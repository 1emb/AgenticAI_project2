"""Stage 5, optional: the discrete answer becomes one to three English sentences for the student.

    write_reply(llm, trace)        # sets trace.reply and trace.timings["reply_s"]

The model is given the question and the facts of the answer, nothing else. It never sees the database, the SQL or a refused
record: for a refused question the answer's `target` (the other person's university id) is removed before the facts are
rendered, so the reply cannot contain it. Times, dates and day codes are formatted here, deterministically, before the model
sees them. If the model is unreachable the reply is a fixed sentence built from the answer shape, so the caller always gets text.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal

from ..testset.common import DAY_NAMES, fmt_date, fmt_time, num
from .llm import Client, LLMError
from .pipeline import Trace

SYSTEM = """You are the registrar's assistant at a university, replying to a student in a chat.
You are given the student's question and a JSON object of verified facts that answer it. Write the reply.
Rules:
- One to three short sentences, plain English, no markdown, no lists, no JSON, no field names.
- Use only the facts given. Never add, guess or infer anything that is not in the facts. Never mention university IDs, SQL or databases.
- Refer to people by name, never by he, she, him or her. Do not add advice (such as "consult your advisor") that is not in the facts.
- Dates, times and weekdays are already formatted; copy them as they are.
- If "allowed" is false, decline politely in one sentence and say why in general terms: another student's record is private;
  an instructor's personal details (phone, date of birth, SSN, hire date) are private; lists of students are not given out.
  If "own_answer" is present, give that permitted part as well. Do not name the person whose record was refused unless the facts name them.
- If "error" is "missing_slot", ask the student for the missing piece ("slot": course, term, crn, person, program...) in one sentence,
  using the note if there is one.
- If "unknown" is true, say in one sentence that you can only help with the course catalog, class schedules, degree plans,
  the academic calendar and the student's own record.
- "groups" of prerequisites: alternatives inside one group are OR, different groups are AND.
- Level codes: lower_division = lower-division, upper_division = upper-division, graduate = graduate-level."""

_DAY_KEYS = {"days", "teaching_days"}
_TIME_KEYS = {"start", "end"}


def _format(v, key: str | None = None):
    """Deterministic formatting of the answer before the model sees it."""
    if isinstance(v, dict):
        return {k: _format(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_format(x, key) for x in v]
    if isinstance(v, datetime):
        return fmt_date(v)
    if isinstance(v, date):
        return fmt_date(v)
    if isinstance(v, dtime):
        return fmt_time(v)
    if isinstance(v, Decimal):
        return num(v)
    if isinstance(v, str):
        if key in _DAY_KEYS and v and all(c in DAY_NAMES for c in v):
            return ", ".join(DAY_NAMES[c] for c in v)
        if key in _TIME_KEYS and re.fullmatch(r"\d{2}:\d{2}", v):
            h, m = map(int, v.split(":"))
            return fmt_time(dtime(h, m))
    return v


def facts_for_model(answer: dict) -> dict:
    """The answer without anything the student may not learn: a refusal's `target` is the other person's id."""
    a = {k: v for k, v in answer.items() if k != "target"}
    return _format(a)


def fallback(answer: dict | None, error: str | None) -> str:
    """Fixed sentences when the model is unavailable."""
    if answer is None:
        return f"Sorry, I could not process that question ({error or 'unknown error'})."
    if answer.get("allowed") is False:
        reason = {"other_student_record": "another student's record is private",
                  "student_list_not_permitted": "lists of students are not given out",
                  "instructor_private_record": "an instructor's personal details are private"}.get(answer.get("reason"), "that information is private")
        s = f"Sorry, I can't share that: {reason}."
        if answer.get("own_answer"):
            s += " What I can tell you: " + json.dumps(_format(answer["own_answer"]), ensure_ascii=False) + "."
        return s
    if answer.get("error") == "missing_slot":
        return f"Which {answer.get('slot')} do you mean? " + (answer.get("note") or "")
    if answer.get("unknown"):
        return "I can help with the course catalog, class schedules, degree plans, the academic calendar and your own record."
    return "Here is what I found: " + json.dumps(_format(answer), ensure_ascii=False)


def write_reply(llm: Client, t: Trace) -> str:
    """Fill t.reply from t.answer (or the pipeline error) and return it."""
    t0 = time.perf_counter()
    try:
        if t.answer is None:
            raise LLMError("no answer to render")
        user = f"Question: {t.question}\nFacts: {json.dumps(facts_for_model(t.answer), ensure_ascii=False)}\nReply:"
        res = llm.complete(SYSTEM, user, max_tokens=220)
        reply = " ".join(res.content.split()).strip() or fallback(t.answer, t.error)
        if _leaks(reply, t.answer):
            reply = fallback(t.answer, t.error)
    except LLMError:
        reply = fallback(t.answer, t.error)
    t.reply = reply
    t.timings["reply_s"] = round(time.perf_counter() - t0, 3)
    return reply


def _leaks(reply: str, answer: dict) -> bool:
    """A refused question's reply must not carry the refused person's id, even though the model was not given it."""
    if answer.get("allowed") is not False:
        return False
    target = answer.get("target") or {}
    ids = [target.get("university_id")] + list(target.get("university_ids") or [])
    return any(i and str(i) in reply for i in ids)
