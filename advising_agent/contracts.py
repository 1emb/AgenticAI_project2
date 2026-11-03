"""Interfaces between the Advising agent and the rest of the system.

Every structure here mirrors a table in registrar/models/ (natural keys, same column names) or a message
between agents. docs/interface.html is the human-readable version of this file; keep the two in sync.

Directions:
    Router        -> Advising   AdvisingRequest
    Advising      -> Data agent DataTools (read-only tool calls)
    Advising      -> Policy     PolicyTools (parameters + citations)
    Advising      -> Router     AdvisingResponse
"""
from __future__ import annotations

from typing import Literal, Protocol, TypedDict

# ----------------------------------------------------------------------------------------------------------------
# Router -> Advising
# ----------------------------------------------------------------------------------------------------------------
Role = Literal["student", "instructor", "admin"]


class Requester(TypedDict):
    university_id: str  # from the login session, never from chat
    role: Role


class CoursePref(TypedDict):
    course_code: str  # "CS 4750"
    weight: int  # 1..5


class Preferences(TypedDict, total=False):
    max_credits_per_term: float  # student's own cap; the policy cap still applies
    min_credits_per_term: float  # last planned term is exempt
    prefer_courses: list[CoursePref]
    avoid_courses: list[CoursePref]
    avoid_days: str  # subset of MTWRFSU, soft
    earliest_start: str  # "09:00", soft
    latest_end: str  # "17:00", soft


class AdvisingRequest(TypedDict, total=False):
    request_id: str
    as_of: str  # ISO 8601 clock, same meaning as in data/testset
    requester: Requester
    student_university_id: str  # whose plan; equals requester for a student
    horizon_terms: int  # how many future terms to plan (default 4)
    include_summer: bool  # default False
    target_graduation_term_code: str | None  # "202810"
    target_is_hard: bool  # True: must graduate by target, else report earliest
    preferences: Preferences
    num_plans: int  # optimal alternatives to return (default 3)
    relax: list[str]  # internal: which constraints the solver relaxed


# ----------------------------------------------------------------------------------------------------------------
# Data agent -> Advising (rows, one TypedDict per table or derived view)
# ----------------------------------------------------------------------------------------------------------------
class StudentRow(TypedDict):  # table student (+ program joined)
    university_id: str
    program_code: str
    status: str  # active, leave_of_absence, withdrawn, suspended, dismissed, graduated
    admit_term_code: str
    expected_graduation_term_code: str | None


class ProgramRow(TypedDict):  # table program
    code: str
    degree: str  # BS, MS
    total_credits_required: int
    min_gpa: float


class EnrollmentRow(TypedDict):  # table enrollment (PROPOSED in README, not yet modeled)
    term_code: str
    crn: str
    course_code: str
    status: str  # enrolled, dropped, withdrawn
    grade: str | None  # letter from grade_scale; None = no grade yet


class GradeScaleRow(TypedDict):  # table grade_scale
    letter: str
    points: float | None  # None for W and I


class TermRow(TypedDict):  # table academic_term
    code: str
    name: str
    term_type: str  # fall, spring, summer
    start_date: str
    end_date: str
    sequence: int


class CourseRow(TypedDict):  # table course
    code: str
    title: str
    credit_hours: float
    level: str  # lower_division, upper_division, graduate
    is_active: bool


class PrerequisiteRow(TypedDict):  # table course_prerequisite
    course_code: str
    required_course_code: str
    min_grade: str  # letter; compare by grade_scale.points
    group_number: int  # same group = OR, different groups = AND


class DegreeRequirementRow(TypedDict):  # table degree_requirement
    program_code: str
    course_code: str
    category: str  # core, elective, general_education
    is_required: bool
    suggested_term_number: int | None


class CategoryRequirementRow(TypedDict):  # table program_category_requirement
    program_code: str
    category: str
    min_credits: int


class LectureRow(TypedDict):  # table lecture (+ seats_taken from enrollment count)
    term_code: str
    crn: str
    course_code: str
    section_number: str
    days: str  # subset of MTWRFSU
    start_time: str  # "HH:MM"
    end_time: str
    capacity: int
    is_cancelled: bool
    seats_taken: int | None  # None until enrollment exists; then full = seats_taken >= capacity


class OfferingHistoryRow(TypedDict):  # derived from lecture over past terms
    course_code: str
    term_types: list[str]  # term types in which the course had a non-cancelled lecture


class DataTools(Protocol):
    """Read-only tools the Data agent must expose. All calls are filtered by the requester's permissions."""

    def get_student(self, university_id: str) -> StudentRow: ...
    def get_program(self, program_code: str) -> ProgramRow: ...
    def get_enrollments(self, university_id: str) -> list[EnrollmentRow]: ...
    def get_grade_scale(self) -> list[GradeScaleRow]: ...
    def get_terms_after(self, as_of: str, n: int, include_summer: bool) -> tuple[TermRow | None, list[TermRow]]:
        """(current term by the README clock rule, the next n terms that have not started)."""
        ...
    def get_courses(self, codes: list[str] | None = None) -> list[CourseRow]: ...
    def get_prerequisites(self) -> list[PrerequisiteRow]: ...
    def get_degree_plan(self, program_code: str) -> tuple[list[DegreeRequirementRow], list[CategoryRequirementRow]]: ...
    def get_lectures(self, term_codes: list[str]) -> list[LectureRow]: ...
    def get_offering_history(self, course_codes: list[str]) -> list[OfferingHistoryRow]: ...
    def is_advisor_of(self, instructor_university_id: str, student_university_id: str) -> bool:
        """Needs an advisor assignment table, which the schema does not have yet."""
        ...


# ----------------------------------------------------------------------------------------------------------------
# Policy agent -> Advising
# ----------------------------------------------------------------------------------------------------------------
class Citation(TypedDict):
    key: str  # parameter name
    source: str  # "Synthetic Handbook, Sec. 3.2"
    text: str  # retrieved passage


class PolicyParams(TypedDict):
    max_credits_by_standing: dict[str, float]  # {"good": 18, "probation": 13}
    repeat_rule: Literal["below_prereq_min", "never", "always_if_below_C"]
    allowed_levels_by_degree: dict[str, list[str]]  # {"BS": ["lower_division", "upper_division"]}
    probation_rule: Literal["last_term_gpa_below_program_min"]  # per README note of 2026-10-28
    grad_admit_meets_undergrad_prereqs: bool  # MS students: prerequisites below graduate level that are not in
                                              # their degree plan count as met (no undergraduate record exists)


class PolicyTools(Protocol):
    def get_params(self) -> PolicyParams:
        """Typed values from the versioned policy config that matches the synthetic handbook.
        Not extracted by an LLM at run time: a wrong number here makes every plan wrong."""
        ...

    def cite(self, keys: list[str]) -> list[Citation]:
        """RAG over the handbook: the passages that justify each parameter, for the explanation."""
        ...


# ----------------------------------------------------------------------------------------------------------------
# Advising -> Router
# ----------------------------------------------------------------------------------------------------------------
Status = Literal[
    "ok",  # plans satisfy every hard constraint
    "requirements_met",  # every degree requirement is already met (courses in progress assumed passed)
    "target_infeasible",  # no plan meets the hard target; plans show the earliest feasible term
    "load_infeasible",  # student's max credits too low; plans use the policy cap instead
    "horizon_too_short",  # requirements need more terms than requested; plans use a longer horizon
    "infeasible",  # no plan even after relaxing; see blockers
    "not_eligible",  # student status is not active
    "denied",  # requester may not see this student's record
    "needs_input",  # required request fields missing
    "timeout",  # solver found no plan within the time limit (not proof of infeasibility)
    "error",  # independent validator disagrees with the solver (a bug)
]


class PlannedCourse(TypedDict):
    course_code: str
    credit_hours: float
    category: str | None  # degree_requirement.category; "free_elective" = generic slot toward total credits
    crn: str | None  # only for terms with published lectures
    is_retake: bool


class PlannedTerm(TypedDict):
    term_code: str
    term_name: str
    is_projected: bool  # True: no lectures published; offering inferred from history
    credits: float
    courses: list[PlannedCourse]


class Plan(TypedDict):
    rank: int
    graduation_term_code: str
    terms: list[PlannedTerm]
    total_credits_after: float
    penalties: dict[str, int]  # avoid, prefer, time preference, extra credits


class AdvisingResponse(TypedDict, total=False):
    request_id: str
    allowed: bool  # first field, as in data/testset
    status: Status
    plans: list[Plan]
    earliest_graduation_term_code: str | None
    must_take_next_term: list[str]  # courses in every optimal plan's first term (cautious reasoning)
    remaining: dict[str, object]  # what is still unmet before the plan
    blockers: list[dict[str, object]]  # reason codes with details
    assumptions: list[str]
    relaxed: list[str]
    citations: list[Citation]
    explanation: str  # prose for the user; never changes the plan
    solver: dict[str, object]  # engine, optimal, time
    registration_handoff: list[dict[str, str]] | None  # first-term CRNs; Router passes on only if the user asks
