"""pytest advising_agent/tests -q : every fixture request must match its _expect and pass the validator."""
import json
from pathlib import Path

import pytest

from advising_agent.agent import AdvisingAgent
from advising_agent.fixture_tools import FixtureData, FixturePolicy

HERE = Path(__file__).resolve().parents[1]
DB = HERE / "fixtures" / "example_db.json"
REQS = json.loads((HERE / "fixtures" / "example_requests.json").read_text())


@pytest.mark.parametrize("req", REQS, ids=[r["request_id"] for r in REQS])
def test_request(req):
    agent = AdvisingAgent(FixtureData(DB), FixturePolicy(DB))
    expect = req["_expect"]
    out = agent.handle({k: v for k, v in req.items() if not k.startswith("_")})
    for k, v in expect.items():
        got = out.get(k)
        assert (sorted(got) if isinstance(v, list) else got) == (sorted(v) if isinstance(v, list) else v), (k, got)
    for p in out.get("plans", []):
        assert p["violations"] == [], p["violations"]
