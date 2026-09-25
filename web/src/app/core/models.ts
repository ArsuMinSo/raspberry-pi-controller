// Shapes returned by the backend (/api/v1). Mirrors backend/schemas.py.

export type Role = 'viewer' | 'operator' | 'admin';

export interface User {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface LoginResponse {
  token: string;
  expires_at: string;
  user: User;
}

export interface Me {
  username: string;
  role: Role;
  user: User | null;
}

export interface SessionInfo {
  id: number;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  ip: string | null;
  user_agent: string | null;
  current: boolean;
}

export interface PiSummary {
  mac: string;
  hostname: string | null;
  position: string;
  ip: string | null;
  pi_version: number | null;
  status: string;
  last_seen: string | null;
  tags: string[];
  cpu_1m: number | null;
  cpu_5m: number | null;
  cpu_15m: number | null;
  mem_percent: number | null;
  temp_c: number | null;
}

export interface PiDetail {
  mac: string;
  hostname: string | null;
  position: string;
  ip: string | null;
  status: string;
  last_seen: string | null;
  tags: string[];
  serial: string | null;
  pi_version: number | null;
  created_at: string;
  updated_at: string;
}

export interface ActionQueued {
  action_id: number;
  status: string;
}

export interface ActionResult {
  position: string;
  exit_code: number | null;
  stdout: string | null;
  stderr: string | null;
  error: string | null;
  details: Record<string, unknown> | null;
  duration_ms: number | null;
  finished_at: string;
}

export interface ActionProgress {
  action_id: number;
  action: string;
  status: string;
  finished: boolean;
  user: string;
  command: string | null;
  pis_selected: string[];
  total: number;
  done: number;
  results: ActionResult[];
  error: string | null;
  started_at: string;
  duration_ms: number | null;
}

export interface LogEntry {
  id: number;
  timestamp: string;
  user: string;
  pis_selected: string[];
  action: string;
  command: string | null;
  exit_code: number | null;
  status: string;
  stdout: string | null;
  stderr: string | null;
  duration_ms: number | null;
}

export interface AuditEvent {
  id: number;
  ts: string;
  username: string;
  event: string;
  target: string | null;
  details: Record<string, unknown> | null;
  ip: string | null;
}

// ── Fleet ────────────────────────────────────────────────────────────────────

export interface FleetPiValue {
  position: string;
  hostname: string | null;
  value: number;
}

export interface FleetSummary {
  total: number;
  reachable: number;
  unreachable: number;
  stale_hours: number;
  stale: string[];
  never_seen: string[];
  hottest: FleetPiValue[];
  busiest_cpu: FleetPiValue[];
  highest_mem: FleetPiValue[];
  last_health_check_at: string | null;
}

// ── Settings ─────────────────────────────────────────────────────────────────

export interface SSHSettings {
  key_path: string;
  username: string;
  timeout_s: number;
  retry_count: number;
  retry_delay_s: number;
  parallel_limit: number;
}

export interface NetworkSettings {
  subnet: string;
  probe_ssh: boolean;
  probe_timeout_s: number;
  probe_username: string;
  probe_auth: 'key' | 'password';
  probe_deploy_key: boolean;
}

export interface Settings {
  ssh: SSHSettings;
  network: NetworkSettings;
}

export interface SSHTestResult {
  ip: string;
  success: boolean;
  settings_used: SSHSettings;
  error: string | null;
  error_type: string | null;
  stdout: string | null;
}
