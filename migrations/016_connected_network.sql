-- ─── 016: connected network tracking (WiFi SSID/BSSID the Pi is actually connected to) ───

ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS connected_bssid VARCHAR(17);
ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS connected_ssid VARCHAR(255);
ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS connected_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_raspberries_connected_bssid ON raspberries (connected_bssid);
