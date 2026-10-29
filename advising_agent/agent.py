"""Advising agent: access check -> context -> ASP solve (with relaxations) -> independent validation -> answer.

The LLM is optional and only writes the explanation from the finished, validated result. It never picks courses."""
from __future__ import annotations

from typing import Callable

from .context import DEFAULT_PLANS, Context, build_context, project_terms
from .contracts import AdvisingRequest, AdvisingResponse, DataTools, PolicyTools
from .facts import build_facts, capacity_infeasible, graduation_lower_bound, max_load
from .solver import SolveResult, solve
from .validate import check_plan

REQUIRED_FIELDS = ("request_id", "as_of", "requester", "student_university_id")
MAX_EXTRA_TERMS = 4
LLM = Callable[[str], str]  # prompt -> text, e.g. a local Ollama model


class AdvisingAgent:
    def __init__(self, data: DataTools, policy: PolicyTools, llm: LLM | None = None):
        self.data, self.policy, self.llm = data, policy, llm

    # ---------------------------------------------------------------- entry point
    def handle(self, req: AdvisingRequest) -> AdvisingResponse:
        missing = [f for f in REQUIRED_FIELDS if f not in req]
        if missing:
            return {"request_id": req.get("request_id", ""), "allowed": True, "status": "needs_input",
                    "blockers": [{"code": "missing_field", "fields": missing}]}
        if not self._may_view(req):
            return {"request_id": req["request_id"], "allowed": False, "status": "denied",
                    "blockers": [{"code": "not_own_record_or_advisee"}]}

        ctx = build_context(req, self.data, self.policy)
        if ctx.student["status"] != "active":
            return {"request_id": req["request_id"], "allowed": True, "status": "not_eligible",
                    "blockers": [{"code": "student_not_active", "status": ctx.student["status"]}]}

        static = self._static_blockers(ctx)
        if static:
            return self._answer(ctx, "infeasible", None, [], blockers=static)

        # Relaxation ladder, least intrusive first: drop the hard target, then plan more terms (keeps the
        # student's own credit cap), then drop the credit-cap preference, then both. The first that is
        # satisfiable wins, and the answer lists exactly what was relaxed.
        has_target = bool(req.get("target_is_hard") and req.get("target_graduation_term_code"))
        has_pref = bool(req.get("preferences", {}).get("max_credits_per_term"))
        base_terms = list(ctx.terms)
        ladder = [(True, True, 0)]
        if has_target:
            ladder.append((False, True, 0))
        ladder += [(False, True, k) for k in range(1, MAX_EXTRA_TERMS + 1)]
        if has_pref:
            ladder += [(False, False, k) for k in range(0, MAX_EXTRA_TERMS + 1)]
        for target, use_pref, extra in ladder:
            ctx.terms = base_terms + (project_terms(base_terms[-1], extra, req.get("include_summer", False))
                                      if extra else [])
            result = self._solve(ctx, target=target, use_load_pref=use_pref)
            if not result.satisfiable and result.timed_out:
                return self._answer(ctx, "timeout", None, [], blockers=[{"code": "solver_timeout_no_plan"}])
            if result.satisfiable:
                relaxed = ([] if target or not has_target else ["target_graduation_term"]) \
                    + ([f"horizon extended by {extra} term(s)"] if extra else []) \
                    + ([] if use_pref or not has_pref else ["max_credits_per_term preference"])
                status = ("horizon_too_short" if extra else "load_infeasible" if not use_pref
                          else "target_infeasible" if not target else "ok")
                return self._answer(ctx, status, result, relaxed)
        ctx.terms = base_terms
        return self._answer(ctx, "infeasible", None, ["all"], blockers=[{"code": "no_plan_after_relaxing"}])

    # ---------------------------------------------------------------- helpers
    def _may_view(self, req: AdvisingRequest) -> bool:
        who, sid = req["requester"], req["student_university_id"]
        if who["role"] == "student":
            return who["university_id"] == sid
        if who["role"] == "instructor":
            return self.data.is_advisor_of(who["university_id"], sid)
        return who["role"] == "admin"

    def _solve(self, ctx: Context, target: bool = True, use_load_pref: bool = True) -> SolveResult:
        ctx._use_load_pref = use_load_pref  # type: ignore[attr-defined]
        if capacity_infeasible(ctx, use_load_pref):  # proven in Python, no solver call
            return SolveResult(False, False, [], [], 0.0)
        return solve(build_facts(ctx, target=target, use_load_pref=use_load_pref),
                     ctx.request.get("num_plans", DEFAULT_PLANS), grad_lb=graduation_lower_bound(ctx, use_load_pref))

    def _static_blockers(self, ctx: Context) -> list[dict]:
        out = []
        published = {l["course_code"] for l in ctx.lectures}
        for r in ctx.degree_plan:
            c = r["course_code"]
            if not r["is_required"] or c in ctx.best_points or c in ctx.in_progress:
                continue
            if c not in ctx.courses:
                out.append({"code": "required_course_inactive", "course": c})
            elif c not in published and not (ctx.offered_hist.get(c, set()) & {t["term_type"] for t in ctx.terms}):
                out.append({"code": "required_course_not_offered", "course": c})
        allowed = set(ctx.policy["allowed_levels_by_degree"][ctx.program["degree"]])
        have = {c for c, p in ctx.best_points.items() if p > 0} | ctx.in_progress | ctx.waived

        def reachable(c: str, seen: frozenset = frozenset()) -> bool:
            if c in have:
                return True
            if c in seen or c not in ctx.courses or ctx.courses[c]["level"] not in allowed:
                return False
            groups: dict[int, list[str]] = {}
            for p in ctx.prereqs:
                if p["course_code"] == c:
                    groups.setdefault(p["group_number"], []).append(p["required_course_code"])
            return all(any(reachable(r, seen | {c}) for r in alts) for alts in groups.values())

        for r in ctx.degree_plan:
            if r["is_required"] and not reachable(r["course_code"]):
                out.append({"code": "required_course_unreachable", "course": r["course_code"],
                            "reason": "a prerequisite is neither completed nor takeable at this student's level"})
        return out

    def _remaining(self, ctx: Context) -> dict:
        done = {c for c, p in ctx.best_points.items() if p > 0} | ctx.in_progress
        req = sorted(r["course_code"] for r in ctx.degree_plan if r["is_required"] and r["course_code"] not in done)
        earned = sum(float(ctx.courses[c]["credit_hours"]) for c in done if c in ctx.courses)
        cats = {}
        for r in ctx.category_mins:
            got = sum(float(ctx.courses[d["course_code"]]["credit_hours"]) for d in ctx.degree_plan
                      if d["category"] == r["category"] and d["course_code"] in done and d["course_code"] in ctx.courses)
            cats[r["category"]] = {"needed": r["min_credits"], "earned": got}
        return {"required_courses": req, "categories": cats, "credits_earned": earned,
                "credits_required": ctx.program["total_credits_required"],
                "cumulative_gpa": ctx.cum_gpa, "program_min_gpa": float(ctx.program["min_gpa"]),
                "standing": ctx.standing}

    def _plans(self, ctx: Context, result: SolveResult) -> list[dict]:
        cat = {r["course_code"]: r["category"] for r in ctx.degree_plan}
        retakes = {c for c, p in ctx.best_points.items() if p > 0}
        plans = []
        for rank, m in enumerate(result.models, start=1):
            terms = []
            for i, t in enumerate(ctx.terms, start=1):
                if m.grad is None or i > m.grad:
                    break
                cs = [{"course_code": c, "credit_hours": float(ctx.courses[c]["credit_hours"]),
                       "category": "free_elective" if c in ctx.placeholders else cat.get(c),
                       "crn": m.sec.get((c, i)), "is_retake": c in retakes}
                      for c, ti in sorted(m.take.items()) if ti == i]
                terms.append({"term_code": t["code"], "term_name": t["name"], "term_type": t["term_type"],
                              "is_projected": t["is_projected"], "credits": m.load.get(i, 0) / 10, "courses": cs})
            done = {c for c, p in ctx.best_points.items() if p > 0} | ctx.in_progress | set(m.take)
            plans.append({
                "rank": rank,
                "graduation_term_code": ctx.terms[m.grad - 1]["code"] if m.grad else None,
                "terms": terms,
                "total_credits_after": sum(float(ctx.courses[c]["credit_hours"]) for c in done if c in ctx.courses),
                "penalties": self._penalties(ctx, m),
            })
        return plans

    @staticmethod
    def _penalties(ctx: Context, m) -> dict:
        prefs = ctx.request.get("preferences", {})
        avoid = {p["course_code"] for p in prefs.get("avoid_courses", [])}
        prefer = {p["course_code"] for p in prefs.get("prefer_courses", [])}
        bad_days = set(prefs.get("avoid_days", ""))
        lec = {l["crn"]: l for l in ctx.lectures}
        return {
            "terms_used": m.grad or 0,
            "avoided_courses_taken": sorted(avoid & set(m.take)),
            "preferred_courses_taken": sorted(prefer & set(m.take)),
            "sections_on_avoided_days": sorted(n for n in m.sec.values() if bad_days & set(lec[n]["days"])),
            "planned_credits": sum(float(ctx.courses[c]["credit_hours"]) for c in m.take),
        }

    def _answer(self, ctx: Context, status: str, result: SolveResult | None, relaxed: list[str],
                blockers: list[dict] | None = None) -> AdvisingResponse:
        resp: AdvisingResponse = {
            "request_id": ctx.request["request_id"], "allowed": True, "status": status,  # type: ignore[typeddict-item]
            "remaining": self._remaining(ctx), "blockers": blockers or [], "relaxed": relaxed,
            "assumptions": ctx.assumptions, "plans": [], "earliest_graduation_term_code": None,
            "must_take_next_term": [], "registration_handoff": None,
            "citations": self.policy.cite(["max_credits_by_standing", "repeat_rule", "allowed_levels_by_degree",
                                           "probation_rule"]),
        }
        if result is not None:
            plans = self._plans(ctx, result)
            use_pref = getattr(ctx, "_use_load_pref", True)
            cap = max_load(ctx, use_pref)
            minl = ctx.request.get("preferences", {}).get("min_credits_per_term")
            for p in plans:
                p["violations"] = check_plan(ctx, p, cap, minl)
            if any(p["violations"] for p in plans):
                resp["status"] = "error"  # type: ignore[typeddict-item]
                resp["blockers"].append({"code": "validator_disagrees_with_solver"})
            resp["plans"] = plans
            resp["earliest_graduation_term_code"] = plans[0]["graduation_term_code"] if plans else None
            resp["must_take_next_term"] = result.cautious_first_term
            if result.timed_out:
                note = ("The graduation term is proven earliest; the course mix was not fully optimized within the "
                        "time limit." if result.graduation_proven else
                        "The solver hit its time limit: the plan meets every rule but may not graduate earliest.")
                resp["assumptions"] = resp["assumptions"] + [note]
            if not result.graduation_proven:
                resp["earliest_graduation_term_code"] = None  # a plan exists, but "earliest" is not proven
            first = plans[0]["terms"][0] if plans and plans[0]["terms"] else None
            if first and not first["is_projected"]:
                resp["registration_handoff"] = [{"term_code": first["term_code"], "crn": c["crn"],
                                                 "course_code": c["course_code"]} for c in first["courses"]]
            resp["solver"] = {"engine": "clingo", "optimal": result.optimal,
                              "graduation_proven": result.graduation_proven,
                              "must_take_proven": result.cautious_first_term is not None,
                              "seconds": round(result.seconds, 3), "plans_found": len(plans)}
        resp["explanation"] = self._explain(resp)
        return resp

    def _explain(self, resp: AdvisingResponse) -> str:
        facts = template_explanation(resp)
        if self.llm is None:
            return facts
        prompt = ("Rewrite the advising result below for the student in plain English. Do not add, remove or "
                  "change any course, term, CRN or number. Mention the assumptions.\n\n" + facts)
        return self.llm(prompt)


def template_explanation(resp: AdvisingResponse) -> str:
    lines = [f"Status: {resp['status']}."]
    rem = resp.get("remaining", {})
    if rem:
        lines.append(f"Credits earned {rem['credits_earned']:g} of {rem['credits_required']}; "
                     f"required courses left: {', '.join(rem['required_courses']) or 'none'}.")
    if resp.get("relaxed"):
        lines.append("To find a plan, I relaxed: " + "; ".join(resp["relaxed"]) + ".")
    if resp.get("plans"):
        p = resp["plans"][0]
        lines.append(f"Earliest graduation: {p['graduation_term_code']}.")
        for t in p["terms"]:
            cs = ", ".join(c["course_code"] + (f" (CRN {c['crn']})" if c["crn"] else "") + (" [repeat]" if c["is_retake"] else "")
                           for c in t["courses"])
            lines.append(f"{t['term_name']}{' (projected)' if t['is_projected'] else ''}: {cs} = {t['credits']:g} cr.")
        if resp.get("must_take_next_term"):
            lines.append("In every optimal plan, next term includes: " + ", ".join(resp["must_take_next_term"]) + ".")
    for b in resp.get("blockers", []):
        lines.append(f"Blocker: {b}")
    return "\n".join(lines)
