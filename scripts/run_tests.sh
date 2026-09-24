#!/bin/bash
# Run the test suite against a throwaway PostgreSQL database.
# Safe on the production server too (separate test role + DB). From anywhere:
#   bash scripts/run_tests.sh            # all tests
#   bash scripts/run_tests.sh -k mac     # extra args go to pytest
#
# First run creates role pi_test / database pi_controller_test (needs sudo for
# the postgres user) and a .venv with dev dependencies.
# The tests DROP and recreate tables in the test database — never point this at
# the real pi_controller database.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEST_DB="pi_controller_test"
TEST_USER="pi_test"
TEST_PASSWORD="test"  # local throwaway DB only
VENV="$REPO_DIR/.venv"

export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql://$TEST_USER:$TEST_PASSWORD@localhost/$TEST_DB}"

# Refuse anything that isn't the dedicated test database
if [[ "${TEST_DATABASE_URL%%\?*}" != */"$TEST_DB" ]]; then
    echo "Refusing to run: TEST_DATABASE_URL must point at database '$TEST_DB' (tests drop tables)."
    exit 1
fi

# The app's startup (scheduler) connects to the database in config.yaml — make
# sure it can't log in to the real one with a real password during tests.
unset DB_PASSWORD

# ── Test database ─────────────────────────────────────────────────────────────
if [ -z "${SKIP_DB_SETUP:-}" ]; then
    echo "Ensuring test database $TEST_DB …"
    sudo -u postgres psql -q -v ON_ERROR_STOP=1 \
        -v user="$TEST_USER" -v pw="$TEST_PASSWORD" -v db="$TEST_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'user', :'pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'user')
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db')
\gexec
SQL
fi

# ── Virtualenv ────────────────────────────────────────────────────────────────
if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating $VENV …"
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt" -r "$REPO_DIR/requirements-dev.txt"

# ── Run ───────────────────────────────────────────────────────────────────────
cd "$REPO_DIR"
exec "$VENV/bin/python" -m pytest tests/ "$@"
