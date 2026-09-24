#!/bin/bash
set -e

if [ -z "$DB_PASSWORD" ]; then
    echo "DB_PASSWORD env var required"
    exit 1
fi

# Role password is (re)set from DB_PASSWORD every run so it always matches .env.
# Passed as a psql variable and quoted with %L — safe for any characters.
sudo -u postgres psql -v ON_ERROR_STOP=1 -v pw="$DB_PASSWORD" <<'SQL'
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
for migration in "$(dirname "$0")"/../migrations/*.sql; do
    echo "Applying $(basename "$migration")"
    psql -v ON_ERROR_STOP=1 -h localhost -U pi_controller -d pi_controller -f "$migration"
done
echo "Database setup complete."
