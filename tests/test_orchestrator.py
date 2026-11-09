
"""Tests for orchestrator execution-plan validation."""

import pytest
from types import SimpleNamespace

from registrar.agents.orchestrator.models import (
    ExecutionPlan,
    PlanValidationError,
    validate_plan,
    Task,
)

from registrar.agents.orchestrator.planner import Planner, PlanningError

from registrar.agents.orchestrator.executor import (
    make_read_only_loop,
    execute_task,
    execute_plan,
    TaskResult,
    PlanResult,
)

from unittest.mock import patch

from registrar.agents.loop import LoopResult, ToolCall


from registrar.agents.orchestrator.composer import compose_response
from registrar.agents.orchestrator.orchestrator import Orchestrator


def test_valid_student_plan():
    plan = validate_plan(
        {
            "action": "orchestrate",
            "tasks": [
                {
                    "capability": "academic_record",
                    "question": "What is my GPA?",
                },
                {
                    "capability": "policy",
                    "question": "What are the probation requirements?",
                },
            ]
        },
        role="student",
    )

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.tasks) == 2
    assert plan.action == "orchestrate"
    assert plan.tasks[0].capability == "academic_record"
    


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"action": "unknown"},
        {"action": "orchestrate"},
        {"action": "orchestrate", "tasks": []},
        {"action": "orchestrate", "tasks": "not a list"},
        {
            "action": "orchestrate",
            "tasks": [{"capability": "policy", "question": ""}],
        },
        {
            "action": "orchestrate",
            "tasks": [
                {
                    "capability": "admin_statistics",
                    "question": "Show grades",
                }
            ],
        },
        {
            "action": "orchestrate",
            "tasks": [{"capability": "policy"}],
        },
        {
            "action": "orchestrate",
            "tasks": [
                {
                    "capability": "policy",
                    "question": "Rules",
                    "extra": 1,
                }
            ],
        },
        {
            "action": "orchestrate",
            "tasks": [
                {"capability": "policy", "question": "Rules"}
            ] * 4,
        },
        {"action": "delegate", "tasks": []},
        {"action": "delegate", "extra": "unexpected"},
    ],
)
def test_invalid_plans_are_rejected(data):
    with pytest.raises(PlanValidationError):
        validate_plan(data, role="student")



def test_unknown_role_is_rejected():
    with pytest.raises(PlanValidationError):
        validate_plan(
            {"tasks": [{"capability": "policy", "question": "Rules"}]},
            role="unknown",
        )


def test_instructor_cannot_request_student_record_capability():
    with pytest.raises(PlanValidationError):
        validate_plan(
            {
                "action": "orchestrate",
                "tasks": [
                    {
                        "capability": "academic_record",
                        "question": "Show student records",
                    }
                ]
            },
            role="instructor",
        )

def test_valid_delegation():
    plan = validate_plan(
        {"action": "delegate"},
        role="student",
    )

    assert plan.action == "delegate"
    assert plan.tasks == ()


def mock_client(content):
    """Return a minimal mock of the existing OpenAI-compatible client."""
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=content)
                        )
                    ]
                )
            )
        )
    )


def test_planner_delegates():
    planner = Planner(
        mock_client('{"action":"delegate"}'),
        model="test-model",
    )

    plan = planner.plan("What is my GPA?", role="student")

    assert plan.action == "delegate"
    assert plan.tasks == ()


def test_planner_orchestrates():
    response = (
        '{"action":"orchestrate","tasks":['
        '{"capability":"academic_record","question":"What is my GPA?"},'
        '{"capability":"advising","question":"What courses should I take?"}'
        ']}'
    )

    planner = Planner(mock_client(response), model="test-model")
    plan = planner.plan(
        "What is my GPA and what courses should I take?",
        role="student",
    )

    assert plan.action == "orchestrate"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].capability == "academic_record"
    assert plan.tasks[1].capability == "advising"


def test_planner_rejects_malformed_json():
    planner = Planner(mock_client('{"action":'), model="test-model")

    with pytest.raises(PlanningError):
        planner.plan("What is my GPA?", role="student")


def test_planner_rejects_unauthorized_capability():
    response = (
        '{"action":"orchestrate","tasks":['
        '{"capability":"academic_record","question":"Show student GPA"}'
        ']}'
    )

    planner = Planner(mock_client(response), model="test-model")

    with pytest.raises(PlanningError):
        planner.plan("Show student GPA", role="instructor")



def test_read_only_loop_excludes_write_tools():
    from types import SimpleNamespace

    class FakeRouter:
        role = "student"
        agent = SimpleNamespace(
            loop=SimpleNamespace(
                client=None,
                model="test-model",
                messages=[{"role": "system", "content": "Test agent"}],
                tool_specs=[
                    {"function": {"name": name, "parameters": {"properties": {}}}}
                    for name in (
                        "get_my_gpa",
                        "get_my_transcript",
                        "get_my_registrations",
                        "decline_request",
                        "request_registration",
                        "confirm_change",
                    )
                ],
                dispatch=lambda name, args: {"called": name},
                max_steps=8,
                temperature=0.0,
                verbose=False,
            )
        )

    loop = make_read_only_loop(FakeRouter(), "academic_record")

    assert "get_my_gpa" in loop.tool_names
    assert "request_registration" not in loop.tool_names
    assert "confirm_change" not in loop.tool_names

    call = loop._run_one("request_registration", {})
    assert call.ok is False



@pytest.mark.parametrize(
    ("capability", "expected"),
    [
        (
            "academic_record",
            {"get_my_transcript", "get_my_gpa", "get_my_registrations"},
        ),
        (
            "policy",
            {"search_policy"},
        ),
        (
            "advising",
            {"plan_my_degree"},
        ),
    ],
)
def test_student_capability_tool_selection(capability, expected):
    from types import SimpleNamespace

    from registrar.agents.orchestrator.executor import READ_ONLY_TOOLS

    all_names = set().union(*READ_ONLY_TOOLS["student"].values())
    all_names.update({
        "decline_request",
        "request_registration",
        "request_drop",
        "confirm_change",
        "cancel_change",
    })

    source = SimpleNamespace(
        client=None,
        model="test-model",
        messages=[{"role": "system", "content": "Test agent"}],
        tool_specs=[
            {"function": {"name": name, "parameters": {"properties": {}}}}
            for name in sorted(all_names)
        ],
        dispatch=lambda name, args: {"called": name},
        max_steps=8,
        temperature=0.0,
        verbose=False,
    )

    router = SimpleNamespace(
        role="student",
        agent=SimpleNamespace(loop=source),
    )

    loop = make_read_only_loop(router, capability)

    assert loop.tool_names == expected | {"decline_request"}
    assert not loop.tool_names.intersection({
        "request_registration",
        "request_drop",
        "confirm_change",
        "cancel_change",
    })



def test_execute_task_assembles_tool_results():
    task = Task(
        capability="academic_record",
        question="What is my GPA?",
    )

    tool_call = ToolCall(
        name="get_my_gpa",
        arguments={},
        result={"answer": {"gpa": 3.5}},
        ok=True,
    )

    fake_result = LoopResult(
        reply="Your GPA is 3.5.",
        calls=[tool_call],
        steps=2,
        stopped_early=False,
    )

    with patch(
        "registrar.agents.orchestrator.executor.make_read_only_loop"
    ) as make_loop:
        make_loop.return_value.run.return_value = fake_result

        result = execute_task(router=object(), task=task)

    assert result.reply == "Your GPA is 3.5."
    assert result.answer == {"allowed": True, "gpa": 3.5}
    assert result.calls == [tool_call]
    assert result.steps == 2
    assert result.stopped_early is False



def test_execute_task_retries_ungrounded_response():
    task = Task(
        capability="academic_record",
        question="What is my GPA?",
    )

    first = LoopResult(
        reply="Your GPA is probably 3.5.",
        calls=[],
        steps=1,
        stopped_early=False,
    )

    tool_call = ToolCall(
        name="get_my_gpa",
        arguments={},
        result={"answer": {"gpa": 3.5}},
        ok=True,
    )

    second = LoopResult(
        reply="Your GPA is 3.5.",
        calls=[tool_call],
        steps=2,
        stopped_early=False,
    )

    with patch(
        "registrar.agents.orchestrator.executor.make_read_only_loop"
    ) as make_loop:
        loop = make_loop.return_value
        loop.run.side_effect = [first, second]

        result = execute_task(router=object(), task=task)

    assert loop.run.call_count == 2
    assert result.reply == "Your GPA is 3.5."
    assert result.answer == {"allowed": True, "gpa": 3.5}
    assert result.calls == [tool_call]
    assert result.steps == 3



def test_execute_task_rejects_ungrounded_response():
    task = Task(
        capability="academic_record",
        question="What is my GPA?",
    )

    ungrounded = LoopResult(
        reply="Your GPA is 4.0.",
        calls=[],
        steps=1,
        stopped_early=False,
    )

    with patch(
        "registrar.agents.orchestrator.executor.make_read_only_loop"
    ) as make_loop:
        loop = make_loop.return_value
        loop.run.side_effect = [ungrounded, ungrounded]

        result = execute_task(router=object(), task=task)

    assert loop.run.call_count == 2
    assert result.reply == (
        "I couldn't retrieve verified information for this request."
    )
    assert result.answer["error"] == "ungrounded_response"
    assert result.calls == []
    assert result.steps == 2


def test_execute_plan_runs_tasks_in_order():
    tasks = (
        Task("academic_record", "What is my GPA?"),
        Task("policy", "What are the probation rules?"),
    )

    plan = ExecutionPlan(
        action="orchestrate",
        tasks=tasks,
    )

    def fake_execute(router, task):
        return TaskResult(
            task=task,
            reply=f"Completed: {task.capability}",
            answer={"allowed": True},
            calls=[],
            steps=1,
            stopped_early=False,
        )

    with patch(
        "registrar.agents.orchestrator.executor.execute_task",
        side_effect=fake_execute,
    ) as execute:
        result = execute_plan(router=SimpleNamespace(role="student"), plan=plan)

    assert execute.call_count == 2
    assert [item.task for item in result.tasks] == list(tasks)
    assert result.steps == 2



def test_execute_plan_rejects_unauthorized_capability():
    plan = ExecutionPlan(
        action="orchestrate",
        tasks=(
            Task(
                capability="academic_record",
                question="Show a student's GPA.",
            ),
        ),
    )

    router = SimpleNamespace(role="instructor")

    with patch(
        "registrar.agents.orchestrator.executor.execute_task"
    ) as execute:
        with pytest.raises(ValueError, match="not permitted"):
            execute_plan(router, plan)

    execute.assert_not_called()



def test_compose_response_combines_tasks():
    tasks = [
        TaskResult(
            task=Task("academic_record", "What is my GPA?"),
            reply="Your GPA is 3.5.",
            answer={
                "allowed": True,                 
                "cumulative_gpa": 3.5,
                "last_term": "Spring 2026",
                "last_term_gpa": 3.4,
                "credits_earned": 49,
                },
            calls=[
                ToolCall(
                    name="get_my_gpa",
                    arguments={},
                    result={"answer": {"gpa": 3.5}},
                    ok=True,
                )
            ],
            steps=1,
            stopped_early=False,
        ),
        TaskResult(
            task=Task("policy", "What are the probation rules?"),
            reply="Students must maintain satisfactory academic standing.",
            answer={
                "allowed": True, 
                "policy_sections": ["4.1", "4.2"],
                },
            calls=[
                ToolCall(
                    name="search_policy",
                    arguments={},
                    result={"answer": {"policy": "Academic standing rules"}},
                    ok=True,
                )
            ],
            steps=1,
            stopped_early=False,
        ),
    ]

    result = PlanResult(
        tasks=tasks,
        calls=[call for task in tasks for call in task.calls],
        steps=2,
    )

    response = compose_response(result)

    assert "What is my GPA?" in response
    assert "Cumulative GPA: 3.50" in response
    assert "Spring 2026 GPA: 3.40" in response
    assert "Credits earned: 49" in response
    assert "What are the probation rules?" in response
    assert "Students must maintain" in response



def test_orchestrator_delegates_simple_request():
    router = SimpleNamespace(
        role="student",
        ask=lambda question: SimpleNamespace(
            reply="Your GPA is 3.5.",
            answer={"allowed": True, "gpa": 3.5},
        ),
    )

    with patch(
        "registrar.agents.orchestrator.orchestrator.Planner"
    ) as planner_class:
        planner_class.return_value.plan.return_value = ExecutionPlan(
            action="delegate"
        )

        orchestrator = Orchestrator(
            router=router,
            client=None,
            model="test-model",
        )

        result = orchestrator.ask("What is my GPA?")

    assert result.action == "delegate"
    assert result.reply == "Your GPA is 3.5."



def test_orchestrator_executes_multi_task_plan():
    router = SimpleNamespace(role="student")

    plan = ExecutionPlan(
        action="orchestrate",
        tasks=(
            Task("academic_record", "What is my GPA?"),
            Task("advising", "What courses should I take?"),
        ),
    )

    expected = PlanResult(tasks=[], calls=[], steps=2)

    with (
        patch(
            "registrar.agents.orchestrator.orchestrator.Planner"
        ) as planner_class,
        patch(
            "registrar.agents.orchestrator.orchestrator.execute_plan",
            return_value=expected,
        ) as execute,
        patch(
            "registrar.agents.orchestrator.orchestrator.compose_response",
            return_value="Your GPA and recommended courses.",
        ) as compose,
    ):
        planner_class.return_value.plan.return_value = plan

        orchestrator = Orchestrator(
            router=router,
            client=None,
            model="test-model",
        )

        result = orchestrator.ask(
            "What is my GPA and what courses should I take?",
            allow_orchestration=True,
        )

    execute.assert_called_once_with(router, plan)
    compose.assert_called_once_with(expected)
    assert result.action == "orchestrate"
    assert result.reply == "Your GPA and recommended courses."


def test_orchestrator_falls_back_when_planning_fails():
    router = SimpleNamespace(
        role="student",
        ask=lambda question: SimpleNamespace(
            reply="Your GPA is 3.5.",
            answer={"allowed": True, "gpa": 3.5},
        ),
    )

    with patch(
        "registrar.agents.orchestrator.orchestrator.Planner"
    ) as planner_class:
        planner_class.return_value.plan.side_effect = PlanningError(
            "Invalid plan"
        )

        orchestrator = Orchestrator(
            router=router,
            client=None,
            model="test-model",
        )

        result = orchestrator.ask("What is my GPA?", allow_orchestration=True,)

    assert result.action == "delegate"
    assert result.reply == "Your GPA is 3.5."



def test_orchestrator_defaults_to_existing_router():
    from unittest.mock import Mock

    router = SimpleNamespace(
        role="student",
        ask=Mock(
            return_value=SimpleNamespace(
                reply="Handled by existing router.",
                answer={"allowed": True},
            )
        ),
    )

    with patch(
        "registrar.agents.orchestrator.orchestrator.Planner"
    ) as planner_class:
        orchestrator = Orchestrator(
            router=router,
            client=None,
            model="test-model",
        )

        result = orchestrator.ask("Register me for a course.")

    planner_class.return_value.plan.assert_not_called()
    router.ask.assert_called_once_with("Register me for a course.")
    assert result.action == "delegate"



def test_compose_response_advising_uses_verified_data():
    """Advising responses include verified planning details."""
    task = TaskResult(
        task=Task("advising", "What courses should I take next semester?"),
        reply="You should take CS 4110.",
        answer={
            "allowed": True,
            "status": "target_infeasible",
            "earliest_graduation_term": "Fall 2028",
            "must_take_next_term": [],
            "remaining_required": ["CS 4910"],
            "credits_earned": 64,
            "credits_required": 120,
            "cumulative_gpa": 3.07,
            "standing": "good",
            "next_term": "Spring 2027",
            "next_term_courses": [
                "CS 4110",
                "CS 4720",
                "ECON 2120",
                "HIST 2110",
                "PHIL 2110",
                "PSY 1110",
            ],
        },
        calls=[
            ToolCall(
                name="plan_my_degree",
                arguments={},
                result={"answer": {"status": "target_infeasible"}},
                ok=True,
            )
        ],
        steps=1,
        stopped_early=False,
    )

    result = PlanResult(
        tasks=[task],
        calls=task.calls,
        steps=1,
    )

    response = compose_response(result)

    assert "Recommended courses for Spring 2027:" in response
    assert "CS 4110" in response
    assert "PSY 1110" in response
    assert "Earliest projected graduation: Fall 2028" in response
    assert "Remaining required courses: CS 4910" in response
    assert "Degree requires 120 credits." in response
    assert "target feasibility issue" in response

    # The composer must not misrepresent in-progress credits as earned.
    assert "64 credits earned" not in response



def test_compose_response_preserves_policy_references():
    """Policy responses include the sections returned by the policy tool."""
    task = TaskResult(
        task=Task("policy", "What are the academic probation rules?"),
        reply="Students may be placed on academic probation.",
        answer={
            "allowed": True,
            "policy_sections": ["4.1", "4.2", "3.2"],
        },
        calls=[
            ToolCall(
                name="search_policy",
                arguments={},
                result={
                    "answer": {
                        "policy_sections": ["4.1", "4.2", "3.2"]
                    }
                },
                ok=True,
            )
        ],
        steps=1,
        stopped_early=False,
    )

    result = PlanResult(
        tasks=[task],
        calls=task.calls,
        steps=1,
    )

    response = compose_response(result)

    assert "Students may be placed on academic probation." in response
    assert "Policy references: 4.1, 4.2, 3.2" in response
