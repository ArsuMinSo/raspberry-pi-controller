import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import {
  IonApp, IonContent, IonIcon, IonItem, IonLabel, IonList, IonListHeader, IonMenu, IonMenuToggle, IonNote,
  IonRouterOutlet, IonSplitPane,
} from '@ionic/angular';
import { addIcons } from 'ionicons';
import {
  documentTextOutline, gridOutline, logOutOutline, personCircleOutline, pulseOutline, refreshOutline,
} from 'ionicons/icons';

import { AuthService } from './core/auth.service';

@Component({
  selector: 'app-root',
  template: `
    <ion-app>
      <ion-split-pane contentId="main" when="lg">
        <ion-menu contentId="main" type="overlay" [disabled]="!auth.loggedIn()">
          <ion-content>
            <ion-list lines="none">
              <ion-list-header>Pi Controller</ion-list-header>
              @if (auth.user(); as user) {
                <ion-note class="who">{{ user.username }} · {{ user.role }}</ion-note>
              }
              @for (item of menu; track item.url) {
                <ion-menu-toggle [autoHide]="false">
                  <ion-item [routerLink]="item.url" routerLinkActive="selected" detail="false" button>
                    <ion-icon slot="start" [name]="item.icon"></ion-icon>
                    <ion-label>{{ item.title }}</ion-label>
                  </ion-item>
                </ion-menu-toggle>
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
    IonApp, IonSplitPane, IonMenu, IonContent, IonList, IonListHeader, IonNote, IonMenuToggle, IonItem, IonIcon,
    IonLabel, IonRouterOutlet, RouterLink, RouterLinkActive,
  ],
})
export class AppComponent {
  readonly auth = inject(AuthService);

  readonly menu = [
    { title: 'Inventory', url: '/inventory', icon: 'grid-outline' },
    { title: 'Activity log', url: '/logs', icon: 'document-text-outline' },
    { title: 'Account', url: '/account', icon: 'person-circle-outline' },
  ];

  constructor() {
    addIcons({ documentTextOutline, gridOutline, logOutOutline, personCircleOutline, pulseOutline, refreshOutline });
  }
}
