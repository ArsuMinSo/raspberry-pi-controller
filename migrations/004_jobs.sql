-- ─── 004: background jobs — per-Pi results, 'interrupted' status (web service phase 2) ─
-- Safe to re-run.

-- One row per Pi as soon as it finishes → progress = rows / pis_selected
CREATE TABLE IF NOT EXISTS action_results (
    id           SERIAL PRIMARY KEY,
    action_id    INT          NOT NULL REFERENCES actions_log (id),
    position     VARCHAR(20)  NOT NULL,
    exit_code    INT,
    stdout       TEXT,
    stderr       TEXT,
    error        TEXT,
    details      JSONB,        -- action-specific (health: cpu/mem/temp/uptime …)
    duration_ms  INT,
    finished_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_action_results_action ON action_results (action_id);

CREATE OR REPLACE RULE no_delete_action_results AS
    ON DELETE TO action_results DO INSTEAD NOTHING;

-- Jobs still queued/running when the backend restarts are marked 'interrupted'
ALTER TABLE actions_log DROP CONSTRAINT IF EXISTS actions_log_status_check;
ALTER TABLE actions_log ADD CONSTRAINT actions_log_status_check
    CHECK (status IN ('success', 'fail', 'partial_fail', 'running', 'queued', 'interrupted'));
