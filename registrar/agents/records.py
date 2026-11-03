"""Academic-record tools that need the enrollment table: a student's own transcript and GPA.
Shapes follow the pending `taken_all` / `gpa` intents of the earlier student question catalog. Computations follow
handbook 1.1 and 1.2: credit when points > 0; W and I excluded from the GPA; every attempt counts."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar
from registrar.agents.common import plain
from registrar.agents.student.tools import _fn
from registrar.models import AcademicTerm, Course, Enrollment, GradeScale


def transcript_rows(session: Session, uid: str):
    return session.execute(
        select(Enrollment, AcademicTerm, Course, GradeScale.points)
        .join(AcademicTerm, AcademicTerm.code == Enrollment.term_code)
        .join(Course, Course.code == Enrollment.course_code)
        .outerjoin(GradeScale, GradeScale.letter == Enrollment.grade)
        .where(Enrollment.student_university_id == uid, Enrollment.status != "dropped")
        .order_by(AcademicTerm.sequence, Enrollment.course_code)).all()


def gpa_summary(rows) -> dict:
    by_term: dict[str, list] = defaultdict(list)
    seq = {}
    earned: dict[str, float] = {}
    for e, t, c, pts in rows:
        if pts is None:
            continue
        by_term[t.name].append((float(pts), float(c.credit_hours)))
        seq[t.name] = t.sequence
        if pts > 0:
            earned[c.code] = float(c.credit_hours)  # a repeated course counts once toward credits

    def g(xs):
        cr = sum(c for _, c in xs)
        return round(sum(p * c for p, c in xs) / cr, 2) if cr else None
    last = max(by_term, key=seq.get) if by_term else None
    return {"last_term": last, "last_term_gpa": g(by_term[last]) if last else None,
            "cumulative_gpa": g([x for v in by_term.values() for x in v]), "credits_earned": plain(sum(earned.values())),
            "by_term": {k: g(v) for k, v in sorted(by_term.items(), key=lambda kv: seq[kv[0]])}}


class StudentRecordTools:
    def __init__(self, session: Session, calendar: Calendar, uid: str):
        self.s, self.cal, self.uid = session, calendar, uid

    def get_my_transcript(self) -> dict:
        rows = transcript_rows(self.s, self.uid)
        cur = self.cal.current().code
        completed = [{"course": c.code, "term": t.name, "grade": e.grade} for e, t, c, _ in rows
                     if e.grade and e.grade != "W"]
        withdrawn = [{"course": c.code, "term": t.name} for e, t, c, _ in rows if e.grade == "W"]
        in_progress = [c.code for e, t, c, _ in rows if e.grade is None and t.code == cur]
        return {"answer": {"completed": completed, "withdrawn": withdrawn, "in_progress": in_progress,
                           "transfer_or_test_credit": []}}

    def get_my_gpa(self) -> dict:
        return {"answer": gpa_summary(transcript_rows(self.s, self.uid)),
                "note": "Every attempt counts in the GPA (handbook 1.2); W and I do not."}


RECORD_SPECS = [
    _fn("get_my_transcript", "The logged-in student's own courses: completed with grades, withdrawn (W), and in "
        "progress this term."),
    _fn("get_my_gpa", "The logged-in student's own GPA: last graded term, cumulative, credits earned, GPA by term."),
]
