import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { LoginResponse, Role, User } from './models';
import { hasRole } from './roles';

export const API = '/api/v1';
const STORAGE_KEY = 'pic.session';

interface StoredSession {
  token: string;
  expiresAt: string; // ISO
  user: User;
}

/** Why the user landed on the login page (shown there). */
export type LogoutReason = 'expired' | 'logged-out';

/**
 * Login state. The token lives in sessionStorage — gone when the browser closes;
 * sessions also end server-side 12 h after login (then the next request gets 401).
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private readonly session = signal<StoredSession | null>(this.restore());
  private expiryTimer: ReturnType<typeof setTimeout> | null = null;

  readonly user = computed(() => this.session()?.user ?? null);
  readonly loggedIn = computed(() => this.session() !== null);

  constructor() {
    this.scheduleExpiry();
  }

  get token(): string | null {
    return this.session()?.token ?? null;
  }

  can(required: Role): boolean {
    return hasRole(this.user()?.role, required);
  }

  async login(username: string, password: string): Promise<User> {
    const res = await firstValueFrom(this.http.post<LoginResponse>(`${API}/auth/login`, { username, password }));
    this.store({ token: res.token, expiresAt: res.expires_at, user: res.user });
    return res.user;
  }

  /** Ends the session on the server (best effort), then locally. */
  async logout(): Promise<void> {
    if (this.token) {
      try {
        await firstValueFrom(this.http.post(`${API}/auth/logout`, {}));
      } catch {
        // already expired / server unreachable — still log out locally
      }
    }
    this.endSession('logged-out');
  }

  /** Local logout + redirect to login (used on 401 and when the 12 h are up). */
  endSession(reason: LogoutReason): void {
    this.clear();
    void this.router.navigate(['/login'], { queryParams: { reason } });
  }

  updateUser(patch: Partial<User>): void {
    const s = this.session();
    if (s) {
      this.store({ ...s, user: { ...s.user, ...patch } });
    }
  }

  private store(s: StoredSession): void {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch {
      // storage blocked — session lives in memory only
    }
    this.session.set(s);
    this.scheduleExpiry();
  }

  private clear(): void {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    this.session.set(null);
    this.scheduleExpiry();
  }

  private restore(): StoredSession | null {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return null;
      }
      const s = JSON.parse(raw) as StoredSession;
      if (!s.token || !s.expiresAt || new Date(s.expiresAt).getTime() <= Date.now()) {
        sessionStorage.removeItem(STORAGE_KEY);
        return null;
      }
      return s;
    } catch {
      return null;
    }
  }

  private scheduleExpiry(): void {
    if (this.expiryTimer !== null) {
      clearTimeout(this.expiryTimer);
      this.expiryTimer = null;
    }
    const s = this.session();
    if (!s) {
      return;
    }
    const ms = new Date(s.expiresAt).getTime() - Date.now();
    // setTimeout caps at ~24.8 days; sessions are 12 h
    this.expiryTimer = setTimeout(() => this.endSession('expired'), Math.max(0, ms));
  }
}
