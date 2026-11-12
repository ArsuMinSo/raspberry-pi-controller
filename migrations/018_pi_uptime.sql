-- ─── 018: persist last known Pi uptime (seconds) on the inventory row ───

ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS uptime_s INTEGER;
