"""Run the fixture requests: python -m advising_agent.run_example [request_id]"""
import json
import sys
from pathlib import Path

from .agent import AdvisingAgent
from .fixture_tools import FixtureData, FixturePolicy

HERE = Path(__file__).parent


def main() -> None:
    db = HERE / "fixtures" / "example_db.json"
    agent = AdvisingAgent(FixtureData(db), FixturePolicy(db))
    reqs = json.loads((HERE / "fixtures" / "example_requests.json").read_text())
    pick = sys.argv[1] if len(sys.argv) > 1 else "adv-001"
    for r in reqs:
        if r["request_id"] == pick:
            r = {k: v for k, v in r.items() if not k.startswith("_")}
            out = agent.handle(r)
            print(out.get("explanation", ""))
            print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
