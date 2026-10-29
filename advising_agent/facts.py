"""Context -> ASP facts. Deterministic translation; integers in tenths."""
from __future__ import annotations

from .context import Context


def tenths(x: float) -> int:
    return int(round(float(x) * 10))


def q(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


def minutes(hhmm: str) -> int:
    h, m = hhmm[:5].split(":")
    return int(h) * 60 + int(m)


def overlaps(a: dict, b: dict) -> bool:
    if not set(a["days"]) & set(b["days"]):
        return False
    return minutes(a["start_time"]) < minutes(b["end_time"]) and minutes(b["start_time"]) < minutes(a["end_time"])


def max_load(ctx: Context, use_preference: bool = True) -> float:
    cap = float(ctx.policy["max_credits_by_standing"][ctx.standing])
    pref = ctx.request.get("preferences", {}).get("max_credits_per_term")
    return min(cap, float(pref)) if (use_preference and pref) else cap


def build_facts(ctx: Context, *, target: bool = True, use_load_pref: bool = True) -> str:
    f: list[str] = []
    term_index = {t["code"]: i for i, t in enumerate(ctx.terms, start=1)}
    for i, t in enumerate(ctx.terms, start=1):
        f.append(f"term({i}). term_type({i},{t['term_type']}).")
        if not t["is_projected"]:
            f.append(f"published({i}).")

    for lvl in ctx.policy["allowed_levels_by_degree"][ctx.program["degree"]]:
        f.append(f"allowed_level({lvl}).")
    for c in ctx.courses.values():
        f.append(f"course({q(c['code'])},{tenths(c['credit_hours'])}). level({q(c['code'])},{c['level']}).")
    for c, types in ctx.offered_hist.items():
        for y in sorted(types):
            f.append(f"offered_hist({q(c)},{y}).")

    by_term: dict[int, list[dict]] = {}
    for lec in ctx.lectures:
        i = term_index.get(lec["term_code"])
        if i is None:
            continue
        f.append(f"lecture({i},{q(lec['course_code'])},{q(lec['crn'])}).")
        if lec["seats_taken"] is not None and lec["seats_taken"] >= lec["capacity"]:
            f.append(f"full({i},{q(lec['crn'])}).")
        by_term.setdefault(i, []).append(lec)
    for i, lecs in by_term.items():
        for a in lecs:
            for b in lecs:
                if a["crn"] < b["crn"] and overlaps(a, b):
                    f.append(f"overlap({i},{q(a['crn'])},{q(b['crn'])}). overlap({i},{q(b['crn'])},{q(a['crn'])}).")

    for c, p in ctx.best_points.items():
        f.append(f"completed({q(c)},{tenths(p)}).")
    for c in ctx.in_progress:
        f.append(f"in_progress({q(c)}).")
    for c, tcode, crn in ctx.fixed:
        f.append(f"fixed({q(c)},{term_index[tcode]},{q(crn)}).")

    for p in ctx.prereqs:
        m = ctx.points[p["min_grade"]] or 0.0
        f.append(f"prereq({q(p['course_code'])},{p['group_number']},{q(p['required_course_code'])},{tenths(m)}).")
    if ctx.policy["repeat_rule"] == "below_prereq_min":
        f.append("repeat_below_prereq_min.")

    for r in ctx.degree_plan:
        f.append(f"req_course({r['category']},{q(r['course_code'])}).")
        if r["is_required"]:
            f.append(f"required({q(r['course_code'])}).")
    for r in ctx.category_mins:
        f.append(f"cat_min({r['category']},{tenths(r['min_credits'])}).")
    f.append(f"total_credits({tenths(ctx.program['total_credits_required'])}).")

    prefs = ctx.request.get("preferences", {})
    f.append(f"max_load({tenths(max_load(ctx, use_load_pref))}).")
    if prefs.get("min_credits_per_term"):
        f.append(f"min_load({tenths(prefs['min_credits_per_term'])}).")
    tgt = ctx.request.get("target_graduation_term_code")
    if target and tgt and ctx.request.get("target_is_hard") and tgt in term_index:
        f.append(f"target({term_index[tgt]}).")
    for p in prefs.get("prefer_courses", []):
        f.append(f"prefer({q(p['course_code'])},{p['weight']}).")
    for p in prefs.get("avoid_courses", []):
        f.append(f"avoid({q(p['course_code'])},{p['weight']}).")
    avoid_days = set(prefs.get("avoid_days", ""))
    for i, lecs in by_term.items():
        for lec in lecs:
            bad = bool(avoid_days & set(lec["days"]))
            if prefs.get("earliest_start") and minutes(lec["start_time"]) < minutes(prefs["earliest_start"]):
                bad = True
            if prefs.get("latest_end") and minutes(lec["end_time"]) > minutes(prefs["latest_end"]):
                bad = True
            if bad:
                f.append(f"bad_slot({i},{q(lec['crn'])},1).")
    return "\n".join(f) + "\n"
