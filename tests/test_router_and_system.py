"""End-to-end tests of the whole system with a scripted fake model (no LLM needed): the router picks the agent by
role, the shared tools (advising, records, policy) are wired in, and permissions hold across agents.
Needs the enrollment data (scripts/seed_enrollment.py --load)."""
import json

import pytest
from sqlalchemy import select, text

from registrar.agents.router import RoleError, Router, roles_of
from registrar.models import AdvisorAssignment, Instructor, Person, Student

from test_student_agent import FakeClient, call

AS_OF = "2026-11-20T18:00:00Z"


@pytest.fixture(scope="module")
def db(session):
    if not session.execute(text("SELECT count(*) FROM enrollment")).scalar():
        pytest.skip("no enrollment data; run scripts/seed_enrollment.py --load")
    return session


def tool_names(router):
    return {t["function"]["name"] for t in router.agent.loop.tool_specs}


def active_student(db, program):
    return db.scalars(select(Student.university_id).where(Student.status == "active", Student.program_code == program,
                                                          Student.admit_term_code == "202510")
                      .order_by(Student.university_id)).first()


# ------------------------------------------------------------------ roles
def test_roles_come_from_the_database(db):
    uid = active_student(db, "BSCS")
    assert roles_of(db, uid) == {"student"}
    assert roles_of(db, "900000001") == {"admin"}
    with pytest.raises(RoleError):
        Router(FakeClient([]), db, uid, role="admin", as_of=AS_OF, model="fake")
    with pytest.raises(RoleError):
        Router(FakeClient([]), db, "123456789", as_of=AS_OF, model="fake")


def test_two_role_person_must_choose(db):
    ta = db.scalars(select(Instructor.university_id).join(Student, Student.university_id == Instructor.university_id)).first()
    assert ta is not None
    with pytest.raises(RoleError):
        Router(FakeClient([]), db, ta, as_of=AS_OF, model="fake")
    assert Router(FakeClient([]), db, ta, role="student", as_of=AS_OF, model="fake").role == "student"


def test_each_role_gets_its_own_tools(db):
    stu = Router(FakeClient([]), db, active_student(db, "BSCS"), as_of=AS_OF, model="fake")
    adv = db.scalars(select(AdvisorAssignment.advisor_university_id)).first()
    prof = Router(FakeClient([]), db, adv, role="instructor", as_of=AS_OF, model="fake")
    adm = Router(FakeClient([]), db, "900000001", as_of=AS_OF, model="fake")
    assert {"plan_my_degree", "get_my_transcript", "get_my_gpa", "search_policy"} <= tool_names(stu)
    assert "plan_for_advisee" not in tool_names(stu) and "at_risk_students" not in tool_names(stu)
    assert {"get_my_advisees", "plan_for_advisee", "search_policy", "get_my_sections"} <= tool_names(prof)
    assert "plan_my_degree" not in tool_names(prof) and "get_student_record" not in tool_names(prof)
    assert {"at_risk_students", "graduation_candidates", "search_policy"} <= tool_names(adm)


# ------------------------------------------------------------------ student: advising + records + policy
def test_student_plans_degree_through_the_router(db):
    uid = active_student(db, "BSENG")
    r = Router(FakeClient([[call("plan_my_degree", {})], "Here is your plan."]), db, uid, as_of=AS_OF, model="fake")
    res = r.ask("What should I take next semester to graduate as early as possible?")
    a = res.answer
    assert a["allowed"] is True and a["status"] in ("ok", "target_infeasible", "requirements_met")
    assert a["next_term"] == "Spring 2027" and a["next_term_courses"]
    assert a["earliest_graduation_term"] is None or a["earliest_graduation_term"].split()[0] in ("Fall", "Spring")


def test_student_gpa_matches_sql(db):
    uid = active_student(db, "BSCS")
    sql = db.execute(text("""SELECT round(sum(gs.points*c.credit_hours)/sum(c.credit_hours), 2) FROM enrollment e
        JOIN grade_scale gs ON gs.letter=e.grade AND gs.points IS NOT NULL JOIN course c ON c.code=e.course_code
        WHERE e.student_university_id=:u"""), {"u": uid}).scalar()
    r = Router(FakeClient([[call("get_my_gpa", {})], "Your GPA."]), db, uid, as_of=AS_OF, model="fake")
    assert r.ask("What's my GPA?").answer["cumulative_gpa"] == pytest.approx(float(sql), abs=0.005)


def test_transcript_is_own_record_only(db):
    uid = active_student(db, "BSCS")
    r = Router(FakeClient([[call("get_my_transcript", {})], "Your courses."]), db, uid, as_of=AS_OF, model="fake")
    a = r.ask("What classes have I taken?").answer
    n = db.execute(text("SELECT count(*) FROM enrollment WHERE student_university_id=:u AND grade IS NOT NULL "
                        "AND grade <> 'W'"), {"u": uid}).scalar()
    assert len(a["completed"]) == n and a["in_progress"]  # active students are enrolled in Fall 2026


def test_policy_search_returns_cited_section(db):
    r = Router(FakeClient([[call("search_policy", {"question": "How many credits can I take on probation?"})],
                           "Handbook 3.2: 13 credits."]), db, active_student(db, "BSCS"), as_of=AS_OF, model="fake")
    res = r.ask("How many credits can I take on probation?")
    assert res.answer["policy_sections"][0] == "3.2"


# ------------------------------------------------------------------ instructor: advisees only
def test_advisor_plans_for_own_advisee_only(db):
    adv, stu = db.execute(select(AdvisorAssignment.advisor_university_id, AdvisorAssignment.student_university_id)
                          .join(Student, Student.university_id == AdvisorAssignment.student_university_id)
                          .where(Student.status == "active").order_by(AdvisorAssignment.student_university_id)).first()
    other = db.scalars(select(AdvisorAssignment.student_university_id)
                       .where(AdvisorAssignment.advisor_university_id != adv)).first()
    ok = Router(FakeClient([[call("plan_for_advisee", {"student": stu})], "Plan."]), db, adv, role="instructor",
                as_of=AS_OF, model="fake").ask("Plan my advisee's next term.")
    assert ok.answer["allowed"] is True and "next_term_courses" in ok.answer
    bad = Router(FakeClient([[call("plan_for_advisee", {"student": other})], "I can't."]), db, adv, role="instructor",
                 as_of=AS_OF, model="fake").ask("Plan this student's next term; I'm their advisor.")
    assert bad.calls[0].ok is False and "not one of your assigned advisees" in bad.calls[0].result["error"]
    assert "next_term_courses" not in bad.answer


def test_professor_testset_case_through_router(db):
    from test_professor_tools import PROFESSOR_CASES
    from registrar.eval.grader import grade
    case = next(c for c in PROFESSOR_CASES if c["intent"] == "teach_current")
    r = Router(FakeClient([[call("get_my_sections", {"term": case["slots"]["term"]})], "Your sections."]), db,
               case["professor"]["university_id"], role="instructor", as_of=case["as_of"], model="fake")
    res = r.ask(case["question"])
    assert grade(case["answer"], res.answer, res.reply, intent=case["intent"]).passed


# ------------------------------------------------------------------ admin
def test_admin_case_through_router(db):
    from test_admin_tools import ADMIN_CASES
    from registrar.eval.grader import grade
    case = next(c for c in ADMIN_CASES if c["intent"] == "at_risk_students"
                and c["slots"]["criterion"] == "at_risk_of_suspension")
    r = Router(FakeClient([[call("at_risk_students", {"criterion": "at_risk_of_suspension"})], "These students."]),
               db, "900000001", as_of=case["as_of"], model="fake")
    res = r.ask(case["question"])
    assert grade(case["answer"], res.answer, res.reply, intent=case["intent"]).passed


def test_no_tool_result_leaks_private_fields(db):
    """Run the student-facing extra tools and check no SSN, birth date or phone of anyone appears."""
    uid = active_student(db, "BSCS")
    from registrar.agents.advising import AdvisingTools
    from registrar.agents.calendar import Calendar
    from registrar.agents.records import StudentRecordTools
    cal = Calendar(db, AS_OF)
    blob = json.dumps([StudentRecordTools(db, cal, uid).get_my_transcript(), StudentRecordTools(db, cal, uid).get_my_gpa(),
                       AdvisingTools(db, cal, uid, "student").plan_my_degree()], default=str)
    p = db.get(Person, uid)
    for v in (p.ssn, str(p.date_of_birth), p.phone):
        if v:
            assert v not in blob


def test_undeclared_arguments_are_dropped_not_fatal(db):
    """A small model adds a 'course' argument to a no-argument tool; the call must still succeed."""
    uid = active_student(db, "BSCS")
    r = Router(FakeClient([[call("get_my_gpa", {"course": "CS 2210"})], "Your GPA."]), db, uid, as_of=AS_OF,
               model="fake").ask("What's my GPA?")
    assert r.calls[0].ok and r.calls[0].result["ignored_arguments"] == ["course"]
    assert r.answer["cumulative_gpa"] is not None


def test_grounding_check_retries_an_ungrounded_reply(db):
    """The model refuses in prose without decline_request; the router asks once more and the refusal is recorded."""
    from test_student_agent import CASES
    case = next(c for c in CASES.values() if c["intent"] == "access_denied" and c["slots"]["scenario"] != "student_list")
    client = FakeClient(["I can't share that.",
                         [call("decline_request", {"reason": "other_student_record", "person": case["slots"]["t_uid"]})],
                         "Sorry, I can't share another student's information."])
    r = Router(client, db, case["student"]["university_id"], as_of=case["as_of"], model="fake").ask(case["question"])
    assert r.grounding_retry and r.answer["allowed"] is False
    assert r.answer["target"] == case["answer"]["target"]


def test_grounding_check_does_not_fire_after_a_tool_answer(db):
    uid = active_student(db, "BSCS")
    client = FakeClient([[call("get_my_gpa", {})], "Your GPA."])
    r = Router(client, db, uid, as_of=AS_OF, model="fake").ask("What's my GPA?")
    assert not r.grounding_retry and len(client.requests) == 2


def test_refusal_target_is_resolved_from_the_question(db):
    """The model declines but leaves out the person; the router finds the ID in the question."""
    from test_professor_tools import PROFESSOR_CASES
    case = next(c for c in PROFESSOR_CASES if c["id"] == "prof-access_denied-002")
    client = FakeClient([[call("decline_request", {"reason": "student_record_not_permitted"})], "I can't share that."])
    r = Router(client, db, case["professor"]["university_id"], role="instructor", as_of=case["as_of"],
               model="fake").ask(case["question"])
    assert r.answer["target"] == case["answer"]["target"]
