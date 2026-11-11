#!/usr/bin/env bash
# Stop the project-local Postgres cluster. PGDATA comes from .env (default: ./pgdata), as in start.sh.
set -e
cd "$(dirname "$0")/.."
[ -f .env ] && export $(grep -E '^PGDATA=' .env)
PGDATA=${PGDATA:-$PWD/pgdata}
pg_ctl -D "$PGDATA" stop -m fast
