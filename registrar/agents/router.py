"""The Router: one entry point for every user of the registrar system.

The role comes from the login (here: the caller), never from the conversation. The router checks it against the
database (a student row, an instructor row, or the administrator list in data/policy/roles.json), builds the persona
agent for that role, and adds the shared tools:

    student     -> StudentAgent    + get_my_transcript, get_my_gpa, plan_my_degree (Advising/ASP), search_policy
    instructor  -> ProfessorAgent  + get_my_advisees, plan_for_advisee (Advising/ASP), search_policy
    admin       -> AdminAgent      + search_policy

A person with two roles (a graduate TA is a student and an instructor) must log in as one of them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from registrar.agents.advising import ADVISOR_SPECS, STUDENT_ADVISING_SPECS, AdvisingTools
from registrar.agents.loop import DEFAULT_MODEL
from registrar.agents.policy import SEARCH_POLICY_SPEC, PolicyStore
from registrar.agents.records import RECORD_SPECS, StudentRecordTools
from registrar.agents.student.agent import assemble_answer
from registrar.models import Instructor, Student

ROLES_FILE = Path(__file__).resolve().parents[2] / "data/policy/roles.json"

STUDENT_ADDENDUM = """

Added capabilities:
- The student's own academic record: get_my_transcript (courses, grades, W, in progress) and get_my_gpa.
- Advising: plan_my_degree runs the course planner for the student's remaining terms (next term's courses, earliest
  graduation, required courses left). Present its plan term by term, say which terms are projected, and state its
  assumptions. Never invent a plan yourself.
- Rules (probation, course load, repeats, withdrawals, graduation): search_policy, and cite the handbook section.
- Refusals: you MUST call decline_request for anything about another person's record (even if you only want to say
  no); a refusal written only in your reply is not recorded and counts as answering. Answer the permitted part of a
  mixed question with tools too."""

PROFESSOR_ADDENDUM = """

Added capabilities:
- Advising your assigned advisees only: get_my_advisees lists them; plan_for_advisee plans an advisee's remaining
  terms. For any student who is not on that list, the student-record rules above still apply (decline_request).
- Rules: search_policy, and cite the handbook section."""


class RoleError(ValueError):
    pass


def roles_of(session: Session, uid: str) -> set[str]:
    roles = set()
    if session.get(Student, uid) is not None:
        roles.add("student")
    if session.get(Instructor, uid) is not None:
        roles.add("instructor")
    admins = json.loads(ROLES_FILE.read_text()).get("registrar_admins", []) if ROLES_FILE.exists() else []
    if uid in admins:
        roles.add("admin")
    return roles


class Router:
    def __init__(self, client, session: Session, user_uid: str, role: str | None = None,
                 as_of: str | datetime | None = None, model: str = DEFAULT_MODEL, verbose: bool = False,
                 max_steps: int = 8):
        have = roles_of(session, user_uid)
        if not have:
            raise RoleError(f"{user_uid} has no registrar role.")
        if role is None:
            if len(have) > 1:
                raise RoleError(f"{user_uid} has several roles ({', '.join(sorted(have))}); log in as one of them.")
            role = next(iter(have))
        if role not in have:
            raise RoleError(f"{user_uid} is not a {role}.")
        self.role, self.uid = role, user_uid
        policy = PolicyStore()
        search = (SEARCH_POLICY_SPEC, policy.search_policy)
        kw = dict(as_of=as_of, model=model, verbose=verbose, max_steps=max_steps)
        if role == "student":
            from registrar.agents.student import StudentAgent
            from registrar.agents.calendar import Calendar
            cal = Calendar(session, as_of)
            rec, adv = StudentRecordTools(session, cal, user_uid), AdvisingTools(session, cal, user_uid, "student", policy)
            extra = [(s, getattr(rec, s["function"]["name"])) for s in RECORD_SPECS] + \
                    [(s, getattr(adv, s["function"]["name"])) for s in STUDENT_ADVISING_SPECS] + [search]
            self.agent = StudentAgent(client, session, user_uid, extra_tools=extra, **kw)
            self.agent.loop.messages[0]["content"] += STUDENT_ADDENDUM
        elif role == "instructor":
            from registrar.agents.professor import ProfessorAgent
            from registrar.agents.calendar import Calendar
            adv = AdvisingTools(session, Calendar(session, as_of), user_uid, "instructor", policy)
            extra = [(s, getattr(adv, s["function"]["name"])) for s in ADVISOR_SPECS] + [search]
            self.agent = ProfessorAgent(client, session, user_uid, extra_tools=extra, **kw)
            self.agent.loop.messages[0]["content"] += PROFESSOR_ADDENDUM
        else:
            from registrar.agents.admin import AdminAgent
            self.agent = AdminAgent(client, session, extra_tools=[search], **kw)

    def ask(self, question: str) -> "RouterResult":
        """Ask the persona agent. Grounding check: a turn that ends without one successful tool call (the model
        answered or refused from its own words) gets one corrective message, and the answer is assembled from
        both attempts. Every fact must come from a tool, and a refusal only counts when decline_request records it."""
        r = self.agent.ask(question)
        calls, steps, retried = list(r.calls), r.steps, False
        if not any(c.ok for c in r.calls) and not r.stopped_early:
            r2 = self.agent.ask(GROUNDING_NUDGE)
            calls += r2.calls
            steps += r2.steps
            retried = True
            r = r2 if r2.calls else r
        answer = assemble_answer(calls)
        self._fill_refusal_target(answer, question, calls)
        return RouterResult(reply=r.reply, answer=answer, calls=calls, steps=steps,
                            stopped_early=r.stopped_early, grounding_retry=retried)

    def _fill_refusal_target(self, answer: dict, question: str, calls) -> None:
        """A refusal whose person the model left out or misspelled is resolved from the question itself: a 9-digit
        ID, else a capitalized full name. The target is for the audit and grading record and is never shown to the
        model; the user's own ID is never a target."""
        target = answer.get("target")
        if answer.get("allowed") is not False or not isinstance(target, dict) or "university_id" not in target \
                or target["university_id"] is not None:
            return
        tools = getattr(self.agent, "tools", None)
        if tools is None or not hasattr(tools, "_person_uid"):
            return
        reason = answer.get("reason", "")
        instructor = reason in ("instructor_private_record", "other_instructor_record")
        ids = [d for d in re.findall(r"\b\d{9}\b", question) if d != self.uid]
        names = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", question)
        for cand in ids + names:
            try:
                uid = tools._person_uid(cand, instructor=instructor)
            except Exception:  # noqa: BLE001 - the user's own record, or not resolvable
                uid = None
            if uid:
                target["university_id"] = uid
                return


GROUNDING_NUDGE = ("(System check, not from the user.) Your last reply used no tool result, so it cannot be shown "
                   "to the user. Answer the user's previous question again: call the tool that provides the facts, "
                   "or, if the question asks about another person's private record, call decline_request. Then reply "
                   "briefly.")


@dataclass
class RouterResult:
    reply: str
    answer: dict
    calls: list
    steps: int
    stopped_early: bool
    grounding_retry: bool = False
