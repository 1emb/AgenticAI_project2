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
    "other_student_record": "I can't share another person's student record, or whether they have one.",
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
    "day": "Please ask again and name the weekday, or say 'today' or 'tomorrow'.",
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
    return num(v) if isinstance(v, (Decimal, float)) else v


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
    s = f"CRN {a['crn']} ({a['course']}, {a['term']}) has a capacity of {a['capacity']} seats"
    if a.get("enrolled") is None:
        return s + "."
    s += f"; {a['enrolled']} {'is' if a['enrolled'] == 1 else 'are'} taken and {a['seats_left']} {'is' if a['seats_left'] == 1 else 'are'} left."
    if a.get("is_cancelled"):
        s += " The section is cancelled."
    elif a.get("is_full"):
        s += " It is full."
    return s


# ---- own record (enrollment, 2026-11-02) ----
def _meeting(days, start, end, room) -> str:
    s = f"{_days(days)} {_t(start)}-{_t(end)}" if days and start else "time not listed"
    return s + (f" in {room}" if room else "")


def _mine(sec: dict) -> str:
    s = f"{sec['course']}" + (f" {sec['title']}" if sec.get("title") else "") + f" (CRN {sec['crn']}" + (f", {_n(sec['credit_hours'])} cr)" if sec.get("credit_hours") is not None else ")")
    s += ", " + _meeting(sec.get("days"), sec.get("start"), sec.get("end"), sec.get("room"))
    return s + (f" with {sec['instructor']}" if sec.get("instructor") else "")


def r_my_schedule(a, t):
    verb = {"past": "took", "current": "are enrolled in", "future": "are registered for"}.get(a.get("when"), "are enrolled in")
    if "day" in a:
        if not a.get("has_classes"):
            return f"You have no classes on {a['day']}s in {a['term']}."
        items = "; ".join(f"{m['course']} (CRN {m['crn']}) {_t(m['start'])}-{_t(m['end'])}" + (f" in {m['room']}" if m.get("room") else "") for m in a["meetings"])
        return f"On {a['day']}s in {a['term']} you have {items}."
    secs = a.get("sections") or []
    if not secs:
        return f"You have no sections on record for {a['term']}."
    n = len(secs)
    return f"In {a['term']} you {verb} {n} section{'s' if n != 1 else ''} ({_n(a['credits'])} credits): " + "; ".join(_mine(x) for x in secs) + "."


REASON_TEXT = {
    "status_not_active": "your registrar status is {status}, so you cannot register",
    "registration_not_open": "registration for {term} has not opened yet (it opens {opens})",
    "registration_closed": "registration for {term} closed on {deadline}",
    "not_offered": "{what} has no open section in {term}",
    "prerequisites_not_met": "you have not met its prerequisites (still needed: {missing})",
    "already_completed": "you have already completed {course} (grade {grade}), and a course passed with C or better cannot be repeated",
    "already_enrolled": "you are already enrolled in {course} in {term} (CRN {enrolled})",
    "no_seats": "every section is full",
    "time_clash": "every section with seats left overlaps your other classes that term",
}
NOT_A_REGISTRATION = " This is a check of the registration rules, not a registration."


def r_can_register(a, t):
    what = f"CRN {a['crn']} ({a['course']})" if a.get("crn") else a["course"]
    if a["eligible"]:
        open_secs = [x for x in a.get("sections") or [] if x["seats_left"] > 0 and not x["clash"]]
        s = f"Yes, you can register for {what} in {a['term']}: registration is open, you meet the prerequisites, and seats are left"
        s += " in " + fmt_list(f"CRN {x['crn']} ({x['seats_left']})" for x in open_secs) + "." if open_secs else "."
        if a.get("prerequisites_in_progress"):
            s += " Your prerequisites are met through courses still in progress, so they must be passed first."
        return s + NOT_A_REGISTRATION
    missing = " and ".join(" or ".join(g) for g in a.get("missing_prerequisites") or []) or "see the catalog"
    fields = dict(status=_status(a.get("status")), term=a["term"], opens=_d(a.get("registration_opens")), deadline=_d(a.get("add_deadline")), what=what,
                  course=a["course"], missing=missing, grade=a.get("best_grade") or "passing grade", enrolled=", ".join(a.get("enrolled_crns") or []))
    reasons = [REASON_TEXT.get(code, code).format(**fields) for code in a.get("reasons") or []]
    return f"No, you cannot register for {what} in {a['term']}: " + "; ".join(reasons) + "." + NOT_A_REGISTRATION


def _grade_word(c: dict) -> str:
    if c.get("grade"):
        return c["grade"]
    return "in progress" if c.get("status") == "enrolled" else "no grade"


def r_my_transcript(a, t):
    if "attempts" in a:
        code = a["course"]
        if not a.get("taken"):
            return f"{code} is not on your record."
        parts = (["accepted as transfer credit"] if a.get("transfer_credit") else []) + [f"{x['term']}: {_grade_word(x)}" for x in a["attempts"]]
        return f"{code} on your record: " + "; ".join(parts) + "."
    if "courses" in a:
        if not a["courses"]:
            return f"You have no courses on record for {a['term']}."
        s = f"Your {a['term']} record: " + fmt_list(f"{c['course']} {_grade_word(c)}" for c in a["courses"]) + "."
        if a.get("term_gpa") is not None:
            s += f" Term GPA {a['term_gpa']:.2f}."
        elif a.get("in_progress"):
            s += " Grades are not posted yet."
        return s
    terms = a.get("terms") or []
    if not terms and not a.get("transfer_credits"):
        return "You have no courses on your record yet."
    s = "Your transcript. " + " ".join(f"{x['term']}: " + ", ".join(f"{c['course']} {_grade_word(c)}" for c in x["courses"]) + "." for x in terms)
    if a.get("transfer_credits"):
        s += " Transfer credit: " + fmt_list(c["course"] for c in a["transfer_credits"]) + f" ({_n(sum(c['credit_hours'] for c in a['transfer_credits']))} credits)."
    s += f" Credits earned: {_n(a['credits_earned'])}."
    return s + (f" Cumulative GPA: {a['gpa']:.2f}." if a.get("gpa") is not None else " No GPA yet.")


def r_my_gpa(a, t):
    cum = f"Your cumulative GPA is {a['gpa']:.2f} over {_n(a['graded_credits'])} graded credits" if a.get("gpa") is not None else "You have no graded credits yet, so no GPA is on record"
    if "term" in a:
        if a.get("term_gpa") is None:
            why = " yet; its courses are still in progress" if a.get("in_progress") else "" if a.get("has_rows") else "; nothing is on record for that term"
            return f"You have no graded credits in {a['term']}{why}. {cum}."
        return f"Your {a['term']} GPA is {a['term_gpa']:.2f} over {_n(a['term_graded_credits'])} graded credits. {cum}."
    s = cum + f". You have earned {_n(a['credits_earned'])} credits"
    return s + (f", including {_n(a['transfer_credits'])} transfer credits." if a.get("transfer_credits") else ".")


def r_degree_progress(a, t):
    s = f"Toward the {_prog(a)} you have earned {_n(a['credits_earned'])} of {_n(a['credits_required'])} credits ({_n(a['credits_remaining'])} remaining)."
    rem = a.get("required_remaining") or []
    prog = a.get("in_progress") or []
    if rem and set(rem) == set(prog):
        s += f" Required courses still to pass: {fmt_list(rem)}, in progress now."
    elif rem:
        s += f" Required courses still to pass: {fmt_list(rem)}." + (f" You are taking {fmt_list(prog)} now." if prog else "")
    else:
        s += " Every required course is passed."
    cats = a.get("categories") or {}
    if cats:
        s += " " + fmt_list(f"{k.replace('_', ' ')}: {_n(v['earned'])} of {_n(v['required'])} credits" for k, v in cats.items()) + "."
    s += f" Your GPA is {a['gpa']:.2f} against a program minimum of {a['min_gpa']:.2f}." if a.get("gpa") is not None else " You have no GPA yet."
    return s + (" Every requirement is met." if a.get("complete") else "")


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
    if not a["in_plan"]:    # policy sentence (owner, 2026-11-02): nothing behind it is looked up
        return f"{a['course']} is not listed in the {prog} degree plan. Courses outside the plan need an advisor's approval to count as electives."
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
    "my_schedule": r_my_schedule, "can_register": r_can_register, "my_transcript": r_my_transcript, "my_gpa": r_my_gpa, "degree_progress": r_degree_progress,
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
