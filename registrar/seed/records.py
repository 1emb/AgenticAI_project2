"""Enrollment records for every student, and transfer credit for transfer students (added 2026-11-02, owner's go-ahead for
"transcripts based on the data for all the students").

Rules the generator follows:
- A student attends every term from the admit term to a last term set by status: active students through the current term
  (Fall 2026, in progress: enrolled, no grade) and, for some of them, Spring 2027 (registered, no grade); graduated students
  through their expected graduation term; withdrawn, on-leave, suspended and dismissed students through an earlier term,
  often ending in a term of W grades. A readmitted student may have an earlier stint, then a gap, then the readmit term.
- Each term the student takes, in this order: retakes of failed or too-low prerequisite courses, the degree plan's required
  courses due by their semester number, then plan electives and general-education options until the category minimums are
  met, then anything else that counts toward the total; the load paces the remaining credits over the remaining terms
  (12 to 18 credits, up to 21 in a final term; 6 to 9 for a master's student).
- A course is taken only when every prerequisite group has a member passed with the minimum grade or accepted as transfer
  credit. A master's student's prerequisites are presumed met by the prior degree. A Spring 2027 registration counts the
  Fall 2026 in-progress courses as met.
- Sections fill in CRN order (first fit) and never exceed capacity; cancelled sections are never used; a student's sections
  in a term never overlap, and a TA's never overlap the sections they teach.
- Grades come from a per-student ability plus per-course noise. Graduated students complete every requirement with a GPA at
  or above the program minimum; suspended and dismissed students sit below it. W is rare, I appears only in the latest
  completed term (Spring 2026). Every graded attempt stays on the record and counts in the GPA.
- A transfer student brings the plan's first two semesters (most of them) as transfer credit: it earns credit and meets
  prerequisites, carries no grade, and is outside the GPA.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import time

from . import catalog as C

CURRENT_TERM = "202680"
NEXT_TERM = "202710"
LATEST_GRADED_TERM = "202610"
POINTS = {"A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7, "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0, "D-": 0.7, "F": 0.0}
CUTS = [(3.85, "A"), (3.5, "A-"), (3.15, "B+"), (2.85, "B"), (2.5, "B-"), (2.15, "C+"), (1.85, "C"), (1.5, "C-"), (1.15, "D+"), (0.85, "D"), (0.5, "D-")]
LOAD = {"BS": (12, 18, 21), "MS": (6, 9, 12)}      # (minimum, usual maximum, maximum in a final term)
MAX_ATTEMPTS = 3
TRACE = None            # debugging hook: a callable (uid, term, k, target, chosen course codes, skipped required courses with the reason)
CREDITS = {code: cr for code, _, cr, _ in C.COURSES}
TOTAL = {code: tot for code, _, _, _, tot, _ in C.PROGRAMS}
DEGREE = {code: deg for code, _, _, deg, _, _ in C.PROGRAMS}
MIN_GPA = {code: float(gpa) for code, _, _, _, _, gpa in C.PROGRAMS}


def overlaps(a: tuple, b: tuple) -> bool:
    """Two (days, start, end) patterns conflict when they share a day and their times overlap."""
    return bool(set(a[0]) & set(b[0])) and a[1] < b[2] and b[1] < a[2]


def letter(perf: float) -> str:
    for cut, l in CUTS:
        if perf >= cut:
            return l
    return "F"


def slot(l: dict) -> tuple[str, time, time]:
    return (l["days"], l["start_time"], l["end_time"])


def chain_depth(program: str) -> dict[str, int]:
    """For each course, how many plan courses depend on it transitively along the longest path: MATH 1511 sits under the whole
    engineering chain, a general-education option under nothing. Courses deep in a chain are scheduled first."""
    plan = C.DEGREE_PLANS[program]
    codes = {c for c, _, _ in plan["required"]} | set(plan["elective"]) | set(plan["general_education"])
    dependents: dict[str, set[str]] = defaultdict(set)
    for course in codes:
        for group in C.PREREQUISITES.get(course, []):
            for req, _ in group:
                dependents[req].add(course)
    memo: dict[str, int] = {}

    def depth(c: str) -> int:
        if c not in memo:
            memo[c] = 0
            memo[c] = max((1 + depth(d) for d in dependents[c]), default=0)
        return memo[c]
    return {c: depth(c) for c in codes}


class Record:
    """One student's academic state while the terms are simulated."""

    def __init__(self, row: dict, ability: float):
        self.uid = row["university_id"]
        self.program = row["program_code"]
        self.degree = DEGREE[self.program]
        self.ability = ability
        plan = C.DEGREE_PLANS[self.program]
        depth = chain_depth(self.program)
        self.required = sorted(plan["required"], key=lambda x: (x[2], -depth[x[0]], x[0]))     # (course, category, suggested term)
        self.required_codes = {c for c, _, _ in self.required}
        self.electives = list(plan["elective"])
        self.geneds = list(plan["general_education"])
        self.minimums = C.CATEGORY_MINIMUMS[self.program]
        self.best: dict[str, float] = {}        # course -> best grade points among graded attempts
        self.attempts: Counter = Counter()
        self.transfer: set[str] = set()
        self.in_progress: set[str] = set()
        self.earned = 0.0
        self.category = Counter()               # elective / general_education credits earned
        self.graded_points = 0.0
        self.graded_credits = 0.0
        self.rows: list[dict] = []

    # ---- state questions ----
    def done(self, course: str) -> bool:
        return course in self.transfer or self.best.get(course, -1.0) > 0.0

    def prereqs_met(self, course: str, in_progress_counts: bool = False) -> bool:
        if self.degree == "MS":                  # admitted on a prior degree: the undergraduate prerequisites are presumed met
            return True
        for group in C.PREREQUISITES.get(course, []):
            if not any(req in self.transfer or self.best.get(req, -1.0) >= POINTS[mg] or (in_progress_counts and req in self.in_progress)
                       for req, mg in group):
                return False
        return True

    def retakes(self) -> list[str]:
        """Failed required courses, and prerequisites passed below the grade a still-needed required course asks for."""
        out = []
        for course in self.required_codes:
            if self.done(course) or course in self.transfer:
                continue
            if self.best.get(course) == 0.0 and self.attempts[course] < MAX_ATTEMPTS:
                out.append(course)
            for group in C.PREREQUISITES.get(course, []):
                if any(req in self.transfer or self.best.get(req, -1.0) >= POINTS[mg] for req, mg in group):
                    continue
                for req, mg in group:
                    if req in self.best and self.best[req] < POINTS[mg] and self.attempts[req] < MAX_ATTEMPTS and req not in out:
                        out.append(req)
        order = {c: i for i, (c, _, _) in enumerate(self.required)}
        return sorted(out, key=lambda c: (order.get(c, 99), c))

    def category_of(self, course: str) -> str | None:
        for c, cat, _ in self.required:
            if c == course:
                return cat
        if course in self.electives:
            return "elective"
        if course in self.geneds:
            return "general_education"
        return None

    def complete(self) -> bool:
        return (all(self.done(c) for c in self.required_codes) and self.earned >= TOTAL[self.program]
                and all(self.category[cat] >= mn for cat, mn in self.minimums.items()))

    def gpa(self) -> float | None:
        return self.graded_points / self.graded_credits if self.graded_credits else None

    # ---- state changes ----
    def grant_transfer(self, course: str) -> None:
        self.transfer.add(course)
        self.earned += CREDITS[course]
        cat = self.category_of(course)
        if cat:
            self.category[cat] += CREDITS[course]

    def record(self, course: str, grade: str | None) -> None:
        """Apply one graded attempt (None = still in progress, 'W' = withdrawn, 'I' = incomplete)."""
        if grade is None:
            self.in_progress.add(course)
            return
        if grade in ("W", "I"):
            return
        self.attempts[course] += 1
        pts = POINTS[grade]
        cr = CREDITS[course]
        self.graded_points += pts * cr
        self.graded_credits += cr
        was_done = self.done(course)
        self.best[course] = max(self.best.get(course, -1.0), pts)
        if not was_done and pts > 0:
            self.earned += cr
            cat = self.category_of(course)
            if cat:
                self.category[cat] += cr


def generate_records(seed: int, terms: list[dict], students: list[dict], lectures: list[dict]) -> tuple[list[dict], list[dict]]:
    """Enrollment and transfer-credit rows for every student, in a fixed order. Own random stream: changing this module
    never moves the rows of the other tables."""
    rng = random.Random(f"{seed}-records")          # replaced per student in the loop below; the closures read the current one
    term_by_code = {t["code"]: t for t in terms}
    seq_to_code = {t["sequence"]: t["code"] for t in terms}
    cur_seq, next_seq = term_by_code[CURRENT_TERM]["sequence"], term_by_code[NEXT_TERM]["sequence"]
    first_seq = term_by_code["202180"]["sequence"]
    sections: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for l in sorted(lectures, key=lambda l: (l["term_code"], int(l["crn"]))):
        if not l["is_cancelled"]:
            sections[(l["term_code"], l["course_code"])].append(l)
    offered_terms: dict[str, set[str]] = defaultdict(set)
    for (t, c) in sections:
        offered_terms[t].add(c)
    taught: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for l in lectures:
        taught[(l["instructor_university_id"], l["term_code"])].append(slot(l))
    seats: Counter = Counter()
    enrollments: list[dict] = []
    transfers: list[dict] = []

    def term_plan(st: dict) -> tuple[list[tuple[str, str]], int]:
        """[(term_code, kind)] in order, kind in graded | withdraw_all | enrolled | registered, and the term the pace aims at."""
        admit_seq = term_by_code[st["admit_term_code"]]["sequence"]
        expected_seq = term_by_code[st["expected_graduation_term_code"]]["sequence"] if st["expected_graduation_term_code"] else admit_seq + 7
        status = st["status"]
        plan: list[tuple[str, str]] = []
        if st["entry_type"] == "readmit" and admit_seq - 3 >= first_seq:      # an earlier stint, then a gap of at least one term
            n = rng.choice([1, 2])
            end = admit_seq - 1 - rng.choice([1, 2])
            start = max(first_seq, end - n + 1)
            plan += [(seq_to_code[s], "graded") for s in range(start, end + 1)]
        if status == "active":
            plan += [(seq_to_code[s], "graded") for s in range(admit_seq, cur_seq)] + [(CURRENT_TERM, "enrolled")]
            if rng.random() < (0.9 if expected_seq == next_seq else 0.4):
                plan.append((NEXT_TERM, "registered"))
            return plan, max(expected_seq, cur_seq + 1)
        if status == "graduated":
            return plan + [(seq_to_code[s], "graded") for s in range(admit_seq, expected_seq + 1)], expected_seq
        if admit_seq >= cur_seq:                                              # left during their first term
            return plan + [(CURRENT_TERM, "withdraw_all")], expected_seq
        last = max(admit_seq, cur_seq - rng.choice([1, 1, 1, 2, 2, 3]))
        plan += [(seq_to_code[s], "graded") for s in range(admit_seq, last)]
        withdraw = rng.random() < (0.6 if status in ("withdrawn", "leave_of_absence") else 0.25)
        plan.append((seq_to_code[last], "withdraw_all" if withdraw else "graded"))
        return plan, expected_seq

    def pick(rec: Record, term: str, k: int, target: float, lo: float, hi: float, final: bool, in_progress_counts: bool,
             delta: Counter, shuffle_sections: bool = False) -> list[tuple[str, dict]]:
        """The courses for one term, each with its section: see the module docstring for the order. `k` is the semester number the
        plan is at (a graduate on a short plan is ahead of their calendar semester, so the chain finishes in time)."""
        busy = list(taught.get((rec.uid, term), []))
        chosen: list[tuple[str, dict]] = []
        load = 0.0
        taken = set()

        skipped: list[tuple[str, str]] = []

        def add(course: str, cap: float) -> bool:
            nonlocal load
            if course in taken:
                return False
            if load + CREDITS[course] > cap:
                skipped.append((course, "load"))
                return False
            why = "no section"
            options = list(sections.get((term, course), []))
            if shuffle_sections:
                rng.shuffle(options)
            for l in options:
                if seats[(term, l["crn"])] + delta[(term, l["crn"])] >= l["capacity"]:
                    why = "full"
                    continue
                s = slot(l)
                if any(overlaps(s, b) for b in busy):
                    why = "clash"
                    continue
                chosen.append((course, l))
                busy.append(s)
                taken.add(course)
                load += CREDITS[course]
                return True
            skipped.append((course, why))
            return False

        def wanted(course: str) -> bool:
            return (not rec.done(course) and course not in rec.in_progress and course in offered_terms[term]
                    and rec.attempts[course] < MAX_ATTEMPTS and rec.prereqs_met(course, in_progress_counts))

        for course in rec.retakes():                                           # 1. retakes
            if course in offered_terms[term] and rec.prereqs_met(course, in_progress_counts):
                add(course, hi)
        for course, _cat, tn in rec.required:                                  # 2. required courses due by now (all of them in a final term)
            if (tn <= k or final) and wanted(course):
                add(course, hi)
        need_el = rec.category["elective"] < rec.minimums.get("elective", 0)
        need_ge = rec.category["general_education"] < rec.minimums.get("general_education", 0)
        pools: list[list[str]] = []                                            # 3. in priority order, shuffled inside each pool
        el = [c for c in rec.electives if wanted(c)]
        ge = [c for c in rec.geneds if wanted(c)]
        rng.shuffle(el)
        rng.shuffle(ge)
        pools += [el if need_el else [], ge if need_ge else [], [] if need_el else el, [] if need_ge else ge]
        if rec.degree == "BS":
            free = [c for c in CREDITS if C.course_level(c) != "graduate" and rec.category_of(c) is None and wanted(c)]
            rng.shuffle(free)
            pools.append(free)
        for pool in pools:
            for course in pool:
                if load >= target:
                    break
                add(course, hi)
        if load < lo:                                                          # 4. still light: pull required courses from later semesters
            for course, _cat, tn in rec.required:
                if load >= lo:
                    break
                if tn > k and wanted(course):
                    add(course, hi)
        if TRACE:
            TRACE(rec.uid, term, k, target, [c for c, _ in chosen], skipped)
        return chosen

    def simulate(st: dict, ability: float, transfer_courses: list[str], delta: Counter, attempt: int = 0) -> Record:
        rec = Record(st, ability)
        for c in transfer_courses:
            rec.grant_transfer(c)
        plan, aim_seq = term_plan(st)
        k = 3 if st["entry_type"] == "transfer" else 1
        lo, hi, final_hi = LOAD[rec.degree]
        graduated = st["status"] == "graduated"
        main_start = next(i for i, (t, _) in enumerate(plan) if t == st["admit_term_code"])
        if graduated and rec.degree == "BS" and (k - 1) + (len(plan) - main_start) < 8:
            # a seven-term graduate takes each plan semester one term early so the chain fits, and carries a heavier load
            k += 8 - (k - 1) - (len(plan) - main_start)
            hi, final_hi = hi + 1, final_hi + 1
        for i, (term, kind) in enumerate(plan):
            seq = term_by_code[term]["sequence"]
            final = graduated and i == len(plan) - 1
            remaining_terms = max(1, aim_seq - seq + 1)
            remaining = TOTAL[rec.program] - rec.earned - sum(CREDITS[c] for c in rec.in_progress)
            cap = final_hi if final or (kind == "registered" and seq >= aim_seq) else hi
            target = cap if final else min(cap, max(lo, remaining / remaining_terms))
            floor = lo if remaining > lo else max(3.0, remaining)
            chosen = pick(rec, term, k, target, floor, cap, final, kind == "registered", delta, shuffle_sections=attempt > 0)
            earlier_stint = i < main_start
            for course, l in chosen:
                if kind in ("enrolled", "registered"):
                    grade = None
                elif kind == "withdraw_all":
                    grade = "W"
                else:
                    core = course in rec.required_codes
                    if not (graduated and (final or core)) and rng.random() < (0.02 if graduated else 0.03):
                        grade = "W"
                    elif term == LATEST_GRADED_TERM and not graduated and rng.random() < 0.01:
                        grade = "I"
                    else:
                        perf = rec.ability - (0.8 if earlier_stint else 0.0) + rng.gauss(0, 0.45)
                        if graduated and core:
                            perf = max(perf, 2.05)      # the chain never breaks: a required course passes at the grade the next one asks for
                        grade = letter(min(4.0, perf))
                rec.rows.append(dict(term_code=term, crn=l["crn"], student_university_id=rec.uid,
                                     status="enrolled" if grade is None else "withdrawn" if grade == "W" else "completed", grade=grade))
                delta[(term, l["crn"])] += 1
                rec.record(course, grade)
            k += 1
        return rec

    def acceptable(st: dict, rec: Record) -> bool:
        gpa, floor = rec.gpa(), MIN_GPA[st["program_code"]]
        if st["status"] == "graduated":
            return rec.complete() and gpa is not None and gpa >= floor
        if st["status"] in ("suspended", "dismissed"):
            return gpa is None or gpa < floor
        return True

    for st in students:
        # 2026-11-05: each student draws from their own stream, so adding students or sections changes another student's record
        # only through the seats they compete for, not through a shifted random sequence
        rng = random.Random(f"{seed}-records-{st['university_id']}")
        status, program = st["status"], st["program_code"]
        if DEGREE[program] == "MS":
            ability = rng.uniform(3.1, 3.95)
        elif status == "graduated":
            ability = rng.uniform(2.6, 3.9)
        elif status in ("suspended", "dismissed"):
            ability = rng.uniform(1.0, 1.7)
        elif status == "active":
            ability = rng.triangular(1.9, 3.95, 3.1)
        else:
            ability = rng.uniform(2.0, 3.6)
        transfer_courses: list[str] = []
        if st["entry_type"] == "transfer":
            plan = C.DEGREE_PLANS[program]
            brought = [c for c, _, tn in plan["required"] if tn <= 2 and rng.random() < 0.9]
            brought += [c for c in rng.sample(plan["general_education"], 2) if rng.random() < 0.5]
            transfer_courses = sorted(brought)
        for attempt in range(8):
            delta: Counter = Counter()
            rec = simulate(st, ability, transfer_courses, delta, attempt)
            if acceptable(st, rec):
                break
            if status == "graduated" and rec.gpa() is not None and rec.gpa() < MIN_GPA[program]:
                ability += 0.25                                         # a graduate who fell short of the GPA worked harder
            elif status in ("suspended", "dismissed"):
                ability -= 0.2                                          # a dismissed student did worse
        else:
            raise RuntimeError(f"no acceptable record for {st['university_id']} ({status}, {program}): gpa {rec.gpa()}, complete {rec.complete()}, "
                               f"earned {rec.earned}, missing {[c for c in rec.required_codes if not rec.done(c)]}, categories {dict(rec.category)}")
        seats.update(delta)
        enrollments.extend(rec.rows)
        transfers.extend(dict(student_university_id=st["university_id"], course_code=c, credit_hours=CREDITS[c], accepted_term_code=st["admit_term_code"])
                         for c in transfer_courses)
    enrollments.sort(key=lambda r: (r["term_code"], int(r["crn"]), r["student_university_id"]))
    transfers.sort(key=lambda r: (r["student_university_id"], r["course_code"]))
    return enrollments, transfers
