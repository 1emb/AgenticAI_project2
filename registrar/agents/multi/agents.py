"""The specialist agents of the registrar multi-agent system.

Four specialists, each with its own LLM loop, system prompt and exclusive set of tools, plus one coordinator
(coordinator.py) that plans and delegates. A specialist is built from the tools the Router already assembled for the
logged-in user, so authorization is unchanged: the user's ID and role are bound inside the tools, and no agent message
can widen them.

    data          reads records, schedules, catalog facts, statistics (everything that is not owned below)
    policy        retrieval (RAG) over the handbook and the course catalog; cites sections
    advising      degree planning (ASP planner): plan_my_degree, advisees
    registration  the only agent that prepares changes: request/cancel add, drop, grade posting. It cannot make
                  them: the Router does, in code, when the user's next message is exactly "yes"

Agents also talk to each other: a specialist may call `consult_agent(agent, request)` to ask a peer, one level deep
(a consulted agent cannot consult further, so there is no recursion). Registration, for example, asks Policy whether a
load limit applies and Advising whether a course fits the plan before it prepares a change. Every consulted answer comes
back as a tool result, so the asking agent's grounding check, and the graded `answer`, include the peer's verified facts.

Grounding is per agent: an agent's reply is only trusted if that agent's own tools (or a consulted peer) produced facts.
A Policy answer with no retrieved section is replaced by a fixed "not covered" sentence, never LLM prose.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from registrar.agents.common import ToolError
from registrar.agents.loop import ToolCall, ToolLoop
from registrar.agents.student.agent import assemble_answer

DATA, POLICY, ADVISING, REGISTRATION = "data", "policy", "advising", "registration"
ALL_AGENTS = (DATA, POLICY, ADVISING, REGISTRATION)
REGISTER_FOR_COURSE = "request_registration_for_course"   # synthetic tool: course -> section -> pending change

OWNED = {
    POLICY: frozenset({"search_policy", "search_catalog"}),
    ADVISING: frozenset({"plan_my_degree", "get_my_advisees", "plan_for_advisee", "check_course_in_my_plan"}),
    REGISTRATION: frozenset({"check_registration", "request_registration", REGISTER_FOR_COURSE, "request_drop",
                             "request_grade", "confirm_change", "cancel_change"}),
}
SHARED = frozenset({"decline_request"})          # every agent can record a refusal
# Read-only lookups registration also needs to do its job: request_registration takes a 5-digit CRN, so the agent must be able
# to find a course's sections itself (small models rarely consult a peer for that). Data keeps these tools too.
READS_FOR = {REGISTRATION: frozenset({"get_course_sections", "get_section", "get_my_registrations"})}
PEERS = {DATA: (), POLICY: (DATA,), ADVISING: (DATA, POLICY), REGISTRATION: (DATA, POLICY, ADVISING)}
DESCRIPTION = {
    DATA: "records and facts: transcript, GPA, registrations, schedules, courses, sections, calendar, statistics",
    POLICY: "handbook rules (grading, load limits, probation, repeats, graduation, privacy) and courses by topic",
    ADVISING: "degree planning: remaining requirements, next-term courses, graduation timeline, advisees",
    REGISTRATION: "changes: add or drop a course, post a grade (prepares the change; the user confirms with 'yes' next turn)",
}
REGISTER_FOR_COURSE_SPEC = {"type": "function", "function": {
    "name": REGISTER_FOR_COURSE,
    "description": "Prepare a registration when the user names a COURSE (e.g. 'CS 5810') and not a CRN: it finds the course's "
                   "section for the term and prepares the change for the user to confirm. If the course has several "
                   "sections it lists them so you can ask which one. Use request_registration only when the user gave a CRN.",
    "parameters": {"type": "object", "properties": {
        "course": {"type": "string", "description": "Course code, e.g. 'CS 5810'."},
        "term": {"type": "string", "description": "Term as the user said it; omit if none was named."}},
        "required": ["course"]}}}
WRITE_TOOLS = frozenset({"request_registration", REGISTER_FOR_COURSE, "request_drop", "request_grade", "confirm_change",
                         "cancel_change"})
# A model that did not change anything must not say it did. Matches completion claims, not offers ("I can register you").
CLAIMS_DONE = re.compile(r"\b(you(?:'re| are| have been| were)(?: now)? (?:registered|enrolled|dropped|withdrawn)"
                         r"|(?:has|have) been (?:registered|dropped|withdrawn|posted|added|changed|enrolled)"
                         r"|successfully (?:registered|dropped|posted|added|withdrawn)"
                         r"|i(?:'ve| have) (?:registered|dropped|posted|added|withdrawn))\b", re.I)
NOTHING_CHANGED = ("I haven't changed anything. Tell me the course (and term) you want to register for, or the change "
                   "you want, and I'll prepare it for you to confirm.")
NOT_COVERED = "The handbook and the course catalog don't cover that."
UNVERIFIED = ("I couldn't retrieve verified information for this request. I can help with your record, schedule, "
              "courses, degree planning, registration, and registrar rules.")
REFUSED = "I can't provide that information."

COMMON = """You are the {title} agent of a university registrar's multi-agent system, working for one logged-in {role}
(the system fixes who that is; never ask for an ID and never act for anyone else). Your specialty: {desc}.
Other agents: {others}.
Rules: every fact must come from one of your tools or from a consulted agent; never answer from memory and never invent
a value. For a request about another person's private record call decline_request (a refusal written only in your
reply is not recorded). If part of a request belongs to another agent, answer only your part. Reply briefly."""

PROMPTS = {
    DATA: ("You only read data and cannot change anything. You do not know the registrar's rules: for what is allowed "
           "(credit limits, probation, repeats, deadlines policy, requirements) do not guess from record tools; say that "
           "rules are answered by the policy agent."),
    POLICY: ("Answer rules only from the passages search_policy returns and cite the section ('Handbook 3.2'); find "
             "courses by subject with search_catalog. List a course only if its returned text is actually about the topic, "
             "and state only what that text says: never add a reason a course is relevant that is not in the text. If "
             "nothing matches, say the handbook and catalog do not cover it. Numbers that decide an outcome come from the passages, never from you. "
             "If a rule depends on the user's own record (their load, standing), consult the data agent."),
    ADVISING: ("plan_my_degree / plan_for_advisee run the course planner. Present its plan term by term, say which terms "
               "are projected, state its assumptions and blockers, and never invent a plan yourself. For facts the planner "
               "does not return, consult the data agent; for a rule, consult the policy agent."),
    REGISTRATION: ("When the user names a course, call request_registration_for_course(course, term): it finds the section "
                   "and prepares the change. If it lists several sections, ask the user which one. Use request_registration "
                   "only when the user gave a 5-digit CRN. request_registration, request_registration_for_course, "
                   "request_drop and request_grade prepare a change and return a pending change with a "
                   "reply_to_user sentence: reply with that sentence. You cannot make the change yourself: the system "
                   "makes it when the user's next message is exactly 'yes' and discards it on 'no'; it handles that "
                   "message itself. If a request returns blockers, explain them; nothing was changed. Never say "
                   "a change was made. You may also consult policy (a rule) or advising (does it fit the plan) first."),
}


@dataclass
class AgentResult:
    agent: str
    question: str
    reply: str
    answer: dict
    calls: list
    steps: int
    stopped_early: bool
    status: str                      # ok | refused | ungrounded | no_source
    consulted: list[str] = field(default_factory=list)


def confirmed_sentence(a: dict) -> str:
    """What the user is told after confirm_change succeeded (same words as Router._confirm_without_model)."""
    course, crn, term = a.get("course"), a.get("crn"), a.get("term")
    return {"register": f"You are registered in {course} (CRN {crn}), {term}.",
            "drop": f"{course} (CRN {crn}) is dropped for {term}; it leaves no record.",
            "withdraw": f"You are withdrawn from {course} (CRN {crn}), {term}; it shows a W.",
            "post_grade": f"Posted {a.get('grade')} for {a.get('student')} in {course} (CRN {crn}), {term}."}.get(a.get("action"), "Done.")


def agents_available(router) -> list[str]:
    """Which specialists this user's role can have, from the tools the Router gave the persona agent."""
    names = {s["function"]["name"] for s in router.agent.loop.tool_specs}
    out = [DATA]
    for a in (POLICY, ADVISING, REGISTRATION):
        if names & OWNED[a]:
            out.append(a)
    return out


def judge(agent: str, calls: list[ToolCall]) -> str:
    """Is this agent's answer backed by its own evidence? Per-agent, so a successful but irrelevant call (a handbook search
    with zero hits) does not count as support, and a lone refusal is a refusal, not a fact."""
    ok = [c for c in calls if c.ok]
    if not ok:
        return "ungrounded"
    real = [c for c in ok if c.name != "decline_request"]
    if not real:
        return "refused"
    if agent == POLICY:
        hit = any(c.name in OWNED[POLICY] and (c.result.get("answer", {}).get("policy_sections")
                                                or c.result.get("answer", {}).get("catalog_matches")) for c in real)
        if not hit:
            return "no_source"
    return "ok"


class AgentRuntime:
    """Builds the specialists for one Router (one logged-in user) and runs them. Registration keeps its conversation
    history across turns, because a change is requested in one turn and confirmed in the next; the read-only agents start
    fresh for every task, so one task cannot leak context into another."""

    def __init__(self, router, client=None, model: str | None = None):
        self.router = router
        src = router.agent.loop
        self.src, self.client, self.model = src, client or src.client, model or src.model
        self.specs = {s["function"]["name"]: s for s in src.tool_specs}
        if {"get_course_sections", "request_registration"} <= set(self.specs):   # student: one step from course to pending change
            self.specs[REGISTER_FOR_COURSE] = REGISTER_FOR_COURSE_SPEC
        self.available = agents_available(router)
        self.trace: list[dict] = []
        self._reg: ToolLoop | None = None

    # ------------------------------------------------------------------------------------------ construction
    def tools_of(self, agent: str) -> list[str]:
        owned_by_others = set().union(*OWNED.values())
        if agent == DATA:
            names = [n for n in self.specs if n not in owned_by_others and n not in SHARED]
        else:
            names = [n for n in self.specs if n in OWNED[agent] or n in READS_FOR.get(agent, ())]
        return names + [n for n in self.specs if n in SHARED]

    def peers_of(self, agent: str) -> list[str]:
        return [p for p in PEERS[agent] if p in self.available]

    def prompt_of(self, agent: str) -> str:
        head = COMMON.format(title=agent.capitalize(), role=self.router.role, desc=DESCRIPTION[agent],
                             others="; ".join(f"{p} ({DESCRIPTION[p]})" for p in self.available if p != agent) or "none")
        base = getattr(self.router, "base_prompt", self.src.messages[0]["content"]) if agent == DATA else ""
        return "\n\n".join(x for x in (head, base, PROMPTS[agent]) if x)

    def _consult_spec(self, agent: str) -> dict | None:
        peers = self.peers_of(agent)
        if not peers:
            return None
        return {"type": "function", "function": {
            "name": "consult_agent",
            "description": "Ask another registrar agent a question and get its verified answer. "
                           + "; ".join(f"{p}: {DESCRIPTION[p]}" for p in peers),
            "parameters": {"type": "object", "properties": {
                "agent": {"type": "string", "enum": peers},
                "request": {"type": "string", "description": "A complete, self-contained question for that agent."}},
                "required": ["agent", "request"]}}}

    def _loop(self, agent: str, depth: int) -> ToolLoop:
        if agent == REGISTRATION and depth == 0 and self._reg is not None:
            return self._reg
        specs = [self.specs[n] for n in self.tools_of(agent)]
        consult = self._consult_spec(agent) if depth == 0 else None   # one level deep: consulted agents cannot consult
        if consult:
            specs.append(consult)

        def dispatch(name: str, args: dict) -> dict:
            if name == "consult_agent":
                return self._consult(agent, args)
            if name == REGISTER_FOR_COURSE:
                return self._register_for_course(args)
            return self.src.dispatch(name, args)

        loop = ToolLoop(self.client, self.model, self.prompt_of(agent), specs, dispatch, max_steps=self.src.max_steps,
                        temperature=self.src.temperature, verbose=self.src.verbose)
        if agent == REGISTRATION and depth == 0:
            self._reg = loop
        return loop

    # ------------------------------------------------------------------------------------------ running
    def run(self, agent: str, question: str, context: str = "", depth: int = 0) -> AgentResult:
        if agent not in self.available:
            raise ToolError(f"There is no {agent!r} agent for this user.")
        loop = self._loop(agent, depth)
        text = question if not context else f"{question}\n\n(Verified facts already retrieved by other agents: {context})"
        r = loop.run(text)
        calls, steps = list(r.calls), r.steps
        if not any(c.ok for c in calls) and not r.stopped_early:
            from registrar.agents.router import GROUNDING_NUDGE
            r2 = loop.run(GROUNDING_NUDGE)
            calls += r2.calls
            steps += r2.steps
            r = r2 if r2.calls else r
        status = judge(agent, calls)
        answer = assemble_answer(calls)
        reply = r.reply
        if agent == REGISTRATION:
            pending = [c for c in calls if c.ok and isinstance(c.result, dict) and "reply_to_user" in c.result]
            if answer.get("changed"):
                reply = confirmed_sentence(answer)            # the system's words, not the model's
            elif pending and self.router.gate.pending:
                reply = pending[-1].result["reply_to_user"]   # the system's own words: nothing is changed yet
            elif not any(c.ok and c.name in WRITE_TOOLS for c in calls) and CLAIMS_DONE.search(reply):
                reply = NOTHING_CHANGED                       # no write tool ran, so a completion claim is false
        res = AgentResult(agent, question, reply, answer, calls, steps, r.stopped_early, status,
                          consulted=[c.arguments.get("agent") for c in calls if c.name == "consult_agent" and isinstance(c.arguments, dict)])
        self.trace.append({"agent": agent, "depth": depth, "question": question, "status": status,
                           "tools": [c.name for c in calls], "consulted": res.consulted})
        return res

    def _register_for_course(self, args: dict) -> dict:
        """course -> section -> pending change, in code, so a small model cannot stop halfway (a live llama3.1:8b run looked
        up the sections, asked 'shall I?', and never prepared the change). Nothing is changed here: the existing
        request_registration only prepares a change that the user confirms next turn."""
        course = (args.get("course") or "").strip()
        term = (args.get("term") or "").strip() or "next term"      # request_registration's own default is the next term
        if not course:
            raise ToolError("request_registration_for_course needs a course code such as 'CS 5810'.")
        found = self.src.dispatch("get_course_sections", {"course": course, "term": term})
        a = found.get("answer", {}) if isinstance(found, dict) else {}
        crns = a.get("crns") or []
        if not crns:
            raise ToolError(f"{a.get('course', course)} is not offered in {a.get('term', term)}.")
        if len(crns) == 1:
            return self.src.dispatch("request_registration", {"crn": crns[0], "term": term})
        return {"answer": {"course": a.get("course", course), "term": a.get("term", term), "sections": a.get("sections", crns)},
                "note": "Several sections are offered. Nothing was changed: ask the user which CRN they want, then call "
                        "request_registration with it."}

    def _consult(self, caller: str, args: dict) -> dict:
        peer, request = args.get("agent"), (args.get("request") or "").strip()
        if peer not in self.peers_of(caller):
            raise ToolError(f"The {caller} agent cannot consult {peer!r}. Choose one of: {', '.join(self.peers_of(caller))}.")
        if not request:
            raise ToolError("consult_agent needs a request.")
        res = self.run(peer, request, depth=1)
        if res.status == "ungrounded":
            raise ToolError(f"The {peer} agent could not verify an answer.")
        if res.status == "no_source":
            return {"answer": {}, "reply": NOT_COVERED, "agent": peer}
        out = {"agent": peer, "reply": res.reply}
        if res.answer.get("allowed") is False:
            out["declined"] = {"reason": res.answer.get("reason"), "target": res.answer.get("target")}
            if res.answer.get("own_answer"):
                out["answer"] = res.answer["own_answer"]
        else:
            out["answer"] = {k: v for k, v in res.answer.items() if k != "allowed"}
        return out


def context_of(results: list[AgentResult], limit: int = 1500) -> str:
    """Facts earlier agents verified, handed to the next agent as context (a shared blackboard, bounded in size)."""
    facts = {r.agent: {k: v for k, v in r.answer.items() if k not in ("allowed",)} for r in results
             if r.status == "ok" and r.answer.get("allowed", True)}
    s = json.dumps(facts, default=str)
    return s if facts and len(s) <= limit else (s[:limit] if facts else "")
