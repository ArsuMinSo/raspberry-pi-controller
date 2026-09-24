#!/bin/bash
set -e

if [ -z "$DB_PASSWORD" ]; then
    echo "DB_PASSWORD env var required"
    exit 1
fi

sudo -u postgres psql <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pi_controller') THEN
        CREATE USER pi_controller WITH PASSWORD '${DB_PASSWORD}';
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE pi_controller OWNER pi_controller'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'pi_controller')
\gexec

GRANT ALL ON DATABASE pi_controller TO pi_controller;
SQL

for migration in "$(dirname "$0")"/../migrations/*.sql; do
    echo "Applying $(basename "$migration")"
    psql -v ON_ERROR_STOP=1 -U pi_controller -d pi_controller -f "$migration"
done
echo "Database setup complete."
