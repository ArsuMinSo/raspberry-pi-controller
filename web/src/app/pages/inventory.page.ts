import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  AlertController, IonBadge, IonButton, IonButtons, IonCheckbox, IonContent, IonHeader, IonIcon, IonMenuButton, IonRefresher,
  IonRefresherContent, IonSearchbar, IonSegment, IonSegmentButton, IonLabel, IonSpinner, IonText, IonTitle,
  IonToolbar,
} from '@ionic/angular';
import { Observable, firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime, pct, statusColor, temp } from '../core/format';
import { ActionQueued, FleetSummary, PiSummary } from '../core/models';
import { comparePositions } from '../core/sort';

type StatusFilter = 'all' | 'reachable' | 'unreachable';
type SortColumn = 'position' | 'hostname' | 'ip' | 'status' | 'cpu' | 'ram' | 'temp' | 'pi' | 'seen';

/** Case-insensitive match on position, hostname, IP, MAC and tags. */
export function matchesSearch(pi: PiSummary, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) {
    return true;
  }
  return [pi.position, pi.hostname, pi.ip, pi.mac, ...pi.tags]
    .some((v) => (v ?? '').toLowerCase().includes(q));
}

@Component({
  selector: 'app-inventory',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Inventory</ion-title>
        <ion-buttons slot="end">
          <ion-button (click)="load()" [disabled]="loading()" aria-label="Refresh">
            <ion-icon slot="icon-only" name="refresh-outline"></ion-icon>
          </ion-button>
        </ion-buttons>
      </ion-toolbar>
      <ion-toolbar>
        <ion-searchbar placeholder="Search position, hostname, IP, MAC, tag" [debounce]="150"
                       [(ngModel)]="query" (ionInput)="queryChanged($event)"></ion-searchbar>
      </ion-toolbar>
      <ion-toolbar>
        <ion-segment [value]="statusFilter()" (ionChange)="statusFilter.set($any($event.detail.value))">
          <ion-segment-button value="all"><ion-label>All ({{ pis().length }})</ion-label></ion-segment-button>
          <ion-segment-button value="reachable"><ion-label>Reachable ({{ count('reachable') }})</ion-label></ion-segment-button>
          <ion-segment-button value="unreachable"><ion-label>Unreachable ({{ count('unreachable') }})</ion-label></ion-segment-button>
        </ion-segment>
      </ion-toolbar>
      @if (canAct) {
        <ion-toolbar>
          <ion-buttons slot="start">
            <ion-button (click)="selectVisible()" [disabled]="visible().length === 0">Select shown</ion-button>
            <ion-button (click)="selected.set(emptySet())" [disabled]="selected().size === 0">Clear</ion-button>
          </ion-buttons>
          <ion-buttons slot="end">
            <ion-button fill="solid" color="primary" (click)="healthCheck()" [disabled]="selected().size === 0 || starting()">
              <ion-icon slot="start" name="pulse-outline"></ion-icon>
              Health check ({{ selected().size }})
            </ion-button>
            <ion-button fill="outline" (click)="diagnostics()" [disabled]="selected().size === 0 || starting()">
              Diagnostics
            </ion-button>
            <ion-button fill="outline" color="danger" (click)="reboot()" [disabled]="selected().size === 0 || starting()">
              Reboot
            </ion-button>
          </ion-buttons>
        </ion-toolbar>
      }
    </ion-header>

    <ion-content>
      <ion-refresher slot="fixed" (ionRefresh)="refresh($event)">
        <ion-refresher-content></ion-refresher-content>
      </ion-refresher>

      @if (error()) {
        <ion-text color="danger"><p class="ion-padding">{{ error() }}</p></ion-text>
      }
      @if (summary(); as f) {
        <div class="summary">
          <span><strong>{{ f.total }}</strong> Pis</span>
          <span><ion-badge color="success">{{ f.reachable }}</ion-badge> reachable</span>
          <span><ion-badge [color]="f.unreachable ? 'danger' : 'medium'">{{ f.unreachable }}</ion-badge> unreachable</span>
          @if (f.stale.length) {
            <span class="clickable" (click)="selectPositions(f.stale)" [title]="'Click to select: ' + f.stale.join(', ')">
              <ion-badge color="warning">{{ f.stale.length }}</ion-badge> not seen &gt; {{ f.stale_hours }} h</span>
          }
          @if (f.never_seen.length) {
            <span [title]="f.never_seen.join(', ')"><ion-badge color="medium">{{ f.never_seen.length }}</ion-badge> never seen</span>
          }
          @if (f.hottest[0]; as hot) {
            <span>hottest <strong>{{ hot.position }}</strong> {{ temp(hot.value) }}</span>
          }
          <span class="muted">last health check {{ dateTime(f.last_health_check_at) }}</span>
        </div>
      }
      @if (loading() && pis().length === 0) {
        <div class="ion-padding ion-text-center"><ion-spinner></ion-spinner></div>
      } @else if (visible().length === 0) {
        <p class="ion-padding muted">No Pis match.</p>
      } @else {
        <div class="table-scroll">
          <table class="data">
            <thead>
              <tr>
                @if (canAct) { <th></th> }
                <th (click)="sortBy('position')" class="sortable">Position{{ sortIndicator('position') }}</th>
                <th (click)="sortBy('hostname')" class="sortable">Hostname{{ sortIndicator('hostname') }}</th>
                <th (click)="sortBy('ip')" class="sortable">IP{{ sortIndicator('ip') }}</th>
                <th (click)="sortBy('status')" class="sortable">Status{{ sortIndicator('status') }}</th>
                <th (click)="sortBy('cpu')" class="sortable">CPU 1m{{ sortIndicator('cpu') }}</th>
                <th (click)="sortBy('ram')" class="sortable">RAM{{ sortIndicator('ram') }}</th>
                <th (click)="sortBy('temp')" class="sortable">Temp{{ sortIndicator('temp') }}</th>
                <th (click)="sortBy('pi')" class="sortable">Pi{{ sortIndicator('pi') }}</th>
                <th>Tags</th>
                <th (click)="sortBy('seen')" class="sortable">Last seen{{ sortIndicator('seen') }}</th>
              </tr>
            </thead>
            <tbody>
              @for (pi of visible(); track pi.mac) {
                <tr class="clickable" (click)="open(pi)">
                  @if (canAct) {
                    <td (click)="$event.stopPropagation()">
                      <ion-checkbox [checked]="selected().has(pi.position)" (ionChange)="toggle(pi.position)"
                                    [attr.aria-label]="'Select ' + pi.position"></ion-checkbox>
                    </td>
                  }
                  <td><strong>{{ pi.position }}</strong></td>
                  <td>{{ pi.hostname ?? '—' }}</td>
                  <td>{{ pi.ip ?? '—' }}</td>
                  <td><ion-badge [color]="statusColor(pi.status)">{{ pi.status }}</ion-badge></td>
                  <td>{{ pct(pi.cpu_1m) }}</td>
                  <td>{{ pct(pi.mem_percent) }}</td>
                  <td>{{ temp(pi.temp_c) }}</td>
                  <td>{{ pi.pi_version ?? '—' }}</td>
                  <td class="wrap">{{ pi.tags.join(', ') }}</td>
                  <td>{{ dateTime(pi.last_seen) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </ion-content>
  `,
  styles: [`
    th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
    th.sortable:hover { opacity: 0.7; }
  `],
  imports: [
    FormsModule, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonButton, IonIcon, IonSearchbar,
    IonSegment, IonSegmentButton, IonLabel, IonContent, IonRefresher, IonRefresherContent, IonText, IonSpinner,
    IonCheckbox, IonBadge,
  ],
})
export class InventoryPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly alerts = inject(AlertController);

  readonly canAct = this.auth.can('operator');
  readonly statusColor = statusColor;
  readonly pct = pct;
  readonly temp = temp;
  readonly dateTime = dateTime;

  readonly pis = signal<PiSummary[]>([]);
  readonly summary = signal<FleetSummary | null>(null);
  readonly loading = signal(false);
  readonly starting = signal(false);
  readonly error = signal<string | null>(null);
  readonly statusFilter = signal<StatusFilter>('all');
  readonly search = signal('');
  readonly selected = signal<Set<string>>(new Set());
  readonly sortColumn = signal<SortColumn>('position');
  readonly sortDir = signal<'asc' | 'desc'>('asc');
  query = '';

  readonly visible = computed(() => {
    const status = this.statusFilter();
    const q = this.search();
    const col = this.sortColumn();
    const dir = this.sortDir();
    const filtered = this.pis()
      .filter((pi) => status === 'all' || pi.status === status)
      .filter((pi) => matchesSearch(pi, q));
    filtered.sort((a, b) => this.compare(a, b, col) * (dir === 'desc' ? -1 : 1));
    return filtered;
  });

  constructor() {
    void this.load();
  }

  private compare(a: PiSummary, b: PiSummary, col: SortColumn): number {
    switch (col) {
      case 'position': return comparePositions(a.position, b.position);
      case 'hostname': return (a.hostname ?? '').localeCompare(b.hostname ?? '');
      case 'ip': return this.compareIps(a.ip, b.ip);
      case 'status': return a.status.localeCompare(b.status);
      case 'cpu': return (a.cpu_1m ?? 0) - (b.cpu_1m ?? 0);
      case 'ram': return (a.mem_percent ?? 0) - (b.mem_percent ?? 0);
      case 'temp': return (a.temp_c ?? 0) - (b.temp_c ?? 0);
      case 'pi': return (a.pi_version ?? 0) - (b.pi_version ?? 0);
      case 'seen': return new Date(a.last_seen ?? 0).getTime() - new Date(b.last_seen ?? 0).getTime();
      default: return 0;
    }
  }

  private compareIps(a: string | null, b: string | null): number {
    if (!a && !b) return 0;
    if (!a) return -1;
    if (!b) return 1;
    const aParts = a.split('.').map((x) => parseInt(x, 10));
    const bParts = b.split('.').map((x) => parseInt(x, 10));
    for (let i = 0; i < 4; i++) {
      if (aParts[i] !== bParts[i]) return aParts[i] - bParts[i];
    }
    return 0;
  }

  sortBy(col: SortColumn): void {
    if (this.sortColumn() === col) {
      this.sortDir.set(this.sortDir() === 'asc' ? 'desc' : 'asc');
    } else {
      this.sortColumn.set(col);
      this.sortDir.set('asc');
    }
  }

  sortIndicator(col: SortColumn): string {
    if (this.sortColumn() !== col) return '';
    return this.sortDir() === 'asc' ? ' ▲' : ' ▼';
  }

  emptySet(): Set<string> {
    return new Set();
  }

  count(status: string): number {
    return this.pis().filter((pi) => pi.status === status).length;
  }

  queryChanged(event: Event): void {
    this.search.set(((event as CustomEvent).detail?.value as string | null) ?? '');
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [pis, summary] = await Promise.all([
        firstValueFrom(this.api.listPis()),
        firstValueFrom(this.api.fleetSummary()).catch(() => null), // optional — list still shows without it
      ]);
      this.pis.set(pis);
      this.summary.set(summary);
      const known = new Set(this.pis().map((p) => p.position));
      this.selected.set(new Set([...this.selected()].filter((p) => known.has(p))));
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.loading.set(false);
    }
  }

  async refresh(event: Event): Promise<void> {
    await this.load();
    await (event.target as HTMLIonRefresherElement).complete();
  }

  toggle(position: string): void {
    const next = new Set(this.selected());
    if (next.has(position)) {
      next.delete(position);
    } else {
      next.add(position);
    }
    this.selected.set(next);
  }

  selectVisible(): void {
    this.selected.set(new Set([...this.selected(), ...this.visible().map((p) => p.position)]));
  }

  open(pi: PiSummary): void {
    void this.router.navigate(['/pi', pi.position]);
  }

  /** Select these positions (e.g. the stale ones) for an action. */
  selectPositions(positions: string[]): void {
    this.statusFilter.set('all');
    this.selected.set(new Set(positions));
  }

  healthCheck(): Promise<void> {
    return this.start((positions) => this.api.healthCheck(positions));
  }

  diagnostics(): Promise<void> {
    return this.start((positions) => this.api.diagnostics(positions));
  }

  async reboot(): Promise<void> {
    const positions = [...this.selected()].sort(comparePositions);
    const alert = await this.alerts.create({
      header: `Reboot ${positions.length} Pi${positions.length === 1 ? '' : 's'}?`,
      message: `Their screens go dark for about a minute: ${positions.slice(0, 20).join(', ')}` +
        (positions.length > 20 ? ` … (+${positions.length - 20})` : ''),
      buttons: [{ text: 'Cancel', role: 'cancel' }, { text: 'Reboot', role: 'confirm' }],
    });
    await alert.present();
    if ((await alert.onDidDismiss()).role === 'confirm') {
      await this.start((p) => this.api.reboot(p));
    }
  }

  private async start(fn: (positions: string[]) => Observable<ActionQueued>): Promise<void> {
    this.starting.set(true);
    this.error.set(null);
    try {
      const positions = [...this.selected()].sort(comparePositions);
      const queued = await firstValueFrom(fn(positions));
      await this.router.navigate(['/actions', queued.action_id]);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.starting.set(false);
    }
  }
}
