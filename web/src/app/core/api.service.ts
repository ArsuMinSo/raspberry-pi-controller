import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { API } from './auth.service';
import {
  AccessPointOut, ActionProgress, ActionQueued, AuditEvent, BleDeviceSeen, FleetSummary, FloorMapResponse, LogEntry,
  Me, PiDetail, PiSummary, Role, ScheduledTask, ScheduledTaskCreate, ScheduledTaskUpdate, SessionInfo, Settings,
  SSHTestResult, User,
} from './models';

type Params = Record<string, string | number | null | undefined>;

function params(p: Params): HttpParams {
  let hp = new HttpParams();
  for (const [k, v] of Object.entries(p)) {
    if (v !== null && v !== undefined && v !== '') {
      hp = hp.set(k, String(v));
    }
  }
  return hp;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  // ── Account ───────────────────────────────────────────────────────────────
  me(): Observable<Me> {
    return this.http.get<Me>(`${API}/auth/me`);
  }

  changePassword(current: string, next: string, confirm: string): Observable<void> {
    return this.http.post<void>(`${API}/auth/me/password`, {
      current_password: current, new_password: next, new_password_confirm: confirm,
    });
  }

  sessions(): Observable<SessionInfo[]> {
    return this.http.get<SessionInfo[]>(`${API}/auth/me/sessions`);
  }

  revokeSession(id: number): Observable<void> {
    return this.http.delete<void>(`${API}/auth/me/sessions/${id}`);
  }

  // ── Inventory ─────────────────────────────────────────────────────────────
  listPis(): Observable<PiSummary[]> {
    return this.http.get<PiSummary[]>(`${API}/pi/list`, { params: params({ limit: 500 }) });
  }

  pi(position: string): Observable<PiDetail> {
    return this.http.get<PiDetail>(`${API}/pi/${encodeURIComponent(position)}/status`);
  }

  // ── Actions ───────────────────────────────────────────────────────────────
  healthCheck(positions: string[]): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/health/trigger`, { pis: positions });
  }

  healthCheckAll(): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/health/trigger`, { all: true });
  }

  reboot(positions: string[]): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/pi/reboot`, { pis: positions });
  }

  diagnostics(positions: string[]): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/diagnostics`, { pis: positions });
  }

  fleetSummary(staleHours = 24): Observable<FleetSummary> {
    return this.http.get<FleetSummary>(`${API}/fleet/summary`, { params: params({ stale_hours: staleHours }) });
  }

  action(id: number): Observable<ActionProgress> {
    return this.http.get<ActionProgress>(`${API}/actions/${id}`);
  }

  // ── Users (admin) ─────────────────────────────────────────────────────────
  users(): Observable<User[]> {
    return this.http.get<User[]>(`${API}/users`);
  }

  createUser(body: {
    username: string; role: Role; password: string; password_confirm: string; must_change_password: boolean;
  }): Observable<User> {
    return this.http.post<User>(`${API}/users`, body);
  }

  updateUser(id: number, patch: { role?: Role; is_active?: boolean }): Observable<User> {
    return this.http.patch<User>(`${API}/users/${id}`, patch);
  }

  resetPassword(id: number, password: string, confirm: string, mustChange: boolean): Observable<void> {
    return this.http.post<void>(`${API}/users/${id}/password`, {
      password, password_confirm: confirm, must_change_password: mustChange,
    });
  }

  revokeUserSessions(id: number): Observable<void> {
    return this.http.post<void>(`${API}/users/${id}/revoke-sessions`, {});
  }

  /** Viewer accounts only — pushes their active session(s) out to a long expiry (kiosk displays). */
  extendSession(id: number): Observable<void> {
    return this.http.post<void>(`${API}/users/${id}/extend-session`, {});
  }

  // ── Logs ──────────────────────────────────────────────────────────────────
  logs(filter: { pi?: string; user?: string; limit?: number }): Observable<LogEntry[]> {
    return this.http.get<LogEntry[]>(`${API}/logs`, { params: params({ limit: 100, ...filter }) });
  }

  events(filter: { user?: string; event?: string; limit?: number }): Observable<AuditEvent[]> {
    return this.http.get<AuditEvent[]>(`${API}/logs/events`, { params: params({ limit: 100, ...filter }) });
  }

  // ── Settings (admin) ───────────────────────────────────────────────────────
  // Backend's wire shape doesn't match the Settings model: GET nests ssh/network but names
  // the key path field `private_key_path`, and PATCH wants a *flat* body (`ssh_key_path`,
  // `timeout_s`, `subnet`, ...) — see backend/routes/settings.py. Translate both ways here
  // so the rest of the app can work with the clean nested Settings shape.
  getSettings(): Observable<Settings> {
    return this.http.get<{ ssh: Record<string, unknown>; network: Settings['network'] }>(`${API}/settings`).pipe(
      map((raw) => ({
        ssh: {
          key_path: raw.ssh['private_key_path'] as string,
          username: raw.ssh['username'] as string,
          timeout_s: raw.ssh['timeout_s'] as number,
          retry_count: raw.ssh['retry_count'] as number,
          retry_delay_s: raw.ssh['retry_delay_s'] as number,
          parallel_limit: raw.ssh['parallel_limit'] as number,
        },
        network: raw.network,
      })),
    );
  }

  patchSettings(body: Partial<Settings>): Observable<Settings> {
    const flat: Record<string, unknown> = {};
    if (body.ssh) {
      const s = body.ssh;
      if (s.key_path !== undefined) flat['ssh_key_path'] = s.key_path;
      if (s.username !== undefined) flat['username'] = s.username;
      if (s.timeout_s !== undefined) flat['timeout_s'] = s.timeout_s;
      if (s.retry_count !== undefined) flat['retry_count'] = s.retry_count;
      if (s.retry_delay_s !== undefined) flat['retry_delay_s'] = s.retry_delay_s;
      if (s.parallel_limit !== undefined) flat['parallel_limit'] = s.parallel_limit;
    }
    if (body.network) {
      const n = body.network;
      if (n.subnet !== undefined) flat['subnet'] = n.subnet;
      if (n.probe_ssh !== undefined) flat['probe_ssh'] = n.probe_ssh;
      if (n.probe_timeout_s !== undefined) flat['probe_timeout_s'] = n.probe_timeout_s;
      if (n.probe_username !== undefined) flat['probe_username'] = n.probe_username;
      if (n.probe_auth !== undefined) flat['probe_auth'] = n.probe_auth;
      if (n.probe_deploy_key !== undefined) flat['probe_deploy_key'] = n.probe_deploy_key;
    }
    return this.http.patch<{ ssh: Record<string, unknown>; network: Settings['network'] }>(`${API}/settings`, flat).pipe(
      map((raw) => ({
        ssh: {
          key_path: raw.ssh['private_key_path'] as string,
          username: raw.ssh['username'] as string,
          timeout_s: raw.ssh['timeout_s'] as number,
          retry_count: raw.ssh['retry_count'] as number,
          retry_delay_s: raw.ssh['retry_delay_s'] as number,
          parallel_limit: raw.ssh['parallel_limit'] as number,
        },
        network: raw.network,
      })),
    );
  }

  testSSH(ip: string): Observable<SSHTestResult> {
    return this.http.post<SSHTestResult>(`${API}/settings/test`, { ip });
  }

  // ── Execute Command (admin) ────────────────────────────────────────────────
  executeCommand(positions: string[], command: string, ssh_username?: string, ssh_password?: string): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/command/execute`, {
      pis: positions, command, ssh_username, ssh_password,
    });
  }

  // ── Scheduled Tasks (operator list, admin manage) ──────────────────────────
  listTasks(): Observable<ScheduledTask[]> {
    return this.http.get<ScheduledTask[]>(`${API}/tasks`);
  }

  createTask(body: ScheduledTaskCreate): Observable<ScheduledTask> {
    return this.http.post<ScheduledTask>(`${API}/tasks`, body);
  }

  updateTask(id: number, body: ScheduledTaskUpdate): Observable<ScheduledTask> {
    return this.http.patch<ScheduledTask>(`${API}/tasks/${id}`, body);
  }

  deleteTask(id: number): Observable<void> {
    return this.http.delete<void>(`${API}/tasks/${id}`);
  }

  // ── Floor Map ────────────────────────────────────────────────────────────────
  floorMap(): Observable<FloorMapResponse> {
    return this.http.get<FloorMapResponse>(`${API}/floor-map`);
  }

  floorMapWifiScan(positions: string[]): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/floor-map/wifi-scan`, { pis: positions });
  }

  floorMapWifiScanAll(): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/floor-map/wifi-scan`, { all: true });
  }

  floorMapBleScan(positions: string[]): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/floor-map/ble-scan`, { pis: positions });
  }

  floorMapBleScanAll(): Observable<ActionQueued> {
    return this.http.post<ActionQueued>(`${API}/floor-map/ble-scan`, { all: true });
  }

  placeAccessPoint(bssid: string, x: number, y: number): Observable<AccessPointOut> {
    return this.http.patch<AccessPointOut>(`${API}/floor-map/ap/${encodeURIComponent(bssid)}`, { x, y });
  }

  setAccessPointGroup(bssid: string, groupName: string | null): Observable<AccessPointOut> {
    return this.http.patch<AccessPointOut>(`${API}/floor-map/ap/${encodeURIComponent(bssid)}/group`, { group_name: groupName });
  }

  listAccessPointGroups(): Observable<string[]> {
    return this.http.get<string[]>(`${API}/floor-map/groups`);
  }

  bleDevicesForPi(position: string): Observable<BleDeviceSeen[]> {
    return this.http.get<BleDeviceSeen[]>(`${API}/floor-map/pi/${encodeURIComponent(position)}/ble`);
  }
}
