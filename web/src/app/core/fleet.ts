// Pure helpers for fleet actions (diagnostics, reboot verification).

const THROTTLE_LABELS: Record<string, string> = {
  under_voltage_now: 'under-voltage now',
  freq_capped_now: 'CPU capped now',
  throttled_now: 'throttled now',
  soft_temp_limit_now: 'temp limit now',
  under_voltage_ever: 'under-voltage since boot',
  freq_capped_ever: 'CPU capped since boot',
  throttled_ever: 'throttled since boot',
  soft_temp_limit_ever: 'temp limit since boot',
};

/** Diagnostics `details.throttled` → "ok" or the active flags, e.g. "under-voltage now, throttled since boot". */
export function throttleText(throttled: unknown): string {
  if (!throttled || typeof throttled !== 'object') {
    return '—';
  }
  const t = throttled as Record<string, unknown>;
  if (t['ok'] === true) {
    return 'ok';
  }
  const active = Object.keys(THROTTLE_LABELS).filter((k) => t[k] === true).map((k) => THROTTLE_LABELS[k]);
  return active.length ? active.join(', ') : String(t['raw'] ?? 'unknown');
}

export type RebootVerdict = 'rebooted' | 'not-rebooted' | 'unknown';

/** Grace for the reboot delay + health check duration. */
const REBOOT_MARGIN_S = 60;

/**
 * Did the Pi reboot? Its uptime at the verification health check must be shorter than the time since the reboot
 * was requested. Both timestamps come from the server (actions_log), so browser clock skew doesn't matter.
 */
export function rebootVerdict(
  uptimeS: number | null, rebootStartedAt: string, healthStartedAt: string,
): RebootVerdict {
  const elapsedS = (Date.parse(healthStartedAt) - Date.parse(rebootStartedAt)) / 1000;
  if (uptimeS === null || !isFinite(elapsedS)) {
    return 'unknown';
  }
  return uptimeS <= elapsedS + REBOOT_MARGIN_S ? 'rebooted' : 'not-rebooted';
}
