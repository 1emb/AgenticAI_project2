# How to run the merged registrar system

There are two versions, on two branches. They share the same data, database, tools and rules. The only difference is
the multi-agent coordinator.

| Branch | What it is |
|---|---|
| `merge-fuad-duong-rag` | One agent per user (student, professor or administrator), picked by the router. Has the catalog and handbook search. |
| `merge-all-three` | The same, plus the multi-agent coordinator: a planner splits a message and hands the parts to specialist agents. Turned on with `--multi`. |

Everything below works on both branches. Steps marked **(all-three only)** need `merge-all-three`.

What changed compared with `main` is in [CHANGES.md](CHANGES.md).

## 1. What you need

- PostgreSQL server and client tools (`initdb`, `pg_ctl`, `psql`, `createdb`).
- Python 3.12 with these packages:
  ```bash
  pip install sqlalchemy "psycopg[binary]" alembic python-dotenv openai pytest clingo
  ```
  `clingo` is new. The degree planner needs it. Without it the planner tools and 2 tests fail; the rest works.
- For chatting and evaluation only: a model server with an OpenAI-compatible API and **tool calling turned on**.
  The tests in step 3 need no model.

## 2. Database

Pick the case that fits you.

### 2a. You have never set up the database

```bash
git checkout merge-all-three            # or merge-fuad-duong-rag
pg_isready -h localhost -p 5433         # "no response" = the port is free; otherwise use another port everywhere below

export PGDATA=$PWD/pgdata
initdb -D "$PGDATA" -U registrar -A trust
echo "port = 5433"                    >> "$PGDATA/postgresql.conf"
echo "listen_addresses = 'localhost'" >> "$PGDATA/postgresql.conf"
echo "unix_socket_directories = ''"   >> "$PGDATA/postgresql.conf"

cp .env.example .env                    # then edit .env: set PGDATA and DATA_DIR to your copy of the repo
./db/start.sh
createdb -h localhost -p 5433 -U registrar registrar
alembic upgrade head
python scripts/load_seed.py
```

`load_seed.py` should end with `... grade_submission 831, advisor_assignment 1200`.

### 2b. You already have the database from `main`

```bash
git checkout merge-all-three            # or merge-fuad-duong-rag
./db/start.sh
alembic upgrade head                    # adds the dropped status, advisor_assignment and change_log
python scripts/load_seed.py             # reloads everything, now with advisor_assignment
```

### Start, stop, reset

```bash
./db/start.sh                           # before working
./db/stop.sh                            # when done
python scripts/load_seed.py             # reset: empties every table and the change log, reloads data/seed
```

Registering, dropping and posting grades **change the database**. Run `load_seed.py` to get the original data back.
Always reset before an evaluation run.

Switching between the two branches needs no database change: they use the same schema and data.

## 3. Check without a model

```bash
pytest -q
```

Expected:

| Branch | Result |
|---|---|
| `merge-fuad-duong-rag` | 545 passed, 60 failed, 3 skipped, 3 xfailed |
| `merge-all-three` | 583 passed, 60 failed, 3 skipped, 3 xfailed |

The 60 failures are all in `tests/test_student_tools.py` (58) and `tests/test_student_agent.py` (2). They are the same
ones `main` has: the Student agent has no tools yet for the newer student questions. Any other failure is a problem.

If most tests are **skipped**, the database is not reachable: start it and check `DATABASE_URL` in `.env`.

## 4. Model server

Set these in `.env` (or export them; the shell wins):

```
LLM_BASE_URL=http://127.0.0.1:11434/v1     # Ollama's default; for vLLM usually http://localhost:8000/v1
LLM_MODEL=qwen3-coder:30b                  # the name your server uses for the model
LLM_API_KEY=ollama                         # any text works for a local server
```

- Ollama: `ollama pull qwen3-coder:30b`, then `ollama serve`.
- vLLM: start it with `--enable-auto-tool-choice` and the `--tool-call-parser` for your model. Without these the
  agents cannot call tools and every answer fails.

Optional, for the search only: set `EMBED_MODEL` (for example `nomic-embed-text` in Ollama) to add meaning-based
search on top of keyword search. Without it the search uses keywords only and still works.

## 5. Chat

```bash
python scripts/registrar_chat.py --user 801930214 --verbose                  # a student (Juan Mitchell, MSCS)
python scripts/registrar_chat.py --user 801408626 --verbose                  # a professor (Jose Wilson, CS)
python scripts/registrar_chat.py --user 900000001 --verbose                  # the registrar administrator
python scripts/registrar_chat.py --user 800020284 --role student             # a TA has two roles and must pick one
python scripts/registrar_chat.py --user 801930214 --multi --show-answer      # (all-three only) through the coordinator
```

Options: `--as-of 2026-11-20T18:00:00Z` sets the clock (without it, the real time is used), `--verbose` prints each
tool call, `--show-answer` prints the graded JSON answer (with `--multi` also the plan and which specialist ran),
`--question "..."` asks one question and exits. Type `quit` to leave.

Use `--as-of` for anything that depends on dates. The data is a snapshot around Fall 2026: Fall 2026 is in progress,
Spring 2027 registration opened on 2026-11-02.

### Things to try

As the student, with `--as-of 2026-11-20T18:00:00Z`:

| Type this | What should happen |
|---|---|
| `What is my GPA?` | GPA from the record |
| `What classes have I taken?` | Transcript: completed, withdrawn, in progress |
| `What should I take next semester?` | A plan from the degree planner |
| `How many credits can I take on probation?` | An answer that cites the handbook (section 3.2, 13 credits) |
| `Which courses cover databases?` | Courses found by topic (CS 3410, CS 5410) |
| `What is Jose Wilson's phone number?` | A refusal |
| `Register me for CRN 10016 next spring` | A preview ending in "Please answer yes or no." Nothing is written |
| then `yes` | "You are registered in CS 3320 (CRN 10016), Spring 2027." |
| `Register me for CRN 10022 next spring` | Refused: the section is full |
| `Drop CRN 10016 for Spring 2027`, then `yes` | Dropped, no record |

How confirmation works: a change is made only when your **next message is exactly `yes`**. `no` discards it. Anything
else ("yes please", "ok", "yes later") does not confirm; you are asked to answer yes or no.

As the professor, with `--as-of 2026-12-12T18:00:00Z` (the Fall 2026 grading window, 2026-12-11 to 2026-12-15):

| Type this | What should happen |
|---|---|
| `Who is in my CRN 10005?` | The roster of his own section |
| `Show my advisees` | His 44 advisees |
| `Post a B+ for Chen Williams in CRN 10005` | A preview; then `yes` posts it |
| `Post an A for Chen Williams in CRN 10001` | Refused: not his section |

As the administrator:

| Type this | What should happen |
|---|---|
| `How many students are on probation?` | A count by program |
| `What was the grade distribution in CS courses in Fall 2025?` | Counts per grade |

**(all-three only)** With `--multi`, also try a message with two parts, for example
`What is my GPA and what should I take next semester?`. `--show-answer` then prints the plan, for example two tasks,
one for the `data` specialist and one for `advising`.

## 6. Evaluate against the test sets

Reset the database first (`python scripts/load_seed.py`).

```bash
python scripts/eval_agents.py --persona all --per-intent 1     # quick: one case per question type, about 55 questions
python scripts/eval_agents.py --persona student                # 208 cases
python scripts/eval_agents.py --persona professor              # 202 cases
python scripts/eval_agents.py --persona administrator          # 35 cases
python scripts/eval_agents.py --persona all                    # all 445
python scripts/eval_agents.py --persona all --multi            # (all-three only) the same cases through the coordinator
```

Other options: `--limit N`, `--intent NAME`, `--id CASE_ID`, `--model`, `--base-url`, `--verbose`.

Each question prints `PASS` or `FAIL`, the seconds it took and the tools called. At the end there is a score per
question type and per persona. Every run is also written to `runs/<persona>-<single|multi>-<model>-<time>.jsonl`
on `merge-all-three`, and `runs/<persona>-<model>-<time>.jsonl` on `merge-fuad-duong-rag`.

To compare the two versions: run the same command with and without `--multi` on `merge-all-three`. Without `--multi`
it behaves the same as `merge-fuad-duong-rag`.

Known before you start:
- About 60 of the 208 student cases fail in every version (the missing Student agent tools from step 3).
- 9 professor wordings cannot be passed by any agent; they are listed in `registrar/eval/known_issues.py`.
- The test sets have one request per question, and none of them registers, drops or posts a grade.

The older per-agent scripts still work and can also run the paraphrases:
`python scripts/eval_student_agent.py --paraphrases`, `python scripts/eval_professor_agent.py --paraphrases`. They
test the Student or Professor agent alone, without the router's added tools.

## 7. Check the search alone (no chat model needed)

```bash
python scripts/eval_rag.py                      # keyword search on data/testset/rag and the policy cases
python scripts/eval_rag.py --query "databases"  # the raw result for one query
```

Expected with keyword search only: policy recall@1 0.87, recall@3 1.00; catalog recall@1 0.93, recall@3 0.96;
correctly empty 1.00.

## 8. If something goes wrong

| What you see | Cause | Fix |
|---|---|---|
| `Connection refused` on port 5433 | The database is not running | `./db/start.sh` |
| `column "..." does not exist`, `relation "advisor_assignment" does not exist` | The database is still at `main`'s schema | `alembic upgrade head`, then `python scripts/load_seed.py` |
| `violates check constraint "ck_enrollment_enrollment_status"` | Same | Same |
| `ModuleNotFoundError: No module named 'clingo'` | The planner's solver is missing | `pip install clingo` |
| Every answer fails with no tools called | The model server has tool calling off, or `LLM_MODEL` is not the server's name for the model | See step 4 |
| `... has several roles (instructor, student); log in as one of them` | The user is a TA | Add `--role student` or `--role instructor` |
| A registration that worked before is now refused as `already_enrolled` | An earlier test changed the data | `python scripts/load_seed.py` |
