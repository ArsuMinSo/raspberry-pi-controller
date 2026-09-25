import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  IonButton, IonButtons, IonCard, IonCardContent, IonCardHeader, IonCheckbox, IonContent, IonHeader, IonIcon,
  IonInput, IonItem, IonLabel, IonList, IonMenuButton, IonNote, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { errorMessage } from '../core/errors';
import { PiSummary } from '../core/models';
import { comparePositions } from '../core/sort';
import { TableSort, compareIps, compareStrings } from '../core/table-sort';

type SortColumn = 'position' | 'hostname' | 'ip' | 'status';

@Component({
  selector: 'app-execute-command',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Execute command</ion-title>
      </ion-toolbar>
    </ion-header>
    <ion-content class="ion-padding">
      <div class="page-narrow">
        @if (error()) { <ion-text color="danger"><p>{{ error() }}</p></ion-text> }

        <form (ngSubmit)="submit()">
          <!-- Command input -->
          <ion-card>
            <ion-card-content>
              <ion-list lines="full">
                <ion-item>
                  <ion-input label="Command" labelPlacement="stacked" placeholder="e.g. ps aux"
                             name="command" [(ngModel)]="command" [disabled]="submitting()"
                             required></ion-input>
                </ion-item>
                <ion-item>
                  <ion-input label="SSH username (optional)" labelPlacement="stacked"
                             name="username" [(ngModel)]="sshUsername" [disabled]="submitting()"></ion-input>
                </ion-item>
                <ion-item>
                  <ion-input label="Sudo password (optional)" labelPlacement="stacked" type="password"
                             name="sudoPassword" [(ngModel)]="sudoPassword" [disabled]="submitting()"
                             placeholder="Will not be stored"></ion-input>
                </ion-item>
              </ion-list>
              <ion-note class="muted">Password transmitted once, never stored or logged.</ion-note>
            </ion-card-content>
          </ion-card>

          <!-- Pi selection -->
          <ion-card>
            <ion-card-header>
              <ion-label><strong>Select Pis ({{ selected().size }} of {{ pis().length }})</strong></ion-label>
            </ion-card-header>
            <ion-card-content>
              <ion-button (click)="selectAll()" size="small" fill="outline" [disabled]="pis().length === 0">
                Select all
              </ion-button>
              <ion-button (click)="selectNone()" size="small" fill="outline" [disabled]="selected().size === 0">
                Clear
              </ion-button>
 
              <!-- Submit -->
              <ion-button type="submit" [disabled]="!command || selected().size === 0 || submitting()">
                {{ submitting() ? 'Executing…' : 'Execute' }}
              </ion-button>
            </ion-card-content>
          </ion-card>

          @if (pis().length === 0) {
            <p class="muted">No Pis available.</p>
          } @else {
            <div class="table-scroll">
              <table class="data">
                <thead>
                  <tr>
                    <th></th>
                    <th (click)="sort.sortBy('position')" class="sortable">Position{{ sort.indicator('position') }}</th>
                    <th (click)="sort.sortBy('hostname')" class="sortable">Hostname{{ sort.indicator('hostname') }}</th>
                    <th (click)="sort.sortBy('ip')" class="sortable">IP{{ sort.indicator('ip') }}</th>
                    <th (click)="sort.sortBy('status')" class="sortable">Status{{ sort.indicator('status') }}</th>
                  </tr>
                </thead>
                <tbody>
                  @for (pi of sortedPis(); track pi.mac) {
                    <tr>
                      <td>
                        <ion-checkbox [checked]="selected().has(pi.position)" (ionChange)="toggle(pi.position)"
                                      [attr.aria-label]="'Select ' + pi.position"></ion-checkbox>
                      </td>
                      <td><strong>{{ pi.position }}</strong></td>
                      <td>{{ pi.hostname ?? '—' }}</td>
                      <td>{{ pi.ip ?? '—' }}</td>
                      <td>{{ pi.status }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }

       </form>
      </div>
    </ion-content>
  `,
  styles: [`
    .page-narrow { max-width: 50rem; }
    ion-card-header { --padding-bottom: 8px; }
    ion-card-content { --padding-top: 8px; }
    .table-scroll { overflow-x: auto; margin: 16px 0; }
    .muted { color: var(--ion-color-medium); font-size: 0.9rem; }
    th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
    th.sortable:hover { opacity: 0.7; }
  `],
  imports: [
    FormsModule, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonContent, IonCard, IonCardContent,
    IonCardHeader, IonList, IonItem, IonInput, IonLabel, IonCheckbox, IonButton, IonNote, IonText,
  ],
})
export class ExecuteCommandPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  readonly pis = signal<PiSummary[]>([]);
  readonly selected = signal<Set<string>>(new Set());
  readonly error = signal<string | null>(null);
  readonly submitting = signal(false);
  readonly sort = new TableSort<PiSummary, SortColumn>({
    position: (a, b) => comparePositions(a.position, b.position),
    hostname: (a, b) => compareStrings(a.hostname, b.hostname),
    ip: (a, b) => compareIps(a.ip, b.ip),
    status: (a, b) => a.status.localeCompare(b.status),
  }, 'position');
  readonly sortedPis = computed(() => this.sort.apply(this.pis()));

  command = '';
  sshUsername = '';
  sudoPassword = '';

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const pis = await firstValueFrom(this.api.listPis());
      this.pis.set(pis.sort((a, b) => comparePositions(a.position, b.position)));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
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

  selectAll(): void {
    this.selected.set(new Set(this.pis().map((p) => p.position)));
  }

  selectNone(): void {
    this.selected.set(new Set());
  }

  async submit(): Promise<void> {
    this.submitting.set(true);
    this.error.set(null);
    try {
      const positions = [...this.selected()].sort(comparePositions);
      const queued = await firstValueFrom(
        this.api.executeCommand(positions, this.command, this.sshUsername || undefined, this.sudoPassword || undefined)
      );
      await this.router.navigate(['/actions', queued.action_id]);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.submitting.set(false);
    }
  }
}
