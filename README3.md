# README3: Multi-agent coordinator and RAG

This file adds to [README.md](README.md) (data layer) and [README2.md](README2.md) (database setup, Student agent).
Do the database setup in README2 first. This file covers what was added on top: the **multi-agent coordinator** and
**RAG** (retrieval over the handbook and the course catalog).

## 1. What this adds

A question goes through four steps:

```
question
  -> Coordinator   (registrar/agents/multi/coordinator.py)
       a plain "yes"/"no" to a pending change is handled in code, with no model call
       otherwise the Planner (planner.py) splits the message into at most 3 tasks, each assigned to one specialist
  -> Specialists   (registrar/agents/multi/agents.py), each its own model loop with its own tools
       data          records: GPA, transcript, schedule, sections, statistics
       policy        handbook rules and courses by topic             <- uses RAG
       advising      degree plan, advisees (clingo planner in advising_agent/)
       registration  add / drop a course, post a grade (prepares the change; the user confirms next turn)
  -> Composer      (compose.py) builds one reply from the specialists' verified results
```

Which specialists a person gets depends on their role: students and instructors get all four, administrators get
data and policy. If planning fails, the Coordinator falls back to the single-agent `Router`.

Design rules that the code enforces:

- **Facts come from tools, never from the model.** An answer with no successful tool call is replaced with a fixed
  sentence, and a reply claiming "you are registered" when no write happened is replaced with "I haven't changed anything."
- **Changes need confirmation.** A registration, drop, or grade posting is prepared first; the user's next "yes" is
  confirmed by the system, not by the model.
- **Authorization lives in the tools.** The logged-in user's ID is fixed in the tool code; the model cannot pick whose
  record to read.
- GPA, degree plans and policy references are formatted in code, not written by the model.

## 2. RAG

`registrar/rag/` retrieves wording and citations. Numbers (grades, seats, limits) stay in SQL and `data/policy/params.json`.

| Source | What is indexed | Used for |
|---|---|---|
| handbook | one chunk per section of `data/policy/handbook.md` | rule questions, cited as "Handbook 3.2" |
| catalog | one chunk per active course (title, description, credits, prerequisites) | "which course covers databases?" |
| kb | optional: `data/kb/*.md`, split at `##` headings | extra FAQs or restricted documents (see below) |

Retrieval is **hybrid**: keyword scoring (BM25 with synonyms) plus embedding similarity, merged by reciprocal rank
fusion. Without an embedding model it still works on keywords alone. Each chunk has an `audience`
(`all`, `student`, `instructor`, `admin`) and is filtered before ranking, so a restricted document cannot be returned to
the wrong role. To add a restricted document, create `data/kb/<name>.md` whose first line is `<!-- audience: admin -->`.

## 3. Setup

```bash
pip install sqlalchemy "psycopg[binary]" alembic python-dotenv openai pytest clingo
```

Models run through Ollama. Any OpenAI-compatible server works.

```bash
ollama pull llama3.1:8b          # chat model (smaller than the default; fits a laptop)
ollama pull nomic-embed-text     # embeddings (optional; RAG falls back to keywords without it)
```

Settings are environment variables (PowerShell syntax shown; use `export` on macOS/Linux):

| Variable | Purpose | Default |
|---|---|---|
| `LLM_MODEL` | chat model | `qwen3-coder:30b` (set to `llama3.1:8b` on a laptop) |
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `http://127.0.0.1:11434/v1` |
| `LLM_BACKEND` | `ollama-native` to turn thinking off | OpenAI-compatible |
| `EMBED_MODEL` | embedding model; unset means keyword-only RAG | unset |
| `EMBED_QUERY_PREFIX`, `EMBED_DOC_PREFIX` | task prefixes some models expect | empty |
| `EMBED_MIN_COSINE` | similarity cutoff so off-topic questions return nothing | `0` (we use `0.58`) |
| `EMBED_DENSE_ONLY_MIN` | stricter cutoff for matches with no keyword overlap | `0` |

```powershell
$env:LLM_MODEL = "llama3.1:8b"
$env:EMBED_MODEL = "nomic-embed-text"
$env:EMBED_QUERY_PREFIX = "search_query: "
$env:EMBED_DOC_PREFIX = "search_document: "
$env:EMBED_MIN_COSINE = "0.58"
```

The first search builds an embedding cache in `.rag_cache/` (ignored by git). It rebuilds automatically if the corpus changes.

## 4. Run

```bash
# student (multi-agent); --verbose shows each tool call, --show-answer shows the plan and per-agent trace
python scripts/registrar_chat.py --user 801930214 --multi --verbose --show-answer
# instructor and administrator
python scripts/registrar_chat.py --user 801408626 --multi
python scripts/registrar_chat.py --user 900000001 --multi
# one question, then exit
python scripts/registrar_chat.py --user 801930214 --multi --question "What is my GPA?"
```

Without `--multi` the single-agent Router answers instead. Questions to try as the student: "What is my GPA?", "What are
the probation rules?", "Which courses cover databases?", "What is my GPA and what should I take next semester?",
"Register me for <a course you have not taken> for next semester" followed by "yes".

Registration writes to the real database. Undo a test with "Drop <course>" and then "yes", or reload with
`scripts/load_seed.py` (which empties and reloads the tables).

## 5. Tests

```bash
pytest -q                                        # everything; database tests are skipped without a database
pytest tests/test_multiagent.py tests/test_rag.py -q   # these two need no database or model
```

`tests/test_multiagent.py` uses scripted model responses, so it checks routing, the false-claim guard,
confirmation handling and refusals deterministically.

RAG quality check (needs the embedding model for the hybrid column):

```bash
python scripts/eval_rag.py                       # keyword-only vs hybrid on data/testset/rag
python scripts/eval_rag.py --calibrate           # suggests EMBED_MIN_COSINE
python scripts/eval_rag.py --query "databases"   # raw scores for one query
```

## 6. Where things are

| Path | Role |
|---|---|
| `registrar/agents/multi/` | Coordinator, Planner, specialists, Composer |
| `registrar/rag/` | corpus, hybrid retriever, `search_catalog` tool |
| `registrar/agents/router.py` | builds the persona agent and tools per role (student, instructor, admin) |
| `registrar/agents/advising.py` + `advising_agent/` | database connection and the clingo planner behind the advising specialist |
| `registrar/agents/policy.py` | handbook search (uses RAG when an embedding model is set) |
| `tests/test_multiagent.py`, `tests/test_rag.py`, `data/testset/rag/` | tests and RAG eval cases |

## 7. Known limits

- Tested live with `llama3.1:8b` as a student only. The professor and administrator roles are covered by unit tests, not
  live runs, and have no role-specific documents in the RAG corpus yet.
- A small model's final wording can still be imperfect; the code limits this by building facts and key sentences itself,
  but an off-topic catalog match can occasionally slip through. `EMBED_DENSE_ONLY_MIN` tightens this.
- A course-statistics tool for professors (grade distribution for their own sections) is not implemented.
- This is not yet integrated with `main`'s database schema or GUI. The agents use the schema in this branch.
