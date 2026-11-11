"""Oracle test for data/testset/professor/: for every case and every wording, call the tools a faithful agent would
call for the question as worded, assemble the answer as the agent does, and grade it with the contract grader. Terms
are passed only when the wording names one, so the bare-CRN rules are exercised too. A failure is a bug in our code,
except the wordings in registrar/eval/known_issues.py, which the test set itself makes impossible."""
import re

import pytest

from registrar.agents.answer import assemble_answer
from registrar.agents.calendar import Calendar
from registrar.agents.loop import ToolCall
from registrar.agents.professor.tools import ProfessorTools
from registrar.eval.grader import grade
from registrar.eval.known_issues import professor_unanswerable

from conftest import PROFESSOR_CASES

STUDENT_SCENARIOS = {"student_program", "student_status", "student_contact", "student_personal", "student_graduation",
                     "impersonation_student", "my_student_gpa", "my_student_phone"}
GRADE_SCENARIOS = {"not_my_student_grade", "my_student_other_grade"}
TERMISH = re.compile(r"\b(semester|term|fall|spring|summer)\b|\b\d{4}\b", re.I)


def unanswerable(case: dict, question: str) -> bool:
    return professor_unanswerable(case, question) is not None


def named_term(case: dict, q: str) -> dict:
    s, ql = case["slots"], q.lower()
    if "term" in s and s["term"].lower() in ql:
        return {"term": s["term"]}
    if s.get("term_name") and s["term_name"].lower() in ql:
        return {"term": s["term_name"]}
    return {}


def oracle_calls(case: dict, q: str) -> list[tuple[str, dict]]:
    s, intent, term = case["slots"], case["intent"], named_term(case, q)
    by_crn = bool(s.get("crn")) and s["crn"] in q
    section = {"crn": s["crn"], **term} if by_crn else ({"course": s["course"], **term} if s.get("course") else term)
    student = s.get("t_uid") if s.get("t_uid", "~") in q else s.get("t_name")
    simple = {"teach_current": "get_my_schedule", "teach_term": "get_my_schedule", "teach_week": "get_my_week",
              "teach_load": "get_my_teaching_load", "dept_offerings": "get_department_offerings",
              "dfw_rate": "get_dfw_rates", "grades_submitted": "get_grade_submission_status",
              "my_tas": "get_my_tas", "ta_sections": "get_my_ta_assignments"}
    none = {"load_history": "get_my_load_history", "taught_all": "get_my_teaching_history",
            "students_taught": "get_students_taught", "incompletes": "get_incompletes"}
    if intent in simple:
        return [(simple[intent], term)]
    if intent in none:
        return [(none[intent], {})]
    if intent == "teach_day":
        return [("get_my_day", {"day": s["day"], **term})]
    if intent == "section_meeting":
        return [("get_my_section", section)]
    if intent == "my_capacity":
        return [("get_my_capacity", {"crn": s["crn"], **term} if by_crn else term)]
    if intent == "enrollment_count":
        return [("get_enrollment_counts", {"crn": s["crn"], **term} if by_crn else term)]
    if intent == "term_dates":
        return [("get_term_date", {"event": s["event"], **term})]
    if intent == "course_catalog":
        return [("get_course_catalog", {"course": s["course"]})]
    if intent in ("course_offered", "who_teaches"):
        return [("get_course_offerings", {"course": s["course"], **term})]
    if intent == "taught_history":
        return [("get_my_course_history", {"course": s["course"]})]
    if intent == "course_trend":
        return [("get_course_trend", {"course": s["course"]})]
    if intent == "roster":
        return [("get_roster", section)]
    if intent == "withdrawals":
        return [("get_withdrawals", section)]
    if intent == "section_grades":
        return [("get_section_grades", section)]
    if intent == "grade_distribution":
        return [("get_grade_distribution", section)]
    if intent == "student_in_section":
        return [("check_student_in_section", {"student": student, **section})]
    if intent == "student_grade":
        return [("get_student_grade", {"student": student, **section})]
    if intent == "student_info":
        return [("get_student_info", {"student": student})]

    scenario = s["scenario"]
    if intent == "access_denied":
        if scenario in STUDENT_SCENARIOS:
            return [("decline_request", {"reason": "student_record_not_permitted", "person": student})]
        if scenario in GRADE_SCENARIOS:          # the tool sees the section is not the user's and refuses
            return [("get_student_grade", {"student": student, "course": s["t_course"], "term": s["t_term"]})]
        if scenario == "colleague_roster":
            return [("get_roster", {**section, "instructor": s["o_name"]})]
        if scenario == "student_list":
            return [("decline_request", {"reason": "student_list_not_permitted", "program": s["program_name"]})]
        return [("decline_request", {"reason": "other_instructor_record", "person": s["o_name"]})]
    if intent == "access_allowed":
        if scenario == "colleague_schedule":
            return [("get_colleague_schedule", {"name": s["o_name"], **term})]
        if scenario in ("colleague_email", "colleague_rank"):
            return [("get_instructor", {"name": s["o_name"]})]
        if scenario in ("own_hire_date", "own_record", "own_salary"):
            return [("get_my_profile", {})]
        return [("get_course_catalog", {"course": s["course"]})]
    if scenario == "colleague_schedule_and_phone":
        return [("get_colleague_schedule", {"name": s["o_name"], **term}),
                ("decline_request", {"reason": "other_instructor_record", "person": s["o_name"]})]
    return [("get_my_section", section),
            ("decline_request", {"reason": "student_record_not_permitted", "person": student})]


def run_oracle(session, case: dict, question: str):
    from registrar.agents.common import ToolError
    tools = ProfessorTools(session, case["professor"]["university_id"], Calendar(session, case["as_of"]))
    calls = []
    for n, a in oracle_calls(case, question):
        try:
            calls.append(ToolCall(n, a, getattr(tools, n)(**a), True))
        except ToolError as e:                       # what the agent would see: an error, no answer
            calls.append(ToolCall(n, a, {"error": str(e)}, False))
    return grade(case["answer"], assemble_answer(calls), must_not_mention=case.get("must_not_mention"),
                 intent=case["intent"])


@pytest.mark.parametrize("case", PROFESSOR_CASES, ids=[c["id"] for c in PROFESSOR_CASES])
def test_tools_reproduce_ground_truth(session, case):
    if unanswerable(case, case["question"]):
        pytest.xfail(professor_unanswerable(case, case["question"]))
    result = run_oracle(session, case, case["question"])
    assert result.passed, result.problems


def test_every_paraphrase_too(session):
    failures = []
    for c in PROFESSOR_CASES:
        for p in c["paraphrases"]:
            if not unanswerable(c, p):
                r = run_oracle(session, c, p)
                if not r.passed:
                    failures.append((c["id"], p, r.problems[:2]))
    assert failures == []


def test_unanswerable_list_is_still_needed(session):
    """If the test set is fixed, these start passing; then shrink registrar/eval/known_issues.py."""
    for c in PROFESSOR_CASES:
        for q in [c["question"], *c["paraphrases"]]:
            if unanswerable(c, q):
                assert not run_oracle(session, c, q).passed, (c["id"], q)
