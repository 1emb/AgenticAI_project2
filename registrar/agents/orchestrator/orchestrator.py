
"""Optional orchestration layer for the registrar system."""

from dataclasses import dataclass

from registrar.agents.orchestrator.composer import compose_response
from registrar.agents.orchestrator.executor import execute_plan
from registrar.agents.orchestrator.planner import Planner, PlanningError


@dataclass
class OrchestratorResult:
    reply: str
    action: str
    result: object


class Orchestrator:
    """Coordinate read-only tasks while preserving the existing router."""

    def __init__(self, router, client, model: str):
        self.router = router
        self.planner = Planner(client, model)

    def ask(
        self,
        question: str,
        *,
        allow_orchestration: bool = False,
    ) -> OrchestratorResult:
        if not allow_orchestration:
            return self._delegate(question)

        try:
            plan = self.planner.plan(question, self.router.role)
        except PlanningError:
            return self._delegate(question)

        if plan.action == "delegate":
            return self._delegate(question)

        result = execute_plan(self.router, plan)

        return OrchestratorResult(
            reply=compose_response(result),
            action="orchestrate",
            result=result,
        )


    def _delegate(self, question: str) -> OrchestratorResult:
        result = self.router.ask(question)

        return OrchestratorResult(
            reply=result.reply,
            action="delegate",
            result=result,
        )
