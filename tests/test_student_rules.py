"""Rules the test set does not exercise directly: deadline boundaries, cancelled sections, default terms, phrase
resolution at each clock, refusal targets, and bad input."""
import pytest

from registrar.agents.calendar import Calendar, TermNotFound
from registrar.agents.common import ToolError
from registrar.agents.student.tools import StudentTools

ME = "800260544"            # Raj Martinez, BSENG
DEFAULT, BREAK, SPRING = "2026-11-20T18:00:00+00:00", "2026-12-20T18:00:00+00:00", "2027-01-20T18:00:00+00:00"


def tools(session, as_of=DEFAULT, uid=ME):
    return StudentTools(session, uid, Calendar(session, as_of))


@pytest.mark.parametrize("as_of, phrase, expected", [
    (DEFAULT, None, "Fall 2026"), (DEFAULT, "this semester", "Fall 2026"), (DEFAULT, "this fall", "Fall 2026"),
    (DEFAULT, "next semester", "Spring 2027"), (DEFAULT, "next spring", "Spring 2027"), (DEFAULT, "next fall", "Fall 2027"),
    (DEFAULT, "last spring", "Spring 2026"), (DEFAULT, "last fall", "Fall 2025"), (DEFAULT, "in Fall 2024", "Fall 2024"),
    (DEFAULT, "202710", "Spring 2027"), (DEFAULT, "spring 2027", "Spring 2027"), (DEFAULT, "the upcoming term", "Spring 2027"),
    (BREAK, None, "Spring 2027"), (BREAK, "last semester", "Fall 2026"), (BREAK, "last fall", "Fall 2026"),
    (SPRING, "next semester", "Fall 2027"), (SPRING, "this spring", "Spring 2027"),
])
def test_term_phrases(session, as_of, phrase, expected):
    assert Calendar(session, as_of).resolve(phrase).name == expected


def test_unknown_terms_are_errors(session):
    cal = Calendar(session, DEFAULT)
    for phrase in ("Fall 2099", "someday", "the semester after the apocalypse"):
        with pytest.raises(TermNotFound):
            cal.resolve(phrase)


def test_deadline_on_its_own_day_has_not_passed(session):
    # Spring 2027 add deadline is 2027-01-22: not passed that day, passed the next.
    assert tools(session, "2027-01-22T12:00:00+00:00").get_term_date("add_deadline", "Spring 2027")["answer"]["has_passed"] is False
    assert tools(session, "2027-01-23T12:00:00+00:00").get_term_date("add_deadline", "Spring 2027")["answer"]["has_passed"] is True


def test_registration_defaults_to_next_term_and_window_edges(session):
    t = tools(session, "2026-11-02T08:00:00+00:00")       # Spring 2027 registration opens this day
    a = t.get_registration_window()["answer"]
    assert a["term"] == "Spring 2027" and a["is_open"] is True
    assert tools(session, "2026-11-01T23:00:00+00:00").get_registration_window()["answer"]["is_open"] is False


def test_cancelled_sections_are_not_offered(session):
    # CRN 10022 of CS 3420 is cancelled in Fall 2024.
    a = tools(session).get_course_sections("CS 3420", "Fall 2024")
    assert "10022" not in a["answer"]["crns"] and "10022" in a["cancelled_crns"]
    assert tools(session).get_section("10022", "Fall 2024")["answer"]["is_cancelled"] is True


def test_input_is_normalized_or_rejected(session):
    t = tools(session)
    assert t.get_course_info("cs2210")["answer"]["course"] == "CS 2210"
    assert t.get_section("CRN 10011")["answer"]["crn"] == "10011"
    for bad in (lambda: t.get_course_info("XYZ 9999"), lambda: t.get_course_info("hello"),
                lambda: t.get_section("99999"), lambda: t.get_term_date("finals_party"),
                lambda: t.get_my_plan_for_semester("soon")):
        with pytest.raises(ToolError):
            bad()


def test_refusal_targets(session):
    t = tools(session)
    assert t.decline_request("other_student_record", person="801247891")["declined"]["target"] == {"university_id": "801247891"}
    assert t.decline_request("other_student_record", person="Layla Morales")["declined"]["target"] == {"university_id": "801247891"}
    # Two students share this name, so the target cannot be named.
    assert t.decline_request("other_student_record", person="Chen Miller")["declined"]["target"] == {"university_id": None}
    assert t.decline_request("student_list_not_permitted")["declined"]["target"] == {"program": "BSENG"}
    assert t.decline_request("student_list_not_permitted", program="Bachelor of Science in Computer Science")["declined"]["target"] == {"program": "BSCS"}
    with pytest.raises(ToolError):
        t.decline_request("other_student_record", person=ME)       # your own record is not a refusal
    with pytest.raises(ToolError):
        t.decline_request("because_i_said_so")


def test_no_tool_exposes_private_fields(session):
    """Every value a tool returns comes from public data or the user's own record."""
    import json
    t = tools(session)
    out = json.dumps([t.get_instructor("Juan Hall"), t.get_section("10011"), t.get_my_program(),
                      t.get_course_sections("CS 2230", "this fall")])
    private = session.execute(__import__("sqlalchemy").text(
        "SELECT phone, ssn, date_of_birth::text, COALESCE(i.hire_date::text, 'none') FROM person p "
        "JOIN instructor i USING (university_id) WHERE p.first_name = 'Juan' AND p.last_name = 'Hall'")).one()
    for value in private:
        if value is not None:
            assert value not in out


def test_only_students_can_log_in(session):
    with pytest.raises(ValueError):
        tools(session, uid="000000000")
