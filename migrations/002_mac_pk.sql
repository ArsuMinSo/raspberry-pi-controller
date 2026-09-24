-- ─── 002: MAC as primary key, numeric positions, health stats, scheduled tasks ─
-- Brings the schema in line with backend/models.py. Safe to re-run.
-- Aborts (no changes) if placeholder or duplicate MACs exist — fix those rows first.

DO $$
DECLARE
    n_placeholder INT;
    dup_macs      TEXT;
BEGIN
    SELECT count(*) INTO n_placeholder
      FROM raspberries WHERE lower(mac) = '00:00:00:00:00:00';
    IF n_placeholder > 0 THEN
        RAISE EXCEPTION 'migration 002: % Pi(s) have placeholder MAC 00:00:00:00:00:00 — set real MACs or delete them first', n_placeholder;
    END IF;

    SELECT string_agg(m, ', ') INTO dup_macs
      FROM (SELECT lower(mac) AS m FROM raspberries GROUP BY 1 HAVING count(*) > 1) d;
    IF dup_macs IS NOT NULL THEN
        RAISE EXCEPTION 'migration 002: duplicate MACs must be resolved first: %', dup_macs;
    END IF;
END
$$;

UPDATE raspberries SET mac = lower(mac) WHERE mac <> lower(mac);

ALTER TABLE raspberries ALTER COLUMN position TYPE VARCHAR(20);

ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS cpu_1m      DOUBLE PRECISION;
ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS cpu_5m      DOUBLE PRECISION;
ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS cpu_15m     DOUBLE PRECISION;
ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS mem_percent DOUBLE PRECISION;
ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS temp_c      DOUBLE PRECISION;

-- Swap primary key id → mac
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'raspberries' AND column_name = 'id') THEN
        ALTER TABLE raspberries DROP COLUMN id;  -- drops raspberries_pkey with it
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'raspberries'::regclass AND contype = 'p') THEN
        ALTER TABLE raspberries ADD PRIMARY KEY (mac);
    END IF;
END
$$;

-- ─── scheduled_tasks ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    cron            VARCHAR(100) NOT NULL,
    task_type       VARCHAR(20)  NOT NULL,
    command         TEXT,
    pis             TEXT[]       NOT NULL DEFAULT '{}',
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    last_run        TIMESTAMP,
    last_status     VARCHAR(20),
    last_action_id  INT,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
