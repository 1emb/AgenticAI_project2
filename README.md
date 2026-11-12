# Registrar system (multi-agent, with RAG)

This file has two parts: how to run the system, and how the system uses retrieval-augmented generation (RAG).

## Part 1: How to run

Run every command from the repository folder, in order.

### 1. Install first

- Git
- Python 3.12
- PostgreSQL, with `initdb`, `pg_ctl`, `createdb` and `psql` on your `PATH`
- [Ollama](https://ollama.com), and a GPU with about 20 GB of memory for the model used below

### 2. Get the code

```bash
git clone https://github.com/1emb/AgenticAI_project2.git
cd AgenticAI_project2
git checkout merge-all-three
```

### 3. Install the Python packages

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install sqlalchemy "psycopg[binary]" alembic python-dotenv openai pytest clingo
```

In every new terminal, run `source .venv/bin/activate` again before the commands below.

### 4. Write the settings file

```bash
cat > .env <<EOF
DATABASE_URL=postgresql+psycopg://registrar@localhost:5433/registrar
PGDATA=$PWD/pgdata
DATA_DIR=$PWD/data
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen3-coder:30b
LLM_API_KEY=ollama
EOF
```

### 5. Create the database and load the data

```bash
initdb -D pgdata -U registrar -A trust
echo "port = 5433"                    >> pgdata/postgresql.conf
echo "listen_addresses = 'localhost'" >> pgdata/postgresql.conf
echo "unix_socket_directories = ''"   >> pgdata/postgresql.conf
./db/start.sh
createdb -h localhost -p 5433 -U registrar registrar
alembic upgrade head
python scripts/load_seed.py
```

The last command ends with `advisor_assignment 1200`.

### 6. Start the model

In a second terminal, and leave it running:

```bash
OLLAMA_CONTEXT_LENGTH=32768 ollama serve
```

Back in the first terminal:

```bash
ollama pull qwen3-coder:30b
```

### 7. Chat

```bash
python scripts/registrar_chat.py --multi --user 801930214                    # a student
python scripts/registrar_chat.py --multi --user 801408626                    # a professor
python scripts/registrar_chat.py --multi --user 900000001                    # the registrar administrator
python scripts/registrar_chat.py --multi --user 800020284 --role student     # a teaching assistant: pick student or instructor
```

Type a question and press Enter. Type `quit` to leave.

- Add `--as-of 2026-11-20T18:00:00Z` to set the date the system believes it is. Without it, today's date is used.
- Add `--show-answer` to also print the structured answer, the plan and the agents that ran.
- Add `--question "What is my GPA?"` to ask one question and exit.
- A registration, a drop or a grade is made only when your next message is exactly `yes`. `no` cancels it.

### 8. Run the evaluation

```bash
python scripts/load_seed.py                                           # start from the original data
python scripts/eval_agents.py --multi --persona all --per-intent 1    # short run: one question of each type
python scripts/eval_agents.py --multi --persona all                   # full run: all 445 questions
```

Each question prints `PASS` or `FAIL`. The scores are printed at the end, and every run is saved in `runs/`.

### 9. Stop

```bash
./db/stop.sh
```

Stop the model with Ctrl+C in the second terminal.

To start again later: `source .venv/bin/activate`, `./db/start.sh`, and step 6.
To put the original data back at any time: `python scripts/load_seed.py`.

## Part 2: How RAG is used in the system

### Where RAG sits

A question goes through four steps. RAG is in the third one, inside the policy specialist.

```
question
  -> Coordinator    a "yes" or "no" to a waiting change is handled in code
  -> Planner        splits the message into at most 3 tasks, one specialist per task
  -> Specialists    data          records, from SQL
                    policy        handbook rules and courses by topic     <- RAG
                    advising      degree plan
                    registration  add or drop a course, post a grade
  -> Composer       builds one reply from the specialists' results
```

The planner sends two kinds of question to the policy specialist:

- a question about a rule, such as "What are the probation rules?"
- a question that looks for a course by subject, such as "Which courses cover databases?"

The policy specialist has two tools, and both are retrieval tools. It cannot read the database. Students, professors
and administrators all have this specialist. The advising and registration specialists can also ask it for a rule.

### What is retrieved

Only text is retrieved. Grades, seats, dates and limits are never retrieved: they come from SQL and from
`data/policy/params.json`.

| Source | One chunk is | Chunks | Tool |
|---|---|---|---|
| Handbook, `data/policy/handbook.md` | one numbered section, such as "4.1 Academic standing for undergraduates" | 21 | `search_policy` |
| Course catalog, the `course` and `course_prerequisite` tables | one active course: code, title, description, credit hours, level, prerequisites | 70 | `search_catalog` |
| Optional notes, `data/kb/*.md` | one `##` heading | 0 (the folder is not used yet) | none yet |

A retired course is left out of the catalog chunks, so it is never suggested.

### The three steps of RAG

**1. Retrieve.** The model calls a tool with the user's words. The tool ranks the chunks and returns the best ones.

- `search_policy(question)` returns up to 3 handbook sections.
- `search_catalog(topic)` returns up to 5 courses.

The ranking is BM25, a keyword score. The title of a chunk counts three times. A short synonym list widens the
query, for example "db" also searches "database" and "probation" also searches "standing". A chunk that scores
below one fifth of the best chunk is dropped, so a question that shares no real word with the corpus returns nothing.

**2. Augment.** The tool result goes back to the model as the passages themselves, plus an instruction. For the
handbook the instruction is "Answer only from these passages and cite the section number". For the catalog it is to
list a course only if its text is about the topic.

**3. Generate.** The model writes the answer from the passages. The code then checks it:

- If no tool call returned a passage, the model's answer is thrown away and the user gets the fixed sentence
  "The handbook and the course catalog don't cover that."
- For a rule, the section numbers are added by code as a last line, "Policy references: 4.1, 4.2, 3.2". They are
  the sections that were retrieved, not numbers the model wrote.

### Three real runs

Run as student 801930214 with `qwen3-coder:30b`, with `--verbose` to show the tool call.

A rule:

```
You:   What are the probation rules?
tool:  search_policy("probation") -> sections 4.1, 4.2, 3.2, with their text
Agent: Undergraduate Probation: An undergraduate student is placed on academic probation if their GPA for the
       most recent graded term falls below the minimum program GPA of 2.00. ...
       Policy references: 4.1, 4.2, 3.2
```

A course by subject:

```
You:   Which courses cover databases?
tool:  search_catalog("databases") -> CS 5410, CS 3410, with their text
Agent: CS 5410 Advanced Database Systems. Query optimization, distributed and NoSQL databases, ...
       CS 3410 Database Systems. Relational model, SQL, normalization, transactions, ...
```

A subject that is not in the catalog:

```
You:   Is there a course on underwater basket weaving?
tool:  search_catalog("underwater basket weaving") -> no matches
Agent: The handbook and the course catalog don't cover that.
```

### Where the code is

| Path | What it does |
|---|---|
| `registrar/rag/corpus.py` | builds the chunks from the handbook, the catalog and `data/kb/` |
| `registrar/rag/retriever.py` | BM25, embeddings, rank fusion, the embedding cache |
| `registrar/rag/tools.py` | the `search_catalog` tool |
| `registrar/agents/policy.py` | handbook sections and the `search_policy` tool |
| `registrar/agents/multi/agents.py` | the policy specialist and the check that an answer has a retrieved source |
| `registrar/agents/multi/compose.py` | adds the "Policy references" line |
| `scripts/eval_rag.py`, `tests/test_rag.py` | retrieval evaluation and tests |
