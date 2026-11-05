"""Deterministic generator for the dataset: terms, people, students, instructors and lectures around the catalog.

`generate(seed)` returns {table: [row dicts]} in the column order of csv_io.TABLES. The same seed gives the same rows.
Scope: Fall 2021 to Spring 2031 on the calendar, lectures for Fall 2021 to Spring 2027, Fall 2026 in progress,
Spring 2027 registration open from 2026-11-02. No summer terms. Enrollment and transfer credit come from records.py.

Append-only history (2026-11-02): the six lecture terms Fall 2024 to Spring 2027 were generated first and their rows are
frozen; the earlier terms, the former instructors who staff them, and the enrollment records are generated afterwards from
the same stream (or their own), so the original rows never move.
"""
from __future__ import annotations

import random
from datetime import date, time, timedelta

from . import catalog as C
from .records import generate_records, overlaps
from .staff import salaries, staff_rows, submission_rows

LECTURE_TERMS = ["202480", "202510", "202580", "202610", "202680", "202710"]
EARLIER_LECTURE_TERMS = ["202180", "202210", "202280", "202310", "202380", "202410"]   # added 2026-11-02 for the enrollment history
CURRENT_TERM = "202680"
MAX_SECTIONS_PER_INSTRUCTOR = 4
# instructors who left before Fall 2024 (is_active false, no lecture after Spring 2024); without them the small departments cannot
# staff Fall 2021 to Spring 2024: department, rank, hire year
FORMER_INSTRUCTORS = [("ENGL", "lecturer", 2012), ("ENGL", "lecturer", 2008), ("PHYS", "lecturer", 2015), ("COMM", "adjunct", 2016),
                      ("ECON", "assistant", 2017), ("PHIL", "lecturer", 2013), ("HIST", "adjunct", 2018), ("ENG", "associate", 2009),
                      ("ENG", "lecturer", 2016), ("ENG", "adjunct", 2012)]

FIRST_M = ["James", "Daniel", "Michael", "David", "Jose", "Luis", "Carlos", "Miguel", "Juan", "Andres", "Diego", "Mateo", "Ethan",
           "Noah", "Liam", "Aiden", "Tyler", "Brandon", "Kevin", "Ryan", "Marcus", "Isaiah", "Elijah", "Omar", "Ali", "Ahmed", "Wei",
           "Chen", "Hiroshi", "Raj", "Arjun", "Samuel", "Nathan", "Caleb", "Jacob", "Logan", "Owen", "Victor", "Sergio", "Rafael"]
FIRST_F = ["Maria", "Sofia", "Isabella", "Camila", "Valeria", "Lucia", "Ana", "Elena", "Gabriela", "Daniela", "Emma", "Olivia", "Ava",
           "Mia", "Chloe", "Grace", "Hannah", "Emily", "Sarah", "Jessica", "Priya", "Anjali", "Mei", "Yuki", "Fatima", "Layla", "Aisha",
           "Nadia", "Zoe", "Lily", "Natalie", "Victoria", "Alexis", "Brianna", "Kayla", "Megan", "Rachel", "Clara", "Renata", "Paola"]
FIRST_X = ["Alex", "Sam", "Jordan", "Taylor", "Casey", "Riley"]
LAST = ["Lopez", "Garcia", "Martinez", "Hernandez", "Rodriguez", "Gonzalez", "Perez", "Sanchez", "Ramirez", "Torres", "Flores",
        "Rivera", "Gomez", "Diaz", "Chavez", "Reyes", "Morales", "Ortiz", "Gutierrez", "Jimenez", "Ruiz", "Mendoza", "Castillo",
        "Romero", "Vargas", "Maestas", "Baca", "Montoya", "Archuleta", "Trujillo", "Smith", "Johnson", "Williams", "Brown", "Jones",
        "Miller", "Davis", "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Martin", "Jackson", "Thompson", "White", "Harris",
        "Clark", "Lewis", "Walker", "Hall", "Young", "King", "Wright", "Scott", "Green", "Baker", "Adams", "Nelson", "Hill", "Campbell",
        "Mitchell", "Carter", "Roberts", "Nguyen", "Tran", "Pham", "Kim", "Park", "Lee", "Chen", "Wang", "Li", "Zhang", "Patel",
        "Singh", "Khan", "Nair", "Begay", "Yazzie", "Tsosie", "Becenti"]

# instructors per department (TAs come on top, from the MS students); the first CS and ENG one listed as inactive retired after Spring 2025
INSTRUCTOR_COUNTS = {"CS": 11, "ENG": 11, "MATH": 6, "PHYS": 2, "ENGL": 3, "HIST": 2, "COMM": 1, "PSY": 1, "ECON": 1, "PHIL": 1}
RANK_POOL = ["professor", "professor", "associate", "associate", "assistant", "assistant", "lecturer", "adjunct"]
HIRE_YEARS = {"professor": (1995, 2012), "associate": (2008, 2018), "assistant": (2018, 2024), "lecturer": (2010, 2024), "adjunct": (2015, 2024)}
BUILDING = {"CS": "SH", "ENG": "EC", "MATH": "HH", "PHYS": "SH"}  # everything else meets in BH
ROOMS = {"SH": list(range(101, 119)), "EC": list(range(101, 121)), "HH": list(range(101, 116)), "BH": list(range(101, 126))}

# meeting patterns: (days, start, minutes)
MWF50 = [("MWF", time(h, 30), 50) for h in range(8, 16)]
TR75 = [("TR", time(8, 0), 75), ("TR", time(9, 30), 75), ("TR", time(11, 0), 75), ("TR", time(12, 30), 75), ("TR", time(14, 0), 75),
        ("TR", time(15, 30), 75), ("TR", time(17, 0), 75)]
MW75_EVE = [("MW", time(16, 0), 75), ("MW", time(17, 30), 75)]
MTWR50 = [("MTWR", time(h, 30), 50) for h in range(8, 15)]
THESIS = [("F", time(14, 30), 110), ("R", time(16, 0), 110)]

# how many sections a course gets in a term; graduate courses alternate between fall and spring
SECTION_COUNTS = {"CS 1110": 4, "CS 1120": 2, "CS 2210": 3, "CS 2215": 2, "CS 2230": 2, "CS 3310": 2, "CS 3410": 2,
                  "ENG 1110": 3, "ENG 1120": 2, "ENG 3110": 2, "ENG 3210": 2,
                  "MATH 1511": 4, "MATH 1521": 3, "PHYS 2110": 3, "PHYS 2120": 2,
                  "ENGL 1110": 4, "ENGL 1120": 3, "COMM 1130": 3, "PSY 1110": 3}
FALL_ONLY = {"CS 5110", "CS 5410", "CS 5720", "ENG 5110", "ENG 5510"}
# 2026-11-05 (owner): classes held a median of 4 to 7 students; three more cohorts bring the total to 1,200 students
EXTRA_STUDENTS = {"BSCS": 450, "BSENG": 360, "MSCS": 45, "MSENG": 45}
DEGREE_OF = {code: deg for code, _, _, deg, _, _ in C.PROGRAMS}
SEAT_HEADROOM = 1.15        # added sections leave this much room over the measured demand
SPRING_ONLY = {"CS 5320", "CS 5710", "CS 5810", "ENG 5310", "ENG 5610"}


def term_rows() -> list[dict]:
    rows, seq = [], 0
    for year in range(2021, 2031):
        seq += 1
        rows.append(dict(code=f"{year}80", name=f"Fall {year}", term_type="fall", academic_year=year,
                         start_date=date(year, 8, 19), end_date=date(year, 12, 11), registration_opens=date(year, 4, 6),
                         add_deadline=date(year, 8, 28), drop_deadline=date(year, 9, 4), withdraw_deadline=date(year, 10, 23),
                         grades_due=date(year, 12, 15), sequence=seq))
        seq += 1
        y = year + 1
        rows.append(dict(code=f"{y}10", name=f"Spring {y}", term_type="spring", academic_year=year,
                         start_date=date(y, 1, 13), end_date=date(y, 5, 7), registration_opens=date(year, 11, 2),
                         add_deadline=date(y, 1, 22), drop_deadline=date(y, 1, 29), withdraw_deadline=date(y, 3, 19),
                         grades_due=date(y, 5, 11), sequence=seq))
    return rows


def add_minutes(t: time, minutes: int) -> time:
    m = t.hour * 60 + t.minute + minutes
    return time(m // 60, m % 60)


class People:
    """Unique ids, SSNs, phones and emails for every person."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.ids: set[str] = set()
        self.ssns: set[str] = set()
        self.phones: set[str] = set()
        self.emails: set[str] = set()
        self.rows: list[dict] = []

    def _unique(self, make, seen: set) -> str:
        while True:
            v = make()
            if v not in seen:
                seen.add(v)
                return v

    def add(self, sex: str, birth_year: int, phone_rate: float = 0.9) -> dict:
        rng = self.rng
        first = rng.choice({"M": FIRST_M, "F": FIRST_F, "X": FIRST_X}[sex])
        last = rng.choice(LAST)
        uid = self._unique(lambda: str(rng.randrange(800_000_000, 802_000_000)), self.ids)
        ssn = self._unique(lambda: f"{rng.randint(1, 899):03d}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}", self.ssns)
        phone = self._unique(lambda: f"575-555-{rng.randint(1000, 9999):04d}", self.phones) if rng.random() < phone_rate else None
        base = f"{first[0].lower()}{last.lower()}"
        email, n = f"{base}@nmsu.example", 1
        while email in self.emails:
            n += 1
            email = f"{base}{n}@nmsu.example"
        self.emails.add(email)
        row = dict(university_id=uid, first_name=first, last_name=last, date_of_birth=date(birth_year, rng.randint(1, 12), rng.randint(1, 28)),
                   sex=sex, ssn=ssn, phone=phone, email=email)
        self.rows.append(row)
        return row


def generate(seed: int = 42) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    terms = term_rows()
    term_by_code = {t["code"]: t for t in terms}
    seq_to_code = {t["sequence"]: t["code"] for t in terms}
    current_seq = term_by_code[CURRENT_TERM]["sequence"]
    credits = {code: cr for code, _, cr, _ in C.COURSES}

    # ---------------------------------------------------------------- catalog tables
    departments = [dict(code=c, name=n) for c, n in C.DEPARTMENTS]
    programs = [dict(code=c, department_code=d, name=n, degree=deg, total_credits_required=tot, min_gpa=gpa) for c, d, n, deg, tot, gpa in C.PROGRAMS]
    courses = [dict(code=code, subject=code.split()[0], number=code.split()[1], title=title, description=desc, credit_hours=cr,
                    level=C.course_level(code), is_active=code not in C.RETIRED) for code, title, cr, desc in C.COURSES]
    prereqs = [dict(course_code=code, required_course_code=req, min_grade=mg, group_number=gi)
               for code, groups in C.PREREQUISITES.items() for gi, group in enumerate(groups, start=1) for req, mg in group]
    degree_req, category_req = [], []
    for prog, plan in C.DEGREE_PLANS.items():
        for code, cat, term_no in plan["required"]:
            degree_req.append(dict(program_code=prog, course_code=code, category=cat, is_required=True, suggested_term_number=term_no))
        for cat in ("elective", "general_education"):
            for code in plan[cat]:
                degree_req.append(dict(program_code=prog, course_code=code, category=cat, is_required=False, suggested_term_number=None))
        for cat, mn in C.CATEGORY_MINIMUMS[prog].items():
            category_req.append(dict(program_code=prog, category=cat, min_credits=mn))

    # ---------------------------------------------------------------- people
    people = People(rng)
    students: list[dict] = []
    instructors: list[dict] = []

    def sex() -> str:
        return rng.choices("MFX", weights=[48, 48, 4])[0]

    # undergraduates: admit term weighted toward recent years; status depends on how long ago they entered
    undergrad_admits = ["202180"] * 20 + ["202210"] * 5 + ["202280"] * 25 + ["202310"] * 5 + ["202380"] * 30 + ["202410"] * 6 \
        + ["202480"] * 35 + ["202510"] * 8 + ["202580"] * 45 + ["202610"] * 10 + ["202680"] * 60

    def undergrad(prog: str, out: list[dict]) -> None:
        admit = rng.choice(undergrad_admits)
        admit_seq = term_by_code[admit]["sequence"]
        entry = rng.choices(["first_time", "transfer", "readmit"], weights=[80, 15, 5])[0]
        age = rng.choice([18, 18, 18, 19, 19, 20]) + (rng.randint(1, 4) if entry != "first_time" else 0)
        p = people.add(sex(), int(admit[:4]) - age)
        terms_in = current_seq - admit_seq  # 0 for this fall's new students
        expected_seq = admit_seq + 7 - (2 if entry == "transfer" else 0)
        r = rng.random()
        # 2026-11-02: graduation needs seven completed terms (the prerequisite chains take seven; six for a transfer student,
        # who brings two semesters), and a graduate's expected term is the term they finished, which is over. Before, six-term
        # entrants could be "graduated" with the in-progress term as their expected term: nine students moved to active and
        # one graduate's term moved back one; no other row changed.
        if terms_in >= 8 and r < 0.70:
            status = "graduated"
            expected_seq = min(expected_seq, current_seq - 1)
        elif terms_in >= (6 if entry == "transfer" else 7) and r < 0.35:
            status = "graduated"
            expected_seq = min(expected_seq, current_seq - 1)
        elif r > 0.92:
            status = rng.choice(["withdrawn", "withdrawn", "leave_of_absence", "suspended", "dismissed"])
        else:
            status = "active"
            if expected_seq < current_seq + 1:
                expected_seq = current_seq + rng.choice([1, 1, 2])  # delayed graduation, still active
        residency = rng.choices(["resident", "nonresident", "international"], weights=[60, 28, 12])[0]
        out.append(dict(university_id=p["university_id"], program_code=prog, status=status, entry_type=entry, residency=residency,
                        admit_term_code=admit, expected_graduation_term_code=seq_to_code.get(expected_seq)))

    def graduate(prog: str, admit: str, out: list[dict]) -> dict:
        p = people.add(sex(), int(admit[:4]) - rng.randint(22, 30))
        residency = rng.choices(["resident", "nonresident", "international"], weights=[35, 20, 45])[0]
        out.append(dict(university_id=p["university_id"], program_code=prog, status="active", entry_type="first_time", residency=residency,
                        admit_term_code=admit, expected_graduation_term_code=seq_to_code[term_by_code[admit]["sequence"] + 3]))
        return p

    for prog, n in (("BSCS", 150), ("BSENG", 120)):
        for _ in range(n):
            undergrad(prog, students)

    # graduate students: half entered Fall 2025, half Fall 2026; three of each program's Fall 2025 entrants are teaching assistants
    tas: list[tuple[dict, str]] = []
    for prog, dept in (("MSCS", "CS"), ("MSENG", "ENG")):
        for i in range(15):
            admit = "202580" if i < 8 else "202680"
            p = graduate(prog, admit, students)
            if i < 3:
                tas.append((p, dept))
                instructors.append(dict(university_id=p["university_id"], department_code=dept, rank="ta", is_active=True,
                                        hire_date=term_by_code[admit]["start_date"]))

    # faculty: everyone was hired before the first lecture term, except one new assistant in CS and in ENG (Fall 2025);
    # the first CS and ENG instructor listed retired after Spring 2025
    for dept, n in INSTRUCTOR_COUNTS.items():
        for i in range(n):
            rank = rng.choice(RANK_POOL)
            y0, y1 = HIRE_YEARS[rank]
            hire_year = rng.randint(y0, y1)
            p = people.add(sex(), hire_year - rng.randint(28, 40), phone_rate=0.8)
            retired = dept in ("CS", "ENG") and i == 0
            if retired:
                rank, hire_year = "professor", rng.randint(1990, 2000)
            elif dept in ("CS", "ENG") and i == n - 1:
                rank, hire_year = "assistant", 2025
            instructors.append(dict(university_id=p["university_id"], department_code=dept, rank=rank, is_active=not retired,
                                    hire_date=date(hire_year, 8, 16)))

    # ---------------------------------------------------------------- lectures
    lectures = lecture_rows(rng, LECTURE_TERMS, instructors, term_by_code)
    # the former instructors and the earlier terms come after the frozen six terms, so those rows never change (append-only history)
    for dept, rank, hire_year in FORMER_INSTRUCTORS:
        p = people.add(sex(), hire_year - rng.randint(28, 40), phone_rate=0.8)
        instructors.append(dict(university_id=p["university_id"], department_code=dept, rank=rank, is_active=False, hire_date=date(hire_year, 8, 16)))
    lectures += lecture_rows(rng, EARLIER_LECTURE_TERMS, instructors, term_by_code)
    lectures.sort(key=lambda l: (l["term_code"], int(l["crn"])))

    # 2026-11-05: three more cohorts of each program, drawn after everything above so no earlier row moves; their records are
    # simulated after the original students', who keep their sections and grades and fill first
    added: list[dict] = []
    for prog, n in EXTRA_STUDENTS.items():
        for i in range(n):
            if DEGREE_OF[prog] == "BS":
                undergrad(prog, added)
            else:
                graduate(prog, "202580" if i < n * 8 // 15 else "202680", added)

    people.rows.sort(key=lambda r: r["university_id"])
    students.sort(key=lambda r: r["university_id"])
    added.sort(key=lambda r: r["university_id"])
    instructors.sort(key=lambda r: r["university_id"])

    # the added students need more seats than the frozen sections hold: a dry run with unlimited seats measures each term's demand
    # for each course, and new sections (higher CRNs, own random stream) cover the shortfall with SEAT_HEADROOM to spare
    loose = [dict(l, capacity=100_000) for l in lectures]
    dry, _ = generate_records(seed, terms, students + added, loose)
    by_crn = {(l["term_code"], l["crn"]): l["course_code"] for l in lectures}
    demand: dict[tuple[str, str], int] = {}
    for e in dry:
        key = (e["term_code"], by_crn[(e["term_code"], e["crn"])])
        demand[key] = demand.get(key, 0) + 1
    have: dict[tuple[str, str], int] = {}
    for l in lectures:
        if not l["is_cancelled"]:
            have[(l["term_code"], l["course_code"])] = have.get((l["term_code"], l["course_code"]), 0) + l["capacity"]
    need = {k: int(v * SEAT_HEADROOM) + 1 for k, v in demand.items() if v * SEAT_HEADROOM > have.get(k, 0)}
    hire_rng = random.Random(f"{seed}-hires")

    def hire(dept: str) -> dict:
        rank = hire_rng.choice(["lecturer", "lecturer", "adjunct", "assistant"])
        year = hire_rng.randint(2014, 2020)
        p = people.add(sex(), year - hire_rng.randint(28, 40), phone_rate=0.8)
        row = dict(university_id=p["university_id"], department_code=dept, rank=rank, is_active=True, hire_date=date(year, 8, 16))
        instructors.append(row)
        return row

    lectures += added_sections(random.Random(f"{seed}-sections"), lectures, instructors, term_by_code, need, hire)
    lectures.sort(key=lambda l: (l["term_code"], int(l["crn"])))
    people.rows.sort(key=lambda r: r["university_id"])
    instructors.sort(key=lambda r: r["university_id"])
    enrollment, transfer_credit = generate_records(seed, terms, students + added, lectures)
    students = sorted(students + added, key=lambda r: r["university_id"])
    salaries(seed, instructors)
    lecture_staff = staff_rows(seed, lectures, instructors, enrollment, terms)
    grade_submission = submission_rows(seed, lectures, enrollment, terms)
    return {
        "department": departments, "program": programs, "academic_term": terms, "person": people.rows, "student": students,
        "instructor": instructors, "course": courses, "course_prerequisite": prereqs, "degree_requirement": degree_req,
        "program_category_requirement": category_req, "lecture": lectures, "enrollment": enrollment, "transfer_credit": transfer_credit,
        "lecture_staff": lecture_staff, "grade_submission": grade_submission,
    }


def capacity_range(code: str) -> tuple[int, int]:
    subject, number = code.split()
    level = C.course_level(code)
    if level == "graduate":
        return (15, 25)
    if level == "upper_division":
        return (30, 40)
    if subject in ("CS", "ENG", "MATH", "PHYS") and number[0] == "2":
        return (45, 60)
    if subject in ("CS", "ENG", "MATH", "PHYS"):
        return (80, 120)
    return (60, 100)


def meeting_patterns(code: str, cr: int) -> list[tuple]:
    if cr >= 6:
        return list(THESIS)
    if C.course_level(code) == "graduate":
        return TR75[4:] + MW75_EVE
    if cr == 4:
        return list(MTWR50)
    return MWF50 + TR75 + MW75_EVE


def added_sections(rng: random.Random, lectures: list[dict], instructors: list[dict], term_by_code: dict,
                   need: dict[tuple[str, str], int], hire) -> list[dict]:
    """New sections (2026-11-05) appended after a term's existing CRNs until each (term, course) has `need` seats: the same rules
    as lecture_rows (department, hired by the term's start, active or up to Spring 2025, TAs only on 1000-level courses, at most
    MAX_SECTIONS_PER_INSTRUCTOR, no overlapping sections for an instructor or a room). When nobody in the department is free,
    `hire(department)` adds an instructor (appended to `instructors`). Existing rows are never touched."""
    by_dept: dict[str, list[dict]] = {}
    for ins in instructors:
        by_dept.setdefault(ins["department_code"], []).append(ins)
    credits = {code: cr for code, _, cr, _ in C.COURSES}
    out: list[dict] = []
    for term_code in sorted({t for t, _ in need}):
        term = term_by_code[term_code]
        mine = [l for l in lectures if l["term_code"] == term_code]
        crn = max(int(l["crn"]) for l in mine) + 1
        load: dict[str, int] = {}
        busy: dict[str, list[tuple]] = {}
        room_busy: dict[str, list[tuple]] = {}
        seats: dict[str, int] = {}
        count: dict[str, int] = {}
        for l in mine:
            s = (l["days"], l["start_time"], l["end_time"])
            load[l["instructor_university_id"]] = load.get(l["instructor_university_id"], 0) + 1
            busy.setdefault(l["instructor_university_id"], []).append(s)
            room_busy.setdefault(l["room"], []).append(s)
            count[l["course_code"]] = count.get(l["course_code"], 0) + 1
            if not l["is_cancelled"]:
                seats[l["course_code"]] = seats.get(l["course_code"], 0) + l["capacity"]
        for code in sorted(c for t, c in need if t == term_code):
            subject, number = code.split()
            building = BUILDING.get(subject, "BH")
            lo, hi = capacity_range(code)
            while seats.get(code, 0) < need[(term_code, code)]:
                candidates = [i for i in by_dept[subject]
                              if i["hire_date"] <= term["start_date"]
                              and (i["is_active"] or term_code <= "202510")
                              and (i["rank"] != "ta" or number[0] == "1")]
                chosen = None
                patterns = meeting_patterns(code, credits[code])
                for attempt in range(2):
                    for pat in rng.sample(patterns, len(patterns)):
                        slot = (pat[0], pat[1], add_minutes(pat[1], pat[2]))
                        free = [i for i in candidates if load.get(i["university_id"], 0) < MAX_SECTIONS_PER_INSTRUCTOR
                                and not any(overlaps(slot, b) for b in busy.get(i["university_id"], []))]
                        rooms = [f"{building} {r}" for r in ROOMS[building] if not any(overlaps(slot, b) for b in room_busy.get(f"{building} {r}", []))]
                        if free and rooms:
                            least = min(load.get(i["university_id"], 0) for i in free)
                            chosen = (rng.choice([i for i in free if load.get(i["university_id"], 0) == least]), slot, rng.choice(rooms))
                            break
                    if chosen is not None or attempt == 1:
                        break
                    new = hire(subject)                     # nobody free: the department hires
                    by_dept[subject].append(new)
                    candidates.append(new)
                if chosen is None:
                    raise RuntimeError(f"no room for an added section of {code} in {term_code}")
                ins, slot, room = chosen
                load[ins["university_id"]] = load.get(ins["university_id"], 0) + 1
                busy.setdefault(ins["university_id"], []).append(slot)
                room_busy.setdefault(room, []).append(slot)
                count[code] = count.get(code, 0) + 1
                cap = rng.randrange(lo, hi + 1, 5)
                seats[code] = seats.get(code, 0) + cap
                out.append(dict(term_code=term_code, crn=str(crn), course_code=code, section_number=f"M{count[code]:02d}",
                                instructor_university_id=ins["university_id"], days=slot[0], start_time=slot[1], end_time=slot[2],
                                room=room, capacity=cap, is_cancelled=False))
                crn += 1
    return out


def lecture_rows(rng: random.Random, term_codes: list[str], instructors: list[dict], term_by_code: dict) -> list[dict]:
    """Sections for the given terms: instructors of the course's department who were hired by the term's start (and, if no longer
    active, only up to Spring 2025), at most MAX_SECTIONS_PER_INSTRUCTOR each, no two of theirs overlapping, rooms likewise."""
    by_dept: dict[str, list[dict]] = {}
    for ins in instructors:
        by_dept.setdefault(ins["department_code"], []).append(ins)
    lectures: list[dict] = []
    for term_code in term_codes:
        term = term_by_code[term_code]
        crn = 10001
        load: dict[str, int] = {}
        busy: dict[str, list[tuple]] = {}      # instructor -> patterns taught
        room_busy: dict[str, list[tuple]] = {}  # room -> patterns
        for code, _title, cr, _desc in C.COURSES:
            if code in C.RETIRED and term_code > C.RETIRED[code]:
                continue
            if code in FALL_ONLY and term["term_type"] != "fall":
                continue
            if code in SPRING_ONLY and term["term_type"] != "spring":
                continue
            subject, number = code.split()
            level = C.course_level(code)
            n_sections = SECTION_COUNTS.get(code, 2 if level == "lower_division" else 1)
            dept = subject
            if level == "graduate":
                capacity_range = (15, 25)
            elif level == "upper_division":
                capacity_range = (30, 40)
            elif subject in ("CS", "ENG", "MATH", "PHYS") and number[0] == "2":
                capacity_range = (45, 60)
            elif subject in ("CS", "ENG", "MATH", "PHYS"):
                capacity_range = (80, 120)
            else:
                capacity_range = (60, 100)
            if cr >= 6:
                patterns = list(THESIS)
            elif level == "graduate":
                patterns = TR75[4:] + MW75_EVE
            elif cr == 4:
                patterns = list(MTWR50)
            else:
                patterns = MWF50 + TR75 + MW75_EVE
            building = BUILDING.get(subject, "BH")
            for s in range(1, n_sections + 1):
                candidates = [i for i in by_dept[dept]
                              if i["hire_date"] <= term["start_date"]
                              and (i["is_active"] or term_code <= "202510")
                              and (i["rank"] != "ta" or number[0] == "1")]
                chosen = None
                for pat in rng.sample(patterns, len(patterns)):
                    slot = (pat[0], pat[1], add_minutes(pat[1], pat[2]))
                    free = [i for i in candidates if load.get(i["university_id"], 0) < MAX_SECTIONS_PER_INSTRUCTOR
                            and not any(overlaps(slot, b) for b in busy.get(i["university_id"], []))]
                    if not free:
                        continue
                    least = min(load.get(i["university_id"], 0) for i in free)
                    ins = rng.choice([i for i in free if load.get(i["university_id"], 0) == least])
                    rooms = [f"{building} {r}" for r in ROOMS[building] if not any(overlaps(slot, b) for b in room_busy.get(f"{building} {r}", []))]
                    if not rooms:
                        continue
                    room = rng.choice(rooms)
                    chosen = (ins, slot, room)
                    break
                if chosen is None:
                    raise RuntimeError(f"no instructor or room for {code} in {term_code}")
                ins, slot, room = chosen
                load[ins["university_id"]] = load.get(ins["university_id"], 0) + 1
                busy.setdefault(ins["university_id"], []).append(slot)
                room_busy.setdefault(room, []).append(slot)
                lo, hi = capacity_range
                lectures.append(dict(term_code=term_code, crn=str(crn), course_code=code, section_number=f"M{s:02d}",
                                     instructor_university_id=ins["university_id"], days=slot[0], start_time=slot[1], end_time=slot[2],
                                     room=room, capacity=rng.randrange(lo, hi + 1, 5), is_cancelled=rng.random() < 0.02))
                crn += 1
    return lectures
