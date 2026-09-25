import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import {
  IonBadge, IonButton, IonButtons, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonContent, IonHeader,
  IonIcon, IonMenuButton, IonSpinner, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom, switchMap, timer } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime, pct, statusColor, temp } from '../core/format';
import { FleetSummary, LogEntry, PiSummary, ScheduledTask } from '../core/models';
import { comparePositions } from '../core/sort';

/** Background refresh so results of a health check (or anything else) show up without a manual click. */
const AUTO_REFRESH_MS = 10_000;

@Component({
  selector: 'app-dashboard',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Dashboard</ion-title>
        <ion-buttons slot="end">
          <ion-button (click)="reactorMode.set(!reactorMode())" [color]="reactorMode() ? 'danger' : undefined"
                      aria-label="Toggle reactor view">
            <span slot="icon-only" class="reactor-toggle-icon" aria-hidden="true">☢</span>
          </ion-button>
          <ion-button (click)="load()" [disabled]="loading()" aria-label="Refresh">
            <ion-icon slot="icon-only" name="refresh-outline"></ion-icon>
          </ion-button>
        </ion-buttons>
      </ion-toolbar>
    </ion-header>
    <ion-content class="ion-padding" [class.reactor-bg]="reactorMode()">
      @if (error()) { <ion-text color="danger"><p>{{ error() }}</p></ion-text> }
      @if (loading() && !summary()) {
        <div class="ion-text-center"><ion-spinner></ion-spinner></div>
      }

      @if (reactorMode()) {
        <div class="reactor">
          <div class="reactor-ticks" aria-hidden="true"></div>
          <div class="reactor-core" [title]="reactorStatusLabel()">
            <div class="reactor-core-inner">
              <div class="reactor-core-value">{{ pis().length }}</div>
              <div class="reactor-core-label">UNITS</div>
              <div class="reactor-core-sub">{{ summary()?.reachable ?? 0 }} UP · {{ summary()?.unreachable ?? 0 }} DOWN</div>
            </div>
          </div>
          @for (r of reactorPis(); track r.pi.mac) {
            <div class="wedge-wrap" [style.left.%]="r.left" [style.top.%]="r.top"
                 [style.transform]="'translate(-50%, -50%) rotate(' + r.rotate + 'deg)'"
                 [routerLink]="['/pi', r.pi.position]"
                 [title]="r.pi.position + ' — ' + (r.pi.hostname ?? 'no hostname') + ' — ' + r.pi.status">
              <div class="wedge" [class]="'wedge-' + statusColor(r.pi.status)" [class.wedge-hot]="isHot(r.pi)">
                <div class="wedge-fill" [style.height.%]="fillPercent(r.pi)"></div>
              </div>
              <div class="wedge-label" [style.transform]="'rotate(' + (-r.rotate) + 'deg)'">{{ r.pi.position }}</div>
            </div>
          }
        </div>
      }

      @if (!reactorMode() && summary(); as f) {
        <!-- Stat tiles -->
        <div class="tiles">
          <div class="tile" [class]="'tile-primary'">
            <div class="tile-value">{{ f.total }}</div>
            <div class="tile-label">Total Pis</div>
          </div>
          <div class="tile clickable tile-success" (click)="filterAndGo('reachable')">
            <div class="tile-value">{{ f.reachable }}</div>
            <div class="tile-label">Reachable</div>
          </div>
          <div class="tile clickable tile-danger" (click)="filterAndGo('unreachable')">
            <div class="tile-value">{{ f.unreachable }}</div>
            <div class="tile-label">Unreachable</div>
          </div>
          <div class="tile clickable tile-warning" (click)="selectAndGo(f.stale)">
            <div class="tile-value">{{ f.stale.length }}</div>
            <div class="tile-label">Stale (&gt; {{ f.stale_hours }}h)</div>
          </div>
          <div class="tile clickable tile-medium" (click)="selectAndGo(f.never_seen)">
            <div class="tile-value">{{ f.never_seen.length }}</div>
            <div class="tile-label">Never seen</div>
          </div>
        </div>
        <p class="muted last-check">Last health check: {{ dateTime(f.last_health_check_at) }}</p>

        <!-- Fleet status grid (Zabbix-style host overview) -->
        <ion-card>
          <ion-card-header><ion-card-title>Fleet status</ion-card-title></ion-card-header>
          <ion-card-content>
            @if (pis().length === 0) {
              <p class="muted">No Pis in inventory.</p>
            } @else {
              <div class="status-grid">
                @for (pi of sortedPis(); track pi.mac) {
                  <div class="status-cell" [class]="'status-' + statusColor(pi.status)" [class.hot]="isHot(pi)"
                       [routerLink]="['/pi', pi.position]"
                       [title]="pi.position + ' — ' + (pi.hostname ?? 'no hostname') + ' — ' + pi.status + (isHot(pi) ? ' — ' + temp(pi.temp_c) + ' 🔥' : '')">
                    {{ pi.position }}
                    @if (isHot(pi)) { <span class="flame" aria-hidden="true">🔥</span> }
                  </div>
                }
              </div>
            }
          </ion-card-content>
        </ion-card>

        <!-- Top 5 panels -->
        <div class="top5-row">
          <ion-card>
            <ion-card-header><ion-card-title>Hottest</ion-card-title></ion-card-header>
            <ion-card-content>
              @if (f.hottest.length === 0) { <p class="muted">No data.</p> }
              @for (h of f.hottest; track h.position) {
                <div class="bar-row clickable" [routerLink]="['/pi', h.position]">
                  <span class="bar-label">{{ h.position }}</span>
                  <div class="bar-track"><div class="bar-fill" [style.width.%]="pctOf(h.value, 90)"></div></div>
                  <span class="bar-value">{{ temp(h.value) }}</span>
                </div>
              }
            </ion-card-content>
          </ion-card>
          <ion-card>
            <ion-card-header><ion-card-title>Busiest CPU</ion-card-title></ion-card-header>
            <ion-card-content>
              @if (f.busiest_cpu.length === 0) { <p class="muted">No data.</p> }
              @for (c of f.busiest_cpu; track c.position) {
                <div class="bar-row clickable" [routerLink]="['/pi', c.position]">
                  <span class="bar-label">{{ c.position }}</span>
                  <div class="bar-track"><div class="bar-fill" [style.width.%]="pctOf(c.value, 100)"></div></div>
                  <span class="bar-value">{{ pct(c.value) }}</span>
                </div>
              }
            </ion-card-content>
          </ion-card>
        </div>
      }

      @if (!reactorMode() && canSeeOps) {
        <div class="ops-row">
          <ion-card>
            <ion-card-header><ion-card-title>Recent activity</ion-card-title></ion-card-header>
            <ion-card-content>
              @if (recentActions().length === 0) {
                <p class="muted">No recent actions.</p>
              } @else {
                @for (a of recentActions(); track a.id) {
                  <div class="activity-row clickable" [routerLink]="['/actions', a.id]">
                    <ion-badge [color]="statusColor(a.status)">{{ a.status }}</ion-badge>
                    <span class="activity-action">{{ a.action }}</span>
                    <span class="activity-user muted">{{ a.user }}</span>
                    <span class="activity-time muted">{{ dateTime(a.timestamp) }}</span>
                  </div>
                }
              }
              <ion-button fill="clear" size="small" routerLink="/logs">View all activity</ion-button>
            </ion-card-content>
          </ion-card>

          <ion-card>
            <ion-card-header><ion-card-title>Scheduled tasks</ion-card-title></ion-card-header>
            <ion-card-content>
              @if (tasks().length === 0) {
                <p class="muted">No scheduled tasks.</p>
              } @else {
                <p><strong>{{ enabledTaskCount() }}</strong> of {{ tasks().length }} enabled</p>
                @if (failedTasks().length > 0) {
                  <ion-text color="danger">
                    <p>{{ failedTasks().length }} task(s) last failed:</p>
                  </ion-text>
                  @for (t of failedTasks(); track t.id) {
                    <div class="activity-row">
                      <ion-badge color="danger">fail</ion-badge>
                      <span class="activity-action">{{ t.name }}</span>
                      <span class="activity-time muted">{{ dateTime(t.last_run) }}</span>
                    </div>
                  }
                } @else {
                  <p class="muted">No failing tasks.</p>
                }
              }
              <ion-button fill="clear" size="small" routerLink="/tasks">Manage tasks</ion-button>
            </ion-card-content>
          </ion-card>
        </div>
      }
    </ion-content>
  `,
  styles: [`
    .page-narrow { max-width: 960px; margin: 0 auto; }
    .tiles { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 4px; }
    .tile {
      flex: 1 1 8rem;
      min-width: 8rem;
      padding: 16px;
      border-radius: 8px;
      background: var(--ion-color-step-50, #1e1e24);
      border-left: 4px solid var(--ion-color-medium);
      text-align: center;
    }
    .tile.clickable { cursor: pointer; }
    .tile.clickable:hover { filter: brightness(1.1); }
    .tile-value { font-size: 2rem; font-weight: 700; line-height: 1.1; }
    .tile-label { font-size: 0.8rem; color: var(--ion-color-medium); margin-top: 4px; }
    .tile-primary { border-left-color: var(--ion-color-primary); }
    .tile-success { border-left-color: var(--ion-color-success); }
    .tile-danger { border-left-color: var(--ion-color-danger); }
    .tile-warning { border-left-color: var(--ion-color-warning); }
    .tile-medium { border-left-color: var(--ion-color-medium); }
    .last-check { margin: 8px 0 20px; font-size: 0.85rem; }

    .status-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(3.2rem, 1fr)); gap: 4px; }
    .status-cell {
      padding: 6px 2px;
      text-align: center;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
      color: #fff;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .status-success { background: var(--ion-color-success); }
    .status-danger { background: var(--ion-color-danger); }
    .status-warning { background: var(--ion-color-warning); color: #000; }
    .status-medium { background: var(--ion-color-medium); }

    .status-cell.hot {
      position: relative;
      background: linear-gradient(180deg, #ff7b1a, #d0281a);
      animation: burn-glow 1.1s ease-in-out infinite;
      overflow: visible;
    }
    .flame {
      position: absolute;
      top: -10px;
      right: -2px;
      font-size: 0.9rem;
      animation: flame-flicker 0.6s ease-in-out infinite alternate;
      pointer-events: none;
    }
    @keyframes burn-glow {
      0%, 100% { box-shadow: 0 0 4px 1px rgba(255, 90, 0, 0.6); }
      50% { box-shadow: 0 0 10px 3px rgba(255, 140, 0, 0.9); }
    }
    @keyframes flame-flicker {
      0% { transform: translateY(0) scale(1) rotate(-4deg); opacity: 0.85; }
      50% { transform: translateY(-2px) scale(1.15) rotate(3deg); opacity: 1; }
      100% { transform: translateY(-1px) scale(0.95) rotate(-2deg); opacity: 0.9; }
    }
    @media (prefers-reduced-motion: reduce) {
      .status-cell.hot { animation: none; box-shadow: 0 0 6px 2px rgba(255, 90, 0, 0.7); }
      .flame { animation: none; }
    }

    .reactor-toggle-icon { font-size: 1.2rem; line-height: 1; }

    ion-content.reactor-bg {
      --background: radial-gradient(circle at center, #061014 0%, #020403 78%);
      --padding-start: 4px;
      --padding-end: 4px;
      --padding-top: 4px;
    }

    .hud-font { font-family: 'Courier New', ui-monospace, monospace; letter-spacing: 0.06em; }

    .reactor {
      position: relative;
      width: min(98vw, 96vh, 1400px);
      height: min(98vw, 96vh, 1400px);
      max-width: 100%;
      margin: 8px auto;
      font-family: 'Courier New', ui-monospace, monospace;
    }

    /* Decorative outer tick ring, echoing a HUD dial's minor-tick scale */
    .reactor-ticks {
      position: absolute;
      inset: 2%;
      border-radius: 50%;
      background: repeating-conic-gradient(
        rgba(64, 220, 220, 0.55) 0deg 0.6deg,
        transparent 0.6deg 3.6deg
      );
      -webkit-mask: radial-gradient(circle, transparent 96%, #000 97%, #000 99%, transparent 100%);
      mask: radial-gradient(circle, transparent 96%, #000 97%, #000 99%, transparent 100%);
      pointer-events: none;
    }

    .reactor-core {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      width: 46%; height: 46%;
      min-width: 8rem; min-height: 8rem;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      background:
        radial-gradient(circle, #ff8a3d 0%, #c8431a 42%, #3a0f06 75%, #150502 100%),
        repeating-linear-gradient(0deg, rgba(0,0,0,0.25) 0 1px, transparent 1px 8px),
        repeating-linear-gradient(60deg, rgba(0,0,0,0.2) 0 1px, transparent 1px 8px),
        repeating-linear-gradient(120deg, rgba(0,0,0,0.2) 0 1px, transparent 1px 8px);
      box-shadow: 0 0 30px 8px rgba(255, 110, 30, 0.45), inset 0 0 40px 10px rgba(0, 0, 0, 0.55);
      animation: core-pulse 2.4s ease-in-out infinite;
    }
    .reactor-core::before {
      content: '';
      position: absolute;
      inset: 10%;
      border-radius: 50%;
      border: 1px dashed rgba(64, 220, 220, 0.6);
    }
    .reactor-core-inner {
      position: relative;
      width: 62%; height: 62%;
      border-radius: 50%;
      background: rgba(2, 6, 6, 0.72);
      border: 1px solid rgba(120, 240, 240, 0.5);
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      color: #7bfcf5;
      text-shadow: 0 0 6px rgba(90, 250, 240, 0.7);
    }
    .reactor-core-value { font-size: 1.6rem; font-weight: 700; line-height: 1; }
    .reactor-core-label { font-size: 0.6rem; letter-spacing: 0.15em; opacity: 0.8; }
    .reactor-core-sub { font-size: 0.55rem; letter-spacing: 0.06em; margin-top: 4px; opacity: 0.75; white-space: nowrap; }
    @keyframes core-pulse {
      0%, 100% { box-shadow: 0 0 22px 5px rgba(255, 110, 30, 0.4), inset 0 0 40px 10px rgba(0, 0, 0, 0.55); }
      50% { box-shadow: 0 0 38px 12px rgba(255, 140, 40, 0.7), inset 0 0 40px 10px rgba(0, 0, 0, 0.55); }
    }

    .wedge-wrap {
      position: absolute;
      display: flex; flex-direction: column; align-items: center;
      cursor: pointer;
    }
    .wedge {
      width: 2.1rem;
      height: 2.6rem;
      clip-path: polygon(32% 0%, 68% 0%, 100% 100%, 0% 100%);
      border: 1px solid rgba(64, 220, 220, 0.65);
      background:
        repeating-linear-gradient(0deg, rgba(0,0,0,0.25) 0 1px, transparent 1px 6px),
        rgba(4, 14, 16, 0.85);
      box-shadow: 0 0 6px 1px rgba(64, 220, 220, 0.35);
      overflow: hidden;
      display: flex;
      align-items: flex-end;
      transition: box-shadow 0.3s ease;
    }
    .wedge-wrap:hover .wedge { box-shadow: 0 0 12px 3px rgba(64, 220, 220, 0.7); }
    .wedge-fill {
      width: 100%;
      background: linear-gradient(180deg, #8affea, #17b8b0);
      transition: height 0.4s ease;
    }
    .wedge-success { border-color: rgba(64, 220, 220, 0.65); }
    .wedge-danger { border-color: rgba(255, 70, 70, 0.6); opacity: 0.5; }
    .wedge-danger .wedge-fill { background: #7a1f1f; }
    .wedge-warning { border-color: rgba(255, 190, 60, 0.7); }
    .wedge-medium { border-color: rgba(150, 160, 165, 0.6); }
    .wedge-hot .wedge-fill {
      background: linear-gradient(180deg, #ffd25a, #ff4d1a);
    }
    .wedge-hot {
      border-color: #ff6a2a;
      animation: wedge-danger-glow 1s ease-in-out infinite;
    }
    @keyframes wedge-danger-glow {
      0%, 100% { box-shadow: 0 0 5px 1px rgba(255, 90, 26, 0.6); }
      50% { box-shadow: 0 0 14px 4px rgba(255, 110, 26, 0.95); }
    }
    .wedge-label {
      font-size: 0.6rem;
      color: #8ff2ec;
      white-space: nowrap;
      margin-top: 2px;
      text-shadow: 0 0 4px rgba(90, 250, 240, 0.5);
    }
    @media (prefers-reduced-motion: reduce) {
      .reactor-core { animation: none; }
      .wedge-hot { animation: none; box-shadow: 0 0 9px 3px rgba(255, 90, 26, 0.85); }
    }

    .top5-row { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }
    .top5-row ion-card { flex: 1 1 16rem; margin: 0; }

    .bar-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
    .bar-row.clickable { cursor: pointer; }
    .bar-row.clickable:hover { opacity: 0.8; }
    .bar-label { flex: 0 0 3.5rem; font-size: 0.85rem; font-weight: 600; }
    .bar-track { flex: 1; height: 8px; background: var(--ion-color-step-100, #2a2a32); border-radius: 4px; overflow: hidden; }
    .bar-fill { height: 100%; background: var(--ion-color-primary); border-radius: 4px; }
    .bar-value { flex: 0 0 3rem; text-align: right; font-size: 0.8rem; font-variant-numeric: tabular-nums; }

    .ops-row { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }
    .ops-row ion-card { flex: 1 1 20rem; margin: 0; }
    .activity-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; flex-wrap: wrap; }
    .activity-row.clickable { cursor: pointer; }
    .activity-row.clickable:hover { opacity: 0.8; }
    .activity-action { font-weight: 600; }
    .activity-time { margin-left: auto; font-size: 0.8rem; }
  `],
  imports: [
    RouterLink, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonButton, IonIcon, IonContent, IonText,
    IonSpinner, IonCard, IonCardHeader, IonCardTitle, IonCardContent, IonBadge,
  ],
})
export class DashboardPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);

  readonly canSeeOps = this.auth.can('operator');
  readonly statusColor = statusColor;
  readonly pct = pct;
  readonly temp = temp;
  readonly dateTime = dateTime;

  readonly summary = signal<FleetSummary | null>(null);
  readonly pis = signal<PiSummary[]>([]);
  readonly recentActions = signal<LogEntry[]>([]);
  readonly tasks = signal<ScheduledTask[]>([]);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly reactorMode = signal(false);

  readonly sortedPis = computed(() => [...this.pis()].sort((a, b) => comparePositions(a.position, b.position)));
  readonly enabledTaskCount = computed(() => this.tasks().filter((t) => t.enabled).length);
  readonly failedTasks = computed(() => this.tasks().filter((t) => t.last_status === 'fail'));
  /** Positions each Pi as a wedge around the reactor ring, as a % of the container, starting at 12 o'clock. */
  readonly reactorPis = computed(() => {
    const pis = this.sortedPis();
    const n = pis.length;
    const RING_RADIUS_PCT = 38;
    return pis.map((pi, i) => {
      const angleDeg = (360 / n) * i;
      const rad = (angleDeg - 90) * (Math.PI / 180);
      return {
        pi,
        left: 50 + RING_RADIUS_PCT * Math.cos(rad),
        top: 50 + RING_RADIUS_PCT * Math.sin(rad),
        rotate: angleDeg,
      };
    });
  });

  constructor() {
    void this.load();
    // Auto-refresh in the background so results (e.g. a health check triggered elsewhere) show up without a manual click.
    timer(AUTO_REFRESH_MS, AUTO_REFRESH_MS)
      .pipe(switchMap(() => this.load()), takeUntilDestroyed(this.destroyRef))
      .subscribe();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const calls: [Promise<FleetSummary>, Promise<PiSummary[]>] = [
        firstValueFrom(this.api.fleetSummary()),
        firstValueFrom(this.api.listPis()),
      ];
      const [summary, pis] = await Promise.all(calls);
      this.summary.set(summary);
      this.pis.set(pis);

      if (this.canSeeOps) {
        const [actions, tasks] = await Promise.all([
          firstValueFrom(this.api.logs({ limit: 10 })),
          firstValueFrom(this.api.listTasks()),
        ]);
        this.recentActions.set(actions);
        this.tasks.set(tasks);
      }
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.loading.set(false);
    }
  }

  pctOf(value: number, max: number): number {
    return Math.max(2, Math.min(100, (value / max) * 100));
  }

  readonly HOT_THRESHOLD_C = 65;

  isHot(pi: PiSummary): boolean {
    return pi.temp_c !== null && pi.temp_c > this.HOT_THRESHOLD_C;
  }

  /** Rod fill height: temperature if known, else CPU load, else a low idle level. */
  fillPercent(pi: PiSummary): number {
    if (pi.temp_c !== null) return Math.max(6, Math.min(100, (pi.temp_c / 85) * 100));
    if (pi.cpu_1m !== null) return Math.max(6, Math.min(100, pi.cpu_1m));
    return 6;
  }

  reactorStatusLabel(): string {
    const s = this.summary();
    return s ? `${s.reachable} reachable / ${s.unreachable} unreachable` : '';
  }

  async filterAndGo(status: 'reachable' | 'unreachable'): Promise<void> {
    await this.router.navigate(['/inventory'], { queryParams: { status } });
  }

  async selectAndGo(positions: string[]): Promise<void> {
    if (positions.length === 0) return;
    await this.router.navigate(['/inventory'], { queryParams: { select: positions.join(',') } });
  }
}
