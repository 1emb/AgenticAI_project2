# Registrar replacement

Agentic system that takes over the functions of a university registrar office. This repository holds the domain
definition, the PostgreSQL schema, the test sets, and the agent itself (`registrar/agent/`, student persona so far).

The schema was rebuilt on 2026-10-28 around natural keys and a two-major scope (BS Computer Science and BS
Engineering, plus an MS in each for graduate students). The dataset is a static snapshot committed as one CSV per
table under `data/seed/` (35,147 rows, written by the deterministic generator in `registrar/seed/`); the agents only
read it. The test sets under `data/testset/` are regenerated from it (student set extended 2026-11-01, 2026-11-02 with
the enrollment table, and 2026-11-05 with four times the students, salaries, section staff and grade submissions).
**Building or testing a system against the data: start with [data/README.md](data/README.md).**

## Layout
```
registrar/models/   SQLAlchemy 2.0 models (18 tables)       docs/domain.md    what the registrar does, data, users
registrar/db.py     engine / session (reads .env)            docs/schema.html  visual schema reference with example rows
registrar/seed/     dataset generator; catalog.py holds the  data/seed/        the dataset, one CSV per table
                    courses and plans, records.py enrollment scripts/          seed.py, load_seed.py, check_seed.py, make_testset.py, init_db.py
registrar/testset/  question -> SQL -> answer generators     data/testset/     English test cases (see its README)
registrar/agent/    the agent: classify, extract, resolve,   scripts/          ask.py (one question), grade.py (a test set),
                    permission check, per-intent programs,                     serve_llm.sh (local vLLM server), ui.py (web chat)
                    English reply
registrar/ui/       FastAPI web chat: app.py + static/index.html         runs/             chat.jsonl (interactive test log), grading runs
registrar/chatlog.py  append-only log of interactive questions and verdicts  scripts/          review.py (summarise the log)
db/                 start.sh / stop.sh / psql.sh             alembic/          migrations
pgdata/             Postgres 18 cluster (port 5433)
```
Everything lives on `/home/sheshnagnobackup/mnguyen/AgenticAI_project2`; `~/AgenticAI_project2` is a symlink.
Not in git: `pgdata/` and `.env` (copy `.env.example`).

## Schema
Visual reference, one section per table with example rows that follow the same people across tables:
https://claude.ai/artifact/8XjEo8BMjePpb2vcKgHUye (the same page is saved as [docs/schema.html](docs/schema.html)).

PostgreSQL 18, SQLAlchemy 2.0 models in `registrar/models/`. 18 tables. Natural keys throughout: a human is identified
by `university_id`, a course by its catalog code, a term by its six-digit code, a lecture by term plus CRN.
Enums are VARCHAR with CHECK constraints (see `registrar/models/enums.py`); adding a value needs an Alembic migration.
Enrollment (student x lecture with status and grade) and transfer credit were added on 2026-11-02 (`records.py`, Alembic
revision `64244b3c17e8`); instructor salary, section staff and grade submission on 2026-11-05 (revision `9d2f5b7c41a0`).

In one paragraph: `person` (keyed by `university_id`) carries name, DOB, sex, SSN, phone, email. `student` and
`instructor` share that key and add their profiles; a student points at one `program`, an instructor at one
`department`. `course` and `course_prerequisite` are the catalog; `degree_requirement` and
`program_category_requirement` say what each program needs; `lecture` is a course offered in an `academic_term` by one
instructor with its meeting pattern. `grade_scale` maps letter grades to grade points. `enrollment` is one student in one
lecture with a status and a grade; `transfer_credit` is a course accepted from another institution. `lecture_staff` lists
who works on each section (its instructor of record and any TAs); `grade_submission` records when a section's final grades
were submitted.

### People (`people.py`)
| Table | Key | Columns |
|---|---|---|
| `person` | `university_id` (9 chars) | `first_name`, `last_name`, `date_of_birth`, `sex` (M/F/X, CHECK), `ssn` (raw, synthetic, unique), `phone`, `email` (unique) |
| `student` | `university_id` = FK `person` | `program_code` FK, `status` (active, leave_of_absence, withdrawn, suspended, dismissed, graduated), `entry_type` (first_time, transfer, readmit), `residency` (resident, nonresident, international), `admit_term_code` FK, `expected_graduation_term_code` FK nullable |
| `instructor` | `university_id` = FK `person` | `department_code` FK, `rank` (free text: professor, associate, assistant, lecturer, adjunct, ta), `is_active`, `hire_date`, `salary` (annual whole dollars; a TA's stipend, an adjunct's annual equivalent; own record only) |

One `person` row per human. A graduate teaching assistant has one `person`, one `student` and one `instructor` row
sharing the same `university_id`. Whether a student is undergraduate or graduate follows from `program.degree`.

### Academic structure (`academic.py`)
| Table | Key | Columns |
|---|---|---|
| `department` | `code` (CS, ENG, MATH, ...) | `name`. One row per subject code, because `course.subject` points here. |
| `program` | `code` (BSCS, BSENG, MSCS, MSENG) | `department_code` FK, `name`, `degree` (BS, MS), `total_credits_required`, `min_gpa` |
| `academic_term` | `code` (202680 = Fall 2026) | `name`, `term_type` (fall/spring/summer), `academic_year`, `start_date`, `end_date`, `registration_opens`, `add_deadline`, `drop_deadline` (no W), `withdraw_deadline` (W), `grades_due`, `sequence` (unique ordinal) |

### Catalog, degree plan, lectures (`catalog.py`)
| Table | Key | Columns |
|---|---|---|
| `course` | `code` ("CS 2210") | `subject` FK `department`, `number` (unique together), `title`, `description`, `credit_hours`, `level` (lower_division/upper_division/graduate), `is_active` |
| `course_prerequisite` | (`course_code`, `required_course_code`) | `min_grade` FK `grade_scale` (default C-), `group_number`. Rows sharing a group are OR alternatives; different groups are all required. A course cannot require itself (CHECK). |
| `degree_requirement` | (`program_code`, `course_code`) | `category` (core/elective/general_education), `is_required` (False = choose from the category), `suggested_term_number` (1 to 8) |
| `program_category_requirement` | (`program_code`, `category`) | `min_credits`. Credits the program needs from that category. Core needs no row: its credits are the sum of the required courses. |
| `lecture` | (`term_code`, `crn`) | `course_code` FK, `section_number` (M01), `instructor_university_id` FK `instructor`, `days` (subset of MTWRFSU), `start_time`, `end_time`, `room`, `capacity`, `is_cancelled` |

Three layers: `course` + `course_prerequisite` say what exists and what it takes to get in; `degree_requirement` and
`program_category_requirement` say what a program needs to graduate; `lecture` says who teaches what in a given term.
One lecture has one instructor and one weekly meeting pattern.

### Grades (`grades.py`)
| Table | Key | Columns |
|---|---|---|
| `grade_scale` | `letter` (A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F, W, I) | `points` (4.0 down to 0.0; null for W and I) |

Reference data: the initial migration inserts the 14 rows. `course_prerequisite.min_grade` points here, and so does
`enrollment.grade`. "C- or better" means points >= 1.7. GPA = sum(points x credit hours) / sum(credit hours) over
rows with points; a grade earns credit when points > 0, so F, W and I earn nothing.

### Records (`records.py`)
| Table | Key | Columns |
|---|---|---|
| `enrollment` | (`term_code`, `crn`, `student_university_id`); (`term_code`, `crn`) FK `lecture`, the student FK `student` | `status` (enrolled, completed, withdrawn, dropped), `grade` FK `grade_scale`, nullable. CHECK `status_grade`: enrolled has no grade, withdrawn has W, completed has any other grade, dropped has no grade. |
| `transfer_credit` | (`student_university_id`, `course_code`) | `credit_hours`, `accepted_term_code` FK `academic_term`. A course accepted from another institution: it meets prerequisites and earns credit, has no grade and stays outside the GPA. |
| `lecture_staff` | (`term_code`, `crn`, `university_id`); (`term_code`, `crn`) FK `lecture`, the person FK `instructor` | `role` (instructor, ta; CHECK). Every section has its instructor of record here (the same person as `lecture.instructor_university_id`); each TA assists two lower-division sections of their department per term from Fall 2025, never one they teach and never at a time they teach or sit in class. |
| `grade_submission` | (`term_code`, `crn`) FK `lecture` | `submitted_by` FK `instructor` (the instructor of record), `submitted_at` (timestamptz, UTC). One row per section with students in a graded term (up to Spring 2026); about 8% arrive one to three days after `grades_due`. No row = not submitted (every Fall 2026 and Spring 2027 section) or no students. |

| `advisor_assignment` (`advising.py`) | `student_university_id` FK `student` | `advisor_university_id` FK `instructor`. One advisor per student: the active non-TA instructors of the department that runs the student's program, handed out in turn (1,200 rows, 25 advisors). Added 2026-11-11. |
| `change_log` (`audit.py`) | `id` | `at`, `clock` (the agent's clock at the change), `actor_university_id`, `role`, `action` (register, drop, withdraw, post_grade), `detail` (JSONB). Written only by the write path; empty in the seed. Added 2026-11-11. |

`dropped` (2026-11-11, Alembic `b7e4a1c9d2f3`): a student who leaves a section by the drop deadline keeps the row with status
`dropped` and no grade. A dropped row is on no record and holds no seat, so every count, roster and transcript query leaves it
out. The seed has no dropped rows; they only appear when the write path runs. The agents under `registrar/agents/` skip them;
the test-set builders and `registrar/agent/programs.py` (through `registrar/testset/queries.py`) do not yet.

Added 2026-11-02. One row per student per section: `enrolled` while the term is in progress or still ahead (Fall 2026 and the
Spring 2027 registrations), `completed` with a letter grade or I once posted, `withdrawn` with W. A student who repeats a course
has one row per attempt. Rules the agent applies (`registrar/agent/programs.py`): a course is passed at the first grade with
points > 0 and earns its credits once; a grade of C (2.0) or better cannot be repeated (`PASS_TO_REPEAT`); a prerequisite is met
by a grade at or above `min_grade`, by a transfer credit, or, for the coming term, by a current enrollment in it; MS students
have no prerequisite checks; the seats taken in a section are its non-withdrawn rows; Fall 2026 grades are not posted whatever
the clock, because the dataset is a snapshot. GPA = sum(points x credit hours) / sum(credit hours) over graded rows (W and I
excluded); a term's GPA uses that term's rows only.

### Conventions
- No surrogate integer ids. Foreign keys carry the natural key of the parent, so `student.program_code` is readable without a join.
- Timestamps are not yet needed; every date column is a policy date, stored as `date`.
- Column defaults are server defaults (`is_active`, `is_cancelled`, `is_required`, `min_gpa`, `min_grade`, `group_number`), so raw SQL and COPY loads may omit them.
- The current term is not stored; a stored flag would contradict the per-case clock in the test sets. Rule (noted 2026-10-28): the current term is the one whose `start_date` <= clock <= `end_date`. When the clock falls in a break between terms, the current term is the next one by `start_date`, because students then ask about the coming term; the term that just ended is "last semester". Example: on 2026-12-20, after Fall 2026 ends on 2026-12-11, "my schedule" means Spring 2027 and "my grades last semester" means Fall 2026.
- Not modeled (decided 2026-10-28; enrollment and transfer credit added 2026-11-02): academic standing history (derive from term GPA against `program.min_gpa` when needed), registration appointments, holds and waitlists.
- Whether a lecture is full is not stored: it is the count of `enrollment` rows whose status is not `withdrawn` against `capacity`; `is_cancelled` is the only stored state.
- `rank` on `instructor` is free text on purpose. Promote it to an enum once the set is settled.
- The initial migration is frozen because it carries the `grade_scale` rows. Further schema changes are new Alembic revisions (`alembic revision --autogenerate`).

## Setup
```bash
conda activate /home/sheshnagnobackup/mnguyen/envs/registrar
./db/start.sh                     # starts Postgres on localhost:5433 (TCP only, no unix socket)
./db/psql.sh                      # psql into the registrar database
alembic upgrade head              # create the tables and the grade_scale rows
python scripts/load_seed.py       # load data/seed/*.csv (empties the sixteen data tables first)
```
Connection string: `postgresql+psycopg://registrar@localhost:5433/registrar` (in `.env` as `DATABASE_URL`).
To rebuild from scratch: `dropdb -h localhost -p 5433 -U registrar registrar && createdb -h localhost -p 5433 -U registrar registrar`,
then `alembic upgrade head`. `python scripts/init_db.py --drop` creates the tables from the models without Alembic
and without the grade_scale rows.

## Dataset
`data/seed/` is the whole dataset: 10 departments, 4 programs, 20 terms (Fall 2021 to Spring 2031), 1,255 people
(1,200 students: 600 BSCS, 480 BSENG, 60 MSCS, 60 MSENG; 61 instructors, six of them MS students working as TAs, ten
former instructors who only taught before Fall 2024 and six hired for the added sections), 72 courses (two retired), 73
prerequisite rows, 97 degree-plan rows, 6 category minimums, 1,558 lectures over Fall 2021 to Spring 2027, 25,960
enrollment rows, 1,194 transfer credits, 1,606 section-staff rows (48 of them TAs) and 831 grade submissions. Every value
is synthetic. 100 full names are shared by two or three people; the test-set builders only pick people whose full name is
unique (`registrar/testset/common.py`, `UNIQUE_NAME`).

Scale-up (2026-11-05, owner): with 300 students a section held a median of 4 to 7 students. Three more cohorts of each
program (900 students) are drawn after everything else, so the original 300 students, 55 instructors and 1,402 lectures
are byte-identical. A dry run with unlimited seats measures each term's demand per course, and 152 sections are appended
(higher CRNs, own random stream) until capacity covers demand plus 15%; six instructors are hired where a department had
no one free. Fall 2026 now has 154 sections with a median of 26 students (53% of seats). Each student's record draws
from its own random stream, but records still change when the seats they compete for change: all enrollment rows were
regenerated. `python scripts/seed.py` regenerates the CSVs byte for byte from `registrar/seed/`
(seed 42; `--load` also loads them); `python scripts/check_seed.py` checks the loaded records against the rules in
`registrar/seed/records.py` (prerequisites, capacities, time clashes, graduation, status against GPA) and prints a
profile. The data and the test sets are frozen together: regenerating with a different seed or catalog changes the
answers in `data/testset/`, so rerun `make_testset.py` too.

Enrollment history (added 2026-11-02): every student has a term-by-term record consistent with their status, admit term
and degree plan: completed terms with grades, Fall 2026 in progress (no grades posted, whatever the clock), a Spring 2027
registration for about half of the active students; retakes of failed required courses, prerequisites honoured by an
earlier grade or a transfer credit, section capacities and time clashes respected (TAs' teaching slots included);
graduated students have complete records at or above the program's minimum GPA, suspended and dismissed students fall
below it. Ten student rows changed with the rebuild because graduation now needs seven completed terms (six for transfer
students): nine six-term "graduates" became active students expected to graduate in Spring 2027, and one graduation
moved from Fall 2026 to Spring 2026. The data is append-only: the six lecture terms from Fall 2024 are byte-identical to
the previous snapshot; the earlier terms, the former instructors and the records were generated after them.

## Test dataset
`data/testset/` holds English questions with program-checkable answers: 208 student cases and 118 professor cases,
each with two paraphrases, a simulated clock (`as_of`), the authenticated user, and a discrete `answer` that starts
with `allowed`. Forty student cases and twenty-six professor cases test access control. The student intents cover the
catalog, lectures, degree plans, the calendar and, since 2026-11-02, the student's own record: schedule, registration
eligibility, transcript, GPA and degree progress. The professor set still covers teaching schedules and the catalog;
its roster and grade-statistics intents are listed as pending in its `questions.md`. Formats, clocks, the permission model and
the verification contract are in [data/testset/README.md](data/testset/README.md).

## Agent
`registrar/agent/` answers a student's English question in four stages; the first two are calls to a local LLM, the rest is
plain Python over the database. One request is answered per message (owner, 2026-11-02): a third small LLM call,
`count_requests`, answers "how many requests?" with a digit (a word pair such as "one request / more than one" always came back
"one"), and when it says more than one the reply ends with "You asked more than one thing; I handle one request per message, so
please ask the rest separately." When the counter says more than one and the classifier says `unknown`, a restricted second
choice (`rescue_label`: the servable labels plus "none of these") asks which label covers any request in the message; the
classifier reads one request per message well and two badly, and wording changes to its rule only moved the misses around, so
the split is structural. Measured on the Codex sets: every tagged two-request row flagged (25/25 dev, 60/60 and 107/108
acceptance), fewer than one untagged row in a hundred flagged too, none of the 161 graded student questions of the time. The classifier still decides which request is answered:

1. **Classify** (`llm.py`): the model may only reply with one of the 23 labels in `intents.py`: 22 answerable question types (17 about the
   catalog, degree plans and the calendar, and since 2026-11-02 five about the asker's own record: `my_schedule`, `can_register`,
   `my_transcript`, `my_gpa`, `degree_progress`), `student_list` (always refused), and `unknown` for everything else. `unknown`
   covers greetings and nonsense but also every registrar matter this assistant has no data or power for (holds, waitlists,
   enrollment verification, official transcripts sent to a third party, carrying out add/drop/swap/withdraw) and every service that is not the registrar's (tuition, financial aid, parking, housing, dining, IT,
   instructor office hours, advising); its reply is one fixed "I don't know what you are talking about" sentence plus the scope
   sentence. Two referral labels with topic slots and an office table (`not_in_data`, `outside_registrar`, 2026-11-02, Codex design
   review) were tried and folded back into `unknown` the same day, owner's decision, see commit `c436eef` for the implementation.
   vLLM's `structured_outputs.choice` enforces the label set, and the token logprobs give a confidence (kept for diagnosis only; misclassifications have scored 0.99).
   Access control is not a question type: "What is Raj Martinez's phone number?" classifies as `person_info`. Each label's
   description says what it covers and which neighbouring questions belong elsewhere; the classifier rules in `CLASSIFY_SYSTEM`
   settle the boundaries that matter most: "can I take/register for/add COURSE or CRN", "am I eligible", "do I meet the
   prerequisites" is `can_register` (an information-only check of the registration rules: status, window, offering, prerequisites,
   not already passed, seats, time clash; the reply says it is not a registration), "yet/still/now" cues without a course
   are `register_when` (so is "my time ticket": individual appointments are not recorded, the reply gives the general window and
   says so), add/drop/withdraw timing is `term_dates`, "add me / withdraw me" is an action (`unknown`), and a
   message with two independent requests is classified by the one this assistant can serve (owner, 2026-11-02, after five of
   the seven blind-set misses were the model doing exactly that against the earlier first-in-textual-order rule); when both can
   be served, the first in textual order wins, and the reply says that only one request was handled.
2. **Extract** (`llm.py`): given the type, the model fills that type's slot schema (`structured_outputs.json`) with
   *mentions*, phrases copied from the question: `{"course_mention": "Capstone Design I", "term_mention": "next spring"}`.
   It never writes database keys.
3. **Resolve** (`resolve.py`): Python turns mentions into keys with the database and the case clock: the title becomes
   `ENG 4910`, "next spring" under a November 2026 clock becomes term `202710`, a name becomes a university id. Each
   resolution carries a status (`ok`, `none`, `not_found`, `ambiguous`), so a wrong answer is traceable to its stage.
4. **Program** (`programs.py`): one function per intent applies the permission rule from `data/testset/README.md` and
   runs the SQL from `registrar/testset/queries.py`, returning the discrete answer shape the test set grades.
5. **Reply** (`reply.py`, 2026-11-01, made deterministic 2026-11-02): one writer per intent turns the discrete answer into one to
   three English sentences; refusals and clarifications are fixed sentences. There is no conversation state (owner, 2026-11-02),
   so a clarification tells the student to ask again with the missing piece included rather than asking a follow-up question
   whose answer the next turn could not be matched to. No model is involved, so the reply can neither
   invent a fact nor leak one, and it costs nothing (the whole pipeline runs in about 0.2 s per question against 1.3 s with a model
   reply). The earlier LLM rendering is kept for comparison only (`ask.py --llm-reply`, `reply_mode: "llm"` in the web API). The
   change followed the 90-question Codex run (`runs/codex/phase2-report.md`): in every case where the English was wrong the JSON
   answer was right; the model had turned AND into OR, "not in your plan" into "yes", and invented "no holds" and "no longer
   enrolled". `grade.py --reply` scans the reply for `must_not_mention` values (0 leaks on the 208 student cases and their paraphrases).

Model: Qwen3.5-27B served by vLLM 0.32 on one H100 (`scripts/serve_llm.sh`; weights under
`/home/sheshnagnobackup/mnguyen/models`, outside the repo). `.env` holds `LLM_BASE_URL` and `LLM_MODEL`.

```bash
./db/start.sh && scripts/serve_llm.sh &                       # Postgres and the model server, from your own terminal
python scripts/ask.py --uid 800260544 "Who teaches CS 2230 this fall?"     # one question, full trace and English reply
python scripts/ask.py --case stu-prerequisites-001                         # a test case, with its expected answer
python scripts/grade.py --persona student --paraphrases                    # the whole set; per-stage accuracy, failures, runs/*.jsonl
python scripts/grade.py --persona student --reply                          # also write replies and fail any that leak a protected value
python scripts/ui.py                                                       # web chat at http://127.0.0.1:8080
```

The grader scores each question three times: the intent, the resolved slots against the case's `slots`, and the answer
under the verification contract. With `--reply` the English reply is written too and scanned for `must_not_mention` values.

### Web chat (`scripts/ui.py`)
A single page served by FastAPI (`registrar/ui/`): choose the student from the 1,200 in the database (filter by name, ID or
program), choose the clock (the five test-set clocks, or any UTC datetime), ask, and read the reply. Each reply expands to show
how it was produced: intent and confidence, the mentions, each resolution with its status, the graded answer, the SQL and the
per-stage timings. Refusals are marked. In the question box, Up recalls earlier questions (this session first, then the
saved log, newest first) and Down walks forward to the unsent draft, as in a shell. From a laptop, forward the port (`ssh -L 8080:localhost:8080 <host>`) and open
`http://localhost:8080`. There is no login; the student is a choice, since this is a simulation.

### Test log (`runs/chat.jsonl`)
Every question asked through the web chat or `scripts/ask.py` is appended to `runs/chat.jsonl` (`registrar/chatlog.py`;
path overridable with `CHAT_LOG`): who asked, the clock, the question, and the whole trace, including the reply, the SQL
and timings. Under each answer the page has verdict buttons (correct, wrong, should have refused, should have answered)
and a note; they append verdict records to the same file, latest wins. Each verdict says who judged (`by`: owner from the
page, or a judge name such as `codex` for verdicts imported with `scripts/import_verdicts.py <file> --by codex`); the
History view marks imported verdicts with the judge's name and can filter by judge, and clicking overrules them. The
History view lists everything recorded, filterable by text, intent, outcome, verdict, judge and student, and opens any
row's full trace with its verdict controls.
`grade.py` runs are not logged there; they keep their own `runs/<persona>-<timestamp>.jsonl`.

```bash
python scripts/review.py                     # counts by outcome, verdict and intent; what was judged wrong; errors; slowest
python scripts/review.py --list unjudged     # or: wrong | should_refuse | should_answer | refused | error | all
python scripts/review.py --csv runs/chat.csv # one row per question, for a spreadsheet
```
`runs/` is git-ignored, so the log stays on this machine.

## Merged system (2026-11-11)
Duong's branch `advising-agent` (af41cf6) and then Mason's branch `mason` (fdf81d8, the coordinator and RAG on top of
Duong's) merged into main's agents (a846c19), with main as the base:

| Part | Where | From |
|---|---|---|
| Student and Professor agents, eval runner | `registrar/agents/student/`, `professor/`, `registrar/eval/` | main, unchanged except that the Professor agent accepts extra tools and its queries skip dropped rows |
| Router (role from the login), Administrator agent | `registrar/agents/router.py`, `admin/` | Duong |
| Own transcript and GPA, degree planner (clingo), handbook search | `registrar/agents/records.py`, `advising.py` + `advising_agent/`, `policy.py` + `data/policy/` | Duong, reading main's `enrollment` and `transfer_credit` |
| Writes: register, drop / withdraw, post a grade | `registrar/agents/registration.py` | Duong, rewritten for main's table |
| Multi-agent coordinator: planner, four specialists (data, policy, advising, registration), composer | `registrar/agents/multi/` | Mason (fdf81d8); `scripts/registrar_chat.py --multi` |
| Retrieval over the handbook and the course catalog (BM25, plus embeddings when `EMBED_MODEL` is set), `search_catalog` tool | `registrar/rag/`, `data/testset/rag/` | Mason; details in [README3.md](README3.md) |

Duong's own enrollment table and data (`data/seed_enrollment/`) are gone; everything reads `data/seed/`. The administrator
cases (`data/testset/administrator/cases.jsonl`, 35) were regenerated on this dataset by `registrar/testset/administrator.py`.

How a write works: the request tool checks the rules and shows a preview; nothing is written. The change is made only when
the user's next message is exactly "yes" ("no" discards it); the model has no tool that confirms. At the yes the date and
the rows are read again under row locks and the change is worked out afresh: if it is no longer what was shown (a drop
that became a withdrawal, a section that moved), nothing is written and the user is asked again.

```bash
alembic upgrade head && python scripts/load_seed.py     # adds advisor_assignment, change_log and the dropped status
pip install clingo                                      # the degree planner
python scripts/registrar_chat.py --user 801930214       # student; instructors and 900000001 (admin) work too
pytest -q                                               # no model needed
```
Older write-up of Duong's branch before the merge: [docs/system.html](docs/system.html). Not done yet: the student test set's
own-record intents still fail on main's Student agent (its 60 known failures); the write path has unit tests
(`tests/test_registration.py`) but no test set; of the 2026-11-10 review of the write path, still open are the master's
program rules (5.2, 6.1), a grade for a student whose full name is shared, an explicit future term moved to the open grading
term, and a change log that cannot undo a change by itself.

## Next steps
1. The professor persona (same pipeline, its own intents), then a persona switch in the web chat.
2. Multi-turn chat: the UI sends each question alone today, so "and next spring?" has no context.
3. On the enrollment table (2026-11-02): the professor's roster intents (who is in my section, enrollment counts, grade
   distributions), the administrator persona, and a `my_schedule` check for one CRN ("am I still in CRN 10025"). Still not
   modeled: holds, waitlists, time tickets, carrying out registration changes.
