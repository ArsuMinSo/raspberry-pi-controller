-- ─── 006: health samples time-series table ─────────────────────────────
-- Stores per-Pi health metrics (CPU, memory, temp) with timestamp for history/dashboards.

CREATE TABLE IF NOT EXISTS health_samples (
    id              SERIAL PRIMARY KEY,
    mac             VARCHAR(17)  NOT NULL REFERENCES raspberries (mac) ON DELETE CASCADE,
    timestamp       TIMESTAMP    NOT NULL DEFAULT NOW(),
    cpu_1m          DOUBLE PRECISION,
    cpu_5m          DOUBLE PRECISION,
    cpu_15m         DOUBLE PRECISION,
    mem_percent     DOUBLE PRECISION,
    temp_c          DOUBLE PRECISION,
    uptime_s        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_health_samples_mac_ts
    ON health_samples (mac, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_health_samples_ts
    ON health_samples (timestamp DESC);
