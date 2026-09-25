import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import {
  IonBadge, IonButton, IonButtons, IonContent, IonHeader, IonInput, IonItem, IonLabel, IonMenuButton,
  IonSegment, IonSegmentButton, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { ColumnMenuComponent } from '../core/column-menu.component';
import { errorMessage } from '../core/errors';
import { dateTime, statusColor } from '../core/format';
import { AuditEvent, LogEntry } from '../core/models';
import { TableSort, compareDates, compareStrings } from '../core/table-sort';
import { ColumnDef, TableColumns } from '../core/table-columns';

type Tab = 'actions' | 'events';
type ActionSortColumn = 'when' | 'user' | 'action' | 'status' | 'duration';
type ActionCol = ActionSortColumn | 'pis' | 'command';
type EventSortColumn = 'when' | 'user' | 'event' | 'target' | 'ip';
type EventCol = EventSortColumn | 'details';

const ACTION_COLUMNS: ColumnDef<ActionCol>[] = [
  { key: 'when', label: 'When', defaultWidth: 150 },
  { key: 'user', label: 'User', defaultWidth: 110 },
  { key: 'action', label: 'Action', defaultWidth: 100 },
  { key: 'status', label: 'Status', defaultWidth: 100 },
  { key: 'pis', label: 'Pis', defaultWidth: 160 },
  { key: 'command', label: 'Command', defaultWidth: 200 },
  { key: 'duration', label: 'Duration', defaultWidth: 90 },
];

const EVENT_COLUMNS: ColumnDef<EventCol>[] = [
  { key: 'when', label: 'When', defaultWidth: 150 },
  { key: 'user', label: 'User', defaultWidth: 110 },
  { key: 'event', label: 'Event', defaultWidth: 130 },
  { key: 'target', label: 'Target', defaultWidth: 130 },
  { key: 'details', label: 'Details', defaultWidth: 200 },
  { key: 'ip', label: 'IP', defaultWidth: 120 },
];

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
        <ion-buttons slot="end">
          @if (tab() === 'actions') {
            <app-column-menu [cols]="actionCols" triggerId="logs-actions-cols"></app-column-menu>
          } @else {
            <app-column-menu [cols]="eventCols" triggerId="logs-events-cols"></app-column-menu>
          }
        </ion-buttons>
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
                @if (actionCols.isVisible('when')) {
                  <th (click)="actionSort.sortBy('when')" class="sortable" [style.width.px]="actionCols.width('when')">
                    When{{ actionSort.indicator('when') }}<span class="resize-handle" (pointerdown)="actionCols.startResize('when', $event)"></span>
                  </th>
                }
                @if (actionCols.isVisible('user')) {
                  <th (click)="actionSort.sortBy('user')" class="sortable" [style.width.px]="actionCols.width('user')">
                    User{{ actionSort.indicator('user') }}<span class="resize-handle" (pointerdown)="actionCols.startResize('user', $event)"></span>
                  </th>
                }
                @if (actionCols.isVisible('action')) {
                  <th (click)="actionSort.sortBy('action')" class="sortable" [style.width.px]="actionCols.width('action')">
                    Action{{ actionSort.indicator('action') }}<span class="resize-handle" (pointerdown)="actionCols.startResize('action', $event)"></span>
                  </th>
                }
                @if (actionCols.isVisible('status')) {
                  <th (click)="actionSort.sortBy('status')" class="sortable" [style.width.px]="actionCols.width('status')">
                    Status{{ actionSort.indicator('status') }}<span class="resize-handle" (pointerdown)="actionCols.startResize('status', $event)"></span>
                  </th>
                }
                @if (actionCols.isVisible('pis')) {
                  <th [style.width.px]="actionCols.width('pis')">
                    Pis<span class="resize-handle" (pointerdown)="actionCols.startResize('pis', $event)"></span>
                  </th>
                }
                @if (actionCols.isVisible('command')) {
                  <th [style.width.px]="actionCols.width('command')">
                    Command<span class="resize-handle" (pointerdown)="actionCols.startResize('command', $event)"></span>
                  </th>
                }
                @if (actionCols.isVisible('duration')) {
                  <th (click)="actionSort.sortBy('duration')" class="sortable" [style.width.px]="actionCols.width('duration')">
                    Duration{{ actionSort.indicator('duration') }}<span class="resize-handle" (pointerdown)="actionCols.startResize('duration', $event)"></span>
                  </th>
                }
              </tr>
            </thead>
            <tbody>
              @for (a of sortedActions(); track a.id) {
                <tr class="clickable" [routerLink]="['/actions', a.id]">
                  @if (actionCols.isVisible('when')) { <td>{{ dateTime(a.timestamp) }}</td> }
                  @if (actionCols.isVisible('user')) { <td>{{ a.user }}</td> }
                  @if (actionCols.isVisible('action')) { <td>{{ a.action }}</td> }
                  @if (actionCols.isVisible('status')) { <td><ion-badge [color]="statusColor(a.status)">{{ a.status }}</ion-badge></td> }
                  @if (actionCols.isVisible('pis')) { <td class="wrap">{{ summarise(a.pis_selected) }}</td> }
                  @if (actionCols.isVisible('command')) { <td class="wrap">{{ a.command ?? '' }}</td> }
                  @if (actionCols.isVisible('duration')) { <td>{{ a.duration_ms !== null ? (a.duration_ms / 1000).toFixed(1) + ' s' : '' }}</td> }
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
                @if (eventCols.isVisible('when')) {
                  <th (click)="eventSort.sortBy('when')" class="sortable" [style.width.px]="eventCols.width('when')">
                    When{{ eventSort.indicator('when') }}<span class="resize-handle" (pointerdown)="eventCols.startResize('when', $event)"></span>
                  </th>
                }
                @if (eventCols.isVisible('user')) {
                  <th (click)="eventSort.sortBy('user')" class="sortable" [style.width.px]="eventCols.width('user')">
                    User{{ eventSort.indicator('user') }}<span class="resize-handle" (pointerdown)="eventCols.startResize('user', $event)"></span>
                  </th>
                }
                @if (eventCols.isVisible('event')) {
                  <th (click)="eventSort.sortBy('event')" class="sortable" [style.width.px]="eventCols.width('event')">
                    Event{{ eventSort.indicator('event') }}<span class="resize-handle" (pointerdown)="eventCols.startResize('event', $event)"></span>
                  </th>
                }
                @if (eventCols.isVisible('target')) {
                  <th (click)="eventSort.sortBy('target')" class="sortable" [style.width.px]="eventCols.width('target')">
                    Target{{ eventSort.indicator('target') }}<span class="resize-handle" (pointerdown)="eventCols.startResize('target', $event)"></span>
                  </th>
                }
                @if (eventCols.isVisible('details')) {
                  <th [style.width.px]="eventCols.width('details')">
                    Details<span class="resize-handle" (pointerdown)="eventCols.startResize('details', $event)"></span>
                  </th>
                }
                @if (eventCols.isVisible('ip')) {
                  <th (click)="eventSort.sortBy('ip')" class="sortable" [style.width.px]="eventCols.width('ip')">
                    IP{{ eventSort.indicator('ip') }}<span class="resize-handle" (pointerdown)="eventCols.startResize('ip', $event)"></span>
                  </th>
                }
              </tr>
            </thead>
            <tbody>
              @for (e of sortedEvents(); track e.id) {
                <tr>
                  @if (eventCols.isVisible('when')) { <td>{{ dateTime(e.ts) }}</td> }
                  @if (eventCols.isVisible('user')) { <td>{{ e.username }}</td> }
                  @if (eventCols.isVisible('event')) { <td>{{ e.event }}</td> }
                  @if (eventCols.isVisible('target')) { <td>{{ e.target ?? '' }}</td> }
                  @if (eventCols.isVisible('details')) { <td class="wrap"><code>{{ e.details ? json(e.details) : '' }}</code></td> }
                  @if (eventCols.isVisible('ip')) { <td>{{ e.ip ?? '' }}</td> }
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
    IonSegmentButton, IonLabel, IonContent, IonItem, IonInput, IonButton, IonText, IonBadge, ColumnMenuComponent,
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
  readonly actionCols = new TableColumns<ActionCol>(ACTION_COLUMNS, 'logs-actions');
  readonly eventCols = new TableColumns<EventCol>(EVENT_COLUMNS, 'logs-events');
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
