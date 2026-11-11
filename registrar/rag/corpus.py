"""The knowledge corpus: every piece of unstructured text the agents may retrieve from, as uniform Chunks.

Sources
  handbook   one chunk per section of data/policy/handbook.md           (rules; cite "Handbook 3.2")
  catalog    one chunk per active course: title, description, credits,  (what a course is about; cite the code)
             level and prerequisites
  kb         one chunk per "## heading" of any data/kb/*.md file        (drop-in FAQs, office notes, ...)

What is deliberately NOT here: anything numeric or personal. Grades, enrollments, seats, deadlines and degree plans stay
in SQL behind the existing tools, and the numbers that change outcomes stay in data/policy/params.json. Retrieval only
supplies wording and citations. Each chunk carries an `audience` so a future restricted document (say, an
administrators-only procedure) cannot be returned to a student: the retriever filters on it before ranking.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEVEL_WORDS = {"lower_division": "lower division", "upper_division": "upper division", "graduate": "graduate"}


@dataclass(frozen=True)
class Chunk:
    id: str                      # "handbook:3.2", "catalog:CS 3410", "kb:faq:2"
    source: str                  # handbook | catalog | kb
    title: str
    text: str                    # what is embedded and shown to the model
    audience: str = "all"        # all | student | instructor | admin
    meta: dict = field(default_factory=dict, compare=False, hash=False)

    def as_hit(self) -> dict:
        return {"id": self.id, "source": self.source, "title": self.title, "text": self.text, **self.meta}


# ------------------------------------------------------------------------------------------------ handbook
def handbook_chunks(path: Path | None = None) -> list[Chunk]:
    from registrar.agents.policy import HANDBOOK, load_sections
    return [Chunk(f"handbook:{s.id}", "handbook", f"Handbook {s.id} {s.title}", f"{s.title}. {s.text}",
                  meta={"section": s.id}) for s in load_sections(path or HANDBOOK)]


# ------------------------------------------------------------------------------------------------ catalog
def prerequisite_text(rows: list[dict]) -> str:
    """Rows sharing a group_number are OR alternatives; different groups are all required (schema convention)."""
    groups: dict[int, list[str]] = {}
    for r in sorted(rows, key=lambda r: (int(r["group_number"]), r["required_course_code"])):
        groups.setdefault(int(r["group_number"]), []).append(f"{r['required_course_code']} (grade {r['min_grade']} or better)")
    if not groups:
        return "No prerequisites."
    parts = [" or ".join(g) if len(g) == 1 else "(" + " or ".join(g) + ")" for g in groups.values()]
    return "Prerequisites: " + " and ".join(parts) + "."


def catalog_chunks(courses: list[dict], prereqs: list[dict]) -> list[Chunk]:
    """courses: dicts with code, title, description, credit_hours, level, is_active. Retired courses are left out: a
    student asking what to take should not be pointed at a course that is no longer offered."""
    by_course: dict[str, list[dict]] = {}
    for p in prereqs:
        by_course.setdefault(p["course_code"], []).append(p)
    out = []
    for c in courses:
        if str(c["is_active"]).lower() not in ("true", "1", "t"):
            continue
        level = LEVEL_WORDS.get(str(c["level"]), str(c["level"]))
        text = (f"{c['code']} {c['title']}. {c['description']} {c['credit_hours']} credit hours, {level} course. "
                f"{prerequisite_text(by_course.get(c['code'], []))}")
        out.append(Chunk(f"catalog:{c['code']}", "catalog", f"{c['code']} {c['title']}", text,
                         meta={"course": c["code"], "level": str(c["level"])}))
    return out


def catalog_chunks_from_csv(seed_dir: Path | None = None) -> list[Chunk]:
    d = seed_dir or ROOT / "data/seed"
    rd = lambda n: list(csv.DictReader(open(d / n, newline="")))
    return catalog_chunks(rd("course.csv"), rd("course_prerequisite.csv"))


def catalog_chunks_from_session(session) -> list[Chunk]:
    """Same chunks from the live database, so the index follows the courses table rather than a CSV snapshot."""
    from sqlalchemy import select
    from registrar.agents.common import plain
    from registrar.models import Course, CoursePrerequisite
    courses = [{"code": c.code, "title": c.title, "description": c.description, "credit_hours": plain(c.credit_hours),
                "level": plain(c.level), "is_active": c.is_active} for c in session.scalars(select(Course))]
    prereqs = [{"course_code": p.course_code, "required_course_code": p.required_course_code,
                "min_grade": p.min_grade, "group_number": p.group_number}
               for p in session.scalars(select(CoursePrerequisite))]
    return catalog_chunks(courses, prereqs)


# ------------------------------------------------------------------------------------------------ kb
def kb_chunks(kb_dir: Path | None = None) -> list[Chunk]:
    """data/kb/<name>.md, split at '## ' headings. An optional first line '<!-- audience: instructor -->' restricts the file."""
    d = kb_dir or ROOT / "data/kb"
    out = []
    for f in sorted(d.glob("*.md")) if d.exists() else []:
        raw = f.read_text()
        m = re.match(r"\s*<!--\s*audience:\s*(\w+)\s*-->", raw)
        audience = m.group(1) if m else "all"
        n = 0
        for block in re.split(r"(?m)^##\s+", raw)[1:]:
            title, _, body = block.partition("\n")
            body = " ".join(body.split())
            if body:
                n += 1
                out.append(Chunk(f"kb:{f.stem}:{n}", "kb", f"{f.stem}: {title.strip()}", f"{title.strip()}. {body}",
                                 audience=audience))
    return out


def build_corpus(session=None, kb_dir: Path | None = None) -> list[Chunk]:
    catalog = catalog_chunks_from_session(session) if session is not None else catalog_chunks_from_csv()
    return handbook_chunks() + catalog + kb_chunks(kb_dir)
