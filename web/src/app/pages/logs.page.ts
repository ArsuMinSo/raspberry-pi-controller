import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import {
  IonBadge, IonButton, IonButtons, IonContent, IonHeader, IonInput, IonItem, IonLabel, IonMenuButton,
  IonSegment, IonSegmentButton, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { errorMessage } from '../core/errors';
import { dateTime, statusColor } from '../core/format';
import { AuditEvent, LogEntry } from '../core/models';
import { TableSort, compareDates, compareStrings } from '../core/table-sort';

type Tab = 'actions' | 'events';
type ActionSortColumn = 'when' | 'user' | 'action' | 'status' | 'duration';
type EventSortColumn = 'when' | 'user' | 'event' | 'target' | 'ip';

@Component({
  selector: 'app-logs',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Activity log</ion-title>
      </ion-toolbar>
      <ion-toolbar>
        <ion-segment [value]="tab()" (ionChange)="switchTab($any($event.detail.value))">
          <ion-segment-button value="actions"><ion-label>Pi actions</ion-label></ion-segment-button>
          <ion-segment-button value="events"><ion-label>Logins &amp; changes</ion-label></ion-segment-button>
        </ion-segment>
      </ion-toolbar>
    </ion-header>
    <ion-content>
      <form class="filters" (ngSubmit)="load()">
        <ion-item><ion-input label="User" labelPlacement="stacked" name="user" [(ngModel)]="user"></ion-input></ion-item>
        @if (tab() === 'actions') {
          <ion-item><ion-input label="Pi position" labelPlacement="stacked" name="pi" [(ngModel)]="pi"></ion-input></ion-item>
        } @else {
          <ion-item><ion-input label="Event" labelPlacement="stacked" name="event" placeholder="e.g. login_failed"
                               [(ngModel)]="event"></ion-input></ion-item>
        }
        <ion-button type="submit">Filter</ion-button>
      </form>

      @if (error()) { <ion-text color="danger"><p class="ion-padding">{{ error() }}</p></ion-text> }

      <div class="table-scroll">
        @if (tab() === 'actions') {
          <table class="data">
            <thead>
              <tr>
                <th (click)="actionSort.sortBy('when')" class="sortable">When{{ actionSort.indicator('when') }}</th>
                <th (click)="actionSort.sortBy('user')" class="sortable">User{{ actionSort.indicator('user') }}</th>
                <th (click)="actionSort.sortBy('action')" class="sortable">Action{{ actionSort.indicator('action') }}</th>
                <th (click)="actionSort.sortBy('status')" class="sortable">Status{{ actionSort.indicator('status') }}</th>
                <th>Pis</th>
                <th>Command</th>
                <th (click)="actionSort.sortBy('duration')" class="sortable">Duration{{ actionSort.indicator('duration') }}</th>
              </tr>
            </thead>
            <tbody>
              @for (a of sortedActions(); track a.id) {
                <tr class="clickable" [routerLink]="['/actions', a.id]">
                  <td>{{ dateTime(a.timestamp) }}</td>
                  <td>{{ a.user }}</td>
                  <td>{{ a.action }}</td>
                  <td><ion-badge [color]="statusColor(a.status)">{{ a.status }}</ion-badge></td>
                  <td class="wrap">{{ summarise(a.pis_selected) }}</td>
                  <td class="wrap">{{ a.command ?? '' }}</td>
                  <td>{{ a.duration_ms !== null ? (a.duration_ms / 1000).toFixed(1) + ' s' : '' }}</td>
                </tr>
              } @empty {
                <tr><td colspan="7" class="muted">No entries.</td></tr>
              }
            </tbody>
          </table>
        } @else {
          <table class="data">
            <thead>
              <tr>
                <th (click)="eventSort.sortBy('when')" class="sortable">When{{ eventSort.indicator('when') }}</th>
                <th (click)="eventSort.sortBy('user')" class="sortable">User{{ eventSort.indicator('user') }}</th>
                <th (click)="eventSort.sortBy('event')" class="sortable">Event{{ eventSort.indicator('event') }}</th>
                <th (click)="eventSort.sortBy('target')" class="sortable">Target{{ eventSort.indicator('target') }}</th>
                <th>Details</th>
                <th (click)="eventSort.sortBy('ip')" class="sortable">IP{{ eventSort.indicator('ip') }}</th>
              </tr>
            </thead>
            <tbody>
              @for (e of sortedEvents(); track e.id) {
                <tr>
                  <td>{{ dateTime(e.ts) }}</td>
                  <td>{{ e.username }}</td>
                  <td>{{ e.event }}</td>
                  <td>{{ e.target ?? '' }}</td>
                  <td class="wrap"><code>{{ e.details ? json(e.details) : '' }}</code></td>
                  <td>{{ e.ip ?? '' }}</td>
                </tr>
              } @empty {
                <tr><td colspan="6" class="muted">No entries.</td></tr>
              }
            </tbody>
          </table>
        }
      </div>
    </ion-content>
  `,
  styles: [`
    .filters { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px; padding: 8px 16px; }
    .filters ion-item { flex: 1 1 12rem; }
    code { font-size: 0.8rem; }
    th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
    th.sortable:hover { opacity: 0.7; }
  `],
  imports: [
    FormsModule, RouterLink, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonSegment,
    IonSegmentButton, IonLabel, IonContent, IonItem, IonInput, IonButton, IonText, IonBadge,
  ],
})
export class LogsPage {
  private readonly api = inject(ApiService);

  readonly statusColor = statusColor;
  readonly dateTime = dateTime;

  readonly tab = signal<Tab>('actions');
  readonly actions = signal<LogEntry[]>([]);
  readonly events = signal<AuditEvent[]>([]);
  readonly error = signal<string | null>(null);
  // No default column: preserve the API's own order (newest first) until the user clicks a header.
  readonly actionSort = new TableSort<LogEntry, ActionSortColumn>({
    when: (a, b) => compareDates(a.timestamp, b.timestamp),
    user: (a, b) => compareStrings(a.user, b.user),
    action: (a, b) => compareStrings(a.action, b.action),
    status: (a, b) => compareStrings(a.status, b.status),
    duration: (a, b) => (a.duration_ms ?? 0) - (b.duration_ms ?? 0),
  });
  readonly eventSort = new TableSort<AuditEvent, EventSortColumn>({
    when: (a, b) => compareDates(a.ts, b.ts),
    user: (a, b) => compareStrings(a.username, b.username),
    event: (a, b) => compareStrings(a.event, b.event),
    target: (a, b) => compareStrings(a.target, b.target),
    ip: (a, b) => compareStrings(a.ip, b.ip),
  });
  readonly sortedActions = computed(() => this.actionSort.apply(this.actions()));
  readonly sortedEvents = computed(() => this.eventSort.apply(this.events()));
  user = '';
  pi = '';
  event = '';

  constructor() {
    void this.load();
  }

  switchTab(tab: Tab): void {
    this.tab.set(tab);
    void this.load();
  }

  async load(): Promise<void> {
    this.error.set(null);
    try {
      if (this.tab() === 'actions') {
        this.actions.set(await firstValueFrom(this.api.logs({ user: this.user.trim(), pi: this.pi.trim() })));
      } else {
        this.events.set(await firstValueFrom(this.api.events({ user: this.user.trim(), event: this.event.trim() })));
      }
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  summarise(pis: string[]): string {
    return pis.length <= 5 ? pis.join(', ') : `${pis.slice(0, 5).join(', ')} … (+${pis.length - 5})`;
  }

  json(value: unknown): string {
    return JSON.stringify(value);
  }
}
