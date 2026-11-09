
"""Compose responses from completed orchestration tasks."""

from registrar.agents.orchestrator.executor import PlanResult


def _format_gpa(answer: dict) -> str:
    """Format verified GPA information from the academic-record tool."""
    lines = []

    if answer.get("cumulative_gpa") is not None:
        lines.append(f"Cumulative GPA: {answer['cumulative_gpa']:.2f}")

    if answer.get("last_term_gpa") is not None:
        term = answer.get("last_term") or "Last graded term"
        lines.append(f"{term} GPA: {answer['last_term_gpa']:.2f}")

    if answer.get("credits_earned") is not None:
        lines.append(f"Credits earned: {answer['credits_earned']:g}")

    return "\n".join(lines)


def _format_advising(answer: dict) -> str:
    """Format verified advising results without inventing details."""
    lines = []

    term = answer.get("next_term")
    courses = answer.get("next_term_courses") or []

    if term and courses:
        lines.append(f"Recommended courses for {term}:")
        lines.extend(f"- {course}" for course in courses)
    elif term:
        lines.append(f"No courses were recommended for {term}.")

    graduation = answer.get("earliest_graduation_term")
    if graduation:
        lines.append(f"Earliest projected graduation: {graduation}")

    remaining = answer.get("remaining_required")
    if remaining:
        lines.append(f"Remaining required courses: {', '.join(remaining)}")

    if answer.get("credits_required") is not None:
        lines.append(f"Degree requires {answer['credits_required']:g} credits.")

    if answer.get("status") == "target_infeasible":
        lines.append(
            "The advising planner reported a target feasibility issue; "
            "the projected plan should be reviewed."
        )
    elif answer.get("status") not in (None, "ok"):
        lines.append(f"Planning status: {answer['status']}")

    return "\n".join(lines)


def _format_policy(answer: dict, reply: str) -> str:
    """Preserve the policy explanation and append verified section references."""
    sections = answer.get("policy_sections") or []

    if not sections:
        return reply

    references = ", ".join(str(section) for section in sections)
    return f"{reply}\n\nPolicy references: {references}"


def compose_response(result: PlanResult) -> str:
    """Combine task responses using verified tool results where supported."""
    sections = []

    for task_result in result.tasks:
        if task_result.answer.get("allowed") is False:
            content = "I can't provide that information."

        elif task_result.answer.get("error"):
            content = task_result.reply

        else:
            successful = [call for call in task_result.calls if call.ok]

            if not successful:
                content = "I couldn't retrieve verified information."

            elif (
                task_result.task.capability == "academic_record"
                and any(call.name == "get_my_gpa" for call in successful)
            ):
                content = _format_gpa(task_result.answer)
                if not content:
                    content = "I couldn't retrieve verified GPA information."

            elif (
                task_result.task.capability == "advising"
                and any(call.name == "plan_my_degree" for call in successful)
            ):
                content = _format_advising(task_result.answer)
                if not content:
                    content = "I couldn't retrieve verified advising information."
                
            elif (
                task_result.task.capability == "policy"
                and any(call.name == "search_policy" for call in successful)
            ):
                content = _format_policy(task_result.answer, task_result.reply)

            else:
                content = task_result.reply

        sections.append(f"{task_result.task.question}\n{content}")

    return "\n\n".join(sections)

