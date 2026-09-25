import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  AlertController, IonBadge, IonButton, IonButtons, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonCheckbox,
  IonContent, IonHeader, IonIcon, IonInput, IonItem, IonList, IonMenuButton, IonSelect, IonSelectOption, IonText,
  IonTitle, IonToolbar, ToastController,
} from '@ionic/angular';
import { addIcons } from 'ionicons';
import { refreshOutline } from 'ionicons/icons';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime } from '../core/format';
import { ScheduledTask, TaskType } from '../core/models';
import { TableSort, compareDates, compareStrings } from '../core/table-sort';

const TASK_TYPES: TaskType[] = ['command', 'health', 'discovery'];
type SortColumn = 'name' | 'cron' | 'type' | 'enabled' | 'last_run' | 'last_status' | 'created_by' | 'last_edited_by';

@Component({
  selector: 'app-tasks',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Scheduled tasks</ion-title>
        <ion-buttons slot="end">
          <ion-button (click)="load()" [disabled]="loading()" aria-label="Refresh">
            <ion-icon slot="icon-only" name="refresh-outline"></ion-icon>
          </ion-button>
        </ion-buttons>
      </ion-toolbar>
    </ion-header>
    <ion-content class="ion-padding">
      <div class="page-narrow">
        @if (error()) { <ion-text color="danger"><p>{{ error() }}</p></ion-text> }

        @if (tasks().length === 0 && !loading()) {
          <p class="muted">No scheduled tasks.</p>
        } @else {
          <div class="table-scroll">
            <table class="data">
              <thead>
                <tr>
                  <th (click)="sort.sortBy('name')" class="sortable">Name{{ sort.indicator('name') }}</th>
                  <th (click)="sort.sortBy('cron')" class="sortable">Cron{{ sort.indicator('cron') }}</th>
                  <th (click)="sort.sortBy('type')" class="sortable">Type{{ sort.indicator('type') }}</th>
                  <th>Pis</th>
                  <th (click)="sort.sortBy('enabled')" class="sortable">Enabled{{ sort.indicator('enabled') }}</th>
                  <th (click)="sort.sortBy('last_run')" class="sortable">Last run{{ sort.indicator('last_run') }}</th>
                  <th (click)="sort.sortBy('last_status')" class="sortable">Last status{{ sort.indicator('last_status') }}</th>
                  <th (click)="sort.sortBy('created_by')" class="sortable">Created by{{ sort.indicator('created_by') }}</th>
                  <th (click)="sort.sortBy('last_edited_by')" class="sortable">Last edit by{{ sort.indicator('last_edited_by') }}</th>
                  @if (canManage) { <th></th> }
                </tr>
              </thead>
              <tbody>
                @for (t of sortedTasks(); track t.id) {
                  <tr [class.disabled]="!t.enabled">
                    <td><strong>{{ t.name }}</strong></td>
                    <td><code>{{ t.cron }}</code></td>
                    <td>{{ t.task_type }}</td>
                    <td class="wrap">{{ t.pis.length ? t.pis.join(', ') : 'all' }}</td>
                    <td>
                      @if (canManage) {
                        <ion-checkbox [checked]="t.enabled" (ionChange)="toggleEnabled(t)" [disabled]="busy()"></ion-checkbox>
                      } @else {
                        <ion-badge [color]="t.enabled ? 'success' : 'medium'">{{ t.enabled ? 'yes' : 'no' }}</ion-badge>
                      }
                    </td>
                    <td>{{ dateTime(t.last_run) }}</td>
                    <td>
                      @if (t.last_status) {
                        <ion-badge [color]="t.last_status === 'success' ? 'success' : t.last_status === 'fail' ? 'danger' : 'warning'">
                          {{ t.last_status }}
                        </ion-badge>
                      } @else { — }
                    </td>
                    <td>{{ t.created_by ?? '—' }}</td>
                    <td>{{ t.last_edited_by ?? '—' }}</td>
                    @if (canManage) {
                      <td class="actions">
                        <ion-button size="small" fill="outline" (click)="startEdit(t)" [disabled]="busy()">Edit</ion-button>
                        <ion-button size="small" fill="outline" color="danger" (click)="remove(t)" [disabled]="busy()">Delete</ion-button>
                      </td>
                    }
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }

        @if (canManage) {
          <ion-card>
            <ion-card-header><ion-card-title>{{ editingId() ? 'Edit task' : 'New task' }}</ion-card-title></ion-card-header>
            <ion-card-content>
              <form (ngSubmit)="save()">
                <ion-list lines="full">
                  <ion-item>
                    <ion-input label="Name" labelPlacement="stacked" name="name" [(ngModel)]="name" [disabled]="busy()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-input label="Cron expression" labelPlacement="stacked" name="cron" [(ngModel)]="cron"
                               placeholder="0 3 * * *" [disabled]="busy()" helperText="minute hour day month weekday"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-select label="Type" labelPlacement="stacked" interface="popover" name="task_type"
                                [(ngModel)]="taskType" [disabled]="busy()">
                      @for (tt of taskTypes; track tt) { <ion-select-option [value]="tt">{{ tt }}</ion-select-option> }
                    </ion-select>
                  </ion-item>
                  @if (taskType === 'command') {
                    <ion-item>
                      <ion-input label="Command" labelPlacement="stacked" name="command" [(ngModel)]="command" [disabled]="busy()"></ion-input>
                    </ion-item>
                  }
                  <ion-item>
                    <ion-input label="Pis (comma-separated positions, blank = all)" labelPlacement="stacked"
                               name="pis" [(ngModel)]="pisText" [disabled]="busy()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-checkbox name="enabled" [(ngModel)]="enabled" labelPlacement="end" [disabled]="busy()">Enabled</ion-checkbox>
                  </ion-item>
                </ion-list>
                @if (formError()) { <ion-text color="danger"><p>{{ formError() }}</p></ion-text> }
                <ion-button type="submit" [disabled]="busy() || !name || !cron || (taskType === 'command' && !command)">
                  {{ editingId() ? 'Update task' : 'Create task' }}
                </ion-button>
                @if (editingId()) {
                  <ion-button fill="outline" color="medium" type="button" (click)="cancelEdit()" [disabled]="busy()">Cancel</ion-button>
                }
              </form>
            </ion-card-content>
          </ion-card>
        }
      </div>
    </ion-content>
  `,
  styles: [`
    .page-narrow { max-width: 60rem; }
    td.actions { white-space: nowrap; }
    tr.disabled td { opacity: 0.6; }
    ion-select { min-width: 7rem; }
    code { font-size: 0.85rem; }
    th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
    th.sortable:hover { opacity: 0.7; }
  `],
  imports: [
    FormsModule, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonButton, IonIcon, IonContent, IonText,
    IonCard, IonCardHeader, IonCardTitle, IonCardContent, IonList, IonItem, IonInput, IonSelect, IonSelectOption,
    IonCheckbox, IonBadge,
  ],
})
export class TasksPage {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly alerts = inject(AlertController);
  private readonly toast = inject(ToastController);

  readonly canManage = this.auth.can('admin');
  readonly taskTypes = TASK_TYPES;
  readonly dateTime = dateTime;

  readonly tasks = signal<ScheduledTask[]>([]);
  readonly loading = signal(false);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly formError = signal<string | null>(null);
  readonly editingId = signal<number | null>(null);
  readonly sort = new TableSort<ScheduledTask, SortColumn>({
    name: (a, b) => compareStrings(a.name, b.name),
    cron: (a, b) => compareStrings(a.cron, b.cron),
    type: (a, b) => compareStrings(a.task_type, b.task_type),
    enabled: (a, b) => Number(a.enabled) - Number(b.enabled),
    last_run: (a, b) => compareDates(a.last_run, b.last_run),
    last_status: (a, b) => compareStrings(a.last_status, b.last_status),
    created_by: (a, b) => compareStrings(a.created_by, b.created_by),
    last_edited_by: (a, b) => compareStrings(a.last_edited_by, b.last_edited_by),
  }, 'name');
  readonly sortedTasks = computed(() => this.sort.apply(this.tasks()));

  name = '';
  cron = '';
  taskType: TaskType = 'health';
  command = '';
  pisText = '';
  enabled = true;

  constructor() {
    addIcons({ refreshOutline });
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      this.tasks.set(await firstValueFrom(this.api.listTasks()));
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.loading.set(false);
    }
  }

  startEdit(t: ScheduledTask): void {
    this.editingId.set(t.id);
    this.name = t.name;
    this.cron = t.cron;
    this.taskType = t.task_type;
    this.command = t.command ?? '';
    this.pisText = t.pis.join(', ');
    this.enabled = t.enabled;
    this.formError.set(null);
  }

  cancelEdit(): void {
    this.editingId.set(null);
    this.name = '';
    this.cron = '';
    this.taskType = 'health';
    this.command = '';
    this.pisText = '';
    this.enabled = true;
    this.formError.set(null);
  }

  private parsePis(): string[] {
    return this.pisText.split(',').map((s) => s.trim()).filter((s) => s.length > 0);
  }

  async save(): Promise<void> {
    this.busy.set(true);
    this.formError.set(null);
    try {
      const body = {
        name: this.name,
        cron: this.cron,
        task_type: this.taskType,
        command: this.taskType === 'command' ? this.command : null,
        pis: this.parsePis(),
        enabled: this.enabled,
      };
      if (this.editingId()) {
        await firstValueFrom(this.api.updateTask(this.editingId()!, body));
        await (await this.toast.create({ message: 'Task updated', duration: 2000, color: 'success' })).present();
      } else {
        await firstValueFrom(this.api.createTask(body));
        await (await this.toast.create({ message: 'Task created', duration: 2000, color: 'success' })).present();
      }
      this.cancelEdit();
      await this.load();
    } catch (err) {
      this.formError.set(errorMessage(err));
    } finally {
      this.busy.set(false);
    }
  }

  async toggleEnabled(t: ScheduledTask): Promise<void> {
    this.busy.set(true);
    try {
      await firstValueFrom(this.api.updateTask(t.id, { enabled: !t.enabled }));
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set(false);
    }
  }

  async remove(t: ScheduledTask): Promise<void> {
    const alert = await this.alerts.create({
      header: `Delete task "${t.name}"?`,
      message: 'This cannot be undone.',
      buttons: [{ text: 'Cancel', role: 'cancel' }, { text: 'Delete', role: 'confirm' }],
    });
    await alert.present();
    if ((await alert.onDidDismiss()).role !== 'confirm') return;

    this.busy.set(true);
    try {
      await firstValueFrom(this.api.deleteTask(t.id));
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set(false);
    }
  }
}
