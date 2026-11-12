"""The coordinator's planner: split a user message into tasks and assign each to the specialist agent that owns it.

The planner only proposes. validate_plan() enforces the structure and the authenticated user's available agents, so a
plan can never name an agent the role does not have, and the planner cannot call a tool or touch the database.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from registrar.agents.multi.agents import DESCRIPTION, REGISTRATION

MAX_TASKS = 3


class PlanError(RuntimeError):
    """The model did not produce a valid plan; the coordinator falls back to the single persona agent."""


@dataclass(frozen=True)
class Task:
    agent: str
    question: str


def validate_plan(data, available: list[str]) -> tuple[Task, ...]:
    if not isinstance(data, dict) or set(data) != {"tasks"}:
        raise PlanError("Plan must be an object with exactly one field, 'tasks'.")
    raw = data["tasks"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TASKS:
        raise PlanError(f"Plan must contain between 1 and {MAX_TASKS} tasks.")
    tasks: list[Task] = []
    for i, t in enumerate(raw, 1):
        if not isinstance(t, dict) or set(t) != {"agent", "question"}:
            raise PlanError(f"Task {i} must contain exactly agent and question.")
        agent, q = t["agent"], t["question"]
        if not isinstance(agent, str) or agent not in available:
            raise PlanError(f"Task {i} names an agent this user does not have: {agent!r}")
        if not isinstance(q, str) or not q.strip() or len(q) > 1000:
            raise PlanError(f"Task {i} needs a nonempty question of at most 1000 characters.")
        task = Task(agent, q.strip())
        if task in tasks:
            raise PlanError(f"Task {i} duplicates an earlier task.")
        tasks.append(task)
    regs = [i for i, t in enumerate(tasks) if t.agent == REGISTRATION]
    if regs and (len(regs) > 1 or regs[0] != len(tasks) - 1):
        # a change is only prepared here and confirmed by the user next turn, so it goes last and at most once
        raise PlanError("A registration task must appear at most once, as the last task.")
    return tuple(tasks)


class Planner:
    def __init__(self, client, model: str):
        self.client, self.model = client, model

    def plan(self, question: str, role: str, available: list[str], pending: str | None = None) -> tuple[Task, ...]:
        if not isinstance(question, str) or not question.strip():
            raise PlanError("Question cannot be empty.")
        agents = "\n".join(f'- "{a}": {DESCRIPTION[a]}' for a in available)
        note = (f"\nA change is waiting for the user's confirmation ({pending}). A reply that confirms, cancels or "
                "modifies it goes to the registration agent; unrelated questions go to their own agents.\n") if pending else ""
        system = (
            "You are the coordinator of a university registrar's multi-agent system. Split the user's message into the "
            "distinct needs it contains and assign each need to the one agent that owns it.\n\n"
            f"Logged-in role: {role}\nAvailable agents:\n{agents}\n{note}\n"
            'OUTPUT: exactly one JSON object: {"tasks":[{"agent":"<name>","question":"<one need, in the user\'s words>"}]}\n\n'
            "RULES:\n"
            f"1. One to {MAX_TASKS} tasks. A single need is a single task.\n"
            "2. Never invent IDs, dates, courses, terms or needs the user did not state. Keep each question faithful to the user's wording.\n"
            "3. Requests about another person's private records still go to the data agent: it enforces access and refuses.\n"
            "3b. Questions about what the rules ALLOW or REQUIRE (credit limits, probation, standing, repeats, withdrawals, "
            "graduation requirements, privacy) and questions that find courses by topic go to the policy agent, even when "
            "they say 'I' or 'my'. Only questions about the user's own recorded facts (GPA, grades, schedule, registrations, "
            "a course's sections) go to the data agent.\n"
            "4. Adding, dropping, grade posting, and confirming or cancelling a change go to the registration agent, "
            "at most once and always last.\n"
            "4b. A request to register for, add or drop a named course is ONE registration task. Do not add a policy or "
            "data task to look the course up first: the registration agent finds the course itself.\n"
            "5. Replies to a pending change never reach you: the system handles them itself.\n"
            "6. If unsure which agent owns a need, use the data agent.\n\n"
            "EXAMPLES (student):\n"
            'User: What is my GPA?\n{"tasks":[{"agent":"data","question":"What is my GPA?"}]}\n'
            'User: What are the probation rules?\n{"tasks":[{"agent":"policy","question":"What are the probation rules?"}]}\n'
            'User: What is my GPA and what courses should I take next semester?\n'
            '{"tasks":[{"agent":"data","question":"What is my GPA?"},{"agent":"advising","question":"What courses should I take next semester?"}]}\n'
            'User: How many credits can I take if I am on probation?\n{"tasks":[{"agent":"policy","question":"How many credits can I take if I am on probation?"}]}\n'
            'User: Which courses cover databases?\n{"tasks":[{"agent":"policy","question":"Which courses cover databases?"}]}\n'
            'User: What courses am I registered for?\n{"tasks":[{"agent":"data","question":"What courses am I registered for?"}]}\n'
            'User: Register me for CS 5810 for next semester\n'
            '{"tasks":[{"agent":"registration","question":"Register me for CS 5810 for next semester."}]}\n'
            'User: Is there a course on databases, and register me for CS 3410.\n'
            '{"tasks":[{"agent":"policy","question":"Is there a course on databases?"},{"agent":"registration","question":"Register me for CS 3410."}]}\n\n'
            "Return ONLY the JSON object."
        )
        resp = self.client.chat.completions.create(
            model=self.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": question.strip()}],
            temperature=0.0, response_format={"type": "json_object"})
        content = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.DOTALL).strip()
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
        try:
            data = json.loads(content)
        except (ValueError, TypeError) as e:
            raise PlanError("The model did not return valid JSON.") from e
        return validate_plan(data, available)