import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  IonBadge, IonButton, IonButtons, IonCheckbox, IonContent, IonHeader, IonIcon, IonMenuButton, IonRefresher,
  IonRefresherContent, IonSearchbar, IonSegment, IonSegmentButton, IonLabel, IonSpinner, IonText, IonTitle,
  IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime, pct, statusColor, temp } from '../core/format';
import { PiSummary } from '../core/models';
import { comparePositions } from '../core/sort';

type StatusFilter = 'all' | 'reachable' | 'unreachable';

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
                <th>Position</th><th>Hostname</th><th>IP</th><th>Status</th>
                <th>CPU 1m</th><th>RAM</th><th>Temp</th><th>Pi</th><th>Tags</th><th>Last seen</th>
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

  readonly canAct = this.auth.can('operator');
  readonly statusColor = statusColor;
  readonly pct = pct;
  readonly temp = temp;
  readonly dateTime = dateTime;

  readonly pis = signal<PiSummary[]>([]);
  readonly loading = signal(false);
  readonly starting = signal(false);
  readonly error = signal<string | null>(null);
  readonly statusFilter = signal<StatusFilter>('all');
  readonly search = signal('');
  readonly selected = signal<Set<string>>(new Set());
  query = '';

  readonly visible = computed(() => {
    const status = this.statusFilter();
    const q = this.search();
    return this.pis()
      .filter((pi) => status === 'all' || pi.status === status)
      .filter((pi) => matchesSearch(pi, q))
      .sort((a, b) => comparePositions(a.position, b.position));
  });

  constructor() {
    void this.load();
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
      this.pis.set(await firstValueFrom(this.api.listPis()));
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

  async healthCheck(): Promise<void> {
    this.starting.set(true);
    this.error.set(null);
    try {
      const positions = [...this.selected()].sort(comparePositions);
      const queued = await firstValueFrom(this.api.healthCheck(positions));
      await this.router.navigate(['/actions', queued.action_id]);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.starting.set(false);
    }
  }
}
