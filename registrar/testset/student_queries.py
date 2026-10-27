"""SQL used to answer student questions. Each function logs its statement(s) through a QueryLog."""
from __future__ import annotations

from .common import QueryLog

TERM_COLS = "id, code, name, term_type, academic_year, start_date, end_date, registration_opens, add_deadline, drop_deadline, census_date, withdraw_deadline, grades_due, is_current, sequence"


def student_by_uid(q: QueryLog, university_id: str) -> dict | None:
    return q.one("identify the student", f"""
        SELECT s.id AS student_id, p.id AS person_id, p.university_id, p.legal_first_name, p.preferred_first_name,
               p.legal_last_name, p.email, s.status, s.level, s.catalog_term_id, s.admit_term_id,
               s.expected_graduation_term_id, s.is_honors, s.is_athlete, s.is_veteran
        FROM student s JOIN person p ON p.id = s.person_id
        WHERE p.university_id = %(uid)s""", uid=university_id)


def programs(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("declared programs", """
        SELECT pr.code, pr.name, pr.degree_type, pr.program_type, pr.total_credits_required, sp.is_primary, sp.status,
               ct.code AS catalog_term
        FROM student_program sp JOIN program pr ON pr.id = sp.program_id JOIN academic_term ct ON ct.id = sp.catalog_term_id
        WHERE sp.student_id = %(sid)s AND sp.status IN ('declared', 'completed')
        ORDER BY sp.is_primary DESC, pr.program_type""", sid=student_id)


def current_term(q: QueryLog) -> dict:
    return q.one("current term", f"SELECT {TERM_COLS} FROM academic_term WHERE is_current")


def term_by_code(q: QueryLog, code: str) -> dict:
    return q.one("term dates", f"SELECT {TERM_COLS} FROM academic_term WHERE code = %(code)s", code=code)


def next_registrable_term(q: QueryLog, as_of_date) -> dict | None:
    """The earliest term whose add deadline has not passed: the one 'when can I register' refers to by default."""
    return q.one("next term still open for registration", f"""
        SELECT {TERM_COLS} FROM academic_term WHERE add_deadline >= %(d)s ORDER BY sequence LIMIT 1""", d=as_of_date)


def term_by_offset(q: QueryLog, sequence: int, offset: int) -> dict | None:
    return q.one("adjacent term", f"SELECT {TERM_COLS} FROM academic_term WHERE sequence = %(seq)s", seq=sequence + offset)


def enrolled_terms(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("terms with enrollment", f"""
        SELECT DISTINCT t.id, t.code, t.name, t.sequence
        FROM enrollment e JOIN academic_term t ON t.id = e.term_id
        WHERE e.student_id = %(sid)s AND e.status <> 'dropped'
        ORDER BY t.sequence""", sid=student_id)


def term_schedule(q: QueryLog, student_id: int, term_id: int) -> list[dict]:
    return q.rows("student's enrollments in the term", """
        SELECT e.id AS enrollment_id, e.status, e.credits, e.grading_basis, e.registered_at, e.dropped_at,
               sec.id AS section_id, sec.crn, sec.section_number, sec.instruction_mode, sec.status AS section_status,
               c.id AS course_id, sub.code AS subject, c.course_number, c.title
        FROM enrollment e
        JOIN section sec ON sec.id = e.section_id
        JOIN course c ON c.id = sec.course_id
        JOIN subject sub ON sub.id = c.subject_id
        WHERE e.student_id = %(sid)s AND e.term_id = %(tid)s
        ORDER BY sub.code, c.course_number, sec.section_number""", sid=student_id, tid=term_id)


def meetings(q: QueryLog, section_ids: list[int]) -> list[dict]:
    if not section_ids:
        return []
    return q.rows("meeting times and rooms", """
        SELECT m.section_id, m.days, m.start_time, m.end_time, m.meeting_type, b.code AS building, b.name AS building_name,
               r.room_number
        FROM section_meeting m
        LEFT JOIN room r ON r.id = m.room_id
        LEFT JOIN building b ON b.id = r.building_id
        WHERE m.section_id = ANY(%(ids)s::int[])
        ORDER BY m.section_id, m.start_time""", ids=section_ids)


def instructors(q: QueryLog, section_ids: list[int]) -> list[dict]:
    if not section_ids:
        return []
    return q.rows("instructors", """
        SELECT si.section_id, si.role, p.legal_first_name, p.legal_last_name, p.email
        FROM section_instructor si
        JOIN instructor i ON i.id = si.instructor_id
        JOIN person p ON p.id = i.person_id
        WHERE si.section_id = ANY(%(ids)s::int[])
        ORDER BY si.section_id, si.role""", ids=section_ids)


def section_by_crn(q: QueryLog, term_id: int, crn: str) -> dict | None:
    return q.one("section by CRN", """
        SELECT sec.id AS section_id, sec.crn, sec.section_number, sec.credits, sec.capacity, sec.waitlist_capacity,
               sec.instruction_mode, sec.status, sec.campus, c.id AS course_id, sub.code AS subject, c.course_number, c.title,
               c.level AS course_level
        FROM section sec JOIN course c ON c.id = sec.course_id JOIN subject sub ON sub.id = c.subject_id
        WHERE sec.term_id = %(tid)s AND sec.crn = %(crn)s""", tid=term_id, crn=crn)


def sections_of_course(q: QueryLog, term_id: int, subject: str, number: str) -> list[dict]:
    return q.rows("sections of the course in the term", """
        SELECT sec.id AS section_id, sec.crn, sec.section_number, sec.credits, sec.capacity, sec.waitlist_capacity,
               sec.instruction_mode, sec.status, sec.campus, c.id AS course_id, sub.code AS subject, c.course_number, c.title,
               c.level AS course_level
        FROM section sec JOIN course c ON c.id = sec.course_id JOIN subject sub ON sub.id = c.subject_id
        WHERE sec.term_id = %(tid)s AND sub.code = %(subject)s AND c.course_number = %(number)s
        ORDER BY sec.section_number""", tid=term_id, subject=subject, number=number)


def seat_counts(q: QueryLog, section_ids: list[int]) -> dict[int, dict]:
    if not section_ids:
        return {}
    rows = q.rows("seat and waitlist counts", """
        SELECT sec.id AS section_id, sec.capacity, sec.waitlist_capacity,
               COUNT(e.id) FILTER (WHERE e.status = 'registered') AS registered,
               COUNT(e.id) FILTER (WHERE e.status = 'waitlisted') AS waitlisted
        FROM section sec LEFT JOIN enrollment e ON e.section_id = sec.id
        WHERE sec.id = ANY(%(ids)s::int[])
        GROUP BY sec.id""", ids=section_ids)
    return {r["section_id"]: r for r in rows}


def prerequisites(q: QueryLog, course_id: int) -> list[dict]:
    return q.rows("prerequisite rules", """
        SELECT cp.group_number, cp.prereq_type, cp.min_grade, c.id AS required_course_id, sub.code AS subject,
               c.course_number, c.title
        FROM course_prerequisite cp JOIN course c ON c.id = cp.required_course_id JOIN subject sub ON sub.id = c.subject_id
        WHERE cp.course_id = %(cid)s
        ORDER BY cp.group_number, sub.code, c.course_number""", cid=course_id)


def completed_courses(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("courses completed with grades", """
        SELECT c.id AS course_id, sub.code AS subject, c.course_number, c.title, e.credits, g.grade, t.code AS term_code,
               t.name AS term_name, t.sequence
        FROM enrollment e
        JOIN grade g ON g.enrollment_id = e.id
        JOIN section sec ON sec.id = e.section_id
        JOIN course c ON c.id = sec.course_id
        JOIN subject sub ON sub.id = c.subject_id
        JOIN academic_term t ON t.id = e.term_id
        WHERE e.student_id = %(sid)s AND e.status = 'completed'
        ORDER BY t.sequence, sub.code, c.course_number""", sid=student_id)


def transfer_credits(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("transfer credit", """
        SELECT ti.name AS institution, tc.external_course_code, tc.external_course_title, tc.external_credits,
               tc.external_grade, tc.external_term, tc.awarded_credits, tc.status, c.id AS course_id,
               sub.code AS subject, c.course_number, c.title
        FROM transfer_credit tc
        JOIN transfer_institution ti ON ti.id = tc.institution_id
        LEFT JOIN course c ON c.id = tc.equivalent_course_id
        LEFT JOIN subject sub ON sub.id = c.subject_id
        WHERE tc.student_id = %(sid)s AND tc.status = 'awarded'
        ORDER BY ti.name, tc.external_course_code""", sid=student_id)


def test_credits(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("AP/IB/CLEP credit", """
        SELECT tc.test_type, tc.test_subject, tc.score, tc.credits_awarded, c.id AS course_id, sub.code AS subject,
               c.course_number, c.title
        FROM test_credit tc
        LEFT JOIN course c ON c.id = tc.equivalent_course_id
        LEFT JOIN subject sub ON sub.id = c.subject_id
        WHERE tc.student_id = %(sid)s
        ORDER BY tc.test_type, tc.test_subject""", sid=student_id)


def active_holds(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("active holds", """
        SELECT hold_type, placed_by_office, reason, placed_at, blocks_registration, blocks_transcript, blocks_graduation
        FROM hold WHERE student_id = %(sid)s AND released_at IS NULL
        ORDER BY placed_at""", sid=student_id)


def appointment(q: QueryLog, student_id: int, term_id: int) -> dict | None:
    return q.one("registration appointment (time ticket)", """
        SELECT begins_at, ends_at, priority_group
        FROM registration_appointment WHERE student_id = %(sid)s AND term_id = %(tid)s""", sid=student_id, tid=term_id)


def term_records(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("term GPA and standing history", """
        SELECT t.code AS term_code, t.name AS term_name, t.sequence, r.attempted_credits, r.earned_credits, r.gpa_credits,
               r.term_gpa, r.cumulative_attempted, r.cumulative_earned, r.cumulative_gpa, r.standing, r.classification
        FROM student_term_record r JOIN academic_term t ON t.id = r.term_id
        WHERE r.student_id = %(sid)s
        ORDER BY t.sequence""", sid=student_id)


def transcript_courses(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("transcript course lines", """
        SELECT t.code AS term_code, t.name AS term_name, t.sequence, sub.code AS subject, c.course_number, c.title,
               e.credits, e.status, e.is_repeat, g.grade, g.quality_points, g.counts_in_gpa, g.earns_credit, g.is_final
        FROM enrollment e
        JOIN section sec ON sec.id = e.section_id
        JOIN course c ON c.id = sec.course_id
        JOIN subject sub ON sub.id = c.subject_id
        JOIN academic_term t ON t.id = e.term_id
        LEFT JOIN grade g ON g.enrollment_id = e.id
        WHERE e.student_id = %(sid)s AND e.status IN ('completed', 'withdrawn', 'registered')
        ORDER BY t.sequence, sub.code, c.course_number""", sid=student_id)


def degrees(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("degrees awarded", """
        SELECT pr.code, pr.name, pr.degree_type, t.name AS term_name, d.conferred_date, d.honors, d.final_gpa, d.total_credits
        FROM degree_awarded d JOIN program pr ON pr.id = d.program_id JOIN academic_term t ON t.id = d.term_id
        WHERE d.student_id = %(sid)s ORDER BY d.conferred_date""", sid=student_id)


def academic_actions(q: QueryLog, student_id: int) -> list[dict]:
    return q.rows("academic actions", """
        SELECT a.action_type, a.action_date, t.name AS term_name
        FROM academic_action a JOIN academic_term t ON t.id = a.term_id
        WHERE a.student_id = %(sid)s ORDER BY a.action_date""", sid=student_id)


def course_attempts(q: QueryLog, student_id: int, subject: str, number: str) -> list[dict]:
    return q.rows("attempts at the course", """
        SELECT t.code AS term_code, t.name AS term_name, e.status, e.credits, g.grade
        FROM enrollment e
        JOIN section sec ON sec.id = e.section_id
        JOIN course c ON c.id = sec.course_id
        JOIN subject sub ON sub.id = c.subject_id
        JOIN academic_term t ON t.id = e.term_id
        LEFT JOIN grade g ON g.enrollment_id = e.id
        WHERE e.student_id = %(sid)s AND sub.code = %(subject)s AND c.course_number = %(number)s
        ORDER BY t.sequence""", sid=student_id, subject=subject, number=number)


def course_equivalents(q: QueryLog, student_id: int, subject: str, number: str) -> list[dict]:
    return q.rows("transfer or test credit equivalent to the course", """
        SELECT 'transfer' AS source, ti.name AS detail, tc.awarded_credits AS credits
        FROM transfer_credit tc JOIN transfer_institution ti ON ti.id = tc.institution_id
        JOIN course c ON c.id = tc.equivalent_course_id JOIN subject sub ON sub.id = c.subject_id
        WHERE tc.student_id = %(sid)s AND tc.status = 'awarded' AND sub.code = %(subject)s AND c.course_number = %(number)s
        UNION ALL
        SELECT 'test' AS source, x.test_type || ' ' || x.test_subject AS detail, x.credits_awarded AS credits
        FROM test_credit x JOIN course c ON c.id = x.equivalent_course_id JOIN subject sub ON sub.id = c.subject_id
        WHERE x.student_id = %(sid)s AND sub.code = %(subject)s AND c.course_number = %(number)s""",
        sid=student_id, subject=subject, number=number)


def course_lookup(q: QueryLog, subject: str, number: str) -> dict | None:
    return q.one("course catalog entry", """
        SELECT c.id AS course_id, sub.code AS subject, c.course_number, c.title, c.credits_min, c.credits_max
        FROM course c JOIN subject sub ON sub.id = c.subject_id
        WHERE sub.code = %(subject)s AND c.course_number = %(number)s""", subject=subject, number=number)
