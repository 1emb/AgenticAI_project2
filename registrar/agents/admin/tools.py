"""Tools the Administrator agent can call (role: registrar administrator; may see student records and reports).

Answer shapes follow data/testset/administrator/questions.md where the current schema can support them, with these
adaptations (no college, gen-ed area, waitlist, override, hold or graduation-application data exists):
  - scope kinds: all, course, subject, level, program (students' program)
  - graduation: `graduation_candidates` = active students who meet every requirement once their courses in
    progress are passed (the advising validator decides), instead of graduation applications
  - standing: probation = most recent graded term GPA below the program minimum (handbook 4.1/4.2);
    at_risk_of_suspension = active, on probation for >= 2 consecutive graded terms (params.json)
Every computation is Python over ORM rows; data/testset/administrator/ ground truth is computed separately in SQL.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from registrar.agents.calendar import Calendar, TermNotFound
from registrar.agents.common import ToolError, plain
from registrar.agents.policy import PolicyStore
from registrar.agents.student.tools import _fn, normalize_course
from registrar.models import (AcademicTerm, Course, Enrollment, GradeScale, Lecture, Person, Program, Student)

LETTERS = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F", "W", "I"]
SCOPES = ("all", "course", "subject", "level", "program")
STUDENT_LIST_CAP = 40
# Holds (or held) a seat. Ported 2026-11-11 to main's enrollment table, where a graded row is `completed`; on the
# branch this came from, a graded row stayed `enrolled`. Withdrawn and dropped rows hold no seat.
SEATED = ("enrolled", "completed")


def pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


class AdminTools:
    def __init__(self, session: Session, calendar: Calendar, policy: PolicyStore | None = None):
        self.s, self.cal = session, calendar
        self.policy = policy or PolicyStore()
        self.points = {g.letter: (None if g.points is None else float(g.points)) for g in session.scalars(select(GradeScale))}
        self.courses = {c.code: c for c in session.scalars(select(Course))}
        self.terms = {t.code: t for t in session.scalars(select(AcademicTerm))}
        self.students = {s.university_id: s for s in session.scalars(select(Student))}
        self.programs = {p.code: p for p in session.scalars(select(Program))}
        self.rows = list(session.scalars(select(Enrollment).where(Enrollment.status != "dropped")))

    def _program(self, program: str | None) -> str | None:
        """None for all programs; accepts a code (BSCS) or a name ("Computer Science"); rejects anything else."""
        text = str(program or "").strip()
        if text.lower() in ("", "all", "any", "none", "every", "all programs", "university", "null"):
            return None
        if text.upper() in self.programs:
            return text.upper()
        low = text.lower()
        named = [c for c, p in self.programs.items() if low == p.name.lower()]
        if not named:
            named = sorted((c for c, p in self.programs.items() if low in p.name.lower()),
                           key=lambda c: self.programs[c].degree != "BS")  # "computer science" -> the bachelor's
        if named:
            return named[0]
        raise ToolError(f"There is no program {text!r}; use BSCS, BSENG, MSCS or MSENG, or omit it for all.")

    # ================================================================ scope
    def _term(self, term: str | None):
        if term in (None, "", "all", "all terms", "overall"):
            return None
        try:
            return self.cal.resolve(term)
        except TermNotFound as e:
            raise ToolError(str(e)) from None

    def _scope(self, kind: str, value: str | None, term: str | None) -> tuple[dict, callable]:
        kind = (kind or "all").lower()
        if kind in ("section", "sections", "university", "everything"):
            kind = "all"  # "section" is a unit, not a scope (grading_extremes has unit=section)
        if kind not in SCOPES:
            raise ToolError(f"scope_kind must be one of {', '.join(SCOPES)}.")
        raw = str(value or "").strip()
        # A term passed as the scope value ("Fall 2025") is the term.
        if re.fullmatch(r"(?i)(fall|spring|summer)\s+\d{4}|(this|last|next)\s+(fall|spring|summer|semester|term)", raw):
            term = term if term not in (None, "", "all") else raw
            raw, value = "", None
        # A level word passed as the value ("lower-division") is the level scope.
        lvl = re.sub(r"[\s_-]+", " ", raw.lower()).replace(" courses", "").replace(" level", "").strip()
        if lvl in ("lower division", "lower", "upper division", "upper", "graduate", "grad"):
            kind, value = "level", {"lower division": "lower_division", "lower": "lower_division",
                                    "upper division": "upper_division", "upper": "upper_division",
                                    "graduate": "graduate", "grad": "graduate"}[lvl]
            raw = value
        # The value's shape settles a confused kind: a course code has a number, a subject code does not,
        # a program code is one of the programs.
        if raw.lower() in ("", "all", "any", "none", "every", "null"):
            kind, value = ("all", None) if kind in ("course", "subject", "all") else (kind, value)
        elif kind in ("all", "subject") and re.fullmatch(r"[A-Za-z]{2,5}\s*-?\s*\d{3,4}[A-Za-z]?", raw):
            kind = "course"
        elif kind in ("all", "course") and raw.upper() in self.programs:
            kind = "program"
        elif kind in ("all", "course") and raw.isalpha():
            kind = "subject"
        elif kind == "level":
            pass
        t = self._term(term)
        v = None
        if kind == "course":
            v = normalize_course(value)
            if v not in self.courses:
                raise ToolError(f"There is no course {v}.")
        elif kind == "subject":
            v = str(value or "").strip().upper()
            if not any(c.subject == v for c in self.courses.values()):
                raise ToolError(f"There is no subject {v}.")
        elif kind == "level":
            v = {"lower": "lower_division", "upper": "upper_division", "grad": "graduate"}.get(
                str(value or "").lower().split("_")[0].split(" ")[0].replace("-", ""), str(value or "").lower())
            if v not in ("lower_division", "upper_division", "graduate"):
                raise ToolError("level must be lower_division, upper_division or graduate.")
        elif kind == "program":
            v = self._program(value)
            if v is None:
                kind = "all"

        def match_course(course_code: str, student_uid: str | None = None) -> bool:
            c = self.courses[course_code]
            return (kind == "all" or (kind == "course" and c.code == v) or (kind == "subject" and c.subject == v)
                    or (kind == "level" and plain(c.level) == v)
                    or (kind == "program" and student_uid is not None
                        and self.students[student_uid].program_code == v))
        return {"kind": kind, "value": v, "term": t.name if t else None}, (match_course, t)

    def _graded(self, match, t) -> list[Enrollment]:
        out = []
        for e in self.rows:
            if e.grade is None or e.grade == "I":
                continue
            if t is not None and e.term_code != t.code:
                continue
            if match(e.course_code, e.student_university_id):
                out.append(e)
        return out

    # ================================================================ course-group statistics
    def grade_distribution(self, scope_kind: str = "all", scope_value: str | None = None,
                           term: str | None = None) -> dict:
        scope, (match, t) = self._scope(scope_kind, scope_value, term)
        rows = self._graded(match, t)
        counts = Counter(e.grade for e in rows)
        graded = len(rows)
        pts = [(self.points[e.grade], float(self.courses[e.course_code].credit_hours)) for e in rows
               if self.points[e.grade] is not None]
        cr = sum(c for _, c in pts)
        dfw = sum(counts[g] for g in ("D+", "D", "D-", "F", "W"))
        return {"answer": {"scope": scope, "available": graded > 0, "graded": graded,
                           "counts": {g: n for g, n in counts.items() if n}, "pct_a": pct(counts["A"], graded),
                           "pct_f": pct(counts["F"], graded), "pct_dfw": pct(dfw, graded),
                           "mean_gpa": round(sum(p * c for p, c in pts) / cr, 2) if cr else None},
                "note": "No posted grades yet in that scope." if not graded else
                        "graded counts letter grades and W (not I); pct_a counts A only."}

    def dfw_rate(self, scope_kind: str = "all", scope_value: str | None = None, term: str | None = None) -> dict:
        scope, (match, t) = self._scope(scope_kind, scope_value, term)
        rows = self._graded(match, t)
        c = Counter(e.grade for e in rows)
        d, f, w = c["D+"] + c["D"] + c["D-"], c["F"], c["W"]
        passed = sum(n for g, n in c.items() if (self.points[g] or 0) >= 1.7)
        return {"answer": {"scope": scope, "total": len(rows), "d": d, "f": f, "w": w,
                           "dfw_rate": pct(d + f + w, len(rows)), "pass_rate": pct(passed, len(rows))}}

    def grading_extremes(self, metric: str, direction: str = "highest", unit: str = "course",
                         scope_kind: str = "all", scope_value: str | None = None, term: str | None = None,
                         limit: int = 5) -> dict:
        if metric not in ("pct_a", "pct_f", "pct_dfw", "mean_gpa"):
            raise ToolError("metric must be pct_a, pct_f, pct_dfw or mean_gpa.")
        if unit not in ("course", "section"):
            raise ToolError("unit must be course or section.")
        scope, (match, t) = self._scope(scope_kind, scope_value, term)
        groups: dict[str, list[Enrollment]] = defaultdict(list)
        for e in self._graded(match, t):
            key = e.course_code if unit == "course" else (e.crn if t is not None else f"{e.term_code}:{e.crn}")
            groups[key].append(e)
        items = []
        for k, es in groups.items():
            if len(es) < 10:
                continue
            c = Counter(e.grade for e in es)
            if metric == "pct_a":
                val = pct(c["A"], len(es))
            elif metric == "pct_f":
                val = pct(c["F"], len(es))
            elif metric == "pct_dfw":
                val = pct(sum(c[g] for g in ("D+", "D", "D-", "F", "W")), len(es))
            else:
                ps = [(self.points[e.grade], float(self.courses[e.course_code].credit_hours)) for e in es
                      if self.points[e.grade] is not None]
                cr = sum(x for _, x in ps)
                val = round(sum(p * x for p, x in ps) / cr, 2) if cr else 0.0
            items.append({"key": k, "graded": len(es), "value": val})
        items.sort(key=lambda i: ((-i["value"]) if direction == "highest" else i["value"], i["key"]))
        return {"answer": {"scope": scope, "unit": unit, "metric": metric, "direction": direction, "min_graded": 10,
                           "items": items[:int(limit)]}}

    def withdrawals(self, scope_kind: str = "all", scope_value: str | None = None, term: str | None = None) -> dict:
        scope, (match, t) = self._scope(scope_kind, scope_value, term)
        started = [e for e in self.rows if (t is None or e.term_code == t.code)
                   and match(e.course_code, e.student_university_id)]
        w = [e for e in started if e.grade == "W"]
        top = sorted(Counter(e.course_code for e in w).items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        return {"answer": {"scope": scope, "withdrawn": len(w), "started": len(started), "rate": pct(len(w), len(started)),
                           "top_courses": [{"course": c, "withdrawn": n} for c, n in top]}}

    def enrollment_summary(self, scope_kind: str = "all", scope_value: str | None = None,
                           term: str | None = None) -> dict:
        t = self._term(term) or self.cal.current()
        scope, (match, _) = self._scope(scope_kind, scope_value, t.name)
        if scope["kind"] == "program":
            raise ToolError("enrollment_summary works on course scopes (all, course, subject, level).")
        lecs = [l for l in self.s.scalars(select(Lecture).where(Lecture.term_code == t.code, Lecture.is_cancelled.is_(False)))
                if match(l.course_code)]
        reg = Counter(e.crn for e in self.rows if e.term_code == t.code and e.status.value in SEATED)
        cap = sum(l.capacity for l in lecs)
        registered = sum(reg[l.crn] for l in lecs)
        return {"answer": {"scope": scope, "sections": len(lecs), "capacity": cap, "registered": registered,
                           "seats_left": cap - registered, "fill_rate": pct(registered, cap),
                           "full_sections": sum(1 for l in lecs if reg[l.crn] >= l.capacity)}}

    # ================================================================ student-group statistics
    def _term_gpas(self) -> dict[str, list[tuple[int, float]]]:
        """uid -> [(term sequence, term GPA)] over graded terms, in order."""
        acc: dict[tuple[str, str], list] = defaultdict(list)
        for e in self.rows:
            p = self.points.get(e.grade) if e.grade else None
            if p is None:
                continue
            acc[(e.student_university_id, e.term_code)].append((p, float(self.courses[e.course_code].credit_hours)))
        out: dict[str, list] = defaultdict(list)
        for (uid, tc), xs in acc.items():
            cr = sum(c for _, c in xs)
            out[uid].append((self.terms[tc].sequence, sum(p * c for p, c in xs) / cr))
        return {u: sorted(v) for u, v in out.items()}

    def _cum_gpa(self) -> dict[str, float]:
        acc: dict[str, list] = defaultdict(list)
        for e in self.rows:
            p = self.points.get(e.grade) if e.grade else None
            if p is not None:
                acc[e.student_university_id].append((p, float(self.courses[e.course_code].credit_hours)))
        return {u: round(sum(p * c for p, c in xs) / sum(c for _, c in xs), 2) for u, xs in acc.items()}

    def at_risk_students(self, criterion: str = "probation", program: str | None = None,
                         threshold: float | None = None) -> dict:
        if criterion not in ("probation", "at_risk_of_suspension", "gpa_below"):
            raise ToolError("criterion must be probation, at_risk_of_suspension or gpa_below.")
        need = int(self.policy.get_params()["at_risk_consecutive_probation_terms"])
        tg, cum = self._term_gpas(), self._cum_gpa()
        prog = self._program(program)
        hits = []
        for uid, st in self.students.items():
            if plain(st.status) != "active" or (prog and st.program_code != prog):
                continue
            mn = float(self.programs[st.program_code].min_gpa)
            streak = 0
            for _, g in reversed(tg.get(uid, [])):
                if g < mn - 1e-9:
                    streak += 1
                else:
                    break
            if criterion == "probation":
                ok = streak >= 1
            elif criterion == "at_risk_of_suspension":
                ok = streak >= need
            else:
                if threshold is None:
                    raise ToolError("gpa_below needs a threshold.")
                ok = uid in cum and cum[uid] < float(threshold)
            if ok:
                hits.append({"university_id": uid, "cumulative_gpa": cum.get(uid), "probation_terms": streak,
                             "program": st.program_code})
        hits.sort(key=lambda h: h["university_id"])
        return {"answer": {"scope": {"kind": "program" if prog else "all", "value": prog}, "criterion": criterion,
                           "threshold": threshold if criterion == "gpa_below" else None, "count": len(hits),
                           "by_program": dict(Counter(h["program"] for h in hits)),
                           "students": [{k: h[k] for k in ("university_id", "cumulative_gpa", "probation_terms")}
                                        for h in hits] if len(hits) <= STUDENT_LIST_CAP else None},
                "citations": [c["source"] for c in self.policy.cite(["probation_rule",
                                                                     "at_risk_consecutive_probation_terms"])]}

    def graduation_candidates(self, program: str | None = None) -> dict:
        """Active students who meet every requirement once their courses in progress are passed."""
        from advising_agent.context import build_context
        from advising_agent.validate import check_plan
        from registrar.agents.advising import PgAdvisingData
        data = PgAdvisingData(self.s, self.cal)
        prog = self._program(program)
        ids = []
        for uid, st in sorted(self.students.items()):
            if plain(st.status) != "active" or (prog and st.program_code != prog):
                continue
            ctx = build_context({"request_id": "grad", "as_of": self.cal.as_of.isoformat(),
                                 "requester": {"university_id": "admin", "role": "admin"},
                                 "student_university_id": uid, "horizon_terms": 1}, data, self.policy)
            if not check_plan(ctx, {"terms": []}, 99, None):
                ids.append(uid)
        return {"answer": {"term": self.cal.current().name, "scope": {"kind": "program" if prog else "all", "value": prog},
                           "graduating": len(ids), "students": ids if len(ids) <= STUDENT_LIST_CAP else None},
                "note": "No graduation applications exist; this counts students whose requirements will all be met "
                        "when this term's courses are passed."}

    def headcount(self, filter: str = "active", program: str | None = None) -> dict:
        allowed = ("active", "full_time", "part_time", "first_time_this_term", "transfer_this_term", "international",
                   "resident", "nonresident")
        if filter not in allowed:
            raise ToolError(f"filter must be one of {', '.join(allowed)}.")
        cur = self.cal.current()
        load = Counter()
        for e in self.rows:
            if e.term_code == cur.code and e.status.value in SEATED:
                load[e.student_university_id] += float(self.courses[e.course_code].credit_hours)
        prog = self._program(program)
        ft = self.policy.get_params()["full_time_credits"]
        out = []
        for uid, st in self.students.items():
            if plain(st.status) != "active" or (prog and st.program_code != prog):
                continue
            deg = self.programs[st.program_code].degree
            ok = {"active": True,
                  "full_time": load[uid] >= ft[deg], "part_time": 0 < load[uid] < ft[deg],
                  "first_time_this_term": st.admit_term_code == cur.code and plain(st.entry_type) == "first_time",
                  "transfer_this_term": st.admit_term_code == cur.code and plain(st.entry_type) == "transfer",
                  "international": plain(st.residency) == "international",
                  "resident": plain(st.residency) == "resident",
                  "nonresident": plain(st.residency) == "nonresident"}[filter]
            if ok:
                out.append(st.program_code)
        return {"answer": {"scope": {"kind": "program" if prog else "all", "value": prog}, "filter": filter,
                           "count": len(out), "by_program": dict(Counter(out))}}

    def gpa_profile(self, program: str | None = None, threshold: float | None = None,
                    comparison: str | None = None) -> dict:
        cum = self._cum_gpa()
        prog = self._program(program)
        g = sorted(cum[u] for u, st in self.students.items()
                   if plain(st.status) == "active" and u in cum and (not prog or st.program_code == prog))
        if comparison not in (None, "ge", "lt"):
            raise ToolError("comparison must be ge or lt.")
        match = None
        if threshold is not None:
            comparison = comparison or "ge"
            match = sum(1 for x in g if (x >= threshold if comparison == "ge" else x < threshold))
        return {"answer": {"scope": {"kind": "program" if prog else "all", "value": prog}, "students_with_gpa": len(g),
                           "mean_gpa": round(statistics.fmean(g), 2) if g else None,
                           "median_gpa": round(statistics.median(g), 2) if g else None,
                           "threshold": threshold, "comparison": comparison if threshold is not None else None,
                           "count_matching": match}}

    def cohort_outcomes(self, admit_term: str, entry_type: str | None = None) -> dict:
        t = self._term(admit_term)
        if t is None:
            raise ToolError("Name the admit term, e.g. 'Fall 2024'.")
        if entry_type in (None, "", "all", "any"):
            entry_type = None
        elif entry_type not in ("first_time", "transfer", "readmit"):
            raise ToolError("entry_type must be first_time, transfer or readmit; omit it for all students.")
        rows = [st for st in self.students.values() if st.admit_term_code == t.code
                and (entry_type is None or plain(st.entry_type) == entry_type)]
        c = Counter(plain(st.status) for st in rows)
        return {"answer": {"cohort": {"admit_term": t.name, "entry_type": entry_type or "all"}, "size": len(rows),
                           "counts_by_status": dict(c),
                           "retained_rate": pct(c["active"] + c["graduated"], len(rows))}}

    def get_student_record(self, student: str) -> dict:
        """Admin may read one student's record (registrar_admin role)."""
        text = str(student or "").strip()
        st = self.students.get(text)
        if st is None:
            words = text.lower().split()
            cands = [s for s in self.students.values()
                     if (p := self.s.get(Person, s.university_id)) and f"{p.first_name} {p.last_name}".lower() == " ".join(words)]
            if len(cands) != 1:
                raise ToolError("Give the student's university ID or exact name.")
            st = cands[0]
        tg = self._term_gpas().get(st.university_id, [])
        p = self.s.get(Person, st.university_id)
        return {"answer": {"university_id": st.university_id, "name": f"{p.first_name} {p.last_name}",
                           "program": st.program_code, "status": plain(st.status),
                           "cumulative_gpa": self._cum_gpa().get(st.university_id),
                           "last_term_gpa": round(tg[-1][1], 2) if tg else None}}


_SCOPE = {"scope_kind": {"type": "string", "enum": list(SCOPES),
                         "description": "What the statistic covers: all, one course, a subject (CS, MATH), a level "
                                        "(lower_division, upper_division, graduate) or a program (students' major)."},
          "scope_value": {"type": "string", "description": "Course code, subject code, level or program code."},
          "term": {"type": "string", "description": "Term as the user said it ('last spring', 'Fall 2025'); omit or "
                                                    "'all' for every term."}}
TOOL_SPECS = [
    _fn("grade_distribution", "Grade counts, % A, % F, % DFW and mean GPA for a group of courses in a term or over "
        "all terms. Use for 'how are the grades', 'how many A's/F's'.", _SCOPE),
    _fn("dfw_rate", "D, F, W counts, DFW rate and pass rate (C- or better) for a group of courses.", _SCOPE),
    _fn("grading_extremes", "Courses or sections with the highest or lowest % A, % F, % DFW or mean GPA (at least 10 "
        "grades).", {"metric": {"type": "string", "enum": ["pct_a", "pct_f", "pct_dfw", "mean_gpa"]},
                     "direction": {"type": "string", "enum": ["highest", "lowest"]},
                     "unit": {"type": "string", "enum": ["course", "section"]},
                     "limit": {"type": "integer"}, **_SCOPE}, ["metric"]),
    _fn("withdrawals", "Withdrawals (W) and withdrawal rate for a group of courses, with the top courses.", _SCOPE),
    _fn("enrollment_summary", "Sections, capacity, registered students, seats left, fill rate and full sections for "
        "a group of courses in a term (default: current).", _SCOPE),
    _fn("at_risk_students", "Active students on academic probation, at risk of suspension ('brink of dismissal'), "
        "or with cumulative GPA below a threshold; with IDs when 40 or fewer.",
        {"criterion": {"type": "string", "enum": ["probation", "at_risk_of_suspension", "gpa_below"]},
         "program": {"type": "string", "description": "Program code (BSCS, BSENG, MSCS, MSENG). Only when the user "
                                                     "names a program or major; otherwise omit it."},
         "threshold": {"type": "number"}}),
    _fn("graduation_candidates", "Active students who will meet every degree requirement once this term's courses "
        "are passed ('who will graduate').",
        {"program": {"type": "string", "description": "Program code, only when the user names one; otherwise omit."}}),
    _fn("headcount", "Count of active students by filter: active, full_time, part_time, first_time_this_term, "
        "transfer_this_term, international, resident, nonresident.",
        {"filter": {"type": "string"}, "program": {"type": "string", "description": "Only when the user names a "
                                                                                    "program; otherwise omit."}}),
    _fn("gpa_profile", "Mean and median cumulative GPA of active students, optionally how many are at or above "
        "(ge) / below (lt) a threshold.", {"program": {"type": "string"}, "threshold": {"type": "number"},
                                           "comparison": {"type": "string", "enum": ["ge", "lt"]}}),
    _fn("cohort_outcomes", "Status counts and retention rate of the students admitted in a term.",
        {"admit_term": {"type": "string"}, "entry_type": {"type": "string",
                                                           "enum": ["all", "first_time", "transfer", "readmit"],
                                                           "description": "Only when the user names an entry type "
                                                                          "(first-time, transfer); otherwise omit."}},
        ["admit_term"]),
    _fn("get_student_record", "One student's program, status and GPA (registrar administrators only).",
        {"student": {"type": "string", "description": "University ID or full name."}}, ["student"]),
]
