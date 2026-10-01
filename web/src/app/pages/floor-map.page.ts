import { Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import {
  IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonMenuButton, IonSpinner, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { errorMessage } from '../core/errors';
import { AccessPointOut, FloorMapEdge, FloorMapPiNode, FloorMapResponse } from '../core/models';

/** View-box is a fixed logical size; drag positions are stored in these units. */
const VIEW_W = 1000;
const VIEW_H = 700;
const UNPLACED_ROW_Y = 40;

/** RSSI range used to turn a signal reading into an edge weight (0..1). Typical indoor WiFi: ~-30 (strong) to ~-90 (weak). */
const RSSI_STRONG = -30;
const RSSI_WEAK = -90;

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
    <ion-content class="ion-padding graph-bg">
      @if (error()) { <ion-text color="danger"><p>{{ error() }}</p></ion-text> }
      @if (statusMsg()) { <ion-text color="medium"><p>{{ statusMsg() }}</p></ion-text> }
      @if (loading() && !map()) {
        <div class="ion-text-center"><ion-spinner></ion-spinner></div>
      }

      @if (map(); as m) {
        <p class="hint">
          Drag an access point to place/reposition it. Unplaced APs (seen in a scan, never placed) sit in the
          staging row at the top. Pi position is estimated from the latest WiFi scan and isn't draggable.
          Line thickness/brightness = signal strength; node size = number of connections.
        </p>

        <div class="filter-row">
          <ion-button fill="outline" size="small" [color]="showConnections() ? 'primary' : 'medium'"
                      (click)="showConnections.set(!showConnections())">Connections</ion-button>
          <ion-button fill="outline" size="small" [color]="showAps() ? 'primary' : 'medium'"
                      (click)="showAps.set(!showAps())">APs</ion-button>
          <ion-button fill="outline" size="small" [color]="showPis() ? 'primary' : 'medium'"
                      (click)="showPis.set(!showPis())">Pis</ion-button>
          <ion-button fill="outline" size="small" (click)="toggleFullscreen()">
            <ion-icon slot="icon-only" [name]="fullscreen() ? 'contract-outline' : 'expand-outline'"></ion-icon>
          </ion-button>
        </div>

        <div class="map-wrap" #mapWrap [class.fullscreen]="fullscreen()">
          <svg
            [attr.viewBox]="'0 0 ' + viewW + ' ' + viewH"
            class="map-canvas"
            preserveAspectRatio="xMidYMid meet"
            (pointermove)="onPointerMove($event)"
            (pointerup)="onPointerUp()"
            (pointerleave)="onPointerUp()"
          >
            <line x1="0" [attr.y1]="UNPLACED_ROW_Y + 25" [attr.x2]="viewW" [attr.y2]="UNPLACED_ROW_Y + 25"
                  class="staging-divider" />

            @if (showConnections()) {
              @for (e of visibleEdges(); track e.position + e.bssid) {
                <line [attr.x1]="e.x1" [attr.y1]="e.y1" [attr.x2]="e.x2" [attr.y2]="e.y2"
                      class="edge" [attr.stroke-width]="e.width" [style.opacity]="e.opacity" />
              }
            }

            @if (showPis()) {
              @for (pi of piNodes(); track pi.mac) {
                @if (pi.x !== null && pi.y !== null) {
                  <g [attr.transform]="'translate(' + pi.x + ',' + pi.y + ')'" class="pi-node">
                    <circle [attr.r]="nodeRadius(piDegree(pi.position))" />
                    <text [attr.y]="-(nodeRadius(piDegree(pi.position)) + 6)" text-anchor="middle">{{ pi.position }}</text>
                  </g>
                }
              }
            }

            @if (showAps()) {
              @for (ap of apNodes(); track ap.bssid) {
                <g [attr.transform]="'translate(' + dragPos(ap) + ')'"
                   class="ap-node" [class.ap-unplaced]="ap.x === null"
                   (pointerdown)="onPointerDown($event, ap)">
                  <title>{{ apTitle(ap) }}</title>
                  <circle [attr.r]="nodeRadius(apDegree(ap.bssid))" />
                  <text [attr.y]="-(nodeRadius(apDegree(ap.bssid)) + 6)" text-anchor="middle">{{ apLabel(ap) }}</text>
                </g>
              }
            }
          </svg>
        </div>

        @if (unplacedCount() > 0) {
          <p class="hint">{{ unplacedCount() }} access point(s) not yet placed — drag from the staging row above.</p>
        }
      }
    </ion-content>
  `,
  styles: [`
    .hint { color: var(--ion-color-medium); font-size: 0.85rem; margin: 4px 0 12px; }

    .graph-bg { --background: #1b1b1f; }

    .filter-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 10px; }

    .map-wrap {
      width: 100%;
      max-width: 1400px;
      margin: 0 auto;
      aspect-ratio: 1000 / 700;
      max-height: 82vh;
    }
    .map-wrap.fullscreen {
      max-width: none;
      max-height: none;
      width: 100vw;
      height: 100vh;
      aspect-ratio: auto;
    }
    .map-canvas {
      width: 100%;
      height: 100%;
      display: block;
      background: radial-gradient(circle at 50% 45%, #262630 0%, #19191d 75%);
      border: 1px solid #33333c;
      border-radius: 10px;
      touch-action: none;
    }
    .map-wrap.fullscreen .map-canvas { border-radius: 0; }
    .staging-divider { stroke: #3a3a44; stroke-dasharray: 4 4; }

    .edge { stroke: #7fd8d0; stroke-linecap: round; transition: opacity 0.3s ease; }

    .pi-node circle {
      fill: #5b8cff;
      stroke: #a9c1ff;
      stroke-width: 1.5;
      filter: drop-shadow(0 0 4px rgba(91, 140, 255, 0.65));
    }
    .pi-node text { font-size: 11px; fill: #d6def5; }

    .ap-node { cursor: grab; }
    .ap-node circle {
      fill: #ffb454;
      stroke: #ffd9a0;
      stroke-width: 1.5;
      filter: drop-shadow(0 0 4px rgba(255, 180, 84, 0.6));
    }
    .ap-node.ap-unplaced circle {
      fill: #7d7d88;
      stroke: #a3a3ae;
      filter: none;
    }
    .ap-node text { font-size: 10px; fill: #d6def5; pointer-events: none; }

    @media (max-width: 600px) {
      .map-wrap { max-height: 68vh; }
      .pi-node text, .ap-node text { font-size: 13px; }
    }
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
  readonly edges = signal<FloorMapEdge[]>([]);
  readonly unplacedCount = signal(0);

  readonly showConnections = signal(true);
  readonly showAps = signal(true);
  readonly showPis = signal(true);
  readonly fullscreen = signal(false);
  private readonly mapWrap = viewChild<ElementRef<HTMLDivElement>>('mapWrap');

  private dragging: { bssid: string; x: number; y: number } | null = null;
  private svgEl: SVGSVGElement | null = null;

  constructor() {
    this.load();
    document.addEventListener('fullscreenchange', () => {
      this.fullscreen.set(document.fullscreenElement === this.mapWrap()?.nativeElement);
    });
  }

  async toggleFullscreen(): Promise<void> {
    const el = this.mapWrap()?.nativeElement;
    if (!el) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await el.requestFullscreen();
    }
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
      this.edges.set(m.edges);
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

  /** Node size reflects its connection count, like Obsidian's graph view. */
  nodeRadius(degree: number): number {
    return Math.min(6 + degree * 1.5, 16);
  }

  /** Primary name + "(+N more)" when the BSSID has broadcast more than one SSID across scans. */
  apLabel(ap: AccessPointOut): string {
    const name = ap.ssid || ap.bssid;
    const extra = ap.ssids.length - (ap.ssid ? 1 : 0);
    return extra > 0 ? `${name} (+${extra})` : name;
  }

  apTitle(ap: AccessPointOut): string {
    return ap.ssids.length > 0 ? ap.ssids.join(', ') : ap.bssid;
  }

  piDegree(position: string): number {
    return this.edges().filter((e) => e.position === position).length;
  }

  apDegree(bssid: string): number {
    return this.edges().filter((e) => e.bssid === bssid).length;
  }

  /** Edges with both endpoints resolved to canvas coordinates, weighted by RSSI (stroke width/opacity). */
  visibleEdges(): Array<FloorMapEdge & { x1: number; y1: number; x2: number; y2: number; width: number; opacity: number }> {
    const piByPosition = new Map(this.piNodes().map((p) => [p.position, p]));
    const apByBssid = new Map(this.apNodes().map((a) => [a.bssid, a]));
    const out: Array<FloorMapEdge & { x1: number; y1: number; x2: number; y2: number; width: number; opacity: number }> = [];
    for (const e of this.edges()) {
      const pi = piByPosition.get(e.position);
      const ap = apByBssid.get(e.bssid);
      if (!pi || pi.x === null || pi.y === null || !ap) continue;
      const [ax, ay] = this.dragPos(ap).split(',').map(Number);
      if (ax === null || ay === null || Number.isNaN(ax) || Number.isNaN(ay)) continue;
      const strength = this.rssiStrength(e.rssi);
      out.push({ ...e, x1: pi.x, y1: pi.y, x2: ax, y2: ay, width: 0.5 + strength * 3, opacity: 0.15 + strength * 0.6 });
    }
    return out;
  }

  private rssiStrength(rssi: number): number {
    const clamped = Math.min(Math.max(rssi, RSSI_WEAK), RSSI_STRONG);
    return (clamped - RSSI_WEAK) / (RSSI_STRONG - RSSI_WEAK);
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
