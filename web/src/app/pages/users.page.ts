import { Component, OnInit, computed, inject, signal } from '@angular/core';
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
import { Role, User } from '../core/models';
import { ROLES, usernameProblem } from '../core/roles';
import { TableSort, compareDates, compareStrings } from '../core/table-sort';
import { newPasswordProblem } from './account.page';

type SortColumn = 'username' | 'role' | 'status' | 'last_login' | 'created';

/** Admin: create users, change roles, disable, reset passwords, end sessions. Users are never deleted. */
@Component({
  selector: 'app-users',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Users</ion-title>
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

        <div class="table-scroll">
          <table class="data">
            <thead>
              <tr>
                <th (click)="sort.sortBy('username')" class="sortable">User{{ sort.indicator('username') }}</th>
                <th (click)="sort.sortBy('role')" class="sortable">Role{{ sort.indicator('role') }}</th>
                <th (click)="sort.sortBy('status')" class="sortable">Status{{ sort.indicator('status') }}</th>
                <th (click)="sort.sortBy('last_login')" class="sortable">Last login{{ sort.indicator('last_login') }}</th>
                <th (click)="sort.sortBy('created')" class="sortable">Created{{ sort.indicator('created') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              @for (u of sortedUsers(); track u.id) {
                <tr [class.disabled]="!u.is_active">
                  <td>
                    {{ u.username }}
                    @if (u.id === me()) { <ion-badge color="medium">you</ion-badge> }
                    @if (u.must_change_password) { <ion-badge color="warning">must change password</ion-badge> }
                  </td>
                  <td>
                    <ion-select interface="popover" [value]="u.role" (ionChange)="changeRole(u, $event.detail.value)"
                                [disabled]="busy()" aria-label="Role">
                      @for (r of roles; track r) { <ion-select-option [value]="r">{{ r }}</ion-select-option> }
                    </ion-select>
                  </td>
                  <td>
                    <ion-badge [color]="u.is_active ? 'success' : 'danger'">{{ u.is_active ? 'active' : 'disabled' }}</ion-badge>
                  </td>
                  <td>{{ dateTime(u.last_login_at) }}</td>
                  <td>{{ dateTime(u.created_at) }}</td>
                  <td class="actions">
                    <ion-button size="small" fill="outline" (click)="resetPassword(u)" [disabled]="busy()">Reset password</ion-button>
                    <ion-button size="small" fill="outline" (click)="endSessions(u)" [disabled]="busy()">End sessions</ion-button>
                    <ion-button size="small" fill="outline" [color]="u.is_active ? 'danger' : 'success'"
                                (click)="toggleActive(u)" [disabled]="busy()">
                      {{ u.is_active ? 'Disable' : 'Enable' }}
                    </ion-button>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        <p class="muted">Users are never deleted (the activity log refers to them) — disable them instead.
          Disabling, a password reset or "End sessions" logs the user out everywhere.</p>

        <ion-card>
          <ion-card-header><ion-card-title>New user</ion-card-title></ion-card-header>
          <ion-card-content>
            <form (ngSubmit)="create()">
              <ion-list lines="full">
                <ion-item>
                  <ion-input label="Username" labelPlacement="stacked" name="username" autocomplete="off"
                             [(ngModel)]="username" helperText="lowercase letters, digits, . _ -"></ion-input>
                </ion-item>
                <ion-item>
                  <ion-select label="Role" labelPlacement="stacked" interface="popover" name="role" [(ngModel)]="role">
                    @for (r of roles; track r) { <ion-select-option [value]="r">{{ r }}</ion-select-option> }
                  </ion-select>
                </ion-item>
                <ion-item>
                  <ion-input label="Password (min. 12 characters)" labelPlacement="stacked" type="password"
                             name="password" autocomplete="new-password" [(ngModel)]="password"></ion-input>
                </ion-item>
                <ion-item>
                  <ion-input label="Password again" labelPlacement="stacked" type="password" name="confirm"
                             autocomplete="new-password" [(ngModel)]="confirm"></ion-input>
                </ion-item>
                <ion-item>
                  <ion-checkbox name="mustChange" [(ngModel)]="mustChange" labelPlacement="end">
                    Must change password at first login
                  </ion-checkbox>
                </ion-item>
              </ion-list>
              @if (createError()) { <ion-text color="danger"><p>{{ createError() }}</p></ion-text> }
              <ion-button type="submit" [disabled]="busy() || !username || !password || !confirm">Create user</ion-button>
            </form>
          </ion-card-content>
        </ion-card>
      </div>
    </ion-content>
  `,
  styles: [`
    td.actions { white-space: nowrap; }
    tr.disabled td { opacity: 0.6; }
    ion-select { min-width: 7rem; }
    ion-badge { margin-left: 4px; }
    th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
    th.sortable:hover { opacity: 0.7; }
  `],
  imports: [
    FormsModule, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonButton, IonIcon, IonContent,
    IonText, IonBadge, IonSelect, IonSelectOption, IonCard, IonCardHeader, IonCardTitle, IonCardContent, IonList,
    IonItem, IonInput, IonCheckbox,
  ],
})
export class UsersPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly alerts = inject(AlertController);
  private readonly toasts = inject(ToastController);

  readonly roles = ROLES;
  readonly dateTime = dateTime;
  readonly users = signal<User[]>([]);
  readonly loading = signal(false);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly createError = signal<string | null>(null);
  readonly sort = new TableSort<User, SortColumn>({
    username: (a, b) => compareStrings(a.username, b.username),
    role: (a, b) => compareStrings(a.role, b.role),
    status: (a, b) => Number(a.is_active) - Number(b.is_active),
    last_login: (a, b) => compareDates(a.last_login_at, b.last_login_at),
    created: (a, b) => compareDates(a.created_at, b.created_at),
  }, 'username');
  readonly sortedUsers = computed(() => this.sort.apply(this.users()));

  username = '';
  role: Role = 'viewer';
  password = '';
  confirm = '';
  mustChange = true;

  constructor() {
    addIcons({ refreshOutline });
  }

  me(): number | undefined {
    return this.auth.user()?.id;
  }

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    try {
      this.users.set(await firstValueFrom(this.api.users()));
      this.error.set(null);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.loading.set(false);
    }
  }

  async create(): Promise<void> {
    const username = this.username.trim().toLowerCase();
    const problem = usernameProblem(username) ?? newPasswordProblem(this.password, this.confirm);
    if (problem) {
      this.createError.set(problem);
      return;
    }
    await this.run(async () => {
      await firstValueFrom(this.api.createUser({
        username, role: this.role, password: this.password, password_confirm: this.confirm,
        must_change_password: this.mustChange,
      }));
      this.username = this.password = this.confirm = '';
      this.createError.set(null);
      await this.toast(`Created ${this.role} ${username}`);
    }, (msg) => this.createError.set(msg));
  }

  async changeRole(u: User, role: Role): Promise<void> {
    if (role === u.role) {
      return;
    }
    if (u.id === this.me() && !(await this.confirmAlert(
      'Change your own role?', `You'll become ${role} and may lose access to this page.`, 'Change role'))) {
      await this.load(); // put the select back
      return;
    }
    await this.run(async () => {
      await firstValueFrom(this.api.updateUser(u.id, { role }));
      await this.toast(`${u.username} is now ${role}`);
    });
  }

  async toggleActive(u: User): Promise<void> {
    const disabling = u.is_active;
    const ok = await this.confirmAlert(
      disabling ? `Disable ${u.username}?` : `Enable ${u.username}?`,
      disabling
        ? (u.id === this.me() ? "That's you — you'll be logged out now." : 'They are logged out everywhere and can’t log in.')
        : 'They can log in again.',
      disabling ? 'Disable' : 'Enable',
    );
    if (!ok) {
      return;
    }
    await this.run(async () => {
      await firstValueFrom(this.api.updateUser(u.id, { is_active: !disabling }));
      await this.toast(`${u.username} ${disabling ? 'disabled' : 'enabled'}`);
    });
  }

  async endSessions(u: User): Promise<void> {
    if (!(await this.confirmAlert(`End all sessions of ${u.username}?`,
      u.id === this.me() ? "That includes this browser — you'll be logged out." : 'They must log in again.',
      'End sessions'))) {
      return;
    }
    await this.run(async () => {
      await firstValueFrom(this.api.revokeUserSessions(u.id));
      await this.toast(`Sessions of ${u.username} ended`);
    });
  }

  async resetPassword(u: User): Promise<void> {
    const alert = await this.alerts.create({
      header: `New password for ${u.username}`,
      message: 'At least 12 characters, entered twice. They must change it at next login and are logged out everywhere.',
      inputs: [
        { name: 'password', type: 'password', placeholder: 'New password', attributes: { autocomplete: 'new-password' } },
        { name: 'confirm', type: 'password', placeholder: 'New password again', attributes: { autocomplete: 'new-password' } },
      ],
      buttons: [
        { text: 'Cancel', role: 'cancel' },
        {
          text: 'Reset password',
          handler: (v: { password: string; confirm: string }) => {
            const problem = newPasswordProblem(v.password, v.confirm);
            if (problem) {
              void this.toast(problem, 'danger');
              return false; // keep the dialog open
            }
            void this.run(async () => {
              await firstValueFrom(this.api.resetPassword(u.id, v.password, v.confirm, true));
              await this.toast(`Password of ${u.username} reset`);
            });
            return true;
          },
        },
      ],
    });
    await alert.present();
  }

  /** Run a change, then reload; errors (e.g. "last active admin") shown as a toast or via `onError`. */
  private async run(fn: () => Promise<void>, onError?: (msg: string) => void): Promise<void> {
    this.busy.set(true);
    try {
      await fn();
    } catch (err) {
      const msg = errorMessage(err);
      if (onError) {
        onError(msg);
      } else {
        await this.toast(msg, 'danger');
      }
    } finally {
      this.busy.set(false);
      await this.load();
    }
  }

  private async confirmAlert(header: string, message: string, confirmText: string): Promise<boolean> {
    const alert = await this.alerts.create({
      header, message,
      buttons: [{ text: 'Cancel', role: 'cancel' }, { text: confirmText, role: 'confirm' }],
    });
    await alert.present();
    const { role } = await alert.onDidDismiss();
    return role === 'confirm';
  }

  private async toast(message: string, color: 'success' | 'danger' = 'success'): Promise<void> {
    const t = await this.toasts.create({ message, color, duration: 3000, position: 'bottom' });
    await t.present();
  }
}
