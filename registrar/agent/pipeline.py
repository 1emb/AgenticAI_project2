"""Question in, discrete answer out, with a trace of every stage.

    trace = answer_question(conn, llm, question, university_id, as_of)

Stages: classify (LLM, label only) -> extract (LLM, mentions only) -> resolve (Python, mentions to keys) -> program (Python,
permission rule + SQL). reply.write_reply() adds the optional fifth stage, English prose from the answer. The trace keeps the label and its confidence, the mentions, each resolution with its status, the SQL run,
timings and the error of the stage that failed, if any.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from ..testset import queries as Q
from ..testset.common import DEFAULT_AS_OF, QueryLog
from . import resolve
from .intents import BY_NAME, DETAIL_VALUES, EVENT_VALUES, REQUESTED_VALUES, UNKNOWN, Intent
from .llm import Client, LLMError
from .programs import PROGRAMS, Missing
from .resolve import Resolved


@dataclass
class Trace:
    question: str
    as_of: datetime
    user: dict
    intent: str | None = None
    intent_confidence: float | None = None
    multi_request: bool | None = None                  # the message holds more than one request (llm.count_requests); one is answered
    mentions: dict = field(default_factory=dict)
    resolved: dict = field(default_factory=dict)       # slot -> {value, status, note}
    answer: dict | None = None
    reply: str | None = None                            # English reply (reply.py), when asked for
    error: str | None = None
    failed_stage: str | None = None
    sql: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        return d


def _summary(res: Resolved) -> dict:
    v = res.value
    if isinstance(v, dict):
        v = v.get("code") or v.get("university_id") or v
    return {"value": v, "status": res.status, "note": res.note, **({"candidates": res.candidates} if res.candidates else {})}


def resolve_all(q: QueryLog, intent: Intent, mentions: dict, as_of: datetime, st: dict) -> dict[str, Resolved]:
    """Every slot the intent declares becomes a Resolved; absent slots resolve to 'none' so programs can test .ok uniformly."""
    r: dict[str, Resolved] = {}
    get = mentions.get
    if "course_mention" in intent.slots:
        r["course"] = resolve.course(q, get("course_mention"))
    if "crn_mention" in intent.slots:
        r["crn"] = resolve.crn(get("crn_mention"))
    if "term_mention" in intent.slots:
        r["term"] = resolve.term(q, get("term_mention"), as_of, default_current=intent.name not in ("my_transcript", "my_gpa"))
    if "day_mention" in intent.slots:
        r["day"] = resolve.day(get("day_mention"), as_of)
    if "term_number_mention" in intent.slots:
        r["term_number"] = resolve.term_number(get("term_number_mention"))
    if "event" in intent.slots:
        r["event"] = Resolved(EVENT_VALUES[get("event")], "ok") if get("event") in EVENT_VALUES else Resolved()
    if "person_mention" in intent.slots:
        r["person"] = resolve.person(q, get("person_mention"))
    if "requested" in intent.slots:
        r["requested"] = Resolved([REQUESTED_VALUES[v] for v in get("requested") or [] if v in REQUESTED_VALUES], "ok")
    if "own_appointment" in intent.slots:
        r["own_appointment"] = Resolved(bool(get("own_appointment")), "ok")
    if "compare_with_me" in intent.slots:
        r["compare_with_me"] = Resolved(bool(get("compare_with_me")), "ok")
    if "program_mention" in intent.slots:
        r["program"] = resolve.program(q, get("program_mention"), st["program_code"])
    if "details" in intent.slots:
        r["details"] = Resolved([DETAIL_VALUES[v] for v in get("details") or [] if v in DETAIL_VALUES], "ok")
    return r


def answer_question(conn, llm: Client, question: str, university_id: str, as_of: datetime = DEFAULT_AS_OF, intent_override: str | None = None) -> Trace:
    q = QueryLog(conn)
    st = Q.student_by_uid(q, university_id)
    if st is None:
        raise ValueError(f"no student {university_id}")
    t = Trace(question, as_of, {"university_id": st["university_id"], "name": f"{st['first_name']} {st['last_name']}", "program_code": st["program_code"]})
    try:
        # 1. classify
        t0 = time.perf_counter()
        if intent_override:
            label = intent_override
            t.timings["classify_s"] = round(time.perf_counter() - t0, 3)
        else:   # classify; count the requests (one is answered per message, owner 2026-11-02); rescue a multi-request unknown
            label, t.intent_confidence, t.multi_request, timings = llm.label(question)
            t.timings.update(timings)
        t.intent = label
        intent = BY_NAME.get(label, BY_NAME[UNKNOWN])
        # 2. extract
        t0 = time.perf_counter()
        t.mentions, _ = llm.extract(question, intent)
        t.timings["extract_s"] = round(time.perf_counter() - t0, 3)
        # 3. resolve
        t0 = time.perf_counter()
        resolved = resolve_all(q, intent, t.mentions, as_of, st)
        t.resolved = {k: _summary(v) for k, v in resolved.items()}
        t.timings["resolve_s"] = round(time.perf_counter() - t0, 3)
        # 4. program (permission rule inside)
        t0 = time.perf_counter()
        t.answer = PROGRAMS[intent.name](q, resolved, st, as_of)
        t.timings["program_s"] = round(time.perf_counter() - t0, 3)
    except LLMError as e:
        t.error, t.failed_stage = str(e), "classify" if t.intent is None else "extract"
    except Missing as e:
        t.error, t.failed_stage = str(e), "resolve"
        t.answer = {"allowed": True, "error": "missing_slot", "slot": e.slot, "status": e.res.status, "note": e.res.note}
    t.sql = [e for e in q.entries if not e["purpose"].startswith("LEAK")]
    return t
