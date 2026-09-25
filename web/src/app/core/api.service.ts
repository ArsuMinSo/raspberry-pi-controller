import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API } from './auth.service';
import {
  ActionProgress, ActionQueued, AuditEvent, FleetSummary, LogEntry, Me, PiDetail, PiSummary, Role, SessionInfo, Settings, SSHTestResult, User,
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

  // ── Logs ──────────────────────────────────────────────────────────────────
  logs(filter: { pi?: string; user?: string; limit?: number }): Observable<LogEntry[]> {
    return this.http.get<LogEntry[]>(`${API}/logs`, { params: params({ limit: 100, ...filter }) });
  }

  events(filter: { user?: string; event?: string; limit?: number }): Observable<AuditEvent[]> {
    return this.http.get<AuditEvent[]>(`${API}/logs/events`, { params: params({ limit: 100, ...filter }) });
  }

  // ── Settings (admin) ───────────────────────────────────────────────────────
  getSettings(): Observable<Settings> {
    return this.http.get<Settings>(`${API}/settings`);
  }

  patchSettings(body: Partial<Settings>): Observable<Settings> {
    return this.http.patch<Settings>(`${API}/settings`, body);
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
}
