import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  IonBadge, IonButton, IonButtons, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonContent, IonHeader,
  IonInput, IonItem, IonList, IonMenuButton, IonNote, IonText, IonTitle, IonToolbar, ToastController,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { dateTime } from '../core/format';
import { SessionInfo } from '../core/models';

export const MIN_PASSWORD_LENGTH = 12;

/** Client-side check before sending (the server checks the same rules). */
export function newPasswordProblem(next: string, confirm: string): string | null {
  if (next.length < MIN_PASSWORD_LENGTH) {
    return `New password must be at least ${MIN_PASSWORD_LENGTH} characters`;
  }
  if (next !== confirm) {
    return 'New passwords do not match';
  }
  return null;
}

@Component({
  selector: 'app-account',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Account</ion-title>
      </ion-toolbar>
    </ion-header>
    <ion-content class="ion-padding">
      <div class="page-narrow">
        @if (auth.user(); as user) {
          <p><strong>{{ user.username }}</strong> · {{ user.role }}
            <span class="muted"> · last login {{ dateTime(user.last_login_at) }}</span></p>
        }
        @if (forced()) {
          <ion-note color="warning" class="notice">Please set a new password before continuing.</ion-note>
        }

        <ion-card>
          <ion-card-header><ion-card-title>Change password</ion-card-title></ion-card-header>
          <ion-card-content>
            <form (ngSubmit)="changePassword()">
              <ion-list lines="full">
                <ion-item>
                  <ion-input label="Current password" labelPlacement="stacked" type="password" name="current"
                             autocomplete="current-password" [(ngModel)]="current"></ion-input>
                </ion-item>
                <ion-item>
                  <ion-input label="New password (min. 12 characters)" labelPlacement="stacked" type="password"
                             name="next" autocomplete="new-password" [(ngModel)]="next"></ion-input>
                </ion-item>
                <ion-item>
                  <ion-input label="New password again" labelPlacement="stacked" type="password" name="confirm"
                             autocomplete="new-password" [(ngModel)]="confirm"></ion-input>
                </ion-item>
              </ion-list>
              @if (passwordError()) { <ion-text color="danger"><p>{{ passwordError() }}</p></ion-text> }
              <ion-button type="submit" [disabled]="saving() || !current || !next || !confirm">Change password</ion-button>
            </form>
            <p class="muted">Changing your password logs out your other devices.</p>
          </ion-card-content>
        </ion-card>

        <ion-card>
          <ion-card-header><ion-card-title>Active sessions</ion-card-title></ion-card-header>
          <ion-card-content>
            @if (sessionsError()) { <ion-text color="danger"><p>{{ sessionsError() }}</p></ion-text> }
            <div class="table-scroll">
              <table class="data">
                <thead><tr><th>Started</th><th>Last used</th><th>Expires</th><th>IP</th><th>Browser</th><th></th></tr></thead>
                <tbody>
                  @for (s of sessions(); track s.id) {
                    <tr>
                      <td>{{ dateTime(s.created_at) }}</td>
                      <td>{{ dateTime(s.last_used_at) }}</td>
                      <td>{{ dateTime(s.expires_at) }}</td>
                      <td>{{ s.ip ?? '' }}</td>
                      <td class="wrap ua">{{ s.user_agent ?? '' }}</td>
                      <td>
                        @if (s.current) { <ion-badge color="primary">this browser</ion-badge> }
                        @else { <ion-button size="small" fill="outline" color="danger" (click)="revoke(s)">End</ion-button> }
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </ion-card-content>
        </ion-card>

        <ion-button color="medium" fill="outline" (click)="auth.logout()">Log out</ion-button>
      </div>
    </ion-content>
  `,
  styles: [`.notice { display: block; margin-bottom: 12px; } .ua { max-width: 20rem; font-size: 0.8rem; }`],
  imports: [
    FormsModule, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonContent, IonCard, IonCardHeader,
    IonCardTitle, IonCardContent, IonList, IonItem, IonInput, IonButton, IonText, IonNote, IonBadge,
  ],
})
export class AccountPage implements OnInit {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastController);

  /** ?force=1 when the account must change its password (set by an admin) */
  readonly force = input<string>();

  readonly dateTime = dateTime;
  readonly sessions = signal<SessionInfo[]>([]);
  readonly sessionsError = signal<string | null>(null);
  readonly passwordError = signal<string | null>(null);
  readonly saving = signal(false);
  readonly forced = signal(false);
  current = '';
  next = '';
  confirm = '';

  ngOnInit(): void {
    this.forced.set(!!this.auth.user()?.must_change_password);
    void this.loadSessions();
  }

  async loadSessions(): Promise<void> {
    try {
      this.sessions.set(await firstValueFrom(this.api.sessions()));
      this.sessionsError.set(null);
    } catch (err) {
      this.sessionsError.set(errorMessage(err));
    }
  }

  async changePassword(): Promise<void> {
    const problem = newPasswordProblem(this.next, this.confirm);
    if (problem) {
      this.passwordError.set(problem);
      return;
    }
    this.saving.set(true);
    this.passwordError.set(null);
    try {
      await firstValueFrom(this.api.changePassword(this.current, this.next, this.confirm));
      this.current = this.next = this.confirm = '';
      this.auth.updateUser({ must_change_password: false });
      await (await this.toast.create({ message: 'Password changed', duration: 2000, color: 'success' })).present();
      await this.loadSessions();
      if (this.forced()) {
        this.forced.set(false);
        await this.router.navigate(['/inventory']);
      }
    } catch (err) {
      this.passwordError.set(
        err instanceof HttpErrorResponse && err.status === 403 ? 'Current password is wrong' : errorMessage(err));
    } finally {
      this.saving.set(false);
    }
  }

  async revoke(s: SessionInfo): Promise<void> {
    try {
      await firstValueFrom(this.api.revokeSession(s.id));
      await this.loadSessions();
    } catch (err) {
      this.sessionsError.set(errorMessage(err));
    }
  }
}
