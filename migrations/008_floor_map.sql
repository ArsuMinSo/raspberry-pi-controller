-- ─── 008: floor map (AP anchors + wifi/ble scans) ──────────────────────────
-- access_points: fixed real-world anchor points, placed manually (drag+save
--   x/y from the UI). Auto-registered (x/y NULL) the first time any Pi sees
--   the BSSID in a wifi scan.
-- wifi_scans / ble_scans: time-series scan readings per Pi, same pattern as
--   health_samples (006) — latest-per-window read, no update-in-place.

CREATE TABLE IF NOT EXISTS access_points (
    bssid              VARCHAR(17) PRIMARY KEY,     -- xx:xx:xx:xx:xx:xx, lowercase
    ssid               VARCHAR(255),
    x                  DOUBLE PRECISION,             -- NULL until placed on map
    y                  DOUBLE PRECISION,
    placed_by_user_id  INTEGER REFERENCES users (id),
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wifi_scans (
    id          SERIAL PRIMARY KEY,
    mac         VARCHAR(17)  NOT NULL REFERENCES raspberries (mac) ON DELETE CASCADE,
    bssid       VARCHAR(17)  NOT NULL,   -- not FK'd — AP may be seen before it's registered
    rssi        SMALLINT     NOT NULL,   -- dBm, e.g. -63
    timestamp   TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ble_scans (
    id           SERIAL PRIMARY KEY,
    mac          VARCHAR(17)  NOT NULL REFERENCES raspberries (mac) ON DELETE CASCADE,
    device_mac   VARCHAR(17)  NOT NULL,
    device_name  VARCHAR(255),
    rssi         SMALLINT,               -- nullable: RSSI arrives async, not every device gets one per scan window
    timestamp    TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wifi_scans_mac_ts ON wifi_scans (mac, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_wifi_scans_bssid  ON wifi_scans (bssid);
CREATE INDEX IF NOT EXISTS idx_ble_scans_mac_ts  ON ble_scans (mac, timestamp DESC);
