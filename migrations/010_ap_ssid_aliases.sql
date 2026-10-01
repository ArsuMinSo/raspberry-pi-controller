-- ─── 010: track every SSID name seen for a BSSID, not just the first ──────

ALTER TABLE access_points ADD COLUMN IF NOT EXISTS ssids TEXT[] NOT NULL DEFAULT '{}';

UPDATE access_points SET ssids = ARRAY[ssid] WHERE ssid IS NOT NULL AND ssids = '{}';
