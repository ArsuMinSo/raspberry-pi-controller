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
import { ColumnMenuComponent } from '../core/column-menu.component';
import { errorMessage } from '../core/errors';
import { dateTime } from '../core/format';
import { ScheduledTask, TaskType } from '../core/models';
import { TableSort, compareDates, compareStrings } from '../core/table-sort';
import { ColumnDef, TableColumns } from '../core/table-columns';

const TASK_TYPES: TaskType[] = ['command', 'health', 'discovery'];
type SortColumn = 'name' | 'cron' | 'type' | 'enabled' | 'last_run' | 'last_status' | 'created_by' | 'last_edited_by';
type Col = SortColumn | 'pis';

const COLUMNS: ColumnDef<Col>[] = [
  { key: 'name', label: 'Name', defaultWidth: 140 },
  { key: 'cron', label: 'Cron', defaultWidth: 110 },
  { key: 'type', label: 'Type', defaultWidth: 100 },
  { key: 'pis', label: 'Pis', defaultWidth: 140 },
  { key: 'enabled', label: 'Enabled', defaultWidth: 90 },
  { key: 'last_run', label: 'Last run', defaultWidth: 150 },
  { key: 'last_status', label: 'Last status', defaultWidth: 110 },
  { key: 'created_by', label: 'Created by', defaultWidth: 110 },
  { key: 'last_edited_by', label: 'Last edit by', defaultWidth: 110 },
];

@Component({
  selector: 'app-tasks',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Scheduled tasks</ion-title>
        <ion-buttons slot="end">
          <app-column-menu [cols]="cols" triggerId="tasks-cols"></app-column-menu>
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
                  @if (cols.isVisible('name')) {
                    <th (click)="sort.sortBy('name')" class="sortable" [style.width.px]="cols.width('name')">
                      Name{{ sort.indicator('name') }}<span class="resize-handle" (pointerdown)="cols.startResize('name', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('cron')) {
                    <th (click)="sort.sortBy('cron')" class="sortable" [style.width.px]="cols.width('cron')">
                      Cron{{ sort.indicator('cron') }}<span class="resize-handle" (pointerdown)="cols.startResize('cron', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('type')) {
                    <th (click)="sort.sortBy('type')" class="sortable" [style.width.px]="cols.width('type')">
                      Type{{ sort.indicator('type') }}<span class="resize-handle" (pointerdown)="cols.startResize('type', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('pis')) {
                    <th [style.width.px]="cols.width('pis')">
                      Pis<span class="resize-handle" (pointerdown)="cols.startResize('pis', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('enabled')) {
                    <th (click)="sort.sortBy('enabled')" class="sortable" [style.width.px]="cols.width('enabled')">
                      Enabled{{ sort.indicator('enabled') }}<span class="resize-handle" (pointerdown)="cols.startResize('enabled', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('last_run')) {
                    <th (click)="sort.sortBy('last_run')" class="sortable" [style.width.px]="cols.width('last_run')">
                      Last run{{ sort.indicator('last_run') }}<span class="resize-handle" (pointerdown)="cols.startResize('last_run', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('last_status')) {
                    <th (click)="sort.sortBy('last_status')" class="sortable" [style.width.px]="cols.width('last_status')">
                      Last status{{ sort.indicator('last_status') }}<span class="resize-handle" (pointerdown)="cols.startResize('last_status', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('created_by')) {
                    <th (click)="sort.sortBy('created_by')" class="sortable" [style.width.px]="cols.width('created_by')">
                      Created by{{ sort.indicator('created_by') }}<span class="resize-handle" (pointerdown)="cols.startResize('created_by', $event)"></span>
                    </th>
                  }
                  @if (cols.isVisible('last_edited_by')) {
                    <th (click)="sort.sortBy('last_edited_by')" class="sortable" [style.width.px]="cols.width('last_edited_by')">
                      Last edit by{{ sort.indicator('last_edited_by') }}<span class="resize-handle" (pointerdown)="cols.startResize('last_edited_by', $event)"></span>
                    </th>
                  }
                  @if (canManage) { <th class="col-check"></th> }
                </tr>
              </thead>
              <tbody>
                @for (t of sortedTasks(); track t.id) {
                  <tr [class.disabled]="!t.enabled">
                    @if (cols.isVisible('name')) { <td><strong>{{ t.name }}</strong></td> }
                    @if (cols.isVisible('cron')) { <td><code>{{ t.cron }}</code></td> }
                    @if (cols.isVisible('type')) { <td>{{ t.task_type }}</td> }
                    @if (cols.isVisible('pis')) { <td class="wrap">{{ t.pis.length ? t.pis.join(', ') : 'all' }}</td> }
                    @if (cols.isVisible('enabled')) {
                      <td>
                        @if (canManage) {
                          <ion-checkbox [checked]="t.enabled" (ionChange)="toggleEnabled(t)" [disabled]="busy()"></ion-checkbox>
                        } @else {
                          <ion-badge [color]="t.enabled ? 'success' : 'medium'">{{ t.enabled ? 'yes' : 'no' }}</ion-badge>
                        }
                      </td>
                    }
                    @if (cols.isVisible('last_run')) { <td>{{ dateTime(t.last_run) }}</td> }
                    @if (cols.isVisible('last_status')) {
                      <td>
                        @if (t.last_status) {
                          <ion-badge [color]="t.last_status === 'success' ? 'success' : t.last_status === 'fail' ? 'danger' : 'warning'">
                            {{ t.last_status }}
                          </ion-badge>
                        } @else { — }
                      </td>
                    }
                    @if (cols.isVisible('created_by')) { <td>{{ t.created_by ?? '—' }}</td> }
                    @if (cols.isVisible('last_edited_by')) { <td>{{ t.last_edited_by ?? '—' }}</td> }
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
    IonCheckbox, IonBadge, ColumnMenuComponent,
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
  readonly cols = new TableColumns<Col>(COLUMNS, 'tasks');
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
