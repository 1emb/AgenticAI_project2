"""SQL used to answer professor questions. Shared catalog/section queries live in student_queries."""
from __future__ import annotations

from .common import QueryLog
from .student_queries import TERM_COLS  # noqa: F401  (re-exported for callers)

SECTION_COLS = """sec.id AS section_id, sec.crn, sec.section_number, sec.credits, sec.capacity, sec.waitlist_capacity,
               sec.instruction_mode, sec.status AS section_status, sec.term_id, c.id AS course_id, sub.code AS subject,
               c.course_number, c.title, c.level AS course_level"""


def instructor_by_uid(q: QueryLog, university_id: str) -> dict | None:
    return q.one("identify the instructor", """
        SELECT i.id AS instructor_id, p.id AS person_id, p.university_id, p.legal_first_name, p.preferred_first_name,
               p.legal_last_name, p.email, i.rank, i.is_active, d.code AS department, d.name AS department_name
        FROM instructor i JOIN person p ON p.id = i.person_id JOIN department d ON d.id = i.department_id
        WHERE p.university_id = %(uid)s""", uid=university_id)


def taught_sections(q: QueryLog, instructor_id: int, term_id: int) -> list[dict]:
    return q.rows("sections the instructor teaches in the term", f"""
        SELECT {SECTION_COLS}
        FROM section_instructor si
        JOIN section sec ON sec.id = si.section_id
        JOIN course c ON c.id = sec.course_id
        JOIN subject sub ON sub.id = c.subject_id
        WHERE si.instructor_id = %(iid)s AND si.role = 'primary' AND sec.term_id = %(tid)s AND sec.status <> 'cancelled'
        ORDER BY sub.code, c.course_number, sec.section_number""", iid=instructor_id, tid=term_id)


def taught_sections_all(q: QueryLog, instructor_id: int, course: tuple[str, str] | None = None) -> list[dict]:
    extra = " AND sub.code = %(subject)s AND c.course_number = %(number)s" if course else ""
    params = {"iid": instructor_id}
    if course:
        params.update(subject=course[0], number=course[1])
    return q.rows("every section the instructor has taught", f"""
        SELECT {SECTION_COLS}, t.code AS term_code, t.name AS term_name, t.sequence
        FROM section_instructor si
        JOIN section sec ON sec.id = si.section_id
        JOIN academic_term t ON t.id = sec.term_id
        JOIN course c ON c.id = sec.course_id
        JOIN subject sub ON sub.id = c.subject_id
        WHERE si.instructor_id = %(iid)s AND si.role = 'primary' AND sec.status <> 'cancelled'{extra}
        ORDER BY t.sequence, sub.code, c.course_number, sec.section_number""", **params)


def section_enrollments(q: QueryLog, section_ids: list[int]) -> list[dict]:
    if not section_ids:
        return []
    return q.rows("enrollments and grades in the sections", """
        SELECT e.id AS enrollment_id, e.section_id, e.student_id, p.university_id, p.legal_first_name, p.preferred_first_name,
               p.legal_last_name, p.email, e.status, e.credits, e.registered_at, e.dropped_at,
               g.grade, g.quality_points, g.counts_in_gpa, g.earns_credit, g.is_final, g.posted_at, g.incomplete_deadline
        FROM enrollment e
        JOIN student s ON s.id = e.student_id
        JOIN person p ON p.id = s.person_id
        LEFT JOIN grade g ON g.enrollment_id = e.id
        WHERE e.section_id = ANY(%(ids)s::int[])
        ORDER BY e.section_id, p.legal_last_name, p.legal_first_name""", ids=section_ids)


def waitlist(q: QueryLog, section_id: int) -> list[dict]:
    return q.rows("waitlist in order", """
        SELECT w.position, w.status, p.university_id
        FROM waitlist_entry w JOIN student s ON s.id = w.student_id JOIN person p ON p.id = s.person_id
        WHERE w.section_id = %(sid)s AND w.status = 'waiting'
        ORDER BY w.position""", sid=section_id)


def roster_profiles(q: QueryLog, section_id: int, term_sequence: int) -> list[dict]:
    """Per enrolled student: classification before the term, primary program, college, admit term."""
    return q.rows("student classification, major, and college for the roster", """
        SELECT p.university_id, e.status, s.admit_term_id,
               (SELECT r.classification FROM student_term_record r JOIN academic_term rt ON rt.id = r.term_id
                 WHERE r.student_id = s.id AND rt.sequence < %(seq)s ORDER BY rt.sequence DESC LIMIT 1) AS classification,
               pr.code AS program, co.code AS college
        FROM enrollment e
        JOIN student s ON s.id = e.student_id
        JOIN person p ON p.id = s.person_id
        LEFT JOIN LATERAL (
            SELECT sp.program_id FROM student_program sp
            WHERE sp.student_id = s.id AND sp.is_primary AND sp.status IN ('declared', 'completed')
            ORDER BY sp.declared_at DESC LIMIT 1) sp ON TRUE
        LEFT JOIN program pr ON pr.id = sp.program_id
        LEFT JOIN department d ON d.id = pr.department_id
        LEFT JOIN college co ON co.id = d.college_id
        WHERE e.section_id = %(sid)s
        ORDER BY p.university_id""", sid=section_id, seq=term_sequence)


def calendar_events(q: QueryLog, term_id: int) -> list[dict]:
    return q.rows("academic calendar for the term", """
        SELECT name, event_type, event_date, end_date FROM academic_calendar_event
        WHERE term_id = %(tid)s ORDER BY event_date""", tid=term_id)


def grade_changes_requested(q: QueryLog, person_id: int) -> list[dict]:
    return q.rows("grade changes the instructor requested", """
        SELECT gc.old_grade, gc.new_grade, gc.reason, gc.requested_at, gc.applied_at, gc.approved_by_person_id,
               p.university_id, sec.crn, sub.code AS subject, c.course_number, t.name AS term_name
        FROM grade_change gc
        JOIN grade g ON g.id = gc.grade_id
        JOIN enrollment e ON e.id = g.enrollment_id
        JOIN section sec ON sec.id = e.section_id
        JOIN course c ON c.id = sec.course_id
        JOIN subject sub ON sub.id = c.subject_id
        JOIN academic_term t ON t.id = e.term_id
        JOIN student s ON s.id = e.student_id
        JOIN person p ON p.id = s.person_id
        WHERE gc.requested_by_person_id = %(pid)s
        ORDER BY gc.requested_at""", pid=person_id)


def course_catalog(q: QueryLog, subject: str, number: str) -> dict | None:
    return q.one("course catalog entry", """
        SELECT c.id AS course_id, sub.code AS subject, c.course_number, c.title, c.credits_min, c.credits_max, c.level,
               c.is_gen_ed, c.gen_ed_area, c.is_repeatable
        FROM course c JOIN subject sub ON sub.id = c.subject_id
        WHERE sub.code = %(subject)s AND c.course_number = %(number)s""", subject=subject, number=number)


def student_by_uid_public(q: QueryLog, university_id: str) -> dict | None:
    """Only what a roster shows: id and name. Used to resolve a name the professor typed."""
    return q.one("resolve the student named in the question", """
        SELECT s.id AS student_id, p.university_id, p.legal_first_name, p.preferred_first_name, p.legal_last_name, p.email
        FROM student s JOIN person p ON p.id = s.person_id WHERE p.university_id = %(uid)s""", uid=university_id)
