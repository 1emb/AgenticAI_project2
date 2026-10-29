"""Opt-in stress test (about 20 s): RUN_SLOW=1 pytest advising_agent/tests -q
A synthetic BS program: 200-course catalog, prerequisite depth up to 4, 120 credits, 8-term horizon."""
import json
import os
import random
from pathlib import Path

import pytest

from advising_agent.agent import AdvisingAgent
from advising_agent.fixture_tools import FixtureData, FixturePolicy

BASE = Path(__file__).resolve().parents[1] / "fixtures" / "example_db.json"


def make_db(seed: int = 1) -> dict:
    rnd = random.Random(seed)
    base = json.loads(BASE.read_text())
    subj = ["CS", "MATH", "ENGL", "PHYS", "HIST", "ECON", "BIOL", "CHEM"]
    courses, pre, hist, codes = [], [], [], []
    for i in range(200):
        s, lvl = subj[i % len(subj)], [1, 2, 3, 4][i % 4]
        code = f"{s} {lvl}{100 + i:03d}"
        codes.append(code)
        courses.append({"code": code, "subject": s, "number": code.split()[1], "title": code, "credit_hours": 3,
                        "level": "lower_division" if lvl < 3 else "upper_division", "is_active": True})
        hist.append({"course_code": code, "term_types": rnd.choice([["fall", "spring"], ["fall"], ["spring"]])})
        lower = [codes[j] for j in range(i) if [1, 2, 3, 4][j % 4] == lvl - 1][-12:]
        if lower:
            for g in range(rnd.choice([0, 1, 1, 2])):
                for a in rnd.sample(lower, min(len(lower), rnd.choice([1, 1, 2]))):
                    pre.append({"course_code": code, "required_course_code": a, "min_grade": "C-", "group_number": g + 1})
    pmap: dict = {}
    for p in pre:
        pmap.setdefault(p["course_code"], {}).setdefault(p["group_number"], []).append(p["required_course_code"])
    need = set(rnd.sample(codes, 22))
    changed = True
    while changed:  # close the required set under prerequisites
        changed = False
        for c in list(need):
            for alts in pmap.get(c, {}).values():
                if not any(a in need for a in alts):
                    need.add(alts[0])
                    changed = True
    order, seen = [], set()

    def visit(c):
        if c in seen:
            return
        seen.add(c)
        for alts in pmap.get(c, {}).values():
            visit(next((a for a in alts if a in need), alts[0]))
        order.append(c)

    for c in sorted(need):
        visit(c)
    rest = [c for c in codes if c not in need]
    dr = [{"program_code": "BSCS", "course_code": c, "category": "core", "is_required": True, "suggested_term_number": None} for c in sorted(need)]
    dr += [{"program_code": "BSCS", "course_code": c, "category": "elective", "is_required": False, "suggested_term_number": None} for c in rest[:60]]
    dr += [{"program_code": "BSCS", "course_code": c, "category": "general_education", "is_required": False, "suggested_term_number": None} for c in rest[60:80]]
    enr = [{"student_university_id": "800123456", "term_code": "202580", "crn": f"9{k:04d}", "course_code": c,
            "status": "enrolled", "grade": "B"} for k, c in enumerate(order[:16])]
    return dict(base, course=courses, course_prerequisite=pre, degree_requirement=dr, enrollment=enr, lecture=[],
                offering_history=hist, program=[dict(base["program"][0], total_credits_required=120)],
                program_category_requirement=[{"program_code": "BSCS", "category": "elective", "min_credits": 18},
                                              {"program_code": "BSCS", "category": "general_education", "min_credits": 12}])


@pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="set RUN_SLOW=1")
def test_large_program(tmp_path):
    db = tmp_path / "large.json"
    db.write_text(json.dumps(make_db()))
    agent = AdvisingAgent(FixtureData(db), FixturePolicy(db))
    out = agent.handle({"request_id": "large", "as_of": "2026-11-20T18:00:00+00:00",
                        "requester": {"university_id": "800123456", "role": "student"},
                        "student_university_id": "800123456", "horizon_terms": 8,
                        "preferences": {"max_credits_per_term": 18}})
    assert out["status"] == "ok"
    assert out["plans"] and out["plans"][0]["violations"] == []
    assert out["solver"]["graduation_proven"]
    assert out["solver"]["seconds"] < 30
