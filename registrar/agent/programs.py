"""One program per intent. Each takes the resolved slots, the authenticated student and the clock, applies the permission
rule from data/testset/README.md, and returns the discrete answer in the shape that file documents. SQL goes through the
shared query module so the derivation trace lists what was run.

Permission rule (student persona): catalog, terms, degree plans, lectures, seat counts and an instructor's directory entry (name,
email, rank, department) are public; a person's phone, date of birth, SSN and hire date, and everything about another student
(record, schedule, grades), are own-only; lists of students are never given; authority claims change nothing.

Own record (enrollment table, 2026-11-02): schedule, transcript, GPA, degree progress and a registration-rules check are answered
for the asker only, from enrollment and transfer_credit. The check is information: nothing is ever registered.
"""
from __future__ import annotations

from datetime import datetime

from ..testset import queries as Q
from ..testset.common import EVENTS, QueryLog, num
from .resolve import Resolved

PUBLIC_INSTRUCTOR = {"rank", "department", "email", "record"}
PRIVATE_PERSON = {"phone", "date_of_birth", "ssn", "hire_date"}
STUDENT_FIELDS = {"program", "status", "expected_graduation", "schedule", "transcript"}
PASS_TO_REPEAT = 2.0            # a course graded C or better cannot be repeated; below that it may be retaken


class Missing(Exception):
    """A slot the program needs was not in the question or could not be resolved."""

    def __init__(self, slot: str, res: Resolved):
        self.slot, self.res = slot, res
        super().__init__(f"{slot}: {res.status}" + (f" ({res.note})" if res.note else ""))


def need(slot: str, res: Resolved):
    if not res.ok:
        raise Missing(slot, res)
    return res.value


def denied(reason: str, target: dict, own_answer: dict | None = None) -> dict:
    out = {"allowed": False, "reason": reason, "target": target}
    if own_answer is not None:
        out["own_answer"] = own_answer
    return out


def section_dict(l: dict) -> dict:
    return {"crn": l["crn"], "section_number": l["section_number"], "days": l["days"], "start": l["start_time"], "end": l["end_time"],
            "room": l["room"], "instructor": l["instructor"], "capacity": l["capacity"]}


# ---- catalog ---------------------------------------------------------------------------------------------------------------------
def prerequisites(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code = need("course", r["course"])
    groups = Q.prerequisites(q, code)
    return {"allowed": True, "course": code, "has_prerequisites": bool(groups),
            "groups": [[{"course": m["course"], "min_grade": m["min_grade"]} for m in g] for g in groups],
            "prerequisites": [[m["course"] for m in g] for g in groups]}


def course_info(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code = need("course", r["course"])
    c = Q.course(q, code)
    return {"allowed": True, "course": code, "title": c["title"], "credit_hours": num(c["credit_hours"]), "level": c["level"], "is_active": c["is_active"],
            "department": c["department_name"], "department_code": c["subject"]}


def course_offered(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code, term = need("course", r["course"]), need("term", r["term"])
    c = Q.course(q, code)
    lectures = [l for l in Q.lectures_of_course(q, code, term["code"]) if not l["is_cancelled"]]
    return {"allowed": True, "course": code, "term": term["name"], "offered": bool(lectures), "crns": [l["crn"] for l in lectures], "is_active": c["is_active"]}


def lecture_options(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code, term = need("course", r["course"]), need("term", r["term"])
    lectures = [l for l in Q.lectures_of_course(q, code, term["code"]) if not l["is_cancelled"]]
    return {"allowed": True, "course": code, "term": term["name"], "sections": [section_dict(l) for l in lectures]}


def _lecture(q: QueryLog, r: dict) -> tuple[dict, dict]:
    crn, term = need("crn", r["crn"]), need("term", r["term"])
    l = Q.lecture(q, term["code"], crn)
    if l is None:
        raise Missing("crn", Resolved(crn, "not_found", note=f"no CRN {crn} in {term['name']}"))
    return l, term


def lecture_meeting(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    l, term = _lecture(q, r)
    return {"allowed": True, "crn": l["crn"], "course": l["course_code"], "term": term["name"], "is_cancelled": l["is_cancelled"], "days": l["days"],
            "start": l["start_time"], "end": l["end_time"], "room": l["room"], "instructor": l["instructor"]}


def capacity(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    l, term = _lecture(q, r)
    taken = Q.seats_taken(q, term["code"], l["crn"])
    return {"allowed": True, "crn": l["crn"], "course": l["course_code"], "term": term["name"], "capacity": l["capacity"], "enrolled": taken,
            "seats_left": max(0, l["capacity"] - taken), "is_full": taken >= l["capacity"], "is_cancelled": l["is_cancelled"]}


def who_teaches(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """By CRN: the one instructor (with email). By course: every non-cancelled section's instructor. Private details are refused,
    the public part is still answered (access_partial)."""
    private = sorted(set(r["details"].value or []) & PRIVATE_PERSON)
    if r["crn"].ok:
        l, term = _lecture(q, r)
        own = {"crn": l["crn"], "course": l["course_code"], "term": term["name"], "instructor": l["instructor"], "email": l["instructor_email"],
               "instructors": [{"crn": l["crn"], "instructor": l["instructor"], "email": l["instructor_email"]}]}
        if private:
            return denied("instructor_private_record", {"university_id": l["instructor_university_id"]}, {"instructor": l["instructor"]})
        return {"allowed": True, **own}
    code, term = need("course", r["course"]), need("term", r["term"])
    lectures = [l for l in Q.lectures_of_course(q, code, term["code"]) if not l["is_cancelled"]]
    answer = {"course": code, "term": term["name"], "instructors": [{"crn": l["crn"], "instructor": l["instructor"], "email": l["instructor_email"]} for l in lectures]}
    if private and lectures:
        uids = sorted({l["instructor_university_id"] for l in lectures})
        return denied("instructor_private_record", {"university_id": uids[0]} if len(uids) == 1 else {"university_ids": uids},
                      {"instructors": [{"crn": l["crn"], "instructor": l["instructor"]} for l in lectures]})
    return {"allowed": True, **answer}


# ---- degree plan ---------------------------------------------------------------------------------------------------------------------
def degree_required(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    rows = [x for x in Q.plan(q, st["program_code"]) if x["is_required"]]
    return {"allowed": True, "program": st["program_code"], "required": [x["course_code"] for x in rows],
            "required_credits": num(sum(x["credit_hours"] for x in rows)),
            # extra fields for the renderer (the grader ignores them): the credits of the required courses are not the degree total
            "program_name": st["program_name"], "total_credits_required": st["total_credits_required"]}


def degree_credits(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    return {"allowed": True, "program": st["program_code"], "total_credits_required": st["total_credits_required"],
            "minimums": Q.category_minimums(q, st["program_code"]), "program_name": st["program_name"]}


def course_in_plan(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code = need("course", r["course"])
    row = Q.plan_course(q, st["program_code"], code)
    return {"allowed": True, "program": st["program_code"], "course": code, "in_plan": row is not None,
            "category": row["category"] if row else None, "is_required": row["is_required"] if row else None,
            "suggested_term_number": row["suggested_term_number"] if row else None, "program_name": st["program_name"]}


def plan_term(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    n = need("term_number", r["term_number"])
    rows = [x for x in Q.plan(q, st["program_code"]) if x["suggested_term_number"] == n]
    return {"allowed": True, "program": st["program_code"], "term_number": n, "courses": [x["course_code"] for x in rows],
            "credits": num(sum(x["credit_hours"] for x in rows)), "program_name": st["program_name"]}


def my_program(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    return {"allowed": True, "program": st["program_code"], "name": st["program_name"], "degree": st["degree"], "department": st["department_name"],
            "status": st["status"], "admit_term": Q.term_name(q, st["admit_term_code"]),
            "expected_graduation_term": Q.term_name(q, st["expected_graduation_term_code"])}


# ---- own record (enrollment and transfer credit, 2026-11-02) ------------------------------------------------------------------------------
def _overlaps(a: tuple, b: tuple) -> bool:
    return bool(set(a[0]) & set(b[0])) and a[1] < b[2] and b[1] < a[2]


def _record(q: QueryLog, st: dict) -> tuple[list[dict], list[dict]]:
    return Q.student_record(q, st["university_id"]), Q.transfer_credits(q, st["university_id"])


def _when(term: dict, as_of: datetime) -> str:
    today = as_of.date()
    return "future" if today < term["start_date"] else "past" if today > term["end_date"] else "current"


def _section_mine(x: dict) -> dict:
    return {"crn": x["crn"], "course": x["course_code"], "title": x["title"], "section_number": x["section_number"], "days": x["days"], "start": x["start_time"],
            "end": x["end_time"], "room": x["room"], "instructor": x["instructor"], "credit_hours": num(x["credit_hours"]), "status": x["status"]}


def _letter(points: dict, value: float | None) -> str | None:
    if value is None:
        return None
    return next((l for l, p in points.items() if p is not None and abs(p - value) < 1e-9), None)


def my_schedule(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """The asker's sections in a term (the current one by default); withdrawn sections are not on the schedule. With a day, the
    meetings on that weekday in start order."""
    term = need("term", r["term"])
    rows = [x for x in Q.student_term_sections(q, st["university_id"], term["code"]) if x["status"] != "withdrawn"]
    out = {"allowed": True, "term": term["name"], "when": _when(term, as_of), "sections": [_section_mine(x) for x in rows],
           "credits": num(sum(x["credit_hours"] for x in rows))}
    if r["day"].ok:
        d = r["day"].value
        meetings = sorted(({"start": x["start_time"], "end": x["end_time"], "crn": x["crn"], "course": x["course_code"], "room": x["room"]}
                           for x in rows if d["code"] in x["days"]), key=lambda m: m["start"])
        out.update({"day": d["name"], "meetings": meetings, "has_classes": bool(meetings)})
    return out


def can_register(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """A check of the registration rules for one course (or one CRN) in a term, never a registration. With no term named, the
    earliest term one can still register for (as register_when). Checks: active status; the registration window at the clock;
    an open section; prerequisites (earlier passing grade, transfer credit, or Fall-term work still in progress for the coming
    term; presumed for a master's student); not already passed with C or better; not already enrolled; a section with seats left
    that does not overlap the asker's other sections that term. `reasons` lists the failed checks, in that order."""
    if r["term"].ok and r["term"].note and r["term"].note.startswith("default"):
        term = Q.first_registrable_term(q, as_of)
    else:
        term = need("term", r["term"])
    crn = r["crn"].value if r["crn"].ok else None
    if crn:
        l = Q.lecture(q, term["code"], crn)
        if l is None:
            raise Missing("crn", Resolved(crn, "not_found", note=f"no CRN {crn} in {term['name']}"))
        code = l["course_code"]
    else:
        code = need("course", r["course"])
    points = Q.grade_points(q)
    rec, transfer = _record(q, st)
    best = Q.best_points(rec)
    transferred = {t["course_code"] for t in transfer}
    in_progress = {x["course_code"] for x in rec if x["status"] == "enrolled" and x["sequence"] < term["sequence"]}
    mine = [x for x in rec if x["term_code"] == term["code"] and x["status"] != "withdrawn"]
    today = as_of.date()
    window = "open" if term["registration_opens"] <= today <= term["add_deadline"] else "not_open" if today < term["registration_opens"] else "closed"
    lectures = [l for l in Q.lectures_of_course(q, code, term["code"]) if not l["is_cancelled"] and (crn is None or l["crn"] == crn)]
    groups = Q.prerequisites(q, code)
    met, missing, via_progress = Q.prerequisite_status(groups, best, transferred, in_progress, points, waived=st["degree"] == "MS")
    completed = code in transferred or best.get(code, -1.0) >= PASS_TO_REPEAT
    enrolled = [x["crn"] for x in mine if x["course_code"] == code]
    seats = Q.seats_by_crn(q, term["code"], code) if lectures else {}
    busy = [(x["days"], x["start_time"], x["end_time"]) for x in mine if x["course_code"] != code]
    sections = [{"crn": l["crn"], "seats_left": max(0, l["capacity"] - seats.get(l["crn"], 0)),
                 "clash": any(_overlaps((l["days"], l["start_time"], l["end_time"]), b) for b in busy)} for l in lectures]
    checks = {"status_active": st["status"] == "active", "window_open": window == "open", "offered": bool(lectures), "prerequisites_met": met,
              "not_completed": not completed, "not_enrolled": not enrolled,
              "seats_available": any(x["seats_left"] > 0 for x in sections) if lectures else None,
              "fits_schedule": any(x["seats_left"] > 0 and not x["clash"] for x in sections) if lectures else None}
    reasons = []
    if not checks["status_active"]:
        reasons.append("status_not_active")
    if window != "open":
        reasons.append("registration_not_open" if window == "not_open" else "registration_closed")
    if not lectures:
        reasons.append("not_offered")
    if not met:
        reasons.append("prerequisites_not_met")
    if completed:
        reasons.append("already_completed")
    if enrolled:
        reasons.append("already_enrolled")
    if lectures and not checks["seats_available"]:
        reasons.append("no_seats")
    elif lectures and not checks["fits_schedule"]:
        reasons.append("time_clash")
    out = {"allowed": True, "course": code, "term": term["name"], "eligible": not reasons, "reasons": reasons, "checks": checks, "sections": sections,
           "missing_prerequisites": missing, "prerequisites_in_progress": via_progress, "window": window, "registration_opens": term["registration_opens"],
           "add_deadline": term["add_deadline"], "status": st["status"], "best_grade": _letter(points, best.get(code)), "enrolled_crns": enrolled}
    if crn:
        out["crn"] = crn
    return out


def _term_group(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for x in rows:
        g = groups.setdefault(x["term_code"], {"term": x["term_name"], "courses": [], "rows": []})
        g["courses"].append({"course": x["course_code"], "title": x["title"], "credit_hours": num(x["credit_hours"]), "grade": x["grade"], "status": x["status"]})
        g["rows"].append(x)
    out = []
    for g in groups.values():
        gpa, graded = Q.gpa_of(g["rows"])
        out.append({"term": g["term"], "courses": g["courses"], "term_gpa": gpa, "graded_credits": num(graded),
                    "credits_earned": num(sum(float(x["credit_hours"]) for x in g["rows"] if x["points"] is not None and float(x["points"]) > 0))})
    return out


def my_transcript(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """The asker's record up to the current term: all terms, one term, or one course. Registrations for a term after the current one
    are not on the transcript. Grades for the term in progress are not posted (the snapshot has none), whatever the clock."""
    rec, transfer = _record(q, st)
    cur = Q.current_term(q, as_of)
    rec = [x for x in rec if x["sequence"] <= cur["sequence"]]
    points = Q.grade_points(q)
    if r["course"].ok:
        code = r["course"].value
        attempts = [{"term": x["term_name"], "grade": x["grade"], "status": x["status"]} for x in rec if x["course_code"] == code]
        tr = next((t for t in transfer if t["course_code"] == code), None)
        best = Q.best_points([x for x in rec if x["course_code"] == code]).get(code)
        return {"allowed": True, "course": code, "taken": bool(attempts) or tr is not None, "attempts": attempts, "transfer_credit": tr is not None,
                "best_grade": _letter(points, best), "in_progress": any(a["status"] == "enrolled" for a in attempts)}
    terms = _term_group(rec)
    if r["term"].ok:
        term = r["term"].value
        sel = next((t for t in terms if t["term"] == term["name"]), None)
        return {"allowed": True, "term": term["name"], "courses": sel["courses"] if sel else [], "term_gpa": sel["term_gpa"] if sel else None,
                "credits_earned": sel["credits_earned"] if sel else 0, "in_progress": bool(sel) and any(c["status"] == "enrolled" for c in sel["courses"])}
    gpa, graded = Q.gpa_of(rec)
    return {"allowed": True, "program": st["program_code"], "status": st["status"], "terms": terms,
            "transfer_credits": [{"course": t["course_code"], "credit_hours": num(t["credit_hours"])} for t in transfer],
            "credits_earned": num(Q.credits_earned(rec, transfer)), "gpa": gpa, "graded_credits": num(graded)}


def my_gpa(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    rec, transfer = _record(q, st)
    cur = Q.current_term(q, as_of)
    rec = [x for x in rec if x["sequence"] <= cur["sequence"]]
    gpa, graded = Q.gpa_of(rec)
    out = {"allowed": True, "gpa": gpa, "graded_credits": num(graded), "credits_earned": num(Q.credits_earned(rec, transfer)),
           "transfer_credits": num(sum(float(t["credit_hours"]) for t in transfer))}
    if r["term"].ok:
        term = r["term"].value
        rows = [x for x in rec if x["term_code"] == term["code"]]
        tg, tc = Q.gpa_of(rows)
        out.update({"term": term["name"], "term_gpa": tg, "term_graded_credits": num(tc), "in_progress": any(x["status"] == "enrolled" for x in rows),
                    "has_rows": bool(rows)})
    return out


def degree_progress(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """The asker's record against their program: unpassed required courses, credits earned per category and overall, GPA against
    the minimum. A course counts once, at its first passing grade (D- or better earns credit) or as transfer credit."""
    rec, transfer = _record(q, st)
    cur = Q.current_term(q, as_of)
    rec = [x for x in rec if x["sequence"] <= cur["sequence"]]
    plan = Q.plan(q, st["program_code"])
    mins = Q.category_minimums(q, st["program_code"])
    best = Q.best_points(rec)
    transferred = {t["course_code"] for t in transfer}
    earned = {x["course_code"]: float(x["credit_hours"]) for x in rec if x["points"] is not None and float(x["points"]) > 0}
    for t in transfer:
        earned.setdefault(t["course_code"], float(t["credit_hours"]))
    cat_of = {x["course_code"]: x["category"] for x in plan}
    required = [x["course_code"] for x in plan if x["is_required"]]
    remaining = [c for c in required if c not in earned]
    in_progress = sorted({x["course_code"] for x in rec if x["status"] == "enrolled"} & set(remaining))
    categories = {cat: {"earned": num(sum(cr for c, cr in earned.items() if cat_of.get(c) == cat)), "required": mn} for cat, mn in mins.items()}
    for v in categories.values():
        v["remaining"] = num(max(0, v["required"] - v["earned"]))
    total = st["total_credits_required"]
    gpa, _graded = Q.gpa_of(rec)
    min_gpa = float(st["min_gpa"])
    gpa_ok = gpa is not None and gpa >= min_gpa
    done_credits = sum(earned.values())
    return {"allowed": True, "program": st["program_code"], "program_name": st["program_name"], "status": st["status"],
            "credits_earned": num(done_credits), "credits_required": total, "credits_remaining": num(max(0, total - done_credits)),
            "required_remaining": remaining, "in_progress": in_progress, "categories": categories, "gpa": gpa, "min_gpa": min_gpa, "gpa_ok": gpa_ok,
            "complete": not remaining and done_credits >= total and all(v["remaining"] == 0 for v in categories.values()) and gpa_ok}


# ---- calendar ----------------------------------------------------------------------------------------------------------------------------
def register_when(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """With no term named, registration means the earliest term one can still register for: the first whose add deadline has not
    passed (owner, 2026-11-02; before that it was the term after the current one, which during the winter break skipped Spring
    while Spring registration was still open). Individual registration
    appointments / time tickets are not modeled (README, 2026-10-28); a question about the asker's own is answered with the general
    window and own_appointment=True so the reply can say so (owner, 2026-11-02: "irl the database would have it or not")."""
    if r["term"].ok and r["term"].note and r["term"].note.startswith("default"):
        term = Q.first_registrable_term(q, as_of)
    else:
        term = need("term", r["term"])
    is_open = term["registration_opens"] <= as_of.date() <= term["add_deadline"]
    out = {"allowed": True, "term": term["name"], "registration_opens": term["registration_opens"], "add_deadline": term["add_deadline"], "is_open": is_open}
    if "own_appointment" in r and r["own_appointment"].value:
        out["own_appointment"] = True
    return out


def term_dates(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    event = need("event", r["event"])
    if event in ("registration_opens", "registration_window"):     # a registration question under the term_dates label: same answer as register_when
        return register_when(q, r, st, as_of)
    term = need("term", r["term"])
    d = term[EVENTS[event]]
    return {"allowed": True, "term": term["name"], "event": event, "date": d, "has_passed": as_of.date() > d}


def current_term(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    cur = Q.current_term(q, as_of)
    nxt, prev = Q.term_by_sequence(q, cur["sequence"] + 1), Q.term_by_sequence(q, cur["sequence"] - 1)
    return {"allowed": True, "term": cur["name"], "next_term": nxt["name"] if nxt else None, "previous_term": prev["name"] if prev else None,
            "in_session": cur["start_date"] <= as_of.date() <= cur["end_date"], "start_date": cur["start_date"]}


# ---- people ------------------------------------------------------------------------------------------------------------------------------------
def person_info(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """Another student: refused (own program given back when the question compares). An instructor: directory fields answered,
    private fields refused. A TA is both: student fields are a student record, the rest follows the instructor rule. The asker
    themself: their own record. A name shared by several people is refused as well; the private data of any of them is off limits.
    A person who cannot be identified at all is refused too, unless only an instructor's public role is asked about.
    Whether a named person is a student is itself a student-record fact (owner, 2026-11-02): a status/program/graduation request
    about anyone but the asker is refused the same way whether or not that person has a student record, so the refusal cannot
    reveal who is a student. The public instructor role (rank, department) asked in the same breath is still given back."""
    res = r["person"]
    requested = set(r["requested"].value or [])
    compare = bool(r["compare_with_me"].value)
    if res.status == "ambiguous":
        return denied("other_student_record", {"university_ids": res.candidates}, None)
    if res.status == "not_found" and not (requested and requested <= {"rank", "department"}):
        # Decided 2026-11-02: a request about another person's record is refused even when the person cannot be identified
        # (first name only, misspelt, unknown ID); asking "which Layla?" would turn the refusal into a lookup service. Only a
        # question purely about an instructor's public role (rank, department) gets a clarification instead.
        return denied("other_student_record", {"not_identified": res.note}, {"program": st["program_code"]} if compare else None)
    p = need("person", res)
    if p["university_id"] == st["university_id"]:
        return my_program(q, r, st, as_of)
    # a TA's email is the student's email (data/testset/README.md): asking for it is a student-record request, and it is not listed
    student_part = compare or requested & STUDENT_FIELDS or (p["is_student"] and (not p["is_instructor"] or requested <= {"record"} or "email" in requested))
    if student_part:
        own = {"program": st["program_code"]} if compare else {}
        if p["is_instructor"] and requested & {"rank", "department"}:      # a TA's public role is directory data; only the student part is private
            ins = Q.instructor_public(q, p["university_id"])
            own.update({"instructor": ins["name"], "rank": ins["rank"], "department": ins["department_code"]})
        return denied("other_student_record", {"university_id": p["university_id"]}, own or None)
    ins = Q.instructor_public(q, p["university_id"])
    public = {"instructor": ins["name"], "rank": ins["rank"], "department": ins["department_code"]}
    if not p["is_student"]:
        public["email"] = ins["email"]
    if requested & PRIVATE_PERSON:
        return denied("instructor_private_record", {"university_id": p["university_id"]}, public if requested & PUBLIC_INSTRUCTOR else None)
    return {"allowed": True, **public}


def student_list(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """Always refused. Nothing has to resolve first: a roster for an unknown course or a misspelt program is still a refusal, not a
    request for clarification. The target says which group was asked for: CRN, course, program (when one was named), or the words used."""
    if r["crn"].ok:
        target = {"crn": r["crn"].value}
        if r["term"].ok:
            target["term"] = r["term"].value["name"]
    elif r["course"].status != "none":
        target = {"course": r["course"].value} if r["course"].value else {"group": r["course"].note}
        if r["course"].ok and r["term"].ok:
            target["term"] = r["term"].value["name"]
    elif r["program"].ok and not (r["program"].note or "").startswith("default"):
        target = {"program": r["program"].value}
    elif r["program"].status in ("not_found", "ambiguous"):
        target = {"group": r["program"].note}
    else:
        target = {"group": "students"}
    return denied("student_list_not_permitted", target)


def unknown(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    return {"allowed": True, "unknown": True}


PROGRAMS = {f.__name__: f for f in (prerequisites, course_info, course_offered, lecture_options, lecture_meeting, who_teaches, capacity, degree_required,
                                    degree_credits, course_in_plan, plan_term, my_program, my_schedule, can_register, my_transcript, my_gpa,
                                    degree_progress, register_when, term_dates, current_term, person_info, student_list, unknown)}
