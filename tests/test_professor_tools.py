"""Oracle test for the Professor agent, mirroring test_student_tools.py: for every case in
data/testset/professor/cases.jsonl, call the tool a perfect agent would call with the case's own slots, assemble the
answer as the agent does, and grade it. A failure here is a bug in the tools, not in the model.

Known test-set conflict (reported in the README section on the Professor agent): `course_catalog` and the
`access_allowed/prerequisites` scenario both use the question "What are the prerequisites for X?" but expect
different shapes under the same key (records with min_grade vs plain codes). The oracle uses the tool that fits each
case's intent; a live agent can satisfy only one of the two for that wording."""
import json

import pytest

from registrar.agents.calendar import Calendar
from registrar.agents.loop import ToolCall
from registrar.agents.professor.tools import ProfessorTools
from registrar.agents.student.agent import assemble_answer
from registrar.eval.grader import grade

from conftest import ROOT

PROFESSOR_CASES = [json.loads(line) for line in open(ROOT / "data/testset/professor/cases.jsonl")]


def oracle_calls(case: dict) -> list[tuple[str, dict]]:
    s, intent = case["slots"], case["intent"]
    term = {"term": s["term"]} if "term" in s else {}
    simple = {"teach_current": "get_my_sections", "teach_term": "get_my_sections", "teach_week": "get_my_week",
              "teach_load": "get_my_load", "dept_offerings": "get_department_offerings"}
    if intent in simple:
        return [(simple[intent], term)]
    if intent == "teach_day":
        return [("get_my_day", {"day": s["day"], **term})]
    if intent == "section_meeting":
        key = {"crn": s["crn"]} if "crn" in s and "CRN" in case["question"] else {"course": s["course"]}
        return [("get_section_meeting", {**key, **term})]
    if intent == "my_capacity":
        return [("get_my_capacity", {**({"crn": s["crn"]} if "crn" in s and "CRN" in case["question"] else {}),
                                     **term})]
    if intent == "term_dates":
        return [("get_term_date", {"event": s["event"], **term})]
    if intent == "course_catalog":
        return [("get_course_catalog", {"course": s["course"]})]
    if intent in ("course_offered", "who_teaches"):
        return [("get_course_sections", {"course": s["course"], **term})]
    if intent == "taught_history":
        return [("get_taught_history", {"course": s["course"]})]
    if intent == "load_history":
        return [("get_load_history", {})]

    sc = s["scenario"]
    if intent == "access_denied":
        if sc == "student_list":
            return [("decline_request", {"reason": "student_list_not_permitted", "program": s["program_name"]})]
        if sc in ("other_instructor_private", "impersonation_instructor"):
            return [("decline_request", {"reason": "other_instructor_record", "person": s["o_name"]})]
        who = s["t_uid"] if case["id"].endswith(("1", "3", "5", "7", "9")) else s["t_name"]  # test both forms
        return [("decline_request", {"reason": "student_record_not_permitted", "person": who})]
    if intent == "access_allowed":
        if sc == "colleague_schedule":
            return [("get_colleague_sections", {"name": s["o_name"], **term})]
        if sc in ("colleague_email", "colleague_rank"):
            return [("get_colleague", {"name": s["o_name"]})]
        if sc in ("own_hire_date", "own_record"):
            return [("get_my_record", {})]
        if sc == "prerequisites":
            return [("get_prerequisites", {"course": s["course"]})]
    if intent == "access_partial":
        if sc == "colleague_schedule_and_phone":
            return [("get_colleague_sections", {"name": s["o_name"], **term}),
                    ("decline_request", {"reason": "other_instructor_record", "person": s["o_name"]})]
        if sc == "my_section_and_student_program":
            return [("get_section_meeting_one", {"crn": s["crn"], **term}),
                    ("decline_request", {"reason": "student_record_not_permitted", "person": s["t_uid"]})]
    raise AssertionError(f"no oracle for {intent}/{s.get('scenario')}")


def run(tools: ProfessorTools, name: str, args: dict) -> dict:
    if name == "get_section_meeting_one":  # the partial case grades one flat section record
        sec = tools.get_section_meeting(**args)["answer"]["sections"][0]
        return {"answer": sec}
    return getattr(tools, name)(**args)


@pytest.mark.parametrize("case", PROFESSOR_CASES, ids=[c["id"] for c in PROFESSOR_CASES])
def test_tools_reproduce_ground_truth(session, case):
    tools = ProfessorTools(session, case["professor"]["university_id"], Calendar(session, case["as_of"]))
    calls = [ToolCall(n, a, run(tools, n, a), True) for n, a in oracle_calls(case)]
    result = grade(case["answer"], assemble_answer(calls), must_not_mention=case.get("must_not_mention"),
                   intent=case["intent"])
    assert result.passed, result.problems


def test_no_professor_tool_returns_private_fields(session):
    """Run every read tool for one professor and check that no student field or colleague private field appears."""
    case = PROFESSOR_CASES[0]
    tools = ProfessorTools(session, case["professor"]["university_id"], Calendar(session, case["as_of"]))
    from registrar.models import Person
    me = session.get(Person, tools.uid)
    outs = [tools.get_my_sections(), tools.get_my_week(), tools.get_load_history(), tools.get_my_record(),
            tools.get_department_offerings(), tools.get_colleague("Luis Hall"),
            tools.get_colleague_sections("Luis Hall")]
    blob = json.dumps(outs, default=str)
    hall = session.get(Person, tools._colleague("Luis Hall")[0].university_id)
    privates = [v for v in (hall.phone, hall.ssn, str(hall.date_of_birth), me.ssn) if v]  # phone may be empty
    assert len(privates) >= 3
    for private in privates:
        assert private not in blob
