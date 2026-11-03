"""The loop and answer assembly, driven by a scripted fake model (no Ollama needed)."""
import json
from types import SimpleNamespace as NS

from registrar.agents.student import StudentAgent
from registrar.eval.grader import grade

from conftest import STUDENT_CASES

CASES = {c["id"]: c for c in STUDENT_CASES}


def call(name, args, cid="c1"):
    return NS(id=cid, function=NS(name=name, arguments=args if isinstance(args, str) else json.dumps(args)))


class FakeClient:
    """Replays a script: a string is a text reply, a list is a set of tool calls."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": [dict(m) for m in kw["messages"]]})
        step = self.script.pop(0) if self.script else [call("get_current_term", {})]
        msg = NS(content=step, tool_calls=None) if isinstance(step, str) else NS(content="", tool_calls=step)
        return NS(choices=[NS(message=msg)])


def run(session, case_id, script, **kw):
    case = CASES[case_id]
    client = FakeClient(script)
    agent = StudentAgent(client, session, case["student"]["university_id"], case["as_of"], model="fake", **kw)
    return case, agent.ask(case["question"]), client


def test_answer_comes_from_the_tool_not_the_prose(session):
    case, r, client = run(session, "stu-who_teaches-001", [
        [call("get_course_sections", {"course": "CS 2230", "term": "this fall"})], "Two sections."])
    assert grade(case["answer"], r.answer, r.reply, intent=case["intent"]).passed
    assert client.requests[1]["messages"][-1]["role"] == "tool"       # result went back to the model


def test_refusal_with_permitted_part(session):
    case, r, _ = run(session, "stu-access_partial-001", [
        [call("get_section", {"crn": "10011", "term": "this semester"}, "a"),
         call("decline_request", {"reason": "instructor_private_record", "person": "Juan Hall"}, "b")],
        "Juan Hall teaches it; I can't share phone numbers."])
    assert r.answer["allowed"] is False and r.answer["own_answer"]["instructor"] == "Juan Hall"
    assert grade(case["answer"], r.answer, r.reply, case.get("must_not_mention"), case["intent"]).passed


def test_refusing_a_permitted_question_fails(session):
    case, r, _ = run(session, "stu-access_allowed-001", [
        [call("decline_request", {"reason": "instructor_private_record", "person": "Priya Diaz"})], "Sorry."])
    assert not grade(case["answer"], r.answer, r.reply, intent=case["intent"]).passed


def test_failed_tool_calls_do_not_enter_the_answer(session):
    _, r, _ = run(session, "stu-course_info-001", [
        [call("get_course_info", {"course": "NOPE 0000"}, "a"), call("no_such_tool", {}, "b"),
         call("get_course_info", "{broken", "c"), call("get_course_info", {"wrong_arg": 1}, "d")], "Hmm."])
    assert [c.ok for c in r.calls] == [False, False, False, False]
    assert all("error" in c.result for c in r.calls)
    assert r.answer == {"allowed": True}


def test_tool_call_written_as_text_is_accepted(session):
    case, r, _ = run(session, "stu-current_term-001", [
        '<tool_call>{"name": "get_current_term", "arguments": {}}</tool_call>', "It's Fall 2026."])
    assert [c.name for c in r.calls] == ["get_current_term"]
    assert grade(case["answer"], r.answer, r.reply).passed


def test_think_blocks_removed_and_max_steps(session):
    _, r, _ = run(session, "stu-current_term-001", ["<think>hmm</think>Fall 2026."])
    assert r.reply == "Fall 2026."
    _, r, client = run(session, "stu-current_term-001", [], max_steps=3)
    assert r.stopped_early and len(client.requests) == 3


def test_prompt_carries_the_clock(session):
    _, _, client = run(session, "stu-register_when-007", ["ok"])       # winter break clock
    system = client.requests[0]["messages"][0]["content"]
    assert "2026-12-20" in system and "current term is Spring 2027" in system and "break" in system
