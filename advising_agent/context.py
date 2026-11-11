"""Assemble everything the solver needs from the Data and Policy tools, and derive the deterministic facts
(best grades, GPA, standing, current term). No LLM here: every number is computed in code."""
from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import (
    AdvisingRequest, CategoryRequirementRow, CourseRow, DataTools, DegreeRequirementRow, EnrollmentRow,
    LectureRow, PolicyParams, PolicyTools, PrerequisiteRow, ProgramRow, StudentRow, TermRow,
)

DEFAULT_HORIZON = 4
DEFAULT_PLANS = 3


@dataclass
class Context:
    request: AdvisingRequest
    student: StudentRow
    program: ProgramRow
    policy: PolicyParams
    points: dict[str, float | None]  # grade letter -> points
    current_term: TermRow | None
    terms: list[TermRow]  # planning terms, in order; projected ones have is_projected
    courses: dict[str, CourseRow]
    prereqs: list[PrerequisiteRow]
    degree_plan: list[DegreeRequirementRow]
    category_mins: list[CategoryRequirementRow]
    lectures: list[LectureRow]
    offered_hist: dict[str, set[str]]
    best_points: dict[str, float] = field(default_factory=dict)  # course -> best points with a grade
    in_progress: set[str] = field(default_factory=set)
    fixed: list[tuple[str, str, str]] = field(default_factory=list)  # (course, term_code, crn)
    withdrawn: set[str] = field(default_factory=set)
    cum_gpa: float | None = None
    last_term_gpa: float | None = None
    standing: str = "good"
    assumptions: list[str] = field(default_factory=list)
    candidates: set[str] = field(default_factory=set)  # courses the solver may plan
    waived: set[str] = field(default_factory=set)  # prerequisites treated as met (not credited)
    placeholders: list[str] = field(default_factory=list)  # generic free-elective slots


def project_terms(last: TermRow | None, n: int, include_summer: bool) -> list[TermRow]:
    """Terms beyond those stored in academic_term. Codes follow 202680 = Fall 2026, 202710 = Spring 2027;
    the summer suffix 60 is an assumption until the data team confirms it."""
    order = ["spring", "summer", "fall"] if include_summer else ["spring", "fall"]
    suffix = {"spring": "10", "summer": "60", "fall": "80"}
    name = {"spring": "Spring", "summer": "Summer", "fall": "Fall"}
    if last is None:
        raise ValueError("cannot project terms without at least one stored term")
    year, ttype, seq = int(last["code"][:4]), last["term_type"], last["sequence"]
    out: list[TermRow] = []
    while len(out) < n:
        i = order.index(ttype) if ttype in order else len(order) - 1
        if i + 1 < len(order):
            ttype = order[i + 1]
        else:
            ttype, year = order[0], year + 1
        seq += 1
        out.append({"code": f"{year}{suffix[ttype]}", "name": f"{name[ttype]} {year}", "term_type": ttype,
                    "start_date": "", "end_date": "", "sequence": seq, "is_projected": True})  # type: ignore[typeddict-unknown-key]
    return out


def gpa(rows: list[tuple[float, float]]) -> float | None:
    cr = sum(c for _, c in rows)
    return round(sum(p * c for p, c in rows) / cr, 2) if cr else None


def build_context(req: AdvisingRequest, data: DataTools, policy: PolicyTools) -> Context:
    sid = req["student_university_id"]
    student = data.get_student(sid)
    program = data.get_program(student["program_code"])
    params = policy.get_params()
    points = {g["letter"]: g["points"] for g in data.get_grade_scale()}

    n = req.get("horizon_terms", DEFAULT_HORIZON)
    include_summer = req.get("include_summer", False)
    current, stored = data.get_terms_after(req["as_of"], n, include_summer)
    terms = [dict(t, is_projected=False) for t in stored]
    if len(terms) < n:
        terms += project_terms(terms[-1] if terms else current, n - len(terms), include_summer)

    courses = {c["code"]: c for c in data.get_courses() if c["is_active"]}
    plan_rows, cat_rows = data.get_degree_plan(student["program_code"])
    stored_codes = [t["code"] for t in terms if not t["is_projected"]]
    lectures = [l for l in data.get_lectures(stored_codes) if not l["is_cancelled"]]
    with_lectures = {l["term_code"] for l in lectures}
    for t in terms:  # a stored term without lecture rows has no published schedule yet: plan it as projected
        if not t["is_projected"] and t["code"] not in with_lectures:
            t["is_projected"] = True
    hist = {h["course_code"]: set(h["term_types"]) for h in data.get_offering_history(list(courses))}

    ctx = Context(req, student, program, params, points, current, terms, courses, data.get_prerequisites(),
                  plan_rows, cat_rows, lectures, hist)

    # ---- history from enrollment ----
    plan_terms = {t["code"] for t in terms}
    by_term: dict[str, list[tuple[float, float]]] = {}
    for e in data.get_enrollments(sid):
        c = e["course_code"]
        if e["status"] == "dropped":
            continue
        if e["status"] == "withdrawn" or e["grade"] == "W":
            ctx.withdrawn.add(c)
            continue
        if e["term_code"] in plan_terms:
            ctx.fixed.append((c, e["term_code"], e["crn"]))
            continue
        if e["grade"] is None:
            if current and e["term_code"] == current["code"]:
                ctx.in_progress.add(c)
            continue
        p = points.get(e["grade"])
        if p is None:  # I (incomplete): no credit yet
            continue
        ctx.best_points[c] = max(p, ctx.best_points.get(c, -1.0))
        cr = float(courses[c]["credit_hours"]) if c in courses else 0.0
        by_term.setdefault(e["term_code"], []).append((p, cr))

    # Transfer credit (optional in the data contract): the course is done and meets any prerequisite minimum, but it
    # has no grade, so it stays out of the GPA terms above.
    for c in getattr(data, "get_transfer_credits", lambda _sid: [])(sid):
        ctx.best_points[c] = max(4.0, ctx.best_points.get(c, -1.0))

    graded_terms = sorted(by_term)
    ctx.cum_gpa = gpa([x for t in graded_terms for x in by_term[t]])
    ctx.last_term_gpa = gpa(by_term[graded_terms[-1]]) if graded_terms else None
    if params["probation_rule"] == "last_term_gpa_below_program_min" and ctx.last_term_gpa is not None:
        ctx.standing = "probation" if ctx.last_term_gpa < float(program["min_gpa"]) else "good"

    if ctx.program["degree"] == "MS" and params.get("grad_admit_meets_undergrad_prereqs"):
        in_plan = {r["course_code"] for r in plan_rows}
        ctx.waived = {c for c, row in courses.items() if row["level"] != "graduate" and c not in in_plan}
        ctx.assumptions.append("As a graduate admit, undergraduate prerequisites outside the MS plan are treated as met.")
    select_candidates(ctx)

    if ctx.in_progress:
        ctx.assumptions.append("Courses in progress are assumed passed with at least the prerequisite minimum.")
    ctx.assumptions.append("Every planned course is assumed passed with at least the prerequisite minimum.")
    if any(t["is_projected"] for t in terms):
        ctx.assumptions.append("Terms without published lectures use the course's past offering pattern "
                               "(fall/spring/summer); sections and seats are not checked there.")
    if any(l["seats_taken"] is None for l in lectures):
        ctx.assumptions.append("Seat counts are unknown (no enrollment data), so sections are not checked for being full.")
    return ctx


FREE_ELECTIVE_CREDITS = 3.0


def select_candidates(ctx: Context) -> None:
    """Limit the search to degree-plan courses, their prerequisites (transitively) and preferred courses.
    If those cannot reach the program's total credits, add generic free-elective slots. Without this, every
    catalog course is a choice and optimality proofs on a 200-course catalog exceed the time limit."""
    pre: dict[str, set[str]] = {}
    for p in ctx.prereqs:
        pre.setdefault(p["course_code"], set()).add(p["required_course_code"])
    todo = [r["course_code"] for r in ctx.degree_plan]
    todo += [p["course_code"] for p in ctx.request.get("preferences", {}).get("prefer_courses", [])]
    cand: set[str] = set()
    while todo:
        c = todo.pop()
        if c in cand or c not in ctx.courses or c in ctx.waived:
            continue
        cand.add(c)
        todo.extend(pre.get(c, ()))
    ctx.candidates = cand
    done = {c for c, p in ctx.best_points.items() if p > 0} | ctx.in_progress
    reachable = sum(float(ctx.courses[c]["credit_hours"]) for c in cand | done if c in ctx.courses)
    deficit = float(ctx.program["total_credits_required"]) - reachable
    k = max(0, int(-(-deficit // FREE_ELECTIVE_CREDITS)))  # ceil
    for i in range(1, k + 1):
        code = f"FREE ELECTIVE {i}"
        ctx.courses[code] = {"code": code, "title": "Free elective", "credit_hours": FREE_ELECTIVE_CREDITS,
                             "level": "lower_division", "is_active": True}
        ctx.placeholders.append(code)
    if k:
        ctx.assumptions.append(f"{k} free-elective slot(s) of {FREE_ELECTIVE_CREDITS:g} credits stand for any "
                               "course without prerequisites; the student picks them later.")
