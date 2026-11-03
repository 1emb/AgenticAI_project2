#!/usr/bin/env bash
# Start the project-local Postgres cluster (port 5433). Data lives on sheshnagnobackup; socket stays local.
set -e
cd "$(dirname "$0")/.."
PGDATA=/home/sheshnagnobackup/mnguyen/AgenticAI_project2/pgdata
# Start the project-local Postgres cluster. PGDATA comes from .env (default: ./pgdata). This works for all user, since each person’s .env points at their own folder.
[ -f .env ] && export $(grep -E '^PGDATA=' .env)
PGDATA=${PGDATA:-$PWD/pgdata}
pg_ctl -D "$PGDATA" -l "$PGDATA/server.log" start
