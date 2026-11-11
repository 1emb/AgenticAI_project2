"""DataTools over the team's frozen seed dataset (data/seed/*.csv), so the agent runs on the real catalog,
degree plans, terms and lectures without Postgres. There is no enrollment table in the schema yet, so
get_enrollments() returns [] (every student looks like a new student) and seats_taken is None."""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


def _rows(name: str) -> list[dict]:
    return list(csv.DictReader((SEED / f"{name}.csv").open()))


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("true", "t", "1", "yes")


class SeedData:
    def __init__(self, seed_dir: str | Path | None = None):
        global SEED
        if seed_dir:
            SEED = Path(seed_dir)
        self.students = {r["university_id"]: r for r in _rows("student")}
        self.programs = {r["code"]: r for r in _rows("program")}
        self.terms = sorted(_rows("academic_term"), key=lambda t: int(t["sequence"]))
        for t in self.terms:
            t["sequence"] = int(t["sequence"])
        self.courses = [dict(r, credit_hours=float(r["credit_hours"]), is_active=_bool(r["is_active"]))
                        for r in _rows("course")]
        self.prereqs = [dict(r, group_number=int(r["group_number"])) for r in _rows("course_prerequisite")]
        self.plan = [dict(r, is_required=_bool(r["is_required"]),
                          suggested_term_number=int(r["suggested_term_number"]) if r["suggested_term_number"] else None)
                     for r in _rows("degree_requirement")]
        self.cat = [dict(r, min_credits=int(r["min_credits"])) for r in _rows("program_category_requirement")]
        self.lectures = [dict(r, capacity=int(r["capacity"]), is_cancelled=_bool(r["is_cancelled"]),
                              start_time=r["start_time"][:5], end_time=r["end_time"][:5], seats_taken=None)
                         for r in _rows("lecture")]

    def get_student(self, uid):
        s = self.students[uid]
        return {k: s[k] or None for k in ("university_id", "program_code", "status", "admit_term_code",
                                          "expected_graduation_term_code")}

    def get_program(self, code):
        p = self.programs[code]
        return {"code": p["code"], "degree": p["degree"], "total_credits_required": int(p["total_credits_required"]),
                "min_gpa": float(p["min_gpa"])}

    def get_enrollments(self, uid):
        return []  # not modeled in the schema yet

    def get_grade_scale(self):
        # mirrors the rows inserted by the initial migration
        pts = [("A", 4.0), ("A-", 3.7), ("B+", 3.3), ("B", 3.0), ("B-", 2.7), ("C+", 2.3), ("C", 2.0), ("C-", 1.7),
               ("D+", 1.3), ("D", 1.0), ("D-", 0.7), ("F", 0.0), ("W", None), ("I", None)]
        return [{"letter": l, "points": p} for l, p in pts]

    def get_terms_after(self, as_of, n, include_summer):
        clock = datetime.fromisoformat(as_of).date()
        terms = [t for t in self.terms if include_summer or t["term_type"] != "summer"]
        current = next((t for t in terms if date.fromisoformat(t["start_date"]) <= clock <= date.fromisoformat(t["end_date"])), None)
        future = [t for t in terms if date.fromisoformat(t["start_date"]) > clock]
        if current is None and future:
            current = future[0]
        return current, future[:n]

    def get_courses(self, codes=None):
        return [c for c in self.courses if codes is None or c["code"] in codes]

    def get_prerequisites(self):
        return self.prereqs

    def get_degree_plan(self, program_code):
        return ([r for r in self.plan if r["program_code"] == program_code],
                [r for r in self.cat if r["program_code"] == program_code])

    def get_lectures(self, term_codes):
        return [l for l in self.lectures if l["term_code"] in term_codes]

    def get_offering_history(self, course_codes):
        ttype = {t["code"]: t["term_type"] for t in self.terms}
        seen: dict[str, set] = defaultdict(set)
        for l in self.lectures:
            if not l["is_cancelled"]:
                seen[l["course_code"]].add(ttype[l["term_code"]])
        return [{"course_code": c, "term_types": sorted(seen[c])} for c in course_codes if c in seen]

    def is_advisor_of(self, instructor_id, student_id):
        return False  # no advisor assignment in the schema yet
