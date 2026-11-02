"""Oracle test: for every case in data/testset/student/cases.jsonl, call the tool a perfect agent would call with the
case's own slots, assemble the answer exactly as the agent does, and grade it with the contract grader. This proves
the tools, the term resolver, the answer assembly and the grader agree with the ground truth, independently of any
LLM. A failure here is a bug in our code, not in the model."""
import pytest

from registrar.agents.calendar import Calendar
from registrar.agents.loop import ToolCall
from registrar.agents.student.agent import assemble_answer
from registrar.agents.student.tools import StudentTools
from registrar.eval.grader import grade

from conftest import STUDENT_CASES

SECTION_TOOLS = {"course_offered", "lecture_options", "who_teaches"}


def oracle_calls(case: dict, tools: StudentTools) -> list[tuple[str, dict]]:
    s, intent = case["slots"], case["intent"]
    term = {"term": s["term"]} if "term" in s else {}
    if intent == "prerequisites":
        return [("get_prerequisites", {"course": s["course"]})]
    if intent == "course_info":
        return [("get_course_info", {"course": s["course"]})]
    if intent in SECTION_TOOLS:
        return [("get_course_sections", {"course": s["course"], **term})]
    if intent in ("lecture_meeting", "capacity"):
        return [("get_section", {"crn": s["crn"], **term})]
    if intent == "degree_required":
        return [("get_my_required_courses", {})]
    if intent == "degree_credits":
        return [("get_my_credit_requirements", {})]
    if intent == "course_in_plan":
        return [("check_course_in_my_plan", {"course": s["course"]})]
    if intent == "plan_term":
        return [("get_my_plan_for_semester", {"term_number": s["term_number"]})]
    if intent == "my_program":
        return [("get_my_program", {})]
    if intent == "register_when":
        return [("get_registration_window", term)]
    if intent == "term_dates":
        return [("get_term_date", {"event": s["event"], **term})]
    if intent == "current_term":
        return [("get_current_term", {})]

    scenario = s["scenario"]
    who = s.get("t_name") if case["id"].endswith(("1", "3", "5", "7", "9")) else s.get("t_uid")  # test both
    if intent == "access_denied":
        if scenario == "student_list":
            return [("decline_request", {"reason": "student_list_not_permitted", "program": s["program_name"]})]
        if scenario == "instructor_private":
            return [("decline_request", {"reason": "instructor_private_record", "person": s["i_name"]})]
        return [("decline_request", {"reason": "other_student_record", "person": who or s["t_name"]})]
    if intent == "access_allowed":
        if scenario == "instructor_rank":
            return [("get_instructor", {"name": s["i_name"]})]
        if scenario == "prerequisites":
            return [("get_prerequisites", {"course": s["course"]})]
        if scenario == "course_department":
            return [("get_course_department", {"course": s["course"]})]
        return [("get_section", {"crn": s["crn"], **term})]
    if intent == "access_partial":
        if scenario == "teacher_and_phone":
            section = tools.get_section(s["crn"], s.get("term"))["answer"]
            return [("get_section", {"crn": s["crn"], **term}),
                    ("decline_request", {"reason": "instructor_private_record", "person": section["instructor"]})]
        return [("get_my_program", {}),
                ("decline_request", {"reason": "other_student_record", "person": who or s["t_name"]})]
    raise AssertionError(f"no oracle for {intent}")


@pytest.mark.parametrize("case", STUDENT_CASES, ids=[c["id"] for c in STUDENT_CASES])
def test_tools_reproduce_ground_truth(session, case):
    tools = StudentTools(session, case["student"]["university_id"], Calendar(session, case["as_of"]))
    calls = [ToolCall(name, args, getattr(tools, name)(**args), True) for name, args in oracle_calls(case, tools)]
    answer = assemble_answer(calls)
    result = grade(case["answer"], answer, must_not_mention=case.get("must_not_mention"), intent=case["intent"])
    assert result.passed, result.problems
