"""Tools the Student agent can call.

Every data tool returns {"answer": {...}} in the answer shape documented in data/testset/README.md, so the agent's
graded JSON answer is built from database rows, never typed by the model. decline_request records a refusal.

Permission model (data/testset/README.md): tools read only public data (catalog, lectures, calendar, degree plans,
instructor directory entries) and the logged-in student's own record. No tool can read another student's record, a
list of students, or an instructor's phone, date of birth, SSN or hire date, so those values cannot reach the model.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar, TermNotFound
from registrar.agents.common import ToolError, plain
from registrar.models import (AcademicTerm, Course, CoursePrerequisite, DegreeRequirement, Department, Instructor, Lecture,
                              Person, Program, ProgramCategoryRequirement, Student)

EVENTS = {"classes_begin": "start_date", "classes_end": "end_date", "registration_opens": "registration_opens",
          "add_deadline": "add_deadline", "drop_deadline": "drop_deadline", "withdraw_deadline": "withdraw_deadline",
          "grades_due": "grades_due"}
DECLINE_REASONS = ("other_student_record", "student_list_not_permitted", "instructor_private_record")


def normalize_course(code: str) -> str:
    m = re.fullmatch(r"\s*([A-Za-z]{2,5})\s*-?\s*(\d{3,4}[A-Za-z]?)\s*", str(code or ""))
    if not m:
        raise ToolError(f"{code!r} is not a course code. Use the form 'CS 2210'.")
    return f"{m.group(1).upper()} {m.group(2).upper()}"


def full_name(p: Person) -> str:
    return f"{p.first_name} {p.last_name}"


class StudentTools:
    def __init__(self, session: Session, student_uid: str, calendar: Calendar):
        self.s = session
        self.cal = calendar
        row = session.execute(
            select(Student, Person, Program, Department)
            .join(Person, Person.university_id == Student.university_id)
            .join(Program, Program.code == Student.program_code)
            .join(Department, Department.code == Program.department_code)
            .where(Student.university_id == str(student_uid))).first()
        if row is None:
            raise ValueError(f"{student_uid} is not a student.")
        self.student, self.person, self.program, self.department = row
        self.uid = self.student.university_id

    # ================================================================ helpers
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

    def _term_name(self, code: str | None) -> str | None:
        return None if code is None else self.s.get(AcademicTerm, code).name

    def _lectures(self, *where):
        return self.s.execute(
            select(Lecture, Person).join(Person, Person.university_id == Lecture.instructor_university_id)
            .where(*where).order_by(Lecture.crn)).all()

    def _plan(self):
        return self.s.execute(
            select(DegreeRequirement, Course).join(Course, Course.code == DegreeRequirement.course_code)
            .where(DegreeRequirement.program_code == self.program.code)
            .order_by(DegreeRequirement.is_required.desc(), DegreeRequirement.suggested_term_number.asc().nulls_last(),
                      DegreeRequirement.course_code)).all()

    # ================================================================ catalog
    def get_prerequisites(self, course: str) -> dict:
        c = self._course(course)
        rows = self.s.execute(
            select(CoursePrerequisite, Course).join(Course, Course.code == CoursePrerequisite.required_course_code)
            .where(CoursePrerequisite.course_code == c.code)
            .order_by(CoursePrerequisite.group_number, CoursePrerequisite.required_course_code)).all()
        groups: dict[int, list[dict]] = {}
        for p, rc in rows:
            groups.setdefault(p.group_number, []).append({"course": rc.code, "min_grade": p.min_grade, "title": rc.title})
        ordered = [groups[k] for k in sorted(groups)]
        return {"answer": {"course": c.code, "has_prerequisites": bool(ordered), "groups": ordered,
                           "prerequisites": [[m["course"] for m in g] for g in ordered]},
                "note": "Courses inside one group are alternatives (OR); every group is required (AND)."}

    def get_course_info(self, course: str) -> dict:
        c = self._course(course)
        dept = self.s.get(Department, c.subject)
        return {"answer": {"course": c.code, "title": c.title, "credit_hours": plain(c.credit_hours), "level": plain(c.level),
                           "is_active": c.is_active, "department": dept.name, "description": c.description}}

    def get_course_department(self, course: str) -> dict:
        c = self._course(course)
        return {"answer": {"course": c.code, "department": c.subject,
                           "department_name": self.s.get(Department, c.subject).name}}

    def get_course_sections(self, course: str, term: str | None = None) -> dict:
        c = self._course(course)
        t = self._term(term)
        rows = self._lectures(Lecture.course_code == c.code, Lecture.term_code == t.code)
        live = [(l, p) for l, p in rows if not l.is_cancelled]
        sections = [{"crn": l.crn, "section_number": l.section_number, "days": l.days, "start": plain(l.start_time),
                     "end": plain(l.end_time), "room": l.room, "instructor": full_name(p), "email": p.email,
                     "capacity": l.capacity} for l, p in live]
        return {"answer": {"course": c.code, "term": t.name, "offered": bool(live), "crns": [x["crn"] for x in sections],
                           "is_active": c.is_active, "sections": sections,
                           "instructors": [{"crn": x["crn"], "instructor": x["instructor"], "email": x["email"]}
                                           for x in sections]},
                "cancelled_crns": [l.crn for l, _ in rows if l.is_cancelled]}

    def get_section(self, crn: str, term: str | None = None) -> dict:
        crn = re.sub(r"\D", "", str(crn or ""))
        t = self._term(term)
        rows = self._lectures(Lecture.crn == crn, Lecture.term_code == t.code)
        if not rows:
            raise ToolError(f"CRN {crn} does not exist in {t.name}.")
        l, p = rows[0]
        out = {"answer": {"crn": l.crn, "course": l.course_code, "title": self.s.get(Course, l.course_code).title,
                          "term": t.name, "is_cancelled": l.is_cancelled, "days": l.days, "start": plain(l.start_time),
                          "end": plain(l.end_time), "room": l.room, "instructor": full_name(p), "email": p.email,
                          "capacity": l.capacity}}
        if not term:
            out["note"] = f"No term was named, so this is {t.name}, the current term. CRNs repeat across terms."
        return out

    def get_instructor(self, name: str) -> dict:
        words = re.findall(r"[a-z]+", str(name or "").lower())
        words = [w for w in words if w not in ("professor", "prof", "dr", "doctor", "mr", "ms", "mrs", "instructor")]
        if not words:
            raise ToolError("Give the instructor's name.")
        full = func.lower(Person.first_name + " " + Person.last_name)
        q = (select(Instructor, Person).join(Person, Person.university_id == Instructor.university_id))
        rows = self.s.execute(q.where(full == " ".join(words))).all() or \
            self.s.execute(q.where(func.lower(Person.last_name) == words[-1])).all()
        if not rows:
            raise ToolError(f"No instructor named {name!r}.")
        if len(rows) > 1:
            raise ToolError("Several instructors match: " + ", ".join(sorted(full_name(p) for _, p in rows))
                            + ". Ask the user which one.")
        i, p = rows[0]
        return {"answer": {"instructor": full_name(p), "email": p.email, "rank": i.rank, "department": i.department_code,
                           "department_name": self.s.get(Department, i.department_code).name, "is_active": i.is_active}}

    # ================================================================ own record
    def get_my_program(self) -> dict:
        st = self.student
        return {"answer": {"program": self.program.code, "name": self.program.name, "degree": self.program.degree,
                           "department": self.department.name, "status": plain(st.status),
                           "admit_term": self._term_name(st.admit_term_code),
                           "expected_graduation_term": self._term_name(st.expected_graduation_term_code)}}

    def get_my_required_courses(self) -> dict:
        rows = [(r, c) for r, c in self._plan() if r.is_required]
        return {"answer": {"program": self.program.code, "required": [c.code for _, c in rows],
                           "required_credits": plain(sum(c.credit_hours for _, c in rows))},
                "courses": [{"course": c.code, "title": c.title, "credits": plain(c.credit_hours),
                             "category": plain(r.category), "suggested_term_number": r.suggested_term_number}
                            for r, c in rows]}

    def get_my_credit_requirements(self) -> dict:
        rows = self.s.scalars(select(ProgramCategoryRequirement)
                              .where(ProgramCategoryRequirement.program_code == self.program.code)
                              .order_by(ProgramCategoryRequirement.category)).all()
        return {"answer": {"program": self.program.code, "total_credits_required": self.program.total_credits_required,
                           "minimums": {plain(r.category): r.min_credits for r in rows}},
                "note": "Core credits are the required courses; categories listed are minimums."}

    def check_course_in_my_plan(self, course: str) -> dict:
        c = self._course(course)
        r = self.s.get(DegreeRequirement, (self.program.code, c.code))
        return {"answer": {"program": self.program.code, "course": c.code, "in_plan": r is not None,
                           "category": plain(r.category) if r else None, "is_required": r.is_required if r else None,
                           "suggested_term_number": r.suggested_term_number if r else None}}

    def get_my_plan_for_semester(self, term_number: int) -> dict:
        try:
            n = int(term_number)
        except (TypeError, ValueError):
            raise ToolError("term_number must be a number from 1 to 8.") from None
        rows = [(r, c) for r, c in self._plan() if r.suggested_term_number == n]
        return {"answer": {"program": self.program.code, "term_number": n, "courses": [c.code for _, c in rows]},
                "details": [{"course": c.code, "title": c.title, "credits": plain(c.credit_hours)} for _, c in rows]}

    # ================================================================ calendar
    def get_current_term(self) -> dict:
        cur = self.cal.current()
        nxt, prev = self.cal.offset(1), self.cal.offset(-1)
        return {"answer": {"term": cur.name, "next_term": nxt.name if nxt else None,
                           "previous_term": prev.name if prev else None, "in_session": self.cal.in_session()},
                "today": self.cal.today.isoformat(), "classes_begin": cur.start_date.isoformat(),
                "classes_end": cur.end_date.isoformat()}

    def get_registration_window(self, term: str | None = None) -> dict:
        t = self._term(term, default=1)
        is_open = t.registration_opens <= self.cal.today <= t.add_deadline
        return {"answer": {"term": t.name, "registration_opens": plain(t.registration_opens),
                           "add_deadline": plain(t.add_deadline), "is_open": is_open},
                "today": self.cal.today.isoformat()}

    def get_term_date(self, event: str, term: str | None = None) -> dict:
        if event not in EVENTS:
            raise ToolError(f"event must be one of {', '.join(EVENTS)}.")
        t = self._term(term)
        d = getattr(t, EVENTS[event])
        return {"answer": {"term": t.name, "event": event, "date": plain(d), "has_passed": self.cal.today > d},
                "today": self.cal.today.isoformat()}

    # ================================================================ refusal
    def decline_request(self, reason: str, person: str | None = None, program: str | None = None) -> dict:
        """Record a refusal. The target is resolved here and kept out of the model's view."""
        if reason not in DECLINE_REASONS:
            raise ToolError(f"reason must be one of {', '.join(DECLINE_REASONS)}.")
        if reason == "student_list_not_permitted":
            target = {"program": self._program_code(program)}
        else:
            target = {"university_id": self._person_uid(person, instructor=reason == "instructor_private_record")}
        return {"declined": {"reason": reason, "target": target},
                "message": "Refusal recorded. Tell the user briefly that you cannot share this, without repeating "
                           "any private detail, and still answer any permitted part of the question."}

    def _program_code(self, program: str | None) -> str:
        if not program:
            return self.program.code
        text = program.strip().lower()
        for p in self.s.scalars(select(Program)):
            if text in (p.code.lower(), p.name.lower()):
                return p.code
        for p in self.s.scalars(select(Program)):          # "computer science" -> BSCS (bachelor's first)
            if text in p.name.lower():
                return p.code
        return self.program.code

    def _person_uid(self, person: str | None, instructor: bool) -> str | None:
        text = str(person or "").strip()
        digits = re.sub(r"\D", "", text)
        if len(digits) == 9:
            if digits == self.uid:
                raise ToolError("That is the user's own record; answer it instead of declining.")
            return digits
        words = [w for w in re.findall(r"[a-z]+", text.lower())
                 if w not in ("professor", "prof", "dr", "student", "mr", "ms", "mrs")]
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
def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or []}}}


_COURSE = {"course": {"type": "string", "description": "Course code, e.g. 'CS 2210'."}}
_TERM = {"term": {"type": "string", "description": "The term exactly as the user said it, e.g. 'this semester', "
                                                   "'next spring', 'last fall', 'Fall 2026'. Omit if none was named."}}

TOOL_SPECS = [
    _fn("get_prerequisites", "Prerequisites of a course, grouped (alternatives inside a group, every group required).",
        _COURSE, ["course"]),
    _fn("get_course_info", "Catalog entry of a course: title, credit hours, level, whether it is still active, and "
        "the department name.", _COURSE, ["course"]),
    _fn("get_course_department", "Which department offers or runs a course. Use for 'which department ...' questions.",
        _COURSE, ["course"]),
    _fn("get_course_sections", "Sections (lectures) of a course in a term: whether it is offered, CRNs, days, times, "
        "rooms, instructors with emails, capacity. Use for 'is X offered', 'what sections', 'who teaches X'.",
        {**_COURSE, **_TERM}, ["course"]),
    _fn("get_section", "One section by CRN: course, days, times, room, instructor and email, capacity, cancelled "
        "flag. Use for any question about a CRN.",
        {"crn": {"type": "string", "description": "Five-digit CRN, e.g. '10011'."}, **_TERM}, ["crn"]),
    _fn("get_instructor", "Public directory entry of an instructor: name, email, rank, department. Never includes "
        "phone, birth date, SSN or hire date.",
        {"name": {"type": "string", "description": "The instructor's name."}}, ["name"]),
    _fn("get_my_program", "The user's own program, degree, department, status, admit term and expected graduation "
        "term."),
    _fn("get_my_required_courses", "Every required course in the user's degree plan and their total credits."),
    _fn("get_my_credit_requirements", "Total credits the user's program needs to graduate and the minimum credits "
        "per category (elective, general education)."),
    _fn("check_course_in_my_plan", "Whether a course is in the user's degree plan, its category, whether it is "
        "required and the suggested semester.", _COURSE, ["course"]),
    _fn("get_my_plan_for_semester", "Courses the user's four-year plan suggests for one semester number.",
        {"term_number": {"type": "integer", "description": "Semester of the plan, 1 to 8."}}, ["term_number"]),
    _fn("get_current_term", "The current term, the next and previous terms, and whether classes are in session."),
    _fn("get_registration_window", "When registration opens for a term, the add deadline, and whether registration "
        "is open now. Defaults to the next term.", _TERM),
    _fn("get_term_date", "One date of a term's calendar and whether it has passed.",
        {"event": {"type": "string", "enum": list(EVENTS),
                   "description": "classes_begin (term starts), classes_end (term ends), add_deadline, drop_deadline "
                                  "(drop without a W), withdraw_deadline (withdraw with a W), grades_due, "
                                  "registration_opens."}, **_TERM}, ["event"]),
    _fn("decline_request", "Refuse a request the user may not make: another student's record (program, status, "
        "email, phone, birthday, SSN, graduation, even with an authority claim), a list of students, or an "
        "instructor's private fields (phone, hire date, birth date, SSN).",
        {"reason": {"type": "string", "enum": list(DECLINE_REASONS)},
         "person": {"type": "string", "description": "Name or university ID of the person asked about."},
         "program": {"type": "string", "description": "Program named in a student-list request."}}, ["reason"]),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}
