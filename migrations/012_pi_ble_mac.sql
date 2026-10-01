-- ─── 012: each Pi's own Bluetooth controller MAC, captured from its own scan ────
-- Lets a BLE sighting of another Pi's controller be recognized as a Pi<->Pi proximity
-- reading instead of an ambient bystander device (informational, no GDPR concern —
-- it's our own fleet hardware, not a stranger's phone).

ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS ble_mac VARCHAR(17);
CREATE INDEX IF NOT EXISTS idx_raspberries_ble_mac ON raspberries (ble_mac);
