
"""Manual integration test for the optional registrar orchestrator."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from registrar.agents.loop import make_client
from registrar.agents.router import Router
from registrar.agents.orchestrator.orchestrator import Orchestrator


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://registrar@localhost:5433/registrar",
)

MODEL = os.environ.get("LLM_MODEL", "llama3.1:8b")


def main():
    engine = create_engine(DATABASE_URL)
    client = make_client()

    with Session(engine) as session:
        router = Router(
            client=client,
            session=session,
            user_uid="800003546",
            role="student",
            model=MODEL,
            verbose=False,
        )

        orchestrator = Orchestrator(
            router=router,
            client=client,
            model=MODEL,
        )

        question = (
            "What is my GPA, what are the academic probation rules, "
            "and what courses should I take next semester?"
        )

        result = orchestrator.ask(
            question,
            allow_orchestration=True,
        )

        print("\nACTION:", result.action)
        print("\nREPLY:\n", result.reply)

        if result.action == "orchestrate":
            print("\nTASK DETAILS:")
            for task in result.result.tasks:
                print(f"\nCapability: {task.task.capability}")
                print(f"Question: {task.task.question}")
                print(f"Tools: {[call.name for call in task.calls]}")
                print(f"Answer: {task.answer}")


if __name__ == "__main__":
    main()
