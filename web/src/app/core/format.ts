/** Ionic colour for a Pi status or an action status. */
export function statusColor(status: string | null | undefined): string {
  switch (status) {
    case 'reachable':
    case 'success':
      return 'success';
    case 'partial_fail':
    case 'running':
    case 'queued':
      return 'warning';
    case 'unreachable':
    case 'fail':
    case 'interrupted':
      return 'danger';
    default:
      return 'medium';
  }
}

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(0)} %`;
}

export function temp(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(1)} °C`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) {
    return '—';
  }
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Number from an untyped JSON details object (health results). */
export function num(details: Record<string, unknown> | null | undefined, key: string): number | null {
  const v = details?.[key];
  return typeof v === 'number' ? v : null;
}

export function uptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '—';
  }
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
}
