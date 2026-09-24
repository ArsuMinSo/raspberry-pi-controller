-- ─── 003: users, sessions, audit events (web service phase 1) ────────────────
-- See docs/design/web-service.md. Safe to re-run.

CREATE TABLE IF NOT EXISTS users (
    id                    SERIAL PRIMARY KEY,
    username              VARCHAR(32)  NOT NULL UNIQUE,
    password_hash         TEXT         NOT NULL,
    role                  VARCHAR(10)  NOT NULL
                              CHECK (role IN ('viewer', 'operator', 'admin')),
    is_active             BOOLEAN      NOT NULL DEFAULT TRUE,
    must_change_password  BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sessions (
    id            SERIAL PRIMARY KEY,
    user_id       INT          NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash    CHAR(64)     NOT NULL UNIQUE,  -- sha256 hex of the bearer token
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ  NOT NULL,
    revoked_at    TIMESTAMPTZ,
    ip            VARCHAR(45),
    user_agent    VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);

-- Append-only log of everything that isn't a Pi operation (logins, edits, settings, users)
CREATE TABLE IF NOT EXISTS audit_events (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    user_id     INT           REFERENCES users (id),
    username    VARCHAR(64)   NOT NULL,
    event       VARCHAR(40)   NOT NULL,
    target      VARCHAR(255),
    details     JSONB,
    ip          VARCHAR(45),
    user_agent  VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_audit_events_ts      ON audit_events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_user    ON audit_events (username);
CREATE INDEX IF NOT EXISTS idx_audit_events_event   ON audit_events (event);

CREATE OR REPLACE RULE no_delete_audit_events AS
    ON DELETE TO audit_events DO INSTEAD NOTHING;

-- Who did it
ALTER TABLE actions_log     ADD COLUMN IF NOT EXISTS user_id       INT REFERENCES users (id);
ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS owner_user_id INT REFERENCES users (id);
