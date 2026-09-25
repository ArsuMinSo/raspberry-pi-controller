import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import {
  IonBackButton, IonBadge, IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonSpinner, IonText, IonTitle,
  IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { ColumnMenuComponent } from '../core/column-menu.component';
import { errorMessage } from '../core/errors';
import { dateTime, statusColor } from '../core/format';
import { LogEntry, PiDetail } from '../core/models';
import { TableSort, compareDates, compareStrings } from '../core/table-sort';
import { ColumnDef, TableColumns } from '../core/table-columns';

type SortColumn = 'when' | 'action' | 'status' | 'user';
type Col = SortColumn | 'command';

const COLUMNS: ColumnDef<Col>[] = [
  { key: 'when', label: 'When', defaultWidth: 150 },
  { key: 'action', label: 'Action', defaultWidth: 100 },
  { key: 'status', label: 'Status', defaultWidth: 100 },
  { key: 'user', label: 'User', defaultWidth: 110 },
  { key: 'command', label: 'Command', defaultWidth: 220 },
];

@Component({
  selector: 'app-pi-detail',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-back-button defaultHref="/inventory"></ion-back-button></ion-buttons>
        <ion-title>Pi {{ position() }}</ion-title>
        @if (canAct) {
          <ion-buttons slot="end">
            <ion-button (click)="healthCheck()" [disabled]="starting() || !pi()">
              <ion-icon slot="start" name="pulse-outline"></ion-icon> Health check
            </ion-button>
          </ion-buttons>
        }
      </ion-toolbar>
    </ion-header>
    <ion-content class="ion-padding">
      <div class="page-narrow">
        @if (error()) { <ion-text color="danger"><p>{{ error() }}</p></ion-text> }
        @if (pi(); as p) {
          <table class="data details">
            <tbody>
              <tr><th>Status</th><td><ion-badge [color]="statusColor(p.status)">{{ p.status }}</ion-badge></td></tr>
              <tr><th>Hostname</th><td>{{ p.hostname ?? '—' }}</td></tr>
              <tr><th>IP</th><td>{{ p.ip ?? '—' }}</td></tr>
              <tr><th>MAC</th><td>{{ p.mac }}</td></tr>
              <tr><th>Pi version</th><td>{{ p.pi_version ?? '—' }}</td></tr>
              <tr><th>Serial</th><td>{{ p.serial ?? '—' }}</td></tr>
              <tr><th>Tags</th><td class="wrap">{{ p.tags.join(', ') || '—' }}</td></tr>
              <tr><th>Last seen</th><td>{{ dateTime(p.last_seen) }}</td></tr>
              <tr><th>Added</th><td>{{ dateTime(p.created_at) }}</td></tr>
            </tbody>
          </table>
        } @else if (!error()) {
          <div class="ion-text-center"><ion-spinner></ion-spinner></div>
        }

        @if (canAct) {
        <div class="section-head">
          <h3>Recent actions</h3>
          <app-column-menu [cols]="cols" triggerId="pi-detail-cols"></app-column-menu>
        </div>
        @if (actions().length === 0) {
          <p class="muted">None yet.</p>
        } @else {
          <div class="table-scroll">
            <table class="data">
              <thead>
                <tr>
                  @if (cols.isVisible('when')) {
                    <th (click)="sort.sortBy('when')" class="sortable" [style.width.px]="cols.width('when')">
                      When{{ sort.indicator('when') }}<span class="resize-handle" (pointerdown)="cols.startResize('when', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('action')) {
                    <th (click)="sort.sortBy('action')" class="sortable" [style.width.px]="cols.width('action')">
                      Action{{ sort.indicator('action') }}<span class="resize-handle" (pointerdown)="cols.startResize('action', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('status')) {
                    <th (click)="sort.sortBy('status')" class="sortable" [style.width.px]="cols.width('status')">
                      Status{{ sort.indicator('status') }}<span class="resize-handle" (pointerdown)="cols.startResize('status', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('user')) {
                    <th (click)="sort.sortBy('user')" class="sortable" [style.width.px]="cols.width('user')">
                      User{{ sort.indicator('user') }}<span class="resize-handle" (pointerdown)="cols.startResize('user', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('command')) {
                    <th [style.width.px]="cols.width('command')">
                      Command<span class="resize-handle" (pointerdown)="cols.startResize('command', $event)"></span>
                    </th>
                  }
                </tr>
              </thead>
              <tbody>
                @for (a of sortedActions(); track a.id) {
                  <tr class="clickable" [routerLink]="['/actions', a.id]">
                    @if (cols.isVisible('when')) { <td>{{ dateTime(a.timestamp) }}</td> }
                    @if (cols.isVisible('action')) { <td>{{ a.action }}</td> }
                    @if (cols.isVisible('status')) { <td><ion-badge [color]="statusColor(a.status)">{{ a.status }}</ion-badge></td> }
                    @if (cols.isVisible('user')) { <td>{{ a.user }}</td> }
                    @if (cols.isVisible('command')) { <td class="wrap">{{ a.command ?? '' }}</td> }
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
        }
      </div>
    </ion-content>
  `,
  styles: [`
    table.details th { width: 10rem; }
    th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
    th.sortable:hover { opacity: 0.7; }
    .section-head { display: flex; align-items: center; justify-content: space-between; }
  `],
  imports: [
    RouterLink, IonHeader, IonToolbar, IonButtons, IonBackButton, IonTitle, IonButton, IonIcon, IonContent,
    IonText, IonBadge, IonSpinner, ColumnMenuComponent,
  ],
})
export class PiDetailPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);

  /** Route param :position */
  readonly position = input.required<string>();

  readonly canAct = this.auth.can('operator');
  readonly statusColor = statusColor;
  readonly dateTime = dateTime;

  readonly pi = signal<PiDetail | null>(null);
  readonly actions = signal<LogEntry[]>([]);
  readonly error = signal<string | null>(null);
  readonly starting = signal(false);
  // No default column: preserve the API's own order (newest first) until the user clicks a header.
  readonly sort = new TableSort<LogEntry, SortColumn>({
    when: (a, b) => compareDates(a.timestamp, b.timestamp),
    action: (a, b) => compareStrings(a.action, b.action),
    status: (a, b) => compareStrings(a.status, b.status),
    user: (a, b) => compareStrings(a.user, b.user),
  });
  readonly cols = new TableColumns<Col>(COLUMNS, 'pi-detail-actions');
  readonly sortedActions = computed(() => this.sort.apply(this.actions()));

  async ngOnInit(): Promise<void> {
    try {
      const [pi, actions] = await Promise.all([
        firstValueFrom(this.api.pi(this.position())),
        // Activity log is operator+ — viewers don't see recent actions
        this.canAct ? firstValueFrom(this.api.logs({ pi: this.position(), limit: 20 })) : Promise.resolve([]),
      ]);
      this.pi.set(pi);
      this.actions.set(actions);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  async healthCheck(): Promise<void> {
    this.starting.set(true);
    try {
      const queued = await firstValueFrom(this.api.healthCheck([this.position()]));
      await this.router.navigate(['/actions', queued.action_id]);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.starting.set(false);
    }
  }
}
