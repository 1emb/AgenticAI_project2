"""The Coordinator: the entry point of the multi-agent system for one logged-in user.

    Coordinator(router, client, model).ask(question) -> MultiResult   (a RouterResult plus .route, .plan, .trace)

Per message:
  1. The Router's confirmation gate runs first, in code: with a change pending, the user's exact "yes" makes it,
     their exact "no" discards it, and any other message gets "answer yes or no" with the preview again. No model
     is called and none can confirm (owner rule, 2026-11-11: exact wording only).
  2. Otherwise the planner splits the message into tasks and assigns each to a specialist (data, policy, advising,
     registration). Tasks run in order; each gets the facts earlier agents verified.
  3. The composer builds one reply.
If planning fails (bad JSON, invalid plan) the message goes to the Router's single persona agent, which behaves exactly as
before, so the multi-agent layer can only add capability, never remove it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from registrar.agents.multi.agents import AgentResult, AgentRuntime, context_of
from registrar.agents.multi.compose import compose
from registrar.agents.multi.planner import Planner, PlanError
from registrar.agents.registration import NO, YES
from registrar.agents.router import RouterResult
from registrar.agents.student.agent import assemble_answer


@dataclass
class MultiResult(RouterResult):
    route: str = "multi"                      # multi | confirm | fallback
    plan: list = field(default_factory=list)  # [{agent, question}]
    trace: list = field(default_factory=list) # one entry per agent run, consulted peers included
    results: list = field(default_factory=list)


class Coordinator:
    def __init__(self, router, client=None, model: str | None = None):
        self.router = router
        self.runtime = AgentRuntime(router, client, model)
        self.planner = Planner(self.runtime.client, self.runtime.model)

    def ask(self, question: str) -> MultiResult:
        r = self.router
        r.gate.new_turn(question)
        confirmed = r._confirm_without_model(question)
        if confirmed is not None:
            return MultiResult(**vars(confirmed), route="confirm")
        self.runtime.trace.clear()
        if r.writer is not None and not r.gate.pending and (YES.match(question) or NO.match(question)):
            # a bare "yes" or "no" with nothing pending: say so, in code, rather than let a model guess what it answers
            return MultiResult(reply="There is no pending change to confirm. Tell me what you would like to do, for "
                                     "example 'register me for CS 5810'.", answer={"allowed": True}, calls=[], steps=0,
                               stopped_early=False, route="confirm")
        pending = next(iter(r.gate.pending.values()), None)
        try:
            tasks = self.planner.plan(question, r.role, self.runtime.available,
                                      pending=f"{pending.action} {pending.detail}" if pending else None)
            route = "multi"
        except PlanError:
            fb = r.ask(question)
            return MultiResult(**vars(fb), route="fallback")
        results: list[AgentResult] = []
        for t in tasks:
            results.append(self.runtime.run(t.agent, t.question, context_of(results)))
        calls = [c for x in results for c in x.calls]
        answer = assemble_answer(calls)
        r._fill_refusal_target(answer, question, calls)
        return MultiResult(reply=compose(results), answer=answer, calls=calls, steps=sum(x.steps for x in results),
                           stopped_early=any(x.stopped_early for x in results), route=route,
                           plan=[{"agent": t.agent, "question": t.question} for t in tasks],
                           trace=list(self.runtime.trace), results=results)
