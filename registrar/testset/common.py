"""Shared plumbing for test-set generators: clocks, query logging, formatting helpers, JSON encoding, leak markers."""
from __future__ import annotations

import json
import random
import re
import string
from datetime import date, datetime, time, timezone
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

UTC = timezone.utc
SNAPSHOT = datetime(2026, 10, 19, 16, 0, tzinfo=UTC)        # Spring 2027 registration not yet open; Fall withdraw deadline still ahead
DEFAULT_AS_OF = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)   # the clock assumed when a question names no time
AS_OF_LATE = datetime(2026, 12, 3, 15, 30, tzinfo=UTC)      # late Fall 2026, before finals end
AS_OF_BREAK = datetime(2026, 12, 20, 18, 0, tzinfo=UTC)     # winter break: Fall 2026 over, Spring 2027 not started
AS_OF_SPRING = datetime(2027, 1, 20, 18, 0, tzinfo=UTC)     # Spring 2027 in progress, add deadline (Jan 22) still ahead
CURRENT, FUTURE, PREVIOUS = "202680", "202710", "202610"    # at the default clock

DAY_NAMES = {"M": "Monday", "T": "Tuesday", "W": "Wednesday", "R": "Thursday", "F": "Friday", "S": "Saturday", "U": "Sunday"}
DAY_ABBR = {"M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu", "F": "Fri", "S": "Sat", "U": "Sun"}
WEEK = "MTWRFSU"
EVENTS = {"classes_begin": "start_date", "classes_end": "end_date", "registration_opens": "registration_opens", "add_deadline": "add_deadline",
          "drop_deadline": "drop_deadline", "withdraw_deadline": "withdraw_deadline", "grades_due": "grades_due"}
ORDINAL = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth"}
RANK_TITLE = {"professor": "Professor", "associate": "Associate Professor", "assistant": "Assistant Professor", "lecturer": "Lecturer", "adjunct": "Adjunct Instructor",
              "ta": "Teaching Assistant"}


def connect(dsn: str) -> psycopg.Connection:
    """Client-side cursor so every executed statement can be captured with literal values."""
    return psycopg.connect(dsn, cursor_factory=psycopg.ClientCursor, options="-c TimeZone=UTC")


class QueryLog:
    """Runs queries and keeps the literal SQL (params substituted) in execution order."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.entries: list[dict] = []

    def rows(self, purpose: str, sql: str, **params) -> list[dict]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            literal = cur.mogrify(sql, params or None)
            cur.execute(sql, params or None)
            out = cur.fetchall()
        entry = {"purpose": purpose, "sql": " ".join(literal.split())}
        if entry not in self.entries:
            self.entries.append(entry)
        return out

    def one(self, purpose: str, sql: str, **params) -> dict | None:
        r = self.rows(purpose, sql, **params)
        return r[0] if r else None


def pick(rng: random.Random, templates: list[str], k: int = 3, **slots) -> tuple[str, list[str]]:
    """Question plus paraphrases from a template list. Templates whose placeholders are not all in `slots` are skipped, so a
    list can mix wordings for different targets. Term phrases carry their own preposition ("in Fall 2025"), so a doubled
    one ("in in Fall 2025") is collapsed."""
    usable = [t for t in templates if all(name in slots for _, name, _, _ in string.Formatter().parse(t) if name)]
    chosen = rng.sample(usable, k=min(k, len(usable)))
    rendered = [re.sub(r"\b(in|for|during) (?:in|for|during)\b", r"\1", t.format(**slots)) for t in chosen]
    return rendered[0], rendered[1:]


def term_phrase(rng: random.Random, term: dict, current: dict) -> tuple[str, str]:
    """(phrase, name): how a person refers to the term, as a phrase that follows a verb ("... in Fall 2024", "... this semester")."""
    opts = [f"in {term['name']}", f"in {term['name']}"]
    if term["code"] == current["code"]:
        opts += ["this semester", f"this {term['term_type']}", "this term"]
    elif term["sequence"] == current["sequence"] + 1:
        opts += ["next semester", f"next {term['term_type']}", "next term"]
    elif term["sequence"] == current["sequence"] - 1:
        opts += ["last semester", f"last {term['term_type']}", "last term"]
    return rng.choice(opts), term["name"]


def num(v):
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f.is_integer() else f
    return v


def fmt_date(d: date | datetime | None) -> str:
    if d is None:
        return "n/a"
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def fmt_time(t: time) -> str:
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def fmt_days(days: str) -> str:
    return "/".join(DAY_ABBR[d] for d in days)


def fmt_meeting(days: str, start: time, end: time, room: str | None) -> str:
    where = f" in {room}" if room else ""
    return f"{fmt_days(days)} {fmt_time(start)}-{fmt_time(end)}{where}"


def fmt_list(items) -> str:
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def fmt_groups(groups: list[list[dict]]) -> str:
    """Prerequisite groups as prose: 'CS 2210 (C- or better) and MATH 2210 (C or better)'; alternatives inside a group use 'or'."""
    parts = []
    for g in groups:
        alts = [f"{m['course']} ({m['min_grade']} or better)" for m in g]
        parts.append(" or ".join(alts) if len(alts) > 1 else alts[0])
    return fmt_list(parts)


class Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, time):
            return o.strftime("%H:%M")
        if isinstance(o, Decimal):
            return num(o)
        return super().default(o)


def leak_markers(values) -> list[str] | None:
    """Values that must not appear in the agent's reply. Only strings of three or more characters are usable; a program code
    or a status word is too common to scan for. Returns None when nothing usable is left (the refusal is then the only check)."""
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        v = str(v).strip()
        if len(v) >= 3 and v not in out:
            out.append(v)
    return out or None


def with_allowed(answer: dict) -> dict:
    """Every ground-truth answer states whether the request was permitted; access-control builders set it themselves."""
    if "allowed" in answer:
        return answer
    return {"allowed": True, **answer}
