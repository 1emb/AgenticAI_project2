"""Policy agent: retrieval quality on data/testset/policy/cases.jsonl, and agreement between the handbook text and
the machine-readable parameters the code uses (a number changed in one place must be changed in the other)."""
import json
import re

from registrar.agents.policy import PolicyStore

from conftest import ROOT

CASES = [json.loads(l) for l in open(ROOT / "data/testset/policy/cases.jsonl")]


def test_retrieval_recall():
    p = PolicyStore()
    at1 = sum(p.search(c["question"])[:1][0]["section"] == c["expected_section"] for c in CASES)
    at3 = sum(c["expected_section"] in [h["section"] for h in p.search(c["question"])] for c in CASES)
    assert at3 == len(CASES), "every question's section must be in the top 3"
    assert at1 >= 0.8 * len(CASES)


def test_params_match_handbook_text():
    p = PolicyStore()
    text = lambda sid: p.section(sid).text
    cap = p.params["max_credits_by_standing"]
    assert f"at most {cap['good']} credit hours" in text("3.2")
    assert f"at most {cap['probation']} credit hours" in text("3.2")
    ft = p.params["full_time_credits"]
    assert f"{ft['BS']} or more credit hours" in text("3.1") and f"{ft['MS']} or more credit hours" in text("3.1")
    assert "two or more consecutive terms" in text("4.1") and p.params["at_risk_consecutive_probation_terms"] == 2
    assert "three consecutive probation terms" in text("4.1") and p.params["suspension_consecutive_probation_terms"] == 3
    assert "required courses included" in text("8.1") and p.params["category_minimum_includes_required"] is True
    assert "count as met" in text("5.2") and p.params["grad_admit_meets_undergrad_prereqs"] is True
    assert p.params["repeat_rule"] == "below_prereq_min" and "below the minimum grade" in text("2.1")
    for key, sid in p.params["sections"].items():
        assert p.section(sid) is not None, key


def test_grade_points_in_handbook_match_database(session):
    from sqlalchemy import select
    from registrar.models import GradeScale
    p = PolicyStore()
    stated = dict(re.findall(r"\b([A-D][+-]?|F) (\d\.\d)\b", p.section("1.1").text))
    db = {g.letter: float(g.points) for g in session.scalars(select(GradeScale)) if g.points is not None}
    assert {k: float(v) for k, v in stated.items()} == db
