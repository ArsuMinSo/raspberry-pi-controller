import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  IonButton, IonButtons, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonContent, IonHeader, IonInput,
  IonItem, IonList, IonMenuButton, IonNote, IonText, IonTitle, IonToolbar, ToastController,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { errorMessage } from '../core/errors';
import { NetworkSettings, Settings, SSHSettings, SSHTestResult } from '../core/models';

@Component({
  selector: 'app-settings',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Settings</ion-title>
      </ion-toolbar>
    </ion-header>
    <ion-content class="ion-padding">
      <div class="page-narrow">
        @if (error()) { <ion-text color="danger"><p>{{ error() }}</p></ion-text> }
        @if (!loaded()) { <p>Loading…</p> }
        @if (loaded()) {
          <form (ngSubmit)="save()">
            <!-- SSH Settings -->
            <ion-card>
              <ion-card-header><ion-card-title>SSH Settings</ion-card-title></ion-card-header>
              <ion-card-content>
                <ion-list lines="full">
                  <ion-item>
                    <ion-input label="Private key path" labelPlacement="stacked"
                               name="key_path" [(ngModel)]="ssh.key_path" [disabled]="saving()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-input label="SSH username" labelPlacement="stacked"
                               name="username" [(ngModel)]="ssh.username" [disabled]="saving()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-input label="Connection timeout (seconds)" labelPlacement="stacked" type="number"
                               name="timeout_s" [(ngModel)]="ssh.timeout_s" [disabled]="saving()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-input label="Retry count" labelPlacement="stacked" type="number"
                               name="retry_count" [(ngModel)]="ssh.retry_count" [disabled]="saving()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-input label="Retry delay (seconds)" labelPlacement="stacked" type="number"
                               name="retry_delay_s" [(ngModel)]="ssh.retry_delay_s" [disabled]="saving()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-input label="Max parallel connections" labelPlacement="stacked" type="number"
                               name="parallel_limit" [(ngModel)]="ssh.parallel_limit" [disabled]="saving()"></ion-input>
                  </ion-item>
                </ion-list>
                <div style="display: flex; gap: 8px; margin-top: 16px;">
                  <ion-input label="Test IP" labelPlacement="floating" [(ngModel)]="testIP" name="testIP"
                             [disabled]="savingTest()" style="flex: 1;"></ion-input>
                  <ion-button (click)="testConnection()" [disabled]="!testIP() || savingTest()" color="secondary">
                    {{ savingTest() ? 'Testing…' : 'Test' }}
                  </ion-button>
                </div>
                @if (testResult()) {
                  <div style="margin-top: 16px;">
                    @if (testResult()!.success) {
                      <ion-note color="success"><p>✓ Connection successful</p></ion-note>
                    } @else {
                      <ion-note color="danger">
                        <p><strong>{{ testResult()!.error_type }}</strong></p>
                        <p>{{ testResult()!.error }}</p>
                      </ion-note>
                    }
                  </div>
                }
              </ion-card-content>
            </ion-card>

            <!-- Network Settings -->
            <ion-card>
              <ion-card-header><ion-card-title>Network & Discovery</ion-card-title></ion-card-header>
              <ion-card-content>
                <ion-list lines="full">
                  <ion-item>
                    <ion-input label="Subnet / IP range" labelPlacement="stacked"
                               name="subnet" [(ngModel)]="network.subnet" [disabled]="saving()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-input label="SSH probe username" labelPlacement="stacked"
                               name="probe_username" [(ngModel)]="network.probe_username" [disabled]="saving()"></ion-input>
                  </ion-item>
                  <ion-item>
                    <ion-input label="SSH probe timeout (seconds)" labelPlacement="stacked" type="number"
                               name="probe_timeout_s" [(ngModel)]="network.probe_timeout_s" [disabled]="saving()"></ion-input>
                  </ion-item>
                </ion-list>
              </ion-card-content>
            </ion-card>

            <!-- Save -->
            <ion-button type="submit" [disabled]="saving() || !changed()">
              {{ saving() ? 'Saving…' : 'Save changes' }}
            </ion-button>
            @if (saveError()) { <ion-text color="danger"><p>{{ saveError() }}</p></ion-text> }
            @if (saved()) { <ion-note color="success"><p>✓ Settings saved</p></ion-note> }
          </form>
        }
      </div>
    </ion-content>
  `,
  styles: [`
    .page-narrow { max-width: 50rem; }
    div[style*="flex"] { display: flex; align-items: center; }
  `],
  imports: [
    FormsModule, IonHeader, IonToolbar, IonButtons, IonMenuButton, IonTitle, IonContent, IonCard, IonCardHeader,
    IonCardTitle, IonCardContent, IonList, IonItem, IonInput, IonButton, IonText, IonNote,
  ],
})
export class SettingsPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastController);

  readonly loaded = signal(false);
  readonly saving = signal(false);
  readonly savingTest = signal(false);
  readonly error = signal<string | null>(null);
  readonly saveError = signal<string | null>(null);
  readonly saved = signal(false);
  readonly testResult = signal<SSHTestResult | null>(null);
  readonly testIP = signal('');

  readonly ssh: SSHSettings = { key_path: '', username: '', timeout_s: 0, retry_count: 0, retry_delay_s: 0, parallel_limit: 0 };
  readonly network: NetworkSettings = { subnet: '', probe_ssh: false, probe_timeout_s: 0, probe_username: '', probe_auth: 'key', probe_deploy_key: false };
  private original: Settings | null = null;

  readonly changed = signal(false);

  constructor() {
    // Track changes in SSH/network settings
    effect(() => {
      if (!this.original) return;
      const currentSettings: Settings = { ssh: { ...this.ssh }, network: { ...this.network } };
      const hasChanged = JSON.stringify(this.original) !== JSON.stringify(currentSettings);
      this.changed.set(hasChanged);
    });
  }

  ngOnInit(): void {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      this.loaded.set(false);
      const settings = await firstValueFrom(this.api.getSettings());
      this.original = JSON.parse(JSON.stringify(settings));
      Object.assign(this.ssh, settings.ssh);
      Object.assign(this.network, settings.network);
      this.error.set(null);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.loaded.set(true);
    }
  }

  async save(): Promise<void> {
    this.saving.set(true);
    this.saveError.set(null);
    this.saved.set(false);
    try {
      const patch: Partial<Settings> = {
        ssh: { ...this.ssh },
        network: { ...this.network },
      };
      const result = await firstValueFrom(this.api.patchSettings(patch));
      this.original = JSON.parse(JSON.stringify(result));
      this.changed.set(false);
      this.saved.set(true);
      await (await this.toast.create({ message: 'Settings saved', duration: 2000, color: 'success' })).present();
    } catch (err) {
      this.saveError.set(errorMessage(err));
    } finally {
      this.saving.set(false);
    }
  }

  async testConnection(): Promise<void> {
    const ip = this.testIP().trim();
    if (!ip) return;
    this.savingTest.set(true);
    this.testResult.set(null);
    try {
      const result = await firstValueFrom(this.api.testSSH(ip));
      this.testResult.set(result);
    } catch (err) {
      this.testResult.set({
        ip,
        success: false,
        settings_used: this.ssh,
        error: errorMessage(err),
        error_type: err instanceof HttpErrorResponse ? `HTTP ${err.status}` : 'Error',
        stdout: null,
      });
    } finally {
      this.savingTest.set(false);
    }
  }
}
