"""Runs the agent on the team's frozen seed dataset (data/seed). No enrollment exists, so every student is
planned as a new student. MS cases are fast; BS cases take 10 to 20 s and need RUN_SLOW=1."""
import os
from pathlib import Path

import pytest

from advising_agent.agent import AdvisingAgent
from advising_agent.fixture_tools import FixturePolicy
from advising_agent.seed_tools import SEED, SeedData

POLICY = Path(__file__).resolve().parents[1] / "fixtures" / "example_db.json"
pytestmark = pytest.mark.skipif(not (SEED / "student.csv").exists(), reason="seed data not present")
CASES = [("MSCS", "800204340", 4, False), ("MSENG", "800091963", 4, False),
         ("BSCS", "800109888", 8, True), ("BSENG", "800013375", 8, True)]


@pytest.mark.parametrize("prog,uid,horizon,slow", CASES, ids=[c[0] for c in CASES])
def test_seed_program(prog, uid, horizon, slow):
    if slow and not os.environ.get("RUN_SLOW"):
        pytest.skip("set RUN_SLOW=1")
    out = AdvisingAgent(SeedData(), FixturePolicy(POLICY)).handle({
        "request_id": prog, "as_of": "2026-11-20T18:00:00+00:00",
        "requester": {"university_id": uid, "role": "student"}, "student_university_id": uid,
        "horizon_terms": horizon, "preferences": {"max_credits_per_term": 18 if slow else 12}})
    assert out["status"] == "ok", out.get("blockers")
    assert out["plans"][0]["violations"] == []
    if not slow:
        assert out["solver"]["optimal"] and out["earliest_graduation_term_code"] == "202810"
