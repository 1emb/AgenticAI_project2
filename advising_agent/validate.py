"""Independent plan check in plain Python. It does not reuse the ASP encoding, so a bug in either one shows up
as a disagreement. The Registration agent can reuse check_term() for a single term."""
from __future__ import annotations

from .context import Context
from .facts import overlaps


def check_plan(ctx: Context, plan: dict, max_load: float, min_load: float | None) -> list[str]:
    v: list[str] = []
    pts = ctx.points
    have: dict[str, float] = dict(ctx.best_points)  # course -> points assumed available
    for c in ctx.in_progress:
        have[c] = 4.0
    lec_by_crn = {(l["term_code"], l["crn"]): l for l in ctx.lectures}
    allowed = set(ctx.policy["allowed_levels_by_degree"][ctx.program["degree"]])
    groups: dict[str, dict[int, list[tuple[str, float]]]] = {}
    for p in ctx.prereqs:
        groups.setdefault(p["course_code"], {}).setdefault(p["group_number"], []).append(
            (p["required_course_code"], pts[p["min_grade"]] or 0.0))

    planned_terms = [t for t in plan["terms"] if t["courses"]]
    for k, t in enumerate(planned_terms):
        credits = sum(c["credit_hours"] for c in t["courses"])
        if credits > max_load + 1e-9:
            v.append(f"{t['term_code']}: {credits} credits above cap {max_load}")
        if min_load and k < len(planned_terms) - 1 and credits < min_load - 1e-9:
            v.append(f"{t['term_code']}: {credits} credits below minimum {min_load}")
        secs = []
        for c in t["courses"]:
            code = c["course_code"]
            if ctx.courses[code]["level"] not in allowed:
                v.append(f"{code}: level not allowed")
            for g, alts in groups.get(code, {}).items():
                if not any(have.get(r, -1) >= m for r, m in alts):
                    v.append(f"{t['term_code']} {code}: prerequisite group {g} not met")
            if t["is_projected"]:
                if t["term_type"] not in ctx.offered_hist.get(code, set()):
                    v.append(f"{t['term_code']} {code}: not offered in {t['term_type']} terms")
            else:
                lec = lec_by_crn.get((t["term_code"], c["crn"]))
                if lec is None or lec["course_code"] != code:
                    v.append(f"{t['term_code']} {code}: CRN {c['crn']} is not a lecture of this course")
                else:
                    if lec["seats_taken"] is not None and lec["seats_taken"] >= lec["capacity"]:
                        v.append(f"{t['term_code']} {code}: CRN {c['crn']} is full")
                    secs.append(lec)
        for i, a in enumerate(secs):
            for b in secs[i + 1:]:
                if overlaps(a, b):
                    v.append(f"{t['term_code']}: CRN {a['crn']} and {b['crn']} overlap")
        for c in t["courses"]:  # available from the next term on
            have[c["course_code"]] = 4.0

    fin = {c for c, p in have.items() if p > 0}
    for r in ctx.degree_plan:
        if r["is_required"] and r["course_code"] not in fin:
            v.append(f"required course {r['course_code']} missing")
    for r in ctx.category_mins:
        got = sum(float(ctx.courses[d["course_code"]]["credit_hours"]) for d in ctx.degree_plan
                  if d["category"] == r["category"] and d["course_code"] in fin and d["course_code"] in ctx.courses)
        if got < r["min_credits"] - 1e-9:
            v.append(f"category {r['category']}: {got} of {r['min_credits']} credits")
    total = sum(float(ctx.courses[c]["credit_hours"]) for c in fin if c in ctx.courses)
    if total < ctx.program["total_credits_required"] - 1e-9:
        v.append(f"total credits {total} below {ctx.program['total_credits_required']}")
    return v
