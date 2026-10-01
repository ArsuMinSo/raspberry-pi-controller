-- ─── 009: widen actions_log.action CHECK for floor map scans ──────────────

ALTER TABLE actions_log DROP CONSTRAINT IF EXISTS actions_log_action_check;
ALTER TABLE actions_log ADD CONSTRAINT actions_log_action_check
    CHECK (action IN ('kill', 'restart', 'execute', 'health', 'status', 'discovery',
                      'reboot', 'diagnostics', 'wifi_scan', 'ble_scan'));
