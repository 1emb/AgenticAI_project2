"""Grade the Student agent against data/testset/student/cases.jsonl with a real model.

    python scripts/eval_student_agent.py                         # all 152 cases, question wording only
    python scripts/eval_student_agent.py --limit 20              # quick smoke run
    python scripts/eval_student_agent.py --intent access_denied --intent access_partial
    python scripts/eval_student_agent.py --paraphrases           # also run both paraphrases (456 runs)
    python scripts/eval_student_agent.py --id stu-capacity-002 --verbose

Each run uses a fresh agent set to the case's student and clock. The JSON answer is graded with the contract in
data/testset/README.md (registrar/eval/grader.py). Every run is written to runs/student-<model>-<time>.jsonl.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.agents.student import StudentAgent  # noqa: E402
from registrar.eval.runner import Persona, parser, run, term_not_named  # noqa: E402

STUDENT = Persona("student", StudentAgent, "student", term_not_named)

if __name__ == "__main__":
    run(STUDENT, parser("student", __doc__).parse_args())
