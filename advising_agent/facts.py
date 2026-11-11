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


def term_windows(ctx: Context, keep: set[str]) -> tuple[dict[str, int], dict[str, int]]:
    """Redundant bounds that prune the search (they never remove a valid plan).
    earliest[C]: first term index where C is offered and every prerequisite group can already be met.
    latest[C]  : for required C, the last index that leaves room for required courses that need C
                 (C is the only option in one of their groups) in later offered terms."""
    H = len(ctx.terms)
    ttype = {i: t["term_type"] for i, t in enumerate(ctx.terms, start=1)}
    published = {i for i, t in enumerate(ctx.terms, start=1) if not t["is_projected"]}
    lect = {(l["term_code"], l["course_code"]) for l in ctx.lectures}

    def offered(c: str, i: int) -> bool:
        if c in ctx.placeholders:
            return True
        if i in published:
            return (ctx.terms[i - 1]["code"], c) in lect
        return ttype[i] in ctx.offered_hist.get(c, set())

    done = {c for c, p in ctx.best_points.items() if p > 0} | ctx.in_progress
    groups: dict[str, dict[int, list[str]]] = {}
    for p in ctx.prereqs:
        if p["course_code"] in keep:
            groups.setdefault(p["course_code"], {}).setdefault(p["group_number"], []).append(p["required_course_code"])
    INF = H + 1
    avail = {c: 0 for c in done | ctx.waived}  # usable from term 1 on

    def ready(c: str, i: int) -> bool:
        return all(any(avail.get(r, INF) < i for r in alts) for alts in groups.get(c, {}).values())

    earliest: dict[str, int] = {}
    changed = True
    while changed:
        changed = False
        for c in keep:
            for i in range(1, H + 1):
                if offered(c, i) and ready(c, i):
                    if earliest.get(c, INF) > i:
                        earliest[c] = i
                        changed = True
                    break
            if c not in done and c in earliest and avail.get(c, INF) > earliest[c]:
                avail[c] = earliest[c]
                changed = True

    required = {r["course_code"] for r in ctx.degree_plan if r["is_required"]} - done
    sole_needers: dict[str, set[str]] = {}
    for d, gs in groups.items():
        if d in required:
            for alts in gs.values():
                if len(alts) == 1:
                    sole_needers.setdefault(alts[0], set()).add(d)
    latest: dict[str, int] = {}

    def lst(c: str, stack: frozenset = frozenset()) -> int:
        if c in latest:
            return latest[c]
        bound = H
        for d in sole_needers.get(c, ()):
            if d in stack:
                continue
            bound = min(bound, lst(d, stack | {c}) - 1)
        i = bound
        while i >= 1 and not offered(c, i):
            i -= 1
        latest[c] = i
        return i

    for c in required:
        lst(c)
    return earliest, {c: v for c, v in latest.items() if c in required}


def build_facts(ctx: Context, *, target: bool = True, use_load_pref: bool = True) -> str:
    f: list[str] = []
    term_index = {t["code"]: i for i, t in enumerate(ctx.terms, start=1)}
    for i, t in enumerate(ctx.terms, start=1):
        f.append(f"term({i}). term_type({i},{t['term_type']}).")
        if not t["is_projected"]:
            f.append(f"published({i}).")

    for lvl in ctx.policy["allowed_levels_by_degree"][ctx.program["degree"]]:
        f.append(f"allowed_level({lvl}).")
    keep = ctx.candidates | set(ctx.best_points) | ctx.in_progress | {c for c, _, _ in ctx.fixed}
    keep |= set(ctx.placeholders)
    for code in sorted(keep):
        c = ctx.courses.get(code)
        if c is None:
            continue
        f.append(f"course({q(code)},{tenths(c['credit_hours'])}). level({q(code)},{c['level']}).")
    for c, types in ctx.offered_hist.items():
        if c in keep:
            for y in sorted(types):
                f.append(f"offered_hist({q(c)},{y}).")
    lo, hi = term_windows(ctx, keep)
    f.append(f"grad_lb({graduation_lower_bound(ctx, use_load_pref)}).")
    for c, e in lo.items():
        f.append(f"earliest({q(c)},{e}).")
    for c, l in hi.items():
        f.append(f"latest({q(c)},{l}).")
    for i, c in enumerate(ctx.placeholders):
        f.append(f"placeholder({q(c)}).")
        if i:
            f.append(f"ph_order({q(ctx.placeholders[i - 1])},{q(c)}).")

    by_term: dict[int, list[dict]] = {}
    for lec in ctx.lectures:
        i = term_index.get(lec["term_code"])
        if i is None or lec["course_code"] not in keep:
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
    for c in sorted(ctx.waived):
        f.append(f"waived({q(c)}).")
    for c, tcode, crn in ctx.fixed:
        f.append(f"fixed({q(c)},{term_index[tcode]},{q(crn)}).")

    for p in ctx.prereqs:
        if p["course_code"] not in keep:
            continue
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


def graduation_lower_bound(ctx: Context, use_load_pref: bool = True) -> int:
    """Smallest term index the plan can end in, from credits still needed and the per-term cap.
    Returned as len(terms) + 1 when even the full horizon is too short, and 0 when nothing is left to earn."""
    import math
    needed, first = _needed_and_first(ctx)
    if needed <= 1e-9:
        return 0
    return first + math.ceil(needed / max_load(ctx, use_load_pref) - 1e-9) - 1


def _needed_and_first(ctx: Context) -> tuple[float, int]:
    done = {c for c, p in ctx.best_points.items() if p > 0} | ctx.in_progress
    cr = lambda c: float(ctx.courses[c]["credit_hours"]) if c in ctx.courses else 0.0
    earned = sum(cr(c) for c in done)
    req_left = sum(cr(r["course_code"]) for r in ctx.degree_plan if r["is_required"] and r["course_code"] not in done)
    cat_short = 0.0
    for m in ctx.category_mins:
        rows = [d["course_code"] for d in ctx.degree_plan if d["category"] == m["category"]]
        have = sum(cr(c) for c in rows if c in done)
        req_in_cat = sum(cr(d["course_code"]) for d in ctx.degree_plan
                         if d["category"] == m["category"] and d["is_required"] and d["course_code"] not in done)
        cat_short += max(0.0, m["min_credits"] - have - req_in_cat)
    needed = max(float(ctx.program["total_credits_required"]) - earned, req_left + cat_short)
    keep = ctx.candidates | done | set(ctx.placeholders)
    lo, _ = term_windows(ctx, keep)
    return needed, min(lo.values(), default=len(ctx.terms) + 1)


def capacity_infeasible(ctx: Context, use_load_pref: bool = True) -> bool:
    """Necessary condition, checked in Python before solving: the credits still needed must fit into
    (per-term cap) x (terms in which some needed course can be taken). Proving this inside the solver
    is a pigeonhole argument, which CDCL solvers handle badly."""
    return graduation_lower_bound(ctx, use_load_pref) > len(ctx.terms)
