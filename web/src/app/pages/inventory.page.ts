import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
  AlertController, IonBadge, IonButton, IonButtons, IonCard, IonCardContent, IonCheckbox, IonChip, IonContent,
  IonHeader, IonIcon, IonItem, IonLabel, IonMenuButton, IonRange, IonRefresher, IonRefresherContent, IonSearchbar,
  IonSegment, IonSegmentButton, IonSpinner, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { Observable, firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime, pct, statusColor, temp } from '../core/format';
import { ColumnMenuComponent } from '../core/column-menu.component';
import { ActionQueued, FleetSummary, PiSummary } from '../core/models';
import { comparePositions } from '../core/sort';
import { TableSort, compareDates, compareIps, compareStrings } from '../core/table-sort';
import { ColumnDef, TableColumns } from '../core/table-columns';

type StatusFilter = 'all' | 'reachable' | 'unreachable';
type SortColumn = 'position' | 'hostname' | 'ip' | 'status' | 'cpu' | 'ram' | 'temp' | 'pi' | 'seen';
type Col = SortColumn | 'tags';

const COLUMNS: ColumnDef<Col>[] = [
  { key: 'position', label: 'Position', defaultWidth: 100 },
  { key: 'hostname', label: 'Hostname', defaultWidth: 140 },
  { key: 'ip', label: 'IP', defaultWidth: 120 },
  { key: 'status', label: 'Status', defaultWidth: 110 },
  { key: 'cpu', label: 'CPU 1m', defaultWidth: 90 },
  { key: 'ram', label: 'RAM', defaultWidth: 90 },
  { key: 'temp', label: 'Temp', defaultWidth: 90 },
  { key: 'pi', label: 'Pi', defaultWidth: 70 },
  { key: 'tags', label: 'Tags', defaultWidth: 160 },
  { key: 'seen', label: 'Last seen', defaultWidth: 160 },
];

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
      <ion-toolbar>
        <ion-buttons slot="start">
          <ion-button fill="outline" (click)="showFilters = !showFilters">
            <ion-icon slot="start" name="funnel-outline"></ion-icon>
            Filters
            @if (filterTags().size + filterVersions().size > 0 || filterStale() || filterMinTemp() > 0 || filterMinCpu() > 0 || filterMinRam() > 0) {
              <ion-badge color="primary">{{ filterTags().size + filterVersions().size + (filterStale() ? 1 : 0) + (filterMinTemp() > 0 ? 1 : 0) + (filterMinCpu() > 0 ? 1 : 0) + (filterMinRam() > 0 ? 1 : 0) }}</ion-badge>
            }
          </ion-button>
          @if (filterTags().size + filterVersions().size > 0 || filterStale() || filterMinTemp() > 0 || filterMinCpu() > 0 || filterMinRam() > 0) {
            <ion-button fill="outline" (click)="clearFilters()">Clear</ion-button>
          }
        </ion-buttons>
        <ion-buttons slot="end">
          <app-column-menu [cols]="cols" triggerId="inventory-cols"></app-column-menu>
        </ion-buttons>
      </ion-toolbar>
      @if (showFilters) {
        <ion-card class="filters-card ion-margin">
          <ion-card-content>
            <div class="filter-section">
              <strong>Tags</strong>
              <div class="filter-chips">
                @for (tag of allTags; track tag) {
                  <ion-chip [outline]="!filterTags().has(tag)" (click)="toggleTag(tag)">{{ tag }}</ion-chip>
                }
              </div>
            </div>
            <div class="filter-section">
              <strong>Pi version</strong>
              <div class="filter-chips">
                @for (v of [2, 3, 4, 5]; track v) {
                  <ion-chip [outline]="!filterVersions().has(v)" (click)="toggleVersion(v)">Pi {{ v }}</ion-chip>
                }
              </div>
            </div>
            <div class="filter-section">
              <ion-item lines="none">
                <ion-checkbox slot="start" [checked]="filterStale()" (ionChange)="filterStale.set($any($event.detail.checked))"></ion-checkbox>
                <ion-label>Not seen &gt; 24h</ion-label>
              </ion-item>
            </div>
            <div class="filter-section">
              <strong>Temp &gt;= {{ filterMinTemp() }}°C</strong>
              <ion-range min="0" max="90" step="5" [value]="filterMinTemp()" (ionChange)="filterMinTemp.set($any($event.detail.value))"></ion-range>
            </div>
            <div class="filter-section">
              <strong>CPU 1m &gt;= {{ filterMinCpu() }}%</strong>
              <ion-range min="0" max="100" step="10" [value]="filterMinCpu()" (ionChange)="filterMinCpu.set($any($event.detail.value))"></ion-range>
            </div>
            <div class="filter-section">
              <strong>RAM &gt;= {{ filterMinRam() }}%</strong>
              <ion-range min="0" max="100" step="10" [value]="filterMinRam()" (ionChange)="filterMinRam.set($any($event.detail.value))"></ion-range>
            </div>
          </ion-card-content>
        </ion-card>
      }
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
                @if (canAct) { <th class="col-check"></th> }
                @if (cols.isVisible('position')) {
                  <th (click)="sort.sortBy('position')" class="sortable" [style.width.px]="cols.width('position')">
                    Position{{ sort.indicator('position') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('position', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('hostname')) {
                  <th (click)="sort.sortBy('hostname')" class="sortable" [style.width.px]="cols.width('hostname')">
                    Hostname{{ sort.indicator('hostname') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('hostname', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('ip')) {
                  <th (click)="sort.sortBy('ip')" class="sortable" [style.width.px]="cols.width('ip')">
                    IP{{ sort.indicator('ip') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('ip', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('status')) {
                  <th (click)="sort.sortBy('status')" class="sortable" [style.width.px]="cols.width('status')">
                    Status{{ sort.indicator('status') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('status', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('cpu')) {
                  <th (click)="sort.sortBy('cpu')" class="sortable" [style.width.px]="cols.width('cpu')">
                    CPU 1m{{ sort.indicator('cpu') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('cpu', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('ram')) {
                  <th (click)="sort.sortBy('ram')" class="sortable" [style.width.px]="cols.width('ram')">
                    RAM{{ sort.indicator('ram') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('ram', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('temp')) {
                  <th (click)="sort.sortBy('temp')" class="sortable" [style.width.px]="cols.width('temp')">
                    Temp{{ sort.indicator('temp') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('temp', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('pi')) {
                  <th (click)="sort.sortBy('pi')" class="sortable" [style.width.px]="cols.width('pi')">
                    Pi{{ sort.indicator('pi') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('pi', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('tags')) {
                  <th [style.width.px]="cols.width('tags')">
                    Tags
                    <span class="resize-handle" (pointerdown)="cols.startResize('tags', $event)"></span>
                  </th>
                }
                @if (cols.isVisible('seen')) {
                  <th (click)="sort.sortBy('seen')" class="sortable" [style.width.px]="cols.width('seen')">
                    Last seen{{ sort.indicator('seen') }}
                    <span class="resize-handle" (pointerdown)="cols.startResize('seen', $event)"></span>
                  </th>
                }
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
                  @if (cols.isVisible('position')) { <td><strong>{{ pi.position }}</strong></td> }
                  @if (cols.isVisible('hostname')) { <td>{{ pi.hostname ?? '—' }}</td> }
                  @if (cols.isVisible('ip')) { <td>{{ pi.ip ?? '—' }}</td> }
                  @if (cols.isVisible('status')) { <td><ion-badge [color]="statusColor(pi.status)">{{ pi.status }}</ion-badge></td> }
                  @if (cols.isVisible('cpu')) { <td>{{ pct(pi.cpu_1m) }}</td> }
                  @if (cols.isVisible('ram')) { <td>{{ pct(pi.mem_percent) }}</td> }
                  @if (cols.isVisible('temp')) { <td>{{ temp(pi.temp_c) }}</td> }
                  @if (cols.isVisible('pi')) { <td>{{ pi.pi_version ?? '—' }}</td> }
                  @if (cols.isVisible('tags')) { <td class="wrap">{{ pi.tags.join(', ') }}</td> }
                  @if (cols.isVisible('seen')) { <td>{{ dateTime(pi.last_seen) }}</td> }
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
    .filters-card { margin: 8px; }
    .filter-section { margin-bottom: 16px; }
    .filter-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    ion-chip { cursor: pointer; }
  `],
  imports: [
    FormsModule, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonButton, IonIcon, IonSearchbar,
    IonSegment, IonSegmentButton, IonLabel, IonContent, IonRefresher, IonRefresherContent, IonText, IonSpinner,
    IonCheckbox, IonBadge, IonCard, IonCardContent, IonChip, IonItem, IonRange, ColumnMenuComponent,
  ],
})
export class InventoryPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
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
  readonly cols = new TableColumns<Col>(COLUMNS, 'inventory');
  readonly sort = new TableSort<PiSummary, SortColumn>({
    position: (a, b) => comparePositions(a.position, b.position),
    hostname: (a, b) => compareStrings(a.hostname, b.hostname),
    ip: (a, b) => compareIps(a.ip, b.ip),
    status: (a, b) => a.status.localeCompare(b.status),
    cpu: (a, b) => (a.cpu_1m ?? 0) - (b.cpu_1m ?? 0),
    ram: (a, b) => (a.mem_percent ?? 0) - (b.mem_percent ?? 0),
    temp: (a, b) => (a.temp_c ?? 0) - (b.temp_c ?? 0),
    pi: (a, b) => (a.pi_version ?? 0) - (b.pi_version ?? 0),
    seen: (a, b) => compareDates(a.last_seen, b.last_seen),
  }, 'position');
  readonly filterTags = signal<Set<string>>(new Set());
  readonly filterVersions = signal<Set<number>>(new Set());
  readonly filterStale = signal(false);
  readonly filterMinTemp = signal(0);
  readonly filterMinCpu = signal(0);
  readonly filterMinRam = signal(0);
  query = '';
  allTags: string[] = [];
  showFilters = false;

  readonly visible = computed(() => {
    const status = this.statusFilter();
    const q = this.search();
    const tags = this.filterTags();
    const versions = this.filterVersions();
    const stale = this.filterStale();
    const minTemp = this.filterMinTemp();
    const minCpu = this.filterMinCpu();
    const minRam = this.filterMinRam();
    const filtered = this.pis()
      .filter((pi) => status === 'all' || pi.status === status)
      .filter((pi) => matchesSearch(pi, q))
      .filter((pi) => tags.size === 0 || pi.tags.some((t) => tags.has(t)))
      .filter((pi) => versions.size === 0 || (pi.pi_version && versions.has(pi.pi_version)))
      .filter((pi) => !stale || !pi.last_seen || new Date(pi.last_seen).getTime() < Date.now() - 24 * 3600 * 1000)
      .filter((pi) => (pi.temp_c ?? 0) >= minTemp)
      .filter((pi) => (pi.cpu_1m ?? 0) >= minCpu)
      .filter((pi) => (pi.mem_percent ?? 0) >= minRam);
    return this.sort.apply(filtered);
  });

  constructor() {
    void this.load();
    // Deep-link from the dashboard: ?status=reachable|unreachable, ?select=pos1,pos2,...
    const params = this.route.snapshot.queryParamMap;
    const status = params.get('status');
    if (status === 'reachable' || status === 'unreachable') {
      this.statusFilter.set(status);
    }
    const select = params.get('select');
    if (select) {
      this.selected.set(new Set(select.split(',').filter((p) => p.length > 0)));
    }
  }

  toggleTag(tag: string): void {
    const next = new Set(this.filterTags());
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    this.filterTags.set(next);
  }

  toggleVersion(v: number): void {
    const next = new Set(this.filterVersions());
    if (next.has(v)) next.delete(v);
    else next.add(v);
    this.filterVersions.set(next);
  }

  clearFilters(): void {
    this.filterTags.set(new Set());
    this.filterVersions.set(new Set());
    this.filterStale.set(false);
    this.filterMinTemp.set(0);
    this.filterMinCpu.set(0);
    this.filterMinRam.set(0);
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
      const tagSet = new Set<string>();
      pis.forEach((pi) => pi.tags.forEach((t) => tagSet.add(t)));
      this.allTags = [...tagSet].sort();
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
