
"""LLM-based task planner for the registrar orchestrator.

Generates structured execution plans without executing any tools.
"""

import json
import re

from registrar.agents.orchestrator.models import (
    ExecutionPlan,
    PlanValidationError,
    ROLE_CAPABILITIES,
    validate_plan,
)


class PlanningError(RuntimeError):
    """Raised when the LLM cannot produce a valid execution plan."""


class Planner:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def plan(self, question: str, role: str) -> ExecutionPlan:
        """Generate and validate a plan for an authenticated role."""

        if role not in ROLE_CAPABILITIES:
            raise PlanningError(f"Unknown role: {role!r}")

        if not isinstance(question, str) or not question.strip():
            raise PlanningError("Question cannot be empty.")

        capabilities = ", ".join(sorted(ROLE_CAPABILITIES[role]))

        

        system_prompt = (
            "You are a request planner for a university registrar system.\n"
            "You decide whether the authenticated user's request needs "
            "multi-task coordination.\n\n"
            f"Authenticated role: {role}\n"
            f"Allowed capability labels: {capabilities}\n\n"

            "OUTPUT FORMAT:\n"
            "Return exactly one JSON object using one of these schemas:\n"
            '{"action":"delegate"}\n'
            "OR\n"
            '{"action":"orchestrate","tasks":['
            '{"capability":"academic_record","question":"What is my GPA?"},'
            '{"capability":"advising","question":"What courses should I take next semester?"}'
            ']}\n\n'

            "DECISION RULES:\n"
            "1. Delegate any request that can be answered as one task.\n"
            "2. Delegate registration, dropping courses, grade changes, "
            "confirmations, cancellations, and all database modifications.\n"
            "3. Delegate requests involving another person's private records. "
            "The existing agent will enforce authorization.\n"
            "4. Orchestrate ONLY when the request contains two or three "
            "distinct read-only information needs.\n"
            "5. Never invent student IDs, dates, courses, terms, or constraints.\n"
            "6. Never add tasks the user did not request.\n"
            "7. If uncertain, delegate.\n\n"

            "TASK FORMAT RULES:\n"
            "Each task MUST contain exactly two fields:\n"
            '- \"capability\": one of the allowed capability labels.\n'
            '- \"question\": a natural-language question preserving the '
            "user's request.\n"
            "Do not use fields such as data, type, task, operation, or "
            "action inside tasks.\n"
            "Do not generate tool calls or database commands.\n\n"

            "CAPABILITY DEFINITIONS:\n"
            "- academic_record: the student's own GPA, transcript, "
            "or registrations.\n"
            "- policy: university handbook rules and requirements.\n"
            "- advising: degree planning and course recommendations.\n\n"

            "EXAMPLES:\n"
            'User: What is my GPA?\n'
            'Output: {"action":"delegate"}\n\n'

            'User: What are the probation rules?\n'
            'Output: {"action":"delegate"}\n\n'

            'User: Register me for CS 1110.\n'
            'Output: {"action":"delegate"}\n\n'

            "User: Show me another student's transcript.\n"
            'Output: {"action":"delegate"}\n\n'

            "User: What is my GPA and what courses should I take next semester?\n"
            'Output: {"action":"orchestrate","tasks":['
            '{"capability":"academic_record","question":"What is my GPA?"},'
            '{"capability":"advising","question":"What courses should I take next semester?"}'
            ']}\n\n'

            "User: What is my GPA, what are the probation rules, "
            "and what courses should I take next semester?\n"
            'Output: {"action":"orchestrate","tasks":['
            '{"capability":"academic_record","question":"What is my GPA?"},'
            '{"capability":"policy","question":"What are the probation rules?"},'
            '{"capability":"advising","question":"What courses should I take next semester?"}'
            ']}\n\n'

            "Return ONLY the JSON object. No Markdown or explanations."
        )



        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question.strip()},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or ""

        content = re.sub(
            r"<think>.*?</think>", "", content, flags=re.DOTALL
        ).strip()

        if content.startswith("```"):
            content = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", content
            ).strip()

        try:
            data = json.loads(content)
        except (ValueError, TypeError) as exc:
            raise PlanningError(
                "The LLM did not return valid JSON."
            ) from exc

        try:
            return validate_plan(data, role)
        except PlanValidationError as exc:
            raise PlanningError(
                f"The LLM returned an invalid plan: {exc}"
            ) from exc
