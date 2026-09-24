import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import {
  IonApp, IonButton, IonContent, IonIcon, IonItem, IonLabel, IonList, IonListHeader, IonMenu, IonMenuToggle, IonNote,
  IonRouterOutlet, IonSplitPane,
} from '@ionic/angular';
import { addIcons } from 'ionicons';
import {
  chevronBackOutline, documentTextOutline, gridOutline, logOutOutline, personCircleOutline, pinOutline, pulseOutline,
  refreshOutline,
} from 'ionicons/icons';

import { AuthService } from './core/auth.service';
import { Role } from './core/models';

const PIN_KEY = 'pic.menuPinned';

/** Menu pinned open on wide screens? Per-browser preference; storage may be unavailable. */
function readPinned(): boolean {
  try {
    return localStorage.getItem(PIN_KEY) !== '0';
  } catch {
    return true;
  }
}

@Component({
  selector: 'app-root',
  template: `
    <ion-app>
      <!-- Pinned: menu always visible from 768 px. Collapsed: overlay, opened with ☰ -->
      <ion-split-pane contentId="main" when="md" [disabled]="!menuPinned()">
        <ion-menu contentId="main" type="overlay" [disabled]="!auth.loggedIn()">
          <ion-content>
            <ion-list lines="none">
              <ion-list-header>
                <ion-label>Pi Controller</ion-label>
                <ion-button fill="clear" size="small" (click)="togglePinned()"
                            [attr.aria-label]="menuPinned() ? 'Collapse menu' : 'Keep menu open'"
                            [title]="menuPinned() ? 'Collapse menu' : 'Keep menu open'">
                  <ion-icon slot="icon-only" [name]="menuPinned() ? 'chevron-back-outline' : 'pin-outline'"></ion-icon>
                </ion-button>
              </ion-list-header>
              @if (auth.user(); as user) {
                <ion-note class="who">{{ user.username }} · {{ user.role }}</ion-note>
              }
              @for (item of menu; track item.url) {
                @if (!item.role || auth.can(item.role)) {
                  <ion-menu-toggle [autoHide]="false">
                    <ion-item [routerLink]="item.url" routerLinkActive="selected" detail="false" button>
                      <ion-icon slot="start" [name]="item.icon"></ion-icon>
                      <ion-label>{{ item.title }}</ion-label>
                    </ion-item>
                  </ion-menu-toggle>
                }
              }
              <ion-menu-toggle [autoHide]="false">
                <ion-item button detail="false" (click)="auth.logout()">
                  <ion-icon slot="start" name="log-out-outline"></ion-icon>
                  <ion-label>Log out</ion-label>
                </ion-item>
              </ion-menu-toggle>
            </ion-list>
          </ion-content>
        </ion-menu>
        <ion-router-outlet id="main"></ion-router-outlet>
      </ion-split-pane>
    </ion-app>
  `,
  styles: [`
    .who { display: block; padding: 0 16px 12px; }
    ion-item.selected { --color: var(--ion-color-primary); font-weight: 600; }
  `],
  imports: [
    IonApp, IonButton, IonSplitPane, IonMenu, IonContent, IonList, IonListHeader, IonNote, IonMenuToggle, IonItem, IonIcon,
    IonLabel, IonRouterOutlet, RouterLink, RouterLinkActive,
  ],
})
export class AppComponent {
  readonly auth = inject(AuthService);

  readonly menuPinned = signal(readPinned());

  readonly menu: { title: string; url: string; icon: string; role?: Role }[] = [
    { title: 'Inventory', url: '/inventory', icon: 'grid-outline' },
    { title: 'Activity log', url: '/logs', icon: 'document-text-outline', role: 'operator' },
    { title: 'Account', url: '/account', icon: 'person-circle-outline' },
  ];

  constructor() {
    addIcons({
      chevronBackOutline, documentTextOutline, gridOutline, logOutOutline, personCircleOutline, pinOutline,
      pulseOutline, refreshOutline,
    });
  }

  togglePinned(): void {
    const pinned = !this.menuPinned();
    this.menuPinned.set(pinned);
    try {
      localStorage.setItem(PIN_KEY, pinned ? '1' : '0');
    } catch {
      // storage unavailable (private mode) — preference lasts for this page load only
    }
  }
}
