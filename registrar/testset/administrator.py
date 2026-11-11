"""Administrator test cases with ground truth computed in raw SQL, independently of registrar/agents/admin/tools.py.

    python scripts/make_testset.py --persona administrator     (or: python -m registrar.testset.administrator)

Shapes and rules: data/testset/administrator/questions.md, adapted to this schema as documented in
registrar/agents/admin/tools.py. Percentages have one decimal; GPAs two decimals (the grader allows 0.005).

Ported 2026-11-11 to main's enrollment table (one row per student and section, no course_code column, graded rows
`completed`): every query reads enrollment through ENR, which adds the lecture's course code and leaves dropped rows
out. A seat is held by an `enrolled` or `completed` row. Transfer credit counts toward graduation.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-11-20T18:00:00+00:00"
CURRENT, PREV_SPRING, PREV_FALL, NEXT = "202680", "202610", "202580", "202710"
DFW = ("D+", "D", "D-", "F", "W")
ENR = ("(SELECT x.*, xl.course_code FROM enrollment x JOIN lecture xl ON xl.term_code = x.term_code AND xl.crn = x.crn "
       "WHERE x.status <> 'dropped')")


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


class Truth:
    def __init__(self, dsn: str):
        self.c = psycopg.connect(dsn)

    def q(self, sql, *args):
        with self.c.cursor() as cur:
            cur.execute(sql.replace("FROM enrollment e", f"FROM {ENR} e"), args)
            return cur.fetchall()

    def term_name(self, code):
        return self.q("SELECT name FROM academic_term WHERE code=%s", code)[0][0]

    # graded rows in a course scope: (grade, points, credits, course, crn, student, term)
    def graded(self, kind, value, term):
        where, args = ["e.grade IS NOT NULL", "e.grade <> 'I'", "e.status <> 'dropped'"], []
        if term:
            where.append("e.term_code = %s"); args.append(term)
        if kind == "course":
            where.append("c.code = %s"); args.append(value)
        elif kind == "subject":
            where.append("c.subject = %s"); args.append(value)
        elif kind == "level":
            where.append("c.level = %s"); args.append(value)
        elif kind == "program":
            where.append("s.program_code = %s"); args.append(value)
        return self.q(f"""SELECT e.grade, gs.points, c.credit_hours, c.code, e.crn, e.student_university_id, e.term_code
            FROM enrollment e JOIN course c ON c.code = e.course_code JOIN grade_scale gs ON gs.letter = e.grade
            JOIN student s ON s.university_id = e.student_university_id WHERE {' AND '.join(where)}""", *args)

    def scope(self, kind, value, term):
        return {"kind": kind, "value": value, "term": self.term_name(term) if term else None}

    def grade_distribution(self, kind, value, term):
        rows = self.graded(kind, value, term)
        cnt = Counter(r[0] for r in rows)
        pts = [(float(r[1]), float(r[2])) for r in rows if r[1] is not None]
        cr = sum(c for _, c in pts)
        return {"scope": self.scope(kind, value, term), "available": bool(rows), "graded": len(rows),
                "counts": dict(cnt), "pct_a": pct(cnt["A"], len(rows)), "pct_f": pct(cnt["F"], len(rows)),
                "pct_dfw": pct(sum(cnt[g] for g in DFW), len(rows)),
                "mean_gpa": round(sum(p * c for p, c in pts) / cr, 2) if cr else None}

    def dfw_rate(self, kind, value, term):
        rows = self.graded(kind, value, term)
        cnt = Counter(r[0] for r in rows)
        passed = sum(1 for r in rows if r[1] is not None and float(r[1]) >= 1.7)
        d, f, w = cnt["D+"] + cnt["D"] + cnt["D-"], cnt["F"], cnt["W"]
        return {"scope": self.scope(kind, value, term), "total": len(rows), "d": d, "f": f, "w": w,
                "dfw_rate": pct(d + f + w, len(rows)), "pass_rate": pct(passed, len(rows))}

    def extremes(self, metric, direction, unit, kind, value, term, limit=5):
        rows = self.graded(kind, value, term)
        g = defaultdict(list)
        for r in rows:
            if unit == "section":
                if not r[4]:
                    continue
                g[r[4] if term else f"{r[6]}:{r[4]}"].append(r)
            else:
                g[r[3]].append(r)
        items = []
        for k, rs in g.items():
            if len(rs) < 10:
                continue
            cnt = Counter(r[0] for r in rs)
            if metric == "mean_gpa":
                ps = [(float(r[1]), float(r[2])) for r in rs if r[1] is not None]
                v = round(sum(p * c for p, c in ps) / sum(c for _, c in ps), 2)
            else:
                num = {"pct_a": cnt["A"], "pct_f": cnt["F"], "pct_dfw": sum(cnt[x] for x in DFW)}[metric]
                v = pct(num, len(rs))
            items.append({"key": k, "graded": len(rs), "value": v})
        items.sort(key=lambda i: (-i["value"] if direction == "highest" else i["value"], i["key"]))
        return {"scope": self.scope(kind, value, term), "unit": unit, "metric": metric, "direction": direction,
                "min_graded": 10, "items": items[:limit]}

    def withdrawals(self, kind, value, term):
        where, args = ["e.status <> 'dropped'", "e.term_code = %s"], [term]
        if kind == "subject":
            where.append("c.subject = %s"); args.append(value)
        rows = self.q(f"SELECT e.course_code, e.grade FROM enrollment e JOIN course c ON c.code=e.course_code "
                      f"WHERE {' AND '.join(where)}", *args)
        w = Counter(c for c, g in rows if g == "W")
        top = sorted(w.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        return {"scope": self.scope(kind, value, term), "withdrawn": sum(w.values()), "started": len(rows),
                "rate": pct(sum(w.values()), len(rows)), "top_courses": [{"course": c, "withdrawn": n} for c, n in top]}

    def enrollment(self, kind, value, term):
        cond, args = "", [term]
        if kind == "subject":
            cond, args = " AND c.subject = %s", [term, value]
        elif kind == "course":
            cond, args = " AND c.code = %s", [term, value]
        elif kind == "level":
            cond, args = " AND c.level = %s", [term, value]
        rows = self.q(f"""SELECT l.crn, l.capacity, (SELECT count(*) FROM enrollment e WHERE e.term_code=l.term_code
              AND e.crn=l.crn AND e.status IN ('enrolled', 'completed')) FROM lecture l JOIN course c ON c.code=l.course_code
              WHERE l.term_code=%s AND NOT l.is_cancelled{cond}""", *args)
        cap, reg = sum(r[1] for r in rows), sum(r[2] for r in rows)
        return {"scope": self.scope(kind, value, term), "sections": len(rows), "capacity": cap, "registered": reg,
                "seats_left": cap - reg, "fill_rate": pct(reg, cap), "full_sections": sum(1 for r in rows if r[2] >= r[1])}

    def _streaks(self):
        rows = self.q("""SELECT e.student_university_id, t.sequence,
                 sum(gs.points * c.credit_hours) / sum(c.credit_hours) AS term_gpa
               FROM enrollment e JOIN grade_scale gs ON gs.letter = e.grade AND gs.points IS NOT NULL
               JOIN course c ON c.code = e.course_code JOIN academic_term t ON t.code = e.term_code
               GROUP BY 1, 2 ORDER BY 1, 2""")
        mins = dict(self.q("SELECT s.university_id, p.min_gpa FROM student s JOIN program p ON p.code=s.program_code"))
        by = defaultdict(list)
        for uid, _, g in rows:
            by[uid].append(float(g))
        out = {}
        for uid, gs in by.items():
            n = 0
            for g in reversed(gs):
                if g < float(mins[uid]) - 1e-9:
                    n += 1
                else:
                    break
            out[uid] = n
        return out

    def cum(self):
        return {u: round(float(g), 2) for u, g in self.q("""SELECT e.student_university_id,
                 sum(gs.points * c.credit_hours) / sum(c.credit_hours) FROM enrollment e
               JOIN grade_scale gs ON gs.letter = e.grade AND gs.points IS NOT NULL
               JOIN course c ON c.code = e.course_code GROUP BY 1""")}

    def at_risk(self, criterion, program=None, threshold=None):
        streak, cum = self._streaks(), self.cum()
        active = self.q("SELECT university_id, program_code FROM student WHERE status='active'"
                        + (" AND program_code=%s" if program else ""), *([program] if program else []))
        hits = []
        for uid, prog in sorted(active):
            s = streak.get(uid, 0)
            ok = (s >= 1) if criterion == "probation" else (s >= 2) if criterion == "at_risk_of_suspension" \
                else (uid in cum and cum[uid] < threshold)
            if ok:
                hits.append((uid, prog, s))
        return {"scope": {"kind": "program" if program else "all", "value": program}, "criterion": criterion,
                "threshold": threshold if criterion == "gpa_below" else None, "count": len(hits),
                "by_program": dict(Counter(p for _, p, _ in hits)),
                "students": [{"university_id": u, "cumulative_gpa": cum.get(u), "probation_terms": s}
                             for u, _, s in hits] if len(hits) <= 40 else None}

    def graduation(self, program=None):
        studs = self.q("""SELECT s.university_id, s.program_code, p.total_credits_required FROM student s
            JOIN program p ON p.code=s.program_code WHERE s.status='active'""" + (" AND s.program_code=%s" if program else ""),
                       *([program] if program else []))
        done = defaultdict(set)
        for uid, course in self.q("""SELECT e.student_university_id, e.course_code FROM enrollment e
                LEFT JOIN grade_scale gs ON gs.letter = e.grade
                WHERE (gs.points > 0) OR (e.grade IS NULL AND e.status='enrolled' AND e.term_code=%s)
                UNION SELECT student_university_id, course_code FROM transfer_credit""", CURRENT):
            done[uid].add(course)
        credit = dict(self.q("SELECT code, credit_hours FROM course"))
        plan = defaultdict(list)
        for prog, course, cat, req in self.q("SELECT program_code, course_code, category, is_required FROM degree_requirement"):
            plan[prog].append((course, cat, req))
        mins = defaultdict(dict)
        for prog, cat, m in self.q("SELECT program_code, category, min_credits FROM program_category_requirement"):
            mins[prog][cat] = m
        ids = []
        for uid, prog, total in sorted(studs):
            d = done[uid]
            if any(req and c not in d for c, _, req in plan[prog]):
                continue
            if any(sum(float(credit[c]) for c, k, _ in plan[prog] if k == cat and c in d) < m for cat, m in mins[prog].items()):
                continue
            if sum(float(credit[c]) for c in d) < total:
                continue
            ids.append(uid)
        return {"term": self.term_name(CURRENT), "scope": {"kind": "program" if program else "all", "value": program},
                "graduating": len(ids), "students": ids if len(ids) <= 40 else None}

    def headcount(self, flt, program=None):
        load = dict(self.q("""SELECT e.student_university_id, sum(c.credit_hours) FROM enrollment e
            JOIN course c ON c.code=e.course_code WHERE e.term_code=%s AND e.status IN ('enrolled', 'completed')
            GROUP BY 1""", CURRENT))
        rows = self.q("""SELECT s.university_id, s.program_code, p.degree, s.admit_term_code, s.entry_type, s.residency
            FROM student s JOIN program p ON p.code=s.program_code WHERE s.status='active'"""
                      + (" AND s.program_code=%s" if program else ""), *([program] if program else []))
        ft = {"BS": 12, "MS": 9}
        keep = []
        for uid, prog, deg, admit, entry, res in rows:
            l = float(load.get(uid, 0))
            ok = {"active": True, "full_time": l >= ft[deg], "part_time": 0 < l < ft[deg],
                  "first_time_this_term": admit == CURRENT and entry == "first_time",
                  "international": res == "international", "resident": res == "resident"}[flt]
            if ok:
                keep.append(prog)
        return {"scope": {"kind": "program" if program else "all", "value": program}, "filter": flt,
                "count": len(keep), "by_program": dict(Counter(keep))}

    def gpa_profile(self, program=None, threshold=None, comparison=None):
        cum = self.cum()
        act = [u for (u,) in self.q("SELECT university_id FROM student WHERE status='active'"
                                    + (" AND program_code=%s" if program else ""), *([program] if program else []))]
        g = sorted(cum[u] for u in act if u in cum)
        n = len(g)
        med = g[n // 2] if n % 2 else (g[n // 2 - 1] + g[n // 2]) / 2
        m = None
        if threshold is not None:
            m = sum(1 for x in g if (x >= threshold if comparison == "ge" else x < threshold))
        return {"scope": {"kind": "program" if program else "all", "value": program}, "students_with_gpa": n,
                "mean_gpa": round(sum(g) / n, 2), "median_gpa": round(med, 2), "threshold": threshold,
                "comparison": comparison if threshold is not None else None, "count_matching": m}

    def cohort(self, term):
        c = Counter(s for (s,) in self.q("SELECT status FROM student WHERE admit_term_code=%s", term))
        size = sum(c.values())
        return {"cohort": {"admit_term": self.term_name(term), "entry_type": "all"}, "size": size,
                "counts_by_status": dict(c), "retained_rate": pct(c["active"] + c["graduated"], size)}

    def student_record(self, uid):
        (prog, status, first, last), = self.q("""SELECT s.program_code, s.status, p.first_name, p.last_name FROM student s
            JOIN person p ON p.university_id=s.university_id WHERE s.university_id=%s""", uid)
        return {"university_id": uid, "name": f"{first} {last}", "program": prog, "status": status,
                "cumulative_gpa": self.cum().get(uid)}


def cases(t: Truth) -> list[dict]:
    C = []

    def add(intent, slots, answer, q, p1, p2):
        C.append({"id": f"adm-{intent}-{sum(1 for c in C if c['intent'] == intent) + 1:03d}", "persona": "administrator",
                  "intent": intent, "as_of": AS_OF, "as_of_is_default": True, "question": q, "paraphrases": [p1, p2],
                  "slots": slots, "answer": {"allowed": True, **answer}})

    gd = [("subject", "MATH", PREV_SPRING, "How are the grades in MATH this past spring?",
           "What did the MATH grade distribution look like last spring?", "Show me the spread of MATH grades in Spring 2026."),
          ("subject", "CS", PREV_FALL, "What was the grade distribution in CS courses in Fall 2025?",
           "How were CS grades in Fall 2025?", "Break down the grades given in CS for Fall 2025."),
          ("course", "ENGL 1110", None, "What does the grade distribution look like for ENGL 1110 across all terms?",
           "How have grades in ENGL 1110 looked overall?", "Give me the all-time grade spread for ENGL 1110."),
          ("level", "lower_division", PREV_SPRING, "How many A's and F's were given in lower-division courses last spring?",
           "What were the lower-division grades like in Spring 2026?", "Grade distribution for lower-division classes, last spring?"),
          ("program", "BSCS", PREV_FALL, "How did Computer Science majors do in their courses in Fall 2025?",
           "What grades did BSCS students earn in Fall 2025?", "Grade spread for Computer Science majors in Fall 2025?"),
          ("subject", "CS", CURRENT, "How are the grades in CS this semester?",
           "What's the CS grade distribution so far this term?", "Are CS grades for this semester in yet, and how do they look?")]
    for kind, val, term, q, a, b in gd:
        add("grade_distribution_group", {"scope_kind": kind, "scope_value": val, "term_code": term},
            t.grade_distribution(kind, val, term), q, a, b)
    for kind, val, term, q, a, b in [
            ("subject", "MATH", PREV_SPRING, "What is the DFW rate for MATH courses last spring?",
             "How many D's, F's and W's were there in MATH in Spring 2026?", "MATH DFW rate, Spring 2026?"),
            ("level", "upper_division", PREV_FALL, "What was the DFW rate in upper-division courses in Fall 2025?",
             "How did upper-division pass rates look in Fall 2025?", "Upper-division DFW and pass rate for Fall 2025?"),
            ("subject", "ENG", None, "What share of students pass ENG courses overall?",
             "What's the all-time DFW rate in ENG?", "Pass rate across every ENG course and term?")]:
        add("dfw_rate_group", {"scope_kind": kind, "scope_value": val, "term_code": term}, t.dfw_rate(kind, val, term), q, a, b)
    for metric, direction, unit, kind, val, term, q, a, b in [
            ("pct_f", "highest", "course", "all", None, None, "Which five courses have the highest F rate overall?",
             "Top five courses by share of F grades, all terms?", "Where are the most F's given, by course?"),
            ("pct_a", "highest", "section", "all", None, PREV_SPRING, "Which sections gave the highest share of A's last spring?",
             "Which Spring 2026 sections had the most A's proportionally?", "Top sections by A rate in Spring 2026?"),
            ("mean_gpa", "lowest", "course", "all", None, PREV_FALL, "Which courses had the lowest average GPA in Fall 2025?",
             "Lowest mean GPA courses for Fall 2025?", "Which Fall 2025 courses graded hardest on average?"),
            ("pct_dfw", "highest", "course", "subject", "CS", None, "Which CS courses have the worst DFW rate?",
             "Highest DFW rates among CS courses, all terms?", "Where do CS students struggle most, by DFW rate?")]:
        add("grading_extremes", {"metric": metric, "direction": direction, "unit": unit, "scope_kind": kind,
                                 "scope_value": val, "term_code": term},
            t.extremes(metric, direction, unit, kind, val, term), q, a, b)
    for kind, val, term, q, a, b in [
            ("all", None, PREV_SPRING, "How many withdrawals were there last spring, and which courses had the most?",
             "Withdrawal count and rate for Spring 2026?", "Which courses had the most W's in Spring 2026?"),
            ("subject", "MATH", PREV_FALL, "How many students withdrew from MATH courses in Fall 2025?",
             "MATH withdrawals in Fall 2025?", "What was the withdrawal rate in MATH for Fall 2025?")]:
        add("withdrawals_group", {"scope_kind": kind, "scope_value": val, "term_code": term}, t.withdrawals(kind, val, term), q, a, b)
    for kind, val, term, q, a, b in [
            ("subject", "CS", CURRENT, "How many students are enrolled in CS courses this fall, and how full are the sections?",
             "CS enrollment and fill rate this semester?", "How many seats are left in CS sections this fall?"),
            ("course", "MATH 1511", CURRENT, "What's the total capacity versus enrollment for MATH 1511 this fall?",
             "How full is MATH 1511 this semester?", "MATH 1511 seats and registrations this term?"),
            ("all", None, NEXT, "How many students have registered for Spring 2027 sections so far?",
             "What's the Spring 2027 fill rate right now?", "How many Spring 2027 seats are taken?"),
            ("level", "graduate", CURRENT, "How full are graduate-level sections this semester?",
             "Graduate course enrollment this fall?", "Capacity and registrations for graduate courses this term?")]:
        add("enrollment_group", {"scope_kind": kind, "scope_value": val, "term_code": term}, t.enrollment(kind, val, term), q, a, b)
    for crit, prog, thr, q, a, b in [
            ("at_risk_of_suspension", None, None, "Which students are on the brink of dismissal?",
             "Who is close to being suspended?", "List students at risk of suspension."),
            ("probation", None, None, "How many students are on academic probation right now?",
             "Which students are currently on probation?", "Give me the probation list."),
            ("probation", "BSENG", None, "Which Engineering bachelor's students are on probation?",
             "BSENG students on probation right now?", "Who in BSENG is on academic probation?"),
            ("gpa_below", None, 2.0, "How many active students have a cumulative GPA below 2.0?",
             "Which active students are under a 2.0 cumulative GPA?", "Count of active students with GPA under 2.0?")]:
        add("at_risk_students", {"criterion": crit, "program": prog, "threshold": thr}, t.at_risk(crit, prog, thr), q, a, b)
    for prog, q, a, b in [(None, "Which students will graduate at the end of this term?",
                           "Who finishes their degree this semester?", "How many students complete all requirements this fall?"),
                          ("BSCS", "Which Computer Science majors are set to graduate this semester?",
                           "BSCS students finishing this term?", "Who in BSCS completes their degree this fall?")]:
        add("graduation_candidates", {"program": prog}, t.graduation(prog), q, a, b)
    for flt, prog, q, a, b in [("active", None, "How many active students do we have?", "What's our active headcount?",
                                "Total number of active students?"),
                               ("full_time", None, "How many students are enrolled full-time this fall?",
                                "Full-time headcount this semester?", "How many students carry a full-time load this term?"),
                               ("first_time_this_term", None, "How many new first-time students started this fall?",
                                "First-time freshmen this semester?", "How many first-time students began in Fall 2026?"),
                               ("international", "MSCS", "How many international students are in the MSCS program?",
                                "International MSCS students, active?", "Count of active international students in MSCS?")]:
        add("headcount", {"filter": flt, "program": prog}, t.headcount(flt, prog), q, a, b)
    for prog, thr, cmp_, q, a, b in [(None, None, None, "What is the average cumulative GPA of active students?",
                                      "Mean and median GPA across active students?", "What's the typical GPA of our active students?"),
                                     ("BSCS", 3.5, "ge", "How many active Computer Science majors have a GPA of 3.5 or higher?",
                                      "BSCS students at 3.5 or above?", "How many BSCS students have at least a 3.5?"),
                                     ("BSENG", 2.5, "lt", "How many BSENG students have a GPA below 2.5?",
                                      "Engineering bachelor's students under 2.5 GPA?", "Count of BSENG students below a 2.5?")]:
        add("gpa_profile", {"program": prog, "threshold": thr, "comparison": cmp_}, t.gpa_profile(prog, thr, cmp_), q, a, b)
    for term, q, a, b in [("202480", "Of the students admitted in Fall 2024, how many are still active or graduated?",
                           "How is the Fall 2024 cohort doing?", "Retention of the Fall 2024 admits?"),
                          ("202180", "What happened to the students admitted in Fall 2021?",
                           "Outcomes for the Fall 2021 cohort?", "How many Fall 2021 admits graduated?")]:
        add("cohort_outcomes", {"admit_term_code": term}, t.cohort(term), q, a, b)
    uid = t.at_risk("probation")["students"][0]["university_id"]
    add("student_record", {"student": uid}, t.student_record(uid), f"What is {uid}'s program, status and GPA?",
        f"Pull up the record for student {uid}.", f"How is {uid} doing academically?")
    return C


def main():
    import sys
    sys.path.insert(0, str(ROOT))
    from registrar.db import DATABASE_URL
    t = Truth(DATABASE_URL.replace("postgresql+psycopg://", "postgresql://"))
    cs = cases(t)
    out = ROOT / "data/testset/administrator/cases.jsonl"
    with open(out, "w") as f:
        for c in cs:
            f.write(json.dumps(c, sort_keys=False) + "\n")
    print(f"wrote {len(cs)} cases to {out}")


if __name__ == "__main__":
    main()
