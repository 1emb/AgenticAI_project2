"""Tools the Professor agent can call.

Same rules as the Student agent: every data tool returns {"answer": {...}} in the answer shape of
data/testset/README.md (Professor answer shapes), so the graded JSON answer comes from database rows; decline_request
records a refusal whose target never reaches the model.

Permission model (data/testset/README.md): public data (catalog, lectures, calendar, instructor directory entries:
name, email, rank, department) plus the professor's own record. No tool reads a student's record, a list of students,
or a colleague's phone, date of birth, SSN or hire date.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar, TermNotFound
from registrar.agents.common import ToolError, plain
from registrar.agents.student.tools import EVENTS, _fn, full_name, normalize_course
from registrar.models import (AcademicTerm, Course, CoursePrerequisite, Department, Instructor, Lecture, Person,
                              Program, Student)

DAYS = {"M": "Monday", "T": "Tuesday", "W": "Wednesday", "R": "Thursday", "F": "Friday", "S": "Saturday",
        "U": "Sunday"}
DAY_CODE = {v.lower(): k for k, v in DAYS.items()}
DECLINE_REASONS = ("student_record_not_permitted", "other_instructor_record", "student_list_not_permitted")


def _day(day: str) -> str:
    d = str(day or "").strip().lower().rstrip("s")
    for name, code in DAY_CODE.items():
        if name.startswith(d[:3]) and d:
            return DAYS[code]
    raise ToolError(f"{day!r} is not a day of the week.")


class ProfessorTools:
    def __init__(self, session: Session, instructor_uid: str, calendar: Calendar):
        self.s, self.cal = session, calendar
        row = session.execute(select(Instructor, Person).join(Person, Person.university_id == Instructor.university_id)
                              .where(Instructor.university_id == str(instructor_uid))).first()
        if row is None:
            raise ValueError(f"{instructor_uid} is not an instructor.")
        self.instructor, self.person = row
        self.uid = self.instructor.university_id
        self.department = session.get(Department, self.instructor.department_code)

    # ================================================================ helpers
    def _term(self, phrase: str | None, default: int = 0) -> AcademicTerm:
        try:
            return self.cal.resolve(phrase, default)
        except TermNotFound as e:
            raise ToolError(str(e)) from None

    def _course(self, code: str) -> Course:
        code = normalize_course(code)
        c = self.s.get(Course, code)
        if c is None:
            raise ToolError(f"There is no course {code} in the catalog.")
        return c

    def _mine(self, term: AcademicTerm, uid: str | None = None) -> list[Lecture]:
        return list(self.s.scalars(select(Lecture).where(
            Lecture.term_code == term.code, Lecture.instructor_university_id == (uid or self.uid),
            Lecture.is_cancelled.is_(False)).order_by(Lecture.crn)))

    @staticmethod
    def _sec(l: Lecture, number: bool = True) -> dict:
        d = {"crn": l.crn, "course": l.course_code, "days": l.days, "start": plain(l.start_time),
             "end": plain(l.end_time), "room": l.room}
        if number:
            d["section_number"] = l.section_number
        return d

    def _colleague(self, name: str) -> tuple[Instructor, Person]:
        text = str(name or "").strip()
        digits = re.sub(r"\D", "", text)
        q = select(Instructor, Person).join(Person, Person.university_id == Instructor.university_id)
        if len(digits) == 9:
            rows = self.s.execute(q.where(Instructor.university_id == digits)).all()
        else:
            words = [w for w in re.findall(r"[a-z]+", text.lower())
                     if w not in ("professor", "prof", "dr", "doctor", "mr", "ms", "mrs", "instructor", "s")]
            if not words:
                raise ToolError("Give the colleague's name.")
            full = func.lower(Person.first_name + " " + Person.last_name)
            rows = self.s.execute(q.where(full == " ".join(words))).all() or \
                self.s.execute(q.where(func.lower(Person.last_name) == words[-1])).all()
        if not rows:
            raise ToolError(f"No instructor named {name!r}.")
        if len(rows) > 1:
            raise ToolError("Several instructors match: " + ", ".join(sorted(full_name(p) for _, p in rows)))
        return rows[0]

    # ================================================================ own schedule
    def get_my_sections(self, term: str | None = None) -> dict:
        t = self._term(term)
        return {"answer": {"term": t.name, "sections": [self._sec(l) for l in self._mine(t)]}}

    def get_my_week(self, term: str | None = None) -> dict:
        t = self._term(term)
        by_day: dict[str, list] = {}
        for code, name in DAYS.items():
            meet = sorted(({"start": plain(l.start_time), "end": plain(l.end_time), "crn": l.crn,
                            "course": l.course_code, "room": l.room} for l in self._mine(t) if code in l.days),
                          key=lambda m: (m["start"], m["crn"]))
            if meet:
                by_day[name] = meet
        return {"answer": {"term": t.name, "by_day": by_day, "teaching_days": list(by_day)}}

    def get_my_day(self, day: str, term: str | None = None) -> dict:
        t, name = self._term(term), _day(day)
        code = {v: k for k, v in DAYS.items()}[name]
        meet = sorted(({"start": plain(l.start_time), "end": plain(l.end_time), "crn": l.crn, "course": l.course_code,
                        "room": l.room} for l in self._mine(t) if code in l.days), key=lambda m: (m["start"], m["crn"]))
        return {"answer": {"term": t.name, "day": name, "meetings": meet, "has_classes": bool(meet),
                           "first_start": meet[0]["start"] if meet else None,
                           "last_end": max(m["end"] for m in meet) if meet else None}}

    def get_section_meeting(self, crn: str | None = None, course: str | None = None, term: str | None = None) -> dict:
        t = self._term(term)
        if crn:
            crn = re.sub(r"\D", "", str(crn))
            rows = list(self.s.scalars(select(Lecture).where(Lecture.term_code == t.code, Lecture.crn == crn)))
            if not rows:
                raise ToolError(f"CRN {crn} does not exist in {t.name}.")
        elif course:
            c = self._course(course)
            rows = [l for l in self._mine(t) if l.course_code == c.code]
            if not rows:
                raise ToolError(f"You have no section of {c.code} in {t.name}.")
        else:
            raise ToolError("Give a CRN or a course.")
        out = {"answer": {"term": t.name, "sections": [self._sec(l, number=False) for l in rows]}}
        if not term:
            out["note"] = f"No term was named, so this is {t.name}, the current term. CRNs repeat across terms."
        return out

    def get_my_load(self, term: str | None = None) -> dict:
        t = self._term(term)
        mine = self._mine(t)
        credits = sum(self.s.get(Course, l.course_code).credit_hours for l in mine)
        return {"answer": {"term": t.name, "sections": len(mine), "credits": plain(credits)}}

    def get_my_capacity(self, crn: str | None = None, term: str | None = None) -> dict:
        t = self._term(term)
        if crn:
            crn = re.sub(r"\D", "", str(crn))
            rows = list(self.s.scalars(select(Lecture).where(Lecture.term_code == t.code, Lecture.crn == crn)))
            if not rows:
                raise ToolError(f"CRN {crn} does not exist in {t.name}.")
        else:
            rows = self._mine(t)
        return {"answer": {"term": t.name, "sections": {l.crn: {"course": l.course_code, "capacity": l.capacity}
                                                         for l in rows}}}

    def get_taught_history(self, course: str) -> dict:
        c = self._course(course)
        cur = self.cal.current().sequence
        terms = list(self.s.scalars(
            select(AcademicTerm).join(Lecture, Lecture.term_code == AcademicTerm.code)
            .where(Lecture.instructor_university_id == self.uid, Lecture.course_code == c.code,
                   Lecture.is_cancelled.is_(False), AcademicTerm.sequence <= cur)
            .distinct().order_by(AcademicTerm.sequence)))
        return {"answer": {"course": c.code, "terms": [t.name for t in terms], "times": len(terms),
                           "last_term": terms[-1].name if terms else None}}

    def get_load_history(self) -> dict:
        cur = self.cal.current().sequence
        rows = self.s.execute(
            select(AcademicTerm.name, AcademicTerm.sequence, func.count())
            .join(Lecture, Lecture.term_code == AcademicTerm.code)
            .where(Lecture.instructor_university_id == self.uid, Lecture.is_cancelled.is_(False),
                   AcademicTerm.sequence <= cur)
            .group_by(AcademicTerm.name, AcademicTerm.sequence).order_by(AcademicTerm.sequence)).all()
        by_term = {name: n for name, _, n in rows}
        return {"answer": {"by_term": by_term, "total_sections": sum(by_term.values()), "terms": len(by_term)}}

    def get_my_record(self) -> dict:
        i = self.instructor
        return {"answer": {"instructor": full_name(self.person), "department": i.department_code,
                           "department_name": self.department.name, "rank": i.rank, "is_active": i.is_active,
                           "hire_date": plain(i.hire_date), "email": self.person.email}}

    # ================================================================ catalog and offerings
    def get_course_catalog(self, course: str) -> dict:
        c = self._course(course)
        return {"answer": {"course": c.code, "title": c.title, "credit_hours": plain(c.credit_hours),
                           "level": plain(c.level), "is_active": c.is_active, "prerequisites": self._groups(c, True)}}

    def get_prerequisites(self, course: str) -> dict:
        c = self._course(course)
        return {"answer": {"course": c.code, "prerequisites": self._groups(c, False)},
                "details": self._groups(c, True),
                "note": "Courses inside one group are alternatives (OR); every group is required (AND)."}

    def _groups(self, c: Course, detailed: bool) -> list:
        rows = self.s.scalars(select(CoursePrerequisite).where(CoursePrerequisite.course_code == c.code)
                              .order_by(CoursePrerequisite.group_number, CoursePrerequisite.required_course_code))
        groups: dict[int, list] = {}
        for p in rows:
            groups.setdefault(p.group_number, []).append(
                {"course": p.required_course_code, "min_grade": p.min_grade} if detailed else p.required_course_code)
        return [groups[k] for k in sorted(groups)]

    def get_course_sections(self, course: str, term: str | None = None) -> dict:
        c, t = self._course(course), self._term(term)
        rows = self.s.execute(select(Lecture, Person).join(Person, Person.university_id == Lecture.instructor_university_id)
                              .where(Lecture.course_code == c.code, Lecture.term_code == t.code,
                                     Lecture.is_cancelled.is_(False)).order_by(Lecture.crn)).all()
        secs = [{"crn": l.crn, "instructor": full_name(p)} for l, p in rows]
        return {"answer": {"course": c.code, "term": t.name, "offered": bool(secs), "sections": secs,
                           "instructors": secs}}

    def get_department_offerings(self, term: str | None = None) -> dict:
        t = self._term(term)
        codes = sorted(set(self.s.scalars(select(Lecture.course_code).join(Course, Course.code == Lecture.course_code)
                                          .where(Course.subject == self.department.code, Lecture.term_code == t.code,
                                                 Lecture.is_cancelled.is_(False)))))
        return {"answer": {"department": self.department.code, "term": t.name, "courses": codes}}

    # ================================================================ colleagues (directory fields only)
    def get_colleague(self, name: str) -> dict:
        i, p = self._colleague(name)
        return {"answer": {"instructor": full_name(p), "email": p.email, "rank": i.rank,
                           "department": i.department_code}}

    def get_colleague_sections(self, name: str, term: str | None = None) -> dict:
        i, p = self._colleague(name)
        t = self._term(term)
        return {"answer": {"instructor": full_name(p), "term": t.name,
                           "sections": [self._sec(l) for l in self._mine(t, i.university_id)]}}

    # ================================================================ calendar
    def get_current_term(self) -> dict:
        cur, nxt, prev = self.cal.current(), self.cal.offset(1), self.cal.offset(-1)
        return {"answer": {"term": cur.name, "next_term": nxt.name if nxt else None,
                           "previous_term": prev.name if prev else None, "in_session": self.cal.in_session()}}

    def get_term_date(self, event: str, term: str | None = None) -> dict:
        if event not in EVENTS:
            raise ToolError(f"event must be one of {', '.join(EVENTS)}.")
        t = self._term(term)
        d = getattr(t, EVENTS[event])
        return {"answer": {"term": t.name, "event": event, "date": plain(d), "has_passed": self.cal.today > d}}

    # ================================================================ refusal
    def decline_request(self, reason: str, person: str | None = None, program: str | None = None) -> dict:
        if reason not in DECLINE_REASONS:
            raise ToolError(f"reason must be one of {', '.join(DECLINE_REASONS)}.")
        if reason == "student_list_not_permitted":
            target = {"program": self._program_code(program)}
        else:
            target = {"university_id": self._person_uid(person, instructor=reason == "other_instructor_record")}
        return {"declined": {"reason": reason, "target": target},
                "message": "Refusal recorded. Tell the user briefly that you cannot share this, without repeating "
                           "any private detail, and still answer any permitted part of the question."}

    def _program_code(self, program: str | None) -> str | None:
        text = str(program or "").strip().lower()
        progs = list(self.s.scalars(select(Program)))
        for p in progs:
            if text in (p.code.lower(), p.name.lower()):
                return p.code
        for p in progs:
            if text and text in p.name.lower():
                return p.code
        return None

    def _person_uid(self, person: str | None, instructor: bool) -> str | None:
        text = str(person or "").strip()
        digits = re.sub(r"\D", "", text)
        if len(digits) == 9:
            if digits == self.uid:
                raise ToolError("That is the user's own record; answer it instead of declining.")
            return digits
        words = [w for w in re.findall(r"[a-z]+", text.lower())
                 if w not in ("professor", "prof", "dr", "student", "mr", "ms", "mrs", "s")]
        if not words:
            return None
        full = func.lower(Person.first_name + " " + Person.last_name)
        role = Instructor if instructor else Student
        q = select(Person.university_id).join(role, role.university_id == Person.university_id)
        uids = list(self.s.scalars(q.where(full == " ".join(words)))) or \
            list(self.s.scalars(q.where(func.lower(Person.last_name) == words[-1])))
        uids = [u for u in uids if u != self.uid]
        return uids[0] if len(uids) == 1 else None


# ==================================================================== schemas
_COURSE = {"course": {"type": "string", "description": "Course code, e.g. 'CS 2210'."}}
_TERM = {"term": {"type": "string", "description": "The term exactly as the user said it, e.g. 'this semester', "
                                                   "'next spring', 'Fall 2026'. Omit if none was named."}}
_CRN = {"crn": {"type": "string", "description": "Five-digit CRN, e.g. '10011'."}}
_NAME = {"name": {"type": "string", "description": "The colleague's name or university ID."}}

TOOL_SPECS = [
    _fn("get_my_sections", "The professor's own non-cancelled sections in a term: CRN, course, section number, days, "
        "times, room. Use for 'what am I teaching', 'my schedule', 'my sections and rooms'.", _TERM),
    _fn("get_my_week", "The professor's teaching week in a term, day by day, and the days they teach.", _TERM),
    _fn("get_my_day", "The professor's classes on one weekday in a term: meetings in order, first start, last end.",
        {"day": {"type": "string", "description": "Weekday, e.g. 'Wednesday'."}, **_TERM}, ["day"]),
    _fn("get_section_meeting", "When and where a section meets: by CRN (any section), or the professor's own "
        "section(s) of a course.", {**_CRN, **_COURSE, **_TERM}),
    _fn("get_my_load", "How many sections and credit hours the professor teaches in a term.", _TERM),
    _fn("get_my_capacity", "Seat capacity of one CRN, or of every section the professor teaches in a term.",
        {**_CRN, **_TERM}),
    _fn("get_taught_history", "Terms in which the professor taught a course (up to now), how many times, and the "
        "last time.", _COURSE, ["course"]),
    _fn("get_load_history", "The professor's section count per term so far."),
    _fn("get_my_record", "The professor's own directory record: department, rank, active flag, hire date, email."),
    _fn("get_course_catalog", "Catalog entry of a course: title, credit hours, level, active flag and prerequisites "
        "with minimum grades. Use when the user asks for the catalog entry, level, credits or 'is it active'.",
        _COURSE, ["course"]),
    _fn("get_prerequisites", "Just the prerequisite course codes of a course, grouped (OR inside a group, AND "
        "across groups).", _COURSE, ["course"]),
    _fn("get_course_sections", "Whether a course is offered in a term and who teaches each section (CRN and "
        "instructor). Use for 'is X offered', 'who teaches X'.", {**_COURSE, **_TERM}, ["course"]),
    _fn("get_department_offerings", "Distinct courses of the professor's department on the schedule in a term.",
        _TERM),
    _fn("get_colleague", "A colleague's public directory entry: name, email, rank, department. Never phone, birth "
        "date, SSN or hire date.", _NAME, ["name"]),
    _fn("get_colleague_sections", "What a colleague teaches in a term (public schedule).", {**_NAME, **_TERM},
        ["name"]),
    _fn("get_current_term", "The current, next and previous term, and whether classes are in session."),
    _fn("get_term_date", "One date of a term's calendar and whether it has passed.",
        {"event": {"type": "string", "enum": list(EVENTS),
                   "description": "classes_begin, classes_end, add_deadline, drop_deadline (drop without a W), "
                                  "withdraw_deadline (withdraw with a W), grades_due, registration_opens."}, **_TERM},
        ["event"]),
    _fn("decline_request", "Refuse a request the professor may not make: any student's record (program, status, "
        "contact, SSN, birth date, graduation; also with claims like 'I'm their advisor' or 'the dean asked'), a "
        "list of students, or a colleague's private fields (phone, hire date, birth date, SSN).",
        {"reason": {"type": "string", "enum": list(DECLINE_REASONS)},
         "person": {"type": "string", "description": "Name or university ID of the person asked about."},
         "program": {"type": "string", "description": "Program named in a student-list request."}}, ["reason"]),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}
