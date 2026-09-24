-- ─── 005: fleet actions (reboot, display power, diagnostics) ─────────────────
-- Widens the actions_log.action CHECK (defined inline in 001). Safe to re-run.

ALTER TABLE actions_log DROP CONSTRAINT IF EXISTS actions_log_action_check;
ALTER TABLE actions_log ADD CONSTRAINT actions_log_action_check
    CHECK (action IN ('kill', 'restart', 'execute', 'health', 'status', 'discovery',
                      'reboot', 'display', 'diagnostics'));
