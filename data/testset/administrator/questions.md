# Administrator persona: proposed questions

Draft for review before any cases are generated. Same conventions as the other sets: every case has an `as_of`
clock (default 2026-11-20 18:00 UTC), the administrator is authenticated, two paraphrases per case, and a discrete
`answer` checked by a program under the verification contract in `data/testset/professor/questions.md`
(typed values only, field-by-field comparison, decimals with tolerance, lists as multisets unless `ordered`).

Role assumed: `registrar_admin` (has `student.read.any`, `report.aggregate.read`, `person.read.any`), so answers may
include student IDs. If the administrator should instead be `institutional_research` (aggregate only), every
`students: [id]` field below is dropped and only counts remain.

At the default clock: Fall 2026 is in progress with no grades posted, so "this semester" grade questions answer
`available: false`; the latest graded term is Summer 2026 for a few students and Spring 2026 for most; Spring 2027
registration is open with no enrollments yet; the latest academic standing comes from each student's most recent
`student_term_record`.

Scopes used throughout (one `scope` object in every answer so the grader can check the resolution):
`{kind: enum{all, course, subject, department, college, level, gen_ed_area, program, classification, cohort},
value: code | null, term: term | null}`. "This semester" resolves through `as_of`; "last spring" is Spring 2026.

---

## A. Statistics about a group of courses

### `grade_distribution_group` (14 cases)
How the grades look for a subject, department, college, course, level, or gen-ed area in a term or over all terms.
- How are the grades in MATH this past spring?
- What was the grade distribution across the College of Business in Fall 2025?
- How many A's and how many F's were given in BIOL courses last spring?
- Are there a lot of A's in lower-division CHEM courses?
- What does the grade distribution look like for ENGL 1110 across all terms?
- How are the grades in CS this semester? (not available: grades not posted)

Slots: `scope`. Answer: `{scope, available: bool, graded: int, counts: {A: int, "A-": int, ..., F: int, W: int, I: int},
pct_a: num, pct_f: num, pct_dfw: num, mean_gpa: num | null}`.
Rule: `graded` counts posted grades excluding I; `pct_*` are percentages of `graded` with one decimal; `mean_gpa` is
credit-weighted over grades with `counts_in_gpa`; `pct_a` counts A only (not A-).

### `grading_extremes` (10 cases)
Which sections or courses gave the most A's, or had the highest F or DFW rate.
- Which sections gave the highest share of A's last spring?
- Which five courses had the highest F rate in Fall 2025?
- Which ENGR courses have the worst DFW rate over the last three years?
- Which section in the College of Arts and Sciences had the lowest average GPA in Spring 2026?
- Which courses had no F's at all last spring?

Slots: `scope`, `metric: enum{pct_a, pct_f, pct_dfw, mean_gpa}`, `direction: enum{highest, lowest}`, `limit: int`, `unit: enum{section, course}`.
Answer: `{scope, unit, metric, direction, min_graded: int, items: [{key: crn | course, graded: int, value: num}] (ordered)}`.
Rule: only sections/courses with at least `min_graded = 10` posted grades qualify; ordered by metric, then by key
ascending; `limit` defaults to 5; the "no F's" variant returns `items` with `value = 0` and no limit.

### `dfw_rate_group` (8 cases)
- What is the DFW rate for MATH courses this past year?
- What share of students passed their gen-ed science courses in Fall 2025?
- How does the DFW rate in upper-division BUS courses compare with lower-division?
- Which college had the highest DFW rate last spring?

Slots: `scope` (one or two for comparisons). Answer: `{scopes: [{scope, total: int, d: int, f: int, w: int, dfw_rate: num, pass_rate: num}], highest: scope | null}`.
Rule: as in the professor set: total = letter grades plus W, excluding I; pass = C- or better or S; percentages with one decimal.

### `grade_trend_group` (8 cases)
- How has the A rate in CHEM changed over the last four fall terms?
- What was the average GPA in COMM courses each spring since 2023?
- Has the F rate in MATH 1220 gone up or down between Fall 2024 and Fall 2025?

Slots: `scope`, `terms: [term_code]` or a range, `metric`. Answer: `{scope, metric, by_term: [{term, graded, value: num}] (ordered by term), change: {from: term, to: term, delta: num, increased: bool} | null}`.

### `enrollment_group` (12 cases)
Seats, headcount, and fill for a group of sections in a term.
- How many students are enrolled in CS courses this fall?
- How many sections does the College of Engineering have this semester, and how full are they overall?
- How many sections are full in BUS right now?
- What's the total capacity versus enrollment for MATH 1220 this fall?
- How many Spring 2027 sections are scheduled in HEST, and how many seats is that?
- How many students are on waitlists in A&S this semester?

Slots: `scope`. Answer: `{scope, sections: int, capacity: int, registered: int, seats_left: int, fill_rate: num, full_sections: int, waitlisted: int, online_sections: int}`.
Rule: `registered` counts status `registered` (current/future) or `completed + withdrawn` (past); `full_sections` = sections with `seats_left <= 0`.

### `low_enrollment_sections` (8 cases)
- Which sections this fall have fewer than 10 students?
- Which ENGR sections are under 50% full this semester?
- How many Spring 2027 sections have no one registered yet? (all of them, at the default clock)
- Which sections in the College of Business have more than 5 students on the waitlist?

Slots: `scope`, `measure: enum{registered, fill_rate, waitlisted}`, `comparison: enum{lt, gt}`, `threshold: num`.
Answer: `{scope, measure, comparison, threshold, count: int, sections: [{crn, course, registered, capacity, waitlisted}]}`.

### `withdrawals_group` (8 cases)
- How many withdrawals have there been in MATH this semester?
- Which course had the most W's in Fall 2025?
- What is the withdrawal rate in the College of Engineering this fall?
- How many students withdrew from gen-ed courses last spring?

Slots: `scope`. Answer: `{scope, withdrawn: int, started: int, rate: num, top_courses: [{course, withdrawn}] (ordered, ties by course code)}`.
Rule: `started` = enrollments not dropped; `top_courses` lists up to 5.

### `incompletes_group` (6 cases)
- How many incomplete grades are outstanding across the university?
- How many incompletes in the College of Arts and Sciences are past their deadline?
- Which departments have the most unresolved incompletes?

Slots: `scope`, `only_expired: bool`. Answer: `{scope, outstanding: int, expired: int, by_department: {dept_code: int}}`.
Rule: grade I with `is_final = false`; `expired = as_of.date() > incomplete_deadline`.

### `overrides_group` (6 cases)
- How many prerequisite overrides were granted for Fall 2026 sections?
- Which department granted the most capacity overrides this semester?
- How many overrides of each type were issued this fall?

Slots: `scope`, optional `override_type`. Answer: `{scope, counts_by_type: {prerequisite: int, capacity: int, time_conflict: int, level: int, credit_overload: int}, total: int, top_department: {code, count} | null}`.

---

## B. Statistics about a group of students

### `graduating_students` (12 cases)
Who is graduating, and where applications stand.
- Which students are graduating this term?
- How many students have applied to graduate in Spring 2027, and how many are approved so far?
- How many graduation applications are still under review for Fall 2026?
- How many students in the College of Engineering are set to graduate this semester?
- How many degrees were conferred in Spring 2026, by college?

Slots: `scope`, `term_code`, `status` filter. Answer: `{scope, term, counts_by_status: {submitted: int, under_review: int, approved: int, denied: int, conferred: int}, graduating: int, students: [id] | null}`.
Rule: "graduating" = application for the term with status `approved` (or `conferred` for past terms); `students` is
listed only when the question asks who and the count is at most 40, else null.

### `at_risk_students` (12 cases)
Students on probation or about to be suspended.
- Which students are on the brink of suspension?
- How many students are on academic probation right now, by college?
- Which students have been on probation for two terms in a row?
- How many active students have a cumulative GPA below 2.0?
- Which students in the College of Business are on probation and still registered this semester?

Slots: `scope`, `criterion: enum{probation, at_risk_of_suspension, gpa_below}`, optional `threshold`.
Answer: `{scope, criterion, threshold: num | null, count: int, by_college: {code: int}, students: [{university_id, cumulative_gpa: num, probation_terms: int}] | null}`.
Rule (from the standing policy in the seed): probation = latest term record standing `probation` (cumulative GPA
under 2.0); a student is suspended after three consecutive probation terms with another term GPA under 2.0, so
`at_risk_of_suspension` = active, on probation, with two or more consecutive probation terms as of the latest record.
Dismissal is not modeled; "brink of dismissal" maps to this. `students` listed only when asked who and count <= 40.

### `standing_summary` (8 cases)
- How many students made the dean's list last spring, by college?
- How many students were placed on probation after Fall 2025?
- How many students were suspended after Spring 2026?
- What's the standing breakdown of active students right now?

Slots: `scope`, `term_code` | latest, `standing` filter. Answer: `{scope, term, counts: {good_standing: int, deans_list: int, probation: int, suspension: int}, by_college: {code: {standing: int}} | null}`.
Rule: term-specific questions use that term's records; "right now" uses each active student's latest record; students
with no record yet are counted under `no_record`.

### `headcount` (14 cases)
- How many active undergraduates do we have?
- How many active students are in each college?
- How many students are enrolled full-time this fall?
- How many new first-time freshmen started this fall?
- How many international students are active this semester?
- How many students are registered for at least one online section this fall?
- How many active students are veterans, athletes, or in the honors program?

Slots: `scope`, `filter: enum{active, full_time, part_time, first_time_this_term, transfer_this_term, international, resident, nonresident, veteran, athlete, honors, online_any, classification:<x>}`.
Answer: `{scope, filter, count: int, by_college: {code: int} | null, by_classification: {freshman: int, ...} | null}`.
Rule: full-time = registered credits >= 12 in the term; classification from the latest term record, else `freshman`.

### `gpa_profile` (8 cases)
- What is the average cumulative GPA of active students in the College of Engineering?
- How many active students have a cumulative GPA of 3.5 or higher?
- What's the median GPA of seniors right now?
- How many Computer Science majors have a GPA below 2.5?

Slots: `scope`, optional `threshold`, `comparison`. Answer: `{scope, students_with_gpa: int, mean_gpa: num, median_gpa: num, threshold: num | null, comparison: enum{ge, lt} | null, count_matching: int | null}`.
Rule: uses each active student's latest cumulative GPA; students with no GPA are excluded from mean and median
(even-count median = average of the two middle values).

### `cohort_outcomes` (8 cases)
- Of the students admitted in Fall 2024, how many are still active, graduated, withdrawn, or suspended?
- How many of the Fall 2023 first-time cohort have graduated so far?
- What share of transfer students admitted in Fall 2025 are still enrolled?

Slots: `cohort: {admit_term_code, entry_type | all}`. Answer: `{cohort, size: int, counts_by_status: {active: int, graduated: int, withdrawn: int, suspended: int, leave_of_absence: int, dismissed: int}, retained_rate: num}`.
Rule: `retained_rate` = (active + graduated) / size as a percentage with one decimal.

### `missing_graduation_application` (6 cases)
- Which seniors haven't applied for graduation yet?
- How many students with 100 or more earned credits have no graduation application on file?
- Which Computer Science seniors are missing a graduation application?

Slots: `scope`, `credits_threshold` | classification senior. Answer: `{scope, count: int, students: [{university_id, cumulative_earned: num}] | null}`.
Rule: active students whose latest record meets the criterion and who have no application with status submitted,
under_review, or approved for the current or next term.

### `holds_summary` (8 cases)
- How many students currently have a registration hold, by hold type?
- Which office has placed the most active holds?
- How many students with a financial hold are registered this semester?
- Which students have a conduct hold right now?

Slots: `scope`, `hold_type` filter, `blocks: enum{registration, transcript, graduation} | null`. Answer: `{scope, students_with_hold: int, counts_by_type: {financial: int, advising: int, conduct: int, immunization: int, registrar: int, admissions: int}, counts_by_office: {office: int}, students: [id] | null}`.
Rule: unreleased holds only; a student with two holds counts once in `students_with_hold`.

### `pending_requests` (8 cases)
Work queues the office owns.
- How many petitions are waiting for a decision, by type?
- Which transcript requests are on hold, and for whom?
- How many enrollment verifications are still unprocessed?
- How many graduation applications are under review right now?

Slots: `queue: enum{petition, transcript_request, enrollment_verification, graduation_application}`, `status` filter. Answer: `{queue, counts_by_status: {status: int}, counts_by_type: {type: int} | null, pending: int, students: [id] | null}`.
Rule: pending = submitted, under_review, processing, or on_hold as applicable.

---

## Needs a decision

1. **Which role is "administrator".** Assumed `registrar_admin`, so student IDs may appear. If it is a dean, chair,
   or institutional research, say so: scope or ID visibility changes.
2. **"Brink of dismissal."** The seed models probation (cum GPA < 2.0) and suspension (three consecutive probation
   terms plus a failing term); dismissal never occurs. I propose "at risk" = two or more consecutive probation terms.
   Alternative: cumulative GPA within 0.2 of 2.0 while on probation.
3. **Lists of students.** Proposed cap of 40 IDs in an answer; above that only counts are returned. Change the cap?
4. **Counts.** The draft totals about 190 cases.

Not possible from the data, so not proposed: time-to-degree beyond the six seeded years, course evaluations,
faculty workload policy, financial figures (fees exist only on transcript requests).
