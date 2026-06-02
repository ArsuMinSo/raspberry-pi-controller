-- ─── raspberries ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raspberries (
    id          SERIAL PRIMARY KEY,
    mac         VARCHAR(17)  NOT NULL,
    serial      VARCHAR(255),
    hostname    VARCHAR(255),
    position    VARCHAR(6)   NOT NULL UNIQUE,
    pi_version  SMALLINT,
    current_ip  INET,
    status      VARCHAR(20)  NOT NULL DEFAULT 'unreachable'
                    CHECK (status IN ('reachable', 'unreachable')),
    last_seen   TIMESTAMP,
    tags        TEXT[]       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raspberries_status   ON raspberries (status);
CREATE INDEX IF NOT EXISTS idx_raspberries_tags     ON raspberries USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_raspberries_position ON raspberries (position);

-- ─── actions_log ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS actions_log (
    id            SERIAL PRIMARY KEY,
    timestamp     TIMESTAMP    NOT NULL DEFAULT NOW(),
    "user"        VARCHAR(255) NOT NULL DEFAULT 'admin',
    pis_selected  TEXT[]       NOT NULL,
    action        VARCHAR(50)  NOT NULL
                      CHECK (action IN ('kill','restart','execute','health','status','discovery')),
    command       TEXT,
    exit_code     INT,
    stdout        TEXT,
    stderr        TEXT,
    status        VARCHAR(20)  NOT NULL
                      CHECK (status IN ('success','fail','partial_fail','running','queued')),
    retry_count   SMALLINT     NOT NULL DEFAULT 0,
    duration_ms   INT
);

CREATE INDEX IF NOT EXISTS idx_actions_log_timestamp ON actions_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_actions_log_user      ON actions_log ("user");
CREATE INDEX IF NOT EXISTS idx_actions_log_status    ON actions_log (status);

CREATE OR REPLACE RULE no_delete_actions_log AS
    ON DELETE TO actions_log DO INSTEAD NOTHING;
