"""The Administrator agent: a registrar administrator, one clock, the tools in tools.py and the shared loop."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar
from registrar.agents.loop import DEFAULT_MODEL, ToolCall, ToolLoop
from registrar.agents.student.agent import assemble_answer

from .tools import TOOL_SPECS, AdminTools

SYSTEM_PROMPT = """You are the Administrator agent of the university registrar office, working for a registrar
administrator. Right now it is {today} (UTC). The current term is {current}; the previous term was {prev}.

How to work:
- Use a tool for every number. Never compute or estimate statistics yourself.
- Pick the scope from the question, using only the values the user wrote: a course code the user named ->
  scope_kind course; a subject code the user named ("<SUBJ> courses") -> scope_kind subject; a level ("lower-division",
  "upper-division", "graduate") -> scope_kind level; a program or major the user named -> the program argument with
  that program's code (bachelor's in Computer Science BSCS, in Engineering BSENG; master's MSCS, MSENG).
  Nothing named -> scope_kind all. Put the term in `term`, exactly as the user said it; omit it for "overall" or
  "across all terms". Never put a course, subject or program the user did not name.
- "On the brink of dismissal / about to be suspended" -> at_risk_students with criterion at_risk_of_suspension.
  "On probation" -> criterion probation. "Who will graduate" -> graduation_candidates.
- For rules (what probation means, credit limits), call search_policy and cite the handbook section.
- Pass a filter (program, entry type, scope) only when the user names it. "Which students ..." with no program
  means all students: leave program out. Never add a filter the user did not ask for.
- "Which sections ..." -> grading_extremes with unit section; "which courses ..." -> unit course. "Highest / worst
  F or DFW rate" -> direction highest; "lowest average GPA" -> metric mean_gpa, direction lowest.
- "Pass rate / DFW rate" -> dfw_rate. "GPA below X" -> at_risk_students with criterion gpa_below and threshold X.
- Call the one tool that answers the question, once. Do not call extra tools "to be thorough": their results
  replace the answer.

Reply in a few clear sentences built from the tool results."""


@dataclass
class AdminResult:
    reply: str
    answer: dict
    calls: list[ToolCall]
    steps: int
    stopped_early: bool


class AdminAgent:
    def __init__(self, client, session: Session, as_of: str | datetime | None = None, model: str = DEFAULT_MODEL,
                 max_steps: int = 8, verbose: bool = False, extra_tools=None):
        self.calendar = Calendar(session, as_of)
        self.tools = AdminTools(session, self.calendar)
        specs, self.extra = list(TOOL_SPECS), {}
        for spec, fn in (extra_tools or []):
            specs.append(spec)
            self.extra[spec["function"]["name"]] = fn
        prev = self.calendar.offset(-1)
        prompt = SYSTEM_PROMPT.format(today=self.calendar.as_of.strftime("%A %Y-%m-%d %H:%M"),
                                      current=self.calendar.current().name, prev=prev.name if prev else "none")
        self.loop = ToolLoop(client, model, prompt, specs, self._dispatch, max_steps=max_steps, verbose=verbose)

    def _dispatch(self, name: str, args: dict) -> dict:
        if name in self.extra:
            return self.extra[name](**args)
        return getattr(self.tools, name)(**args)

    def ask(self, question: str) -> AdminResult:
        r = self.loop.run(question)
        return AdminResult(reply=r.reply, answer=assemble_answer(r.calls), calls=r.calls, steps=r.steps,
                           stopped_early=r.stopped_early)
