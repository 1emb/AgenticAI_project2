# Registrar replacement: data layer

Agentic system that takes over the functions of a university registrar office. This repository holds the domain
definition, the PostgreSQL schema, and the test sets for the agents.

The schema was rebuilt on 2026-10-28 around natural keys and a two-major scope (BS Computer Science and BS
Engineering, plus an MS in each for graduate students). The dataset is a static snapshot committed as one CSV per
table under `data/seed/` (1,660 rows, written by the deterministic generator in `registrar/seed/`); the agents only
read it. The test sets under `data/testset/` were regenerated from it the same day.

## Layout
```
registrar/models/   SQLAlchemy 2.0 models (12 tables)       docs/domain.md    what the registrar does, data, users
registrar/db.py     engine / session (reads .env)            docs/schema.html  visual schema reference with example rows
registrar/seed/     dataset generator; catalog.py holds the  data/seed/        the dataset, one CSV per table
                    hand-written courses and degree plans    scripts/          seed.py, load_seed.py, make_testset.py, init_db.py
registrar/testset/  question -> SQL -> answer generators     data/testset/     English test cases (see its README)
db/                 start.sh / stop.sh / psql.sh             alembic/          migrations
pgdata/             Postgres 18 cluster (port 5433)
```
Everything lives on `/home/sheshnagnobackup/mnguyen/AgenticAI_project2`; `~/AgenticAI_project2` is a symlink.
Not in git: `pgdata/` and `.env` (copy `.env.example`).

## Schema
Visual reference, one section per table with example rows that follow the same people across tables:
https://claude.ai/artifact/8XjEo8BMjePpb2vcKgHUye (the same page is saved as [docs/schema.html](docs/schema.html)).

PostgreSQL 18, SQLAlchemy 2.0 models in `registrar/models/`. 12 tables. Natural keys throughout: a human is identified
by `university_id`, a course by its catalog code, a term by its six-digit code, a lecture by term plus CRN.
Enums are VARCHAR with CHECK constraints (see `registrar/models/enums.py`); adding a value needs an Alembic migration.
Enrollment (student x lecture with grade) is deliberately not modeled yet.

In one paragraph: `person` (keyed by `university_id`) carries name, DOB, sex, SSN, phone, email. `student` and
`instructor` share that key and add their profiles; a student points at one `program`, an instructor at one
`department`. `course` and `course_prerequisite` are the catalog; `degree_requirement` and
`program_category_requirement` say what each program needs; `lecture` is a course offered in an `academic_term` by one
instructor with its meeting pattern. `grade_scale` maps letter grades to grade points.

### People (`people.py`)
| Table | Key | Columns |
|---|---|---|
| `person` | `university_id` (9 chars) | `first_name`, `last_name`, `date_of_birth`, `sex` (M/F/X, CHECK), `ssn` (raw, synthetic, unique), `phone`, `email` (unique) |
| `student` | `university_id` = FK `person` | `program_code` FK, `status` (active, leave_of_absence, withdrawn, suspended, dismissed, graduated), `entry_type` (first_time, transfer, readmit), `residency` (resident, nonresident, international), `admit_term_code` FK, `expected_graduation_term_code` FK nullable |
| `instructor` | `university_id` = FK `person` | `department_code` FK, `rank` (free text: professor, associate, assistant, lecturer, adjunct, ta), `is_active`, `hire_date` |

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

Reference data: the initial migration inserts the 14 rows. `course_prerequisite.min_grade` points here, and so will
the enrollment grade. "C- or better" means points >= 1.7. GPA = sum(points x credit hours) / sum(credit hours) over
rows with points; a grade earns credit when points > 0, so F, W and I earn nothing.

### Conventions
- No surrogate integer ids. Foreign keys carry the natural key of the parent, so `student.program_code` is readable without a join.
- Timestamps are not yet needed; every date column is a policy date, stored as `date`.
- Column defaults are server defaults (`is_active`, `is_cancelled`, `is_required`, `min_gpa`, `min_grade`, `group_number`), so raw SQL and COPY loads may omit them.
- The current term is not stored; a stored flag would contradict the per-case clock in the test sets. Rule (noted 2026-10-28): the current term is the one whose `start_date` <= clock <= `end_date`. When the clock falls in a break between terms, the current term is the next one by `start_date`, because students then ask about the coming term; the term that just ended is "last semester". Example: on 2026-12-20, after Fall 2026 ends on 2026-12-11, "my schedule" means Spring 2027 and "my grades last semester" means Fall 2026.
- Not modeled for now (decided 2026-10-28): enrollment, academic standing history (derive from term GPA against `program.min_gpa` when needed), registration appointments, holds and waitlists. Old test cases that depend on them are dropped at regeneration.
- Whether a lecture is full is not stored. It comes from enrollment counted against `capacity`; `is_cancelled` is the only stored state.
- `rank` on `instructor` is free text on purpose. Promote it to an enum once the set is settled.
- The initial migration is frozen because it carries the `grade_scale` rows. Further schema changes are new Alembic revisions (`alembic revision --autogenerate`).

## Setup
```bash
conda activate /home/sheshnagnobackup/mnguyen/envs/registrar
./db/start.sh                     # starts Postgres on localhost:5433 (TCP only, no unix socket)
./db/psql.sh                      # psql into the registrar database
alembic upgrade head              # create the tables and the grade_scale rows
python scripts/load_seed.py       # load data/seed/*.csv (empties the eleven data tables first)
```
Connection string: `postgresql+psycopg://registrar@localhost:5433/registrar` (in `.env` as `DATABASE_URL`).
To rebuild from scratch: `dropdb -h localhost -p 5433 -U registrar registrar && createdb -h localhost -p 5433 -U registrar registrar`,
then `alembic upgrade head`. `python scripts/init_db.py --drop` creates the tables from the models without Alembic
and without the grade_scale rows.

## Dataset
`data/seed/` is the whole dataset: 10 departments, 4 programs, 20 terms (Fall 2021 to Spring 2031), 339 people
(300 students: 150 BSCS, 120 BSENG, 15 MSCS, 15 MSENG; 45 instructors, six of them MS students working as TAs),
72 courses (two retired), 73 prerequisite rows, 97 degree-plan rows, 6 category minimums and 694 lectures over
Fall 2024 to Spring 2027. Every value is synthetic. `python scripts/seed.py` regenerates the CSVs byte for byte
from `registrar/seed/` (seed 42; `--load` also loads them). The data and the test sets are frozen together:
regenerating with a different seed or catalog changes the answers in `data/testset/`, so rerun `make_testset.py` too.

## Test dataset
`data/testset/` holds English questions with program-checkable answers: 152 student cases and 118 professor cases,
each with two paraphrases, a simulated clock (`as_of`), the authenticated user, and a discrete `answer` that starts
with `allowed`. Twenty-six cases per persona test access control. The intents cover the catalog, lectures, degree
plans, the calendar and teaching schedules; everything that needs enrollment (registration, transcripts, rosters,
grade statistics) is listed as pending in each persona's `questions.md`. Formats, clocks, the permission model and
the verification contract are in [data/testset/README.md](data/testset/README.md).

## Next steps
1. The agent itself, graded against `data/testset/` (the schema and data are frozen for it).
2. When the schema reopens: `enrollment` table, proposed as (`term_code`, `crn`, `student_university_id`) with `status` (enrolled/dropped/withdrawn) and `grade` FK `grade_scale`; then the pending intents (registration, transcripts, GPA, rosters, grade statistics) and the administrator persona.
