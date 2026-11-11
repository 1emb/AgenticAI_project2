"""The Professor agent end to end with a scripted fake model (no model server needed)."""
import pytest

from registrar.agents.professor import ProfessorAgent
from registrar.eval.grader import grade

from conftest import PROFESSOR_CASES
from test_student_agent import FakeClient, call

CASES = {c["id"]: c for c in PROFESSOR_CASES}


def run(session, case_id, script, **kw):
    case = CASES[case_id]
    client = FakeClient(script)
    agent = ProfessorAgent(client, session, case["professor"]["university_id"], case["as_of"], model="fake", **kw)
    return case, agent.ask(case["question"]), client


def passes(case, r):
    return grade(case["answer"], r.answer, r.reply, case.get("must_not_mention"), case["intent"]).passed


def tool_messages(client, step=1):
    return [m["content"] for m in client.requests[step]["messages"] if m["role"] == "tool"]


def test_schedule_answer_comes_from_the_tool(session):
    case, r, _ = run(session, "prof-teach_current-001", [[call("get_my_schedule", {"term": "this semester"})], "Here."])
    assert passes(case, r)


def test_week_is_graded_in_order(session):
    case, r, _ = run(session, "prof-teach_week-001", [[call("get_my_week", {"term": "next term"})], "Here."])
    assert passes(case, r)
    day = next(iter(r.answer["by_day"]))
    if len(r.answer["by_day"][day]) > 1:
        r.answer["by_day"][day].reverse()                      # same items, wrong order -> must fail
        assert not passes(case, r)


def test_ta_roster_of_an_assisted_section(session):
    case = CASES["prof-roster-001"]
    assert case["professor"]["rank"] == "ta"
    case, r, _ = run(session, "prof-roster-001", [[call("get_roster", {"crn": "10046"})], "Here is the roster."])
    assert passes(case, r)


def test_refusal_decided_by_the_data_not_the_model(session):
    # "How did Omar Gomez do in CS 4810 in Fall 2025?": the model just asks for the grade; the tool sees the student
    # was never in the user's sections and records the refusal.
    case, r, client = run(session, "prof-access_denied-002", [
        [call("get_student_grade", {"student": "Omar Gomez", "course": "CS 4810", "term": "in Fall 2025"})],
        "I can't share that student's grades."])
    assert passes(case, r) and r.answer["allowed"] is False
    assert not any(case["answer"]["target"]["university_id"] in m for m in tool_messages(client))


def test_colleague_roster_is_refused_with_the_section_as_target(session):
    case, r, _ = run(session, "prof-access_denied-006", [
        [call("get_roster", {"crn": "10120", "instructor": "Ana Mendoza"})], "Rosters are only for your sections."])
    assert passes(case, r) and r.answer["target"] == {"term": "Fall 2026", "crn": "10120"}


def test_partial_colleague_schedule_and_phone(session):
    case, r, client = run(session, "prof-access_partial-001", [
        [call("get_colleague_schedule", {"name": "Camila Ruiz", "term": "in Fall 2026"}, "a"),
         call("decline_request", {"reason": "other_instructor_record", "person": "Camila Ruiz"}, "b")],
        "Camila Ruiz teaches three sections; I can't share phone numbers."])
    assert passes(case, r)
    assert not any(case["answer"]["target"]["university_id"] in m for m in tool_messages(client))


def test_partial_my_section_and_a_student(session):
    case, r, _ = run(session, "prof-access_partial-002", [
        [call("get_my_section", {"crn": "10067"}, "a"),
         call("decline_request", {"reason": "student_record_not_permitted", "person": "801477453"}, "b")],
        "CRN 10067 meets MTWR 14:30 in HH 104. I can't share student records."])
    assert passes(case, r)


@pytest.mark.parametrize("case_id", ["prof-access_allowed-006", "prof-access_allowed-001"])
def test_own_hire_date_and_salary_are_answered_not_refused(session, case_id):
    case, r, _ = run(session, case_id, [[call("get_my_profile", {})], "Here it is."])
    assert passes(case, r)
    case, r, _ = run(session, case_id, [
        [call("decline_request", {"reason": "other_instructor_record", "person": "me"})], "Sorry."])
    assert not passes(case, r)


@pytest.mark.parametrize("case_id", ["prof-access_denied-005", "prof-access_denied-001"])
def test_leaky_reply_fails_even_with_the_right_refusal(session, case_id):
    case = CASES[case_id]
    s = case["slots"]
    person = s.get("t_name") or s.get("o_name")
    script = [[call("decline_request", {"reason": case["answer"]["reason"], "person": person})],
              f"I can't share that, but it's {case['must_not_mention'][0]}."]
    _, r, _ = run(session, case_id, script)
    g = grade(case["answer"], r.answer, r.reply, case["must_not_mention"], case["intent"])
    assert not g.passed and g.leaked


def test_prompt_carries_identity_clock_and_ta_role(session):
    _, _, client = run(session, "prof-teach_current-001", ["ok"])
    system = client.requests[0]["messages"][0]["content"]
    case = CASES["prof-teach_current-001"]
    assert case["professor"]["name"] in system and "2026-11-20" in system and "Fall 2026" in system
    _, _, client = run(session, "prof-roster-001", ["ok"])
    assert "graduate TA" in client.requests[0]["messages"][0]["content"]


def test_winter_break_prompt(session):
    case_id = next(c["id"] for c in PROFESSOR_CASES if c["as_of"].startswith("2026-12-20"))
    _, _, client = run(session, case_id, ["ok"])
    assert "next semester is Spring 2027" in client.requests[0]["messages"][0]["content"]


def test_only_instructors(session):
    with pytest.raises(ValueError):
        ProfessorAgent(FakeClient([]), session, "800002531", model="fake")
