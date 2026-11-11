"""Grade the Professor agent against data/testset/professor/cases.jsonl with a real model.

    python scripts/eval_professor_agent.py                       # all 202 cases, question wording only
    python scripts/eval_professor_agent.py --limit 20            # quick smoke run
    python scripts/eval_professor_agent.py --intent access_denied --intent access_partial
    python scripts/eval_professor_agent.py --paraphrases         # also run both paraphrases (606 runs)
    python scripts/eval_professor_agent.py --id prof-roster-001 --verbose

Each run uses a fresh agent set to the case's instructor and clock. The JSON answer is graded with the contract in
data/testset/README.md (registrar/eval/grader.py). Every run is written to runs/professor-<model>-<time>.jsonl.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.agents.professor import ProfessorAgent  # noqa: E402
from registrar.eval.known_issues import professor_unanswerable  # noqa: E402
from registrar.eval.runner import Persona, parser, run  # noqa: E402

PROFESSOR = Persona("professor", ProfessorAgent, "professor", professor_unanswerable)

if __name__ == "__main__":
    run(PROFESSOR, parser("professor", __doc__).parse_args())
