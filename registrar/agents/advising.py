"""The Advising agent on the real database.

PgAdvisingData implements advising_agent.contracts.DataTools with SQL over the seed tables, enrollment, transfer_credit
and advisor_assignment. Ported 2026-11-11 to main's enrollment table: the planner still receives rows in its own
contract (status enrolled / dropped / withdrawn, a grade or none, a course code), so a graded `completed` row is
handed over as `enrolled` with its grade and the course code is read from the lecture. AdvisingTools wraps advising_agent.AdvisingAgent (ASP planner + validator) as tools for the
persona agents:
  - students: plan_my_degree (their own record only)
  - instructors: get_my_advisees, plan_for_advisee (only students assigned to them in advisor_assignment; a claim
    in the conversation is not an assignment)
Each tool returns {"answer": {...}} like the other tools, so the graded answer is built from the planner's result.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from advising_agent.agent import AdvisingAgent
from registrar.agents.calendar import Calendar
from registrar.agents.common import ToolError, plain
from registrar.agents.policy import PolicyStore
from registrar.agents.student.tools import _fn
from registrar.models import (AcademicTerm, AdvisorAssignment, Course, CoursePrerequisite, DegreeRequirement,
                              Enrollment, GradeScale, Lecture, Person, Program, ProgramCategoryRequirement, Student,
                              TransferCredit)


class PgAdvisingData:
    """advising_agent.contracts.DataTools over Postgres. Every call is scoped by the AdvisingTools caller."""

    def __init__(self, session: Session, calendar: Calendar):
        self.s, self.cal = session, calendar

    def get_student(self, uid):
        st = self.s.get(Student, uid)
        if st is None:
            raise ToolError(f"{uid} is not a student.")
        return {"university_id": st.university_id, "program_code": st.program_code, "status": plain(st.status),
                "admit_term_code": st.admit_term_code, "expected_graduation_term_code": st.expected_graduation_term_code}

    def get_program(self, code):
        p = self.s.get(Program, code)
        return {"code": p.code, "degree": p.degree, "total_credits_required": p.total_credits_required,
                "min_gpa": float(p.min_gpa)}

    def get_enrollments(self, uid):
        rows = self.s.execute(select(Enrollment, Lecture.course_code)
                              .join(Lecture, (Lecture.term_code == Enrollment.term_code) & (Lecture.crn == Enrollment.crn))
                              .where(Enrollment.student_university_id == uid))
        contract_status = {"completed": "enrolled"}  # the planner tells graded from ungraded by the grade itself
        return [{"term_code": e.term_code, "crn": e.crn, "course_code": course,
                 "status": contract_status.get(plain(e.status), plain(e.status)), "grade": e.grade} for e, course in rows]

    def get_transfer_credits(self, uid):
        """Courses accepted from another institution: credit and prerequisites, no grade, outside the GPA."""
        return list(self.s.scalars(select(TransferCredit.course_code).where(TransferCredit.student_university_id == uid)))

    def get_grade_scale(self):
        return [{"letter": g.letter, "points": None if g.points is None else float(g.points)}
                for g in self.s.scalars(select(GradeScale))]

    def get_terms_after(self, as_of, n, include_summer):
        cur = self.cal.current()
        future = [t for t in self.cal.terms if t.start_date > self.cal.today
                  and (include_summer or plain(t.term_type) != "summer")]
        row = lambda t: {"code": t.code, "name": t.name, "term_type": plain(t.term_type),
                         "start_date": t.start_date.isoformat(), "end_date": t.end_date.isoformat(),
                         "sequence": t.sequence}
        return row(cur), [row(t) for t in future[:n]]

    def get_courses(self, codes=None):
        return [{"code": c.code, "title": c.title, "credit_hours": float(c.credit_hours), "level": plain(c.level),
                 "is_active": c.is_active} for c in self.s.scalars(select(Course))
                if codes is None or c.code in codes]

    def get_prerequisites(self):
        return [{"course_code": p.course_code, "required_course_code": p.required_course_code,
                 "min_grade": p.min_grade, "group_number": p.group_number}
                for p in self.s.scalars(select(CoursePrerequisite))]

    def get_degree_plan(self, program_code):
        reqs = [{"program_code": r.program_code, "course_code": r.course_code, "category": plain(r.category),
                 "is_required": r.is_required, "suggested_term_number": r.suggested_term_number}
                for r in self.s.scalars(select(DegreeRequirement).where(DegreeRequirement.program_code == program_code))]
        cats = [{"program_code": r.program_code, "category": plain(r.category), "min_credits": r.min_credits}
                for r in self.s.scalars(select(ProgramCategoryRequirement)
                                        .where(ProgramCategoryRequirement.program_code == program_code))]
        return reqs, cats

    def get_lectures(self, term_codes):
        taken = dict(self.s.execute(select(Enrollment.term_code + ":" + Enrollment.crn, func.count())
                                    .where(Enrollment.status == "enrolled", Enrollment.term_code.in_(term_codes))
                                    .group_by(Enrollment.term_code, Enrollment.crn)).all())
        return [{"term_code": l.term_code, "crn": l.crn, "course_code": l.course_code,
                 "section_number": l.section_number, "days": l.days, "start_time": plain(l.start_time),
                 "end_time": plain(l.end_time), "capacity": l.capacity, "is_cancelled": l.is_cancelled,
                 "seats_taken": taken.get(f"{l.term_code}:{l.crn}", 0)}
                for l in self.s.scalars(select(Lecture).where(Lecture.term_code.in_(term_codes)))]

    def get_offering_history(self, course_codes):
        rows = self.s.execute(select(Lecture.course_code, AcademicTerm.term_type).distinct()
                              .join(AcademicTerm, AcademicTerm.code == Lecture.term_code)
                              .where(Lecture.is_cancelled.is_(False), AcademicTerm.start_date <= self.cal.today)).all()
        hist: dict[str, set] = {}
        for c, tt in rows:
            hist.setdefault(c, set()).add(plain(tt))
        return [{"course_code": c, "term_types": sorted(v)} for c, v in hist.items() if c in course_codes]

    def is_advisor_of(self, instructor_uid, student_uid):
        a = self.s.get(AdvisorAssignment, student_uid)
        return a is not None and a.advisor_university_id == instructor_uid


class AdvisingTools:
    def __init__(self, session: Session, calendar: Calendar, user_uid: str, role: str,
                 policy: PolicyStore | None = None, time_limit_terms: int = 8):
        self.s, self.cal, self.uid, self.role = session, calendar, user_uid, role
        self.policy = policy or PolicyStore()
        self.agent = AdvisingAgent(PgAdvisingData(session, calendar), self.policy)
        self.horizon = time_limit_terms

    def _plan(self, student_uid: str, target_term: str | None, max_credits: float | None,
              avoid_days: str | None) -> dict:
        req = {"request_id": f"adv-{student_uid}", "as_of": self.cal.as_of.isoformat(),
               "requester": {"university_id": self.uid, "role": self.role}, "student_university_id": student_uid,
               "horizon_terms": self.horizon, "preferences": {}}
        if target_term:
            t = self.cal.resolve(target_term)
            req.update(target_graduation_term_code=t.code, target_is_hard=True)
        if max_credits:
            req["preferences"]["max_credits_per_term"] = float(max_credits)
        if avoid_days:
            req["preferences"]["avoid_days"] = avoid_days
        r = self.agent.handle(req)
        if not r.get("allowed", True):
            raise ToolError("Not permitted: that student is not assigned to you for advising.")
        name = {t.code: t.name for t in self.cal.terms}
        name_of = lambda code: name.get(code, code)
        plan = r.get("plans", [{}])[0] if r.get("plans") else {}
        terms = [{"term": name_of(t["term_code"]), "projected": t["is_projected"], "credits": t["credits"],
                  "courses": [c["course_code"] for c in t["courses"]],
                  "crns": [c["crn"] for c in t["courses"] if c["crn"]]} for t in plan.get("terms", [])]
        rem = r.get("remaining", {})
        answer = {"status": r["status"],
                  "earliest_graduation_term": name_of(r["earliest_graduation_term_code"])
                  if r.get("earliest_graduation_term_code") else None,
                  "must_take_next_term": r.get("must_take_next_term"),
                  "remaining_required": rem.get("required_courses"),
                  "credits_earned": rem.get("credits_earned"), "credits_required": rem.get("credits_required"),
                  "cumulative_gpa": rem.get("cumulative_gpa"), "standing": rem.get("standing"),
                  "next_term": terms[0]["term"] if terms else None,
                  "next_term_courses": terms[0]["courses"] if terms else []}
        return {"answer": answer, "plan": terms, "relaxed": r.get("relaxed"), "assumptions": r.get("assumptions"),
                "blockers": r.get("blockers"), "citations": [c["source"] for c in r.get("citations", [])],
                "note": "Present the plan term by term; say which terms are projected (no sections published yet) "
                        "and mention the assumptions."}

    # ---------------------------------------------------------------- student
    def plan_my_degree(self, target_term: str | None = None, max_credits: float | None = None,
                       avoid_days: str | None = None) -> dict:
        if self.role != "student":
            raise ToolError("plan_my_degree is for students; use plan_for_advisee.")
        return self._plan(self.uid, target_term, max_credits, avoid_days)

    # ---------------------------------------------------------------- advisor
    def get_my_advisees(self) -> dict:
        rows = self.s.execute(select(Person.university_id, Person.first_name, Person.last_name, Student.program_code)
                              .join(AdvisorAssignment, AdvisorAssignment.student_university_id == Person.university_id)
                              .join(Student, Student.university_id == Person.university_id)
                              .where(AdvisorAssignment.advisor_university_id == self.uid,
                                     Student.status == "active").order_by(Person.last_name, Person.first_name)).all()
        return {"answer": {"advisees": [{"university_id": u, "name": f"{f} {l}", "program": p} for u, f, l, p in rows],
                           "count": len(rows)}}

    def plan_for_advisee(self, student: str, target_term: str | None = None, max_credits: float | None = None,
                         avoid_days: str | None = None) -> dict:
        if self.role != "instructor":
            raise ToolError("plan_for_advisee is for advisors.")
        uid = self._advisee_uid(student)
        return self._plan(uid, target_term, max_credits, avoid_days)

    def _advisee_uid(self, student: str) -> str:
        mine = self.get_my_advisees()["answer"]["advisees"]
        text = str(student or "").strip().lower()
        for a in mine:
            if text in (a["university_id"], a["name"].lower()) or (text and a["name"].lower().endswith(text)):
                return a["university_id"]
        raise ToolError("Not permitted: that student is not one of your assigned advisees. Do not reveal anything "
                        "about them.")


_PLAN_ARGS = {"target_term": {"type": "string", "description": "Graduation term the student wants, as said "
                                                               "('Spring 2028'). Omit for 'as early as possible'."},
              "max_credits": {"type": "number", "description": "Most credits per term the student wants."},
              "avoid_days": {"type": "string", "description": "Weekdays to avoid as letters, e.g. 'F' for Friday."}}

STUDENT_ADVISING_SPECS = [_fn(
    "plan_my_degree", "Plan the logged-in student's remaining terms to graduation with the course planner: what to "
    "take next term, the earliest graduation term, required courses left, credits and GPA. Use for 'what should I "
    "take next', 'when can I graduate', 'make me a plan', 'can I graduate by X'.", _PLAN_ARGS)]
ADVISOR_SPECS = [
    _fn("get_my_advisees", "The active students assigned to the logged-in instructor for advising."),
    _fn("plan_for_advisee", "Plan an assigned advisee's remaining terms (next term, earliest graduation, required "
        "courses left). Refused for anyone who is not assigned to this instructor.",
        {"student": {"type": "string", "description": "Advisee's name or university ID."}, **_PLAN_ARGS},
        ["student"]),
]
