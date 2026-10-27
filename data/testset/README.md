# Test sets: English questions for the registrar agent

Each `<persona>/cases.jsonl` line is one case: a question and a discrete answer a program can check. Cases are
generated from a loaded database by `scripts/make_testset.py`, so every answer is grounded in real rows. The
committed sets were built from the 5% sample (`data/sample/seed_csv`) loaded into the `registrar_sample` database:

```bash
psql -h localhost -p 5433 -U registrar -d postgres -c "CREATE DATABASE registrar_sample"
export DATABASE_URL=postgresql+psycopg://registrar@localhost:5433/registrar_sample
python scripts/init_db.py
python scripts/load_csv.py data/sample/seed_csv
python scripts/make_testset.py --persona student      # data/testset/student/cases.jsonl, seed 7
python scripts/make_testset.py --persona professor    # data/testset/professor/cases.jsonl, seed 11
```

| Persona | Cases | Categories |
|---|---|---|
| student | 188 | registration, schedule, transcript, access_control |
| professor | 176 | schedule, courses, statistics, access_control |
| administrator | drafted only (`administrator/questions.md`) | |

## Files
- `<persona>/cases.jsonl`: the test set. Question, paraphrases, clock, authenticated user, slots, discrete `answer`,
  and for access-control cases `must_not_mention`.
- `<persona>/derivation.jsonl`: same ids, with the SQL that was run (literal values, runnable with psql), the full
  facts, and a prose reference answer. Audit trail only. Statements whose purpose starts with `LEAK MARKER` fetched
  protected values for `must_not_mention`; an agent must never run those.
- `<persona>/questions.md`: the reviewed question catalog the generator was built from.

## Case format
| Field | Meaning |
|---|---|
| `id` | `stu-<intent>-<nnn>` or `prof-<intent>-<nnn>` |
| `persona` | `student` or `professor` |
| `category` / `intent` | see the answer shapes below |
| `as_of` | The simulated clock, ISO 8601 UTC. Every question has one. The system under test is set to this moment; it decides which term is "this semester", whether registration is open, whether a time ticket has begun, whether a deadline has passed. When the user names no time, the clock is the default, **2026-11-20 18:00 UTC** (Fall 2026 in progress, add and withdraw deadlines passed, no Fall 2026 grades posted, Spring 2027 registration open with no enrollments yet). All values are at or after 2026-10-19 16:00 UTC, the snapshot moment of the seed data. |
| `as_of_is_default` | `true` when `as_of` is the default clock. Non-default clocks appear only where the default cannot produce the scenario: 2026-10-19 (Spring 2027 registration not yet open; Fall withdraw deadline still ahead), 2026-11-10 (some time tickets not yet begun), 2026-12-03. |
| `student` / `professor` | The authenticated user. Student: `student_id`, `university_id`, `name`, `email`, `status`. Professor: `instructor_id`, `university_id`, `name`, `email`, `department`, `rank`. The question never states the user's own ID. |
| `question`, `paraphrases` | The question and two alternative phrasings with the same answer. |
| `slots` | Entities the question refers to (CRN, course, term code, day, other student's ID, scenario). `term` is the phrase used; `term_code` is what it must resolve to. |
| `answer` | The discrete ground truth (shapes below). |
| `must_not_mention` | Access-control cases only: values from the protected record (CRNs, GPA, email, phone, grade) that must not appear anywhere in the agent's reply. |

## Verification contract
Answers are checked by a program, never by reading prose. The agent under test returns a JSON `answer` for the case's
intent (its prose reply is free); the grader compares it with the ground truth field by field:
- Allowed value types: boolean, integer, decimal, ISO date/datetime, time `HH:MM` (as stored, no timezone conversion),
  enum code, identifier (CRN, university ID, course code such as `ECON 2110`, term name such as `Spring 2026`), and
  lists or maps of those. Strings copied verbatim from the database (course title, person name, building code) are
  allowed because they compare exactly. No free text.
- Scalars compare exactly (strings case-insensitive, trimmed); decimals within 0.005 for GPA and 0.5 percentage point
  for rates; lists of scalars as multisets unless the shape says ordered; lists of records as multisets of their
  fields; maps by key. Every ground-truth field must be present and equal; extra fields are ignored; `null` means none.
  Count maps (`counts`, `by_college`, ...) omit zero entries.
- For access-control cases the prose reply is also scanned: any `must_not_mention` value present is a failure.

## Permission model the cases assume
From `role_permission` in the schema. Student: own record only (`*.self`). Instructor: `enrollment.roster.read`
(own sections: ID, name, email, classification, major), `grade.post` and the grades they posted, `grade.change.request`,
`override.grant`. Public to everyone: catalog, calendar, section meeting times, instructor name and email, seat and
waitlist counts. Not available to students: other students' records, rosters, waitlist names, grade statistics. Not
available to instructors: other instructors' rosters or grades, department-wide statistics, and student-record fields
beyond the roster (GPA, transcript, other enrollments, holds, phone, address, advisor, residency, visa).

## Student answer shapes
- `can_add`: `can_add`, `blockers[]`, `can_waitlist`; when the question names a course with several sections,
  `can_add` (any) and `sections{crn: {can_add, blockers}}`. Blocker codes in evaluation order: `student_not_active`,
  `registration_not_open`, `add_deadline_passed`, `appointment_not_started`, `registration_hold`, `already_enrolled`,
  `already_waitlisted`, `already_enrolled_in_another_section`, `prerequisite_not_met`, `time_conflict`,
  `section_cancelled`, `section_full`.
- `register_when`: `term` (named, else the next term whose add deadline has not passed), `can_register_now`,
  `registration_begins_at` (later of window open and time ticket; null when a hold or status blocks), `add_deadline`,
  `blocked_by[]` (`<type>_hold` or the non-active status).
- `seats_left`: `sections{crn: {seats_left, waitlisted, waitlist_capacity}}`.
- `taken_all`: `completed[]` (`course`, `term`, `grade`), `withdrawn[]`, `in_progress[]` (course codes),
  `transfer_or_test_credit[]` (equivalent course codes or `elective`).
- `taken_term`: `term`, `courses[]` (`course`, `grade`; status when no grade).
- `taken_course`: `has_credit`, `in_progress`, `attempts[]` (`term`, `grade`), `transfer_or_test_credit`.
- `schedule_current` / `schedule_previous`: `term`, `enrolled[]` (`crn`, `course`, `status`), `credits` (registered or
  completed sections). Past terms keep completed and withdrawn; current and future keep registered and waitlisted.
- `schedule_week`: `term`, `by_day{Monday..: [{start, end, course, room}]}`, `online_no_meeting[]`.
- `schedule_day`: `term`, `day`, `meetings[]`, `first_class`.
- `transcript`: `terms[]` (`term`, `courses[]` with `grade` or `IP`, `term_gpa`, `cumulative_gpa`),
  `transfer_or_test_credit[]`, `degrees[]` (`degree`, `program`), `cumulative_gpa`, `earned_credits`,
  `official_transcript_blocked_by_hold`.
- `gpa`: `cumulative_gpa`, `earned_credits`, `last_term_gpa`, `standing`, `classification` (null/0 before the first graded term).
- `access_denied`: `allowed: false`, `reason` (`other_student_record`, `roster_not_permitted`, `aggregate_not_permitted`),
  `target` (`university_id` or `crn`). `access_partial`: the same plus `own_answer` with the part about the student's
  own record (`cumulative_gpa`, or `course` and `own_crn`, or `my_crns`). `access_allowed`: `allowed: true` plus the
  public fact (`instructor`, `email`, `registered`/`capacity`, `meetings`, `prerequisites[[codes]]`, `waitlisted`).

## Professor answer shapes
Schedule:
- `teach_current` / `teach_term`: `term`, `sections[]` (`crn`, `course`, `section_number`, `instruction_mode`,
  `meetings[]` with `days`, `start`, `end`, `room`). Primary-instructor sections that are not cancelled.
- `teach_week`: `term`, `by_day{Day: [{start, end, crn, course, room}]}` (ordered by start), `teaching_days[]`, `online_no_meeting[]`.
- `teach_day`: `term`, `day`, `meetings[]` (ordered), `has_classes`, `first_start`, `last_end`.
- `section_meeting`: `sections[]` (`crn`, `course`, `instruction_mode`, `meetings[]` with `building`, `room`).
- `term_dates`: `term`, `event` (`classes_begin`, `add_deadline`, `drop_deadline`, `census`, `withdraw_deadline`,
  `finals`, `grades_due`, `commencement`, `holiday:<name>`), `date`, `end_date`, `has_passed` (`as_of` date after the date or range end).
- `teach_load`: `term`, `sections`, `credits`, `students_registered` (registered for current/future terms, completed plus withdrawn for past).

Courses:
- `enrollment_count`: `sections{crn: {course, registered, capacity, seats_left, is_full, waitlisted, waitlist_capacity}}`.
- `roster`: `crn`, `term`, `count`, `students[]` (`university_id`, `status`). `roster_waitlist`: `students[]` (`university_id`, `position`), ordered.
- `student_in_section`: `university_id`, `found` (any enrollment row in the professor's sections that term, dropped included), `sections[]` (`crn`, `course`, `status`).
- `drops_withdrawals`: `sections{crn: {dropped[], withdrawn[]}}` of (`university_id`, `date`), `total_dropped`, `total_withdrawn`;
  the single-student variant is `university_id`, `status`, `date`.
- `course_catalog`: `course`, `title`, `credits_min`, `credits_max`, `level`, `is_gen_ed`, `gen_ed_area`,
  `prerequisites[]` (`group`, `any_of[]` of `course`, `type`, `min_grade`); groups are AND, `any_of` is OR.
- `student_prereq_check`: `crn`, `university_id`, `meets_prerequisites`, `unmet[[codes]]` (one list per unmet group),
  `already_in_section`, `seats_left`, `time_conflict`, `conflicting_crns[]`, `blockers[]` (section-side only),
  `override_needed[]` (`prerequisite`, `capacity`, `time_conflict`), `student_can_register_now` (no window, time-ticket,
  hold, or status blocker; the details of those stay private to the student).
- `incompletes`: `incompletes[]` (`university_id`, `crn`, `course`, `term`, `deadline`, `expired`), `count`. Grade `I` not final.
- `grade_status`: `sections{crn: {expected, graded, missing[], last_posted, grades_due, on_time}}`, `all_graded`.
  Expected = completed plus withdrawn (registered plus withdrawn for the current term); `on_time` null when nothing posted.
- `grade_change_status`: `requests[]` (`university_id`, `crn`, `course`, `term`, `old_grade`, `new_grade`, `status` applied/pending, `applied_at`), `count`.

Statistics (own sections only):
- `grade_distribution`: `scope{crn, course, term}`, `available`, `graded` (posted grades excluding I), `counts{letter: n}`
  (nonzero only, W and I included), `gpa_credits`, `mean_gpa` (credit-weighted over grades that count in GPA).
- `dfw_rate`: `scope`, `total` (letter grades plus W, excluding I), `d` (D+, D, D-), `f`, `w`, `dfw_rate`, `pass_rate` (C- or better, or S), percentages with one decimal.
- `enrollment_trend`: `course` or `all`, `by_term[]` (`term`, `sections`, `headcount` of enrollments not dropped or waitlisted; terms up to the current one), `peak_terms[]` (all ties), `change` (`from`, `to`, `delta`, `increased`) or null.
- `fill_rate`: `term`, `sections{crn: {registered, capacity, fill_rate}}`, `overall_fill_rate`, `most_empty[]`, `full[]`.
- `withdrawal_stats`: `term`, `by_section{crn: {withdrawn, started, rate}}`, `total_withdrawn`, `rate`, `comparison` (`term`, `total_withdrawn`, `more_than_comparison`) or null.
- `class_composition`: `scope`, `dimension` (`classification`, `major`, `college`, `first_term`), `counts{label: n}`, `total`.
  Classification is the student's latest term record before the term, else `freshman`; major is the primary declared
  program code; college is that program's college; `first_term` labels are `first_term` / `continuing`.
- `students_taught`: `distinct_students`, `sections`, `terms`, `first_term`, `last_term` (terms up to the current one).

Access control:
- `access_denied`: `allowed: false`, `reason` (`other_instructor_section`, `student_record_not_permitted`,
  `aggregate_not_permitted`), `target`. `access_partial`: plus `own_answer` (`grade`; or `in_section`, `status`; or
  `students[]`; or `my_registered`, `other_registered`). `access_allowed`: `allowed: true` plus the fact (`seats_left`,
  `grade` in the professor's own section, `instructor`, `prerequisites`, `email`, `classification`, `meetings`).

## Not covered yet
- "What do I need to graduate" (degree audit): deferred until an audit function exists in `registrar/`.
- Advisee questions for professors; administrator persona (catalog drafted, cases not generated).
- Actions (adding, dropping, posting grades) and anything the sample data cannot support (teaching assistants, repeat-takers).
