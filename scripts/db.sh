#!/usr/bin/env bash
# Start the embedded Postgres (./.pgdata/pg) and make sure the dev and test databases exist.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
uv run --no-project --python 3.12 --with pgserver python -c "
import pgserver; s = pgserver.get_server('.pgdata/pg', cleanup_mode=None)
for db in ('automind', 'automind_test'):
    if db not in s.psql('select datname from pg_database'):
        s.psql(f'create database {db}')
print('Postgres ready:', s.get_uri())"
