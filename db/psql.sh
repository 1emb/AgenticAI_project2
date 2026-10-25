#!/usr/bin/env bash
# Open psql against the registrar database.
exec psql -h localhost -p 5433 -U registrar -d registrar "$@"
