import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  ActionSheetController, AlertController, IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonInput, IonLabel,
  IonMenuButton, IonRange, IonSpinner, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { errorMessage } from '../core/errors';
import { AccessPointOut, FloorMapEdge, FloorMapPiNode, FloorMapResponse, PiBleEdge } from '../core/models';

/** View-box is a fixed logical size; drag positions are stored in these units. */
const VIEW_W = 1000;
const VIEW_H = 700;

/** Factory floor plan background (rendered once from the Visio-exported PDF via poppler,
 * see web/src/assets/floor-map/plan.jpg) — sized to fit inside the view box at its native
 * 2200x2410 aspect ratio, letterboxed and centered rather than stretched so it isn't distorted. */
const FLOOR_PLAN_IMG_W = Math.round(VIEW_H * (2200 / 2410));
const FLOOR_PLAN_IMG = {
  src: 'assets/floor-map/plan.jpg',
  w: FLOOR_PLAN_IMG_W,
  h: VIEW_H,
  x: Math.round((VIEW_W - FLOOR_PLAN_IMG_W) / 2),
};
const UNPLACED_ROW_Y = 40;

/** RSSI range used to turn a signal reading into an edge weight (0..1). Typical indoor WiFi: ~-30 (strong) to ~-90 (weak). */
const RSSI_STRONG = -30;
const RSSI_WEAK = -90;

/** One physical AP box — may represent several BSSIDs manually grouped together (click an AP to manage). */
interface ApGroup {
  key: string;
  bssids: string[];
  ssids: string[];
  x: number | null;
  y: number | null;
  /** False once staged with synthetic x/y for the staging row — x/y are non-null either way. */
  placed: boolean;
  /** Fixed for untangle; set/cleared from the AP sheet. */
  pinned: boolean;
}

@Component({
  selector: 'app-floor-map',
  template: `
    <ion-header [class.fs-hidden]="fullscreen()">
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button></ion-menu-button></ion-buttons>
        <ion-title>Floor Map</ion-title>
        <ion-buttons slot="end">
          @if (canOperate) {
            <ion-button (click)="scanWifi()" [disabled]="scanning()">WiFi scan</ion-button>
            <ion-button (click)="scanBle()" [disabled]="scanning()">BLE scan</ion-button>
          }
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
        <p class="hint" [class.fs-hidden]="fullscreen()">
          Drag an access point to place/reposition it; click (without dragging) to group it with other APs that
          are really the same router. Unplaced APs (seen in a scan, never placed) sit in the staging row at the
          top. Pi position is estimated from the latest WiFi scan; a Pi with no WiFi position yet falls back to
          its BLE sightings of other (already-positioned) Pis — dashed purple "BLE links" below. Click a Pi to open
          a sheet with its MAC and IP (View details from there); drag one to pin it in place (yellow ring) — a
          pinned Pi's sheet also offers release (admins also get "Identify", popping its hostname/IP/MAC on its own
          screen). Clicking an AP shows its MAC(s) in the sheet. Scroll to zoom. Line
          thickness/brightness = signal strength; node size = number of connections.
        </p>

        <div class="filter-row" [class.fs-hidden]="fullscreen()">
          <ion-button fill="outline" size="small" [color]="showConnections() ? 'primary' : 'medium'"
                      (click)="showConnections.set(!showConnections())">Connections</ion-button>
          <ion-button fill="outline" size="small" [color]="showAps() ? 'primary' : 'medium'"
                      (click)="showAps.set(!showAps())">APs</ion-button>
          <ion-button fill="outline" size="small" [color]="showPis() ? 'primary' : 'medium'"
                      (click)="showPis.set(!showPis())">Pis</ion-button>
          <ion-button fill="outline" size="small" [color]="showBleLinks() ? 'primary' : 'medium'"
                      (click)="showBleLinks.set(!showBleLinks())">BLE links</ion-button>
          <ion-button fill="outline" size="small" [color]="showFloorPlan() ? 'primary' : 'medium'"
                      (click)="toggleFloorPlan()">Floor plan</ion-button>
          <ion-button fill="outline" size="small" (click)="toggleFullscreen()">
            <ion-icon slot="icon-only" [name]="fullscreen() ? 'contract-outline' : 'expand-outline'"></ion-icon>
          </ion-button>
          <ion-button fill="outline" size="small" (click)="resetZoom()" [disabled]="zoom().scale === 1 && zoom().x === 0 && zoom().y === 0">
            Reset zoom
          </ion-button>
          @if (canOperate) {
            <ion-button fill="outline" size="small" (click)="untangle()" [disabled]="untangling()">
              {{ untangling() ? 'Untangling…' : 'Automatic untangle' }}
            </ion-button>
            <ion-button fill="outline" size="small" color="danger" (click)="confirmClearLinks()">
              Clear links
            </ion-button>
          }
          <ion-input class="ssid-filter" fill="outline" placeholder="wifi1, wifi2, ..."
                     [(ngModel)]="apFilterInput" (keyup.enter)="applyApFilter()"></ion-input>
          <ion-button fill="outline" size="small" (click)="applyApFilter()">Filter</ion-button>
          @if (canOperate) {
            <ion-button fill="outline" size="small" (click)="autoGroup()">Auto-group</ion-button>
          }
          @if (apFilterTerms().length > 0) {
            <ion-button fill="clear" size="small" (click)="clearApFilter()">Clear filter</ion-button>
          }
          <div class="links-slider">
            <ion-label>Links per Pi: {{ topLinksPerPi() === MAX_LINKS_PER_PI ? 'All' : topLinksPerPi() }}</ion-label>
            <ion-range [min]="1" [max]="MAX_LINKS_PER_PI" [step]="1" [snaps]="true" [ticks]="true"
                       [value]="topLinksPerPi()" (ionChange)="topLinksPerPi.set($any($event.detail.value))"></ion-range>
          </div>
        </div>

        <div class="map-wrap" [class.fullscreen]="fullscreen()">
          @if (fullscreen()) {
            <ion-button class="fs-exit-btn" fill="solid" size="small" (click)="toggleFullscreen()" aria-label="Exit fullscreen">
              <ion-icon slot="icon-only" name="contract-outline"></ion-icon>
            </ion-button>
          }
          <svg
            [attr.viewBox]="viewBoxStr()"
            class="map-canvas"
            [class.panning]="panning()"
            preserveAspectRatio="xMidYMid meet"
            (pointerdown)="onBackgroundPointerDown($event)"
            (pointermove)="onPointerMove($event)"
            (pointerup)="onPointerUp($event)"
            (pointerleave)="onPointerUp($event)"
            (pointercancel)="onPointerUp($event)"
            (wheel)="onWheel($event)"
          >
            @if (showFloorPlan()) {
              <image [attr.href]="floorPlanImg.src" [attr.x]="floorPlanImg.x" y="0"
                     [attr.width]="floorPlanImg.w" [attr.height]="floorPlanImg.h" class="floor-plan-bg" />
            }

            @if (showConnections()) {
              @for (e of visibleEdges(); track e.position + e.groupKey) {
                <line [attr.x1]="e.x1" [attr.y1]="e.y1" [attr.x2]="e.x2" [attr.y2]="e.y2"
                      class="edge" [attr.stroke-width]="e.width / zoom().scale" [style.opacity]="e.opacity" />
              }
            }

            @if (showBleLinks()) {
              @for (e of visibleBleEdges(); track e.position_a + e.position_b) {
                <line [attr.x1]="e.x1" [attr.y1]="e.y1" [attr.x2]="e.x2" [attr.y2]="e.y2"
                      class="ble-edge" [attr.stroke-width]="e.width / zoom().scale" [style.opacity]="e.opacity" />
              }
            }

            @if (showPis()) {
              @for (pi of piNodes(); track pi.mac) {
                @if (pi.x !== null && pi.y !== null) {
                  <g [attr.transform]="'translate(' + piDragPos(pi) + ')'"
                     class="pi-node" [class.pi-pinned]="pi.pinned"
                     (pointerdown)="onPiPointerDown($event, pi)">
                    <title>{{ pi.position }}{{ pi.pinned ? ' (pinned — click to release)' : '' }}</title>
                    <circle [attr.r]="scaledRadius(piDegree(pi.position))" />
                    <text [attr.y]="-(scaledRadius(piDegree(pi.position)) + 6 / zoom().scale)"
                          [style.font-size.px]="11 / zoom().scale" text-anchor="middle">{{ pi.position }}</text>
                  </g>
                }
              }
            }

            @if (showAps()) {
              @for (ap of visibleApNodes(); track ap.key) {
                <g [attr.transform]="'translate(' + dragPos(ap) + ')'"
                   class="ap-node" [class.ap-unplaced]="!ap.placed"
                   (pointerdown)="onPointerDown($event, ap)">
                  <title>{{ apTitle(ap) }}</title>
                  <circle [attr.r]="scaledRadius(apDegree(ap.key))" />
                  <text [attr.y]="-(scaledRadius(apDegree(ap.key)) + 6 / zoom().scale)"
                        [style.font-size.px]="10 / zoom().scale" text-anchor="middle">{{ apLabel(ap) }}</text>
                </g>
              }
            }
          </svg>
        </div>

        @if (unplacedCount() > 0) {
          <p class="hint" [class.fs-hidden]="fullscreen()">{{ unplacedCount() }} access point(s) not yet placed — drag from the staging row above.</p>
        }
        @if (hiddenPiCount() > 0) {
          <p class="hint" [class.fs-hidden]="fullscreen()">{{ hiddenPiCount() }} Pi(s) not shown — no <em>placed</em> AP seen in their latest WiFi
          scan, and no BLE sighting of an already-positioned Pi either. Place an AP they can see (or get a
          neighboring Pi positioned), then re-scan.</p>
        }
      }
    </ion-content>
  `,
  styles: [`
    .hint { color: var(--ion-color-medium); font-size: 0.85rem; margin: 4px 0 12px; }

    .graph-bg { --background: #1b1b1f; }

    .filter-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 0 0 10px; }
    .ssid-filter { max-width: 220px; }
    .links-slider { display: flex; align-items: center; gap: 8px; min-width: 220px; }
    .links-slider ion-label { white-space: nowrap; font-size: 0.85rem; }
    .links-slider ion-range { flex: 1; min-width: 120px; padding: 0; }

    .map-wrap {
      position: relative;
      width: 100%;
      max-width: 2100px;
      margin: 0 auto;
      aspect-ratio: 1000 / 700;
      max-height: 95vh;
    }
    .map-wrap.fullscreen {
      max-width: none;
      max-height: none;
      width: 100vw;
      height: 100vh;
      aspect-ratio: auto;
    }
    .fs-hidden { display: none; }
    .fs-exit-btn {
      position: absolute;
      top: 10px;
      right: 10px;
      z-index: 10;
      --background: rgba(20, 20, 24, 0.75);
    }
    .map-canvas {
      width: 100%;
      height: 100%;
      display: block;
      background: radial-gradient(circle at 50% 45%, #262630 0%, #19191d 75%);
      border: 1px solid #33333c;
      border-radius: 10px;
      touch-action: none;
      cursor: grab;
    }
    .map-canvas.panning { cursor: grabbing; }
    .map-wrap.fullscreen .map-canvas { border-radius: 0; }
    .floor-plan-bg { opacity: 0.35; pointer-events: none; }

    .edge { stroke: #7fd8d0; stroke-linecap: round; transition: opacity 0.3s ease; }
    .ble-edge { stroke: #c78bff; stroke-linecap: round; transition: opacity 0.3s ease; }

    .pi-node circle {
      fill: #5b8cff;
      stroke: #a9c1ff;
      stroke-width: 1.5;
      filter: drop-shadow(0 0 4px rgba(91, 140, 255, 0.65));
    }
    .pi-node { cursor: grab; }
    .pi-node text { font-size: 11px; fill: #d6def5; pointer-events: none; }
    .pi-node.pi-pinned circle { stroke: #ffe08a; stroke-width: 2.5; }

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
  imports: [
    FormsModule, IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonInput, IonLabel, IonMenuButton, IonRange,
    IonSpinner, IonText, IonTitle, IonToolbar,
  ],
})
export class FloorMapPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  readonly canOperate = inject(AuthService).can('operator');
  // "Identify" runs an arbitrary SSH command — admin-only fleet-wide, same as pi-detail's execute box.
  readonly canExecute = inject(AuthService).can('admin');

  readonly viewW = VIEW_W;
  readonly viewH = VIEW_H;
  readonly UNPLACED_ROW_Y = UNPLACED_ROW_Y;

  readonly map = signal<FloorMapResponse | null>(null);
  readonly loading = signal(false);
  readonly scanning = signal(false);
  readonly error = signal('');
  readonly statusMsg = signal('');

  readonly piNodes = signal<FloorMapPiNode[]>([]);
  readonly apNodes = signal<ApGroup[]>([]);
  readonly edges = signal<FloorMapEdge[]>([]);
  readonly bleEdges = signal<PiBleEdge[]>([]);

  /** Comma-separated SSID text filter — applied on button click, not live-as-you-type. */
  apFilterInput = '';
  readonly apFilterTerms = signal<string[]>([]);

  /** Slider: keep only the N strongest Pi->AP WiFi links per Pi (max value = no limit, show all).
   * Doesn't affect BLE Pi<->Pi links. */
  readonly MAX_LINKS_PER_PI = 10;
  readonly topLinksPerPi = signal(this.MAX_LINKS_PER_PI);

  readonly showConnections = signal(true);
  readonly showBleLinks = signal(true);
  readonly showAps = signal(true);
  readonly showPis = signal(true);
  readonly showFloorPlan = signal(true);
  readonly floorPlanImg = FLOOR_PLAN_IMG;
  readonly fullscreen = signal(false);
  readonly untangling = signal(false);
  /** x/y = viewBox min-corner, scale = zoom factor (viewBox width/height shrink as scale grows). */
  readonly zoom = signal({ scale: 1, x: 0, y: 0 });

  readonly hiddenPiCount = () => this.piNodes().filter((p) => p.x === null || p.y === null).length;

  readonly panning = signal(false);

  /** A signal (not a plain field) so the heavy derived collections below can be `computed()` and
   * skip recomputing on every animation-frame change-detection tick where nothing actually moved
   * — see `visibleEdges` for why that mattered. */
  private readonly dragging = signal<
    | { kind: 'ap'; key: string; bssids: string[]; x: number; y: number; startScreen: { x: number; y: number } }
    | { kind: 'pi'; position: string; pinned: boolean; x: number; y: number; startScreen: { x: number; y: number } }
    | null
  >(null);
  // A bit more forgiving than a mouse click — a finger naturally drifts a few px on a tap.
  private static readonly CLICK_THRESHOLD_PX = 8;
  private panStart: { clientX: number; clientY: number; zoom: { scale: number; x: number; y: number } } | null = null;
  private svgEl: SVGSVGElement | null = null;

  // ─── Touch: two-finger pinch to zoom (wheel has no touch equivalent) ──────
  private readonly activePointers = new Map<number, { x: number; y: number }>();
  private pinch: { pointerIds: [number, number]; lastDistance: number } | null = null;

  private trackPointerDown(event: PointerEvent): void {
    this.activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (this.activePointers.size === 2 && !this.pinch) {
      // A 2nd finger landing mid drag/pan means "pinch now" — drop whatever single-pointer
      // gesture was in progress so it doesn't fight with the zoom.
      this.dragging.set(null);
      this.panStart = null;
      this.panning.set(false);
      const [idA, idB] = [...this.activePointers.keys()] as [number, number];
      this.pinch = { pointerIds: [idA, idB], lastDistance: this.pointerDistance(idA, idB) };
    }
  }

  private pointerDistance(idA: number, idB: number): number {
    const a = this.activePointers.get(idA);
    const b = this.activePointers.get(idB);
    if (!a || !b) return 0;
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  constructor() {
    this.apFilterInput = localStorage.getItem(FloorMapPage.AP_FILTER_STORAGE_KEY) ?? '';
    this.applyApFilter();
    this.load();
    document.addEventListener('fullscreenchange', () => {
      this.fullscreen.set(document.fullscreenElement === document.documentElement);
    });
  }

  viewBoxStr(): string {
    const z = this.zoom();
    return `${z.x} ${z.y} ${VIEW_W / z.scale} ${VIEW_H / z.scale}`;
  }

  resetZoom(): void {
    this.zoom.set({ scale: 1, x: 0, y: 0 });
  }

  /** Zoom in/out around a view-box point, keeping it fixed on screen. Shared by the mouse wheel
   * and touch pinch — pinch just supplies a (shrinking/growing) distance ratio instead of a
   * wheel tick as the zoom `factor`. */
  private zoomAround(cursor: { x: number; y: number }, factor: number): void {
    const z = this.zoom();
    const newScale = Math.min(Math.max(z.scale * factor, 0.5), 8);
    const sizeOldX = VIEW_W / z.scale;
    const sizeOldY = VIEW_H / z.scale;
    const fracX = (cursor.x - z.x) / sizeOldX;
    const fracY = (cursor.y - z.y) / sizeOldY;
    const sizeNewX = VIEW_W / newScale;
    const sizeNewY = VIEW_H / newScale;
    this.zoom.set({ scale: newScale, x: cursor.x - fracX * sizeNewX, y: cursor.y - fracY * sizeNewY });
  }

  onWheel(event: WheelEvent): void {
    event.preventDefault();
    this.svgEl = event.currentTarget as SVGSVGElement;
    const cursor = this.toViewBox(event);
    if (!cursor) return;
    this.zoomAround(cursor, event.deltaY < 0 ? 1.15 : 1 / 1.15);
  }

  /** Force-directed relaxation of AP box positions only — Pis stay computed/fixed for the pass,
   * AP boxes repel each other (declutter overlap) and are pulled toward the Pis that see them,
   * weighted by signal strength. Only what is on screen takes part: APs/Pis/connections shown by the
   * toggles, APs passing the SSID filter, and links within the links-per-Pi cap. Pinned APs
   * never move — they only push and pull the others. Hidden boxes keep their saved positions. Result is saved
   * per-BSSID via the normal placement endpoint (every BSSID in a box moves together). */
  async untangle(): Promise<void> {
    const topLinksLimit = this.topLinksPerPi();
    const shownPis = new Set(this.showPis() ? this.piNodes().map((p) => p.position) : []);
    const apByKey = new Map((this.showAps() ? this.visibleApNodes() : []).map((a) => [a.key, a]));
    const drawnLinks = this.showConnections() ? this.visibleLinks() : [];
    const allEdges = this.edges().length;

    console.log(`[untangle] topLinksPerPi=${topLinksLimit}, MAX_LINKS_PER_PI=${this.MAX_LINKS_PER_PI}, total edges in DB=${allEdges}, filtered drawnLinks=${drawnLinks.length}, APs=${apByKey.size}, Pis=${shownPis.size}`);

    if (drawnLinks.length === 0) {
      console.log('[untangle] No links to draw, skipping');
      this.untangling.set(true);
      this.untangling.set(false);
      return;
    }

    // Each Pi's anchor is the weighted centroid (1/rssi², as the server does) of only its top-N
    // placed APs (filtered by visibleLinks), so only those exert pull.
    const anchorSum = new Map<string, { x: number; y: number; w: number }>();
    for (const link of drawnLinks) {
      const ap = apByKey.get(link.groupKey);
      if (!ap?.placed || ap.x === null || ap.y === null || !shownPis.has(link.position)) continue;
      const w = 1 / Math.max(link.rssi ** 2, 1);
      let s = anchorSum.get(link.position);
      if (!s) {
        s = { x: 0, y: 0, w: 0 };
        anchorSum.set(link.position, s);
      }
      s.x += w * ap.x;
      s.y += w * ap.y;
      s.w += w;
    }

    // For each AP, collect the Pis that have it in their top-N links, positioned at their anchor.
    const edgesByKey = new Map<string, Array<{ x: number; y: number; weight: number }>>();
    for (const link of drawnLinks) {
      const piAnchor = anchorSum.get(link.position);
      if (!piAnchor || !apByKey.has(link.groupKey)) continue;
      let arr = edgesByKey.get(link.groupKey);
      if (!arr) {
        arr = [];
        edgesByKey.set(link.groupKey, arr);
      }
      arr.push({ x: piAnchor.x / piAnchor.w, y: piAnchor.y / piAnchor.w, weight: this.rssiStrength(link.rssi) });
    }

    const shownAps = this.showAps() ? this.visibleApNodes() : [];
    let groups = shownAps.map((a) => ({
      key: a.key, bssids: a.bssids, fixed: a.pinned, x: a.x ?? VIEW_W / 2, y: a.y ?? VIEW_H / 2,
    }));
    if (groups.length === 0) return;

    this.untangling.set(true);
    const REPULSION = 9000;
    const MIN_DISTANCE = 60;
    const ATTRACTION = 0.06;
    const MARGIN = 30;
    const MIN_Y = UNPLACED_ROW_Y + 40;
    const startTime = performance.now();
    console.log(`[untangle] Starting spring simulation (250 iterations, ${groups.length} APs, ${groups.filter(g => !g.fixed).length} movable)`);

    for (let iter = 0; iter < 250; iter++) {
      const forces = groups.map(() => ({ fx: 0, fy: 0 }));
      for (let i = 0; i < groups.length; i++) {
        for (let j = i + 1; j < groups.length; j++) {
          const dx = groups[i].x - groups[j].x;
          const dy = groups[i].y - groups[j].y;
          const distSq = Math.max(dx * dx + dy * dy, 1);
          const dist = Math.sqrt(distSq);
          const overlap = Math.max(0, MIN_DISTANCE - dist);
          const f = REPULSION / distSq + overlap * 0.5;
          const fx = (dx / dist) * f;
          const fy = (dy / dist) * f;
          forces[i].fx += fx; forces[i].fy += fy;
          forces[j].fx -= fx; forces[j].fy -= fy;
        }
        for (const edge of edgesByKey.get(groups[i].key) ?? []) {
          forces[i].fx += (edge.x - groups[i].x) * ATTRACTION * edge.weight;
          forces[i].fy += (edge.y - groups[i].y) * ATTRACTION * edge.weight;
        }
      }
      groups = groups.map((g, i) => g.fixed ? g : {
        ...g,
        x: Math.min(Math.max(g.x + forces[i].fx, MARGIN), VIEW_W - MARGIN),
        y: Math.min(Math.max(g.y + forces[i].fy, MIN_Y), VIEW_H - MARGIN),
      });
    }

    const elapsed = performance.now() - startTime;
    console.log(`[untangle] Simulation complete (${elapsed.toFixed(0)}ms).`);

    try {
      const writes = groups.filter((g) => !g.fixed)
        .flatMap((g) => g.bssids.map((bssid) => firstValueFrom(this.api.placeAccessPoint(bssid, g.x, g.y))));
      console.log(`[untangle] Saving ${writes.length} AP position(s)`);
      await Promise.all(writes);
      await this.load();
      console.log('[untangle] Saved and reloaded');
    } catch (e) {
      console.error('[untangle] Error:', e);
      this.error.set(errorMessage(e));
    } finally {
      this.untangling.set(false);
    }
  }

  /** Fullscreens the whole page (`<html>`), not just the map div — Ionic's action-sheet/alert
   * overlays (View details / Identify / Release pin, the "Remove AP" confirm, etc.) portal to
   * `document.body`. The Fullscreen API only renders the fullscreened element and its
   * descendants, so fullscreening just the map div made those overlays invisible (silently —
   * they still opened, just off in the hidden rest-of-page). Fullscreening `documentElement`
   * keeps body, and everything portaled to it, inside the fullscreened subtree. CSS below hides
   * the header/filter chrome and expands `.map-wrap` to fill the screen to reproduce the old look. */
  async toggleFullscreen(): Promise<void> {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await document.documentElement.requestFullscreen();
    }
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    try {
      const m = await firstValueFrom(this.api.floorMap());
      this.map.set(m);
      this.piNodes.set(m.pis);
      this.edges.set(m.edges);
      this.bleEdges.set(m.pi_ble_edges);
      this.apNodes.set(this.groupAccessPoints(m.access_points));
      this.showFloorPlan.set(m.plan_visible);
    } catch (e) {
      this.error.set(errorMessage(e));
    } finally {
      this.loading.set(false);
    }
  }

  /** bssid → ApGroup.key. Lets apDegree/visibleEdges/untangle resolve a raw BSSID to its box. */
  private bssidToKey = new Map<string, string>();

  /** One box per `group_name` (several BSSIDs manually grouped — see `openApMenu`), or per
   * BSSID when ungrouped. Unplaced boxes get staged along the top row so they don't overlap. */
  private groupAccessPoints(aps: AccessPointOut[]): ApGroup[] {
    this.bssidToKey = new Map();
    const groups = new Map<string, ApGroup>();
    for (const ap of aps) {
      const key = ap.group_name ?? ap.bssid;
      const g = groups.get(key) ?? { key, bssids: [], ssids: [], x: null, y: null, placed: false, pinned: false };
      g.bssids.push(ap.bssid);
      if (ap.pinned) g.pinned = true;
      const ssidsToAdd = ap.ssid ? [...ap.ssids, ap.ssid] : ap.ssids;
      for (const s of ssidsToAdd) {
        if (!g.ssids.includes(s)) g.ssids.push(s);
      }
      if (!g.placed && ap.x !== null && ap.y !== null) {
        g.x = ap.x;
        g.y = ap.y;
        g.placed = true;
      }
      groups.set(key, g);
      this.bssidToKey.set(ap.bssid, key);
    }

    const all = [...groups.values()];
    const placed = all.filter((g) => g.placed);
    const unplaced = all.filter((g) => !g.placed);
    const staged = unplaced.map((g, i) => ({ ...g, x: 40 + i * 60, y: UNPLACED_ROW_Y }));
    return [...placed, ...staged];
  }

  /** Click (without dragging) an AP box to assign it to a manual group — "Group to:" with a
   * "New group…" option and every existing group name listed. BSSIDs sharing a group render
   * as one box. */
  private readonly actionSheets = inject(ActionSheetController);
  private readonly alerts = inject(AlertController);

  /** Groups ungrouped APs whose BSSIDs differ only by 1 in the last octet (server-side). */
  async autoGroup(): Promise<void> {
    this.error.set('');
    try {
      const res = await firstValueFrom(this.api.autoGroupAccessPoints());
      this.statusMsg.set(`Grouped ${res.aps} APs into ${res.groups} group(s).`);
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  private async setApPinned(ap: ApGroup, pinned: boolean): Promise<void> {
    this.error.set('');
    try {
      await Promise.all(ap.bssids.map((bssid) => firstValueFrom(this.api.pinAccessPoint(bssid, pinned))));
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  async openApMenu(ap: ApGroup): Promise<void> {
    let groups: string[] = [];
    try {
      groups = await firstValueFrom(this.api.listAccessPointGroups());
    } catch {
      // non-fatal — menu still works with just "New group…"
    }
    const currentlyGrouped = groups.includes(ap.key);

    const buttons: Array<{ text: string; role?: string; handler?: () => void }> = [
      { text: 'New group…', handler: () => void this.promptNewGroup(ap) },
      ...groups.filter((g) => g !== ap.key).map((g) => ({ text: g, handler: () => void this.assignGroup(ap, g) })),
    ];
    if (currentlyGrouped) {
      buttons.push({ text: 'Remove from group', role: 'destructive', handler: () => void this.assignGroup(ap, null) });
    }
    if (ap.placed && this.canOperate) {
      buttons.push(ap.pinned
        ? { text: 'Unpin (let untangle move it)', handler: () => void this.setApPinned(ap, false) }
        : { text: 'Pin in place (untangle keeps it)', handler: () => void this.setApPinned(ap, true) });
    }
    buttons.push({ text: 'Remove access point', role: 'destructive', handler: () => void this.confirmRemoveAp(ap) });
    buttons.push({ text: 'Cancel', role: 'cancel' });

    const sheet = await this.actionSheets.create({
      header: `Group "${this.apLabel(ap)}" to:`,
      subHeader: `MAC ${ap.bssids.join(', ')}`,
      buttons,
    });
    await sheet.present();
  }

  private async promptNewGroup(ap: ApGroup): Promise<void> {
    const alert = await this.alerts.create({
      header: 'New group name',
      inputs: [{ name: 'name', type: 'text', placeholder: 'e.g. Lobby router' }],
      buttons: [{ text: 'Cancel', role: 'cancel' }, { text: 'Create', role: 'confirm' }],
    });
    await alert.present();
    const res = await alert.onDidDismiss();
    const name = (res.data?.values?.name as string | undefined)?.trim();
    if (res.role === 'confirm' && name) {
      await this.assignGroup(ap, name);
    }
  }

  /** Deletes every BSSID in this box from the map entirely — not just unplacing it. A later WiFi
   * scan that still sees the BSSID just re-registers it as a fresh unplaced AP. Confirm first,
   * it can't be undone. */
  private async confirmRemoveAp(ap: ApGroup): Promise<void> {
    const alert = await this.alerts.create({
      header: `Remove "${this.apLabel(ap)}"?`,
      message: ap.bssids.length > 1
        ? `Deletes all ${ap.bssids.length} grouped BSSIDs from the map. This cannot be undone.`
        : 'Deletes this access point from the map. This cannot be undone.',
      buttons: [
        { text: 'Cancel', role: 'cancel' },
        { text: 'Remove', role: 'destructive', handler: () => void this.removeAp(ap) },
      ],
    });
    await alert.present();
  }

  private async removeAp(ap: ApGroup): Promise<void> {
    try {
      await Promise.all(ap.bssids.map((bssid) => firstValueFrom(this.api.deleteAccessPoint(bssid))));
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  private async assignGroup(ap: ApGroup, groupName: string | null): Promise<void> {
    try {
      await Promise.all(ap.bssids.map((bssid) => firstValueFrom(this.api.setAccessPointGroup(bssid, groupName))));
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  /** Shared across every user (not a per-browser preference) — toggling it here changes what
   * everyone else sees next time they load the page, via the `plan_visible` setting row. */
  async toggleFloorPlan(): Promise<void> {
    const next = !this.showFloorPlan();
    this.showFloorPlan.set(next); // optimistic — feels instant, load() will correct it on failure
    try {
      await firstValueFrom(this.api.setFloorPlanVisible(next));
    } catch (e) {
      this.error.set(errorMessage(e));
      await this.load();
    }
  }

  /** Permanently deletes every stored WiFi/BLE scan reading (all Pi<->AP and Pi<->Pi links,
   * fleet-wide) — AP placements/groups and Pi pins are untouched. Confirm first, it can't be undone. */
  async confirmClearLinks(): Promise<void> {
    const alert = await this.alerts.create({
      header: 'Clear all links?',
      message: 'Deletes every stored WiFi and BLE scan reading for the whole fleet. Links reappear after the '
        + 'next scan. This cannot be undone.',
      buttons: [
        { text: 'Cancel', role: 'cancel' },
        { text: 'Clear links', role: 'destructive', handler: () => void this.clearLinks() },
      ],
    });
    await alert.present();
  }

  private async clearLinks(): Promise<void> {
    try {
      await firstValueFrom(this.api.clearAllLinks());
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
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

  private static readonly AP_FILTER_STORAGE_KEY = 'floorMap.apFilter';

  applyApFilter(): void {
    const terms = this.apFilterInput.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean);
    this.apFilterTerms.set(terms);
    localStorage.setItem(FloorMapPage.AP_FILTER_STORAGE_KEY, this.apFilterInput);
  }

  clearApFilter(): void {
    this.apFilterInput = '';
    this.apFilterTerms.set([]);
    localStorage.removeItem(FloorMapPage.AP_FILTER_STORAGE_KEY);
  }

  /** APs matching the SSID filter (any SSID in the box contains any filter term), or all of
   * them when no filter is applied. Everything else (counts, degree, edges) is derived from
   * this instead of `apNodes()` so a filtered-out box is excluded everywhere, not just hidden
   * visually. */
  readonly visibleApNodes = computed(() => {
    const terms = this.apFilterTerms();
    if (terms.length === 0) return this.apNodes();
    return this.apNodes().filter((g) => g.ssids.some((s) => terms.some((t) => s.toLowerCase().includes(t))));
  });

  unplacedCount(): number {
    return this.visibleApNodes().filter((g) => !g.placed).length;
  }

  /** Numeric position, used internally (e.g. by `visibleEdges`) to avoid a string
   * format-then-reparse round trip on every edge endpoint. */
  private apCoords(ap: ApGroup): { x: number; y: number } {
    const d = this.dragging();
    if (d?.kind === 'ap' && d.key === ap.key) return { x: d.x, y: d.y };
    const s = this.settling();
    if (s?.apKey === ap.key) return { x: s.apX, y: s.apY };
    return { x: ap.x ?? NaN, y: ap.y ?? NaN };
  }

  private piCoords(pi: FloorMapPiNode): { x: number; y: number } {
    const d = this.dragging();
    if (d?.kind === 'pi' && d.position === pi.position) return { x: d.x, y: d.y };
    const held = this.settling()?.pis.get(pi.position);
    if (held) return held;
    const follow = this.dragFollowers().get(pi.position);
    return { x: (pi.x ?? NaN) + (follow?.dx ?? 0), y: (pi.y ?? NaN) + (follow?.dy ?? 0) };
  }

  /** For the SVG `transform` attribute, which needs a "x,y" string. */
  dragPos(ap: ApGroup): string {
    const { x, y } = this.apCoords(ap);
    return `${x},${y}`;
  }

  piDragPos(pi: FloorMapPiNode): string {
    const { x, y } = this.piCoords(pi);
    return `${x},${y}`;
  }

  /** Node size reflects its connection count, like Obsidian's graph view. */
  nodeRadius(degree: number): number {
    return Math.min(3 + degree * 0.75, 8);
  }

  /** Radius in viewBox user-units, shrunk as you zoom in — since the viewBox itself shrinks
   * on zoom, a radius that didn't shrink would grow on screen and crowd out everything
   * around it; dividing by scale keeps node footprint from eating the extra detail zoom reveals. */
  scaledRadius(degree: number): number {
    return this.nodeRadius(degree) / this.zoom().scale;
  }

  /** Primary SSID + "(+N more)" when the box groups more than one SSID (own BSSID, or other
   * BSSIDs grouped into the same physical AP). */
  apLabel(ap: ApGroup): string {
    const name = ap.ssids[0] || ap.bssids[0];
    const extra = ap.ssids.length - (ap.ssids[0] ? 1 : 0);
    return extra > 0 ? `${name} (+${extra})` : name;
  }

  apTitle(ap: ApGroup): string {
    return ap.ssids.length > 0 ? ap.ssids.join(', ') : ap.bssids.join(', ');
  }

  piDegree(position: string): number {
    return this.visibleEdges().filter((e) => e.position === position).length;
  }

  apDegree(key: string): number {
    return this.visibleEdges().filter((e) => e.groupKey === key).length;
  }

  /** Edges with both endpoints resolved to canvas coordinates, weighted by RSSI (stroke width/opacity).
   * Only to APs that survive the SSID filter — a filtered-out box's connections disappear too. Also
   * capped per-Pi at `topLinksPerPi` (strongest RSSI first) by the links-per-Pi slider.
   *
   * `computed()`, not a plain method: this used to recompute from scratch (including a sort) on
   * every call, and it was being called many times per Angular change-detection cycle (once from
   * the template loop, twice more per Pi/AP via `piDegree`/`apDegree`) — and a CD cycle runs on
   * every animation frame while anything on the page keeps scheduling one (Ionic's gesture/anim
   * internals do, continuously), not just while actually dragging. That compounded into a
   * measured multi-second chunk of a profiling capture going to this one function — see the
   * "why is mapplan so laggy" investigation. `computed()` instead caches the result and only
   * redoes the work when a dependency signal (`piNodes`, `apNodes`, `edges`, `dragging`, …)
   * actually changes value. */
  /** Links on screen by the SSID filter and links-per-Pi cap, without coordinates — so the
   * drag-follow below can read them without depending on the drawn edges. */
  readonly visibleLinks = computed(() => {
    const piByPosition = new Map(this.piNodes().map((p) => [p.position, p]));
    const apByKey = new Map(this.visibleApNodes().map((a) => [a.key, a]));
    const byPosition = new Map<string, FloorMapEdge[]>();
    for (const e of this.edges()) {
      const groupKey = this.bssidToKey.get(e.bssid);
      if (!groupKey || !apByKey.has(groupKey)) continue;
      const pi = piByPosition.get(e.position);
      if (!pi || pi.x === null || pi.y === null) continue;
      const arr = byPosition.get(e.position) ?? [];
      arr.push(e);
      byPosition.set(e.position, arr);
    }

    const limit = this.topLinksPerPi() >= this.MAX_LINKS_PER_PI ? Infinity : this.topLinksPerPi();
    const out: Array<{ position: string; groupKey: string; rssi: number }> = [];
    for (const [position, forPi] of byPosition) {
      const strongest = [...forPi].sort((a, b) => b.rssi - a.rssi).slice(0, limit);
      for (const e of strongest) out.push({ position, groupKey: this.bssidToKey.get(e.bssid)!, rssi: e.rssi });
    }
    return out;
  });

  readonly visibleEdges = computed(() => {
    const piByPosition = new Map(this.piNodes().map((p) => [p.position, p]));
    const apByKey = new Map(this.visibleApNodes().map((a) => [a.key, a]));
    const out: Array<{ position: string; groupKey: string; rssi: number; x1: number; y1: number; x2: number; y2: number; width: number; opacity: number }> = [];
    for (const link of this.visibleLinks()) {
      const { x: px, y: py } = this.piCoords(piByPosition.get(link.position)!);
      const { x: ax, y: ay } = this.apCoords(apByKey.get(link.groupKey)!);
      if (Number.isNaN(ax) || Number.isNaN(ay) || Number.isNaN(px) || Number.isNaN(py)) continue;
      const strength = this.rssiStrength(link.rssi);
      out.push({
        position: link.position, groupKey: link.groupKey, rssi: link.rssi, x1: px, y1: py, x2: ax, y2: ay,
        width: 0.5 + strength * 3, opacity: 0.15 + strength * 0.6,
      });
    }
    return out;
  });

  /** Positions held after an AP drop until the saved state reloads, so nothing snaps back. */
  private readonly settling = signal<{
    apKey: string; apX: number; apY: number; pis: Map<string, { x: number; y: number }>;
  } | null>(null);

  /** While an AP is dragged, each unpinned Pi with a visible link to it moves by the same drag
   * delta, scaled by that link's signal strength (spring-like: strong links follow closely, weak
   * ones lag). Pinned Pis stay put. Preview only — on drop the AP is saved and Pi positions are
   * recomputed from scans on reload. */
  readonly dragFollowers = computed(() => {
    const out = new Map<string, { dx: number; dy: number }>();
    const d = this.dragging();
    if (d?.kind !== 'ap') return out;
    const ap = this.apNodes().find((a) => a.key === d.key);
    if (!ap || ap.x === null || ap.y === null) return out;
    const dx = d.x - ap.x;
    const dy = d.y - ap.y;
    const pinned = new Set(this.piNodes().filter((p) => p.pinned).map((p) => p.position));
    const strength = new Map<string, number>();
    for (const link of this.visibleLinks()) {
      if (link.groupKey !== d.key || pinned.has(link.position)) continue;
      strength.set(link.position, Math.max(strength.get(link.position) ?? 0, this.rssiStrength(link.rssi)));
    }
    for (const [position, w] of strength) out.set(position, { dx: dx * w, dy: dy * w });
    return out;
  });

  /** Pi<->Pi BLE sightings with both endpoints resolved to canvas coordinates — only drawable
   * once at least one end has a (WiFi-derived) position; a link between two still-unpositioned
   * Pis has nowhere to be drawn. */
  readonly visibleBleEdges = computed(() => {
    const piByPosition = new Map(this.piNodes().map((p) => [p.position, p]));
    const out: Array<PiBleEdge & { x1: number; y1: number; x2: number; y2: number; width: number; opacity: number }> = [];
    for (const e of this.bleEdges()) {
      const a = piByPosition.get(e.position_a);
      const b = piByPosition.get(e.position_b);
      if (!a || !b || a.x === null || a.y === null || b.x === null || b.y === null) continue;
      const { x: ax, y: ay } = this.piCoords(a);
      const { x: bx, y: by } = this.piCoords(b);
      const strength = this.rssiStrength(e.rssi);
      out.push({ ...e, x1: ax, y1: ay, x2: bx, y2: by, width: 0.5 + strength * 3, opacity: 0.15 + strength * 0.6 });
    }
    return out;
  });

  private rssiStrength(rssi: number): number {
    const clamped = Math.min(Math.max(rssi, RSSI_WEAK), RSSI_STRONG);
    return (clamped - RSSI_WEAK) / (RSSI_STRONG - RSSI_WEAK);
  }

  onPointerDown(event: PointerEvent, ap: ApGroup): void {
    event.stopPropagation(); // don't also start a background pan
    this.svgEl = (event.currentTarget as SVGGraphicsElement).ownerSVGElement;
    this.trackPointerDown(event);
    if (this.pinch || !this.canOperate) return; // 2nd finger landing here starts a pinch instead; viewers can look, not move/group APs
    const pt = this.toViewBox(event);
    if (!pt) return;
    this.dragging.set({
      kind: 'ap', key: ap.key, bssids: ap.bssids, x: pt.x, y: pt.y,
      startScreen: { x: event.clientX, y: event.clientY },
    });
  }

  onPiPointerDown(event: PointerEvent, pi: FloorMapPiNode): void {
    event.stopPropagation(); // don't also start a background pan
    this.svgEl = (event.currentTarget as SVGGraphicsElement).ownerSVGElement;
    this.trackPointerDown(event);
    // Tracked for every role, even viewers — a plain click/tap (no real movement) navigates to
    // the Pi's detail page regardless of permissions; only an actual drag is gated to operators
    // below. A 2nd finger landing here starts a pinch instead of a drag.
    if (this.pinch) return;
    const pt = this.toViewBox(event);
    if (!pt || pi.x === null || pi.y === null) return;
    this.dragging.set({
      kind: 'pi', position: pi.position, pinned: pi.pinned, x: pt.x, y: pt.y,
      startScreen: { x: event.clientX, y: event.clientY },
    });
  }

  /** Pointerdown on empty canvas (not an AP node, which stops propagation) — pan the view. */
  onBackgroundPointerDown(event: PointerEvent): void {
    if (this.dragging()) return;
    this.svgEl = event.currentTarget as SVGSVGElement;
    this.trackPointerDown(event);
    if (this.pinch) return; // 2nd finger landing here starts a pinch instead of a pan
    this.panStart = { clientX: event.clientX, clientY: event.clientY, zoom: this.zoom() };
    this.panning.set(true);
  }

  onPointerMove(event: PointerEvent): void {
    if (this.activePointers.has(event.pointerId)) {
      this.activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    }
    if (this.pinch) {
      const [idA, idB] = this.pinch.pointerIds;
      const a = this.activePointers.get(idA);
      const b = this.activePointers.get(idB);
      if (!a || !b) return;
      const dist = this.pointerDistance(idA, idB);
      const factor = this.pinch.lastDistance > 0 ? dist / this.pinch.lastDistance : 1;
      this.pinch.lastDistance = dist;
      const cursor = this.toViewBox({ clientX: (a.x + b.x) / 2, clientY: (a.y + b.y) / 2 });
      if (cursor) this.zoomAround(cursor, factor);
      return;
    }
    const dragNow = this.dragging();
    if (dragNow) {
      const pt = this.toViewBox(event);
      if (!pt) return;
      this.dragging.set({ ...dragNow, x: pt.x, y: pt.y });
      return;
    }
    if (this.panStart && this.svgEl) {
      const ctm = this.svgEl.getScreenCTM();
      if (!ctm) return;
      const dxUser = (event.clientX - this.panStart.clientX) / ctm.a;
      const dyUser = (event.clientY - this.panStart.clientY) / ctm.d;
      this.zoom.set({ scale: this.panStart.zoom.scale, x: this.panStart.zoom.x - dxUser, y: this.panStart.zoom.y - dyUser });
    }
  }

  async onPointerUp(event?: PointerEvent): Promise<void> {
    if (event) this.activePointers.delete(event.pointerId);
    if (this.pinch && (!this.activePointers.has(this.pinch.pointerIds[0]) || !this.activePointers.has(this.pinch.pointerIds[1]))) {
      this.pinch = null; // one of the two pinch fingers lifted — zoom gesture is over
    }
    this.panStart = null;
    this.panning.set(false);
    const drag = this.dragging();
    if (!drag) return;
    const followers = drag.kind === 'ap' ? this.dragFollowers() : null;
    this.dragging.set(null);

    const moved = event
      ? Math.hypot(event.clientX - drag.startScreen.x, event.clientY - drag.startScreen.y)
      : Infinity;

    if (drag.kind === 'ap') {
      if (moved < FloorMapPage.CLICK_THRESHOLD_PX) {
        const ap = this.apNodes().find((a) => a.key === drag.key)
          ?? { key: drag.key, bssids: drag.bssids, ssids: [], x: null, y: null, placed: false, pinned: false };
        await this.openApMenu(ap);
        return;
      }
      const pis = new Map<string, { x: number; y: number }>();
      for (const [position, f] of followers ?? []) {
        const node = this.piNodes().find((p) => p.position === position);
        if (node?.x != null && node.y != null) pis.set(position, { x: node.x + f.dx, y: node.y + f.dy });
      }
      this.settling.set({ apKey: drag.key, apX: drag.x, apY: drag.y, pis });
      try {
        await Promise.all(drag.bssids.map((bssid) => firstValueFrom(this.api.placeAccessPoint(bssid, drag.x, drag.y))));
        await this.load();
      } catch (e) {
        this.error.set(errorMessage(e));
      } finally {
        this.settling.set(null);
      }
      return;
    }

    // A plain click opens the Pi's sheet with its MAC and IP; "View details" is the first option.
    // Operators also get "Release pin" on a pinned Pi, and admins "Identify" (pops hostname/IP/MAC
    // on the Pi's own screen).
    if (moved < FloorMapPage.CLICK_THRESHOLD_PX) {
      const pi = this.piNodes().find((p) => p.position === drag.position);
      if (pi) await this.openPiMenu(pi, drag.pinned);
      else await this.router.navigate(['/pi', drag.position]);
      return;
    }

    if (!this.canOperate) {
      await this.load(); // snap back — viewers can't persist a drag
      return;
    }
    try {
      await firstValueFrom(this.api.pinPi(drag.position, drag.x, drag.y));
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  private async openPiMenu(pi: FloorMapPiNode, pinned: boolean): Promise<void> {
    const position = pi.position;
    const buttons: Array<{ text: string; role?: string; handler?: () => void }> = [
      { text: 'View details', handler: () => void this.router.navigate(['/pi', position]) },
    ];
    if (this.canExecute) {
      buttons.push({ text: 'Identify (show info on screen)', handler: () => void this.identifyPi(position) });
    }
    if (pinned && this.canOperate) {
      buttons.push({ text: 'Release pin', role: 'destructive', handler: () => void this.unpinPi(position) });
    }
    buttons.push({ text: 'Cancel', role: 'cancel' });

    const sheet = await this.actionSheets.create({
      header: `Pi ${position}`,
      subHeader: `MAC ${pi.mac} · IP ${pi.ip ?? '—'}`,
      buttons,
    });
    await sheet.present();
  }

  /** Pops a zenity dialog with hostname/IP/MAC on the Pi's own screen — a quick way to match a
   * floor-map dot to the physical unit in front of you. Fire-and-forget: nothing useful to show
   * in the web UI (the result is a dialog on the Pi, not textual output), so just queue it and
   * let the status line confirm it was sent instead of jumping to the action-progress page. */
  private static readonly IDENTIFY_CMD =
    'export DISPLAY=:0 && zenity --display=:0 --info --text "$(hostname -I)\\n$(cat /sys/class/net/wlan0/address)\\n$(hostname)" --width 300 --timeout 10';

  private async identifyPi(position: string): Promise<void> {
    this.error.set('');
    try {
      await firstValueFrom(this.api.executeCommand([position], FloorMapPage.IDENTIFY_CMD));
      this.statusMsg.set(`Identify sent to ${position} — check its screen.`);
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  private async unpinPi(position: string): Promise<void> {
    try {
      await firstValueFrom(this.api.unpinPi(position));
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  /** Screen → SVG user-space via the CTM, so dragging tracks correctly regardless of
   * letterboxing from preserveAspectRatio (plain bounding-box math drifts off when the
   * container's aspect ratio doesn't exactly match the 1000x700 viewBox). */
  private toViewBox(event: { clientX: number; clientY: number }): { x: number; y: number } | null {
    if (!this.svgEl) return null;
    const ctm = this.svgEl.getScreenCTM();
    if (!ctm) return null;
    const pt = this.svgEl.createSVGPoint();
    pt.x = event.clientX;
    pt.y = event.clientY;
    const p = pt.matrixTransform(ctm.inverse());
    return { x: Math.round(p.x), y: Math.round(p.y) };
  }
}
