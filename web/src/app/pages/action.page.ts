import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnInit, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import {
  IonBackButton, IonBadge, IonButton, IonButtons, IonContent, IonHeader, IonProgressBar, IonText, IonTitle,
  IonToolbar,
} from '@ionic/angular';
import { catchError, firstValueFrom, map, of, switchMap, take, takeWhile, timer } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime, num, pct, statusColor, temp, uptime } from '../core/format';
import { RebootVerdict, rebootVerdict, throttleText } from '../core/fleet';
import { ActionProgress, ActionResult } from '../core/models';
import { comparePositions } from '../core/sort';
import { TableSort } from '../core/table-sort';

type DiagCol = 'position' | 'result' | 'throttle' | 'disk_used' | 'disk_free';
type HealthCol = 'position' | 'result' | 'cpu' | 'ram' | 'temp' | 'uptime';
type VerifyCol = 'position' | 'verdict' | 'uptime';

const POLL_MS = 1000;
/** Wait before checking that rebooted Pis came back with a fresh uptime. */
const REBOOT_VERIFY_DELAY_S = 90;

/** Stop polling only on these; anything else (network blip, 502 during a restart) is retried. */
function isFatal(err: unknown): boolean {
  return err instanceof HttpErrorResponse && [401, 403, 404].includes(err.status);
}

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

          @if (p.action === 'diagnostics') {
            <div class="table-scroll">
              <table class="data">
                <thead>
                  <tr>
                    <th (click)="diagSort.sortBy('position')" class="sortable">Position{{ diagSort.indicator('position') }}</th>
                    <th (click)="diagSort.sortBy('result')" class="sortable">Result{{ diagSort.indicator('result') }}</th>
                    <th (click)="diagSort.sortBy('throttle')" class="sortable">Throttling / power{{ diagSort.indicator('throttle') }}</th>
                    <th (click)="diagSort.sortBy('disk_used')" class="sortable">Disk used{{ diagSort.indicator('disk_used') }}</th>
                    <th (click)="diagSort.sortBy('disk_free')" class="sortable">Free{{ diagSort.indicator('disk_free') }}</th>
                  </tr>
                </thead>
                <tbody>
                  @for (r of sortedDiag(); track r.position) {
                    <tr class="clickable" [routerLink]="['/pi', r.position]">
                      <td><strong>{{ r.position }}</strong></td>
                      <td>
                        @if (r.error) { <span class="error-text">{{ r.error }}</span> } @else { <ion-badge color="success">ok</ion-badge> }
                      </td>
                      <td [class.error-text]="throttleText(r.details?.['throttled']) !== 'ok'">{{ throttleText(r.details?.['throttled']) }}</td>
                      <td [class.error-text]="diskUsed(r) >= 90">{{ pct(diskUsed(r) >= 0 ? diskUsed(r) : null) }}</td>
                      <td>{{ diskFree(r) }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          } @else if (p.action === 'health') {
            <div class="table-scroll">
              <table class="data">
                <thead>
                  <tr>
                    <th (click)="healthSort.sortBy('position')" class="sortable">Position{{ healthSort.indicator('position') }}</th>
                    <th (click)="healthSort.sortBy('result')" class="sortable">Result{{ healthSort.indicator('result') }}</th>
                    <th (click)="healthSort.sortBy('cpu')" class="sortable">CPU 1m{{ healthSort.indicator('cpu') }}</th>
                    <th (click)="healthSort.sortBy('ram')" class="sortable">RAM{{ healthSort.indicator('ram') }}</th>
                    <th (click)="healthSort.sortBy('temp')" class="sortable">Temp{{ healthSort.indicator('temp') }}</th>
                    <th (click)="healthSort.sortBy('uptime')" class="sortable">Uptime{{ healthSort.indicator('uptime') }}</th>
                  </tr>
                </thead>
                <tbody>
                  @for (r of sortedHealth(); track r.position) {
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

          @if (p.action === 'reboot' && p.finished && canAct) {
            <h3>Did they reboot?</h3>
            <p class="muted">A health check compares each Pi's uptime with the time since the reboot was requested.</p>
            @if (verifyCountdown() !== null) {
              <p>Checking in {{ verifyCountdown() }} s …
                <ion-button size="small" fill="outline" (click)="startVerify()">Check now</ion-button></p>
            }
            @if (verifyCountdown() === null && !verify() && !verifyError()) {
              <ion-button size="small" fill="outline" (click)="startVerify()">Check now</ion-button>
            }
            @if (verifyError()) { <ion-text color="danger"><p>{{ verifyError() }}</p></ion-text> }
            @if (verify(); as v) {
              <div class="table-scroll">
                <table class="data">
                  <thead>
                    <tr>
                      <th (click)="verifySort.sortBy('position')" class="sortable">Position{{ verifySort.indicator('position') }}</th>
                      <th (click)="verifySort.sortBy('verdict')" class="sortable">Verdict{{ verifySort.indicator('verdict') }}</th>
                      <th (click)="verifySort.sortBy('uptime')" class="sortable">Uptime{{ verifySort.indicator('uptime') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (r of verifySorted(); track r.position) {
                      <tr>
                        <td><strong>{{ r.position }}</strong></td>
                        <td>
                          @switch (verdict(r)) {
                            @case ('rebooted') { <ion-badge color="success">rebooted</ion-badge> }
                            @case ('not-rebooted') { <ion-badge color="danger">NOT rebooted</ion-badge> }
                            @default { <span class="error-text">{{ r.error ?? 'unknown' }}</span> }
                          }
                        </td>
                        <td>{{ uptime(num(r.details, 'uptime_s')) }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
              @if (v.finished) {
                <ion-button size="small" fill="outline" (click)="startVerify()">Check again</ion-button>
              } @else {
                <p class="muted">Checking {{ v.done }} / {{ v.total }} …</p>
              }
            }
          }
        </div>
      }
    </ion-content>
  `,
  styles: [`
    .result { margin: 12px 0; }
    ion-badge { margin-left: 6px; }
    th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
    th.sortable:hover { opacity: 0.7; }
  `],
  imports: [
    RouterLink, IonHeader, IonToolbar, IonButtons, IonBackButton, IonTitle, IonProgressBar, IonContent, IonText,
    IonBadge, IonButton,
  ],
})
export class ActionPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly canAct = inject(AuthService).can('operator');

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
  readonly throttleText = throttleText;

  /** Reboot verification: a follow-up health check on the Pis that accepted the reboot */
  readonly verify = signal<ActionProgress | null>(null);
  readonly verifyError = signal<string | null>(null);
  readonly verifyCountdown = signal<number | null>(null);
  private verifyStarted = false;
  private sawRunning = false;

  readonly diagSort = new TableSort<ActionResult, DiagCol>({
    position: (a, b) => comparePositions(a.position, b.position),
    result: (a, b) => (a.error ?? '').localeCompare(b.error ?? ''),
    throttle: (a, b) => throttleText(a.details?.['throttled']).localeCompare(throttleText(b.details?.['throttled'])),
    disk_used: (a, b) => this.diskUsed(a) - this.diskUsed(b),
    disk_free: (a, b) => this.diskFreeMb(a) - this.diskFreeMb(b),
  }, 'position');
  readonly healthSort = new TableSort<ActionResult, HealthCol>({
    position: (a, b) => comparePositions(a.position, b.position),
    result: (a, b) => (a.error ?? '').localeCompare(b.error ?? ''),
    cpu: (a, b) => (num(a.details, 'cpu_1m') ?? 0) - (num(b.details, 'cpu_1m') ?? 0),
    ram: (a, b) => (num(a.details, 'mem_percent') ?? 0) - (num(b.details, 'mem_percent') ?? 0),
    temp: (a, b) => (num(a.details, 'temp_c') ?? 0) - (num(b.details, 'temp_c') ?? 0),
    uptime: (a, b) => (num(a.details, 'uptime_s') ?? 0) - (num(b.details, 'uptime_s') ?? 0),
  }, 'position');
  readonly verifySort = new TableSort<ActionResult, VerifyCol>({
    position: (a, b) => comparePositions(a.position, b.position),
    verdict: (a, b) => this.verdict(a).localeCompare(this.verdict(b)),
    uptime: (a, b) => (num(a.details, 'uptime_s') ?? 0) - (num(b.details, 'uptime_s') ?? 0),
  }, 'position');

  readonly verifySorted = computed<ActionResult[]>(() => this.verifySort.apply(this.verify()?.results ?? []));

  readonly sortedDiag = computed<ActionResult[]>(() => this.diagSort.apply(this.progress()?.results ?? []));
  readonly sortedHealth = computed<ActionResult[]>(() => this.healthSort.apply(this.progress()?.results ?? []));

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
    this.poll(Number(this.id()), (p) => {
      this.progress.set(p);
      if (!p.finished) {
        this.sawRunning = true;
      } else if (p.action === 'reboot' && this.canAct && this.sawRunning) {
        this.scheduleVerify(); // only when watched live — opening an old reboot doesn't trigger checks
      }
    }, (msg) => this.error.set(msg));
  }

  /** Poll an action every second until it finishes; transient errors are shown and retried. */
  private poll(id: number, onProgress: (p: ActionProgress) => void, onError: (msg: string | null) => void): void {
    timer(0, POLL_MS)
      .pipe(
        switchMap(() => this.api.action(id).pipe(
          map((p) => ({ p, fatal: false, err: null as string | null })),
          catchError((err: unknown) => of({ p: null, fatal: isFatal(err), err: errorMessage(err) })),
        )),
        takeWhile((r) => !r.fatal && !r.p?.finished, true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((r) => {
        if (r.p) {
          onError(null);
          onProgress(r.p);
        } else {
          onError(r.fatal ? r.err : `${r.err} — retrying …`);
        }
      });
  }

  diskUsed(r: ActionResult): number {
    const disk = r.details?.['disk'] as Record<string, unknown> | undefined;
    return typeof disk?.['used_percent'] === 'number' ? disk['used_percent'] : -1;
  }

  diskFree(r: ActionResult): string {
    const mb = this.diskFreeMb(r);
    return mb >= 0 ? (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`) : '—';
  }

  private diskFreeMb(r: ActionResult): number {
    const disk = r.details?.['disk'] as Record<string, unknown> | undefined;
    const mb = disk?.['free_mb'];
    return typeof mb === 'number' ? mb : -1;
  }

  verdict(r: ActionResult): RebootVerdict {
    const reboot = this.progress();
    const check = this.verify();
    if (!reboot || !check || r.error) {
      return 'unknown';
    }
    return rebootVerdict(num(r.details, 'uptime_s'), reboot.started_at, check.started_at);
  }

  private scheduleVerify(): void {
    if (this.verifyStarted || this.verifyCountdown() !== null) {
      return;
    }
    timer(0, 1000)
      .pipe(take(REBOOT_VERIFY_DELAY_S + 1), takeUntilDestroyed(this.destroyRef))
      .subscribe((i) => {
        if (this.verifyStarted) {
          return;
        }
        const left = REBOOT_VERIFY_DELAY_S - i;
        this.verifyCountdown.set(left);
        if (left <= 0) {
          void this.startVerify();
        }
      });
  }

  async startVerify(): Promise<void> {
    const accepted = (this.progress()?.results ?? [])
      .filter((r) => !r.error && r.exit_code === 0)
      .map((r) => r.position);
    this.verifyStarted = true;
    this.verifyCountdown.set(null);
    if (accepted.length === 0) {
      this.verifyError.set('No Pi accepted the reboot — nothing to check.');
      return;
    }
    try {
      const queued = await firstValueFrom(this.api.healthCheck(accepted));
      this.verify.set(null);
      this.verifyError.set(null);
      this.poll(queued.action_id, (v) => this.verify.set(v), (msg) => this.verifyError.set(msg));
    } catch (err) {
      this.verifyError.set(errorMessage(err));
    }
  }
}
