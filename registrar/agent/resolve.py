"""Mentions to keys. Pure Python over database rows and the clock; no model involved, every failure is explicit.

Each resolver returns a Resolved(value, status, candidates): status is "ok", "none" (nothing in the question), "not_found" or
"ambiguous". The pipeline records all of them next to the mentions so a wrong answer can be traced to the stage that caused it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from ..testset import queries as Q
from ..testset.common import QueryLog

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7, "8th": 8}
SEASONS = {"fall": "fall", "autumn": "fall", "spring": "spring", "summer": "summer"}
TERM_WORDS = r"(?:semester|sem|term|session)"


@dataclass
class Resolved:
    value: object = None
    status: str = "none"               # ok | none | not_found | ambiguous
    candidates: list = field(default_factory=list)
    note: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# ---- course ------------------------------------------------------------------------------------------------------------
def course(q: QueryLog, mention: str | None) -> Resolved:
    m = _clean(mention)
    if not m:
        return Resolved()
    code = re.search(r"\b([A-Za-z]{2,4})\s*-?\s*(\d{4}[A-Za-z]?)\b", m)
    if code:
        key = f"{code.group(1).upper()} {code.group(2).upper()}"
        row = q.one("course by code", "SELECT code, title FROM course WHERE code = %(c)s", c=key)
        return Resolved(key, "ok") if row else Resolved(key, "not_found", note=f"no course {key}")
    rows = q.rows("course by title", "SELECT code, title FROM course WHERE lower(title) = lower(%(t)s) ORDER BY code", t=m)
    if not rows:
        rows = q.rows("course by partial title", "SELECT code, title FROM course WHERE title ILIKE %(t)s ORDER BY code", t=f"%{m}%")
    if len(rows) == 1:
        return Resolved(rows[0]["code"], "ok")
    if not rows:
        return Resolved(None, "not_found", note=f"no course titled '{m}'")
    return Resolved(None, "ambiguous", [r["code"] for r in rows], note=f"'{m}' matches {len(rows)} courses")


# ---- term --------------------------------------------------------------------------------------------------------------
def all_terms(q: QueryLog) -> list[dict]:
    return q.rows("all terms", f"SELECT {Q.TERM_COLS} FROM academic_term ORDER BY sequence")


def current_term(q: QueryLog, as_of: datetime) -> dict:
    return Q.current_term(q, as_of)


def term(q: QueryLog, mention: str | None, as_of: datetime, default_current: bool = True) -> Resolved:
    """'this fall', 'next semester', 'next sem', 'last term', 'in Fall 2026', 'the Spring 2027 schedule', '2026 fall' -> a term row.
    A bare season ('spring', 'for fall') is the current term when it is that season, else the next term of that season
    (added 2026-11-02 after the realistic test run). With no mention the current term is returned (status 'ok', note
    'default'), unless default_current is False."""
    terms = all_terms(q)
    cur = current_term(q, as_of)
    by_seq = {t["sequence"]: t for t in terms}
    m = _clean(mention).lower()
    if not m:
        return Resolved(cur, "ok", note="default: no term in the question") if default_current else Resolved()

    explicit = re.search(r"\b(fall|autumn|spring|summer)\s*(?:of\s*)?(\d{4})\b", m) or re.search(r"\b(\d{4})\s*(fall|autumn|spring|summer)\b", m)
    if explicit:
        season, year = (explicit.group(1), explicit.group(2)) if explicit.group(1).isalpha() else (explicit.group(2), explicit.group(1))
        name = f"{SEASONS[season].capitalize()} {year}"
        hit = next((t for t in terms if t["name"] == name), None)
        return Resolved(hit, "ok") if hit else Resolved(None, "not_found", note=f"no term named {name}")

    rel = re.search(rf"\b(this|next|last|previous|upcoming|coming|current)\s+(fall|autumn|spring|summer|{TERM_WORDS})\b", m)
    if rel:
        word, what = rel.group(1), rel.group(2)
        season = SEASONS.get(what)
        if word in ("this", "current"):
            if season is None or cur["term_type"] == season:
                return Resolved(cur, "ok")
            nxt = next((t for t in terms if t["sequence"] > cur["sequence"] and t["term_type"] == season), None)
            return Resolved(nxt, "ok", note=f"'{m}': current term is {cur['name']}, taking the next {season}") if nxt else Resolved(None, "not_found")
        if word in ("next", "upcoming", "coming"):
            # During a break the "current" term is the coming one (it has not started), and "next semester" means that coming term,
            # not the one after it (owner, 2026-11-02: "coming term"). In session, "next" is the term after the current one.
            step = 1 if cur["start_date"] <= as_of.date() <= cur["end_date"] else 0
            if season is None:
                hit = by_seq.get(cur["sequence"] + step)
            else:
                hit = next((t for t in terms if t["sequence"] >= cur["sequence"] + step and t["term_type"] == season), None)
            return Resolved(hit, "ok", note=None if step else f"'{m}' during the break before {cur['name']}: the coming term") \
                if hit else Resolved(None, "not_found", note=f"no term after {cur['name']}")
        if word in ("last", "previous"):
            if season is None:
                hit = by_seq.get(cur["sequence"] - 1)
            else:
                hit = next((t for t in reversed(terms) if t["sequence"] < cur["sequence"] and t["term_type"] == season), None)
            return Resolved(hit, "ok") if hit else Resolved(None, "not_found", note=f"no term before {cur['name']}")
    bare = re.search(r"\b(fall|autumn|spring|summer)\b", m)
    if bare:
        season = SEASONS[bare.group(1)]
        if cur["term_type"] == season:
            return Resolved(cur, "ok", note=f"'{m}': the current term is a {season}")
        nxt = next((t for t in terms if t["sequence"] > cur["sequence"] and t["term_type"] == season), None)
        return Resolved(nxt, "ok", note=f"'{m}': the next {season} after {cur['name']}") if nxt else Resolved(None, "not_found", note=f"no {season} after {cur['name']}")
    if re.search(r"\b(now|right now|currently|today|at the moment)\b", m):
        return Resolved(cur, "ok")
    return Resolved(None, "not_found", note=f"cannot read a term in '{mention}'")


# ---- crn / numbers -------------------------------------------------------------------------------------------------------
def crn(mention: str | None) -> Resolved:
    m = re.search(r"\b(\d{5})\b", _clean(mention))
    if m:
        return Resolved(m.group(1), "ok")
    return Resolved() if not _clean(mention) else Resolved(None, "not_found", note=f"no 5-digit CRN in '{mention}'")


def term_number(mention: str | None) -> Resolved:
    m = _clean(mention).lower()
    if not m:
        return Resolved()
    for w, n in ORDINALS.items():
        if re.search(rf"\b{w}\b", m):
            return Resolved(n, "ok")
    d = re.search(r"\b(\d{1,2})\b", m)
    if d and 1 <= int(d.group(1)) <= 12:
        return Resolved(int(d.group(1)), "ok")
    return Resolved(None, "not_found", note=f"cannot read a semester number in '{mention}'")


# ---- person ----------------------------------------------------------------------------------------------------------------
PERSON_SQL = """
    SELECT p.university_id, p.first_name, p.last_name, p.first_name || ' ' || p.last_name AS name,
           s.university_id IS NOT NULL AS is_student, i.university_id IS NOT NULL AS is_instructor
    FROM person p LEFT JOIN student s ON s.university_id = p.university_id LEFT JOIN instructor i ON i.university_id = p.university_id"""


def person(q: QueryLog, mention: str | None) -> Resolved:
    """A 9-digit ID, a full name, or a title plus last name ('Professor Lee', 'Dr. Lee') -> a person row with student/instructor flags."""
    m = _clean(mention)
    if not m:
        return Resolved()
    uid = re.search(r"\b(\d{9})\b", m)
    if uid:
        row = q.one("person by university id", PERSON_SQL + " WHERE p.university_id = %(u)s", u=uid.group(1))
        return Resolved(row, "ok") if row else Resolved(None, "not_found", note=f"no person with ID {uid.group(1)}")
    name = re.sub(r"^(professor|prof\.?|dr\.?|mr\.?|ms\.?|mrs\.?|student|instructor)\s+", "", m, flags=re.I)
    name = re.sub(r"'s$", "", name).strip(" ,.?!")
    rows = q.rows("person by full name", PERSON_SQL + " WHERE lower(p.first_name || ' ' || p.last_name) = lower(%(n)s) ORDER BY p.university_id", n=name)
    if not rows:
        rows = q.rows("person by last name", PERSON_SQL + " WHERE lower(p.last_name) = lower(%(n)s) ORDER BY p.university_id", n=name)
        if len(rows) > 1 and re.match(r"^(professor|prof\.?|dr\.?)\s", m, flags=re.I):
            rows = [r for r in rows if r["is_instructor"]]
    if len(rows) == 1:
        return Resolved(rows[0], "ok")
    if not rows:
        return Resolved(None, "not_found", note=f"no person named '{name}'")
    return Resolved(None, "ambiguous", [r["university_id"] for r in rows], note=f"'{name}' matches {len(rows)} people")


# ---- program -----------------------------------------------------------------------------------------------------------------
def program(q: QueryLog, mention: str | None, own_program_code: str) -> Resolved:
    """A program name, code, or a subject word ('computer science') -> program code. 'my program'/none -> the asker's own program."""
    m = _clean(mention).lower()
    rows = q.rows("programs", "SELECT code, name, degree, department_code FROM program ORDER BY code")
    if not m:
        return Resolved(own_program_code, "ok", note="default: no program named, taking the asker's own")
    if re.search(r"\b(my|our)\b", m):
        return Resolved(own_program_code, "ok", note="the asker's own program")
    exact = [r for r in rows if r["code"].lower() == m or r["name"].lower() == m]
    if len(exact) == 1:
        return Resolved(exact[0]["code"], "ok")
    partial = [r for r in rows if m in r["name"].lower()]
    if len(partial) == 1:
        return Resolved(partial[0]["code"], "ok")
    if partial:
        own = [r for r in partial if r["code"] == own_program_code]
        if own:
            return Resolved(own[0]["code"], "ok", note=f"'{mention}' matches several programs; taking the asker's own")
        return Resolved(None, "ambiguous", [r["code"] for r in partial], note=f"'{mention}' matches {len(partial)} programs")
    return Resolved(None, "not_found", note=f"no program matching '{mention}'")
