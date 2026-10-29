"""DataTools and PolicyTools backed by a JSON fixture, so the agent runs before the database is seeded.
The fixture holds rows in the exact shape of the real tables (see contracts.py)."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path


class FixtureData:
    def __init__(self, path: str | Path):
        self.d = json.loads(Path(path).read_text())

    def get_student(self, uid):
        return next(s for s in self.d["student"] if s["university_id"] == uid)

    def get_program(self, code):
        return next(p for p in self.d["program"] if p["code"] == code)

    def get_enrollments(self, uid):
        return [e for e in self.d["enrollment"] if e["student_university_id"] == uid]

    def get_grade_scale(self):
        return self.d["grade_scale"]

    def get_terms_after(self, as_of, n, include_summer):
        clock = datetime.fromisoformat(as_of).date()
        terms = sorted(self.d["academic_term"], key=lambda t: t["sequence"])
        if not include_summer:
            terms = [t for t in terms if t["term_type"] != "summer"]
        current = next((t for t in terms if date.fromisoformat(t["start_date"]) <= clock <= date.fromisoformat(t["end_date"])), None)
        future = [t for t in terms if date.fromisoformat(t["start_date"]) > clock]
        if current is None and future:  # README rule: in a break, the next term counts as current
            current = future[0]
        return current, future[:n]

    def get_courses(self, codes=None):
        return [c for c in self.d["course"] if codes is None or c["code"] in codes]

    def get_prerequisites(self):
        return self.d["course_prerequisite"]

    def get_degree_plan(self, program_code):
        return ([r for r in self.d["degree_requirement"] if r["program_code"] == program_code],
                [r for r in self.d["program_category_requirement"] if r["program_code"] == program_code])

    def get_lectures(self, term_codes):
        return [l for l in self.d["lecture"] if l["term_code"] in term_codes]

    def get_offering_history(self, course_codes):
        return [h for h in self.d["offering_history"] if h["course_code"] in course_codes]

    def is_advisor_of(self, instructor_id, student_id):
        return [instructor_id, student_id] in self.d.get("advisor_assignment", [])


class FixturePolicy:
    def __init__(self, path: str | Path):
        self.d = json.loads(Path(path).read_text())["policy"]

    def get_params(self):
        return self.d["params"]

    def cite(self, keys):
        return [c for c in self.d["citations"] if c["key"] in keys]
