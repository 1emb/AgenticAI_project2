# What changed in the merged versions

This is for someone testing the two merged branches. How to set them up and run them is in [RUN.md](RUN.md).

## In one paragraph

Three people's work is now one system. `main` (Fuad) had a Student agent and a Professor agent that only read data.
Duong's branch added a router, an Administrator agent, a degree planner, a handbook search, and the ability to change
data: register, drop, withdraw, post a grade. Mason's branch added a search over the handbook and the course catalog,
and a coordinator that splits one message across several specialist agents. All of it now runs on `main`'s dataset
(1,200 students).

## The two versions

| Branch | Contains |
|---|---|
| `merge-fuad-duong-rag` | Fuad + Duong + Mason's search. One agent answers each message. |
| `merge-all-three` | The same, plus Mason's coordinator, used when you pass `--multi`. |

They differ by the coordinator only. Same data, same database, same tools, same rules. On `merge-all-three` without
`--multi` you get the same behaviour as `merge-fuad-duong-rag`.

## What is new for each kind of user

| User | Before, on `main` | Now |
|---|---|---|
| Student | Catalog, sections, degree plan, calendar | Also: own transcript and GPA, a degree plan from the planner, handbook questions, finding courses by topic, **registering, dropping and withdrawing** |
| Professor | Schedule, rosters, grades and statistics of own sections | Also: own advisees and a plan for an advisee, handbook questions, finding courses by topic, **posting a grade** |
| Administrator | Did not exist | Statistics over groups: grade distributions, withdrawals, enrollment and seats, students at risk, graduation candidates, headcounts, GPA profile, one student's record |

How the user's role is decided is also new: one entry point (`scripts/registrar_chat.py --user <id>`) looks the ID up
in the database and picks the agent. A TA is both a student and an instructor and has to choose with `--role`.

## Changing data: the part that most needs testing

This is the first version that writes to the database. The rules it is meant to follow:

1. **Nothing is written when you ask.** The system checks the rules and shows a preview that ends with
   "Please answer yes or no."
2. **Only the exact word `yes` makes the change**, as your next message. `no` discards it. "yes please", "ok",
   "sure", "yes later", "yes?", "yes, but switch me to the other section" must all write nothing. While a change
   is waiting, the system answers every such message itself: it says it can only take yes or no and repeats the
   preview. The model is not asked, so it cannot claim the change was made.
3. **The change is worked out again at the moment of the yes**, with the date and the data as they are then. If the
   result is no longer what the preview said, nothing is written and you are asked again with the new preview.
   Example: a drop previewed at 23:59 on the last drop day and confirmed at 00:01 would now be a withdrawal with a W,
   so the system must ask again instead of writing the W.
4. **One change at a time.** While one is waiting, nothing else is answered until you say `yes` or `no`.
5. **Every change is logged** in the table `change_log` (who, when, what).

What each change does to the data:

| Change | When allowed | Effect on the `enrollment` row |
|---|---|---|
| Register | Registration open, before the add deadline, and every rule passes | New row, status `enrolled` |
| Drop | Up to the term's drop deadline | Status `dropped`, no grade. The row stays but counts nowhere |
| Withdraw | After the drop deadline, up to the withdraw deadline | Status `withdrawn`, grade `W` |
| Post a grade | By the section's instructor of record, from the last day of classes to the grades-due date | The grade, status `completed` |

Registration is refused with one or more of these reasons: `student_not_active`, `registration_not_open`,
`add_deadline_passed`, `already_enrolled`, `already_enrolled_in_another_section`, `prerequisite_not_met`,
`level_not_allowed`, `repeat_not_permitted`, `time_conflict`, `section_cancelled`, `section_full`,
`credit_limit_exceeded`.

Good things to try to break: confirming with other words, confirming after a long pause, asking something else
while a change is waiting, two chat windows for the same student at once, registering for a full or cancelled section, a
time clash, more than 18 credits, posting a grade outside the grading window or for someone else's section.

Because writes change the data, reload it before each test session: `python scripts/load_seed.py`.

## Changes to the database and the data

- **New status `dropped`** on `enrollment`. A dropped row must be invisible: not on a roster, not in a seat count,
  not on a transcript. The loaded data has none; they appear only after a drop.
- **New table `advisor_assignment`**: one advisor per student, 1,200 rows.
- **New table `change_log`**: empty until a change is made.
- One new migration, `b7e4a1c9d2f3`. No existing table or CSV changed otherwise.
- Duong's own enrollment table and data set are not used any more.
- The 35 administrator test cases were recomputed on this data set. The student (208) and professor (202) test sets
  are untouched.

## Changes to code that existed before

- **Professor agent (`main`'s):** kept as it was, 33 tools. Its queries now skip dropped rows, and it accepts the
  added tools (advisees, planner, searches, grade posting). Duong's own professor agent was not kept.
- **Student agent (`main`'s):** unchanged, plus the added tools.
- **Duong's write code:** rewritten for `main`'s table and for rules 2 and 3 above. In his branch any message
  starting with "yes" confirmed, and the model itself could confirm.
- **Mason's coordinator:** follows rule 2 as well. No specialist agent can confirm a change.
- **`db/stop.sh`:** fixed. It had a typo and ignored `.env`.
- **`scripts/load_seed.py`:** also empties `change_log`, so a reload is a full reset.

## What the coordinator adds (`merge-all-three`, with `--multi`)

A message goes to a planner first. It splits the message into at most three tasks and gives each to one specialist:
`data` (records and facts), `policy` (handbook and course search), `advising` (degree planner), `registration`
(prepares changes). Each specialist has only its own tools. The answers are joined into one reply. If the plan is
not valid, the message goes to the single agent instead.

What to look for: does a two-part message ("What is my GPA and what should I take next semester?") get both parts
answered; does a one-part message still get the right answer; is it slower; does the yes/no rule still hold.

## Known problems

- **60 of the 208 student test cases fail in every version**, as on `main`: the Student agent has no tools that
  answer the test set's own-record questions in the test set's format (schedule, eligibility, transcript, GPA,
  degree progress, seats left). The new transcript and GPA tools return a different format.
- **9 professor wordings** cannot be passed by any agent (`registrar/eval/known_issues.py`).
- **No test set covers writes or two-part messages.** Writes are covered by unit tests only (`tests/test_registration.py`).
- Master's students skip two rules: an upper-division course outside their plan is allowed, and so is a graduate
  course whose prerequisite is an undergraduate course in their plan.
- Posting a grade by full name picks one student when two in the section share that name, and the preview does not
  show which.
- A grade asked for a future term during a grading window is moved to the term being graded. The preview shows it.
- Posting grades does not mark the section as submitted (`grade_submission` is not touched).
- "Can I register for X" has two rule sets: the one behind the student test set (`registrar/agent/programs.py`) and
  the one the write path uses. They can disagree.
- The older question-answering pipeline (`registrar/agent/`) and the test-set builders do not skip dropped rows yet.
  This only matters after a drop.
- Each advisor has 44 to 54 students, far more than a real advisor would.
- `docs/schema.html` does not show the new status and tables yet. `docs/system.html` and parts of `README3.md`
  describe the branches before the merge.

## What has been checked, and what has not

Checked, without a model:
- The setup in RUN.md, from an empty folder: packages, database, migration, data load. Also the upgrade from a
  database made on `main`.
- The unit tests on both branches: 545 and 583 passed; the 60 failures are the known student ones.
- Every example in RUN.md section 5, by calling the same tools the model would call.
- The search on its test questions (32 catalog, 30 handbook), keywords only.

Checked with a real model (`qwen3-coder:30b` in Ollama, 2026-11-11), following RUN.md exactly from an empty folder on
each branch: setup, chat, and the short evaluation (67 questions, one of each type).

| Version | Student | Professor | Administrator | Seconds per question |
|---|---|---|---|---|
| single agent (`merge-fuad-duong-rag`) | 16 of 23 | 31 of 33 | 11 of 11 | 5.0 |
| coordinator (`merge-all-three`, `--multi`) | 9 of 23 | 30 of 33 | 11 of 11 | 5.5 |

A register / confirm / drop / cancel conversation was also run on both.

**Not checked:** the full evaluation (445 questions), paraphrases, two-part questions, and any other model.
