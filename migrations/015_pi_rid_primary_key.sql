-- ─── 015: raspberries.rid (plain auto-increment) replaces mac as the primary key ──────────
-- MAC/IP are a poor fit for identity: a Pi can have more than one interface (wlan0 vs eth0
-- reporting different MACs depending on which one answers a probe), a MAC can change (NIC
-- swap), and an IP changes by design (DHCP). None of that should ever mean "this is now a
-- different Pi" or break foreign keys pointing at it. `rid` is a meaningless, stable surrogate
-- key assigned once at insert and never touched again; `mac`/`position` remain required+unique
-- business keys for lookups, just no longer what other tables hang their FKs off.

ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS rid BIGSERIAL;

-- The mac-keyed FKs below depend on raspberries_pkey; drop them before the PK goes.
ALTER TABLE wifi_scans DROP CONSTRAINT IF EXISTS wifi_scans_mac_fkey;
ALTER TABLE ble_scans DROP CONSTRAINT IF EXISTS ble_scans_mac_fkey;
ALTER TABLE health_samples DROP CONSTRAINT IF EXISTS health_samples_mac_fkey;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'raspberries_pkey') THEN
        ALTER TABLE raspberries DROP CONSTRAINT raspberries_pkey;
    END IF;
END $$;

ALTER TABLE raspberries ADD PRIMARY KEY (rid);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'raspberries_mac_key') THEN
        ALTER TABLE raspberries ADD CONSTRAINT raspberries_mac_key UNIQUE (mac);
    END IF;
END $$;

-- wifi_scans / ble_scans / health_samples: swap their Pi reference from mac (string) to
-- pi_rid (the new surrogate key) — backfill from the existing mac column, then drop it.

ALTER TABLE wifi_scans ADD COLUMN IF NOT EXISTS pi_rid BIGINT;
UPDATE wifi_scans SET pi_rid = raspberries.rid
    FROM raspberries WHERE wifi_scans.mac = raspberries.mac AND wifi_scans.pi_rid IS NULL;
ALTER TABLE wifi_scans ALTER COLUMN pi_rid SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'wifi_scans_pi_rid_fkey') THEN
        ALTER TABLE wifi_scans ADD CONSTRAINT wifi_scans_pi_rid_fkey
            FOREIGN KEY (pi_rid) REFERENCES raspberries (rid) ON DELETE CASCADE;
    END IF;
END $$;
ALTER TABLE wifi_scans DROP COLUMN IF EXISTS mac;

ALTER TABLE ble_scans ADD COLUMN IF NOT EXISTS pi_rid BIGINT;
UPDATE ble_scans SET pi_rid = raspberries.rid
    FROM raspberries WHERE ble_scans.mac = raspberries.mac AND ble_scans.pi_rid IS NULL;
ALTER TABLE ble_scans ALTER COLUMN pi_rid SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ble_scans_pi_rid_fkey') THEN
        ALTER TABLE ble_scans ADD CONSTRAINT ble_scans_pi_rid_fkey
            FOREIGN KEY (pi_rid) REFERENCES raspberries (rid) ON DELETE CASCADE;
    END IF;
END $$;
ALTER TABLE ble_scans DROP COLUMN IF EXISTS mac;

ALTER TABLE health_samples ADD COLUMN IF NOT EXISTS pi_rid BIGINT;
UPDATE health_samples SET pi_rid = raspberries.rid
    FROM raspberries WHERE health_samples.mac = raspberries.mac AND health_samples.pi_rid IS NULL;
ALTER TABLE health_samples ALTER COLUMN pi_rid SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'health_samples_pi_rid_fkey') THEN
        ALTER TABLE health_samples ADD CONSTRAINT health_samples_pi_rid_fkey
            FOREIGN KEY (pi_rid) REFERENCES raspberries (rid) ON DELETE CASCADE;
    END IF;
END $$;
ALTER TABLE health_samples DROP COLUMN IF EXISTS mac;

-- Old mac-keyed indexes died with their columns; replace with rid-keyed equivalents.
CREATE INDEX IF NOT EXISTS idx_wifi_scans_pi_rid_ts ON wifi_scans (pi_rid, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ble_scans_pi_rid_ts ON ble_scans (pi_rid, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_health_samples_pi_rid_ts ON health_samples (pi_rid, timestamp DESC);
