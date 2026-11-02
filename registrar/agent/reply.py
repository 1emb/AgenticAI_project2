"""Stage 5: the English reply. Deterministic by default (decided 2026-11-02): one writer per intent turns the discrete answer into
sentences, refusals and clarifications are fixed sentences, and no model is involved, so the reply can neither invent a fact nor
leak one. The earlier LLM rendering is kept behind mode="llm" for comparison only.

    write_reply(llm, trace)                 # deterministic; llm is unused in this mode
    write_reply(llm, trace, mode="llm")     # the old third model call

Why deterministic: on 90 realistic questions (runs/codex/phase2-report.md) the JSON answer was right in every case where the English
was wrong; the model turned AND into OR, "not in your plan" into "yes", required-course credits into the degree total, and invented
"no holds" and "no longer enrolled". The wording policy: registrar statuses are reported as stored and never interpreted; dates as
"Oct 23, 2026", times as "9:30 AM"; instructor emails are included when the answer has them; a refusal never repeats the other
person's name; nothing is said about data the answer does not carry.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal

from ..testset.common import DAY_ABBR, DAY_NAMES, RANK_TITLE, fmt_date, fmt_list, fmt_time, num
from .llm import Client, LLMError
from .pipeline import Trace

# ---------------------------------------------------------------------------------------------------------------------------------
# deterministic renderer
# ---------------------------------------------------------------------------------------------------------------------------------
REFUSALS = {
    "other_student_record": "I can't share another student's record.",
    "instructor_private_record": "I can't share an instructor's private personal details (phone number, date of birth, SSN, hire date).",
    "student_list_not_permitted": "I can't provide lists of students, whether by program, course or section.",
}
SCOPE = "I can help with the course catalog, class schedules, degree plans, the academic calendar and your own registrar record."
EVENT_PHRASE = {
    "classes_begin": "Classes in {term} begin {date}.",
    "classes_end": "Classes in {term} end {date}.",
    "add_deadline": "The last day to add a class in {term} is {date}.",
    "drop_deadline": "The last day to drop a class in {term} without a W is {date}.",
    "withdraw_deadline": "The last day to withdraw from a class in {term} (with a W) is {date}.",
    "grades_due": "Grades for {term} are due {date}.",
}
# No conversation state is kept (owner, 2026-11-02): a clarification tells the student to ask again with the missing piece included,
# because the next message is classified on its own and cannot be matched to this one.
SLOT_QUESTION = {
    "course": "Please ask again and include the course: a course code such as CS 2230, or its exact title.",
    "crn": "Please ask again and include the section's 5-digit CRN, and the term if it is not the current one.",
    "term": "Please ask again and include the term, for example Fall 2026 or 'next spring'.",
    "term_number": "Please ask again and say which semester of the plan you mean, 1 through 8.",
    "event": "Please ask again and say which date you need: the first or last day of classes, the add, drop or withdrawal deadline, or when grades are due.",
    "person": "Please ask again and include the person's full name or university ID.",
    "program": "Please ask again and include the program.",
}

def _d(v) -> str:
    """A date, datetime or ISO string -> 'Oct 23, 2026'."""
    if isinstance(v, str):
        try:
            v = date.fromisoformat(v[:10])
        except ValueError:
            return v
    return fmt_date(v)


def _t(v) -> str:
    if isinstance(v, str):
        h, m = (int(x) for x in v.split(":")[:2])
        v = dtime(h, m)
    return fmt_time(v)


def _days(days: str) -> str:
    return "/".join(DAY_ABBR[c] for c in days) if days and all(c in DAY_ABBR for c in days) else days


def _n(v):
    return num(v) if isinstance(v, Decimal) else v


def _status(s: str) -> str:
    return {"leave_of_absence": "on leave of absence"}.get(s, (s or "").replace("_", " "))


def _level(level: str) -> str:
    return {"lower_division": "lower-division", "upper_division": "upper-division", "graduate": "graduate-level"}.get(level, level)


def _group(g: list[dict], several: bool) -> str:
    alts = [f"{m['course']} with {m['min_grade']} or better" for m in g]
    if len(alts) == 1:
        return alts[0]
    inner = "either " + " or ".join(alts)
    return f"({inner})" if several else inner


# ---- allowed answers, one writer per intent ----
def r_prerequisites(a, t):
    groups = a.get("groups") or []
    if not a.get("has_prerequisites") or not groups:
        return f"No prerequisites are listed for {a['course']}."
    if len(groups) == 1:
        return f"{a['course']} requires {_group(groups[0], False)}."
    return f"{a['course']} requires all of these: " + " AND ".join(_group(g, True) for g in groups) + "."


def r_course_info(a, t):
    s = f"{a['course']}, {a['title']}, is a {_n(a['credit_hours'])}-credit {_level(a['level'])} course offered by {a['department']} ({a['department_code']})."
    return s + ("" if a.get("is_active", True) else " It is no longer active, so it is not being offered.")


def r_course_offered(a, t):
    if a["offered"]:
        s = f"Yes, {a['course']} is offered in {a['term']}: {fmt_list('CRN ' + str(c) for c in a['crns'])}."
    else:
        s = f"No, {a['course']} has no sections listed in {a['term']}."
    return s + ("" if a.get("is_active", True) else f" {a['course']} is a retired course.")


def _section(sec: dict) -> str:
    parts = [f"CRN {sec['crn']}"]
    if sec.get("section_number"):
        parts[0] += f" (section {sec['section_number']})"
    if sec.get("days") and sec.get("start"):
        parts.append(f"{_days(sec['days'])} {_t(sec['start'])}-{_t(sec['end'])}")
    if sec.get("room"):
        parts.append(f"in {sec['room']}")
    if sec.get("instructor"):
        parts.append(f"with {sec['instructor']}")
    if sec.get("capacity") is not None:
        parts.append(f"{sec['capacity']} seats")
    return ", ".join(parts)


def r_lecture_options(a, t):
    secs = a.get("sections") or []
    if not secs:
        return f"No sections of {a['course']} are scheduled in {a['term']}."
    n = len(secs)
    return f"{a['course']} has {n} section{'s' if n != 1 else ''} in {a['term']}: " + "; ".join(_section(s) for s in secs) + "."


def r_lecture_meeting(a, t):
    lead = f"CRN {a['crn']} ({a['course']}, {a['term']}) is cancelled. Its recorded meeting was " if a.get("is_cancelled") \
        else f"CRN {a['crn']} is {a['course']} in {a['term']}: "
    s = lead + (f"{_days(a['days'])} {_t(a['start'])}-{_t(a['end'])}" if a.get("days") and a.get("start") else "at a time that is not listed")
    s += f" in {a['room']}" if a.get("room") else " (no room is listed)"
    return s + (f", taught by {a['instructor']}." if a.get("instructor") else ".")


def r_who_teaches(a, t):
    if a.get("crn") and a.get("instructor"):
        return f"CRN {a['crn']} ({a['course']}, {a['term']}) is taught by {a['instructor']}" + (f", {a['email']}." if a.get("email") else ".")
    ins = a.get("instructors") or []
    if not ins:
        return f"{a['course']} is not offered in {a['term']}, so nobody is scheduled to teach it."
    who = fmt_list(f"{i['instructor']} (CRN {i['crn']}" + (f", {i['email']})" if i.get("email") else ")") for i in ins)
    return f"{a['course']} in {a['term']} is taught by {who}."


def r_capacity(a, t):
    return f"CRN {a['crn']} ({a['course']}, {a['term']}) has a recorded capacity of {a['capacity']} seats. I don't have enrollment counts, so I can't say how many are left."


def _prog(a) -> str:
    """'Bachelor of Science in Computer Science (BSCS)', or just the code when the name is not in the answer."""
    name = a.get("program_name")
    return f"{name} ({a['program']})" if name and name != a["program"] else a["program"]


def r_degree_required(a, t):
    req = a.get("required") or []
    if not req:
        return f"The {_prog(a)} plan lists no required courses."
    s = f"The {_prog(a)} plan has {len(req)} required courses: {fmt_list(req)}."
    s += f" These listed required courses total {_n(a['required_credits'])} credits"
    if a.get("total_credits_required") is not None:
        s += f"; the program requires {_n(a['total_credits_required'])} credits overall"
    return s + "."


def r_degree_credits(a, t):
    mins = a.get("minimums") or {}
    s = f"The {_prog(a)} requires {_n(a['total_credits_required'])} credits in total"
    if mins:
        s += ", including at least " + fmt_list(f"{_n(v)} in {k.replace('_', ' ')}" for k, v in mins.items())
    return s + "."


def r_course_in_plan(a, t):
    prog = a["program"]
    if not a["in_plan"]:
        return f"{a['course']} is not listed in the {prog} degree plan."
    cat = (a.get("category") or "").replace("_", " ")
    when = f", suggested for semester {a['suggested_term_number']}" if a.get("suggested_term_number") else ""
    if a.get("is_required"):
        return f"Yes, {a['course']} is a required course in the {prog} plan ({cat}){when}."
    return f"{a['course']} is listed in the {prog} plan as a {cat} option{when}; it is not a required course."


def r_plan_term(a, t):
    courses = a.get("courses") or []
    if not courses:
        return f"The {a['program']} plan lists nothing for semester {a['term_number']}."
    s = f"For semester {a['term_number']}, the {a['program']} plan suggests {fmt_list(courses)}"
    return s + (f" ({_n(a['credits'])} credits)." if a.get("credits") is not None else ".")


def r_my_program(a, t):
    s = f"Your record lists the {a['name']} ({a['program']}) in the {a['department']} department. Your recorded registrar status is {_status(a['status'])}."
    if a.get("admit_term"):
        s += f" Admit term: {a['admit_term']}."
    s += f" Expected graduation term on record: {a['expected_graduation_term']}." if a.get("expected_graduation_term") else " No expected graduation term is listed."
    return s


def r_register_when(a, t):
    s = ("I don't have individual registration appointments or time tickets. " if a.get("own_appointment") else "") + \
        f"Registration for {a['term']} opens {_d(a['registration_opens'])} and closes {_d(a['add_deadline'])}, the add deadline."
    if a.get("is_open"):
        return s + " It is open now."
    today = t.as_of.date()
    opens = a["registration_opens"] if isinstance(a["registration_opens"], date) else date.fromisoformat(str(a["registration_opens"])[:10])
    return s + (" It has not opened yet." if today < opens else " It has closed.")


def r_term_dates(a, t):
    if "event" not in a:                      # registration_opens is answered through register_when
        return r_register_when(a, t)
    s = EVENT_PHRASE.get(a["event"], "{term} " + a["event"].replace("_", " ") + ": {date}.").format(term=a["term"], date=_d(a["date"]))
    d = a["date"] if isinstance(a["date"], date) else date.fromisoformat(str(a["date"])[:10])
    today = t.as_of.date()
    return s + (" That date has passed." if d < today else " That is today." if d == today else f" As of {fmt_date(today)}, that is still ahead.")


def r_current_term(a, t):
    s = f"The current term is {a['term']}"
    if a.get("in_session"):
        s += " and classes are in session."
    else:
        s += "; classes are not in session right now" + (f" (they start {_d(a['start_date'])})." if a.get("start_date") else ".")
    if a.get("next_term"):
        s += f" The next term is {a['next_term']}" + (f" and the previous one was {a['previous_term']}." if a.get("previous_term") else ".")
    return s


def r_person_info(a, t):
    if "instructor" in a:
        s = f"{a['instructor']} is {_rank(a.get('rank'))} in {a.get('department')}"
        return s + (f"; email {a['email']}." if a.get("email") else ".")
    return r_my_program(a, t)


def r_unknown(a, t):
    return "I don't know what you are talking about. " + SCOPE


def _rank(rank: str | None) -> str:
    title = RANK_TITLE.get(rank or "", rank or "an instructor")
    return ("an " if title[:1].lower() in "aeiou" else "a ") + title


WRITERS = {
    "prerequisites": r_prerequisites, "course_info": r_course_info, "course_offered": r_course_offered, "lecture_options": r_lecture_options,
    "lecture_meeting": r_lecture_meeting, "who_teaches": r_who_teaches, "capacity": r_capacity, "degree_required": r_degree_required,
    "degree_credits": r_degree_credits, "course_in_plan": r_course_in_plan, "plan_term": r_plan_term, "my_program": r_my_program,
    "register_when": r_register_when, "term_dates": r_term_dates, "current_term": r_current_term, "person_info": r_person_info,
    "unknown": r_unknown,
}


# ---- refusals, clarifications, errors ----
def _own_answer(own: dict) -> str:
    if not own:
        return ""
    if own.get("instructor") and own.get("rank"):
        s = f" The instructor directory lists {own['instructor']} as {_rank(own['rank'])} in {own.get('department')}" + (f"; email {own['email']}." if own.get("email") else ".")
        return s + (f" You are in {own['program']}." if own.get("program") else "")
    if own.get("instructor"):
        return f" The instructor is {own['instructor']}."
    if own.get("instructors"):
        return " The instructors are " + fmt_list(f"{i['instructor']} (CRN {i['crn']})" for i in own["instructors"]) + "."
    if own.get("program"):
        return f" You are in {own['program']}."
    return ""


def r_denied(a, t):
    return REFUSALS.get(a.get("reason"), "I can't share that; it is private.") + _own_answer(a.get("own_answer") or {})


def r_missing(a, t):
    slot, status, note = a.get("slot"), a.get("status"), a.get("note")
    res = (t.resolved or {}).get(slot) or {}
    if status == "ambiguous" and res.get("candidates"):
        return f"I found more than one match: {fmt_list(str(c) for c in res['candidates'])}. Please ask again and say which one you mean."
    lead = ""
    if status == "not_found" and note:
        lead = note[0].upper() + note[1:] + ". "
        lead = re.sub(r"^No ", "I found no ", lead)
        lead = re.sub(r"^Cannot read a term in (.*)\. $", r"I could not read a term in \1. ", lead)
    return lead + SLOT_QUESTION.get(slot, "Please ask again with a little more detail.")


MULTI_REQUEST = " You asked more than one thing; I handle one request per message, so please ask the rest separately."


def render(t: Trace) -> str:
    return _render_one(t) + (MULTI_REQUEST if getattr(t, "multi_request", False) else "")


def _render_one(t: Trace) -> str:
    a = t.answer
    if a is None:
        return "I couldn't complete that lookup. Please try again."
    if a.get("allowed") is False:
        return r_denied(a, t)
    if a.get("error") == "missing_slot":
        return r_missing(a, t)
    writer = WRITERS.get(t.intent or "", r_unknown)
    try:
        return writer(a, t)
    except (KeyError, TypeError, ValueError) as e:      # a shape the writer does not know: a fixed sentence, the detail goes to the trace
        t.error = t.error or f"renderer: {type(e).__name__}: {e}"
        return "I found an answer but couldn't put it into words. Please try again or rephrase."


# ---------------------------------------------------------------------------------------------------------------------------------
# the LLM rendering, kept for comparison (mode="llm")
# ---------------------------------------------------------------------------------------------------------------------------------
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
    if isinstance(v, dict):
        return {k: _format(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_format(x, key) for x in v]
    if isinstance(v, (datetime, date)):
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
    return _format({k: v for k, v in answer.items() if k != "target"})


def _leaks(reply: str, answer: dict) -> bool:
    if answer.get("allowed") is not False:
        return False
    target = answer.get("target") or {}
    ids = [target.get("university_id")] + list(target.get("university_ids") or [])
    return any(i and str(i) in reply for i in ids)


def write_reply(llm: Client | None, t: Trace, mode: str = "render") -> str:
    """Fill t.reply and t.timings['reply_s']. mode 'render' (default) is deterministic; 'llm' is the old model call with the
    deterministic text as its fallback."""
    t0 = time.perf_counter()
    rendered = render(t)
    reply = rendered
    if mode == "llm" and llm is not None and t.answer is not None:
        try:
            user = f"Question: {t.question}\nFacts: {json.dumps(facts_for_model(t.answer), ensure_ascii=False)}\nReply:"
            res = llm.complete(SYSTEM, user, max_tokens=220)
            cand = " ".join(res.content.split()).strip()
            if cand and not _leaks(cand, t.answer):
                reply = cand
        except LLMError:
            pass
    t.reply = reply
    t.timings["reply_s"] = round(time.perf_counter() - t0, 3)
    return reply
