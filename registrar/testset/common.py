"""Shared plumbing for test-set generators: query logging, formatting helpers, JSON encoding."""
from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

GRADE_ORDER = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]
DAY_NAMES = {"M": "Monday", "T": "Tuesday", "W": "Wednesday", "R": "Thursday", "F": "Friday", "S": "Saturday", "U": "Sunday"}
DAY_ABBR = {"M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu", "F": "Fri", "S": "Sat", "U": "Sun"}
WEEK = "MTWRFSU"


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


def grade_meets(grade: str | None, min_grade: str) -> bool:
    if grade is None:
        return True  # transfer / test credit without a letter grade counts as passed
    if grade == "S":
        return GRADE_ORDER.index(min_grade) >= GRADE_ORDER.index("C-")
    if grade not in GRADE_ORDER:
        return False
    return GRADE_ORDER.index(grade) <= GRADE_ORDER.index(min_grade)


def num(v):
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f.is_integer() else f
    return v


def fmt_credits(v) -> str:
    v = num(v)
    return str(v)


def fmt_date(d: date | datetime | None) -> str:
    if d is None:
        return "n/a"
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def fmt_dt(d: datetime | None) -> str:
    if d is None:
        return "n/a"
    return f"{fmt_date(d)} at {fmt_time(d.time())} UTC"


def fmt_time(t: time) -> str:
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def fmt_days(days: str) -> str:
    return "/".join(DAY_ABBR[d] for d in days)


def fmt_meeting(m: dict) -> str:
    where = f" in {m['building']} {m['room_number']}" if m.get("building") else ""
    kind = f" ({m['meeting_type']})" if m.get("meeting_type") and m["meeting_type"] != "lecture" else ""
    return f"{fmt_days(m['days'])} {fmt_time(m['start_time'])}-{fmt_time(m['end_time'])}{where}{kind}"


def fmt_list(items: list[str]) -> str:
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def article(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def cap_first(s: str) -> str:
    return s[:1].upper() + s[1:]


def gpa(v) -> str:
    return "n/a" if v is None else f"{float(v):.2f}"


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
