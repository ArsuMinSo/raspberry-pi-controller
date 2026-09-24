import { Component, DestroyRef, OnInit, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import {
  IonBackButton, IonBadge, IonButtons, IonContent, IonHeader, IonProgressBar, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { catchError, of, switchMap, takeWhile, timer } from 'rxjs';

import { ApiService } from '../core/api.service';
import { errorMessage } from '../core/errors';
import { dateTime, num, pct, statusColor, temp, uptime } from '../core/format';
import { ActionProgress, ActionResult } from '../core/models';
import { comparePositions } from '../core/sort';

const POLL_MS = 1000;

@Component({
  selector: 'app-action',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-back-button defaultHref="/inventory"></ion-back-button></ion-buttons>
        <ion-title>Action #{{ id() }}</ion-title>
      </ion-toolbar>
      @if (progress(); as p) {
        @if (!p.finished) {
          <ion-progress-bar [value]="p.total ? p.done / p.total : 0"
                            [type]="p.total ? 'determinate' : 'indeterminate'"></ion-progress-bar>
        }
      }
    </ion-header>
    <ion-content class="ion-padding">
      @if (error()) {
        <ion-text color="danger"><p>{{ error() }}</p></ion-text>
      }
      @if (progress(); as p) {
        <div class="page-narrow">
          <p>
            <strong>{{ p.action }}</strong>
            <ion-badge [color]="statusColor(p.status)">{{ p.status }}</ion-badge>
            <span class="muted"> · by {{ p.user }} · started {{ dateTime(p.started_at) }}
              @if (p.duration_ms !== null) { · {{ (p.duration_ms / 1000).toFixed(1) }} s }</span>
          </p>
          @if (p.command) { <pre class="output">{{ p.command }}</pre> }
          @if (p.total) { <p>{{ p.done }} / {{ p.total }} Pis done</p> }
          @if (p.error) { <ion-text color="danger"><p>{{ p.error }}</p></ion-text> }

          @if (p.action === 'health') {
            <div class="table-scroll">
              <table class="data">
                <thead><tr><th>Position</th><th>Result</th><th>CPU 1m</th><th>RAM</th><th>Temp</th><th>Uptime</th></tr></thead>
                <tbody>
                  @for (r of sorted(); track r.position) {
                    <tr class="clickable" [routerLink]="['/pi', r.position]">
                      <td><strong>{{ r.position }}</strong></td>
                      <td>
                        @if (r.error) { <span class="error-text">{{ r.error }}</span> } @else { <ion-badge color="success">ok</ion-badge> }
                      </td>
                      <td>{{ pct(num(r.details, 'cpu_1m')) }}</td>
                      <td>{{ pct(num(r.details, 'mem_percent')) }}</td>
                      <td>{{ temp(num(r.details, 'temp_c')) }}</td>
                      <td>{{ uptime(num(r.details, 'uptime_s')) }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          } @else {
            @for (r of sorted(); track r.position) {
              <div class="result">
                <strong>{{ r.position }}</strong>
                @if (r.error) {
                  <span class="error-text"> {{ r.error }}</span>
                } @else {
                  <ion-badge [color]="r.exit_code === 0 ? 'success' : 'danger'">exit {{ r.exit_code }}</ion-badge>
                }
                @if (r.stdout) { <pre class="output">{{ r.stdout }}</pre> }
                @if (r.stderr) { <pre class="output error-text">{{ r.stderr }}</pre> }
              </div>
            }
          }
          @if (pending().length) {
            <p class="muted">Waiting for: {{ pending().join(', ') }}</p>
          }
        </div>
      }
    </ion-content>
  `,
  styles: [`.result { margin: 12px 0; } ion-badge { margin-left: 6px; }`],
  imports: [
    RouterLink, IonHeader, IonToolbar, IonButtons, IonBackButton, IonTitle, IonProgressBar, IonContent, IonText,
    IonBadge,
  ],
})
export class ActionPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Route param :id */
  readonly id = input.required<string>();

  readonly progress = signal<ActionProgress | null>(null);
  readonly error = signal<string | null>(null);

  readonly statusColor = statusColor;
  readonly dateTime = dateTime;
  readonly pct = pct;
  readonly temp = temp;
  readonly uptime = uptime;
  readonly num = num;

  readonly sorted = computed<ActionResult[]>(() =>
    [...(this.progress()?.results ?? [])].sort((a, b) => comparePositions(a.position, b.position)));

  readonly pending = computed<string[]>(() => {
    const p = this.progress();
    if (!p || p.finished) {
      return [];
    }
    const done = new Set(p.results.map((r) => r.position));
    return p.pis_selected.filter((pos) => !done.has(pos)).sort(comparePositions);
  });

  ngOnInit(): void {
    const id = Number(this.id());
    timer(0, POLL_MS)
      .pipe(
        switchMap(() => this.api.action(id).pipe(
          catchError((err: unknown) => {
            this.error.set(errorMessage(err));
            return of(null);
          }),
        )),
        // stop after the first finished response (inclusive) — or on a hard error
        takeWhile((p) => p !== null && !p.finished, true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((p) => {
        if (p) {
          this.error.set(null);
          this.progress.set(p);
        }
      });
  }
}
