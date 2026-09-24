#!/bin/bash
# Create the pi_controller role + database, then apply pending migrations.
# Safe to re-run. Each migration runs in its own transaction together with its
# schema_migrations record — a failing migration leaves the DB unchanged.
set -euo pipefail

if [ -z "${DB_PASSWORD:-}" ]; then
    echo "DB_PASSWORD env var required"
    exit 1
fi

MIGRATIONS_DIR="$(cd "$(dirname "$0")/../migrations" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/pi-controller}"

# Role password is (re)set from DB_PASSWORD every run so it always matches .env.
# Passed as a psql variable and quoted with %L — safe for any characters.
sudo -u postgres psql -q -v ON_ERROR_STOP=1 -v pw="$DB_PASSWORD" <<'SQL'
SELECT format('CREATE USER pi_controller WITH PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pi_controller')
\gexec

SELECT format('ALTER USER pi_controller WITH PASSWORD %L', :'pw')
\gexec

SELECT 'CREATE DATABASE pi_controller OWNER pi_controller'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'pi_controller')
\gexec

GRANT ALL ON DATABASE pi_controller TO pi_controller;
SQL

# TCP + password, same as the backend. The local socket uses peer auth, which
# rejects -U pi_controller when this runs as root.
export PGPASSWORD="$DB_PASSWORD"
db() { psql -q -v ON_ERROR_STOP=1 -h localhost -U pi_controller -d pi_controller "$@"; }

db -c "CREATE TABLE IF NOT EXISTS schema_migrations (
           filename   VARCHAR(255) PRIMARY KEY,
           applied_at TIMESTAMP    NOT NULL DEFAULT NOW()
       )"

applied="$(db -tAc "SELECT filename FROM schema_migrations")"
pending=()
for migration in "$MIGRATIONS_DIR"/*.sql; do
    name="$(basename "$migration")"
    grep -qxF "$name" <<<"$applied" || pending+=("$migration")
done

if [ ${#pending[@]} -eq 0 ]; then
    echo "Database up to date — no pending migrations."
    exit 0
fi

# Back up before touching an existing schema (skipped on a fresh, empty DB)
has_data="$(db -tAc "SELECT to_regclass('public.raspberries') IS NOT NULL")"
if [ "$has_data" = "t" ]; then
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    dump="$BACKUP_DIR/pi_controller-$(date +%Y%m%d-%H%M%S).dump"
    echo "Backing up database to $dump …"
    sudo -u postgres pg_dump -Fc pi_controller > "$dump"
    chmod 600 "$dump"
fi

for migration in "${pending[@]}"; do
    name="$(basename "$migration")"
    echo "Applying $name"
    db --single-transaction -v fn="$name" -f "$migration" -f - <<'SQL'
INSERT INTO schema_migrations (filename) VALUES (:'fn');
SQL
done
echo "Database setup complete."
