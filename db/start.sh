#!/usr/bin/env bash
# Start the project-local Postgres cluster (port 5433). Data lives on sheshnagnobackup; socket stays local.
set -e
cd "$(dirname "$0")/.."
PGDATA=/home/sheshnagnobackup/mnguyen/AgenticAI_project2/pgdata
pg_ctl -D "$PGDATA" -l "$PGDATA/server.log" start
