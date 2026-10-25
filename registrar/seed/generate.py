"""Simulate an NMSU-sized undergraduate population and everything the registrar records about it.

Output is a dict of table_name -> list[dict] with explicit integer ids, ready for bulk COPY.
Deterministic for a given seed. `scale` shrinks every population proportionally for quick test runs.
"""
from __future__ import annotations

import hashlib
import math
import random
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone, time

from faker import Faker

from . import catalog as C

UTC = timezone.utc
TODAY = date(2026, 10, 19)

GRADE_POINTS = {"A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7, "C+": 2.3, "C": 2.0, "C-": 1.7,
                "D+": 1.3, "D": 1.0, "D-": 0.7, "F": 0.0}
GRADE_THRESHOLDS = [(1.0, "A"), (0.7, "A-"), (0.45, "B+"), (0.15, "B"), (-0.1, "B-"), (-0.35, "C+"),
                    (-0.65, "C"), (-0.85, "C-"), (-1.05, "D+"), (-1.25, "D"), (-1.45, "D-")]
PREREQ_PASS = {"A", "A-", "B+", "B", "B-", "C+", "C", "C-"}
EARNS_CREDIT = set(GRADE_POINTS) - {"F"} | {"S"}

# Named prerequisite chains among catalog.NAMED_COURSES: (subject, number) -> [(subject, number, type)]
NAMED_PREREQS = {
    ("CS", "1210"): [("CS", "1120", "p")], ("CS", "2210"): [("CS", "1210", "p")], ("CS", "2710"): [("CS", "1210", "p")],
    ("CS", "3210"): [("CS", "2210", "p"), ("CS", "2710", "p")], ("CS", "3710"): [("CS", "2210", "p")],
    ("CS", "3720"): [("CS", "3710", "p")], ("CS", "4210"): [("CS", "3210", "p")], ("CS", "4320"): [("CS", "3210", "p")],
    ("CS", "4710"): [("CS", "3210", "p"), ("MATH", "2415", "p")], ("CS", "4910"): [("CS", "4320", "p")],
    ("MATH", "1250"): [("MATH", "1220", "p")], ("MATH", "1430"): [("MATH", "1220", "p")],
    ("MATH", "1511"): [("MATH", "1250", "p")], ("MATH", "1521"): [("MATH", "1511", "p")],
    ("MATH", "2530"): [("MATH", "1521", "p")], ("MATH", "2415"): [("MATH", "1521", "p")],
    ("MATH", "3920"): [("MATH", "1521", "p")], ("STAT", "2510"): [("MATH", "1220", "p")],
    ("CHEM", "1225"): [("CHEM", "1215", "p")], ("CHEM", "2115"): [("CHEM", "1225", "p")],
    ("CHEM", "2125"): [("CHEM", "2115", "p")], ("BIOL", "1120"): [("BIOL", "1110", "p")],
    ("BIOL", "2210"): [("BIOL", "2110", "p")], ("BIOL", "2610"): [("BIOL", "1110", "p")],
    ("PHYS", "1310"): [("MATH", "1511", "c")], ("PHYS", "1320"): [("PHYS", "1310", "p")],
    ("PHYS", "1230"): [("MATH", "1250", "p")], ("ENGL", "2210"): [("ENGL", "1110", "p")],
    ("ENGL", "2130"): [("ENGL", "1110", "p")], ("ENGL", "2310"): [("ENGL", "1110", "p")],
    ("ACCT", "2120"): [("ACCT", "2110", "p")], ("FIN", "3110"): [("ACCT", "2110", "p")],
    ("SPAN", "1120"): [("SPAN", "1110", "p")], ("HON", "2130"): [("HON", "1120", "p")],
}

# AP subject -> (subject, number)
AP_MAP = [("English Language", ("ENGL", "1110")), ("Calculus AB", ("MATH", "1511")), ("US History", ("HIST", "1110")),
          ("Psychology", ("PSY", "1110")), ("Biology", ("BIOL", "1110")), ("US Government", ("GOVT", "1110")),
          ("Spanish Language", ("SPAN", "1120")), ("Chemistry", ("CHEM", "1215")), ("Statistics", ("MATH", "1350")),
          ("Computer Science A", ("CS", "1120")), ("World History", ("HIST", "1150")), ("Physics 1", ("PHYS", "1230"))]

MWF = [time(7, 30), time(8, 30), time(9, 30), time(10, 30), time(11, 30), time(12, 30), time(13, 30), time(14, 30), time(15, 30)]
TR = [time(7, 55), time(9, 0), time(10, 20), time(11, 45), time(13, 10), time(14, 35), time(16, 0)]
EVE = [time(17, 30), time(19, 0)]


def ascii_slug(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().replace(" ", "").replace("'", "")


def dt(d: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


def add_minutes(t: time, minutes: int) -> time:
    base = datetime(2000, 1, 1, t.hour, t.minute) + timedelta(minutes=minutes)
    return base.time()


class Generator:
    def __init__(self, scale: float = 1.0, seed: int = 42):
        self.scale = scale
        self.rng = random.Random(seed)
        Faker.seed(seed)
        self.fk_en = Faker("en_US")
        self.fk_es = Faker("es_MX")
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.ids: dict[str, int] = defaultdict(int)
        self.used_uids: set[int] = set()
        self.used_emails: set[str] = set()

    # ------------------------------------------------------------------ helpers
    def add(self, table: str, **row) -> dict:
        if "id" not in row:
            self.ids[table] += 1
            row["id"] = self.ids[table]
        self.rows[table].append(row)
        return row

    def r(self) -> float:
        return self.rng.random()

    def choice(self, seq):
        return self.rng.choice(seq)

    def wchoice(self, seq, weights):
        return self.rng.choices(seq, weights=weights, k=1)[0]

    def between(self, a: date, b: date) -> date:
        if b <= a:
            return a
        return a + timedelta(days=self.rng.randint(0, (b - a).days))

    def between_dt(self, a: date, b: date) -> datetime:
        d = self.between(a, b)
        return dt(d, self.rng.randint(7, 20), self.rng.randint(0, 59))

    # ------------------------------------------------------------------ terms
    def build_terms(self):
        self.terms = []
        seq = 0
        for ay in range(2021, 2027):
            specs = [
                (f"{ay}80", f"Fall {ay}", "fall", ay, date(ay, 8, 20), date(ay, 12, 11), date(ay, 4, 1), date(ay, 10, 30)),
                (f"{ay+1}10", f"Spring {ay+1}", "spring", ay, date(ay + 1, 1, 17), date(ay + 1, 5, 9), date(ay, 11, 1), date(ay + 1, 3, 31)),
            ]
            if ay + 1 <= 2026:
                specs.append((f"{ay+1}50", f"Summer {ay+1}", "summer", ay, date(ay + 1, 6, 1), date(ay + 1, 7, 31), date(ay + 1, 3, 15), date(ay + 1, 7, 6)))
            for code, name, ttype, year, start, end, reg_open, wd in specs:
                seq += 1
                t = self.add("academic_term", code=code, name=name, term_type=ttype, academic_year=year,
                             start_date=start, end_date=end, registration_opens=reg_open,
                             add_deadline=start + timedelta(days=6), drop_deadline=start + timedelta(days=13),
                             census_date=start + timedelta(days=20), withdraw_deadline=wd,
                             grades_due=end + timedelta(days=5), is_current=(code == "202680"), sequence=seq)
                self.terms.append(t)
        self.term_by_code = {t["code"]: t for t in self.terms}
        self.current = self.term_by_code["202680"]
        self.future = self.term_by_code["202710"]
        self.history_terms = [t for t in self.terms if t["sequence"] < self.current["sequence"]]
        self.fall_terms = [t for t in self.terms if t["term_type"] == "fall"]
        for t in self.terms:
            s, e = t["start_date"], t["end_date"]
            ev = [("Classes begin", "milestone", s, None), ("Last day to add", "deadline", t["add_deadline"], None),
                  ("Last day to drop without a W", "deadline", t["drop_deadline"], None),
                  ("Census date", "milestone", t["census_date"], None),
                  ("Last day to withdraw with a W", "deadline", t["withdraw_deadline"], None),
                  ("Final examinations", "finals", e - timedelta(days=4), e),
                  ("Grades due from instructors", "deadline", t["grades_due"], None)]
            if t["term_type"] == "fall":
                ev += [("Labor Day (no classes)", "holiday", date(s.year, 9, 1) + timedelta(days=(7 - date(s.year, 9, 1).weekday()) % 7), None),
                       ("Thanksgiving break", "holiday", date(s.year, 11, 26), date(s.year, 11, 28)),
                       ("Commencement", "commencement", e + timedelta(days=1), None)]
            elif t["term_type"] == "spring":
                ev += [("Martin Luther King Jr. Day (no classes)", "holiday", date(s.year, 1, 20), None),
                       ("Spring break", "holiday", date(s.year, 3, 16), date(s.year, 3, 20)),
                       ("Commencement", "commencement", e + timedelta(days=1), None)]
            else:
                ev += [("Independence Day (no classes)", "holiday", date(s.year, 7, 4), None)]
            for name, etype, d, d2 in ev:
                self.add("academic_calendar_event", term_id=t["id"], name=name, event_type=etype, event_date=d, end_date=d2, description=None)

    # ------------------------------------------------------------------ structure
    def build_structure(self):
        first_term = self.terms[0]
        self.college_by_code = {}
        for code, name in C.COLLEGES:
            self.college_by_code[code] = self.add("college", code=code, name=name, dean_person_id=None)
        self.dept_by_code, self.dept_size = {}, {}
        self.subject_by_code = {}
        for code, name, ccode, subjects, size in C.DEPARTMENTS:
            d = self.add("department", college_id=self.college_by_code[ccode]["id"], code=code, name=name, chair_person_id=None)
            self.dept_by_code[code] = d
            self.dept_size[code] = size
            for s in subjects:
                self.subject_by_code[s] = self.add("subject", code=s, name=C.SUBJECTS[s], department_id=d["id"])
        self.dept_of_subject = {s: next(dc for dc, _, _, subs, _ in C.DEPARTMENTS if s in subs) for s in self.subject_by_code}

        # courses
        self.course_by_key: dict[tuple[str, str], dict] = {}
        self.courses_by_subject: dict[str, list[dict]] = defaultdict(list)
        self.gen_ed_by_area: dict[str, list[dict]] = defaultdict(list)
        for subj, num, title, credits, area in C.NAMED_COURSES:
            self._add_course(subj, num, title, credits, area, first_term)
        for subj in self.subject_by_code:
            size = self.dept_size[self.dept_of_subject[subj]]
            factor = math.sqrt(size)
            per_level = {1: max(2, round(3 * factor)), 2: max(3, round(4 * factor)), 3: max(4, round(6 * factor)), 4: max(3, round(4 * factor))}
            existing = {k[1] for k in self.course_by_key if k[0] == subj}
            for lvl, n in per_level.items():
                have = sum(1 for num in existing if num[0] == str(lvl))
                templates = list(C.COURSE_TITLE_TEMPLATES[lvl])
                self.rng.shuffle(templates)
                candidates = [f"{lvl}{h}{t}0" for h in range(1, 8) for t in (1, 2, 3, 5)]
                self.rng.shuffle(candidates)
                made = 0
                for num in candidates:
                    if made >= max(0, n - have):
                        break
                    if num in existing:
                        continue
                    title = templates[made % len(templates)].format(s=C.SUBJECTS[subj])
                    if made >= len(templates):
                        title += f" {made // len(templates) + 1}"
                    credits = 4 if (lvl <= 2 and self.r() < 0.15) else (1 if self.r() < 0.04 else 3)
                    self._add_course(subj, num, title, credits, None, first_term)
                    existing.add(num)
                    made += 1
        # prerequisites
        self.prereqs: dict[int, list[list[tuple[int, str]]]] = defaultdict(list)  # course_id -> groups -> [(req_course_id, type)]
        for (subj, num), reqs in NAMED_PREREQS.items():
            c = self.course_by_key[(subj, num)]
            for rs, rn, typ in reqs:
                rc = self.course_by_key[(rs, rn)]
                self._add_prereq(c, rc, "prerequisite" if typ == "p" else "corequisite")
        for subj, courses in self.courses_by_subject.items():
            by_level = defaultdict(list)
            for c in courses:
                by_level[int(c["course_number"][0])].append(c)
            for c in courses:
                if (subj, c["course_number"]) in NAMED_PREREQS:
                    continue
                lvl = int(c["course_number"][0])
                if lvl >= 2 and by_level[lvl - 1] and self.r() < 0.8:
                    self._add_prereq(c, self.choice(by_level[lvl - 1]), "prerequisite")
                if lvl >= 3 and by_level[lvl - 1] and self.r() < 0.3:
                    other = self.choice(by_level[lvl - 1])
                    if all(other["id"] != g[0][0] for g in self.prereqs[c["id"]]):
                        self._add_prereq(c, other, "prerequisite")
        # buildings & rooms
        self.rooms = []
        for code, name, nrooms, (lo, hi) in C.BUILDINGS:
            b = self.add("building", code=code, name=name)
            for i in range(nrooms):
                cap = self.rng.randint(lo, hi)
                rtype = "lecture_hall" if cap >= 100 else ("lab" if self.r() < 0.15 else ("seminar" if cap < 20 else "classroom"))
                floor = 1 + i // 12
                self.rooms.append(self.add("room", building_id=b["id"], room_number=f"{floor}{(i % 12) + 1:02d}", capacity=cap, room_type=rtype, has_av=self.r() < 0.92))
        # programs
        self.programs = []
        self.program_core: dict[int, list[int]] = {}
        self.program_support: dict[int, list[int]] = {}
        self.program_electives: dict[int, list[int]] = {}
        self.major_weights = []
        for code, name, degree, dept, subj, weight in C.MAJORS:
            p = self.add("program", department_id=self.dept_by_code[dept]["id"], code=code, name=name, degree_type=degree,
                         program_type="major", total_credits_required=120, min_gpa=2.0,
                         upper_division_credits_required=36 if degree else 0, residency_credits_required=30,
                         cip_code=None, is_active=True)
            self.programs.append(p)
            self.major_weights.append(weight)
            self._define_major_requirements(p, subj, undeclared=(degree is None))
        self.majors = list(self.programs)
        self.minors = []
        for code, name, dept, subj in C.MINORS:
            p = self.add("program", department_id=self.dept_by_code[dept]["id"], code=code, name=name, degree_type=None,
                         program_type="minor", total_credits_required=18, min_gpa=2.0, upper_division_credits_required=9,
                         residency_credits_required=9, cip_code=None, is_active=True)
            self.minors.append(p)
            courses = sorted(self.courses_by_subject[subj], key=lambda c: c["course_number"])
            pick = courses[:3] + [c for c in courses if c["course_number"][0] in "34"][:3]
            self.program_core[p["id"]] = [c["id"] for c in pick]
            self.program_support[p["id"]] = []
            self.program_electives[p["id"]] = []
            for ft in self.fall_terms:
                req = self.add("program_requirement", program_id=p["id"], catalog_term_id=ft["id"], name="Minor Core",
                               requirement_type="core", min_credits=18, min_courses=6, min_grade="C-", sort_order=1, description=None)
                for c in pick:
                    self.add("program_requirement_course", requirement_id=req["id"], course_id=c["id"], is_required=True)
        self.gen_ed_courses = {area: [c["id"] for c in cs] for area, cs in self.gen_ed_by_area.items()}
        self.all_courses = [c for cs in self.courses_by_subject.values() for c in cs]
        self.course_by_id = {c["id"]: c for c in self.all_courses}

    def _add_course(self, subj, num, title, credits, area, first_term):
        lvl = int(num[0])
        c = self.add("course", subject_id=self.subject_by_code[subj]["id"], course_number=num, title=title,
                     description=f"{title}. {C.SUBJECTS[subj]} course, {credits} credits.",
                     credits_min=credits, credits_max=credits, level="lower_division" if lvl <= 2 else "upper_division",
                     is_gen_ed=area is not None, gen_ed_area=area, is_repeatable=("Topics" in title or "Independent" in title),
                     is_active=True, effective_term_id=first_term["id"], retired_term_id=None)
        c["_subj"], c["_lvl"], c["_credits"] = subj, lvl, credits
        self.course_by_key[(subj, num)] = c
        self.courses_by_subject[subj].append(c)
        if area:
            self.gen_ed_by_area[area].append(c)
        return c

    def _add_prereq(self, course, required, ptype):
        group = len(self.prereqs[course["id"]]) + 1
        self.add("course_prerequisite", course_id=course["id"], required_course_id=required["id"], prereq_type=ptype,
                 min_grade="C-", group_number=group)
        self.prereqs[course["id"]].append([(required["id"], ptype)])

    def _define_major_requirements(self, p, subj, undeclared=False):
        courses = sorted(self.courses_by_subject[subj], key=lambda c: c["course_number"])
        by_level = defaultdict(list)
        for c in courses:
            by_level[c["_lvl"]].append(c)
        core = []
        if not undeclared:
            for lvl, n in ((1, 2), (2, 3), (3, 4), (4, 3)):
                pool = list(by_level[lvl])
                named = [c for c in pool if (subj, c["course_number"]) in {(s, n_) for s, n_, *_ in C.NAMED_COURSES}]
                rest = [c for c in pool if c not in named]
                self.rng.shuffle(rest)
                core += (named + rest)[:n]
        support = [self.course_by_key[k] for k in C.PROGRAM_SUPPORT.get(subj, [])] if not undeclared else []
        electives = [c for c in by_level[3] + by_level[4] if c not in core][:6]
        self.program_core[p["id"]] = [c["id"] for c in core]
        self.program_support[p["id"]] = [c["id"] for c in support]
        self.program_electives[p["id"]] = [c["id"] for c in electives]
        core_credits = sum(c["_credits"] for c in core) + sum(c["_credits"] for c in support)
        gen_credits = sum(v[1] for v in C.GEN_ED_AREAS.values())
        for ft in self.fall_terms:
            order = 0
            for area, (aname, cr, nc) in C.GEN_ED_AREAS.items():
                order += 1
                req = self.add("program_requirement", program_id=p["id"], catalog_term_id=ft["id"], name=f"General Education: {aname}",
                               requirement_type="general_education", min_credits=cr, min_courses=nc, min_grade="D-", sort_order=order, description=None)
                for c in self.gen_ed_by_area[area]:
                    self.add("program_requirement_course", requirement_id=req["id"], course_id=c["id"], is_required=False)
            if core:
                order += 1
                req = self.add("program_requirement", program_id=p["id"], catalog_term_id=ft["id"], name="Major Core",
                               requirement_type="core", min_credits=sum(c["_credits"] for c in core), min_courses=len(core), min_grade="C-", sort_order=order, description=None)
                for c in core:
                    self.add("program_requirement_course", requirement_id=req["id"], course_id=c["id"], is_required=True)
            if support:
                order += 1
                req = self.add("program_requirement", program_id=p["id"], catalog_term_id=ft["id"], name="Supporting Courses",
                               requirement_type="core", min_credits=sum(c["_credits"] for c in support), min_courses=len(support), min_grade="C-", sort_order=order, description=None)
                for c in support:
                    self.add("program_requirement_course", requirement_id=req["id"], course_id=c["id"], is_required=True)
            if electives:
                order += 1
                req = self.add("program_requirement", program_id=p["id"], catalog_term_id=ft["id"], name="Major Electives",
                               requirement_type="major_elective", min_credits=9, min_courses=3, min_grade="C-", sort_order=order, description="Choose three.")
                for c in electives:
                    self.add("program_requirement_course", requirement_id=req["id"], course_id=c["id"], is_required=False)
            order += 1
            self.add("program_requirement", program_id=p["id"], catalog_term_id=ft["id"], name="Free Electives",
                     requirement_type="free_elective", min_credits=max(0, 120 - gen_credits - core_credits - (9 if electives else 0)), min_courses=0, min_grade="D-", sort_order=order, description=None)
            order += 1
            self.add("program_requirement", program_id=p["id"], catalog_term_id=ft["id"], name="Residency",
                     requirement_type="residency", min_credits=30, min_courses=0, min_grade=None, sort_order=order,
                     description="At least 30 credits earned in residence.")

    # ------------------------------------------------------------------ people
    def make_person(self, kind: str, min_age: int, max_age: int, as_of: date, international=False) -> dict:
        es = self.r() < (0.58 if kind == "student" else 0.35)
        fk = self.fk_es if es else self.fk_en
        sex = "F" if self.r() < 0.53 else "M"
        first = fk.first_name_female() if sex == "F" else fk.first_name_male()
        last = fk.last_name()
        if es and self.r() < 0.3:
            last = f"{last} {fk.last_name()}"
        middle = (fk.first_name_female() if sex == "F" else fk.first_name_male()) if self.r() < 0.6 else None
        age = self.rng.randint(min_age, max_age)
        dob = as_of - timedelta(days=age * 365 + self.rng.randint(0, 364))
        while True:
            uid = self.rng.randint(800000000, 801999999)
            if uid not in self.used_uids:
                self.used_uids.add(uid)
                break
        base = ascii_slug(first[:1] + last.split()[0])[:12] or "user"
        email = f"{base}@nmsu.example"
        n = 1
        while email in self.used_emails:
            n += 1
            email = f"{base}{n}@nmsu.example"
        self.used_emails.add(email)
        pronouns = self.choice(["she/her", "he/him", "they/them", "she/they", "he/they"]) if self.r() < 0.18 else None
        if international:
            country = self.wchoice([c for c, _ in C.INTERNATIONAL_COUNTRIES], [w for _, w in C.INTERNATIONAL_COUNTRIES])
            ethnicity, race = "Not Hispanic or Latino", "Nonresident alien"
        else:
            country = "US"
            ethnicity = "Hispanic or Latino" if es or self.r() < 0.1 else "Not Hispanic or Latino"
            race = self.wchoice(["White", "American Indian or Alaska Native", "Black or African American", "Asian",
                                 "Two or more races", "Native Hawaiian or Other Pacific Islander"], [70, 12, 6, 5, 6, 1])
        p = self.add("person", university_id=str(uid), legal_first_name=first, legal_middle_name=middle, legal_last_name=last,
                     preferred_first_name=(first.split()[0] if " " in first and self.r() < 0.5 else (fk.first_name() if self.r() < 0.08 else None)),
                     pronouns=pronouns, date_of_birth=dob, legal_sex=sex, gender_identity=None,
                     ssn_hash=hashlib.sha256(f"{uid}-ssn".encode()).hexdigest(), citizenship_country=country,
                     ethnicity=ethnicity, race=race, email=email, personal_email=(fk.free_email() if self.r() < 0.7 else None),
                     phone=fk.phone_number()[:30], is_deceased=False)
        # address
        if international:
            city, state = fk.city(), None
        else:
            city, state = self.wchoice([(c, s) for c, s, _ in C.HOME_CITIES], [w for _, _, w in C.HOME_CITIES])
        self.add("address", person_id=p["id"], address_type="permanent", line1=fk.street_address()[:120], line2=None,
                 city=city, state=state, postal_code=(fk.postcode() if not international else None), country=country,
                 is_primary=True, effective_from=as_of - timedelta(days=self.rng.randint(30, 3000)), effective_to=None)
        if kind == "student" and city != "Las Cruces" and self.r() < 0.6:
            self.add("address", person_id=p["id"], address_type="local", line1=self.fk_en.street_address()[:120], line2=None,
                     city="Las Cruces", state="NM", postal_code=self.choice(["88001", "88003", "88005", "88011", "88012"]),
                     country="US", is_primary=False, effective_from=as_of, effective_to=None)
        if self.r() < 0.012:
            self.add("person_name_history", person_id=p["id"], old_first_name=first, old_middle_name=middle,
                     old_last_name=fk.last_name(), new_first_name=first, new_middle_name=middle, new_last_name=last,
                     reason=self.choice(["marriage", "legal name change", "correction", "divorce"]),
                     changed_at=self.between_dt(as_of, TODAY), changed_by_person_id=None)
        return p

    def build_staff_and_faculty(self):
        first_day = self.terms[0]["start_date"]
        self.instructors_by_dept: dict[str, list[dict]] = defaultdict(list)
        self.registrar_staff, self.advisors, self.staff_by_office = [], [], defaultdict(list)
        for office, n, titles in C.STAFF_OFFICES:
            for i in range(max(1, round(n * (self.scale ** 0.5)))):
                p = self.make_person("staff", 24, 64, first_day)
                s = self.add("staff", person_id=p["id"], office=office, title=titles[min(i, len(titles) - 1)] if i < 3 else self.choice(titles[3:] or titles), is_active=True)
                s["_person"] = p
                self.staff_by_office[office].append(s)
        self.registrar_staff = self.staff_by_office["registrar"]
        self.advisors = self.staff_by_office["advising"]
        # deans
        self.deans = {}
        for ccode, college in self.college_by_code.items():
            p = self.make_person("faculty", 45, 66, first_day)
            college["dean_person_id"] = p["id"]
            self.deans[ccode] = p
        # a few faculty per department up front; more are created on demand when sections need them
        self.chairs = {}
        for dcode in self.dept_by_code:
            for i in range(2):
                inst = self._new_instructor(dcode, rank="professor" if i == 0 else None)
                if i == 0:
                    self.dept_by_code[dcode]["chair_person_id"] = inst["person_id"]
                    self.chairs[dcode] = inst
        # system agent account person
        self.agent_person = self.add("person", university_id="800000001", legal_first_name="Registrar", legal_middle_name=None,
                                     legal_last_name="Agent", preferred_first_name=None, pronouns=None, date_of_birth=date(2026, 1, 1),
                                     legal_sex=None, gender_identity=None, ssn_hash=None, citizenship_country="US", ethnicity=None,
                                     race=None, email="registrar-agent@nmsu.example", personal_email=None, phone=None, is_deceased=False)
        self.used_uids.add(800000001)

    def _new_instructor(self, dcode: str, rank: str | None = None) -> dict:
        p = self.make_person("faculty", 27, 68, self.terms[0]["start_date"])
        rank = rank or self.wchoice(["professor", "associate_professor", "assistant_professor", "college_professor", "lecturer", "adjunct"], [18, 22, 20, 15, 12, 13])
        inst = self.add("instructor", person_id=p["id"], department_id=self.dept_by_code[dcode]["id"], rank=rank, is_active=True,
                        hire_date=self.between(date(1990, 8, 15), date(2026, 8, 15)))
        inst["_load"] = defaultdict(int)
        inst["_max"] = 2 if rank in ("professor", "associate_professor") else (4 if rank in ("college_professor", "lecturer") else 3)
        self.instructors_by_dept[dcode].append(inst)
        return inst

    def _new_ta(self, dcode: str) -> dict:
        p = self.make_person("faculty", 22, 32, self.terms[0]["start_date"])
        inst = self.add("instructor", person_id=p["id"], department_id=self.dept_by_code[dcode]["id"], rank="teaching_assistant", is_active=True,
                        hire_date=self.between(date(2021, 8, 15), date(2026, 8, 15)))
        inst["_load"] = defaultdict(int)
        inst["_max"] = 2
        self.instructors_by_dept[dcode + "#ta"].append(inst)
        return inst

    # ------------------------------------------------------------------ students
    def build_students(self):
        self.demand: dict[int, dict[int, list[tuple]]] = defaultdict(lambda: defaultdict(list))  # term -> course -> [(student, outcome, grade)]
        self.students: list[dict] = []
        self.transfer_insts = []
        for name, city, state, itype, w in C.TRANSFER_INSTITUTIONS:
            ti = self.add("transfer_institution", name=name, city=city, state=state, country="US" if state not in ("CH", "NL") else "MX",
                          institution_type=itype, ipeds_unit_id=None)
            ti["_w"] = w
            self.transfer_insts.append(ti)
        self.articulation: dict[tuple[int, int], dict] = {}
        n_first = round(2435 * self.scale)
        n_transfer = round(700 * self.scale)
        n_spring = round(345 * self.scale)
        for t in self.terms:
            if t["sequence"] > self.current["sequence"] or t["term_type"] == "summer":
                continue
            if t["term_type"] == "fall":
                growth = 1.0 + 0.02 * (t["academic_year"] - 2023)
                for _ in range(round(n_first * growth)):
                    self._simulate_student(t, "first_time")
                for _ in range(round(n_transfer * growth)):
                    self._simulate_student(t, "transfer")
            else:
                for _ in range(n_spring):
                    self._simulate_student(t, "transfer" if self.r() < 0.6 else "first_time")

    def _prereqs_ok(self, course_id: int, passed: dict, concurrent: set) -> bool:
        for group in self.prereqs.get(course_id, []):
            ok = False
            for req_id, typ in group:
                g = passed.get(req_id)
                if g is not None and (g in PREREQ_PASS or g == "T"):
                    ok = True
                elif typ == "corequisite" and req_id in concurrent:
                    ok = True
            if not ok:
                return False
        return True

    def _simulate_student(self, admit: dict, entry: str):
        international = self.r() < 0.04
        p = self.make_person("student", 17 if entry == "first_time" else 19, 20 if entry == "first_time" else 34, admit["start_date"], international)
        ability = self.rng.gauss(0, 1)
        hs_gpa = max(1.8, min(4.0, 3.05 + 0.42 * ability + self.rng.gauss(0, 0.3)))
        major = self.wchoice(self.majors, self.major_weights)
        honors = ability > 1.1 and self.r() < 0.5
        residency = "international" if international else ("resident" if self.r() < 0.78 else "nonresident")
        st = self.add("student", person_id=p["id"], level="undergraduate", status="active", entry_type=entry, residency=residency,
                      admit_term_id=admit["id"], catalog_term_id=(admit if admit["term_type"] == "fall" else self._prev_fall(admit))["id"],
                      expected_graduation_term_id=None, status_effective_term_id=admit["id"], first_generation=self.r() < 0.45,
                      high_school_name=(f"{self.choice(['Las Cruces', 'Mayfield', 'Onate', 'Centennial', 'Gadsden', 'Alamogordo', 'Deming', 'Franklin', 'Coronado', 'Eldorado', 'Cibola', 'Volcano Vista', 'Carlsbad', 'Hobbs'])} High School" if not international else None),
                      high_school_gpa=round(hs_gpa, 2), is_veteran=self.r() < 0.05, is_athlete=self.r() < 0.03, is_honors=honors,
                      sevis_id=(f"N00{self.rng.randint(10000000, 99999999)}" if international else None))
        st["_person"], st["_ability"], st["_major"], st["_admit"] = p, ability, major, admit
        st["_part_time"] = self.r() < 0.13
        self.students.append(st)
        self.add("emergency_contact", person_id=p["id"], name=self.fk_es.name() if self.r() < 0.55 else self.fk_en.name(),
                 relationship_to_person=self.choice(["mother", "father", "guardian", "spouse", "sibling"]), phone=self.fk_en.phone_number()[:30], email=None, priority=1)
        self.add("student_program", student_id=st["id"], program_id=major["id"], catalog_term_id=st["catalog_term_id"], declared_term_id=admit["id"],
                 ended_term_id=None, is_primary=True, status="declared", declared_at=dt(admit["start_date"] - timedelta(days=self.rng.randint(20, 120))))
        st["_programs"] = [self.rows["student_program"][-1]]
        if self.r() < 0.10:
            minor = self.choice(self.minors)
            self.add("student_program", student_id=st["id"], program_id=minor["id"], catalog_term_id=st["catalog_term_id"], declared_term_id=admit["id"],
                     ended_term_id=None, is_primary=False, status="declared", declared_at=dt(admit["start_date"]))
            st["_minor"] = minor
        passed: dict[int, str] = {}  # course_id -> best grade ('T' = transfer/test credit)
        earned = 0.0
        # transfer / test credit
        if entry == "transfer":
            self._transfer_credits(st, passed)
            earned += sum(r["awarded_credits"] for r in st.get("_transfer_rows", []))
        elif self.r() < 0.15:
            for subj_name, key in self.rng.sample(AP_MAP, self.rng.randint(1, 3)):
                c = self.course_by_key[key]
                if c["id"] in passed:
                    continue
                score = self.choice(["3", "4", "5"])
                passed[c["id"]] = "T"
                earned += c["_credits"]
                self.add("test_credit", student_id=st["id"], test_type="AP", test_subject=subj_name, score=score,
                         test_date=date(admit["start_date"].year, 5, 10), equivalent_course_id=c["id"], credits_awarded=c["_credits"],
                         posted_at=dt(admit["start_date"] - timedelta(days=30)))
        st["_passed"] = passed
        # term loop
        cum_attempted = cum_earned = cum_points = cum_gpa_credits = 0.0
        cum_earned += earned
        prev_standing = "good_standing"
        probation_streak = 0
        terms_enrolled = 0
        year = 0
        status = "active"
        program = major
        for t in self.terms:
            if t["sequence"] < admit["sequence"] or t["sequence"] > self.current["sequence"]:
                continue
            is_current = t["id"] == self.current["id"]
            if t["term_type"] == "summer":
                if self.r() > 0.12:
                    continue
                n_courses = self.rng.randint(1, 2)
            else:
                if t["term_type"] == "fall" and t["id"] != admit["id"]:
                    year += 1
                    cg = (cum_points / cum_gpa_credits) if cum_gpa_credits else 3.0
                    p_leave = (0.15 if year == 1 else 0.06) + (0.2 if cg < 2.0 else 0) + (0.05 if st["_part_time"] else 0) - 0.02 * max(0, ability)
                    if self.r() < p_leave:
                        status = "withdrawn"
                        st["status"], st["status_effective_term_id"] = status, t["id"]
                        break
                elif t["term_type"] == "spring" and self.r() < 0.03:
                    status = "withdrawn"
                    st["status"], st["status_effective_term_id"] = status, t["id"]
                    break
                # undeclared students declare; some students change major
                if program["degree_type"] is None and terms_enrolled >= 2 and self.r() < 0.5:
                    program = self._change_program(st, program, t)
                elif terms_enrolled >= 2 and self.r() < 0.03:
                    program = self._change_program(st, program, t)
                n_courses = self.rng.randint(2, 3) if st["_part_time"] else self.wchoice([3, 4, 5, 6], [5, 30, 50, 15])
            picks = self._pick_courses(st, program, passed, n_courses, year)
            if not picks:
                continue
            terms_enrolled += 1
            term_attempted = term_earned = term_points = term_gpa_credits = 0.0
            for c in picks:
                outcome, grade = self._outcome(ability, c, t, is_current, year)
                self.demand[t["id"]][c["id"]].append((st["id"], outcome, grade))
                if outcome == "dropped" or is_current:
                    continue
                cr = c["_credits"]
                term_attempted += cr
                if grade in GRADE_POINTS:
                    term_points += GRADE_POINTS[grade] * cr
                    term_gpa_credits += cr
                if grade in EARNS_CREDIT:
                    term_earned += cr
                    best = passed.get(c["id"])
                    if best is None or best == "T" or GRADE_POINTS.get(grade, 0) > GRADE_POINTS.get(best, 0):
                        passed[c["id"]] = grade
            if is_current:
                break
            cum_attempted += term_attempted
            cum_earned += term_earned
            cum_points += term_points
            cum_gpa_credits += term_gpa_credits
            term_gpa = round(term_points / term_gpa_credits, 3) if term_gpa_credits else None
            cum_gpa = round(cum_points / cum_gpa_credits, 3) if cum_gpa_credits else None
            if cum_gpa is not None and cum_gpa < 2.0:
                probation_streak += 1
                standing = "suspension" if probation_streak >= 3 and (term_gpa or 0) < 2.0 else "probation"
            else:
                probation_streak = 0
                standing = "deans_list" if (term_gpa or 0) >= 3.5 and term_gpa_credits >= 12 else "good_standing"
            classification = "freshman" if cum_earned < 30 else "sophomore" if cum_earned < 60 else "junior" if cum_earned < 90 else "senior"
            self.add("student_term_record", student_id=st["id"], term_id=t["id"], attempted_credits=term_attempted, earned_credits=term_earned,
                     gpa_credits=term_gpa_credits, term_gpa=term_gpa, cumulative_attempted=cum_attempted, cumulative_earned=cum_earned,
                     cumulative_gpa=cum_gpa, standing=standing, classification=classification, computed_at=dt(t["grades_due"] + timedelta(days=1), 2))
            if standing in ("probation", "suspension", "deans_list") and standing != prev_standing:
                self.add("academic_action", student_id=st["id"], term_id=t["id"], action_type=standing, action_date=t["grades_due"] + timedelta(days=2),
                         decided_by_person_id=self.choice(self.registrar_staff)["person_id"] if standing != "deans_list" else None, notes=None)
            prev_standing = standing
            if standing == "suspension":
                status = "suspended"
                st["status"], st["status_effective_term_id"] = status, t["id"]
                break
            # graduation
            core_ids = self.program_core[program["id"]]
            core_done = sum(1 for cid in core_ids if cid in passed)
            if t["term_type"] != "summer" and cum_earned >= 120 and (not core_ids or core_done >= len(core_ids) - 2) and program["degree_type"]:
                self._graduate(st, program, t, cum_gpa or 0.0, cum_earned)
                status = "graduated"
                break
        st["_cum_earned"], st["_cum_gpa"] = cum_earned, (cum_points / cum_gpa_credits if cum_gpa_credits else None)
        st["_classification"] = "freshman" if cum_earned < 30 else "sophomore" if cum_earned < 60 else "junior" if cum_earned < 90 else "senior"
        st["_program"] = program
        if status == "active":
            # expected graduation
            remaining_terms = max(1, math.ceil((120 - cum_earned) / 14))
            fs = [x for x in self.terms if x["sequence"] > self.current["sequence"] and x["term_type"] != "summer"]
            st["expected_graduation_term_id"] = (fs[min(remaining_terms - 1, len(fs) - 1)] if fs else self.future)["id"]
            if cum_earned >= 96 and self.r() < 0.7:
                self._graduation_application(st, program, self.future if cum_earned < 108 or self.r() < 0.6 else self.current)

    def _prev_fall(self, t):
        return max((x for x in self.fall_terms if x["sequence"] <= t["sequence"]), key=lambda x: x["sequence"], default=self.fall_terms[0])

    def _change_program(self, st, old_program, term):
        new = self.wchoice(self.majors, self.major_weights)
        while new["id"] == old_program["id"] or new["degree_type"] is None:
            new = self.wchoice(self.majors, self.major_weights)
        for sp in st["_programs"]:
            if sp["program_id"] == old_program["id"] and sp["ended_term_id"] is None:
                sp["ended_term_id"], sp["status"] = term["id"], "changed"
        row = self.add("student_program", student_id=st["id"], program_id=new["id"], catalog_term_id=self._prev_fall(term)["id"], declared_term_id=term["id"],
                       ended_term_id=None, is_primary=True, status="declared", declared_at=dt(term["start_date"] - timedelta(days=self.rng.randint(5, 60))))
        st["_programs"].append(row)
        return new

    def _pick_courses(self, st, program, passed, n, year):
        pid = program["id"]
        needed = []
        for area, ids in self.gen_ed_courses.items():
            _, cr, nc = C.GEN_ED_AREAS[area]
            done = sum(1 for cid in ids if cid in passed)
            if done < nc:
                needed += [(cid, 0) for cid in ids if cid not in passed]
        needed += [(cid, 1) for cid in self.program_support[pid] if cid not in passed]
        needed += [(cid, 1) for cid in self.program_core[pid] if cid not in passed]
        elect = [cid for cid in self.program_electives[pid] if cid not in passed]
        if sum(1 for cid in self.program_electives[pid] if cid in passed) < 3:
            needed += [(cid, 2) for cid in elect]
        if st.get("_minor"):
            needed += [(cid, 2) for cid in self.program_core[st["_minor"]["id"]] if cid not in passed]
        # a needed course blocked by an unmet prerequisite makes that prerequisite needed as well
        extra = []
        for cid, kind in needed:
            for group in self.prereqs.get(cid, []):
                if not any(passed.get(rid) in PREREQ_PASS or passed.get(rid) == "T" for rid, _ in group):
                    extra += [(rid, kind) for rid, _ in group if rid not in passed]
        needed += extra
        picked: list[dict] = []
        concurrent: set[int] = set()
        seen = set()
        scored = []
        for cid, kind in needed:
            if cid in seen:
                continue
            seen.add(cid)
            c = self.course_by_id[cid]
            score = c["_lvl"] * 10 + kind * 3 + self.rng.uniform(0, 12)
            scored.append((score, cid))
        scored.sort()
        for _, cid in scored:
            if len(picked) >= n:
                break
            if self._prereqs_ok(cid, passed, concurrent):
                picked.append(self.course_by_id[cid])
                concurrent.add(cid)
        tries = 0
        while len(picked) < n and tries < 60:
            tries += 1
            c = self.choice(self.all_courses)
            if c["id"] in passed or c["id"] in concurrent or c["_lvl"] > min(4, year + 2):
                continue
            if self._prereqs_ok(c["id"], passed, concurrent):
                picked.append(c)
                concurrent.add(c["id"])
        return picked

    def _outcome(self, ability, course, term, is_current, year):
        r = self.r()
        if r < 0.06:
            return "dropped", None
        if is_current:
            # withdrawals so far this term (withdraw deadline is Oct 30, today is Oct 19)
            return ("withdrawn", "W") if r < 0.085 else ("registered", None)
        if r < 0.10:
            return "withdrawn", "W"
        q = 0.6 * ability + self.rng.gauss(0, 0.8) + 0.35 - 0.12 * (course["_lvl"] - 1) + 0.08 * min(year, 3)
        for thr, g in GRADE_THRESHOLDS:
            if q >= thr:
                grade = g
                break
        else:
            grade = "F"
        if self.r() < 0.004:
            grade = "I"
        return "completed", grade

    def _transfer_credits(self, st, passed):
        inst = self.wchoice(self.transfer_insts, [i["_w"] for i in self.transfer_insts])
        target = self.rng.randint(18, 62)
        pool = [c for area in self.gen_ed_courses.values() for c in area] + [c["id"] for c in self.all_courses if c["_lvl"] <= 2 and self.r() < 0.2]
        self.rng.shuffle(pool)
        total = 0.0
        rows = []
        staff = self.choice(self.registrar_staff)
        for cid in pool:
            if total >= target:
                break
            if cid in passed:
                continue
            c = self.course_by_id[cid]
            rule = self.articulation.get((inst["id"], cid))
            if rule is None:
                rule = self.add("articulation_rule", institution_id=inst["id"], external_course_code=f"{c['_subj']} {self.rng.randint(1000, 2999)}",
                                external_course_title=c["title"], external_credits=c["_credits"], equivalent_course_id=cid,
                                effective_term_id=self.terms[0]["id"], expires_term_id=None)
                self.articulation[(inst["id"], cid)] = rule
            grade = self.wchoice(["A", "B", "C", "D"], [35, 40, 20, 5])
            status = "awarded" if grade != "D" else "denied"
            awarded = c["_credits"] if status == "awarded" else 0
            rows.append(self.add("transfer_credit", student_id=st["id"], institution_id=inst["id"], external_course_code=rule["external_course_code"],
                                 external_course_title=c["title"], external_credits=c["_credits"], external_grade=grade,
                                 external_term=f"{self.choice(['Fall', 'Spring'])} {st['_admit']['academic_year'] - self.rng.randint(1, 3)}",
                                 equivalent_course_id=cid, awarded_credits=awarded, status=status, articulation_rule_id=rule["id"],
                                 evaluated_by_person_id=staff["person_id"], evaluated_at=dt(st["_admit"]["start_date"] - timedelta(days=self.rng.randint(10, 90)))))
            if status == "awarded":
                passed[cid] = "T"
                total += c["_credits"]
        st["_transfer_rows"] = rows

    def _graduate(self, st, program, term, gpa, credits):
        honors = "summa_cum_laude" if gpa >= 3.9 else "magna_cum_laude" if gpa >= 3.7 else "cum_laude" if gpa >= 3.5 else "none"
        app = self._graduation_application(st, program, term, conferred=True)
        self.add("degree_awarded", student_id=st["id"], program_id=program["id"], term_id=term["id"], application_id=app["id"],
                 conferred_date=term["end_date"] + timedelta(days=1), honors=honors, final_gpa=round(gpa, 3), total_credits=credits,
                 diploma_printed_at=dt(term["end_date"] + timedelta(days=40)), diploma_mailed_at=dt(term["end_date"] + timedelta(days=45)))
        st["status"], st["status_effective_term_id"], st["expected_graduation_term_id"] = "graduated", term["id"], term["id"]
        for sp in st["_programs"]:
            if sp["program_id"] == program["id"] and sp["ended_term_id"] is None:
                sp["status"], sp["ended_term_id"] = "completed", term["id"]

    def _graduation_application(self, st, program, term, conferred=False):
        p = st["_person"]
        submitted = self.between_dt(term["start_date"] - timedelta(days=90), min(term["start_date"] + timedelta(days=30), TODAY))
        if conferred:
            status = "conferred"
        else:
            status = self.wchoice(["submitted", "under_review", "approved", "denied"], [40, 30, 25, 5])
        reviewer = self.choice(self.registrar_staff)["person_id"] if status != "submitted" else None
        return self.add("graduation_application", student_id=st["id"], program_id=program["id"], intended_term_id=term["id"], status=status,
                        diploma_name=f"{p['legal_first_name']} {p['legal_middle_name'] + ' ' if p['legal_middle_name'] else ''}{p['legal_last_name']}",
                        attending_commencement=self.r() < 0.8, submitted_at=submitted, reviewed_by_person_id=reviewer,
                        reviewed_at=(submitted + timedelta(days=self.rng.randint(3, 30))) if reviewer else None,
                        review_notes=("Missing: 3 credits upper-division electives." if status == "denied" else None))

    # ------------------------------------------------------------------ sections & enrollments
    def build_sections_and_enrollments(self):
        self.room_busy: set[tuple[int, int, str, time]] = set()
        crn_counter = defaultdict(lambda: 10000)
        # future term: mirror last spring's course offering counts, no students
        spring26 = self.term_by_code["202610"]
        for cid, lst in self.demand[spring26["id"]].items():
            self.demand[self.future["id"]][cid] = [None] * len(lst)
        enrollments_added = 0
        for t in self.terms:
            if t["id"] not in self.demand:
                continue
            is_current, is_future = t["id"] == self.current["id"], t["id"] == self.future["id"]
            for cid, reqs in self.demand[t["id"]].items():
                c = self.course_by_id[cid]
                typical = self._capacity(c)
                min_cap = 40 if (c["is_gen_ed"] and c["_lvl"] == 1) else {1: 20, 2: 15, 3: 12, 4: 8}[c["_lvl"]]
                n_sec = max(1, math.ceil(len(reqs) / typical))
                per = math.ceil(len(reqs) / n_sec)
                cap = max(min_cap, min(typical, math.ceil(per / 5) * 5))
                if is_current and self.r() < 0.3:
                    cap = max(min_cap, cap - 5)  # a few popular sections close and build waitlists
                sections = [self._make_section(c, t, i, cap, crn_counter) for i in range(n_sec)]
                if is_future:
                    continue
                self.rng.shuffle(reqs)
                filled = defaultdict(int)
                for i, (sid, outcome, grade) in enumerate(reqs):
                    sec = sections[i % n_sec]
                    if is_current and filled[sec["id"]] >= sec["capacity"] and outcome == "registered":
                        if filled[sec["id"]] < sec["capacity"] + sec["waitlist_capacity"]:
                            self._enroll(sid, sec, t, "waitlisted", None, filled[sec["id"]] - sec["capacity"] + 1)
                            filled[sec["id"]] += 1
                        continue
                    self._enroll(sid, sec, t, outcome, grade)
                    if outcome != "dropped":
                        filled[sec["id"]] += 1
                    enrollments_added += 1
                for sec in sections:
                    if is_current and filled[sec["id"]] >= sec["capacity"]:
                        sec["status"] = "closed"

    def _capacity(self, c):
        if c["is_gen_ed"] and c["_lvl"] == 1:
            return self.choice([60, 80, 100, 120, 150])
        return {1: self.choice([35, 40, 45, 60]), 2: self.choice([30, 35, 40, 45]), 3: self.choice([24, 28, 30, 35]), 4: self.choice([15, 18, 20, 25, 30])}[c["_lvl"]]

    def _make_section(self, c, t, i, cap, crn_counter):
        mode = self.wchoice(["in_person", "online", "hybrid"], [75, 15, 10])
        crn_counter[t["id"]] += 1
        secnum = f"D{i+1:02d}" if mode == "online" else f"M{i+1:02d}"
        sec = self.add("section", course_id=c["id"], term_id=t["id"], crn=str(crn_counter[t["id"]]), section_number=secnum, credits=c["_credits"],
                       capacity=cap, waitlist_capacity=10 if cap >= 30 else 5, instruction_mode=mode, status="open", campus="Las Cruces", notes=None)
        if mode != "online":
            if c["_credits"] >= 4 and self.r() < 0.5:
                days, start, length = "MTWR", self.choice(MWF), 50
            elif self.r() < 0.5:
                days, start, length = ("MWF", self.choice(MWF), 50)
            elif self.r() < 0.85:
                days, start, length = ("TR", self.choice(TR), 75)
            else:
                days = self.choice(["MW", "TR", "W", "R"])
                start, length = self.choice(EVE), (75 if len(days) == 2 else 150)
            room = None
            candidates = [r for r in self.rooms if r["capacity"] >= cap]
            self.rng.shuffle(candidates)
            for r in candidates[:40]:
                key = (t["id"], r["id"], days, start)
                if key not in self.room_busy:
                    self.room_busy.add(key)
                    room = r
                    break
            self.add("section_meeting", section_id=sec["id"], days=days, start_time=start, end_time=add_minutes(start, length),
                     room_id=room["id"] if room else None, meeting_type="lecture")
            if c["_credits"] >= 4 and self.r() < 0.6:
                lab_day = self.choice(["M", "T", "W", "R", "F"])
                lab_start = self.choice([time(13, 30), time(15, 0), time(16, 30)])
                labs = [r for r in self.rooms if r["room_type"] == "lab" and r["capacity"] >= min(cap, 30)]
                self.add("section_meeting", section_id=sec["id"], days=lab_day, start_time=lab_start, end_time=add_minutes(lab_start, 170),
                         room_id=self.choice(labs)["id"] if labs else None, meeting_type="lab")
        dcode = self.dept_of_subject[c["_subj"]]
        inst = next((x for x in self.instructors_by_dept[dcode] if x["_load"][t["id"]] < x["_max"]), None) or self._new_instructor(dcode)
        inst["_load"][t["id"]] += 1
        self.add("section_instructor", section_id=sec["id"], instructor_id=inst["id"], role="primary")
        sec["_instructor_person"] = inst["person_id"]
        if cap >= 80:
            ta = next((x for x in self.instructors_by_dept[dcode + "#ta"] if x["_load"][t["id"]] < x["_max"]), None) or self._new_ta(dcode)
            ta["_load"][t["id"]] += 1
            self.add("section_instructor", section_id=sec["id"], instructor_id=ta["id"], role="teaching_assistant")
        return sec

    def _enroll(self, sid, sec, t, outcome, grade, wl_position=None):
        reg_at = self.between_dt(t["registration_opens"], t["add_deadline"])
        status = {"registered": "registered", "dropped": "dropped", "withdrawn": "withdrawn", "completed": "completed", "waitlisted": "waitlisted"}[outcome]
        dropped_at = None
        if outcome == "dropped":
            dropped_at = self.between_dt(reg_at.date(), t["drop_deadline"])
        elif outcome == "withdrawn":
            dropped_at = self.between_dt(t["drop_deadline"] + timedelta(days=1), min(t["withdraw_deadline"], TODAY))
        e = self.add("enrollment", student_id=sid, section_id=sec["id"], term_id=t["id"], status=status, grading_basis="letter",
                     credits=sec["credits"], registered_at=reg_at, dropped_at=dropped_at, is_repeat=False)
        self.add("enrollment_event", enrollment_id=e["id"], event_type="waitlist_add" if outcome == "waitlisted" else "register",
                 occurred_at=reg_at, actor_person_id=None, channel="self_service", details={"crn": sec["crn"]})
        if outcome == "waitlisted":
            self.add("waitlist_entry", section_id=sec["id"], student_id=sid, position=wl_position, status="waiting", added_at=reg_at,
                     notified_at=None, expires_at=None, resolved_at=None)
        if outcome == "dropped":
            self.add("enrollment_event", enrollment_id=e["id"], event_type="drop", occurred_at=dropped_at, actor_person_id=None, channel="self_service", details=None)
        if outcome == "withdrawn":
            self.add("enrollment_event", enrollment_id=e["id"], event_type="withdraw", occurred_at=dropped_at, actor_person_id=None, channel="self_service", details=None)
        if grade is not None:
            posted = dropped_at if grade == "W" else dt(t["grades_due"] - timedelta(days=self.rng.randint(0, 4)), self.rng.randint(8, 18))
            self.add("grade", enrollment_id=e["id"], grade=grade, quality_points=GRADE_POINTS.get(grade), counts_in_gpa=grade in GRADE_POINTS,
                     earns_credit=grade in EARNS_CREDIT, is_final=grade != "I", posted_at=posted,
                     posted_by_person_id=sec["_instructor_person"] if grade != "W" else None,
                     incomplete_deadline=(t["end_date"] + timedelta(days=180)) if grade == "I" else None)
            if grade != "W":
                self.add("enrollment_event", enrollment_id=e["id"], event_type="grade_post", occurred_at=posted, actor_person_id=sec["_instructor_person"], channel="staff", details={"grade": grade})

    # ------------------------------------------------------------------ paperwork
    def build_paperwork(self):
        active = [s for s in self.students if s["status"] == "active"]
        alumni = [s for s in self.students if s["status"] == "graduated"]
        gone = [s for s in self.students if s["status"] in ("withdrawn", "suspended")]
        reg_people = [s["person_id"] for s in self.registrar_staff]
        bursar = [s["person_id"] for s in self.staff_by_office["bursar"]]
        conduct = [s["person_id"] for s in self.staff_by_office["dean_of_students"]]
        advisors = self.advisors
        # advisors
        for i, s in enumerate(active):
            a = advisors[i % len(advisors)]
            self.add("advisor_assignment", student_id=s["id"], advisor_person_id=a["person_id"], start_date=s["_admit"]["start_date"], end_date=None, is_primary=True, notes=None)
        # holds
        for s in active:
            r = self.r()
            if r < 0.045:
                self._hold(s, "financial", "bursar", self.choice(bursar), "Past-due balance on student account", blocks=(True, True, True))
            elif r < 0.075:
                self._hold(s, "advising", "advising", self.choice(advisors)["person_id"], "Must meet with advisor before registering", blocks=(True, False, False))
            elif r < 0.085:
                self._hold(s, "immunization", "student_health", None, "Missing MMR immunization record", blocks=(True, False, False))
            elif r < 0.089:
                self._hold(s, "conduct", "dean_of_students", self.choice(conduct), "Pending student conduct case", blocks=(True, True, True))
        for s in gone:
            if self.r() < 0.3:
                self._hold(s, "financial", "bursar", self.choice(bursar), "Unpaid balance at separation", blocks=(True, True, True))
        # released historical holds
        for s in self.rng.sample(active, k=max(1, len(active) // 12)):
            h = self._hold(s, self.choice(["financial", "advising", "immunization"]), "bursar", self.choice(bursar), "Resolved", blocks=(True, False, False))
            h["released_at"] = h["placed_at"] + timedelta(days=self.rng.randint(1, 60))
            h["released_by_person_id"] = h["placed_by_person_id"]
        # registration appointments for the future term
        ends = dt(self.future["add_deadline"], 23, 59)
        for s in active:
            day_offset = {"senior": 0, "junior": 3, "sophomore": 6, "freshman": 9}[s["_classification"]]
            if s["is_honors"] or s["is_athlete"] or s["is_veteran"]:
                day_offset = 0
            begins = dt(date(2026, 11, 2) + timedelta(days=day_offset + self.rng.randint(0, 2)), self.choice([7, 9, 11, 13, 15]))
            self.add("registration_appointment", student_id=s["id"], term_id=self.future["id"], begins_at=begins, ends_at=ends,
                     priority_group="honors" if s["is_honors"] else "athlete" if s["is_athlete"] else "veteran" if s["is_veteran"] else s["_classification"])
        # transcript requests
        for s in alumni + active + gone:
            p_req = 0.25 if s["status"] == "graduated" else 0.06
            if self.r() < p_req:
                for _ in range(self.rng.randint(1, 2)):
                    requested = self.between_dt(date(2024, 10, 1), TODAY)
                    ttype = "official" if self.r() < 0.8 else "unofficial"
                    blocked = any(h["student_id"] == s["id"] and h["blocks_transcript"] and h["released_at"] is None for h in self.rows["hold"][-4000:])
                    status = "on_hold" if blocked else self.wchoice(["fulfilled", "processing", "submitted", "cancelled"], [80, 8, 8, 4])
                    if (TODAY - requested.date()).days > 30 and status in ("processing", "submitted"):
                        status = "fulfilled"
                    self.add("transcript_request", person_id=s["person_id"], transcript_type=ttype,
                             delivery_method=self.wchoice(["electronic", "mail", "pickup"], [75, 20, 5]),
                             recipient_name=self.choice(["Self", "University of New Mexico Graduate Admissions", "Texas Tech University", "Employer HR", "Sandia National Laboratories", "White Sands Missile Range", "Las Cruces Public Schools", "UTEP Admissions", "El Paso Community College"]),
                             recipient_email=(self.fk_en.company_email() if self.r() < 0.7 else None), recipient_address=None,
                             purpose=self.choice(["graduate school", "employment", "transfer", "personal", "licensure"]),
                             status=status, fee=10.0 if ttype == "official" else 0.0, fee_paid=status != "submitted",
                             requested_at=requested, fulfilled_at=(requested + timedelta(days=self.rng.randint(0, 5))) if status == "fulfilled" else None,
                             processed_by_person_id=self.choice(reg_people) if status in ("fulfilled", "on_hold", "processing") else None,
                             hold_note="Transcript hold: unpaid balance" if blocked else None)
        # enrollment verifications
        for s in active:
            if self.r() < 0.09:
                requested = self.between_dt(self.current["start_date"] - timedelta(days=20), TODAY)
                load = "full_time" if not s["_part_time"] else self.choice(["half_time", "three_quarter_time"])
                status = self.wchoice(["fulfilled", "submitted"], [85, 15])
                self.add("enrollment_verification", student_id=s["id"], term_id=self.current["id"],
                         purpose=self.choice(["insurance", "loan_deferment", "employment", "housing", "scholarship", "immigration"]),
                         recipient_name=self.choice(["Blue Cross Blue Shield", "Navient", "Nelnet", "USAA", "Parent employer", "USCIS", "NM Higher Education Department"]),
                         recipient_contact=None, enrollment_load=load, status=status, requested_at=requested,
                         issued_at=(requested + timedelta(days=self.rng.randint(0, 3))) if status == "fulfilled" else None,
                         issued_by_person_id=self.choice(reg_people) if status == "fulfilled" else None)
        # FERPA
        for s in self.students:
            if self.r() < 0.22:
                rel = self.add("ferpa_release", student_id=s["id"], authorized_name=self.fk_es.name() if self.r() < 0.55 else self.fk_en.name(),
                               relationship_to_student=self.wchoice(["mother", "father", "guardian", "spouse", "grandparent"], [45, 35, 8, 8, 4]),
                               authorized_email=self.fk_en.free_email(), authorized_phone=self.fk_en.phone_number()[:30],
                               scope=self.wchoice(["all", "grades", "financial", "enrollment"], [50, 25, 20, 5]), passphrase_hash=hashlib.sha256(str(self.r()).encode()).hexdigest(),
                               effective_from=dt(s["_admit"]["start_date"] + timedelta(days=self.rng.randint(0, 200))),
                               revoked_at=dt(TODAY - timedelta(days=self.rng.randint(1, 300))) if self.r() < 0.06 else None)
                for _ in range(self.rng.randint(0, 2)):
                    self.add("disclosure_log", student_id=s["id"], disclosed_to=rel["authorized_name"], disclosed_to_type="parent",
                             data_categories=self.choice(["grades", "grades,enrollment", "enrollment", "financial"]), legal_basis="consent",
                             disclosed_at=self.between_dt(rel["effective_from"].date(), TODAY), disclosed_by_person_id=self.choice(reg_people), release_id=rel["id"])
            if self.r() < 0.03:
                self.add("ferpa_directory_optout", student_id=s["id"], opted_out_at=dt(s["_admit"]["start_date"] + timedelta(days=self.rng.randint(0, 60))), revoked_at=None)
            if self.r() < 0.004:
                self.add("disclosure_log", student_id=s["id"], disclosed_to=self.choice(["Third Judicial District Court", "US Department of Education OIG", "NCAA Enforcement", "Dona Ana County Sheriff"]),
                         disclosed_to_type="agency", data_categories="enrollment,grades", legal_basis=self.choice(["subpoena", "court_order", "health_safety_emergency"]),
                         disclosed_at=self.between_dt(date(2023, 1, 1), TODAY), disclosed_by_person_id=self.choice(reg_people), release_id=None)
        # petitions
        deans = list(self.deans.values())
        for s in active + gone:
            if self.r() < 0.03:
                ptype = self.wchoice(["late_add", "late_drop", "retroactive_withdrawal", "credit_overload", "residency_reclassification", "academic_standing_appeal", "grade_appeal", "requirement_waiver"],
                                     [15, 25, 15, 10, 8, 12, 8, 7])
                term = self.choice([self.current, self.term_by_code["202610"], self.term_by_code["202580"]])
                submitted = self.between_dt(term["start_date"], min(term["end_date"], TODAY))
                decided = self.r() < (0.5 if term["id"] == self.current["id"] else 0.95)
                status = self.wchoice(["approved", "denied"], [65, 35]) if decided else self.choice(["submitted", "under_review"])
                decider = self.choice(deans)["id"] if ptype in ("academic_standing_appeal", "grade_appeal") else self.choice(reg_people)
                self.add("petition", student_id=s["id"], petition_type=ptype, term_id=term["id"], section_id=None, status=status,
                         student_statement=self.fk_en.paragraph(nb_sentences=3), supporting_documents=None, submitted_at=submitted,
                         decided_by_person_id=decider if decided else None, decided_at=(submitted + timedelta(days=self.rng.randint(2, 21))) if decided else None,
                         decision_rationale=(self.choice(["Documented medical circumstances.", "Policy does not permit exception.", "Approved per department recommendation.", "Insufficient documentation."]) if decided else None))
        # grade changes on a sample of grades
        grades = self.rows["grade"]
        for g in self.rng.sample(grades, k=min(len(grades), max(1, round(len(grades) * 0.0012)))):
            if g["grade"] == "W":
                continue
            old = g["grade"]
            new = self.choice(["A", "B+", "B", "C+", "C"]) if old == "I" else self.choice([x for x in GRADE_POINTS if GRADE_POINTS[x] >= GRADE_POINTS.get(old, 0)])
            if new == old:
                continue
            requested = g["posted_at"] + timedelta(days=self.rng.randint(3, 120))
            self.add("grade_change", grade_id=g["id"], old_grade=old, new_grade=new, reason=self.choice(["Calculation error", "Late work accepted per policy", "Incomplete resolved", "Grade appeal upheld"]),
                     requested_by_person_id=g["posted_by_person_id"] or self.choice(reg_people), approved_by_person_id=self.choice(reg_people),
                     requested_at=requested, applied_at=requested + timedelta(days=self.rng.randint(1, 14)))
            g["grade"], g["quality_points"], g["is_final"], g["earns_credit"], g["counts_in_gpa"] = new, GRADE_POINTS.get(new), True, True, True
        # registration overrides on recent upper-division enrollments
        recent_ids = {self.current["id"], self.term_by_code["202610"]["id"], self.term_by_code["202580"]["id"]}
        sec_by_id = {s["id"]: s for s in self.rows["section"]}
        for e in self.rows["enrollment"]:
            if e["term_id"] in recent_ids and self.r() < 0.012:
                sec = sec_by_id[e["section_id"]]
                otype = self.wchoice(["prerequisite", "capacity", "time_conflict", "credit_overload", "level"], [55, 25, 10, 7, 3])
                granter = sec["_instructor_person"] if otype in ("prerequisite", "capacity") else self.choice(advisors)["person_id"]
                self.add("registration_override", student_id=e["student_id"], section_id=sec["id"], override_type=otype, granted_by_person_id=granter,
                         granted_at=e["registered_at"] - timedelta(days=self.rng.randint(0, 5)), expires_at=None,
                         reason=self.choice(["Equivalent coursework completed elsewhere", "Instructor permission", "Graduating senior", "Advisor approved overload"]), used_at=e["registered_at"])
                self.add("enrollment_event", enrollment_id=e["id"], event_type="override_applied", occurred_at=e["registered_at"], actor_person_id=granter, channel="staff", details={"override": otype})

    def _hold(self, s, htype, office, placer, reason, blocks):
        placed = self.between_dt(self.current["start_date"] - timedelta(days=120), TODAY) if s["status"] == "active" else self.between_dt(date(2023, 1, 1), TODAY)
        return self.add("hold", student_id=s["id"], hold_type=htype, placed_by_office=office, placed_by_person_id=placer, reason=reason, placed_at=placed,
                        released_at=None, released_by_person_id=None, blocks_registration=blocks[0], blocks_transcript=blocks[1], blocks_graduation=blocks[2])

    # ------------------------------------------------------------------ accounts
    def build_security(self):
        role_by_name = {}
        for name, desc in C.ROLES:
            role_by_name[name] = self.add("role", name=name, description=desc)
        perm_by_code = {code: self.add("permission", code=code, description=None) for code in C.PERMISSIONS}
        for rname, codes in C.ROLE_PERMISSIONS.items():
            for code in codes:
                self.add("role_permission", role_id=role_by_name[rname]["id"], permission_id=perm_by_code[code]["id"])
        granted = dt(date(2021, 8, 1))
        account_by_person = {}

        def account(person_id, username, role, dept=None, college=None, active=True):
            acc = account_by_person.get(person_id)
            if acc is None:
                acc = self.add("user_account", person_id=person_id, username=username, password_hash=None, is_active=active, mfa_enabled=self.r() < 0.6,
                               last_login_at=self.between_dt(date(2026, 8, 1), TODAY) if active else None)
                account_by_person[person_id] = acc
            self.add("user_role", user_id=acc["id"], role_id=role_by_name[role]["id"], department_id=dept, college_id=college, granted_at=granted, granted_by_user_id=None, revoked_at=None)
            return acc

        person_by_id = {p["id"]: p for p in self.rows["person"]}
        for s in self.students:
            p = person_by_id[s["person_id"]]
            account(p["id"], p["email"].split("@")[0], "student", active=s["status"] in ("active", "graduated"))
        for inst in self.rows["instructor"]:
            p = person_by_id[inst["person_id"]]
            account(p["id"], p["email"].split("@")[0], "instructor")
        for dcode, inst in self.chairs.items():
            account(inst["person_id"], person_by_id[inst["person_id"]]["email"].split("@")[0], "department_chair", dept=self.dept_by_code[dcode]["id"])
        for ccode, p in self.deans.items():
            account(p["id"], p["email"].split("@")[0], "dean", college=self.college_by_code[ccode]["id"])
        for office, staff in self.staff_by_office.items():
            for i, s in enumerate(staff):
                p = person_by_id[s["person_id"]]
                role = C.OFFICE_ROLE[office]
                if office == "registrar" and i < 2:
                    role = "registrar_admin"
                account(p["id"], p["email"].split("@")[0], role)
        account(self.agent_person["id"], "registrar-agent", "agent")
        self.add("audit_log", actor_user_id=account_by_person[self.agent_person["id"]]["id"], actor_type="system", action="seed",
                 table_name="*", record_id=None, before=None, after={"note": "synthetic data load", "scale": self.scale}, occurred_at=dt(TODAY, 12), ip_address=None, reason="initial seed")

    # ------------------------------------------------------------------ driver
    def run(self, log=print):
        log("terms"); self.build_terms()
        log("structure"); self.build_structure()
        log("staff & faculty"); self.build_staff_and_faculty()
        log("students (simulating term histories)"); self.build_students()
        log("sections & enrollments"); self.build_sections_and_enrollments()
        log("holds, requests, FERPA, petitions"); self.build_paperwork()
        log("accounts & roles"); self.build_security()
        # strip private keys
        for table, rows in self.rows.items():
            for r in rows:
                for k in [k for k in r if k.startswith("_")]:
                    del r[k]
        return self.rows
