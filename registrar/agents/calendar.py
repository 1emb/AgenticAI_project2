"""The agent's clock and term arithmetic.

The current term is never stored (README, Conventions): it is the term whose start_date..end_date contains the clock's
date, and during a break the next term by start date. "Last semester" is the term with sequence one lower. "Next
semester" is the term with sequence one higher while classes are in session; during a break it is the coming term
itself, the same as the current one (owner, 2026-11-02; data/testset/README.md, Case format). Phrases such as "this fall" or "next spring" are resolved here in Python, so the model never has to do
date arithmetic.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from registrar.models import AcademicTerm

UTC = timezone.utc
SEASONS = ("fall", "spring", "summer")
_THIS = {"this", "current", "now", "present"}
_NEXT = {"next", "upcoming", "coming", "following"}
_LAST = {"last", "previous", "past", "prior"}
_SKIP = {"in", "for", "during", "the", "a", "semester", "term", "session", "of", "right", "s"}


def parse_as_of(value: str | datetime | None) -> datetime:
    """The clock as an aware UTC datetime. None means the real current time."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class TermNotFound(ValueError):
    pass


class Calendar:
    def __init__(self, session: Session, as_of: str | datetime | None = None):
        self.as_of = parse_as_of(as_of)
        self.today: date = self.as_of.date()
        self.terms: list[AcademicTerm] = list(session.scalars(select(AcademicTerm).order_by(AcademicTerm.sequence)))
        if not self.terms:
            raise RuntimeError("academic_term is empty; load data/seed first.")
        self._by_seq = {t.sequence: t for t in self.terms}
        self._by_code = {t.code: t for t in self.terms}
        self._by_name = {t.name.lower(): t for t in self.terms}

    # ------------------------------------------------------------ anchors
    def current(self) -> AcademicTerm:
        return next((t for t in self.terms if t.end_date >= self.today), self.terms[-1])

    def offset(self, n: int) -> AcademicTerm | None:
        return self._by_seq.get(self.current().sequence + n)

    def in_session(self) -> bool:
        cur = self.current()
        return cur.start_date <= self.today <= cur.end_date

    # ------------------------------------------------------------ phrases
    def resolve(self, phrase: str | None, default: int = 0) -> AcademicTerm:
        """Turn what the user said into a term. `default` is the offset used when no term is named
        (0 = current term, 1 = next term)."""
        text = (phrase or "").strip().lower().replace("'", "")
        if not text:
            return self._offset_or_fail(default)
        if re.fullmatch(r"\d{6}", text) and text in self._by_code:
            return self._by_code[text]
        named = re.search(r"(fall|spring|summer)\s*(\d{4})", text)
        if named:
            term = self._by_name.get(f"{named.group(1)} {named.group(2)}")
            if term is None:
                raise TermNotFound(f"There is no {named.group(1).title()} {named.group(2)} term in the calendar.")
            return term

        words = [w for w in re.findall(r"[a-z]+", text) if w not in _SKIP]
        season = next((w for w in words if w in SEASONS), None)
        if any(w in _NEXT for w in words):
            direction = 1
        elif any(w in _LAST for w in words):
            direction = -1
        elif any(w in _THIS for w in words) or season:
            direction = 0
        else:
            raise TermNotFound(f"I can't tell which term {phrase!r} means. Use e.g. 'this semester', 'next spring' "
                               f"or 'Fall 2026'.")
        step = direction
        if direction == 1 and not self.in_session():
            step = 0                                   # break: "next" is the coming term
        if season is None:
            return self._offset_or_fail(step)
        return self._season(season, direction, step)

    def _offset_or_fail(self, n: int) -> AcademicTerm:
        term = self.offset(n)
        if term is None:
            raise TermNotFound("That term is outside the calendar.")
        return term

    def _season(self, season: str, direction: int, first_step: int) -> AcademicTerm:
        """'this fall' = the current term if it is a fall, else the coming fall; 'next spring' = the first spring from
        `first_step` terms ahead (0 during a break); 'last fall' = the most recent earlier fall."""
        cur = self.current()
        if direction == 0 and cur.term_type.value == season:
            return cur
        step = -1 if direction < 0 else 1
        seq = cur.sequence + (first_step if direction > 0 else step)
        while seq in self._by_seq:
            if self._by_seq[seq].term_type.value == season:
                return self._by_seq[seq]
            seq += step
        raise TermNotFound(f"No {season} term found in that direction.")
