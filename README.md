# Registrar replacement: data layer

Agentic system that takes over the functions of a university registrar office. This repository currently holds
the domain definition, the PostgreSQL schema, and a synthetic NMSU-sized dataset.

## Layout
```
registrar/models/   SQLAlchemy 2.0 models (53 tables)       docs/domain.md   what the registrar does, data, users
registrar/seed/     synthetic data generator + COPY loader   docs/schema.md   table-by-table reference
registrar/db.py     engine / session (reads .env)            scripts/         init_db.py, seed.py, load_csv.py, make_testset.py
registrar/testset/  question -> SQL -> facts test generators data/testset/    English test cases (see its README)
db/                 start.sh / stop.sh / psql.sh             alembic/         migrations
pgdata/             Postgres 18 cluster (port 5433)          data/seed_csv/   CSV copy of the seeded dataset
                                                             data/sample/     5% CSV sample (committed)
```
Everything lives on `/home/sheshnagnobackup/mnguyen/AgenticAI_project2`; `~/AgenticAI_project2` is a symlink.

Not in git: `pgdata/` (~1.4 GB), the full-size `data/seed_csv/` (~150 MB), and `.env` (copy `.env.example`).
The committed `data/sample/seed_csv/` has the same 52 tables and columns at 5% scale (1,036 students, 143,813 rows,
8.8 MB), produced by `DATA_DIR=data/sample python scripts/seed.py --scale 0.05 --seed 42 --dump --no-load`.
The full dataset is deterministic: `python scripts/seed.py --dump` regenerates it.
`scripts/load_csv.py <dir>` loads any CSV dump into the database named by `DATABASE_URL`; the sample is loaded into a
second database, `registrar_sample`, on the same cluster, and the test sets in `data/testset/` are generated from it.

## Setup
```bash
conda activate /home/sheshnagnobackup/mnguyen/envs/registrar
./db/start.sh                     # starts Postgres on localhost:5433 (TCP only, no unix socket)
./db/psql.sh                      # psql into the registrar database
python scripts/init_db.py --drop  # recreate tables from the models
python scripts/seed.py            # ~13k active undergrads, Fall 2021 - Spring 2027, ~2.4M rows, ~70 s
python scripts/seed.py --scale 0.03   # quick small dataset for tests
```
Connection string: `postgresql+psycopg://registrar@localhost:5433/registrar` (in `.env` as `DATABASE_URL`).

## Dataset
Modeled on NMSU Las Cruces (13,039 undergraduates in fall 2025). Real college structure; synthetic departments,
courses, people, and records. Terms Fall 2021 through Spring 2027, Fall 2026 in progress (grades not yet posted),
Spring 2027 scheduled with registration appointments starting 2026-11-02. Simulation details and calibration
targets are in `registrar/seed/generate.py`.

Known simplifications: no time-conflict checking between a student's sections, no readmission after suspension,
no graduate students, `degree_audit` is empty (the system computes audits), `audit_log` has one seed row.
