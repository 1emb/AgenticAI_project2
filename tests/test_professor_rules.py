"""Professor rules the test set does not exercise directly: how a CRN without a term is read, weekdays, deadline
boundaries, TA rights, data-driven refusals, privacy of every tool, and output formats."""
import json

import pytest
from sqlalchemy import text

from registrar.agents.calendar import Calendar
from registrar.agents.common import ToolError
from registrar.agents.professor.tools import ProfessorTools, parse_day

JOSE = "801408626"      # Jose Wilson, CS professor. Fall 2026: CRN 10005, 10014, 10026, 10123. Spring 2026: 10008
                        # (38 students, grades submitted), 10018, 10027. Spring 2027: 10001, 10013, 10026.
NATHAN = "800337545"    # Nathan Gutierrez, instructor of record of CRN 10012 (CS 2230) in Fall 2026
CARLOS = "800020284"    # Carlos Gonzalez, an MS student and TA; assists CRN 10012 and 10116 in Fall 2026
WANG = "800151804"      # Carlos Wang, PSY professor with three PSY 1110 sections in Spring 2026
KAYLA = "800376715"     # Kayla Anderson, got A- in Jose's CRN 10008, Spring 2026
LUIS = "800002531"      # Luis Trujillo, never in any of Jose's sections
DEFAULT = "2026-11-20T18:00:00+00:00"


def tools(session, uid=JOSE, as_of=DEFAULT):
    return ProfessorTools(session, uid, Calendar(session, as_of))


def declined(out):
    return out.get("_declined")


# ---------------------------------------------------------------- reading a CRN without a term
def test_bare_crn_is_this_term_when_it_is_my_section(session):
    assert tools(session).get_my_section(crn="10026")["answer"]["term"] == "Fall 2026"


def test_bare_crn_for_scheduling_prefers_my_upcoming_section(session):
    # 10001 is Jose's only in Spring 2027; this term it is someone else's.
    out = tools(session).get_my_capacity(crn="10001")
    assert out["answer"]["term"] == "Spring 2027" and "Spring 2027" in out["note"]


def test_bare_crn_for_rosters_prefers_my_most_recent_past_section(session):
    out = tools(session).get_roster(crn="10008")
    assert out["answer"]["term"] == "Spring 2026" and len(out["answer"]["students"]) > 0


def test_bare_crn_for_grades_skips_terms_without_submitted_grades(session):
    out = tools(session).get_grade_distribution(crn="10008")
    assert out["answer"]["term"] == "Spring 2026" and out["answer"]["graded"] > 0


def test_bare_crn_with_a_student_finds_the_section_they_are_in(session):
    a = tools(session).get_student_grade("Kayla Anderson", crn="10008")["answer"]
    assert (a["term"], a["grade"], a["posted"]) == ("Spring 2026", "A-", True)


def test_bare_crn_that_is_not_mine_is_this_terms_section(session):
    a = tools(session).get_my_section(crn="10020")["answer"]       # Daniela Reyes's CS 3420; never Jose's
    assert a["term"] == "Fall 2026" and a["sections"][0]["instructor"] == "Daniela Reyes"
    # 10011 was Jose's in Fall 2025, but for "when does it meet" this term's section is the useful reading.
    assert tools(session).get_my_section(crn="10011")["answer"]["term"] == "Fall 2026"


def test_named_term_always_wins(session):
    assert tools(session).get_my_capacity(crn="10026", term="next spring")["answer"]["term"] == "Spring 2027"


def test_a_course_with_several_of_my_sections_asks_which_crn(session):
    with pytest.raises(ToolError, match="Ask which CRN"):
        tools(session, uid=WANG).get_withdrawals(course="PSY 1110", term="last term")


# ---------------------------------------------------------------- data-driven refusals
def test_colleague_roster_and_statistics_are_refused_with_the_section_as_target(session):
    t = tools(session)
    for out in (t.get_roster(crn="10020"), t.get_section_grades(crn="10020", term="this fall"),
                t.get_withdrawals(crn="10020", term="this fall"), t.get_grade_distribution(crn="10020", term="this fall")):
        assert declined(out) == {"reason": "student_list_not_permitted", "target": {"term": "Fall 2026", "crn": "10020"}}


def test_student_record_needs_the_student_in_my_sections(session):
    t = tools(session)
    assert t.get_student_info("Kayla Anderson")["answer"]["program"]
    for out in (t.get_student_info("Luis Trujillo"), t.get_student_grade("Luis Trujillo", crn="10008")):
        assert declined(out) == {"reason": "student_record_not_permitted", "target": {"university_id": LUIS}}


def test_my_students_grade_elsewhere_is_refused(session):
    # Kayla is Jose's student, but CRN 10002 in Fall 2026 is not Jose's section.
    out = tools(session).get_student_grade("Kayla Anderson", crn="10002", term="this fall")
    assert declined(out) == {"reason": "student_record_not_permitted", "target": {"university_id": KAYLA}}


def test_ta_has_professor_rights_on_assisted_sections(session):
    ta = tools(session, uid=CARLOS)
    assert "answer" in ta.get_roster(crn="10012")                   # assists it
    assert {s["crn"] for s in ta.get_my_ta_assignments()["answer"]["sections"]} >= {"10012", "10116"}
    assert "10012" in ta.get_enrollment_counts()["answer"]["sections"]


def test_ta_is_named_but_their_email_is_withheld(session):
    assert tools(session, uid=NATHAN).get_my_tas("this fall")["answer"]["sections"]["10012"]["tas"] == ["Carlos Gonzalez"]
    entry = tools(session).get_instructor("Carlos Gonzalez")
    assert entry["answer"]["email"] is None and entry["answer"]["rank"] == "ta"


def test_refusal_targets_and_own_record(session):
    t = tools(session)
    assert declined(t.decline_request("other_instructor_record", person="Nathan Gutierrez"))["target"] == \
        {"university_id": NATHAN}
    assert declined(t.decline_request("student_list_not_permitted", program="Master of Science in Engineering"))[
        "target"] == {"program": "MSENG"}
    with pytest.raises(ToolError):                     # own hire date and salary are answered, not refused
        t.decline_request("other_instructor_record", person="Jose Wilson")
    with pytest.raises(ToolError):
        t.decline_request("because_the_dean_said_so")
    me = t.get_my_profile()["answer"]
    assert (me["hire_date"], me["salary"], me["rank"]) == ("2012-08-16", 159100, "professor")


# ---------------------------------------------------------------- privacy and formats
def test_no_tool_exposes_private_fields(session):
    t = tools(session)
    out = json.dumps([t.get_roster(crn="10008"), t.get_student_info("Kayla Anderson"),
                      t.get_section_grades(crn="10008"), t.get_instructor("Nathan Gutierrez"),
                      t.get_colleague_schedule("Nathan Gutierrez", "this fall"), t.get_incompletes(),
                      t.get_my_tas("this fall"), t.get_student_grade("Kayla Anderson", crn="10008")], default=str)
    private = session.execute(text(
        "SELECT p.phone, p.ssn, p.date_of_birth::text FROM person p WHERE university_id IN (:a, :b) "
        "UNION ALL SELECT i.hire_date::text, i.salary::text, NULL FROM instructor i WHERE university_id = :b"),
        {"a": KAYLA, "b": NATHAN}).all()
    for row in private:
        for value in row:
            if value:
                assert value not in out, value


def test_submission_times_are_utc_iso(session):
    a = tools(session).get_grade_submission_status("Spring 2026")["answer"]
    assert a["sections"]["10008"]["submitted_at"] == "2026-05-10T01:45:00+00:00"
    assert a["grades_due"] == "2026-05-11"


@pytest.mark.parametrize("text_, expected", [
    ("Wednesday", "Wednesday"), ("wednesdays", "Wednesday"), ("Wed", "Wednesday"), ("W", "Wednesday"),
    ("thurs", "Thursday"), ("R", "Thursday"), ("Tuesdays", "Tuesday"), ("sat", "Saturday"), ("U", "Sunday")])
def test_weekdays(text_, expected):
    assert parse_day(text_)[1] == expected


def test_deadline_on_its_own_day_has_not_passed(session):
    assert tools(session, as_of="2026-12-15T12:00:00+00:00").get_term_date("grades_due", "Fall 2026")["answer"][
        "has_passed"] is False
    assert tools(session, as_of="2026-12-16T12:00:00+00:00").get_term_date("grades_due", "Fall 2026")["answer"][
        "has_passed"] is True


def test_winter_break_next_semester_is_the_coming_term(session):
    t = tools(session, as_of="2026-12-20T18:00:00+00:00")
    assert t.get_my_schedule("next semester")["answer"]["term"] == "Spring 2027"
    assert t.get_my_schedule("last semester")["answer"]["term"] == "Fall 2026"


def test_only_instructors_can_log_in(session):
    with pytest.raises(ValueError):
        tools(session, uid=KAYLA)


def test_course_trend_counts_only_graded_terms(session):
    # Jose teaches CS 4720 in Fall 2026 (no grades yet); the trend must not list that term.
    by_term = tools(session).get_course_trend("CS 4720")["answer"]["by_term"]
    assert "Fall 2026" not in by_term and "Spring 2027" not in by_term


def test_teaching_history_lists_only_sections_taught_not_assisted(session):
    history = tools(session, uid=CARLOS).get_my_teaching_history()["answer"]
    assisted = {(s["crn"], "Fall 2026") for s in tools(session, uid=CARLOS).get_my_ta_assignments()["answer"]["sections"]}
    listed = {(s["crn"], term) for term, rows in history["by_term"].items() for s in rows}
    assert not assisted & listed


def test_grade_submission_and_tas_cover_only_sections_taught(session):
    ta = tools(session, uid=CARLOS)
    assisted = {s["crn"] for s in ta.get_my_ta_assignments("last spring")["answer"]["sections"]}
    assert assisted, "fixture: Carlos assisted sections in Spring 2026"
    assert not assisted & set(ta.get_grade_submission_status("last spring")["answer"]["sections"])
    assert not assisted & set(ta.get_my_tas("last spring")["answer"]["sections"])
