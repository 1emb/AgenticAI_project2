
"""Structured execution plans for the registrar orchestrator.

The planner proposes how to handle a request. The existing router remains
responsible for authentication, authorization, and write confirmations.
"""

from dataclasses import dataclass
from typing import Any, Literal

MAX_TASKS = 3

ROLE_CAPABILITIES = {
    "student": frozenset({"academic_record", "policy", "advising"}),
    "instructor": frozenset({"policy", "advising"}),
    "admin": frozenset({"policy"}),
}


class PlanValidationError(ValueError):
    """Raised when an orchestrator plan has an invalid structure."""


@dataclass(frozen=True)
class Task:
    capability: str
    question: str


@dataclass(frozen=True)
class ExecutionPlan:
    action: Literal["delegate", "orchestrate"]
    tasks: tuple[Task, ...] = ()


def validate_plan(data: Any, role: str) -> ExecutionPlan:
    """Validate a proposed plan against the authenticated role."""

    if role not in ROLE_CAPABILITIES:
        raise PlanValidationError(f"Unknown role: {role!r}")

    if not isinstance(data, dict):
        raise PlanValidationError("Plan must be a JSON object.")

    action = data.get("action")

    if action == "delegate":
        if set(data) != {"action"}:
            raise PlanValidationError(
                "Delegation must contain only the action field."
            )
        return ExecutionPlan(action="delegate")

    if action != "orchestrate":
        raise PlanValidationError(
            "Action must be 'delegate' or 'orchestrate'."
        )

    if set(data) != {"action", "tasks"}:
        raise PlanValidationError(
            "Orchestration must contain action and tasks."
        )

    raw_tasks = data["tasks"]

    if not isinstance(raw_tasks, list):
        raise PlanValidationError("Tasks must be a list.")

    if not 1 <= len(raw_tasks) <= MAX_TASKS:
        raise PlanValidationError(
            f"Plan must contain between 1 and {MAX_TASKS} tasks."
        )

    allowed = ROLE_CAPABILITIES[role]
    tasks = []

    for index, raw in enumerate(raw_tasks, start=1):
        if not isinstance(raw, dict):
            raise PlanValidationError(f"Task {index} must be an object.")

        if set(raw) != {"capability", "question"}:
            raise PlanValidationError(
                f"Task {index} must contain capability and question."
            )

        capability = raw["capability"]
        question = raw["question"]

        if not isinstance(capability, str) or capability not in allowed:
            raise PlanValidationError(
                f"Task {index} has an unsupported capability: {capability!r}"
            )

        if not isinstance(question, str) or not question.strip():
            raise PlanValidationError(
                f"Task {index} must have a nonempty question."
            )

        if len(question) > 1000:
            raise PlanValidationError(
                f"Task {index} question exceeds 1000 characters."
            )

        tasks.append(
            Task(capability=capability, question=question.strip())
        )

    return ExecutionPlan(action="orchestrate", tasks=tuple(tasks))
