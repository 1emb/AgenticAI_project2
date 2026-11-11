"""Turn the agents' results into one reply. Facts the agents verified are rendered deterministically where the shape is
known (GPA, degree plan, policy references); anything else uses the agent's own reply, which its grounding check already
vouched for. Failures are fixed sentences, never model prose."""
from __future__ import annotations

from registrar.agents.multi.agents import ADVISING, DATA, NOT_COVERED, POLICY, REFUSED, REGISTRATION, UNVERIFIED, AgentResult


def _format_gpa(answer: dict) -> str:
    """Format verified GPA information from the academic-record tool (built in code, never by the model)."""
    lines = []
    if answer.get("cumulative_gpa") is not None:
        lines.append(f"Cumulative GPA: {answer['cumulative_gpa']:.2f}")
    if answer.get("last_term_gpa") is not None:
        term = answer.get("last_term") or "Last graded term"
        lines.append(f"{term} GPA: {answer['last_term_gpa']:.2f}")
    if answer.get("credits_earned") is not None:
        lines.append(f"Credits earned: {answer['credits_earned']:g}")
    return "\n".join(lines)


def format_plan(call_result: dict) -> str:
    """The advising agent's tool result: term-by-term plan with projected flags, then assumptions and blockers."""
    a, lines = call_result.get("answer") or {}, []
    for t in call_result.get("plan") or []:
        courses = ", ".join(t.get("courses") or []) or "no courses"
        lines.append(f"- {t['term']}{' (projected)' if t.get('projected') else ''}, {t.get('credits', 0):g} credits: {courses}")
    if lines:
        lines.insert(0, "Plan:")
    if a.get("earliest_graduation_term"):
        lines.append(f"Earliest projected graduation: {a['earliest_graduation_term']}")
    if a.get("remaining_required"):
        lines.append(f"Required courses still to take: {', '.join(a['remaining_required'])}")
    if call_result.get("assumptions"):
        lines.append("Assumptions: " + "; ".join(str(x) for x in call_result["assumptions"]))
    if call_result.get("blockers"):
        lines.append("Blockers: " + "; ".join(str(x) for x in call_result["blockers"]))
    if a.get("status") not in (None, "ok"):
        lines.append(f"Planning status: {a['status']}")
    return "\n".join(lines)


def one(r: AgentResult) -> str:
    if r.status == "refused" or r.answer.get("allowed") is False and not r.answer.get("own_answer"):
        return REFUSED
    if r.status == "ungrounded":
        errors = [c.result["error"] for c in r.calls if not c.ok and isinstance(c.result, dict) and c.result.get("error")]
        if r.agent == REGISTRATION and errors:   # tool errors are the system's own sentences, safe to show as they are
            return f"I couldn't make that change: {errors[-1]}"
        return UNVERIFIED
    if r.status == "no_source":
        return NOT_COVERED
    ok = [c for c in r.calls if c.ok and c.name != "decline_request"]
    names = {c.name for c in ok}
    if r.agent == DATA and names == {"get_my_gpa"}:
        return _format_gpa(r.answer) or UNVERIFIED
    if r.agent == ADVISING:
        plans = [c for c in ok if c.name in ("plan_my_degree", "plan_for_advisee")]
        if plans:
            return format_plan(plans[-1].result) or r.reply
    if r.agent == POLICY and r.answer.get("policy_sections"):
        return f"{r.reply}\n\nPolicy references: {', '.join(str(s) for s in r.answer['policy_sections'])}"
    return r.reply


def compose(results: list[AgentResult]) -> str:
    if len(results) == 1:
        return one(results[0])
    return "\n\n".join(f"{r.question}\n{one(r)}" for r in results)
