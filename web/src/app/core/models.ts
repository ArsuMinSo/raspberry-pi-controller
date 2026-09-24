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
