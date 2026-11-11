"""Helpers shared by every agent."""
from __future__ import annotations

import re
from datetime import date, time
from decimal import Decimal


class ToolError(Exception):
    """A problem the model should read and explain (unknown course, bad term, ...)."""


def plain(v):
    """JSON-friendly values in the test-set conventions: 3.0 -> 3, times HH:MM, dates ISO, enums by value."""
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "value"):
        return v.value
    return v


def normalize_course(code: str) -> str:
    """'cs2210', 'CS-2210', ' cs 2210 ' -> 'CS 2210'."""
    m = re.fullmatch(r"\s*([A-Za-z]{2,5})\s*-?\s*(\d{3,4}[A-Za-z]?)\s*", str(code or ""))
    if not m:
        raise ToolError(f"{code!r} is not a course code. Use the form 'CS 2210'.")
    return f"{m.group(1).upper()} {m.group(2).upper()}"


def full_name(person) -> str:
    return f"{person.first_name} {person.last_name}"


def name_words(text: str | None) -> list[str]:
    """Lower-case words of a person's name without titles: 'Dr. Juan Hall' -> ['juan', 'hall']."""
    titles = {"professor", "prof", "dr", "doctor", "mr", "ms", "mrs", "instructor", "student", "colleague"}
    return [w for w in re.findall(r"[a-z]+", str(text or "").lower()) if w not in titles]
