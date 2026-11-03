"""Writes to the database: registration, drop and withdrawal for students; grade posting for instructors.

Every change goes through three steps (handbook 7.4):
  1. request_*  : validator code checks every rule and returns a pending change with a confirmation code.
                  Nothing is written.
  2. the user confirms in a LATER message (the ConfirmationGate checks this in code, not the model)
  3. confirm_change : re-validates under a row lock (so two users cannot take the last seat), writes the change and
                  its change_log row in one transaction, and commits.
Blocker codes follow the student test set's `can_add` codes where they exist (data/testset/README.md).
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar, TermNotFound
from registrar.agents.common import ToolError, plain
from registrar.agents.policy import PolicyStore
from registrar.agents.student.tools import _fn
from registrar.models import (AcademicTerm, ChangeLog, Course, CoursePrerequisite, Enrollment, GradeScale, Lecture,
                              Person, Program, Student)

AFFIRM = re.compile(r"^\s*(yes|yep|yeah|y|ok|okay|sure|confirm(ed)?|go ahead|do it|please do|correct|that'?s right|"
                    r"proceed)\b", re.I)
POSTABLE = {"A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F", "I"}


def _overlap(a: Lecture, b: Lecture) -> bool:
    return bool(set(a.days) & set(b.days)) and a.start_time < b.end_time and b.start_time < a.end_time


@dataclass
class Pending:
    code: str
    action: str
    detail: dict
    turn: int


@dataclass
class ConfirmationGate:
    """Tracks the conversation turn and the user's latest message (set by the Router before each turn)."""
    turn: int = 0
    last_user_text: str = ""
    pending: dict[str, Pending] = field(default_factory=dict)

    def new_turn(self, text: str) -> None:
        self.turn += 1
        self.last_user_text = text

    def add(self, action: str, detail: dict) -> Pending:
        p = Pending(secrets.token_hex(3).upper(), action, detail, self.turn)
        self.pending = {p.code: p}  # one pending change at a time; a new request replaces the old one
        return p

    def take(self, code: str) -> Pending:
        p = self.pending.get(str(code or "").strip().upper())
        if p is None:
            raise ToolError("There is no pending change with that code. Request the change again.")
        if self.turn <= p.turn:
            raise ToolError("Not confirmed yet: show the change to the user and wait for them to confirm it in their "
                            "next message. Do not call confirm_change in the same turn as the request.")
        if not AFFIRM.search(self.last_user_text):
            raise ToolError("The user's last message did not confirm the change. Ask them to confirm with 'yes', "
                            "or call cancel_change.")
        del self.pending[p.code]
        return p


class RegistrationService:
    """Rules and writes. No LLM here."""

    def __init__(self, session: Session, calendar: Calendar, policy: PolicyStore):
        self.s, self.cal, self.policy = session, calendar, policy
        self.points = {g.letter: (None if g.points is None else float(g.points)) for g in session.scalars(select(GradeScale))}

    def _term(self, phrase: str | None, default: int = 0) -> AcademicTerm:
        try:
            return self.cal.resolve(phrase, default)
        except TermNotFound as e:
            raise ToolError(str(e)) from None

    def grading_term(self) -> AcademicTerm | None:
        """The term whose grading window (last day of classes to grades due) contains today, if any."""
        return next((t for t in self.cal.terms if t.end_date <= self.cal.today <= t.grades_due), None)

    def term_for_grades(self, phrase: str | None) -> AcademicTerm:
        """During a grading window, 'this fall' / 'this semester' / no term mean the term being graded, not the
        next term that the README break rule makes current."""
        g = self.grading_term()
        text = (phrase or "").strip().lower()
        if g is not None and not re.search(r"\d{4}", text):
            season = next((x for x in ("fall", "spring", "summer") if x in text), None)
            if not text or season == plain(g.term_type) or re.search(r"\b(this|current)\s+(semester|term)\b", text):
                return g
        return self._term(phrase)

    def _lecture(self, crn: str, term: AcademicTerm, lock: bool = False) -> Lecture:
        q = select(Lecture).where(Lecture.term_code == term.code, Lecture.crn == re.sub(r"\D", "", str(crn or "")))
        if lock:
            q = q.with_for_update()
        lec = self.s.scalars(q).first()
        if lec is None:
            raise ToolError(f"CRN {crn} does not exist in {term.name}.")
        return lec

    def _rows(self, uid: str, term_code: str | None = None):
        q = select(Enrollment).where(Enrollment.student_university_id == uid)
        if term_code:
            q = q.where(Enrollment.term_code == term_code)
        return list(self.s.scalars(q))

    # ------------------------------------------------------------------ add
    def add_blockers(self, uid: str, lec: Lecture, term: AcademicTerm) -> list[str]:
        st = self.s.get(Student, uid)
        prog = self.s.get(Program, st.program_code)
        course = self.s.get(Course, lec.course_code)
        params = self.policy.get_params()
        today = self.cal.today
        b = []
        if plain(st.status) != "active":
            b.append("student_not_active")
        if today < term.registration_opens:
            b.append("registration_not_open")
        if today > term.add_deadline:
            b.append("add_deadline_passed")
        mine = [e for e in self._rows(uid, term.code) if plain(e.status) == "enrolled"]
        if any(e.crn == lec.crn for e in mine):
            b.append("already_enrolled")
        elif any(e.course_code == lec.course_code for e in mine):
            b.append("already_enrolled_in_another_section")
        # prerequisites: best grade at or above the minimum; a course in progress in the current term counts (7.2)
        hist = self._rows(uid)
        best: dict[str, float] = {}
        cur = self.cal.current().code
        for e in hist:
            p = self.points.get(e.grade) if e.grade else None
            if p is not None:
                best[e.course_code] = max(best.get(e.course_code, -1), p)
            elif (e.grade is None and plain(e.status) == "enrolled" and e.term_code == cur and term.code != cur
                  and params.get("in_progress_counts_for_prerequisites")):
                best[e.course_code] = max(best.get(e.course_code, -1), 4.0)
        groups: dict[int, list[tuple[str, float]]] = {}
        for pr in self.s.scalars(select(CoursePrerequisite).where(CoursePrerequisite.course_code == course.code)):
            groups.setdefault(pr.group_number, []).append((pr.required_course_code, self.points[pr.min_grade]))
        waived = prog.degree == "MS" and params.get("grad_admit_meets_undergrad_prereqs")
        for alts in groups.values():
            ok = any(best.get(r, -1) >= m for r, m in alts) or (
                waived and all(plain(self.s.get(Course, r).level) != "graduate" for r, _ in alts))
            if not ok:
                b.append("prerequisite_not_met")
                break
        if plain(course.level) not in params["allowed_levels_by_degree"][prog.degree]:
            b.append("level_not_allowed")
        if course.code in best and best[course.code] > 0:  # repeat rule 2.1: only below a prerequisite minimum
            mins = [self.points[p.min_grade] for p in self.s.scalars(
                select(CoursePrerequisite).where(CoursePrerequisite.required_course_code == course.code))]
            if not any(best[course.code] < m for m in mins):
                b.append("repeat_not_permitted")
        others = [self._lecture(e.crn, term) for e in mine if e.crn and e.course_code != lec.course_code]
        if any(_overlap(lec, o) for o in others):
            b.append("time_conflict")
        if lec.is_cancelled:
            b.append("section_cancelled")
        taken = self.s.scalar(select(func.count()).select_from(Enrollment).where(
            Enrollment.term_code == term.code, Enrollment.crn == lec.crn, Enrollment.status == "enrolled"))
        if taken >= lec.capacity:
            b.append("section_full")
        load = sum(float(self.s.get(Course, e.course_code).credit_hours) for e in mine
                   if e.course_code != course.code) + float(course.credit_hours)
        standing = self._standing(uid, prog)
        if load > float(params["max_credits_by_standing"][standing]):
            b.append("credit_limit_exceeded")
        return b

    def _standing(self, uid: str, prog: Program) -> str:
        by_term: dict[str, list] = {}
        seq = {}
        for e in self._rows(uid):
            p = self.points.get(e.grade) if e.grade else None
            if p is None:
                continue
            t = self.s.get(AcademicTerm, e.term_code)
            seq[e.term_code] = t.sequence
            by_term.setdefault(e.term_code, []).append((p, float(self.s.get(Course, e.course_code).credit_hours)))
        if not by_term:
            return "good"
        last = max(by_term, key=seq.get)
        xs = by_term[last]
        gpa = sum(p * c for p, c in xs) / sum(c for _, c in xs)
        return "probation" if gpa < float(prog.min_gpa) else "good"

    def do_add(self, uid: str, term: AcademicTerm, crn: str) -> dict:
        lec = self._lecture(crn, term, lock=True)  # row lock: the seat check below is race-free
        blockers = self.add_blockers(uid, lec, term)
        if blockers:
            raise ToolError("The registration is no longer possible: " + ", ".join(blockers))
        row = self.s.get(Enrollment, (uid, term.code, lec.course_code))
        if row is None:
            self.s.add(Enrollment(student_university_id=uid, term_code=term.code, course_code=lec.course_code,
                                  crn=lec.crn, status="enrolled", grade=None))
        else:  # re-adding a dropped course
            row.crn, row.status, row.grade = lec.crn, "enrolled", None
        return {"term": term.name, "crn": lec.crn, "course": lec.course_code, "status": "enrolled"}

    # ------------------------------------------------------------------ drop / withdraw
    def drop_plan(self, uid: str, term: AcademicTerm, crn: str) -> dict:
        lec = self._lecture(crn, term)
        row = self.s.get(Enrollment, (uid, term.code, lec.course_code))
        if row is None or plain(row.status) != "enrolled" or row.crn != lec.crn:
            raise ToolError(f"You are not enrolled in CRN {lec.crn} in {term.name}.")
        if row.grade is not None:
            raise ToolError("That course already has a final grade.")
        today = self.cal.today
        if today <= term.drop_deadline:
            action = "drop"
        elif today <= term.withdraw_deadline:
            action = "withdraw"
        else:
            raise ToolError(f"The withdraw deadline for {term.name} ({term.withdraw_deadline}) has passed; the "
                            "course keeps the grade earned (handbook 7.1).")
        return {"action": action, "term": term.name, "term_code": term.code, "crn": lec.crn, "course": lec.course_code,
                "result": "removed, no record" if action == "drop" else "grade W on the transcript"}

    def do_drop(self, uid: str, term: AcademicTerm, crn: str) -> dict:
        plan = self.drop_plan(uid, term, crn)
        row = self.s.get(Enrollment, (uid, term.code, plan["course"]), with_for_update=True)
        if plan["action"] == "drop":
            row.status, row.grade = "dropped", None
        else:
            row.status, row.grade = "withdrawn", "W"
        return {k: plan[k] for k in ("action", "term", "crn", "course")} | {"status": plain(row.status)}

    # ------------------------------------------------------------------ grades
    def grade_plan(self, instructor_uid: str, term: AcademicTerm, crn: str, student: str, grade: str) -> dict:
        lec = self._lecture(crn, term)
        if lec.instructor_university_id != instructor_uid:
            raise ToolError(f"You do not teach CRN {lec.crn} in {term.name}; only its instructor posts its grades.")
        letter = str(grade or "").strip().upper()
        if letter not in POSTABLE:
            raise ToolError("The grade must be a letter grade A to F or I. W is recorded only by withdrawal.")
        today = self.cal.today
        if not (term.end_date <= today <= term.grades_due):
            raise ToolError(f"Grades for {term.name} can be posted from {term.end_date} to {term.grades_due} "
                            "(handbook 7.3).")
        uid = self._student_in_section(lec, student)
        row = self.s.get(Enrollment, (uid, term.code, lec.course_code))
        p = self.s.get(Person, uid)
        return {"term": term.name, "term_code": term.code, "crn": lec.crn, "course": lec.course_code,
                "student_university_id": uid, "student": f"{p.first_name} {p.last_name}", "grade": letter,
                "replaces": row.grade}

    def _student_in_section(self, lec: Lecture, student: str) -> str:
        text = str(student or "").strip()
        rows = self.s.execute(select(Enrollment.student_university_id, Person.first_name, Person.last_name)
                              .join(Person, Person.university_id == Enrollment.student_university_id)
                              .where(Enrollment.term_code == lec.term_code, Enrollment.crn == lec.crn,
                                     Enrollment.status == "enrolled")).all()
        for uid, f, l in rows:
            if text == uid or text.lower() == f"{f} {l}".lower():
                return uid
        raise ToolError(f"That student is not enrolled in CRN {lec.crn}.")

    def do_grade(self, instructor_uid: str, detail: dict) -> dict:
        term = self.s.get(AcademicTerm, detail["term_code"])
        plan = self.grade_plan(instructor_uid, term, detail["crn"], detail["student_university_id"], detail["grade"])
        row = self.s.get(Enrollment, (plan["student_university_id"], term.code, plan["course"]), with_for_update=True)
        row.grade = plan["grade"]
        return {"term": plan["term"], "crn": plan["crn"], "course": plan["course"], "student": plan["student"],
                "grade": plan["grade"]}

    def log(self, actor: str, role: str, action: str, detail: dict) -> None:
        self.s.add(ChangeLog(clock=self.cal.as_of, actor_university_id=actor, role=role, action=action, detail=detail))


class StudentWriteTools:
    def __init__(self, svc: RegistrationService, gate: ConfirmationGate, uid: str):
        self.svc, self.gate, self.uid = svc, gate, uid

    def get_my_registrations(self, term: str | None = None) -> dict:
        t = self.svc._term(term, default=1 if term is None and self.svc.cal.today > self.svc.cal.current().add_deadline else 0)
        rows = [e for e in self.svc._rows(self.uid, t.code) if plain(e.status) == "enrolled"]
        return {"answer": {"term": t.name, "registered": [{"crn": e.crn, "course": e.course_code} for e in rows],
                           "credits": plain(sum(float(self.svc.s.get(Course, e.course_code).credit_hours) for e in rows))}}

    def check_registration(self, crn: str, term: str | None = None) -> dict:
        t = self.svc._term(term, default=1)
        lec = self.svc._lecture(crn, t)
        b = self.svc.add_blockers(self.uid, lec, t)
        return {"answer": {"term": t.name, "crn": lec.crn, "course": lec.course_code, "can_add": not b,
                           "blockers": b}}

    def request_registration(self, crn: str, term: str | None = None) -> dict:
        t = self.svc._term(term, default=1)
        lec = self.svc._lecture(crn, t)
        b = self.svc.add_blockers(self.uid, lec, t)
        if b:
            return {"answer": {"term": t.name, "crn": lec.crn, "course": lec.course_code, "can_add": False,
                               "blockers": b}, "note": "Not allowed; explain the blockers. Nothing was changed."}
        p = self.gate.add("register", {"term_code": t.code, "crn": lec.crn, "course": lec.course_code})
        say = (f"I can register you in {lec.course_code} (CRN {lec.crn}), {t.name}, {lec.days} "
               f"{plain(lec.start_time)}-{plain(lec.end_time)}, room {lec.room}. Shall I go ahead?")
        return {"pending_change": {"code": p.code, "action": "register", "term": t.name, "crn": lec.crn,
                                   "course": lec.course_code, "days": lec.days, "start": plain(lec.start_time),
                                   "end": plain(lec.end_time), "room": lec.room},
                "reply_to_user": say, "status": "waiting for the user's confirmation; nothing changed yet"}

    def request_drop(self, crn: str, term: str | None = None) -> dict:
        t = self.svc._term(term)
        plan = self.svc.drop_plan(self.uid, t, crn)
        p = self.gate.add(plan["action"], {"term_code": t.code, "crn": plan["crn"], "course": plan["course"]})
        verb = "drop" if plan["action"] == "drop" else "withdraw you from"
        say = (f"I can {verb} {plan['course']} (CRN {plan['crn']}), {plan['term']}: {plan['result']}. "
               "Shall I go ahead?")
        return {"pending_change": {"code": p.code, **{k: plan[k] for k in ("action", "term", "crn", "course", "result")}},
                "reply_to_user": say, "status": "waiting for the user's confirmation; nothing changed yet"}

    def confirm_change(self, code: str) -> dict:
        p = self.gate.take(code)
        t = self.svc.s.get(AcademicTerm, p.detail["term_code"])
        try:
            if p.action == "register":
                done = self.svc.do_add(self.uid, t, p.detail["crn"])
            else:
                done = self.svc.do_drop(self.uid, t, p.detail["crn"])
            self.svc.log(self.uid, "student", p.action, done)
            self.svc.s.commit()
        except Exception:
            self.svc.s.rollback()
            raise
        return {"answer": {"changed": True, "action": p.action, **done}}

    def cancel_change(self) -> dict:
        self.gate.pending = {}
        return {"answer": {"changed": False, "cancelled": True}}


class InstructorWriteTools:
    def __init__(self, svc: RegistrationService, gate: ConfirmationGate, uid: str):
        self.svc, self.gate, self.uid = svc, gate, uid

    def get_my_roster(self, crn: str, term: str | None = None) -> dict:
        """Own sections only (instructor permission enrollment.roster.read): IDs and names, nothing else."""
        t = self.svc.term_for_grades(term)
        lec = self.svc._lecture(crn, t)
        if lec.instructor_university_id != self.uid:
            raise ToolError(f"You do not teach CRN {lec.crn} in {t.name}.")
        rows = self.svc.s.execute(select(Enrollment.student_university_id, Person.first_name, Person.last_name,
                                         Enrollment.grade)
                                  .join(Person, Person.university_id == Enrollment.student_university_id)
                                  .where(Enrollment.term_code == t.code, Enrollment.crn == lec.crn,
                                         Enrollment.status == "enrolled")
                                  .order_by(Person.last_name, Person.first_name)).all()
        return {"answer": {"term": t.name, "crn": lec.crn, "course": lec.course_code, "count": len(rows),
                           "students": [{"university_id": u, "name": f"{f} {l}", "grade": g} for u, f, l, g in rows]}}

    def request_grade(self, crn: str, student: str, grade: str, term: str | None = None) -> dict:
        t = self.svc.term_for_grades(term)
        g = self.svc.grading_term()
        moved = None
        if g is not None and t.start_date > self.svc.cal.today:  # grades are never posted for a future term
            moved, t = t.name, g
        plan = self.svc.grade_plan(self.uid, t, crn, student, grade)
        p = self.gate.add("post_grade", plan)
        say = (f"I can post {plan['grade']} for {plan['student']} in {plan['course']} (CRN {plan['crn']}), "
               f"{plan['term']}" + (f", replacing {plan['replaces']}" if plan["replaces"] else "") + ". Shall I go ahead?")
        return {"pending_change": {"code": p.code, "action": "post_grade",
                                   **{k: plan[k] for k in ("term", "crn", "course", "student", "grade", "replaces")}},
                "reply_to_user": say, "status": "waiting for the user's confirmation; nothing changed yet",
                **({"note": f"{moved} has not started, so this uses {t.name}, whose grading window is open."}
                   if moved else {})}

    def confirm_change(self, code: str) -> dict:
        p = self.gate.take(code)
        try:
            done = self.svc.do_grade(self.uid, p.detail)
            self.svc.log(self.uid, "instructor", "post_grade", done | {"student_university_id": p.detail["student_university_id"]})
            self.svc.s.commit()
        except Exception:
            self.svc.s.rollback()
            raise
        return {"answer": {"changed": True, "action": "post_grade", **done}}

    def cancel_change(self) -> dict:
        self.gate.pending = {}
        return {"answer": {"changed": False, "cancelled": True}}


_CRN = {"crn": {"type": "string", "description": "Five-digit CRN."}}
_TERM = {"term": {"type": "string", "description": "Term as the user said it; omit if none was named."}}
_CODE = {"code": {"type": "string", "description": "The confirmation code from the pending change."}}
STUDENT_WRITE_SPECS = [
    _fn("get_my_registrations", "The sections the logged-in student is registered in for a term.", _TERM),
    _fn("check_registration", "Whether the student can register for a CRN, with the blockers if not. Changes "
        "nothing.", {**_CRN, **_TERM}, ["crn"]),
    _fn("request_registration", "Prepare registering the student in a CRN (default: next term). Checks every rule "
        "and returns a pending change to show the user. Changes nothing until confirm_change.", {**_CRN, **_TERM},
        ["crn"]),
    _fn("request_drop", "Prepare dropping (before the drop deadline) or withdrawing (W, before the withdraw "
        "deadline) from a CRN the student is registered in. Changes nothing until confirm_change.",
        {**_CRN, **_TERM}, ["crn"]),
    _fn("confirm_change", "Make the pending change. Only after the user confirmed it in their latest message.",
        _CODE, ["code"]),
    _fn("cancel_change", "Discard the pending change."),
]
INSTRUCTOR_WRITE_SPECS = [
    _fn("get_my_roster", "Students enrolled in one of the instructor's own sections (IDs, names, posted grade).",
        {**_CRN, **_TERM}, ["crn"]),
    _fn("request_grade", "Prepare posting a grade for a student in one of the instructor's own sections (during "
        "the grading window). Changes nothing until confirm_change.",
        {**_CRN, "student": {"type": "string", "description": "Student's university ID or full name."},
         "grade": {"type": "string", "description": "Letter grade A to F, or I."}, **_TERM}, ["crn", "student", "grade"]),
    _fn("confirm_change", "Post the pending grade. Only after the user confirmed it in their latest message.",
        _CODE, ["code"]),
    _fn("cancel_change", "Discard the pending change."),
]
