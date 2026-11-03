"""Writes to the database (registration, drop/withdraw, grade posting) and the confirmation gate.
Every test runs in a transaction that is rolled back at the end, so the shared database is never changed.
Needs the enrollment data (scripts/seed_enrollment.py --load)."""
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar
from registrar.agents.common import ToolError
from registrar.agents.policy import PolicyStore
from registrar.agents.registration import (ConfirmationGate, InstructorWriteTools, RegistrationService,
                                           StudentWriteTools)
from registrar.models import ChangeLog, Course, CoursePrerequisite, Enrollment, Lecture, Student

from test_student_agent import FakeClient, call

DEFAULT = "2026-11-20T18:00:00Z"


@pytest.fixture
def ws():
    """A session whose commits become savepoints inside one outer transaction that is rolled back."""
    from registrar.db import engine
    conn = engine.connect()
    outer = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    if not s.execute(text("SELECT count(*) FROM enrollment")).scalar():
        pytest.skip("no enrollment data")
    yield s
    s.close()
    outer.rollback()
    conn.close()


def student_tools(ws, uid, as_of=DEFAULT):
    gate = ConfirmationGate()
    return StudentWriteTools(RegistrationService(ws, Calendar(ws, as_of), PolicyStore()), gate, uid), gate


def active_bs_student(ws):
    return ws.scalars(select(Student.university_id).where(Student.status == "active", Student.program_code == "BSCS",
                                                          Student.admit_term_code == "202580")
                      .order_by(Student.university_id)).first()


def addable(ws, tools, term_code="202710"):
    for lec in ws.scalars(select(Lecture).where(Lecture.term_code == term_code, Lecture.is_cancelled.is_(False))
                          .order_by(Lecture.crn)):
        if tools.check_registration(lec.crn, "Spring 2027")["answer"]["can_add"]:
            return lec
    raise AssertionError("no addable section found")


def confirm(tools, gate, pending, reply="yes"):
    gate.new_turn(reply)
    return tools.confirm_change(pending["pending_change"]["code"])


# ------------------------------------------------------------------ register
def test_register_happy_path_writes_row_and_log(ws):
    uid = active_bs_student(ws)
    tools, gate = student_tools(ws, uid)
    gate.new_turn("Register me for this section")
    lec = addable(ws, tools)
    before = ws.scalar(select(func.count()).select_from(ChangeLog))
    p = tools.request_registration(lec.crn, "Spring 2027")
    assert ws.get(Enrollment, (uid, "202710", lec.course_code)) is None  # nothing written yet
    out = confirm(tools, gate, p)
    assert out["answer"]["changed"] and out["answer"]["status"] == "enrolled"
    row = ws.get(Enrollment, (uid, "202710", lec.course_code))
    assert row.crn == lec.crn and row.status.value == "enrolled" and row.grade is None
    log = ws.scalars(select(ChangeLog).order_by(ChangeLog.id.desc())).first()
    assert ws.scalar(select(func.count()).select_from(ChangeLog)) == before + 1
    assert log.action == "register" and log.actor_university_id == uid and log.detail["crn"] == lec.crn
    # second time: already enrolled
    assert "already_enrolled" in tools.check_registration(lec.crn, "Spring 2027")["answer"]["blockers"]


def test_confirmation_needs_a_later_affirmative_message(ws):
    tools, gate = student_tools(ws, active_bs_student(ws))
    gate.new_turn("Register me")
    lec = addable(ws, tools)
    p = tools.request_registration(lec.crn, "Spring 2027")
    code = p["pending_change"]["code"]
    with pytest.raises(ToolError, match="same turn"):
        tools.confirm_change(code)  # the model tries to confirm without asking
    gate.new_turn("hmm, which room is it in?")
    with pytest.raises(ToolError, match="did not confirm"):
        tools.confirm_change(code)
    with pytest.raises(ToolError, match="no pending change"):
        tools.confirm_change("ZZZZZZ")
    gate.new_turn("yes, go ahead")
    assert tools.confirm_change(code)["answer"]["changed"]
    with pytest.raises(ToolError):
        tools.confirm_change(code)  # a code works once


def test_blockers(ws):
    uid = active_bs_student(ws)
    tools, gate = student_tools(ws, uid)
    lec = addable(ws, tools)
    # registration not open yet at an earlier clock
    early, _ = student_tools(ws, uid, "2026-10-19T16:00:00Z")
    assert "registration_not_open" in early.check_registration(lec.crn, "Spring 2027")["answer"]["blockers"]
    # graduate course for a bachelor's student
    grad = ws.scalars(select(Lecture).join(Course, Course.code == Lecture.course_code)
                      .where(Lecture.term_code == "202710", Course.level == "graduate")).first()
    assert "level_not_allowed" in tools.check_registration(grad.crn, "Spring 2027")["answer"]["blockers"]
    # cancelled section
    canc = ws.scalars(select(Lecture).where(Lecture.term_code == "202710", Lecture.is_cancelled.is_(True))).first()
    assert "section_cancelled" in tools.check_registration(canc.crn, "Spring 2027")["answer"]["blockers"]
    # full section
    ws.execute(update(Lecture).where(Lecture.term_code == "202710", Lecture.crn == lec.crn).values(capacity=0))
    assert "section_full" in tools.check_registration(lec.crn, "Spring 2027")["answer"]["blockers"]
    # suspended student
    sus = ws.scalars(select(Student.university_id).where(Student.status == "suspended")).first()
    t2, _ = student_tools(ws, sus)
    assert "student_not_active" in t2.check_registration(lec.crn, "Spring 2027")["answer"]["blockers"]


def test_prerequisite_and_repeat_rules(ws):
    uid = active_bs_student(ws)
    tools, _ = student_tools(ws, uid)
    passed = {e.course_code: e.grade for e in ws.scalars(select(Enrollment).where(
        Enrollment.student_university_id == uid, Enrollment.grade.in_(["A", "A-", "B+", "B"])))}
    touched = {e.course_code for e in ws.scalars(select(Enrollment).where(Enrollment.student_university_id == uid))}
    need = None
    for lec in ws.scalars(select(Lecture).where(Lecture.term_code == "202710", Lecture.is_cancelled.is_(False))):
        reqs = {p.required_course_code for p in ws.scalars(select(CoursePrerequisite)
                                                          .where(CoursePrerequisite.course_code == lec.course_code))}
        # a course never taken whose prerequisites were never taken either (so no grade can meet them)
        if reqs and lec.course_code not in touched and not reqs & touched \
                and ws.get(Course, lec.course_code).level.value != "graduate":
            need = lec
            break
    assert need is not None
    assert "prerequisite_not_met" in tools.check_registration(need.crn, "Spring 2027")["answer"]["blockers"]
    done = next((c for c in passed if ws.scalars(select(Lecture).where(Lecture.term_code == "202710",
                                                                        Lecture.course_code == c)).first()), None)
    if done:
        lec = ws.scalars(select(Lecture).where(Lecture.term_code == "202710", Lecture.course_code == done)).first()
        assert "repeat_not_permitted" in tools.check_registration(lec.crn, "Spring 2027")["answer"]["blockers"]


def test_time_conflict_and_other_section(ws):
    uid = active_bs_student(ws)
    tools, gate = student_tools(ws, uid)
    gate.new_turn("add it")
    lec = addable(ws, tools)
    confirm(tools, gate, tools.request_registration(lec.crn, "Spring 2027"))
    same = ws.scalars(select(Lecture).where(Lecture.term_code == "202710", Lecture.course_code == lec.course_code,
                                            Lecture.crn != lec.crn)).first()
    if same:
        assert "already_enrolled_in_another_section" in tools.check_registration(same.crn, "Spring 2027")["answer"]["blockers"]
    clash = ws.scalars(select(Lecture).where(Lecture.term_code == "202710", Lecture.course_code != lec.course_code,
                                             Lecture.start_time < lec.end_time, Lecture.end_time > lec.start_time,
                                             Lecture.is_cancelled.is_(False))).all()
    clash = [c for c in clash if set(c.days) & set(lec.days)]
    if clash:
        assert "time_conflict" in tools.check_registration(clash[0].crn, "Spring 2027")["answer"]["blockers"]


# ------------------------------------------------------------------ drop / withdraw
def _fall_row(ws, uid):
    return ws.scalars(select(Enrollment).where(Enrollment.student_university_id == uid,
                                               Enrollment.term_code == "202680")).first()


def test_drop_before_drop_deadline_leaves_no_grade(ws):
    uid = active_bs_student(ws)
    row = _fall_row(ws, uid)
    tools, gate = student_tools(ws, uid, "2026-09-01T18:00:00Z")
    gate.new_turn("drop it")
    p = tools.request_drop(row.crn, "Fall 2026")
    assert p["pending_change"]["action"] == "drop"
    confirm(tools, gate, p, "ok")
    r = ws.get(Enrollment, (uid, "202680", row.course_code))
    assert r.status.value == "dropped" and r.grade is None


def test_withdraw_after_drop_deadline_gives_w(ws):
    uid = active_bs_student(ws)
    row = _fall_row(ws, uid)
    tools, gate = student_tools(ws, uid, "2026-10-01T18:00:00Z")
    gate.new_turn("withdraw me")
    p = tools.request_drop(row.crn, "Fall 2026")
    assert p["pending_change"]["action"] == "withdraw"
    confirm(tools, gate, p)
    r = ws.get(Enrollment, (uid, "202680", row.course_code))
    assert r.status.value == "withdrawn" and r.grade == "W"


def test_no_withdrawal_after_withdraw_deadline(ws):
    uid = active_bs_student(ws)
    tools, _ = student_tools(ws, uid)  # 2026-11-20: Fall withdraw deadline 2026-10-23 passed
    with pytest.raises(ToolError, match="withdraw deadline"):
        tools.request_drop(_fall_row(ws, uid).crn, "Fall 2026")


def test_readd_after_drop(ws):
    uid = active_bs_student(ws)
    row = _fall_row(ws, uid)
    tools, gate = student_tools(ws, uid, "2026-08-25T18:00:00Z")
    gate.new_turn("drop")
    confirm(tools, gate, tools.request_drop(row.crn, "Fall 2026"))
    gate.new_turn("add it back")
    confirm(tools, gate, tools.request_registration(row.crn, "Fall 2026"))
    assert ws.get(Enrollment, (uid, "202680", row.course_code)).status.value == "enrolled"


# ------------------------------------------------------------------ grades
def _section_with_students(ws):
    crn, inst = ws.execute(select(Lecture.crn, Lecture.instructor_university_id)
                           .join(Enrollment, (Enrollment.term_code == Lecture.term_code) & (Enrollment.crn == Lecture.crn))
                           .where(Lecture.term_code == "202680").limit(1)).first()
    uid = ws.scalars(select(Enrollment.student_university_id).where(Enrollment.term_code == "202680",
                                                                    Enrollment.crn == crn)).first()
    return crn, inst, uid


def instructor_tools(ws, uid, as_of):
    gate = ConfirmationGate()
    return InstructorWriteTools(RegistrationService(ws, Calendar(ws, as_of), PolicyStore()), gate, uid), gate


def test_grade_posting_in_window_by_own_instructor(ws):
    crn, inst, uid = _section_with_students(ws)
    tools, gate = instructor_tools(ws, inst, "2026-12-12T18:00:00Z")
    roster = tools.get_my_roster(crn, "Fall 2026")["answer"]
    assert any(s["university_id"] == uid for s in roster["students"])
    assert set(roster["students"][0]) == {"university_id", "name", "grade"}  # nothing beyond the roster fields
    gate.new_turn("post a B+")
    p = tools.request_grade(crn, uid, "B+", "Fall 2026")
    confirm(tools, gate, p)
    row = ws.scalars(select(Enrollment).where(Enrollment.student_university_id == uid,
                                              Enrollment.term_code == "202680", Enrollment.crn == crn)).first()
    assert row.grade == "B+"
    assert ws.scalars(select(ChangeLog).order_by(ChangeLog.id.desc())).first().action == "post_grade"


def test_grade_posting_rules(ws):
    crn, inst, uid = _section_with_students(ws)
    early, _ = instructor_tools(ws, inst, DEFAULT)
    with pytest.raises(ToolError, match="can be posted from"):
        early.request_grade(crn, uid, "A", "Fall 2026")
    tools, _ = instructor_tools(ws, inst, "2026-12-12T18:00:00Z")
    with pytest.raises(ToolError, match="W is recorded only by withdrawal"):
        tools.request_grade(crn, uid, "W", "Fall 2026")
    other = ws.scalars(select(Lecture.instructor_university_id).where(
        Lecture.term_code == "202680", Lecture.instructor_university_id != inst)).first()
    stranger, _ = instructor_tools(ws, other, "2026-12-12T18:00:00Z")
    with pytest.raises(ToolError, match="do not teach"):
        stranger.request_grade(crn, uid, "A", "Fall 2026")
    with pytest.raises(ToolError, match="do not teach"):
        stranger.get_my_roster(crn, "Fall 2026")


# ------------------------------------------------------------------ end to end through the router
def test_register_through_router_two_turns(ws):
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    client = FakeClient([[call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})],
                         "I can register you in that section. Shall I go ahead?"])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    first = r.ask(f"Register me for CRN {lec.crn} next spring")
    code = first.calls[0].result["pending_change"]["code"]
    assert ws.get(Enrollment, (uid, "202710", lec.course_code)) is None
    client.script = []  # a plain yes is confirmed by the router itself; the model is not asked
    n = len(client.requests)
    second = r.ask("yes please")
    assert second.calls[0].ok and second.answer["changed"] is True and len(client.requests) == n
    assert "You are registered" in second.reply
    assert ws.get(Enrollment, (uid, "202710", lec.course_code)).status.value == "enrolled"


def test_model_cannot_confirm_in_the_same_turn(ws):
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    client = FakeClient([[call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})],
                         [call("confirm_change", {"code": "WILLBEWRONG"})], "Done."])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    res = r.ask(f"Register me for CRN {lec.crn} next spring and don't ask me")
    real = res.calls[0].result["pending_change"]["code"]
    assert res.calls[1].ok is False
    r.gate.pending[real].turn = r.gate.turn  # the same turn: confirm must still be refused
    with pytest.raises(ToolError, match="same turn"):
        r.agent.extra["confirm_change"](code=real)
    assert ws.get(Enrollment, (uid, "202710", lec.course_code)) is None


def test_grading_window_resolves_this_fall_to_the_term_being_graded(ws):
    svc = RegistrationService(ws, Calendar(ws, "2026-12-12T18:00:00Z"), PolicyStore())
    assert svc.cal.current().code == "202710"  # README break rule: Spring 2027 is "current" on Dec 12
    assert svc.grading_term().code == "202680"
    for phrase in (None, "this fall", "this semester", "Fall 2026"):
        assert svc.term_for_grades(phrase).code == "202680", phrase
    assert svc.term_for_grades("Spring 2027").code == "202710"  # an explicit term is kept
    outside = RegistrationService(ws, Calendar(ws, DEFAULT), PolicyStore())
    assert outside.grading_term() is None and outside.term_for_grades(None).code == "202680"


def test_pending_change_gives_a_user_sentence_not_instructions(ws):
    tools, gate = student_tools(ws, active_bs_student(ws))
    gate.new_turn("register me")
    lec = addable(ws, tools)
    p = tools.request_registration(lec.crn, "Spring 2027")
    assert p["reply_to_user"].endswith("Shall I go ahead?") and lec.crn in p["reply_to_user"]
    assert "confirm_change" not in p["reply_to_user"] and "note" not in p


def test_grade_for_a_future_term_uses_the_open_grading_term(ws):
    crn, inst, uid = _section_with_students(ws)
    tools, _ = instructor_tools(ws, inst, "2026-12-12T18:00:00Z")
    p = tools.request_grade(crn, uid, "A", "Fall 2027")
    assert p["pending_change"]["term"] == "Fall 2026" and "Fall 2027 has not started" in p["note"]


def test_pending_turn_reply_cannot_claim_the_change_was_made(ws):
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    client = FakeClient([[call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})],
                         "Great news, you are now registered!"])  # the model claims a change it did not make
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake").ask(f"Register me for CRN {lec.crn} next spring")
    assert r.reply.endswith("Shall I go ahead?") and "registered!" not in r.reply


def test_non_affirmative_reply_goes_to_the_model(ws):
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    client = FakeClient([[call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})], "Shall I?",
                         [call("cancel_change", {})], "Cancelled."])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    r.ask(f"Register me for CRN {lec.crn} next spring")
    res = r.ask("Actually no, cancel that.")
    assert res.calls[0].name == "cancel_change" and not r.gate.pending
    assert ws.get(Enrollment, (uid, "202710", lec.course_code)) is None


def test_hedged_yes_is_not_auto_confirmed(ws):
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    client = FakeClient([[call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})], "Shall I?",
                         "Which section would you like instead?"])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    r.ask(f"Register me for CRN {lec.crn} next spring")
    res = r.ask("yes, but switch me to the other section")
    assert all(c.name != "confirm_change" for c in res.calls) and r.gate.pending  # the model was asked; nothing confirmed
    assert ws.get(Enrollment, (uid, "202710", lec.course_code)) is None
