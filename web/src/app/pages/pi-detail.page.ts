import { Component, OnInit, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import {
  IonBackButton, IonBadge, IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonSpinner, IonText, IonTitle,
  IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime, statusColor } from '../core/format';
import { LogEntry, PiDetail } from '../core/models';

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

        <h3>Recent actions</h3>
        @if (actions().length === 0) {
          <p class="muted">None yet.</p>
        } @else {
          <div class="table-scroll">
            <table class="data">
              <thead><tr><th>When</th><th>Action</th><th>Status</th><th>User</th><th>Command</th></tr></thead>
              <tbody>
                @for (a of actions(); track a.id) {
                  <tr class="clickable" [routerLink]="['/actions', a.id]">
                    <td>{{ dateTime(a.timestamp) }}</td>
                    <td>{{ a.action }}</td>
                    <td><ion-badge [color]="statusColor(a.status)">{{ a.status }}</ion-badge></td>
                    <td>{{ a.user }}</td>
                    <td class="wrap">{{ a.command ?? '' }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </div>
    </ion-content>
  `,
  styles: [`table.details th { width: 10rem; }`],
  imports: [
    RouterLink, IonHeader, IonToolbar, IonButtons, IonBackButton, IonTitle, IonButton, IonIcon, IonContent,
    IonText, IonBadge, IonSpinner,
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

  async ngOnInit(): Promise<void> {
    try {
      const [pi, actions] = await Promise.all([
        firstValueFrom(this.api.pi(this.position())),
        firstValueFrom(this.api.logs({ pi: this.position(), limit: 20 })),
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
