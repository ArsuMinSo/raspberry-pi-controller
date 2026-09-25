import { Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import {
  IonBadge, IonButton, IonButtons, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonContent, IonHeader,
  IonIcon, IonMenuButton, IonSpinner, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime, pct, statusColor, temp } from '../core/format';
import { FleetPiValue, FleetSummary, LogEntry, PiSummary, ScheduledTask } from '../core/models';
import { comparePositions } from '../core/sort';

@Component({
  selector: 'app-dashboard',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Dashboard</ion-title>
        <ion-buttons slot="end">
          <ion-button (click)="load()" [disabled]="loading()" aria-label="Refresh">
            <ion-icon slot="icon-only" name="refresh-outline"></ion-icon>
          </ion-button>
        </ion-buttons>
      </ion-toolbar>
    </ion-header>
    <ion-content class="ion-padding">
      @if (error()) { <ion-text color="danger"><p>{{ error() }}</p></ion-text> }
      @if (loading() && !summary()) {
        <div class="ion-text-center"><ion-spinner></ion-spinner></div>
      }

      @if (summary(); as f) {
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
                  <div class="status-cell" [class]="'status-' + statusColor(pi.status)" [routerLink]="['/pi', pi.position]"
                       [title]="pi.position + ' — ' + (pi.hostname ?? 'no hostname') + ' — ' + pi.status">
                    {{ pi.position }}
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
          <ion-card>
            <ion-card-header><ion-card-title>Highest RAM</ion-card-title></ion-card-header>
            <ion-card-content>
              @if (f.highest_mem.length === 0) { <p class="muted">No data.</p> }
              @for (m of f.highest_mem; track m.position) {
                <div class="bar-row clickable" [routerLink]="['/pi', m.position]">
                  <span class="bar-label">{{ m.position }}</span>
                  <div class="bar-track"><div class="bar-fill" [style.width.%]="pctOf(m.value, 100)"></div></div>
                  <span class="bar-value">{{ pct(m.value) }}</span>
                </div>
              }
            </ion-card-content>
          </ion-card>
        </div>
      }

      @if (canSeeOps) {
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

  readonly sortedPis = computed(() => [...this.pis()].sort((a, b) => comparePositions(a.position, b.position)));
  readonly enabledTaskCount = computed(() => this.tasks().filter((t) => t.enabled).length);
  readonly failedTasks = computed(() => this.tasks().filter((t) => t.last_status === 'fail'));

  constructor() {
    void this.load();
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

  async filterAndGo(status: 'reachable' | 'unreachable'): Promise<void> {
    await this.router.navigate(['/inventory'], { queryParams: { status } });
  }

  async selectAndGo(positions: string[]): Promise<void> {
    if (positions.length === 0) return;
    await this.router.navigate(['/inventory'], { queryParams: { select: positions.join(',') } });
  }
}
