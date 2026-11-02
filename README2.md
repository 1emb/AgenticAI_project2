# README2: Database setup and the Student agent

This file adds to [README.md](README.md). It explains how to run the database on your own account, what changed in
`db/start.sh` and `db/stop.sh`, and how to run, evaluate and test the Student agent.

**Legend:** 🟢 new file · 🟡 changed file · 🔵 unchanged, for reference. In code blocks, green `+` lines were added
and red `-` lines were removed.

---

## What changed

| | File | Change |
|---|---|---|
| 🟡 | `db/start.sh`, `db/stop.sh` | Read `PGDATA` from `.env` instead of a hardcoded path, so every user runs their own cluster |
| 🟡 | `.env.example` | Added `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` for the model endpoint |
| 🟡 | `.gitignore` | Ignore `runs/` (evaluation outputs) |
| 🟡 | `README.md` | Layout table and a Student agent section |
| 🟢 | `registrar/agents/` | The agents: tool loop, clock and term rules, Student agent |
| 🟢 | `registrar/eval/grader.py` | The test set's verification contract as code |
| 🟢 | `scripts/student_agent.py` | Chat with the Student agent |
| 🟢 | `scripts/eval_student_agent.py` | Grade the agent against `data/testset/student/` |
| 🟢 | `tests/`, `pytest.ini` | 192 tests; no model needed |
| 🟢 | `README2.md` | This file |

---

## 1. Requirements

- PostgreSQL server and client tools: `initdb`, `pg_ctl`, `psql`, `createdb` (check with `which initdb`).
- Python packages, in whichever environment you use:
  ```bash
  pip install sqlalchemy "psycopg[binary]" alembic python-dotenv openai pytest
  ```
- For the agent only: [Ollama](https://ollama.com) running with a tool-calling model:
  ```bash
  ollama pull qwen3-coder:30b
  ```

---

## 2. Database setup (once per user)

> [!IMPORTANT]
> `pgdata/` is not in git, and the original scripts pointed at another user's home folder. Running them gives
> `pg_ctl: could not access directory ".../pgdata": Permission denied`. Every user creates their own cluster once,
> inside their own copy of the repo.

**Step 1. Check that port 5433 is free.**
```bash
pg_isready -h localhost -p 5433
```
"no response" means the port is free. "accepting connections" means another server (perhaps a colleague's on the same
machine) uses it: pick another port such as 5434 and use it everywhere below.

**Step 2. Create the cluster inside the repo.**
```bash
cd ~/Documents/GitHubRepos/AgenticAI_project2      # your copy of the repo
export PGDATA=$PWD/pgdata
initdb -D "$PGDATA" -U registrar -A trust
echo "port = 5433"                    >> "$PGDATA/postgresql.conf"
echo "listen_addresses = 'localhost'" >> "$PGDATA/postgresql.conf"
echo "unix_socket_directories = ''"   >> "$PGDATA/postgresql.conf"
```

**Step 3. Create `.env`** (not in git; each user has their own).
```bash
cp .env.example .env
```
Edit the paths to point at your copy:
```
DATABASE_URL=postgresql+psycopg://registrar@localhost:5433/registrar
PGDATA=/home/<you>/Documents/GitHubRepos/AgenticAI_project2/pgdata
DATA_DIR=/home/<you>/Documents/GitHubRepos/AgenticAI_project2/data
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen3-coder:30b
LLM_API_KEY=ollama
```

**Step 4. Start the server, create the database, load the data.**
```bash
./db/start.sh
createdb -h localhost -p 5433 -U registrar registrar
alembic upgrade head            # 12 tables plus the grade_scale rows
python scripts/load_seed.py     # data/seed/*.csv; should report lecture 694
```

**Step 5. Check.**
```bash
./db/psql.sh -c "SELECT count(*) FROM lecture;"    # 694
pytest -q                                          # 192 passed
```

> [!WARNING]
> `-A trust` means no password. On a shared machine, any logged-in user can connect through localhost. The data is
> synthetic, so this is usually acceptable. To require a password instead, run
> `initdb -D "$PGDATA" -U registrar --auth=scram-sha-256 --pwprompt` and put it in `.env`:
> `DATABASE_URL=postgresql+psycopg://registrar:<password>@localhost:5433/registrar`.

---

## 3. Everyday use

```bash
./db/start.sh        # before working
./db/stop.sh         # when done
```

The server keeps running until you stop it or the machine restarts. The agent, the evaluation and the database tests
all need it.

> [!TIP]
> Data loaded once stays in `pgdata/`. `python scripts/load_seed.py` is safe to run again: it empties the tables and
> reloads the same CSVs.

### Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `could not access directory ... Permission denied` | The script points at someone else's `pgdata/` | Section 2; set `PGDATA` in your `.env` |
| `Connection refused` on port 5433 | The server is not running | `./db/start.sh` |
| `pg_ctl: directory ... does not exist` | No cluster yet | Section 2, step 2 |
| `database "registrar" does not exist` | Cluster exists, database not created | `createdb -h localhost -p 5433 -U registrar registrar`, then step 4 |
| Many tests **skipped** in `pytest` | Database not reachable | Start the server; check `DATABASE_URL` in `.env` |

---

## 4. 🟡 Changes in `db/start.sh` and `db/stop.sh`

Both scripts had another user's path hardcoded. They now read `PGDATA` from `.env` and fall back to `./pgdata` in the
repo. `.env.example` already had a `PGDATA` line, so no new setting was needed.

**`db/start.sh`**
```diff
 #!/usr/bin/env bash
-# Start the project-local Postgres cluster (port 5433). Data lives on sheshnagnobackup; socket stays local.
+# Start the project-local Postgres cluster. PGDATA comes from .env (default: ./pgdata).
 set -e
 cd "$(dirname "$0")/.."
-PGDATA=/home/sheshnagnobackup/mnguyen/AgenticAI_project2/pgdata
+[ -f .env ] && export $(grep -E '^PGDATA=' .env)
+PGDATA=${PGDATA:-$PWD/pgdata}
 pg_ctl -D "$PGDATA" -l "$PGDATA/server.log" start
```

**`db/stop.sh`**
```diff
 #!/usr/bin/env bash
+# Stop the project-local Postgres cluster. PGDATA comes from .env (default: ./pgdata).
 set -e
-pg_ctl -D /home/sheshnagnobackup/mnguyen/AgenticAI_project2/pgdata stop -m fast
+cd "$(dirname "$0")/.."
+[ -f .env ] && export $(grep -E '^PGDATA=' .env)
+PGDATA=${PGDATA:-$PWD/pgdata}
+pg_ctl -D "$PGDATA" stop -m fast
```

🔵 `db/psql.sh` is unchanged: it connects to `localhost:5433` and works for every user.

> [!NOTE]
> The port is not in the scripts; it lives in each cluster's `postgresql.conf` (section 2, step 2). If you chose a
> port other than 5433, also change it in `.env` and in `db/psql.sh`.

**`.env.example`**
```diff
 DATABASE_URL=postgresql+psycopg://registrar@localhost:5433/registrar
 PGDATA=/path/to/AgenticAI_project2/pgdata
 DATA_DIR=/path/to/AgenticAI_project2/data
+# Model endpoint for the agents (any OpenAI-compatible server; Ollama by default)
+LLM_BASE_URL=http://127.0.0.1:11434/v1
+LLM_MODEL=qwen3-coder:30b
+LLM_API_KEY=ollama
```

**`.gitignore`**
```diff
+# agent evaluation runs (python scripts/eval_student_agent.py)
+runs/
```

---

## 5. 🟢 Running the Student agent

Start the database (`./db/start.sh`) and Ollama, then:

```bash
python scripts/student_agent.py --student 801930214 --verbose
```

`--student` is the university ID of the logged-in student; the agent never asks for it. 801930214 is Juan Mitchell,
an active Master of Science in Computer Science (MSCS) student, admitted Fall 2025, expected to graduate Spring 2027.
`--verbose` prints every tool call and what it returned.

An example session at the test set's default clock (`--as-of 2026-11-20T18:00:00Z`). The tool lines are real; the
model's wording will vary from run to run:

```text
Student agent for Juan Mitchell (MSCS); clock 2026-11-20 18:00 UTC, current term Fall 2026. Type 'quit' to exit.

You: When am I expected to graduate?
  [tool] get_my_program({}) -> {"answer": {"program": "MSCS", "name": "Master of Science in Computer Science",
         "degree": "MS", "department": "Computer Science", "status": "active", "admit_term": "Fall 2025",
         "expected_graduation_term": "Spring 2027"}}

Agent: You're expected to graduate in Spring 2027 from the Master of Science in Computer Science.

You: How many credits do I need, and which courses are required?
  [tool] get_my_credit_requirements({}) -> {"answer": {"program": "MSCS", "total_credits_required": 30,
         "minimums": {"elective": 21}}, ...}
  [tool] get_my_required_courses({}) -> {"answer": {"program": "MSCS", "required": ["CS 5110", "CS 5990"],
         "required_credits": 9}, ...}

Agent: Your program needs 30 credits, at least 21 of them electives. The required courses are CS 5110 and
CS 5990 (9 credits).

You: Can I register for next semester yet?
  [tool] get_registration_window({"term": "next semester"}) -> {"answer": {"term": "Spring 2027",
         "registration_opens": "2026-11-02", "add_deadline": "2027-01-22", "is_open": true}, ...}

Agent: Yes. Registration for Spring 2027 opened on November 2, 2026 and stays open until the add deadline,
January 22, 2027.

You: What's Raj Martinez's email?
  [tool] decline_request({"reason": "other_student_record", "person": "Raj Martinez"}) -> {"declined": true,
         "message": "Refusal recorded. Tell the user briefly that you cannot share this, ..."}

Agent: Sorry, I can't share another student's information.
```

### Options

| Option | Meaning |
|---|---|
| `--student <id>` | Required. University ID of the logged-in student |
| `--verbose` | Print every tool call and its result |
| `--show-answer` | Print the JSON answer the grader would see after each reply |
| `--as-of <time>` | Set the clock, e.g. `2026-12-20T18:00:00Z` (winter break: "this semester" becomes Spring 2027). Default: now |
| `--model <name>` | Model name, default from `LLM_MODEL` (`qwen3-coder:30b`) |
| `--base-url <url>` | Endpoint, default from `LLM_BASE_URL` (Ollama) |

### Questions to try

| Kind | Example |
|---|---|
| Catalog | What are the prerequisites for CS 5990? · Is CS 4710 offered next spring? · Who teaches CS 2230 this fall? |
| Sections | When does CRN 10011 meet? · What's the capacity of CRN 10001? |
| Degree plan | Is CS 5110 required for my degree? · What's in semester 1 of my plan? |
| Calendar | Which term are we in? · When is the withdrawal deadline this semester? |
| Refused | What's Raj Martinez's email? · List all students in my program. · What's Juan Hall's phone number? |
| Mixed | Who teaches CRN 10011, and what's their phone number? (answers the instructor, refuses the phone) |

---

## 6. 🟢 Evaluating the agent

```bash
python scripts/eval_student_agent.py --limit 20                  # quick run
python scripts/eval_student_agent.py                             # all 152 cases
python scripts/eval_student_agent.py --paraphrases               # all 456 wordings
python scripts/eval_student_agent.py --intent access_denied      # one intent (repeatable)
python scripts/eval_student_agent.py --id stu-capacity-002 --verbose
```

Each case runs in a fresh agent set to the case's student and clock. The JSON answer is graded with the contract in
`data/testset/README.md`: `allowed` first, then every ground-truth field; access-control replies are scanned for
`must_not_mention` values. The script prints PASS or FAIL per run, then scores by intent and category, leaks, runs
that hit the step limit, and failed tool calls. Every run is saved to `runs/<model>-<time>.jsonl` with the question,
reply, answer, expected answer and tool calls.

> [!WARNING]
> **Known test-set issue.** 11 cases ask about a CRN without naming a term (e.g. "When does CRN 10089 meet?") but
> expect Spring 2027 at a Fall 2026 clock. CRNs repeat across terms (694 sections, 118 distinct CRNs), so no agent
> can know which term was meant; the agent answers for the current term. The script marks these runs
> `[unanswerable: term not named]` and prints the score with and without them. Fix in the generator
> (`registrar/testset/student.py`, `student_access.py`): use the CRN templates without `{term}` only when the term is
> the current one.

---

## 7. 🟢 Tests

```bash
pytest -q          # 192 passed; needs the database, not the model
```

| File | What it checks |
|---|---|
| `tests/test_student_tools.py` | Replays all 152 cases with the tool calls a perfect agent would make and grades them. A failure here is a bug in the code, not the model |
| `tests/test_student_rules.py` | Rules the cases never reach: deadline day, cancelled sections, default terms, phrase resolution at each clock, refusal targets, no private fields in any tool |
| `tests/test_student_agent.py` | The loop with a scripted fake model: answer assembly, refusals, bad tool calls, step limit, refusal targets never sent to the model |
| `tests/test_grader.py` | The grader accepts correct answers and rejects wrong ones |

---

## 8. 🟢 How the Student agent works

```text
question ──► StudentAgent ──► ToolLoop ──► model (Ollama)
                                  ▲            │ tool calls
                                  │            ▼
                                  └── results ◄── StudentTools ──► PostgreSQL
                                                     │
                     reply + JSON answer ◄── assemble_answer (from tool results)
```

| File | Role |
|---|---|
| `registrar/agents/loop.py` | The tool-calling loop: model, tools, results, repeat until a plain reply (max 8 steps). Reusable for the professor agent |
| `registrar/agents/calendar.py` | The clock and the current-term rule from README Conventions; resolves "this fall", "next spring", "last semester" in Python |
| `registrar/agents/student/tools.py` | 15 tools. Each returns facts in the test set's answer shape. Only public data and the user's own record are reachable |
| `registrar/agents/student/agent.py` | System prompt (user, clock, permission model) and answer assembly |
| `registrar/agents/common.py` | Shared helpers (`ToolError`, value formatting) |
| `registrar/eval/grader.py` | The verification contract as code |

Two design rules:
- **The model never types the graded answer.** It picks tools and writes the reply; the JSON answer is assembled from
  database rows. Calculations and term arithmetic happen in Python.
- **Permissions are enforced by the tools, not the prompt.** No tool reads another student's record, a list of
  students, or an instructor's phone, birth date, SSN or hire date, so those values cannot reach the model. A refusal's
  target ID is recorded for grading but never shown to the model.
