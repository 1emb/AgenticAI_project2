"""Writes to the database (registration, drop/withdraw, grade posting) and the confirmation gate.
Every test runs in a transaction that is rolled back at the end, so the shared database is never changed.
Runs on main's enrollment table (key: term, CRN, student; a drop keeps the row with status `dropped`)."""
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar
from registrar.agents.common import ToolError
from registrar.agents.policy import PolicyStore
from registrar.agents.registration import (ConfirmationGate, InstructorWriteTools, RegistrationService,
                                           StudentWriteTools)
from registrar.models import ChangeLog, Course, CoursePrerequisite, Enrollment, Lecture, Student, TransferCredit

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


def enr(ws, uid, term_code, crn):
    """The student's row in a section, read from the database again."""
    return ws.scalars(select(Enrollment).where(Enrollment.term_code == term_code, Enrollment.crn == crn,
                                               Enrollment.student_university_id == uid)
                      .execution_options(populate_existing=True)).first()


def set_clock(tools, as_of):
    """Move a test clock forward between two turns, as time passing in an open chat would."""
    from registrar.agents.calendar import parse_as_of
    tools.svc.cal.as_of = parse_as_of(as_of)
    tools.svc.cal.today = tools.svc.cal.as_of.date()


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
    assert enr(ws, uid, "202710", lec.crn) is None  # nothing written yet
    out = confirm(tools, gate, p)
    assert out["answer"]["changed"] and out["answer"]["status"] == "enrolled"
    row = enr(ws, uid, "202710", lec.crn)
    assert row.course_code == lec.course_code and row.status.value == "enrolled" and row.grade is None
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
    with pytest.raises(ToolError, match="next message"):
        tools.confirm_change(code)  # confirming without asking
    with pytest.raises(ToolError, match="no pending change"):
        tools.confirm_change("ZZZZZZ")
    # only the exact word confirms (owner, 2026-11-11): none of these writes anything
    for text_ in ("hmm, which room is it in?", "yes, go ahead", "yes later", "yes?", "yes maybe",
                  "yes unless it costs more", "yes, but switch me to the other section", "yes, cancel that", "ok",
                  "sure", "y"):
        gate.new_turn(text_)
        with pytest.raises(ToolError, match="not exactly 'yes'"):
            tools.confirm_change(code)
        assert enr(ws, tools.uid, "202710", lec.crn) is None, text_
    gate.new_turn(" Yes. ")
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
    touched |= set(ws.scalars(select(TransferCredit.course_code).where(TransferCredit.student_university_id == uid)))
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
    return ws.scalars(select(Enrollment).where(Enrollment.student_university_id == uid, Enrollment.status == "enrolled",
                                               Enrollment.term_code == "202680").order_by(Enrollment.crn)).first()


def test_drop_before_drop_deadline_leaves_no_grade(ws):
    uid = active_bs_student(ws)
    row = _fall_row(ws, uid)
    tools, gate = student_tools(ws, uid, "2026-09-01T18:00:00Z")
    gate.new_turn("drop it")
    p = tools.request_drop(row.crn, "Fall 2026")
    assert p["pending_change"]["action"] == "drop"
    crn = row.crn
    seats = ws.scalar(select(func.count()).select_from(Enrollment).where(
        Enrollment.term_code == "202680", Enrollment.crn == crn, Enrollment.status == "enrolled"))
    out = confirm(tools, gate, p)
    assert out["answer"]["action"] == "drop"
    r = enr(ws, uid, "202680", crn)
    assert r.status.value == "dropped" and r.grade is None  # the row stays, marked dropped
    assert ws.scalars(select(ChangeLog).order_by(ChangeLog.id.desc())).first().action == "drop"
    # a dropped row holds no seat and is on no record
    assert ws.scalar(select(func.count()).select_from(Enrollment).where(
        Enrollment.term_code == "202680", Enrollment.crn == crn, Enrollment.status == "enrolled")) == seats - 1
    assert crn not in [x["crn"] for x in tools.get_my_registrations("Fall 2026")["answer"]["registered"]]
    from registrar.agents.records import StudentRecordTools
    rec = StudentRecordTools(ws, tools.svc.cal, uid).get_my_transcript()["answer"]
    assert r.course_code not in rec["in_progress"] and r.course_code not in [w["course"] for w in rec["withdrawn"]]
    from registrar.agents.professor.tools import ProfessorTools
    prof = ProfessorTools(ws, ws.get(Lecture, ("202680", crn)).instructor_university_id, tools.svc.cal)
    assert prof._seats("202680", crn) == seats - 1 and prof._enrollment("202680", crn, uid) is None
    assert uid not in [p_.university_id for _, p_, _ in prof._rows("202680", crn)]


def test_withdraw_after_drop_deadline_gives_w(ws):
    uid = active_bs_student(ws)
    row = _fall_row(ws, uid)
    tools, gate = student_tools(ws, uid, "2026-10-01T18:00:00Z")
    gate.new_turn("withdraw me")
    p = tools.request_drop(row.crn, "Fall 2026")
    assert p["pending_change"]["action"] == "withdraw"
    confirm(tools, gate, p)
    r = enr(ws, uid, "202680", row.crn)
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
    crn = row.crn
    assert enr(ws, uid, "202680", crn).status.value == "dropped"
    gate.new_turn("add it back")
    confirm(tools, gate, tools.request_registration(crn, "Fall 2026"))
    assert enr(ws, uid, "202680", crn).status.value == "enrolled"  # the dropped row comes back


# ------------------------------------------------------------------ grades
def _section_with_students(ws):
    crn, inst = ws.execute(select(Lecture.crn, Lecture.instructor_university_id)
                           .join(Enrollment, (Enrollment.term_code == Lecture.term_code) & (Enrollment.crn == Lecture.crn))
                           .where(Lecture.term_code == "202680", Enrollment.status == "enrolled")
                           .order_by(Lecture.crn).limit(1)).first()
    uid = ws.scalars(select(Enrollment.student_university_id).where(
        Enrollment.term_code == "202680", Enrollment.crn == crn, Enrollment.status == "enrolled")
        .order_by(Enrollment.student_university_id)).first()
    return crn, inst, uid


def instructor_tools(ws, uid, as_of):
    gate = ConfirmationGate()
    return InstructorWriteTools(RegistrationService(ws, Calendar(ws, as_of), PolicyStore()), gate, uid), gate


def test_grade_posting_in_window_by_own_instructor(ws):
    crn, inst, uid = _section_with_students(ws)
    tools, gate = instructor_tools(ws, inst, "2026-12-12T18:00:00Z")
    gate.new_turn("post a B+")
    p = tools.request_grade(crn, uid, "B+", "Fall 2026")
    assert enr(ws, uid, "202680", crn).grade is None  # nothing written yet
    confirm(tools, gate, p)
    row = enr(ws, uid, "202680", crn)
    assert row.grade == "B+" and row.status.value == "completed"  # a graded row is `completed` on this table
    log = ws.scalars(select(ChangeLog).order_by(ChangeLog.id.desc())).first()
    assert log.action == "post_grade" and log.detail["replaces"] is None
    # changing the grade inside the window: the preview names the grade it replaces, and the log keeps it
    gate.new_turn("make it an A")
    p = tools.request_grade(crn, uid, "A", "Fall 2026")
    assert p["pending_change"]["replaces"] == "B+" and "replacing B+" in p["reply_to_user"]
    confirm(tools, gate, p)
    assert enr(ws, uid, "202680", crn).grade == "A"
    assert ws.scalars(select(ChangeLog).order_by(ChangeLog.id.desc())).first().detail["replaces"] == "B+"


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
    assert first.reply.endswith("Please answer yes or no.")
    assert enr(ws, uid, "202710", lec.crn) is None
    client.script = []  # the exact yes is confirmed by the router itself; the model is not asked
    n = len(client.requests)
    second = r.ask("yes")
    assert second.calls[0].ok and second.answer["changed"] is True and len(client.requests) == n
    assert "You are registered" in second.reply
    assert enr(ws, uid, "202710", lec.crn).status.value == "enrolled"


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
    assert res.calls[1].ok is False and "no tool named" in res.calls[1].result["error"]  # the model has no confirm tool
    assert "confirm_change" not in r.agent.extra
    with pytest.raises(ToolError, match="next message"):  # and the gate refuses a confirmation in the request's own turn
        r.writer.confirm_change(real)
    assert enr(ws, uid, "202710", lec.crn) is None


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
    assert p["reply_to_user"].endswith("Shall I go ahead? Please answer yes or no.") and lec.crn in p["reply_to_user"]
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
    assert r.reply.endswith("Please answer yes or no.") and "registered!" not in r.reply


def test_while_a_change_waits_only_yes_or_no_is_taken(ws):
    """Any other message gets the fixed sentence and the preview again; the model is not asked and nothing is written."""
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    client = FakeClient([[call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})], "Shall I?"])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    first = r.ask(f"Register me for CRN {lec.crn} next spring")
    n = len(client.requests)
    for text_ in ("yes please", "yes, but switch me to the other section", "Actually no, cancel that.", "ok",
                  "what time is it at?", "yes later"):
        res = r.ask(text_)
        assert res.reply.startswith("A change is waiting for your answer, and nothing has been changed yet.")
        assert "I can only take yes or no right now." in res.reply and res.reply.endswith(first.reply)
        assert res.answer["changed"] is False and res.calls == [] and len(client.requests) == n, text_
        assert r.gate.pending and enr(ws, uid, "202710", lec.crn) is None, text_
    assert r.ask("yes").answer["changed"] is True and len(client.requests) == n
    assert enr(ws, uid, "202710", lec.crn).status.value == "enrolled"


def test_exact_no_discards_the_pending_change_without_the_model(ws):
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    client = FakeClient([[call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})], "Shall I?"])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    r.ask(f"Register me for CRN {lec.crn} next spring")
    n = len(client.requests)
    res = r.ask("No.")
    assert res.reply == "Nothing was changed." and not r.gate.pending and len(client.requests) == n
    assert enr(ws, uid, "202710", lec.crn) is None


# ------------------------------------------------------------------ the time of the yes decides (owner, 2026-11-11)
def test_drop_that_became_a_withdrawal_is_asked_again(ws):
    uid = active_bs_student(ws)
    crn = _fall_row(ws, uid).crn
    tools, gate = student_tools(ws, uid, "2026-09-04T23:59:00Z")  # the last day to drop
    gate.new_turn("drop it without a transcript record")
    p = tools.request_drop(crn, "Fall 2026")
    assert p["pending_change"]["action"] == "drop" and p["pending_change"]["result"] == "removed, no record"
    set_clock(tools, "2026-09-05T00:01:00Z")  # two minutes later the drop deadline has passed
    logs = ws.scalar(select(func.count()).select_from(ChangeLog))
    again = confirm(tools, gate, p)
    assert again["answer"] == {"changed": False, "needs_confirmation": True}
    assert again["pending_change"]["action"] == "withdraw" and "grade W" in again["reply_to_user"]
    assert again["reply_to_user"].endswith("Please answer yes or no.")
    assert enr(ws, uid, "202680", crn).status.value == "enrolled"  # nothing written
    assert ws.scalar(select(func.count()).select_from(ChangeLog)) == logs
    with pytest.raises(ToolError, match="no pending change"):  # the old code is spent
        tools.confirm_change(p["pending_change"]["code"])
    with pytest.raises(ToolError, match="next message"):  # the new one needs its own, later yes
        tools.confirm_change(again["pending_change"]["code"])
    out = confirm(tools, gate, again)
    assert out["answer"]["changed"] and out["answer"]["action"] == "withdraw"
    row = enr(ws, uid, "202680", crn)
    assert row.status.value == "withdrawn" and row.grade == "W"
    log = ws.scalars(select(ChangeLog).order_by(ChangeLog.id.desc())).first()
    assert log.action == "withdraw" and log.detail["action"] == "withdraw"  # the log says what was written


def test_section_moved_after_the_preview_is_asked_again(ws):
    uid = active_bs_student(ws)
    tools, gate = student_tools(ws, uid)
    gate.new_turn("register me")
    lec = addable(ws, tools)
    p = tools.request_registration(lec.crn, "Spring 2027")
    ws.execute(update(Lecture).where(Lecture.term_code == "202710", Lecture.crn == lec.crn).values(room="ZZ 999"))
    ws.commit()  # someone else's committed change (a savepoint here; the fixture still rolls everything back)
    again = confirm(tools, gate, p)
    assert again["answer"]["changed"] is False and "ZZ 999" in again["reply_to_user"]
    assert enr(ws, uid, "202710", lec.crn) is None
    assert confirm(tools, gate, again)["answer"]["changed"]


def test_rules_are_checked_again_at_the_yes(ws):
    uid = active_bs_student(ws)
    tools, gate = student_tools(ws, uid)
    gate.new_turn("register me")
    lec = addable(ws, tools)
    # suspended after the preview, by a statement the session's cached student row does not see
    p = tools.request_registration(lec.crn, "Spring 2027")
    ws.execute(text("UPDATE student SET status = 'suspended' WHERE university_id = :u"), {"u": uid})
    ws.commit()
    with pytest.raises(ToolError, match="student_not_active"):
        confirm(tools, gate, p)
    assert enr(ws, uid, "202710", lec.crn) is None
    ws.execute(text("UPDATE student SET status = 'active' WHERE university_id = :u"), {"u": uid})
    ws.commit()
    # the add deadline passes between the preview and the yes
    gate.new_turn("register me")
    p = tools.request_registration(lec.crn, "Spring 2027")
    set_clock(tools, "2027-01-23T00:01:00Z")
    with pytest.raises(ToolError, match="add_deadline_passed"):
        confirm(tools, gate, p)
    assert enr(ws, uid, "202710", lec.crn) is None


def test_a_blocked_new_request_discards_the_old_pending_change(ws):
    uid = active_bs_student(ws)
    tools, gate = student_tools(ws, uid)
    gate.new_turn("register me")
    lec = addable(ws, tools)
    p = tools.request_registration(lec.crn, "Spring 2027")
    canc = ws.scalars(select(Lecture).where(Lecture.term_code == "202710", Lecture.is_cancelled.is_(True))).first()
    gate.new_turn("actually that other one instead")
    assert tools.request_registration(canc.crn, "Spring 2027")["answer"]["can_add"] is False
    assert not gate.pending
    with pytest.raises(ToolError, match="no pending change"):
        confirm(tools, gate, p)
    assert enr(ws, uid, "202710", lec.crn) is None


def test_real_clock_is_read_again_and_a_test_clock_is_not(ws):
    live = Calendar(ws)
    assert live.live
    stale = live.as_of
    live.refresh()
    assert live.as_of >= stale
    fixed = Calendar(ws, DEFAULT)
    fixed.refresh()
    assert not fixed.live and fixed.as_of.isoformat() == "2026-11-20T18:00:00+00:00"


# ------------------------------------------------------------------ the multi-agent coordinator on the real router
def _plan(agent, question):
    import json
    return json.dumps({"tasks": [{"agent": agent, "question": question}]})


def test_coordinator_writes_only_on_the_exact_yes(ws):
    """Mason's coordinator in front of the real Router and database: the registration specialist prepares the change,
    a hedged yes is answered in code and writes nothing, the exact yes is confirmed in code with no model call."""
    from registrar.agents.multi import Coordinator
    from registrar.agents.multi.agents import REGISTRATION
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    ask = f"Register me for CRN {lec.crn} next spring"
    client = FakeClient([_plan(REGISTRATION, ask), [call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})],
                         "Shall I?"])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    co = Coordinator(r)
    assert "confirm_change" not in co.runtime.tools_of(REGISTRATION)  # no specialist can confirm
    assert {"request_registration", "request_drop", "cancel_change"} <= set(co.runtime.tools_of(REGISTRATION))
    first = co.ask(ask)
    assert first.route == "multi" and first.reply.endswith("Please answer yes or no.") and r.gate.pending
    n = len(client.requests)
    hedged = co.ask("yes later")  # not the exact word: answered in code, no planner and no specialist
    assert hedged.route == "confirm" and hedged.answer["changed"] is False and len(client.requests) == n
    assert "I can only take yes or no right now." in hedged.reply and hedged.reply.endswith(first.reply)
    assert enr(ws, uid, "202710", lec.crn) is None and r.gate.pending
    done = co.ask("yes")
    assert done.route == "confirm" and done.answer["changed"] is True and len(client.requests) == n
    assert enr(ws, uid, "202710", lec.crn).status.value == "enrolled"
    assert "no pending change" in co.ask("yes").reply and len(client.requests) == n  # nothing left to confirm


def test_coordinator_exact_no_discards(ws):
    from registrar.agents.multi import Coordinator
    from registrar.agents.multi.agents import REGISTRATION
    from registrar.agents.router import Router
    uid = active_bs_student(ws)
    probe, _ = student_tools(ws, uid)
    lec = addable(ws, probe)
    ask = f"Register me for CRN {lec.crn} next spring"
    client = FakeClient([_plan(REGISTRATION, ask), [call("request_registration", {"crn": lec.crn, "term": "Spring 2027"})],
                         "Shall I?"])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    co = Coordinator(r)
    co.ask(ask)
    n = len(client.requests)
    res = co.ask("no")
    assert res.route == "confirm" and res.reply == "Nothing was changed." and not r.gate.pending
    assert len(client.requests) == n and enr(ws, uid, "202710", lec.crn) is None


def test_coordinator_registers_by_course_code(ws):
    """request_registration_for_course (Mason): course -> section -> pending change, on main's student tools."""
    from registrar.agents.multi import Coordinator
    from registrar.agents.multi.agents import REGISTER_FOR_COURSE, REGISTRATION
    from registrar.agents.router import Router
    single = [l for l in ws.scalars(select(Lecture).where(Lecture.term_code == "202710", Lecture.is_cancelled.is_(False))
                                    .order_by(Lecture.crn))
              if ws.scalar(select(func.count()).select_from(Lecture).where(
                  Lecture.term_code == "202710", Lecture.course_code == l.course_code,
                  Lecture.is_cancelled.is_(False))) == 1]
    uid = lec = None
    for cand in ws.scalars(select(Student.university_id).where(Student.status == "active")
                           .order_by(Student.university_id).limit(60)):  # a student who can add a one-section course
        probe, _ = student_tools(ws, cand)
        lec = next((l for l in single if probe.check_registration(l.crn, "Spring 2027")["answer"]["can_add"]), None)
        if lec is not None:
            uid = cand
            break
    assert uid is not None
    ask = f"Register me for {lec.course_code} next spring"
    client = FakeClient([_plan(REGISTRATION, ask),
                         [call(REGISTER_FOR_COURSE, {"course": lec.course_code, "term": "Spring 2027"})], "Shall I?"])
    r = Router(client, ws, uid, as_of=DEFAULT, model="fake")
    co = Coordinator(r)
    first = co.ask(ask)
    assert lec.crn in first.reply and first.reply.endswith("Please answer yes or no.")
    assert co.ask("Yes.").answer["changed"] is True
    assert enr(ws, uid, "202710", lec.crn).status.value == "enrolled"
