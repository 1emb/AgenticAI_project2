
"""Restricted tool execution for orchestrated registrar requests.

Uses the tools and dispatch function of an authenticated router's agent.
Only explicitly approved read-only tools are exposed.
"""

from registrar.agents.loop import ToolLoop

from dataclasses import dataclass

from registrar.agents.orchestrator.models import (
    Task, 
    ExecutionPlan, 
    ROLE_CAPABILITIES
    )
from registrar.agents.student.agent import assemble_answer

READ_ONLY_TOOLS = {
    "student": {
        "academic_record": frozenset({
            "get_my_transcript",
            "get_my_gpa",
            "get_my_registrations",
        }),
        "policy": frozenset({
            "search_policy",
        }),
        "advising": frozenset({
            "plan_my_degree",
        }),
    },
}


def make_read_only_loop(router, capability: str) -> ToolLoop:
    """Create a restricted loop using an authenticated router's tools."""

    allowed = READ_ONLY_TOOLS.get(router.role, {}).get(capability)

    if allowed is None:
        raise ValueError(
            f"Unsupported capability {capability!r} for role {router.role!r}."
        )

    source = router.agent.loop

    specs = [
        spec for spec in source.tool_specs
        if spec["function"]["name"] in allowed | {"decline_request"}
    ]

    available = {spec["function"]["name"] for spec in specs}
    missing = allowed - available

    if missing:
        raise ValueError(
            f"Missing tools for {capability!r}: {sorted(missing)}"
        )

    def restricted_dispatch(name: str, args: dict) -> dict:
        if name not in available:
            raise ValueError(f"Tool {name!r} is not permitted.")

        return source.dispatch(name, args)

    return ToolLoop(
        client=source.client,
        model=source.model,
        system_prompt=source.messages[0]["content"],
        tool_specs=specs,
        dispatch=restricted_dispatch,
        max_steps=source.max_steps,
        temperature=source.temperature,
        verbose=source.verbose,
    )


@dataclass
class TaskResult:
    task: Task
    reply: str
    answer: dict
    calls: list
    steps: int
    stopped_early: bool


def execute_task(router, task: Task) -> TaskResult:
    """Execute one read-only task using the authenticated agent's tools."""

    loop = make_read_only_loop(router, task.capability)
    result = loop.run(task.question)

    calls = list(result.calls)
    steps = result.steps

    # Match the existing router's grounding behavior.
    if not any(call.ok for call in calls) and not result.stopped_early:
        from registrar.agents.router import GROUNDING_NUDGE

        retry = loop.run(GROUNDING_NUDGE)
        calls.extend(retry.calls)
        steps += retry.steps

        if retry.calls:
            result = retry

    
    # Never return an unsupported LLM response as a factual answer.
    if not any(call.ok for call in calls):
        return TaskResult(
            task=task,
            reply="I couldn't retrieve verified information for this request.",
            answer={"allowed": True, "error": "ungrounded_response"},
            calls=calls,
            steps=steps,
            stopped_early=result.stopped_early,
        )

    answer = assemble_answer(calls)


    return TaskResult(
        task=task,
        reply=result.reply,
        answer=answer,
        calls=calls,
        steps=steps,
        stopped_early=result.stopped_early,
    )



@dataclass
class PlanResult:
    tasks: list[TaskResult]
    calls: list
    steps: int


def execute_plan(router, plan: ExecutionPlan) -> PlanResult:
    """Execute validated, read-only tasks in their planned order."""

    if plan.action != "orchestrate":
        raise ValueError("Only orchestration plans can be executed.")

    if not plan.tasks:
        raise ValueError("An orchestration plan must contain tasks.")

    
    allowed = ROLE_CAPABILITIES.get(router.role)

    if allowed is None:
        raise ValueError(f"Unsupported role: {router.role!r}")

    for task in plan.tasks:
        if task.capability not in allowed:
            raise ValueError(
                f"Capability {task.capability!r} is not permitted "
                f"for role {router.role!r}."
            )


    results = []
    calls = []
    steps = 0

    for task in plan.tasks:
        result = execute_task(router, task)
        results.append(result)
        calls.extend(result.calls)
        steps += result.steps

    return PlanResult(
        tasks=results,
        calls=calls,
        steps=steps,
    )
