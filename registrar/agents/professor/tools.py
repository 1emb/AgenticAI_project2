"""Tools the Professor agent can call (professor and TA users).

Every data tool returns {"answer": {...}} in the professor answer shapes of data/testset/README.md, so the graded JSON
answer is built from database rows, never typed by the model. A refusal is recorded under "_declined", which the loop
keeps from the model: by decline_request when the model refuses, or by a student tool itself when the data says the
request is not allowed (the student was never in the user's sections, or the section is a colleague's).

Permission model (data/testset/README.md, data/README.md "Who may see what"):
- Public: catalog, prerequisites, terms, every section's meeting pattern and capacity, the instructor directory (name,
  email, rank, department; a TA by name only, since a TA's email is a student's).
- Own record: hire date, salary.
- "My sections" are the user's lecture_staff rows (instructor of record or TA), non-cancelled, current or past. For a
  student in one of them: name, email, program, status and the grade in that section; the section's roster, counts,
  grade statistics and grade submission.
- Never: a student's phone, date of birth, SSN, GPA, transcript or grades from other sections; anything about a student
  never in the user's sections; a colleague's roster, phone, hire date, birth date, SSN or salary; lists of students.
No tool reads those fields, so they cannot reach the model.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar, TermNotFound
from registrar.agents.common import ToolError, full_name, name_words, normalize_course, plain
from registrar.models import (AcademicTerm, Course, CoursePrerequisite, Department, Enrollment, GradeScale,
                              GradeSubmission, Instructor, Lecture, LectureStaff, Person, Program, Student)
from registrar.models.enums import EnrollmentStatus

EVENTS = {"classes_begin": "start_date", "classes_end": "end_date", "registration_opens": "registration_opens",
          "add_deadline": "add_deadline", "drop_deadline": "drop_deadline", "withdraw_deadline": "withdraw_deadline",
          "grades_due": "grades_due"}
WEEK = [("M", "Monday"), ("T", "Tuesday"), ("W", "Wednesday"), ("R", "Thursday"), ("F", "Friday"), ("S", "Saturday"),
        ("U", "Sunday")]
DAY_BY_NAME = {name.lower(): (code, name) for code, name in WEEK}
D_GRADES = ("D+", "D", "D-")
DECLINE_REASONS = ("student_record_not_permitted", "other_instructor_record", "student_list_not_permitted")
NOT_MINE = "That section is not one of yours, so its students are private."


def parse_day(text: str) -> tuple[str, str]:
    """'Wednesdays', 'wed', 'W', 'thurs', 'R' -> ('W', 'Wednesday') ..."""
    t = re.sub(r"[^a-z]", "", str(text or "").lower())
    if len(t) == 1:
        for code, name in WEEK:
            if code.lower() == t:
                return code, name
    t = t[:-1] if t.endswith("s") and t[:-1] in DAY_BY_NAME else t
    if t in DAY_BY_NAME:
        return DAY_BY_NAME[t]
    for name, pair in DAY_BY_NAME.items():
        if len(t) >= 2 and name.startswith(t):
            return pair
    raise ToolError(f"{text!r} is not a day of the week.")


def utc_iso(v: datetime | None) -> str | None:
    return None if v is None else v.astimezone(timezone.utc).isoformat()


def refusal(reason: str, target: dict, message: str) -> dict:
    return {"_declined": {"reason": reason, "target": target}, "declined": True,
            "message": message + " Tell the user briefly, without repeating any private detail."}


class ProfessorTools:
    def __init__(self, session: Session, instructor_uid: str, calendar: Calendar):
        self.s = session
        self.cal = calendar
        row = session.execute(
            select(Instructor, Person, Department)
            .join(Person, Person.university_id == Instructor.university_id)
            .join(Department, Department.code == Instructor.department_code)
            .where(Instructor.university_id == str(instructor_uid))).first()
        if row is None:
            raise ValueError(f"{instructor_uid} is not an instructor.")
        self.instructor, self.person, self.department = row
        self.uid = self.instructor.university_id
        self._points = {g.letter: (None if g.points is None else float(g.points)) for g in session.scalars(select(GradeScale))}

    # ================================================================ lookups
    def _course(self, code: str) -> Course:
        code = normalize_course(code)
        course = self.s.get(Course, code)
        if course is None:
            raise ToolError(f"There is no course {code} in the catalog.")
        return course

    def _term(self, phrase: str | None, default: int = 0) -> AcademicTerm:
        try:
            return self.cal.resolve(phrase, default)
        except TermNotFound as e:
            raise ToolError(str(e)) from None

    def _lectures(self, *where, live_only: bool = True):
        """(Lecture, instructor Person, Course, AcademicTerm) rows, by term then CRN."""
        q = (select(Lecture, Person, Course, AcademicTerm)
             .join(Person, Person.university_id == Lecture.instructor_university_id)
             .join(Course, Course.code == Lecture.course_code)
             .join(AcademicTerm, AcademicTerm.code == Lecture.term_code)
             .where(*where).order_by(AcademicTerm.sequence, Lecture.crn))
        if live_only:
            q = q.where(Lecture.is_cancelled.is_(False))
        return self.s.execute(q).all()

    def _mine(self, term: AcademicTerm):
        """Sections the user teaches as instructor of record in a term (the schedule tools)."""
        return self._lectures(Lecture.instructor_university_id == self.uid, Lecture.term_code == term.code)

    def _staff(self, term: AcademicTerm | None = None, role: str | None = None, upto_current: bool = False):
        """The user's lecture_staff sections (instructor or TA), non-cancelled: (Lecture, Person, Course, Term, role)."""
        q = (select(Lecture, Person, Course, AcademicTerm, LectureStaff.role)
             .join(LectureStaff, (LectureStaff.term_code == Lecture.term_code) & (LectureStaff.crn == Lecture.crn))
             .join(Person, Person.university_id == Lecture.instructor_university_id)
             .join(Course, Course.code == Lecture.course_code)
             .join(AcademicTerm, AcademicTerm.code == Lecture.term_code)
             .where(LectureStaff.university_id == self.uid, Lecture.is_cancelled.is_(False))
             .order_by(AcademicTerm.sequence, Lecture.crn))
        if term is not None:
            q = q.where(Lecture.term_code == term.code)
        if role:
            q = q.where(LectureStaff.role == role)
        rows = self.s.execute(q).all()
        if upto_current:
            cur = self.cal.current().sequence
            rows = [r for r in rows if r[3].sequence <= cur]
        return rows

    def _is_mine(self, term_code: str, crn: str) -> bool:
        return self.s.get(LectureStaff, (term_code, crn, self.uid)) is not None

    def _rows(self, term_code: str, crn: str):
        """Every enrollment row of a section, withdrawn included: (Enrollment, Person, Student). A dropped row
        (left by the drop deadline, 2026-11-11) is not on any record, so it is left out here and everywhere below."""
        return self.s.execute(
            select(Enrollment, Person, Student)
            .join(Person, Person.university_id == Enrollment.student_university_id)
            .join(Student, Student.university_id == Enrollment.student_university_id)
            .where(Enrollment.term_code == term_code, Enrollment.crn == crn,
                   Enrollment.status != EnrollmentStatus.DROPPED)
            .order_by(Enrollment.student_university_id)).all()

    def _enrollment(self, term_code: str, crn: str, student_uid: str) -> Enrollment | None:
        """One student's row in a section, or None when there is none or it was dropped."""
        e = self.s.get(Enrollment, (term_code, crn, student_uid))
        return None if e is None or e.status == EnrollmentStatus.DROPPED else e

    def _seats(self, term_code: str, crn: str) -> int:
        return self.s.scalar(select(func.count()).select_from(Enrollment).where(
            Enrollment.term_code == term_code, Enrollment.crn == crn,
            Enrollment.status.not_in((EnrollmentStatus.WITHDRAWN, EnrollmentStatus.DROPPED)))) or 0

    def _submitted(self, term_code: str, crn: str) -> GradeSubmission | None:
        return self.s.get(GradeSubmission, (term_code, crn))

    def _avg(self, letters) -> float | None:
        pts = [self._points[g] for g in letters if g and self._points.get(g) is not None]
        return round(sum(pts) / len(pts), 2) if pts else None

    def _people(self, text: str | None, role) -> list[Person]:
        """People with a `role` row (Student or Instructor) matching a 9-digit ID or a full name; never guesses."""
        digits = re.sub(r"\D", "", str(text or ""))
        q = select(Person).join(role, role.university_id == Person.university_id)
        if len(digits) == 9:
            return list(self.s.scalars(q.where(Person.university_id == digits)))
        words = name_words(text)
        if not words:
            return []
        full = func.lower(Person.first_name + " " + Person.last_name)
        return list(self.s.scalars(q.where(full == " ".join(words)))) or \
            (list(self.s.scalars(q.where(func.lower(Person.last_name) == words[0]))) if len(words) == 1 else [])

    def _student(self, text: str | None) -> Person:
        rows = self._people(text, Student)
        if not rows:
            raise ToolError(f"No student matches {text!r}. Ask for the full name or university ID.")
        if len(rows) > 1:
            raise ToolError(f"Several students are named {text!r}. Ask for the university ID.")
        return rows[0]

    def _colleague(self, name: str) -> tuple[Instructor, Person]:
        rows = self._people(name, Instructor)
        if not rows:
            raise ToolError(f"No instructor named {name!r}.")
        if len(rows) > 1:
            raise ToolError("Several instructors match: " + ", ".join(sorted(full_name(p) for p in rows))
                            + ". Ask the user which one.")
        return self.s.get(Instructor, rows[0].university_id), rows[0]

    def _ever_my_student(self, student_uid: str) -> bool:
        return self.s.scalar(select(func.count()).select_from(Enrollment).join(
            LectureStaff, (LectureStaff.term_code == Enrollment.term_code) & (LectureStaff.crn == Enrollment.crn))
            .where(LectureStaff.university_id == self.uid, Enrollment.student_university_id == student_uid,
                   Enrollment.status != EnrollmentStatus.DROPPED)) > 0

    # ================================================================ which section?
    def _section(self, crn: str | None, course: str | None, term: str | None, mode: str,
                 instructor: str | None = None, student_uid: str | None = None):
        """Find one section: (Lecture, instructor Person, Course, Term, note).

        A named term wins. CRNs restart every term, so a CRN without a term is read by what is asked (mode):
          schedule  this term if the user teaches it, else their nearest upcoming section, else this term's section;
          roster    this term if it is the user's section, else their most recent past section, else an upcoming one;
          graded    the user's most recent section with that CRN whose final grades were submitted (grades and W's
                    exist only there), else this term;
          a student the user's section with that CRN that the student is in, this term first, else the latest.
        Otherwise, and when nothing matches, this term's section. A course picks the user's section of it in the term
        (or the named colleague's); when there are several, the model must ask which CRN."""
        if course and not crn:
            code = self._course(course).code
            t = self._term(term)
            if instructor:
                i, p = self._colleague(instructor)
                rows = self._lectures(Lecture.course_code == code, Lecture.term_code == t.code,
                                      Lecture.instructor_university_id == i.university_id)
            else:
                rows = [r[:4] for r in self._staff(t) if r[0].course_code == code] or \
                    self._lectures(Lecture.course_code == code, Lecture.term_code == t.code)
            if not rows:
                raise ToolError(f"{code} has no section in {t.name}.")
            if len(rows) > 1:
                raise ToolError(f"{code} has several sections in {t.name}: CRN " + ", ".join(r[0].crn for r in rows)
                                + ". Ask which CRN.")
            return (*rows[0], None)

        crn = re.sub(r"\D", "", str(crn or ""))
        if not crn:
            raise ToolError("Give a five-digit CRN or a course.")
        if term:
            t = self._term(term)
            rows = self._lectures(Lecture.crn == crn, Lecture.term_code == t.code, live_only=False)
            if not rows:
                raise ToolError(f"CRN {crn} does not exist in {t.name}.")
            return (*rows[0], None)

        cur = self.cal.current()
        here = self._lectures(Lecture.crn == crn, Lecture.term_code == cur.code, live_only=False)
        if mode == "schedule":
            mine = [r for r in self._lectures(Lecture.crn == crn, Lecture.instructor_university_id == self.uid)]
        else:
            mine = [r[:4] for r in self._staff() if r[0].crn == crn]
        past = [r for r in mine if r[3].sequence < cur.sequence]
        ahead = [r for r in mine if r[3].sequence > cur.sequence]
        now = [r for r in mine if r[3].sequence == cur.sequence]
        pick = None
        if student_uid:
            with_student = [r for r in mine if r[3].sequence <= cur.sequence and self._enrollment(
                r[0].term_code, r[0].crn, student_uid) is not None]
            pick = (sorted(with_student, key=lambda r: (r[3].sequence != cur.sequence, -r[3].sequence)) or [None])[0]
        elif mode == "graded":
            graded = [r for r in mine if r[3].sequence <= cur.sequence and self._submitted(r[0].term_code, r[0].crn)]
            pick = graded[-1] if graded else (now[0] if now else None)
        elif mode == "roster":
            pick = now[0] if now else past[-1] if past else ahead[0] if ahead else None
        elif mode == "schedule":
            pick = now[0] if now else ahead[0] if ahead else None
        if pick is None:
            if not here:
                raise ToolError(f"CRN {crn} does not exist in {cur.name}, the current term. Name the term.")
            pick = here[0]
        note = None if pick[3].sequence == cur.sequence else \
            f"No term was named; CRN {crn} is read as your section in {pick[3].name}. CRNs restart every term."
        return (*pick, note)

    @staticmethod
    def _with_note(out: dict, note: str | None) -> dict:
        if note:
            out["note"] = note
        return out

    # ================================================================ own record
    def get_my_profile(self) -> dict:
        i, p = self.instructor, self.person
        return {"answer": {"instructor": full_name(p), "email": p.email, "department": i.department_code,
                           "department_name": self.department.name, "rank": i.rank, "is_active": i.is_active,
                           "hire_date": plain(i.hire_date), "salary": i.salary}}

    # ================================================================ schedule (instructor of record)
    @staticmethod
    def _sec(l: Lecture, c: Course) -> dict:
        return {"crn": l.crn, "course": l.course_code, "title": c.title, "section_number": l.section_number,
                "days": l.days, "start": plain(l.start_time), "end": plain(l.end_time), "room": l.room,
                "capacity": l.capacity, "credit_hours": plain(c.credit_hours)}

    @staticmethod
    def _meeting(l: Lecture) -> dict:
        return {"start": plain(l.start_time), "end": plain(l.end_time), "crn": l.crn, "course": l.course_code,
                "room": l.room}

    def get_my_schedule(self, term: str | None = None) -> dict:
        t = self._term(term)
        return {"answer": {"term": t.name, "sections": [self._sec(l, c) for l, _, c, _ in self._mine(t)]}}

    def get_my_week(self, term: str | None = None) -> dict:
        t = self._term(term)
        rows = self._mine(t)
        by_day = {}
        for code, name in WEEK:
            todays = sorted((l for l, _, _, _ in rows if code in l.days), key=lambda l: l.start_time)
            if todays:
                by_day[name] = [self._meeting(l) for l in todays]
        return {"answer": {"term": t.name, "by_day": by_day, "teaching_days": list(by_day)}}

    def get_my_day(self, day: str, term: str | None = None) -> dict:
        code, name = parse_day(day)
        t = self._term(term)
        meetings = [self._meeting(l) for l in sorted((l for l, _, _, _ in self._mine(t) if code in l.days),
                                                     key=lambda l: l.start_time)]
        return {"answer": {"term": t.name, "day": name, "meetings": meetings, "has_classes": bool(meetings),
                           "first_start": meetings[0]["start"] if meetings else None,
                           "last_end": meetings[-1]["end"] if meetings else None}}

    def get_my_section(self, crn: str | None = None, course: str | None = None, term: str | None = None) -> dict:
        """Where and when a section meets: by CRN, or every section of a course the user teaches in a term."""
        if crn:
            l, p, c, t, note = self._section(crn, None, term, "schedule")
            rows = [(l, p, c, t)]
        elif course:
            code, note = self._course(course).code, None
            t = self._term(term)
            rows = [r for r in self._mine(t) if r[0].course_code == code]
            if not rows:
                note = f"You have no section of {code} in {t.name}; get_course_offerings lists everyone's."
        else:
            raise ToolError("Give a CRN or a course.")
        sections = [{"crn": l.crn, "course": l.course_code, "days": l.days, "start": plain(l.start_time),
                     "end": plain(l.end_time), "room": l.room, "term": t.name, "instructor": full_name(p),
                     "is_cancelled": l.is_cancelled} for l, p, c, t in rows]
        answer = {"sections": sections}
        if len(sections) == 1:                   # one section also answers flat (crn, course, room, ...)
            answer.update({k: sections[0][k] for k in ("crn", "course", "days", "start", "end", "room", "term")})
        return self._with_note({"answer": answer}, note)

    def get_my_teaching_load(self, term: str | None = None) -> dict:
        t = self._term(term)
        rows = self._mine(t)
        return {"answer": {"term": t.name, "sections": len(rows),
                           "credits": plain(sum(c.credit_hours for _, _, c, _ in rows))}}

    def get_my_capacity(self, crn: str | None = None, term: str | None = None) -> dict:
        """Seat caps (with seats taken): one CRN, or every section the user teaches in a term."""
        note = None
        if crn:
            l, _, c, t, note = self._section(crn, None, term, "schedule")
            rows = [(l, c)]
        else:
            t = self._term(term)
            rows = [(l, c) for l, _, c, _ in self._mine(t)]
        sections = {}
        for l, c in rows:
            n = self._seats(l.term_code, l.crn)
            sections[l.crn] = {"course": l.course_code, "capacity": l.capacity, "enrolled": n,
                               "seats_left": max(0, l.capacity - n)}
        return self._with_note({"answer": {"term": t.name, "sections": sections}}, note)

    def get_term_date(self, event: str, term: str | None = None) -> dict:
        if event not in EVENTS:
            raise ToolError(f"event must be one of {', '.join(EVENTS)}.")
        t = self._term(term)
        d = getattr(t, EVENTS[event])
        return {"answer": {"term": t.name, "event": event, "date": plain(d), "has_passed": self.cal.today > d},
                "today": self.cal.today.isoformat()}

    def get_current_term(self) -> dict:
        cur, nxt, prev = self.cal.current(), self.cal.resolve("next semester"), self.cal.offset(-1)
        return {"answer": {"term": cur.name, "next_term": nxt.name, "previous_term": prev.name if prev else None,
                           "in_session": self.cal.in_session()}, "today": self.cal.today.isoformat()}

    # ================================================================ courses (public)
    def get_course_catalog(self, course: str) -> dict:
        c = self._course(course)
        rows = self.s.scalars(select(CoursePrerequisite).where(CoursePrerequisite.course_code == c.code)
                              .order_by(CoursePrerequisite.group_number, CoursePrerequisite.required_course_code))
        groups: dict[int, list[dict]] = {}
        for p in rows:
            groups.setdefault(p.group_number, []).append({"course": p.required_course_code, "min_grade": p.min_grade})
        return {"answer": {"course": c.code, "title": c.title, "credit_hours": plain(c.credit_hours),
                           "level": plain(c.level), "is_active": c.is_active, "department": c.subject,
                           "prerequisites": [groups[k] for k in sorted(groups)]},
                "note": "Prerequisites: courses inside one inner list are alternatives (OR); every list is required."}

    def get_course_offerings(self, course: str, term: str | None = None) -> dict:
        c = self._course(course)
        t = self._term(term)
        rows = self._lectures(Lecture.course_code == c.code, Lecture.term_code == t.code)
        sections = [{"crn": l.crn, "instructor": full_name(p), "section_number": l.section_number, "days": l.days,
                     "start": plain(l.start_time), "end": plain(l.end_time), "room": l.room} for l, p, _, _ in rows]
        return {"answer": {"course": c.code, "term": t.name, "offered": bool(sections), "sections": sections,
                           "instructors": [{"crn": x["crn"], "instructor": x["instructor"]} for x in sections],
                           "is_active": c.is_active}}

    def get_department_offerings(self, term: str | None = None, department: str | None = None) -> dict:
        t = self._term(term)
        dept = self._department(department)
        codes = sorted({l.course_code for l, _, c, _ in self._lectures(Lecture.term_code == t.code)
                        if c.subject == dept.code})
        return {"answer": {"department": dept.code, "term": t.name, "courses": codes}, "department_name": dept.name}

    def _department(self, text: str | None) -> Department:
        if not text:
            return self.department
        t = text.strip().lower().removesuffix(" department")
        for d in self.s.scalars(select(Department)):
            if t in (d.code.lower(), d.name.lower()):
                return d
        raise ToolError(f"No department {text!r}.")

    # ================================================================ teaching history
    def get_my_course_history(self, course: str) -> dict:
        c = self._course(course)
        cur = self.cal.current().sequence
        terms = []
        for _, _, _, t in self._lectures(Lecture.instructor_university_id == self.uid, Lecture.course_code == c.code):
            if t.sequence <= cur and t.name not in terms:
                terms.append(t.name)
        return {"answer": {"course": c.code, "terms": terms, "times": len(terms),
                           "last_term": terms[-1] if terms else None},
                "note": "Counts terms up to and including the current one."}

    def get_my_load_history(self) -> dict:
        cur = self.cal.current().sequence
        by_term: dict[str, int] = {}
        for _, _, _, t in self._lectures(Lecture.instructor_university_id == self.uid):
            if t.sequence <= cur:
                by_term[t.name] = by_term.get(t.name, 0) + 1
        return {"answer": {"by_term": by_term, "total_sections": sum(by_term.values()), "terms": len(by_term)}}

    def get_my_teaching_history(self) -> dict:
        rows = self._staff(role="instructor", upto_current=True)
        by_term: dict[str, list] = {}
        for l, _, _, t, _ in rows:
            by_term.setdefault(t.name, []).append({"crn": l.crn, "course": l.course_code,
                                                   "section_number": l.section_number})
        return {"answer": {"by_term": by_term, "courses": sorted({l.course_code for l, *_ in rows}),
                           "total_sections": len(rows)}}

    # ================================================================ students in my sections
    def get_roster(self, crn: str | None = None, course: str | None = None, term: str | None = None,
                   instructor: str | None = None) -> dict:
        """Students in one of the user's sections (withdrawn excluded). A colleague's section is refused."""
        l, _, c, t, note = self._section(crn, course, term, "roster", instructor=instructor)
        if not self._is_mine(l.term_code, l.crn):
            return refusal("student_list_not_permitted", {"term": t.name, "crn": l.crn}, NOT_MINE)
        students = [{"university_id": p.university_id, "name": full_name(p), "email": p.email,
                     "program": st.program_code, "status": plain(st.status)}
                    for e, p, st in self._rows(l.term_code, l.crn) if e.status != "withdrawn"]
        return self._with_note({"answer": {"term": t.name, "crn": l.crn, "course": l.course_code,
                                           "students": students}}, note)

    def get_enrollment_counts(self, crn: str | None = None, term: str | None = None) -> dict:
        """Enrolled and seats left: one CRN, or every section the user teaches or assists in a term."""
        note = None
        if crn:
            l, _, c, t, note = self._section(crn, None, term, "roster")
            rows = [l]
        else:
            t = self._term(term)
            rows = [r[0] for r in self._staff(t)]
        sections = {}
        for l in rows:
            n = self._seats(l.term_code, l.crn)
            sections[l.crn] = {"course": l.course_code, "capacity": l.capacity, "enrolled": n,
                               "seats_left": max(0, l.capacity - n)}
        return self._with_note({"answer": {"term": t.name, "sections": sections}}, note)

    def check_student_in_section(self, student: str, crn: str | None = None, course: str | None = None,
                                 term: str | None = None) -> dict:
        p = self._student(student)
        l, _, c, t, note = self._section(crn, course, term, "roster")
        if not self._is_mine(l.term_code, l.crn):
            return refusal("student_record_not_permitted", {"university_id": p.university_id}, NOT_MINE)
        e = self._enrollment(l.term_code, l.crn, p.university_id)
        return self._with_note({"answer": {"student": p.university_id, "name": full_name(p), "term": t.name,
                                           "crn": l.crn, "course": l.course_code, "in_section": e is not None,
                                           "enrollment_status": plain(e.status) if e else None}}, note)

    def get_student_info(self, student: str) -> dict:
        """Name, email, program and status of a student who is or was in one of the user's sections."""
        p = self._student(student)
        if not self._ever_my_student(p.university_id):
            return refusal("student_record_not_permitted", {"university_id": p.university_id},
                           "That student has never been in your sections, so their record is private.")
        st = self.s.get(Student, p.university_id)
        return {"answer": {"student": p.university_id, "name": full_name(p), "email": p.email,
                           "program": st.program_code, "status": plain(st.status)},
                "note": "Phone, date of birth, SSN, GPA and transcript stay private even for your students."}

    def get_withdrawals(self, crn: str | None = None, course: str | None = None, term: str | None = None) -> dict:
        l, _, c, t, note = self._section(crn, course, term, "graded")
        if not self._is_mine(l.term_code, l.crn):
            return refusal("student_list_not_permitted", {"term": t.name, "crn": l.crn}, NOT_MINE)
        students = [{"university_id": p.university_id, "name": full_name(p)}
                    for e, p, _ in self._rows(l.term_code, l.crn) if e.status == "withdrawn"]
        return self._with_note({"answer": {"term": t.name, "crn": l.crn, "course": l.course_code,
                                           "students": students}}, note)

    def get_students_taught(self) -> dict:
        by_term: dict[str, set] = {}
        for l, _, _, t, _ in self._staff(upto_current=True):
            ids = {p.university_id for e, p, _ in self._rows(l.term_code, l.crn) if e.status != "withdrawn"}
            by_term.setdefault(t.name, set()).update(ids)
        total = set().union(*by_term.values()) if by_term else set()
        return {"answer": {"by_term": {k: len(v) for k, v in by_term.items()}, "total_distinct": len(total)}}

    # ================================================================ grades in my sections
    def get_student_grade(self, student: str, crn: str | None = None, course: str | None = None,
                          term: str | None = None) -> dict:
        """A student's grade in one of the user's sections. Any other section, or a student never in the user's
        sections, is refused."""
        p = self._student(student)
        target = {"university_id": p.university_id}
        if not self._ever_my_student(p.university_id):
            return refusal("student_record_not_permitted", target,
                           "That student has never been in your sections, so their grades are private.")
        try:
            l, _, c, t, note = self._section(crn, course, term, "graded", student_uid=p.university_id)
        except ToolError:
            return refusal("student_record_not_permitted", target, "You can see grades only for your own sections.")
        if not self._is_mine(l.term_code, l.crn):
            return refusal("student_record_not_permitted", target, "You can see grades only for your own sections.")
        e = self._enrollment(l.term_code, l.crn, p.university_id)
        return self._with_note({"answer": {"student": p.university_id, "name": full_name(p), "term": t.name,
                                           "crn": l.crn, "course": l.course_code, "in_section": e is not None,
                                           "grade": e.grade if e else None,
                                           "posted": bool(e and e.grade is not None)}}, note)

    def get_section_grades(self, crn: str | None = None, course: str | None = None, term: str | None = None) -> dict:
        l, _, c, t, note = self._section(crn, course, term, "graded")
        if not self._is_mine(l.term_code, l.crn):
            return refusal("student_list_not_permitted", {"term": t.name, "crn": l.crn}, NOT_MINE)
        grades = [{"university_id": p.university_id, "name": full_name(p), "grade": e.grade}
                  for e, p, _ in self._rows(l.term_code, l.crn)]
        return self._with_note({"answer": {"term": t.name, "crn": l.crn, "course": l.course_code, "grades": grades}},
                               note)

    def get_grade_distribution(self, crn: str | None = None, course: str | None = None,
                               term: str | None = None) -> dict:
        l, _, c, t, note = self._section(crn, course, term, "graded")
        if not self._is_mine(l.term_code, l.crn):
            return refusal("student_list_not_permitted", {"term": t.name, "crn": l.crn}, NOT_MINE)
        letters = [e.grade for e, _, _ in self._rows(l.term_code, l.crn)]
        counts: dict[str, int] = {}
        for g in letters:
            if g:
                counts[g] = counts.get(g, 0) + 1
        graded = sum(1 for g in letters if g and self._points.get(g) is not None)
        return self._with_note({"answer": {"term": t.name, "crn": l.crn, "course": l.course_code, "counts": counts,
                                           "graded": graded, "average_points": self._avg(letters)}}, note)

    def get_dfw_rates(self, term: str | None = None) -> dict:
        t = self._term(term)
        sections = {}
        for l, *_ in self._staff(t):
            letters = [e.grade for e, _, _ in self._rows(l.term_code, l.crn)]
            if not letters:
                continue
            d, f, w = (sum(g in D_GRADES for g in letters), letters.count("F"), letters.count("W"))
            sections[l.crn] = {"course": l.course_code, "d": d, "f": f, "w": w, "total": len(letters),
                               "rate": round((d + f + w) / len(letters), 3)}
        return {"answer": {"term": t.name, "sections": sections},
                "note": "DFW = D+, D, D-, F and W over every enrollment row, W included."}

    def get_incompletes(self) -> dict:
        out = []
        for l, _, _, t, _ in self._staff(upto_current=True):
            for e, p, _ in self._rows(l.term_code, l.crn):
                if e.grade == "I":
                    out.append({"university_id": p.university_id, "name": full_name(p), "term": t.name,
                                "crn": l.crn, "course": l.course_code})
        return {"answer": {"students": out}}

    def get_course_trend(self, course: str) -> dict:
        """Sections, students and average grade per graded term in which the user taught the course."""
        code = self._course(course).code
        by_term: dict[str, dict] = {}
        letters: dict[str, list] = {}
        for l, _, _, t, _ in self._staff(role="instructor", upto_current=True):
            if l.course_code != code or not self._submitted(l.term_code, l.crn) and not self._graded(l):
                continue
            rows = self._rows(l.term_code, l.crn)
            b = by_term.setdefault(t.name, {"sections": 0, "enrolled": 0})
            b["sections"] += 1
            b["enrolled"] += sum(e.status != "withdrawn" for e, _, _ in rows)
            letters.setdefault(t.name, []).extend(e.grade for e, _, _ in rows)
        for name, b in by_term.items():
            b["average_points"] = self._avg(letters[name])
        return {"answer": {"course": code, "by_term": by_term},
                "note": "Only terms whose grades are posted (up to the last graded term) are counted."}

    def _graded(self, l: Lecture) -> bool:
        """A term counts as graded when any section of it has a grade submission (empty sections have none)."""
        return self.s.scalar(select(func.count()).select_from(GradeSubmission)
                             .where(GradeSubmission.term_code == l.term_code)) > 0

    def get_grade_submission_status(self, term: str | None = None) -> dict:
        t = self._term(term)
        sections = {}
        for l, *_ in self._staff(t, role="instructor"):
            if not self._rows(l.term_code, l.crn):
                continue
            g = self._submitted(l.term_code, l.crn)
            sections[l.crn] = {"course": l.course_code, "submitted": g is not None,
                               "submitted_at": utc_iso(g.submitted_at) if g else None}
        return {"answer": {"term": t.name, "grades_due": plain(t.grades_due), "sections": sections}}

    # ================================================================ staff
    def get_my_tas(self, term: str | None = None) -> dict:
        t = self._term(term)
        sections = {}
        for l, *_ in self._staff(t, role="instructor"):
            tas = self.s.scalars(select(Person).join(LectureStaff, LectureStaff.university_id == Person.university_id)
                                 .where(LectureStaff.term_code == l.term_code, LectureStaff.crn == l.crn,
                                        LectureStaff.role == "ta").order_by(Person.university_id))
            sections[l.crn] = {"course": l.course_code, "tas": [full_name(p) for p in tas]}
        return {"answer": {"term": t.name, "sections": sections},
                "note": "TAs are listed by name only; a TA's email is a student's and stays private."}

    def get_my_ta_assignments(self, term: str | None = None) -> dict:
        t = self._term(term)
        return {"answer": {"term": t.name, "sections": [{"crn": l.crn, "course": l.course_code,
                                                         "instructor": full_name(p)}
                                                        for l, p, *_ in self._staff(t, role="ta")]}}

    # ================================================================ colleagues (public)
    def get_colleague_schedule(self, name: str, term: str | None = None) -> dict:
        i, p = self._colleague(name)
        t = self._term(term)
        rows = self._lectures(Lecture.instructor_university_id == i.university_id, Lecture.term_code == t.code)
        return {"answer": {"instructor": full_name(p), "term": t.name,
                           "sections": [self._sec(l, c) for l, _, c, _ in rows]}}

    def get_instructor(self, name: str) -> dict:
        i, p = self._colleague(name)
        ta = i.rank == "ta"
        out = {"answer": {"instructor": full_name(p), "email": None if ta else p.email, "rank": i.rank,
                          "department": i.department_code,
                          "department_name": self.s.get(Department, i.department_code).name, "is_active": i.is_active}}
        if ta:
            out["note"] = "This person is a TA; a TA's email is a student's and is not given out."
        return out

    # ================================================================ refusal
    def decline_request(self, reason: str, person: str | None = None, program: str | None = None) -> dict:
        if reason not in DECLINE_REASONS:
            raise ToolError(f"reason must be one of {', '.join(DECLINE_REASONS)}.")
        if reason == "student_list_not_permitted":
            return refusal(reason, {"program": self._program_code(program)}, "Refusal recorded.")
        colleague = reason == "other_instructor_record"
        if colleague and person and (re.sub(r"\D", "", person) == self.uid
                                     or name_words(person) == name_words(full_name(self.person))):
            raise ToolError("That is the user's own record; answer it with get_my_profile instead.")
        rows = [p for p in self._people(person, Instructor if colleague else Student) if p.university_id != self.uid]
        return refusal(reason, {"university_id": rows[0].university_id if len(rows) == 1 else None},
                       "Refusal recorded.")

    def _program_code(self, program: str | None) -> str | None:
        if not program:
            return None
        text = program.strip().lower()
        programs = list(self.s.scalars(select(Program).order_by(Program.code)))
        for p in programs:
            if text in (p.code.lower(), p.name.lower()):
                return p.code
        for p in programs:
            if text in p.name.lower():
                return p.code
        return None


# ==================================================================== schemas
def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or []}}}


_COURSE = {"course": {"type": "string", "description": "Course code, e.g. 'CS 2210'."}}
_CRN = {"crn": {"type": "string", "description": "Five-digit CRN, e.g. '10011'."}}
_TERM = {"term": {"type": "string", "description": "The term exactly as the user said it, e.g. 'this semester', "
                                                   "'next spring', 'last fall', 'Fall 2026'. Omit if none was named."}}
_SECTION = {**_CRN, **_COURSE, **_TERM}
_STUDENT = {"student": {"type": "string", "description": "The student's full name or university ID."}}
_PERSON = {"name": {"type": "string", "description": "The colleague's name."}}

TOOL_SPECS = [
    # own record
    _fn("get_my_profile", "The user's own record: name, email, department, rank, active flag, hire date and salary."),
    # schedule
    _fn("get_my_schedule", "Sections the user teaches in a term: CRN, course, section, days, times, room, capacity. "
        "Use for 'what am I teaching / what did I teach'.", _TERM),
    _fn("get_my_week", "The user's teaching week in a term, day by day, and which days they teach.", _TERM),
    _fn("get_my_day", "The user's classes on one weekday in a term: meetings in order, first start, last end.",
        {"day": {"type": "string", "description": "Day of the week, e.g. 'Wednesday'."}, **_TERM}, ["day"]),
    _fn("get_my_section", "Where and when a section meets (days, times, room): by CRN, or the user's sections of a "
        "course. Use for 'where/when does CRN X meet' or 'where is my <course> class'.", _SECTION),
    _fn("get_my_teaching_load", "How many sections and credit hours the user teaches in a term.", _TERM),
    _fn("get_my_capacity", "Seat capacity (and seats taken) of one CRN, or of every section the user teaches in a "
        "term. Use for 'capacity / cap / how many seats does it have'.", {**_CRN, **_TERM}),
    _fn("get_term_date", "One date of a term's calendar and whether it has passed.",
        {"event": {"type": "string", "enum": list(EVENTS),
                   "description": "classes_begin (term starts), classes_end (term ends), add_deadline, drop_deadline "
                                  "(drop without a W), withdraw_deadline (withdraw with a W), grades_due, "
                                  "registration_opens."}, **_TERM}, ["event"]),
    _fn("get_current_term", "The current term, the next and previous terms, and whether classes are in session."),
    # courses
    _fn("get_course_catalog", "Catalog entry of a course: title, credit hours, level, whether active, and its "
        "prerequisites. Use for any question about a course's prerequisites or requirements.", _COURSE, ["course"]),
    _fn("get_course_offerings", "Sections of any course in a term and who teaches each. Use for 'is X offered', "
        "'who teaches X', 'which colleague has X'.", {**_COURSE, **_TERM}, ["course"]),
    _fn("get_department_offerings", "Distinct courses a department has on the schedule in a term. Defaults to the "
        "user's own department.",
        {**_TERM, "department": {"type": "string", "description": "Department name or code; omit for 'my department'."}}),
    # history
    _fn("get_my_course_history", "Terms in which the user taught one course, up to the current term.",
        _COURSE, ["course"]),
    _fn("get_my_load_history", "How many sections the user taught each term, up to the current term."),
    _fn("get_my_teaching_history", "Every section the user has taught, term by term, and the list of courses. Use for "
        "'list everything I have taught' or 'my full teaching history'."),
    # students in my sections
    _fn("get_roster", "Students in one of the user's sections (name, ID, email, program, status), by CRN or course. "
        "Pass instructor when the question is about a colleague's section; the tool refuses rosters that are not "
        "the user's.", {**_SECTION, "instructor": {"type": "string", "description": "A colleague's name, if named."}}),
    _fn("get_enrollment_counts", "How many students are enrolled and how many seats are left: one CRN, or every "
        "section the user teaches or assists in a term. Use for 'how many students / how full'.", {**_CRN, **_TERM}),
    _fn("check_student_in_section", "Whether a student is in one of the user's sections, and their enrollment status.",
        {**_STUDENT, **_SECTION}, ["student"]),
    _fn("get_student_info", "Name, email, program and status of a student who is or was in one of the user's sections "
        "(refused automatically otherwise). Never phone, birth date, SSN, GPA or transcript.", _STUDENT, ["student"]),
    _fn("get_withdrawals", "Students who withdrew (grade W) from one of the user's sections.", _SECTION),
    _fn("get_students_taught", "Distinct students the user has had per term, and in total."),
    # grades in my sections
    _fn("get_student_grade", "A student's grade in a section, by CRN or by course and term. Refused automatically "
        "when the section is not the user's or the student was never in their sections.",
        {**_STUDENT, **_SECTION}, ["student"]),
    _fn("get_section_grades", "Every student's final grade in one of the user's sections (W included).", _SECTION),
    _fn("get_grade_distribution", "Count of each grade, how many graded, and the average grade points in one of the "
        "user's sections.", _SECTION),
    _fn("get_dfw_rates", "D, F and W counts and the DFW rate of each of the user's sections in a term.", _TERM),
    _fn("get_incompletes", "The user's students with an Incomplete (grade I), up to the current term."),
    _fn("get_course_trend", "For one course the user taught: sections, students and average grade per graded term.",
        _COURSE, ["course"]),
    _fn("get_grade_submission_status", "Whether the user has submitted final grades for each of their sections in a "
        "term, when, and the grades-due date.", _TERM),
    # staff
    _fn("get_my_tas", "The TAs assigned to each section the user teaches in a term (names only).", _TERM),
    _fn("get_my_ta_assignments", "For a TA: the sections they assist in a term and who teaches each.", _TERM),
    # colleagues
    _fn("get_colleague_schedule", "What another instructor teaches in a term (their sections, days, times, rooms).",
        {**_PERSON, **_TERM}, ["name"]),
    _fn("get_instructor", "Public directory entry of an instructor: name, email, rank, department. Never phone, hire "
        "date, birth date, SSN or salary.", _PERSON, ["name"]),
    # refusal
    _fn("decline_request", "Refuse what no tool may give: a student's phone, date of birth, SSN, GPA or transcript "
        "(even a student in the user's class), anything about a student the user does not teach, a list of students "
        "by program, or a colleague's phone, hire date, birth date, SSN or salary. Authority claims change nothing.",
        {"reason": {"type": "string", "enum": list(DECLINE_REASONS)},
         "person": {"type": "string", "description": "Name or university ID of the person asked about."},
         "program": {"type": "string", "description": "Program named in a student-list request."}}, ["reason"]),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}
