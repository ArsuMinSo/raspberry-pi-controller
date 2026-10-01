import { Component, inject, signal } from '@angular/core';
import {
  IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonMenuButton, IonSpinner, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { errorMessage } from '../core/errors';
import { AccessPointOut, FloorMapPiNode, FloorMapResponse } from '../core/models';

/** View-box is a fixed logical size; drag positions are stored in these units. */
const VIEW_W = 1000;
const VIEW_H = 700;
const UNPLACED_ROW_Y = 40;

@Component({
  selector: 'app-floor-map',
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Floor Map</ion-title>
        <ion-buttons slot="end">
          <ion-button (click)="scanWifi()" [disabled]="scanning()">WiFi scan</ion-button>
          <ion-button (click)="scanBle()" [disabled]="scanning()">BLE scan</ion-button>
          <ion-button (click)="load()" [disabled]="loading()" aria-label="Refresh">
            <ion-icon slot="icon-only" name="refresh-outline"></ion-icon>
          </ion-button>
        </ion-buttons>
      </ion-toolbar>
    </ion-header>
    <ion-content class="ion-padding">
      @if (error()) { <ion-text color="danger"><p>{{ error() }}</p></ion-text> }
      @if (statusMsg()) { <ion-text color="medium"><p>{{ statusMsg() }}</p></ion-text> }
      @if (loading() && !map()) {
        <div class="ion-text-center"><ion-spinner></ion-spinner></div>
      }

      @if (map(); as m) {
        <p class="hint">
          Drag an access point to place/reposition it. Unplaced APs (seen in a scan, never placed) sit in the
          staging row at the top. Pi position is estimated from the latest WiFi scan and isn't draggable.
        </p>

        <svg
          [attr.viewBox]="'0 0 ' + viewW + ' ' + viewH"
          class="map-canvas"
          (pointermove)="onPointerMove($event)"
          (pointerup)="onPointerUp()"
          (pointerleave)="onPointerUp()"
        >
          <line x1="0" [attr.y1]="UNPLACED_ROW_Y + 25" [attr.x2]="viewW" [attr.y2]="UNPLACED_ROW_Y + 25"
                class="staging-divider" />

          @for (pi of piNodes(); track pi.mac) {
            @if (pi.x !== null && pi.y !== null) {
              <g [attr.transform]="'translate(' + pi.x + ',' + pi.y + ')'" class="pi-node">
                <circle r="10" />
                <text y="-16" text-anchor="middle">{{ pi.position }}</text>
              </g>
            }
          }

          @for (ap of apNodes(); track ap.bssid) {
            <g [attr.transform]="'translate(' + dragPos(ap) + ')'"
               class="ap-node" [class.ap-unplaced]="ap.x === null"
               (pointerdown)="onPointerDown($event, ap)">
              <rect x="-9" y="-9" width="18" height="18" />
              <text y="-14" text-anchor="middle">{{ ap.ssid || ap.bssid }}</text>
            </g>
          }
        </svg>

        @if (unplacedCount() > 0) {
          <p class="hint">{{ unplacedCount() }} access point(s) not yet placed — drag from the staging row above.</p>
        }
      }
    </ion-content>
  `,
  styles: [`
    .hint { color: var(--ion-color-medium); font-size: 0.85rem; margin: 4px 0 12px; }
    .map-canvas {
      width: 100%;
      height: 70vh;
      background: var(--ion-color-light, #f4f4f4);
      border: 1px solid var(--ion-color-step-200, #ddd);
      border-radius: 8px;
      touch-action: none;
    }
    .staging-divider { stroke: var(--ion-color-step-300, #ccc); stroke-dasharray: 4 4; }
    .pi-node circle { fill: var(--ion-color-primary, #3880ff); }
    .pi-node text { font-size: 11px; fill: var(--ion-color-dark, #222); }
    .ap-node { cursor: grab; }
    .ap-node rect { fill: var(--ion-color-warning, #ffc409); stroke: #8a6d00; stroke-width: 1; }
    .ap-node.ap-unplaced rect { fill: var(--ion-color-medium, #92949c); stroke: #555; }
    .ap-node text { font-size: 10px; fill: var(--ion-color-dark, #222); pointer-events: none; }
  `],
  imports: [IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonMenuButton, IonSpinner, IonText, IonTitle, IonToolbar],
})
export class FloorMapPage {
  private readonly api = inject(ApiService);

  readonly viewW = VIEW_W;
  readonly viewH = VIEW_H;
  readonly UNPLACED_ROW_Y = UNPLACED_ROW_Y;

  readonly map = signal<FloorMapResponse | null>(null);
  readonly loading = signal(false);
  readonly scanning = signal(false);
  readonly error = signal('');
  readonly statusMsg = signal('');

  readonly piNodes = signal<FloorMapPiNode[]>([]);
  readonly apNodes = signal<AccessPointOut[]>([]);
  readonly unplacedCount = signal(0);

  private dragging: { bssid: string; x: number; y: number } | null = null;
  private svgEl: SVGSVGElement | null = null;

  constructor() {
    this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    try {
      const m = await firstValueFrom(this.api.floorMap());
      this.map.set(m);
      this.piNodes.set(m.pis);
      const unplaced = m.access_points.filter((a) => a.x === null || a.y === null);
      const placed = m.access_points.filter((a) => a.x !== null && a.y !== null);
      // Lay unplaced APs out along the staging row so they don't overlap
      const staged = unplaced.map((a, i) => ({ ...a, x: 40 + i * 60, y: UNPLACED_ROW_Y }));
      this.apNodes.set([...placed, ...staged]);
      this.unplacedCount.set(unplaced.length);
    } catch (e) {
      this.error.set(errorMessage(e));
    } finally {
      this.loading.set(false);
    }
  }

  async scanWifi(): Promise<void> {
    await this.runScan(() => this.api.floorMapWifiScanAll(), 'WiFi scan queued');
  }

  async scanBle(): Promise<void> {
    await this.runScan(() => this.api.floorMapBleScanAll(), 'BLE scan queued');
  }

  private async runScan(fn: () => ReturnType<ApiService['floorMapWifiScanAll']>, msg: string): Promise<void> {
    this.scanning.set(true);
    this.error.set('');
    try {
      await firstValueFrom(fn());
      this.statusMsg.set(`${msg} — refresh in a few seconds to see results.`);
    } catch (e) {
      this.error.set(errorMessage(e));
    } finally {
      this.scanning.set(false);
    }
  }

  dragPos(ap: AccessPointOut): string {
    if (this.dragging && this.dragging.bssid === ap.bssid) {
      return `${this.dragging.x},${this.dragging.y}`;
    }
    return `${ap.x},${ap.y}`;
  }

  onPointerDown(event: PointerEvent, ap: AccessPointOut): void {
    this.svgEl = (event.currentTarget as SVGGraphicsElement).ownerSVGElement;
    const pt = this.toViewBox(event);
    if (!pt) return;
    this.dragging = { bssid: ap.bssid, x: pt.x, y: pt.y };
  }

  onPointerMove(event: PointerEvent): void {
    if (!this.dragging) return;
    const pt = this.toViewBox(event);
    if (!pt) return;
    this.dragging = { ...this.dragging, x: pt.x, y: pt.y };
  }

  async onPointerUp(): Promise<void> {
    if (!this.dragging) return;
    const { bssid, x, y } = this.dragging;
    this.dragging = null;
    try {
      await firstValueFrom(this.api.placeAccessPoint(bssid, x, y));
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  private toViewBox(event: PointerEvent): { x: number; y: number } | null {
    if (!this.svgEl) return null;
    const rect = this.svgEl.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * VIEW_W;
    const y = ((event.clientY - rect.top) / rect.height) * VIEW_H;
    return { x: Math.round(x), y: Math.round(y) };
  }
}
