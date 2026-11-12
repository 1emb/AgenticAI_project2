"""Writes to the database: registration, drop and withdrawal for students; grade posting for instructors.

Every change goes through three steps (handbook 7.4):
  1. request_*  : validator code checks every rule and returns a pending change with the preview shown to the user.
                  Nothing is written.
  2. the user answers in a LATER message with exactly "yes" (or "no"). The ConfirmationGate checks this in code; the
                  model has no tool that confirms. While a change is waiting, the Router answers every other
                  message itself with "answer yes or no" and the preview; the model is not asked.
  3. confirm_change : reads the clock and the rows again, locks them, works the change out afresh and compares it with
                  the preview. Same result: it writes the change and its change_log row in one transaction. Different
                  result (the drop became a withdrawal, the section moved): nothing is written, the new preview
                  replaces the old one and the user is asked again.

Merged into main 2026-11-11 (from Duong's advising-agent branch) on main's enrollment table: one row per student and
section, status enrolled / completed / withdrawn / dropped. A drop keeps the row with status `dropped` (no grade, no
seat, not on the transcript); posting a grade turns `enrolled` into `completed`. Two rules were set by the owner the
same day: the time of the yes decides the outcome, and only the exact word confirms.

Blocker codes are this module's own (handbook sections 2 to 7); the student test set's `can_register` reasons come from
registrar/agent/programs.py and are a separate rule set.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar, TermNotFound
from registrar.agents.common import ToolError, plain
from registrar.agents.policy import PolicyStore
from registrar.agents.student.tools import _fn
from registrar.models import (AcademicTerm, ChangeLog, Course, CoursePrerequisite, Enrollment, GradeScale, Lecture,
                              Person, Program, Student, TransferCredit)

# Confirmation is the exact word, nothing else in the message (owner, 2026-11-11): "yes later", "yes?", "yes, but ..."
# and "ok" do not confirm. A final full stop or exclamation mark is allowed.
YES = re.compile(r"^\s*yes\s*[.!]?\s*$", re.I)
NO = re.compile(r"^\s*no\s*[.!]?\s*$", re.I)
AFFIRM = YES  # earlier name, kept for callers
ASK = "Please answer yes or no."
POSTABLE = {"A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F", "I"}
ON_ROSTER = ("enrolled", "completed")  # sits in the section: not withdrawn, not dropped


def _overlap(a: Lecture, b: Lecture) -> bool:
    return bool(set(a.days) & set(b.days)) and a.start_time < b.end_time and b.start_time < a.end_time


@dataclass
class Pending:
    code: str
    action: str
    detail: dict
    turn: int
    preview: str = ""  # the sentence shown to the user; repeated when they answer something other than yes or no


@dataclass
class ConfirmationGate:
    """Tracks the conversation turn and the user's latest message (set by the Router before each turn)."""
    turn: int = 0
    last_user_text: str = ""
    pending: dict[str, Pending] = field(default_factory=dict)

    def new_turn(self, text: str) -> None:
        self.turn += 1
        self.last_user_text = text

    def add(self, action: str, detail: dict, preview: str = "") -> Pending:
        p = Pending(secrets.token_hex(3).upper(), action, detail, self.turn, preview)
        self.pending = {p.code: p}  # one pending change at a time; a new request replaces the old one
        return p

    def clear(self) -> None:
        self.pending = {}

    def take(self, code: str) -> Pending:
        p = self.pending.get(str(code or "").strip().upper())
        if p is None:
            raise ToolError("There is no pending change with that code. Request the change again.")
        if self.turn <= p.turn:
            raise ToolError("Not confirmed yet: show the change to the user and wait for their next message.")
        if not YES.match(self.last_user_text):
            raise ToolError("The user's last message was not exactly 'yes', so nothing was changed. " + ASK)
        del self.pending[p.code]
        return p


class RegistrationService:
    """Rules and writes. No LLM here."""

    def __init__(self, session: Session, calendar: Calendar, policy: PolicyStore):
        self.s, self.cal, self.policy = session, calendar, policy
        self.points = {g.letter: (None if g.points is None else float(g.points)) for g in session.scalars(select(GradeScale))}

    def fresh(self) -> None:
        """Before any check: today's date again (when the clock is the real one) and no cached rows, so a student
        suspended, a deadline moved or a section changed since the last turn is seen."""
        self.cal.refresh()
        self.s.expire_all()

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
            q = q.with_for_update().execution_options(populate_existing=True)
        lec = self.s.scalars(q).first()
        if lec is None:
            raise ToolError(f"CRN {crn} does not exist in {term.name}.")
        return lec

    def _lock_student(self, uid: str) -> Student:
        """Row lock on the student, re-read from the database. Every student write takes it first, so two changes
        for one student run one after the other and each sees the other's result."""
        return self.s.scalars(select(Student).where(Student.university_id == uid).with_for_update()
                              .execution_options(populate_existing=True)).one()

    def _rows(self, uid: str, term_code: str | None = None) -> list[Enrollment]:
        """The student's record rows. Dropped rows are not part of the record and are left out."""
        q = select(Enrollment).where(Enrollment.student_university_id == uid, Enrollment.status != "dropped")
        if term_code:
            q = q.where(Enrollment.term_code == term_code)
        return list(self.s.scalars(q))

    def _row(self, uid: str, term: AcademicTerm, crn: str, lock: bool = False) -> Enrollment | None:
        q = select(Enrollment).where(Enrollment.term_code == term.code, Enrollment.crn == crn,
                                     Enrollment.student_university_id == uid)
        if lock:
            q = q.with_for_update().execution_options(populate_existing=True)
        return self.s.scalars(q).first()

    def _best_points(self, uid: str, term: AcademicTerm) -> dict[str, float]:
        """Best grade points per course for prerequisites and repeats: graded attempts, transfer credit (counts as
        met), and a course in progress in the current term when registering for a later one (7.2)."""
        best: dict[str, float] = {}
        cur = self.cal.current().code
        counts_in_progress = self.policy.get_params().get("in_progress_counts_for_prerequisites")
        for e in self._rows(uid):
            p = self.points.get(e.grade) if e.grade else None
            if p is not None:
                best[e.course_code] = max(best.get(e.course_code, -1), p)
            elif plain(e.status) == "enrolled" and e.term_code == cur and term.code != cur and counts_in_progress:
                best[e.course_code] = max(best.get(e.course_code, -1), 4.0)
        for code in self.s.scalars(select(TransferCredit.course_code).where(TransferCredit.student_university_id == uid)):
            best[code] = max(best.get(code, -1), 4.0)
        return best

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
        best = self._best_points(uid, term)
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
        others = [self._lecture(e.crn, term) for e in mine if e.course_code != lec.course_code]
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

    def add_plan(self, uid: str, term: AcademicTerm, crn: str, lock: bool = False) -> dict:
        """What registering would do right now: the section as it stands, or the blockers."""
        lec = self._lecture(crn, term, lock=lock)
        return {"action": "register", "term": term.name, "term_code": term.code, "crn": lec.crn,
                "course": lec.course_code, "days": lec.days, "start": plain(lec.start_time), "end": plain(lec.end_time),
                "room": lec.room, "blockers": self.add_blockers(uid, lec, term)}

    def do_add(self, uid: str, plan: dict) -> dict:
        """Write a registration that add_plan just allowed (student and section rows are locked by the caller)."""
        term = self.s.get(AcademicTerm, plan["term_code"])
        row = self._row(uid, term, plan["crn"], lock=True)
        if row is None:
            self.s.add(Enrollment(term_code=term.code, crn=plan["crn"], student_university_id=uid, status="enrolled",
                                  grade=None))
        elif plain(row.status) == "dropped":  # re-adding a section dropped earlier: the same row comes back
            row.status, row.grade = "enrolled", None
        else:
            raise ToolError(f"There is already a {plain(row.status)} record for CRN {plan['crn']} in {term.name}.")
        return {"term": term.name, "crn": plan["crn"], "course": plan["course"], "status": "enrolled"}

    # ------------------------------------------------------------------ drop / withdraw
    def drop_plan(self, uid: str, term: AcademicTerm, crn: str, lock: bool = False) -> dict:
        """What leaving the section would do right now: a drop (no record) or a withdrawal (W), by today's date."""
        lec = self._lecture(crn, term)
        row = self._row(uid, term, lec.crn, lock=lock)
        status = plain(row.status) if row is not None else None
        if status == "completed":
            raise ToolError("That course already has a final grade.")
        if status != "enrolled":
            raise ToolError(f"You are not enrolled in CRN {lec.crn} in {term.name}.")
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

    def do_drop(self, uid: str, plan: dict) -> dict:
        """Write a drop or withdrawal that drop_plan just allowed, on the row it locked."""
        term = self.s.get(AcademicTerm, plan["term_code"])
        row = self._row(uid, term, plan["crn"])
        if plan["action"] == "drop":
            row.status, row.grade = "dropped", None
        else:
            row.status, row.grade = "withdrawn", "W"
        return {k: plan[k] for k in ("action", "term", "crn", "course")} | {"status": plain(row.status)}

    # ------------------------------------------------------------------ grades
    def grade_plan(self, instructor_uid: str, term: AcademicTerm, crn: str, student: str, grade: str,
                   lock: bool = False) -> dict:
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
        row = self._row(uid, term, lec.crn, lock=lock)
        if row is None or plain(row.status) not in ON_ROSTER:  # withdrew or dropped since the roster was read
            raise ToolError(f"That student is not enrolled in CRN {lec.crn}.")
        p = self.s.get(Person, uid)
        return {"term": term.name, "term_code": term.code, "crn": lec.crn, "course": lec.course_code,
                "student_university_id": uid, "student": f"{p.first_name} {p.last_name}", "grade": letter,
                "replaces": row.grade}

    def _student_in_section(self, lec: Lecture, student: str) -> str:
        text = str(student or "").strip()
        rows = self.s.execute(select(Enrollment.student_university_id, Person.first_name, Person.last_name)
                              .join(Person, Person.university_id == Enrollment.student_university_id)
                              .where(Enrollment.term_code == lec.term_code, Enrollment.crn == lec.crn,
                                     Enrollment.status.in_(ON_ROSTER))).all()
        for uid, f, l in rows:
            if text == uid or text.lower() == f"{f} {l}".lower():
                return uid
        raise ToolError(f"That student is not enrolled in CRN {lec.crn}.")

    def do_grade(self, plan: dict) -> dict:
        """Write a grade that grade_plan just allowed, on the row it locked: the row becomes `completed`."""
        term = self.s.get(AcademicTerm, plan["term_code"])
        row = self._row(plan["student_university_id"], term, plan["crn"])
        row.grade, row.status = plan["grade"], "completed"
        return {k: plan[k] for k in ("term", "crn", "course", "student", "grade", "replaces")}

    def log(self, actor: str, role: str, action: str, detail: dict) -> None:
        self.s.add(ChangeLog(clock=self.cal.as_of, actor_university_id=actor, role=role, action=action, detail=detail))


def _ask_again(gate: ConfirmationGate, action: str, plan: dict, shown: dict, say: str) -> dict:
    """The change worked out at the yes is not the one that was shown: write nothing, make the new one pending."""
    p = gate.add(action, plan, say)
    return {"answer": {"changed": False, "needs_confirmation": True}, "pending_change": {"code": p.code, **shown},
            "reply_to_user": say, "status": "the change differs from what was shown; waiting for a new confirmation; "
                                            "nothing changed"}


class StudentWriteTools:
    def __init__(self, svc: RegistrationService, gate: ConfirmationGate, uid: str):
        self.svc, self.gate, self.uid = svc, gate, uid

    def get_my_registrations(self, term: str | None = None) -> dict:
        self.svc.fresh()
        t = self.svc._term(term, default=1 if term is None and self.svc.cal.today > self.svc.cal.current().add_deadline else 0)
        rows = [e for e in self.svc._rows(self.uid, t.code) if plain(e.status) == "enrolled"]
        return {"answer": {"term": t.name, "registered": [{"crn": e.crn, "course": e.course_code} for e in rows],
                           "credits": plain(sum(float(self.svc.s.get(Course, e.course_code).credit_hours) for e in rows))}}

    def check_registration(self, crn: str, term: str | None = None) -> dict:
        self.svc.fresh()
        plan = self.svc.add_plan(self.uid, self.svc._term(term, default=1), crn)
        return {"answer": {"term": plan["term"], "crn": plan["crn"], "course": plan["course"],
                           "can_add": not plan["blockers"], "blockers": plan["blockers"]}}

    @staticmethod
    def _say_add(plan: dict) -> str:
        return (f"I can register you in {plan['course']} (CRN {plan['crn']}), {plan['term']}, {plan['days']} "
                f"{plan['start']}-{plan['end']}, room {plan['room']}. Shall I go ahead? {ASK}")

    @staticmethod
    def _say_drop(plan: dict) -> str:
        verb = "drop" if plan["action"] == "drop" else "withdraw you from"
        return f"I can {verb} {plan['course']} (CRN {plan['crn']}), {plan['term']}: {plan['result']}. Shall I go ahead? {ASK}"

    def request_registration(self, crn: str, term: str | None = None) -> dict:
        self.gate.clear()  # a new request replaces the old one, also when the new one turns out to be blocked
        self.svc.fresh()
        plan = self.svc.add_plan(self.uid, self.svc._term(term, default=1), crn)
        if plan["blockers"]:
            return {"answer": {"term": plan["term"], "crn": plan["crn"], "course": plan["course"], "can_add": False,
                               "blockers": plan["blockers"]}, "note": "Not allowed; explain the blockers. Nothing was changed."}
        del plan["blockers"]
        p = self.gate.add("register", plan, self._say_add(plan))
        return {"pending_change": {"code": p.code, **{k: v for k, v in plan.items() if k != "term_code"}},
                "reply_to_user": self._say_add(plan), "status": "waiting for the user's confirmation; nothing changed yet"}

    def request_drop(self, crn: str, term: str | None = None) -> dict:
        self.gate.clear()
        self.svc.fresh()
        plan = self.svc.drop_plan(self.uid, self.svc._term(term), crn)
        p = self.gate.add(plan["action"], plan, self._say_drop(plan))
        return {"pending_change": {"code": p.code, **{k: v for k, v in plan.items() if k != "term_code"}},
                "reply_to_user": self._say_drop(plan), "status": "waiting for the user's confirmation; nothing changed yet"}

    def confirm_change(self, code: str) -> dict:
        p = self.gate.take(code)
        svc, shown = self.svc, p.detail
        try:
            svc.fresh()
            svc._lock_student(self.uid)
            t = svc.s.get(AcademicTerm, shown["term_code"])
            if p.action == "register":
                now = svc.add_plan(self.uid, t, shown["crn"], lock=True)  # row lock on the section: the seat check is race-free
                blockers = now.pop("blockers")
                if blockers:
                    raise ToolError("The registration is no longer possible: " + ", ".join(blockers))
                if now != shown:
                    svc.s.rollback()
                    return _ask_again(self.gate, "register", now, {k: v for k, v in now.items() if k != "term_code"},
                                      "The section has changed since I showed it to you. " + self._say_add(now))
                done = svc.do_add(self.uid, now)
            else:
                now = svc.drop_plan(self.uid, t, shown["crn"], lock=True)
                if now != shown:
                    svc.s.rollback()
                    was = "a drop with no record" if shown["action"] == "drop" else "a withdrawal with a W"
                    return _ask_again(self.gate, now["action"], now, {k: v for k, v in now.items() if k != "term_code"},
                                      f"This is no longer {was}: today's date changes the result. " + self._say_drop(now))
                done = svc.do_drop(self.uid, now)
            action = done.get("action", p.action)
            svc.log(self.uid, "student", action, done)
            svc.s.commit()
        except Exception:
            svc.s.rollback()
            raise
        return {"answer": {"changed": True, "action": action, **done}}

    def cancel_change(self) -> dict:
        self.gate.clear()
        return {"answer": {"changed": False, "cancelled": True}}


class InstructorWriteTools:
    def __init__(self, svc: RegistrationService, gate: ConfirmationGate, uid: str):
        self.svc, self.gate, self.uid = svc, gate, uid

    @staticmethod
    def _say(plan: dict) -> str:
        return (f"I can post {plan['grade']} for {plan['student']} in {plan['course']} (CRN {plan['crn']}), "
                f"{plan['term']}" + (f", replacing {plan['replaces']}" if plan["replaces"] else "") + f". Shall I go ahead? {ASK}")

    @staticmethod
    def _shown(plan: dict) -> dict:
        return {k: plan[k] for k in ("term", "crn", "course", "student", "grade", "replaces")}

    def request_grade(self, crn: str, student: str, grade: str, term: str | None = None) -> dict:
        self.gate.clear()
        self.svc.fresh()
        t = self.svc.term_for_grades(term)
        g = self.svc.grading_term()
        moved = None
        if g is not None and t.start_date > self.svc.cal.today:  # grades are never posted for a future term
            moved, t = t.name, g
        plan = self.svc.grade_plan(self.uid, t, crn, student, grade)
        p = self.gate.add("post_grade", plan, self._say(plan))
        return {"pending_change": {"code": p.code, "action": "post_grade", **self._shown(plan)},
                "reply_to_user": self._say(plan), "status": "waiting for the user's confirmation; nothing changed yet",
                **({"note": f"{moved} has not started, so this uses {t.name}, whose grading window is open."}
                   if moved else {})}

    def confirm_change(self, code: str) -> dict:
        p = self.gate.take(code)
        svc, shown = self.svc, p.detail
        try:
            svc.fresh()
            t = svc.s.get(AcademicTerm, shown["term_code"])
            now = svc.grade_plan(self.uid, t, shown["crn"], shown["student_university_id"], shown["grade"], lock=True)
            if now != shown:
                svc.s.rollback()
                return _ask_again(self.gate, "post_grade", now, {"action": "post_grade", **self._shown(now)},
                                  "The record has changed since I showed it to you. " + self._say(now))
            done = svc.do_grade(now)
            svc.log(self.uid, "instructor", "post_grade", done | {"student_university_id": now["student_university_id"]})
            svc.s.commit()
        except Exception:
            svc.s.rollback()
            raise
        return {"answer": {"changed": True, "action": "post_grade", **{k: v for k, v in done.items() if k != "replaces"}}}

    def cancel_change(self) -> dict:
        self.gate.clear()
        return {"answer": {"changed": False, "cancelled": True}}


_CRN = {"crn": {"type": "string", "description": "Five-digit CRN."}}
_TERM = {"term": {"type": "string", "description": "Term as the user said it; omit if none was named."}}
# confirm_change is not a model tool: the Router confirms in code when the user's next message is exactly "yes".
STUDENT_WRITE_SPECS = [
    _fn("get_my_registrations", "The sections the logged-in student is registered in for a term.", _TERM),
    _fn("check_registration", "Whether the student can register for a CRN, with the blockers if not. Changes "
        "nothing.", {**_CRN, **_TERM}, ["crn"]),
    _fn("request_registration", "Prepare registering the student in a CRN (default: next term). Checks every rule "
        "and returns a pending change to show the user. Changes nothing; the system makes the change when the "
        "user's next message is exactly 'yes'.", {**_CRN, **_TERM}, ["crn"]),
    _fn("request_drop", "Prepare dropping (before the drop deadline) or withdrawing (W, before the withdraw "
        "deadline) from a CRN the student is registered in. Changes nothing; the system makes the change when the "
        "user's next message is exactly 'yes'.", {**_CRN, **_TERM}, ["crn"]),
    _fn("cancel_change", "Discard the pending change."),
]
INSTRUCTOR_WRITE_SPECS = [
    _fn("request_grade", "Prepare posting a grade for a student in one of the instructor's own sections (during "
        "the grading window). Changes nothing; the system posts it when the user's next message is exactly 'yes'.",
        {**_CRN, "student": {"type": "string", "description": "Student's university ID or full name."},
         "grade": {"type": "string", "description": "Letter grade A to F, or I."}, **_TERM}, ["crn", "student", "grade"]),
    _fn("cancel_change", "Discard the pending change."),
]
