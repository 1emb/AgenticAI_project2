# How to run the registrar system (multi-agent version)

Run every command from the repository folder, in order.

## 1. Install first

- Git
- Python 3.12
- PostgreSQL, with `initdb`, `pg_ctl`, `createdb` and `psql` on your `PATH`
- [Ollama](https://ollama.com), and a GPU with about 20 GB of memory for the model used below

## 2. Get the code

```bash
git clone https://github.com/1emb/AgenticAI_project2.git
cd AgenticAI_project2
git checkout merge-all-three
```

## 3. Install the Python packages

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install sqlalchemy "psycopg[binary]" alembic python-dotenv openai pytest clingo
```

In every new terminal, run `source .venv/bin/activate` again before the commands below.

## 4. Write the settings file

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

## 5. Create the database and load the data

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

## 6. Start the model

In a second terminal, and leave it running:

```bash
OLLAMA_CONTEXT_LENGTH=32768 ollama serve
```

Back in the first terminal:

```bash
ollama pull qwen3-coder:30b
```

## 7. Chat

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

## 8. Run the evaluation

```bash
python scripts/load_seed.py                                           # start from the original data
python scripts/eval_agents.py --multi --persona all --per-intent 1    # short run: one question of each type
python scripts/eval_agents.py --multi --persona all                   # full run: all 445 questions
```

Each question prints `PASS` or `FAIL`. The scores are printed at the end, and every run is saved in `runs/`.

## 9. Stop

```bash
./db/stop.sh
```

Stop the model with Ctrl+C in the second terminal.

To start again later: `source .venv/bin/activate`, `./db/start.sh`, and step 6.
To put the original data back at any time: `python scripts/load_seed.py`.
