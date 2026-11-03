"""Oracle test for the Administrator agent: the tools (Python over ORM rows) must reproduce the ground truth that
registrar/testset/administrator.py computes separately in raw SQL. Needs the enrollment data
(python scripts/seed_enrollment.py --load); skipped without it."""
import json

import pytest
from sqlalchemy import text

from registrar.agents.admin.tools import AdminTools
from registrar.agents.calendar import Calendar
from registrar.agents.loop import ToolCall
from registrar.agents.student.agent import assemble_answer
from registrar.eval.grader import grade

from conftest import ROOT

PATH = ROOT / "data/testset/administrator/cases.jsonl"
ADMIN_CASES = [json.loads(l) for l in open(PATH)] if PATH.exists() else []


def oracle(case: dict) -> tuple[str, dict]:
    s, intent = case["slots"], case["intent"]
    term = {"term": s["term_code"]} if s.get("term_code") else {}
    scope = {"scope_kind": s.get("scope_kind", "all"), "scope_value": s.get("scope_value"), **term}
    return {
        "grade_distribution_group": ("grade_distribution", scope), "dfw_rate_group": ("dfw_rate", scope),
        "withdrawals_group": ("withdrawals", scope), "enrollment_group": ("enrollment_summary", scope),
        "grading_extremes": ("grading_extremes", {**scope, "metric": s.get("metric"), "direction": s.get("direction"),
                                                  "unit": s.get("unit")}),
        "at_risk_students": ("at_risk_students", {"criterion": s.get("criterion"), "program": s.get("program"),
                                                  "threshold": s.get("threshold")}),
        "graduation_candidates": ("graduation_candidates", {"program": s.get("program")}),
        "headcount": ("headcount", {"filter": s.get("filter"), "program": s.get("program")}),
        "gpa_profile": ("gpa_profile", {"program": s.get("program"), "threshold": s.get("threshold"),
                                        "comparison": s.get("comparison")}),
        "cohort_outcomes": ("cohort_outcomes", {"admit_term": s.get("admit_term_code")}),
        "student_record": ("get_student_record", {"student": s.get("student")}),
    }[intent]


@pytest.fixture(scope="module")
def admin(session):
    if not session.execute(text("SELECT to_regclass('enrollment')")).scalar() or \
            not session.execute(text("SELECT count(*) FROM enrollment")).scalar():
        pytest.skip("no enrollment data; run scripts/seed_enrollment.py --load")
    return lambda as_of: AdminTools(session, Calendar(session, as_of))


@pytest.mark.parametrize("case", ADMIN_CASES, ids=[c["id"] for c in ADMIN_CASES])
def test_admin_tools_match_sql_truth(admin, case):
    name, args = oracle(case)
    tools = admin(case["as_of"])
    answer = assemble_answer([ToolCall(name, args, getattr(tools, name)(**args), True)])
    result = grade(case["answer"], answer, intent=case["intent"])
    assert result.passed, result.problems


def test_program_inputs_are_normalized_or_rejected(admin):
    from registrar.agents.common import ToolError
    t = admin("2026-11-20T18:00:00+00:00")
    assert t.headcount("active", "all")["answer"]["scope"] == {"kind": "all", "value": None}
    assert t.headcount("active", "")["answer"] == t.headcount("active")["answer"]
    assert t.gpa_profile("Computer Science")["answer"]["scope"]["value"] == "BSCS"
    assert t.gpa_profile("Master of Science in Computer Science")["answer"]["scope"]["value"] == "MSCS"
    with pytest.raises(ToolError):
        t.headcount("active", "Basket Weaving")
    with pytest.raises(ToolError):
        t.cohort_outcomes("Fall 2024", "alien")
    assert t.cohort_outcomes("Fall 2024", "all")["answer"]["cohort"]["entry_type"] == "all"


def test_confused_scope_kinds_are_normalized(admin):
    t = admin("2026-11-20T18:00:00+00:00")
    assert t.withdrawals("course", "MATH", "Fall 2025")["answer"]["scope"]["kind"] == "subject"
    assert t.withdrawals("course", "all", "Fall 2025")["answer"]["scope"]["kind"] == "all"
    assert t.dfw_rate("subject", "MATH 1511")["answer"]["scope"] == {"kind": "course", "value": "MATH 1511", "term": None}
    assert t.withdrawals("course", "MATH", "Fall 2025")["answer"] == t.withdrawals("subject", "MATH", "Fall 2025")["answer"]


def test_scope_inputs_recovered_from_value_shape(admin):
    t = admin("2026-11-20T18:00:00+00:00")
    a = t.grade_distribution("all", "ENGL 1110", "all")["answer"]["scope"]
    assert a == {"kind": "course", "value": "ENGL 1110", "term": None}
    b = t.grading_extremes("mean_gpa", "lowest", "course", "course", "Fall 2025")["answer"]
    assert b["scope"] == {"kind": "all", "value": None, "term": "Fall 2025"}
    c = t.grading_extremes("pct_a", "highest", "section", "section", "all", "last spring")["answer"]
    assert c["scope"]["kind"] == "all" and c["unit"] == "section"
    d = t.enrollment_summary("course", "Spring 2027", "Spring 2027")["answer"]["scope"]
    assert d == {"kind": "all", "value": None, "term": "Spring 2027"}


def test_level_words_as_value_mean_level_scope(admin):
    t = admin("2026-11-20T18:00:00+00:00")
    a = t.grade_distribution("course", "lower-division", "last spring")["answer"]
    b = t.grade_distribution("level", "lower_division", "last spring")["answer"]
    assert a == b and a["scope"]["kind"] == "level"
    assert t.dfw_rate("course", "upper division courses", "Fall 2025")["answer"]["scope"]["value"] == "upper_division"
