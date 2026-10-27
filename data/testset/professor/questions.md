# Professor persona: proposed questions

Reviewed draft; cases were generated from it on 2026-10-27 (see `../README.md` for the final answer shapes,
which differ in small ways, and for the access-control intents added afterwards). Same conventions as the student set: every case has an `as_of`
clock (default 2026-11-20 18:00 UTC), the professor is authenticated (identified by `instructor_id` /
`university_id`, never stated in the question), two paraphrases per case, and a discrete `answer`.

At the default clock: Fall 2026 is in progress (withdraw deadline passed Oct 30, finals Dec 7-11, grades due
Dec 16, no Fall 2026 grades posted); "last semester" is Spring 2026 (or Summer 2026 if they taught it); Spring 2027
sections exist with registration open and no students enrolled yet.

Scope rule assumed: the `instructor` role has `enrollment.roster.read`, `grade.post`, `grade.change.request`,
`override.grant`. So every question is about the professor's own sections (primary instructor). Catalog and
calendar facts are public. Anything about other instructors' sections or department-wide numbers needs the
`department_chair` or `report.aggregate.read` permission and is listed separately at the end.

## Verification contract
Every answer is checked by a program, never by reading prose. So:
- The ground truth is computed from the database by the generator; the agent under test must return a JSON
  `answer` object for the case's intent (its prose reply is free). The grader compares field by field.
- Allowed value types: boolean, integer, decimal, ISO date or datetime, time `HH:MM`, enum code, identifier
  (CRN, university ID, course code such as `ECON 2110`, term code), and lists or maps of those. No free text.
  Strings that come from the database verbatim (course title, term name, building code) are allowed because
  they compare exactly.
- Comparison rules: scalars exact (strings case-insensitive, trimmed); decimals within 0.005 for GPA and 0.5
  percentage point for rates; lists of scalars as multisets (order ignored unless the schema says `ordered`);
  lists of records matched as multisets of their fields; maps by key. Every field in the ground truth must be
  present and equal; extra fields in the agent's answer are ignored. `null` means "none" and must be returned as such.
- Where a rule could be read two ways (tie-breaks, who counts as "freshman"), the rule is written next to the
  schema and the generator implements exactly that rule.

Legend for the schemas: `bool`, `int`, `num`, `date`, `datetime`, `time`, `id` (university ID), `crn`, `course`
(subject + number), `term` (term name, e.g. `Spring 2026`), `enum{...}`, `[...]` list, `{k: v}` map.

---

## 1. Schedule (teaching schedule)

### `teach_current` (12 cases)
What they teach this term.
- What am I teaching this semester?
- Can you pull up my teaching schedule for Fall 2026?
- Which sections am I assigned to this term, and when do they meet?
- What classes do I have this fall?
- Show me my sections and rooms for this semester.

Slots: `term_code`.
Answer: `{term: term, sections: [{crn, course, section_number, instruction_mode: enum{in_person, online, hybrid},
meetings: [{days: "MWF", start: time, end: time, room: "BR 102" | null}]}]}`.
Rule: sections where the professor is the primary instructor and status is not `cancelled`; `room` is building code + room number.

### `teach_term` (10 cases)
Same, for a past or future term.
- What did I teach in Spring 2025?
- What am I scheduled to teach next semester?
- Which courses did I have last fall?
- Am I teaching anything in the spring, and what?
- Remind me what sections I had in Fall 2024.

Slots: `term`, `term_code`. Answer: same schema as `teach_current`; an empty `sections` list when they taught nothing.

### `teach_week` (8 cases)
- What does my teaching week look like?
- Lay out my class times day by day.
- Which days of the week do I teach this semester?

Slots: `term_code`.
Answer: `{term, by_day: {Monday: [{start, end, crn, course, room}], ...}, teaching_days: [enum{Monday..Sunday}], online_no_meeting: [crn]}`.
Rule: only days with at least one meeting appear in `by_day`; entries ordered by start time (`ordered`).

### `teach_day` (8 cases)
- What do I teach on Mondays?
- Do I have any classes on Friday?
- When is my first class on Tuesday, and where?
- What time am I done teaching on Wednesdays?

Slots: `term_code`, `day`.
Answer: `{term, day, meetings: [{start, end, crn, course, room}] (ordered), has_classes: bool, first_start: time | null, last_end: time | null}`.

### `section_meeting` (6 cases)
- Where does my ECON 2110 class meet?
- Which room is CRN 10341 in?
- What time does my ECON 1120 section start?
- Is my ECON 4210 section online or in person?

Slots: `crn` | `course`, `term_code`.
Answer: `{crn, course, instruction_mode, meetings: [{days, start, end, building, room}]}`.
Rule: when asked by course and the professor has several sections of it in the term, the answer is a list of these objects.

### `term_dates` (10 cases)
Calendar dates for a term, with whether the date has passed at `as_of`.
- When are grades due this semester?
- When is finals week?
- What's the last day my students can withdraw from my class?
- When does Thanksgiving break start and end?
- When does the spring semester begin?
- Can students still drop my class without a W?
- When is the census date for this term?

Slots: `term_code`, `event: enum{classes_begin, add_deadline, drop_deadline, census, withdraw_deadline, finals, grades_due, commencement, holiday:<name>}`.
Answer: `{term, event, date, end_date: date | null, has_passed: bool}`. Rule: `has_passed` is `as_of.date() > date` (or `> end_date` for ranges).

### `teach_load` (6 cases)
- How many sections am I teaching this term?
- How many credit hours am I teaching this fall?
- How many students do I have in total this semester?
- How many sections do I have next spring?

Slots: `term_code`. Answer: `{term, sections: int, credits: num, students_registered: int}`.
Rule: credits = sum of section credits; students = enrollments with status `registered` (current/future) or `completed` + `withdrawn` (past).

---

## 2. Courses (sections, rosters, catalog, grading)

### `enrollment_count` (10 cases)
- How many students are enrolled in CRN 10341?
- How many students are in each of my sections this semester?
- Is my ECON 2110 section full?
- How many seats are left in my Spring 2027 sections?
- How many people are registered for my ECON 1120 online section?

Slots: `crn` | `course` | all, `term_code`.
Answer: `{sections: {crn: {course, registered: int, capacity: int, seats_left: int, is_full: bool, waitlisted: int, waitlist_capacity: int}}}`.
Rule: `registered` counts status `registered` only; `seats_left = capacity - registered`; `is_full = seats_left <= 0`.

### `roster` (10 cases)
- Who is on my roster for CRN 10341?
- Can you give me the class list for my ECON 2110 section?
- List the students registered in my Spring 2026 ECON 4250 class.
- Which students are currently on the waitlist for CRN 10341, in order?
- Who is enrolled in my Tuesday/Thursday ECON 1120 section?

Slots: `crn` | `course`, `term_code`, `status: enum{registered, waitlisted}`.
Answer: `{crn, term, count: int, students: [{university_id: id, status: enum{registered, waitlisted, completed, withdrawn}}]}`;
the waitlist variant has `students: [{university_id, position: int}]` (`ordered`).
Rule: current/future terms list `registered` (and `waitlisted` when asked); past terms list `completed` and `withdrawn`. Dropped never appear.

### `student_in_section` (8 cases)
- Is 801907856 in my class?
- Which of my sections is student 801389250 enrolled in?
- Is 801824094 still enrolled in CRN 10341, or did they drop?

Slots: `university_id`, `crn` | `course` | any, `term_code`.
Answer: `{university_id, found: bool, sections: [{crn, course, status: enum{registered, waitlisted, dropped, withdrawn, completed}}]}`.
Rule: search only the professor's sections in the term; `found` is true when any row exists, including dropped.

### `drops_withdrawals` (8 cases)
- Who dropped my ECON 2110 class this semester?
- Has anyone withdrawn from CRN 10341?
- How many students dropped or withdrew from my sections this fall, and who?
- Did 801907856 withdraw from my class, and on what date?

Slots: `crn` | `course` | all, `term_code`, optional `university_id`.
Answer: `{sections: {crn: {dropped: [{university_id, date}], withdrawn: [{university_id, date}]}}, total_dropped: int, total_withdrawn: int}`.
Rule: `date` is `dropped_at` as a date.

### `course_catalog` (8 cases)
- What are the prerequisites for ECON 2110?
- How many credits is my ECON 4210 course?
- Is ECON 1120 a gen-ed course, and in which area?
- Is ECON 2110 lower or upper division?
- Does ECON 4210 have a corequisite?

Slots: `course` | `crn`.
Answer: `{course, title, credits_min: num, credits_max: num, level: enum{lower_division, upper_division, graduate},
is_gen_ed: bool, gen_ed_area: string | null, prerequisites: [{group: int, type: enum{prerequisite, corequisite}, any_of: [course], min_grade}]}`.
Rule: prerequisite groups are AND; `any_of` within a group is OR.

### `student_prereq_check` (10 cases)
A student asked to be let into the section; same eligibility rules as the student set, from the instructor's side.
- Student 801907856 wants to add my ECON 2110 section. Do they meet the prerequisites?
- Can 801389250 get into CRN 10341, or do I need to sign an override?
- Has 801824094 completed the prerequisite for ECON 4210?
- Is there room for 801649737 in my spring ECON 1120 section, and are they eligible?
- Would adding 801840101 to CRN 10385 conflict with their schedule?

Slots: `university_id`, `crn` | `course`, `term_code`.
Answer: `{crn, university_id, meets_prerequisites: bool, unmet: [[course]] (one inner list per unmet group),
already_in_section: bool, seats_left: int, time_conflict: bool, conflicting_crns: [crn],
blockers: [enum as in the student set], override_needed: [enum{prerequisite, capacity, time_conflict}]}`.
Rule: `override_needed` lists the blockers an instructor override could clear; registration-window, hold, and
status blockers stay in `blockers` and cannot be overridden by the instructor.

### `incompletes` (6 cases)
- Which of my students have an incomplete grade outstanding?
- When does the incomplete for 801907856 in my Spring 2026 class expire?
- Do I have any incompletes from last semester that still need a grade?
- Which incompletes in my sections have already passed their deadline?

Slots: optional `term_code`, optional `university_id`, `only_expired: bool`.
Answer: `{incompletes: [{university_id, crn, course, term, deadline: date, expired: bool}], count: int}`.
Rule: grade `I` with `is_final = false`; `expired = as_of.date() > deadline`.

### `grade_status` (6 cases)
- Did I submit grades for CRN 10298 last spring?
- Are any of my Spring 2026 students missing a grade?
- Were all grades for my Fall 2025 sections posted on time?
- When did I post grades for my ECON 2110 section last spring?

Slots: `crn` | `course` | all, `term_code`.
Answer: `{sections: {crn: {expected: int, graded: int, missing: [university_id], last_posted: date | null, grades_due: date, on_time: bool | null}}, all_graded: bool}`.
Rule: `expected` = enrollments with status `completed` or `withdrawn`; `on_time` = `last_posted <= grades_due`, null when nothing posted.
Fall 2026 at the default clock: `graded` counts only the W grades already posted, `all_graded = false`.

### `grade_change_status` (4 cases; only four requests exist in the sample)
- What happened to the grade change I requested for 801907856?
- Is my grade change request for CRN 10298 approved yet?
- Which grade changes have I requested, and what is their status?

Slots: `university_id` | `crn` | all.
Answer: `{requests: [{university_id, crn, course, term, old_grade, new_grade, status: enum{pending, applied}, applied_at: date | null}], count: int}`.
Rule: `status = applied` when `applied_at` is set.

---

## 3. Statistics (their own sections)

### `grade_distribution` (12 cases)
- What was the grade distribution in my ECON 2110 section last spring?
- How did grades break down across all the times I've taught ECON 1120?
- What was the average grade in CRN 10298 in Spring 2026?
- How many A's did I give in Fall 2025?
- What's the grade distribution for the class I'm teaching now?

Slots: `crn` | `course` | all, `term_code` | all.
Answer: `{scope: {crn | course | all, term | all}, counts: {A: int, "A-": int, ..., F: int, W: int, I: int}, graded: int, gpa_credits: num, mean_gpa: num | null, available: bool}`.
Rule: `mean_gpa` = credit-weighted quality points over grades with `counts_in_gpa`; `available = false` and
`counts = {}` when no grades are posted for the scope (the current term).

### `dfw_rate` (8 cases)
- What's my DFW rate for ECON 2110?
- How many students failed my ECON 1120 class last spring?
- What percentage of my students withdrew or got a D or F across all my sections?
- What was the pass rate in CRN 10298?

Slots: `crn` | `course` | all, `term_code` | all.
Answer: `{scope, total: int, d: int, f: int, w: int, dfw_rate: num, pass_rate: num}`.
Rule: `total` = graded enrollments (letter grades plus W, excluding I); `d` counts D+, D, D-; `pass` = grade C- or better
(or S); rates are percentages with one decimal.

### `enrollment_trend` (8 cases)
- How many students did I have in ECON 2110 each semester?
- Which term had the most students in my ECON 4250 class?
- How many students were in my sections term by term?
- Did my ECON 1120 headcount increase from Spring 2025 to Spring 2026?

Slots: `course` | all, optional pair of `term_code`s.
Answer: `{course | all, by_term: [{term, sections: int, headcount: int}] (ordered by term), peak_terms: [term], change: {from: term, to: term, delta: int, increased: bool} | null}`.
Rule: headcount = enrollments that were not dropped (completed, withdrawn, registered, waitlisted excluded);
`peak_terms` lists every term tied for the maximum.

### `fill_rate` (6 cases)
- How full are my sections this semester?
- What's my overall fill rate this fall?
- Which of my sections has the most empty seats?
- Are any of my spring sections already full?

Slots: `term_code`.
Answer: `{term, sections: {crn: {registered, capacity, fill_rate: num}}, overall_fill_rate: num, most_empty: [crn], full: [crn]}`.
Rule: fill rate = registered / capacity as a percentage with one decimal; `overall` = sum registered / sum capacity; ties listed.

### `withdrawal_stats` (6 cases)
- How many students have withdrawn from my classes this semester?
- What's the withdrawal rate in CRN 10341 so far?
- Did more people withdraw from my sections this fall than last fall?

Slots: `crn` | all, `term_code`, optional comparison `term_code`.
Answer: `{term, by_section: {crn: {withdrawn: int, started: int, rate: num}}, total_withdrawn: int, rate: num,
comparison: {term, total_withdrawn: int, more_than_comparison: bool} | null}`.
Rule: `started` = enrollments not dropped; rate = withdrawn / started as a percentage.

### `class_composition` (10 cases)
- What's the breakdown of my ECON 2110 section by class standing?
- How many of my students this semester are seniors?
- Which majors are represented in CRN 10341, and how many of each?
- How many students in my ECON 1120 section are in their first semester?
- Which colleges are my students from this fall?

Slots: `crn` | `course` | all, `term_code`, `dimension: enum{classification, major, college, first_term}`.
Answer: `{scope, dimension, counts: {label: int}, total: int}`.
Rule: students = registered (current/future) or completed + withdrawn (past). Classification = `classification` from the
student's latest `student_term_record` before the term, else `freshman`. Major = primary declared program code; college =
that program's department's college code; `first_term` counts students whose `admit_term` is the term in question
(labels `first_term` / `continuing`).

### `students_taught` (4 cases)
- How many students have I taught in total?
- How many distinct students have taken a class with me, and over how many terms?
- How many sections have I taught since I started?

Answer: `{distinct_students: int, sections: int, terms: int, first_term: term, last_term: term}`.
Rule: counts enrollments that were not dropped, in terms up to and including the current one (future sections excluded).

---

## Needs a decision

1. **Other instructors' sections.** Questions like "How does my grade distribution compare with the other ECON 2110
   sections?" or "What's the department's average DFW rate?" are natural, but the `instructor` role does not have
   `report.aggregate.read`. Options: leave them out; include them with an answer of `{allowed: false,
   required_role: department_chair}` so the agent's refusal is tested; or treat course-level aggregates as public.
2. **Student names in answers.** Roster-type answers use `university_id` only. Names are exact database strings and
   could be checked too, at the cost of a bigger answer.
3. **Advisees.** Many professors are also advisors (who are my advisees, which are on probation, who has an
   advising hold). Out of the three categories you named; can be a fourth later.
4. **Counts.** The numbers above total about 200 cases. Say if you want ~150 like the student set.

Dropped from the first draft because the answer is not discrete: catalog descriptions, "is enrollment going up or
down" (replaced by a two-term comparison with a defined delta).
Not possible from the data, so not proposed: teaching assistants (none exist at 5% scale), repeat-takers
(`is_repeat` is always false), attendance, assignments, office hours.
