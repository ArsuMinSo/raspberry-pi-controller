import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  IonButton, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonContent, IonInput, IonItem, IonList, IonNote,
  IonSpinner, IonText,
} from '@ionic/angular';

import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';

@Component({
  selector: 'app-login',
  template: `
    <ion-content class="ion-padding">
      <ion-card class="login">
        <ion-card-header>
          <ion-card-title>Pi Controller</ion-card-title>
        </ion-card-header>
        <ion-card-content>
          @if (reason() === 'expired') {
            <ion-note color="warning" class="notice">Your session ended — please log in again.</ion-note>
          }
          <form (ngSubmit)="submit()">
            <ion-list lines="full">
              <ion-item>
                <ion-input label="Username" labelPlacement="stacked" name="username" autocomplete="username"
                           [(ngModel)]="username" required [disabled]="busy()"></ion-input>
              </ion-item>
              <ion-item>
                <ion-input label="Password" labelPlacement="stacked" type="password" name="password"
                           autocomplete="current-password" [(ngModel)]="password" required
                           [disabled]="busy()"></ion-input>
              </ion-item>
            </ion-list>
            @if (error()) {
              <ion-text color="danger"><p>{{ error() }}</p></ion-text>
            }
            <ion-button type="submit" expand="block" [disabled]="busy() || !username || !password">
              @if (busy()) { <ion-spinner name="dots"></ion-spinner> } @else { Log in }
            </ion-button>
          </form>
        </ion-card-content>
      </ion-card>
    </ion-content>
  `,
  styles: [`
    .login { max-width: 420px; margin: 10vh auto 0; }
    .notice { display: block; margin-bottom: 12px; }
  `],
  imports: [
    FormsModule, IonContent, IonCard, IonCardHeader, IonCardTitle, IonCardContent, IonList, IonItem, IonInput,
    IonButton, IonSpinner, IonText, IonNote,
  ],
})
export class LoginPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  /** ?reason=expired from AuthService.endSession */
  readonly reason = input<string>();

  username = '';
  password = '';
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  async submit(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      const user = await this.auth.login(this.username.trim(), this.password);
      this.password = '';
      await this.router.navigate(user.must_change_password ? ['/account'] : ['/inventory'],
        user.must_change_password ? { queryParams: { force: 1 } } : {});
    } catch (err) {
      if (err instanceof HttpErrorResponse && err.status === 401) {
        this.error.set('Wrong username or password');
      } else if (err instanceof HttpErrorResponse && err.status === 429) {
        this.error.set('Too many failed logins — try again in 15 minutes');
      } else {
        this.error.set(errorMessage(err));
      }
    } finally {
      this.busy.set(false);
    }
  }
}
