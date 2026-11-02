"""Helpers shared by every agent."""
from __future__ import annotations

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
