import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import {
  IonApp, IonButton, IonContent, IonIcon, IonItem, IonLabel, IonList, IonListHeader, IonMenu, IonMenuToggle, IonNote,
  IonRouterOutlet, IonSplitPane,
} from '@ionic/angular';
import { addIcons } from 'ionicons';
import {
  chevronBackOutline, documentTextOutline, gridOutline, logOutOutline, peopleOutline, personCircleOutline, pinOutline,
  pulseOutline, refreshOutline, settingsOutline,
} from 'ionicons/icons';

import { AuthService } from './core/auth.service';
import { Role } from './core/models';

const PIN_KEY = 'pic.menuPinned';
const WIDTH_KEY = 'pic.menuWidth';
const WIDTH_DEFAULT = 270;
const WIDTH_MIN = 180;
const WIDTH_MAX = 480;

function clampWidth(px: number): number {
  return Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, Math.round(px)));
}

function readWidth(): number {
  try {
    const v = Number(localStorage.getItem(WIDTH_KEY));
    return v ? clampWidth(v) : WIDTH_DEFAULT;
  } catch {
    return WIDTH_DEFAULT;
  }
}

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
      <ion-split-pane contentId="main" when="md" [disabled]="!menuPinned()"
                      [style.--side-width]="menuWidth() + 'px'"
                      [style.--side-min-width]="menuWidth() + 'px'"
                      [style.--side-max-width]="menuWidth() + 'px'">
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
          @if (menuPinned()) {
            <!-- Drag to resize the pinned menu; double-click resets -->
            <div class="resize-handle" role="separator" aria-orientation="vertical" aria-label="Resize menu"
                 title="Drag to resize · double-click to reset"
                 (pointerdown)="startResize($event)" (dblclick)="setWidth(270)"></div>
          }
        </ion-menu>
        <ion-router-outlet id="main"></ion-router-outlet>
      </ion-split-pane>
    </ion-app>
  `,
  styles: [`
    .who { display: block; padding: 0 16px 12px; }
    ion-item.selected {
      --background: var(--ion-color-primary);
      --color: var(--ion-color-primary-contrast);
      font-weight: 600;
    }
    .resize-handle {
      position: absolute;
      top: 0;
      right: 0;
      width: 6px;
      height: 100%;
      z-index: 10;
      cursor: col-resize;
      touch-action: none;
    }
    .resize-handle:hover,
    .resize-handle.dragging { background: var(--ion-color-secondary); }
  `],
  imports: [
    IonApp, IonButton, IonSplitPane, IonMenu, IonContent, IonList, IonListHeader, IonNote, IonMenuToggle, IonItem, IonIcon,
    IonLabel, IonRouterOutlet, RouterLink, RouterLinkActive,
  ],
})
export class AppComponent {
  readonly auth = inject(AuthService);

  readonly menuPinned = signal(readPinned());
  readonly menuWidth = signal(readWidth());

  readonly menu: { title: string; url: string; icon: string; role?: Role }[] = [
    { title: 'Inventory', url: '/inventory', icon: 'grid-outline' },
    { title: 'Activity log', url: '/logs', icon: 'document-text-outline', role: 'operator' },
    { title: 'Users', url: '/users', icon: 'people-outline', role: 'admin' },
    { title: 'Settings', url: '/settings', icon: 'settings-outline', role: 'admin' },
    { title: 'Account', url: '/account', icon: 'person-circle-outline' },
  ];

  constructor() {
    addIcons({
      chevronBackOutline, documentTextOutline, gridOutline, logOutOutline, peopleOutline, personCircleOutline,
      pinOutline, pulseOutline, refreshOutline, settingsOutline,
    });
  }

  startResize(down: PointerEvent): void {
    const handle = down.target as HTMLElement;
    const menuLeft = (handle.parentElement?.getBoundingClientRect().left ?? 0);
    handle.setPointerCapture(down.pointerId);
    handle.classList.add('dragging');
    down.preventDefault();

    const move = (e: PointerEvent) => this.menuWidth.set(clampWidth(e.clientX - menuLeft));
    const up = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      handle.removeEventListener('pointercancel', up);
      handle.classList.remove('dragging');
      this.setWidth(this.menuWidth());
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', up);
  }

  setWidth(px: number): void {
    this.menuWidth.set(clampWidth(px));
    try {
      localStorage.setItem(WIDTH_KEY, String(this.menuWidth()));
    } catch {
      // storage unavailable — width lasts for this page load only
    }
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
