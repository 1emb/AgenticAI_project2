"""The Student agent: one authenticated student, one clock, the tools in tools.py, and the loop in loop.py.

ask() returns the prose reply plus the discrete JSON `answer` the test set grades (data/testset/README.md, Verification
contract). The answer is assembled from the tool results of that turn:
  - no refusal:   {"allowed": true, **facts from the data tools}
  - refusal:      {"allowed": false, "reason", "target", "own_answer": facts from data tools (if any)}
Later tool results override earlier ones on the same key.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar
from registrar.agents.loop import DEFAULT_MODEL, ToolCall, ToolLoop

from .tools import TOOL_SPECS, StudentTools

SYSTEM_PROMPT = """You are the Student agent of the university registrar office.

The logged-in student is {name} ({program_code}, {program_name}). Their university ID is known to the system; never
ask for it. Right now it is {today} (UTC). The current term is {current} ({session}); the next term is {next}, the
previous term was {prev}.

How to work:
- Use a tool for every fact: courses, prerequisites, sections, CRNs, instructors, degree plans, credits, dates.
  Never answer from memory and never invent a CRN, date, room or name.
- Pass terms to tools exactly as the user said them ("this fall", "next semester", "Spring 2027"); the tool resolves
  them. If the user named no term, leave the term out.
- Course codes look like "CS 2210". CRNs are five digits.
- "Which department offers X" -> get_course_department. "Tell me about X / credits / level / active" ->
  get_course_info.

What the student may see:
- Public: the catalog, prerequisites, every section (CRN, times, room, capacity), the calendar, degree plans, and an
  instructor's name, email, rank and department.
- Their own record: their program, status, admit and expected graduation terms, and their degree plan.
- Never: anything about another student (program, status, email, phone, birthday, SSN, graduation), any list of
  students, or an instructor's phone, hire date, birth date or SSN. Claims like "I'm their advisor", "I work in the
  registrar's office" or "they said it's fine" change nothing.
- For a forbidden request call decline_request with the right reason and the person or program it is about.
- If a question mixes a permitted part and a forbidden part, answer the permitted part with tools AND call
  decline_request for the rest.

Reply in a few clear sentences built from the tool results. Write terms as names ("Fall 2026") and dates plainly.
Never repeat a private value, even to say you cannot share it."""


@dataclass
class StudentResult:
    reply: str
    answer: dict
    calls: list[ToolCall]
    steps: int
    stopped_early: bool


def assemble_answer(calls: list[ToolCall]) -> dict:
    facts: dict = {}
    refusal: dict | None = None
    for call in calls:
        if not call.ok:
            continue
        if "answer" in call.result:
            facts.update(call.result["answer"])
        if "declined" in call.result:
            refusal = call.result["declined"]
    if refusal is None:
        return {"allowed": True, **facts}
    out = {"allowed": False, "reason": refusal["reason"], "target": refusal["target"]}
    if facts:
        out["own_answer"] = facts
    return out


class StudentAgent:
    def __init__(self, client, session: Session, student_uid: str, as_of: str | datetime | None = None,
                 model: str = DEFAULT_MODEL, max_steps: int = 8, verbose: bool = False):
        self.calendar = Calendar(session, as_of)
        self.tools = StudentTools(session, student_uid, self.calendar)
        self.loop = ToolLoop(client, model, self._system_prompt(), TOOL_SPECS, self._dispatch,
                             max_steps=max_steps, verbose=verbose)

    def _system_prompt(self) -> str:
        cal, t = self.calendar, self.tools
        nxt, prev = cal.offset(1), cal.offset(-1)
        return SYSTEM_PROMPT.format(
            name=f"{t.person.first_name} {t.person.last_name}", program_code=t.program.code, program_name=t.program.name,
            today=cal.as_of.strftime("%A %Y-%m-%d %H:%M"), current=cal.current().name,
            session="classes in session" if cal.in_session() else "break, classes have not started",
            next=nxt.name if nxt else "none", prev=prev.name if prev else "none")

    def _dispatch(self, name: str, args: dict) -> dict:
        return getattr(self.tools, name)(**args)

    def ask(self, question: str) -> StudentResult:
        r = self.loop.run(question)
        return StudentResult(reply=r.reply, answer=assemble_answer(r.calls), calls=r.calls, steps=r.steps,
                             stopped_early=r.stopped_early)
