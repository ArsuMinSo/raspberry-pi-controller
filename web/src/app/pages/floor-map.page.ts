import { Component, ElementRef, OnDestroy, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  ActionSheetController, AlertController, IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonInput,
  IonMenuButton, IonSpinner, IonText, IonTitle, IonToolbar,
} from '@ionic/angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from '../core/api.service';
import { errorMessage } from '../core/errors';
import { AccessPointOut, FloorMapEdge, FloorMapPiNode, FloorMapResponse, PiBleEdge } from '../core/models';

/** View-box is a fixed logical size; node positions live in these units. */
const VIEW_W = 1000;
const VIEW_H = 700;

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
  /** True = fixed at x/y (saved on the server). False = floating, live-simulated, not persisted. */
  pinned: boolean;
}

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
          Everything floats on springs (connections pull, nodes repel) unless pinned. Drag anything to nudge it;
          click (without dragging) to open its menu — "Pin here" fixes it in place (persisted), "Unpin" lets it
          float again. Scroll to zoom, drag empty space to pan. Line thickness/brightness = signal strength;
          node size = number of connections.
        </p>

        <div class="filter-row">
          <ion-button fill="outline" size="small" [color]="showConnections() ? 'primary' : 'medium'"
                      (click)="showConnections.set(!showConnections())">Connections</ion-button>
          <ion-button fill="outline" size="small" [color]="showAps() ? 'primary' : 'medium'"
                      (click)="showAps.set(!showAps())">APs</ion-button>
          <ion-button fill="outline" size="small" [color]="showPis() ? 'primary' : 'medium'"
                      (click)="showPis.set(!showPis())">Pis</ion-button>
          <ion-button fill="outline" size="small" [color]="showBleLinks() ? 'primary' : 'medium'"
                      (click)="showBleLinks.set(!showBleLinks())">BLE links</ion-button>
          <ion-button fill="outline" size="small" (click)="toggleFullscreen()">
            <ion-icon slot="icon-only" [name]="fullscreen() ? 'contract-outline' : 'expand-outline'"></ion-icon>
          </ion-button>
          <ion-button fill="outline" size="small" (click)="resetZoom()" [disabled]="zoom().scale === 1 && zoom().x === 0 && zoom().y === 0">
            Reset zoom
          </ion-button>
          <ion-input class="ssid-filter" fill="outline" placeholder="wifi1, wifi2, ..."
                     [(ngModel)]="apFilterInput" (keyup.enter)="applyApFilter()"></ion-input>
          <ion-button fill="outline" size="small" (click)="applyApFilter()">Filter</ion-button>
          @if (apFilterTerms().length > 0) {
            <ion-button fill="clear" size="small" (click)="clearApFilter()">Clear filter</ion-button>
          }
        </div>

        <div class="map-wrap" #mapWrap [class.fullscreen]="fullscreen()">
          <svg
            [attr.viewBox]="viewBoxStr()"
            class="map-canvas"
            [class.panning]="panning()"
            preserveAspectRatio="xMidYMid meet"
            (pointerdown)="onBackgroundPointerDown($event)"
            (pointermove)="onPointerMove($event)"
            (pointerup)="onPointerUp($event)"
            (pointerleave)="onPointerUp($event)"
            (wheel)="onWheel($event)"
          >
            @if (showConnections() && showAps()) {
              @for (e of visibleEdges(); track e.position + e.groupKey) {
                <line [attr.x1]="e.x1" [attr.y1]="e.y1" [attr.x2]="e.x2" [attr.y2]="e.y2"
                      class="edge" [attr.stroke-width]="e.width / zoom().scale" [style.opacity]="e.opacity" />
              }
            }

            @if (showBleLinks() && showPis()) {
              @for (e of visibleBleEdges(); track e.position_a + e.position_b) {
                <line [attr.x1]="e.x1" [attr.y1]="e.y1" [attr.x2]="e.x2" [attr.y2]="e.y2"
                      class="ble-edge" [attr.stroke-width]="e.width / zoom().scale" [style.opacity]="e.opacity" />
              }
            }

            @if (showPis()) {
              @for (pi of piNodes(); track pi.mac) {
                <g [attr.transform]="'translate(' + posOf('pi:' + pi.position).x + ',' + posOf('pi:' + pi.position).y + ')'"
                   class="pi-node" [class.pi-unpinned]="!pi.pinned"
                   (pointerdown)="onNodePointerDown($event, 'pi', 'pi:' + pi.position, pi.pinned, undefined, pi.position)">
                  <circle [attr.r]="scaledRadius(piDegree(pi.position))" />
                  <text [attr.y]="-(scaledRadius(piDegree(pi.position)) + 6 / zoom().scale)"
                        [style.font-size.px]="11 / zoom().scale" text-anchor="middle">{{ pi.position }}</text>
                </g>
              }
            }

            @if (showAps()) {
              @for (ap of visibleApNodes(); track ap.key) {
                <g [attr.transform]="'translate(' + posOf('ap:' + ap.key).x + ',' + posOf('ap:' + ap.key).y + ')'"
                   class="ap-node" [class.ap-unpinned]="!ap.pinned"
                   (pointerdown)="onNodePointerDown($event, 'ap', 'ap:' + ap.key, ap.pinned, ap.bssids, undefined)">
                  <title>{{ apTitle(ap) }}</title>
                  <circle [attr.r]="scaledRadius(apDegree(ap.key))" />
                  <text [attr.y]="-(scaledRadius(apDegree(ap.key)) + 6 / zoom().scale)"
                        [style.font-size.px]="10 / zoom().scale" text-anchor="middle">{{ apLabel(ap) }}</text>
                </g>
              }
            }
          </svg>
        </div>

        @if (unpinnedApCount() > 0) {
          <p class="hint">{{ unpinnedApCount() }} access point(s) not pinned — floating freely until you fix one.</p>
        }
      }
    </ion-content>
  `,
  styles: [`
    .hint { color: var(--ion-color-medium); font-size: 0.85rem; margin: 4px 0 12px; }

    .graph-bg { --background: #1b1b1f; }

    .filter-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 0 0 10px; }
    .ssid-filter { max-width: 220px; }

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
      cursor: grab;
    }
    .map-canvas.panning { cursor: grabbing; }
    .map-wrap.fullscreen .map-canvas { border-radius: 0; }

    .edge { stroke: #7fd8d0; stroke-linecap: round; transition: opacity 0.3s ease; }
    .ble-edge {
      stroke: #e0a8ff;
      stroke-linecap: round;
      stroke-dasharray: 6 4;
      transition: opacity 0.3s ease;
      filter: drop-shadow(0 0 3px rgba(224, 168, 255, 0.7));
    }

    .pi-node circle {
      fill: #5b8cff;
      stroke: #a9c1ff;
      stroke-width: 1.5;
      filter: drop-shadow(0 0 4px rgba(91, 140, 255, 0.65));
    }
    .pi-node.pi-unpinned circle { opacity: 0.75; filter: none; stroke-dasharray: 2 2; }
    .pi-node text { font-size: 11px; fill: #d6def5; }

    .ap-node { cursor: grab; }
    .ap-node circle {
      fill: #ffb454;
      stroke: #ffd9a0;
      stroke-width: 1.5;
      filter: drop-shadow(0 0 4px rgba(255, 180, 84, 0.6));
    }
    .ap-node.ap-unpinned circle {
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
    FormsModule, IonButton, IonButtons, IonContent, IonHeader, IonIcon, IonInput, IonMenuButton, IonSpinner, IonText,
    IonTitle, IonToolbar,
  ],
})
export class FloorMapPage implements OnDestroy {
  private readonly api = inject(ApiService);

  readonly viewW = VIEW_W;
  readonly viewH = VIEW_H;

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

  readonly showConnections = signal(true);
  readonly showBleLinks = signal(true);
  readonly showAps = signal(true);
  readonly showPis = signal(true);
  readonly fullscreen = signal(false);
  /** x/y = viewBox min-corner, scale = zoom factor (viewBox width/height shrink as scale grows). */
  readonly zoom = signal({ scale: 1, x: 0, y: 0 });
  private readonly mapWrap = viewChild<ElementRef<HTMLDivElement>>('mapWrap');

  readonly panning = signal(false);

  private dragging: {
    id: string; kind: 'pi' | 'ap'; wasPinned: boolean; bssids?: string[]; position?: string;
    x: number; y: number; startScreen: { x: number; y: number };
  } | null = null;
  private static readonly CLICK_THRESHOLD_PX = 4;
  private panStart: { clientX: number; clientY: number; zoom: { scale: number; x: number; y: number } } | null = null;
  private svgEl: SVGSVGElement | null = null;

  /** Live simulation state — plain mutable maps, not signals. Zone.js patches requestAnimationFrame,
   * so a normal change-detection pass runs after every tick and the template re-reads `posOf()`;
   * no need to clone/re-signal a whole Map 60x/sec. */
  private readonly simPos = new Map<string, { x: number; y: number }>();
  private readonly simVel = new Map<string, { x: number; y: number }>();
  private rafId: number | null = null;

  private readonly actionSheets = inject(ActionSheetController);
  private readonly alerts = inject(AlertController);

  constructor() {
    this.apFilterInput = localStorage.getItem(FloorMapPage.AP_FILTER_STORAGE_KEY) ?? '';
    this.applyApFilter();
    this.load();
    document.addEventListener('fullscreenchange', () => {
      this.fullscreen.set(document.fullscreenElement === this.mapWrap()?.nativeElement);
    });
    this.rafId = requestAnimationFrame(this.tick);
  }

  ngOnDestroy(): void {
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
  }

  viewBoxStr(): string {
    const z = this.zoom();
    return `${z.x} ${z.y} ${VIEW_W / z.scale} ${VIEW_H / z.scale}`;
  }

  resetZoom(): void {
    this.zoom.set({ scale: 1, x: 0, y: 0 });
  }

  /** Zoom in/out around the cursor, keeping the point under it fixed on screen. */
  onWheel(event: WheelEvent): void {
    event.preventDefault();
    this.svgEl = event.currentTarget as SVGSVGElement;
    const cursor = this.toViewBox(event);
    if (!cursor) return;
    const z = this.zoom();
    const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    const newScale = Math.min(Math.max(z.scale * factor, 0.5), 8);
    const sizeOldX = VIEW_W / z.scale;
    const sizeOldY = VIEW_H / z.scale;
    const fracX = (cursor.x - z.x) / sizeOldX;
    const fracY = (cursor.y - z.y) / sizeOldY;
    const sizeNewX = VIEW_W / newScale;
    const sizeNewY = VIEW_H / newScale;
    this.zoom.set({ scale: newScale, x: cursor.x - fracX * sizeNewX, y: cursor.y - fracY * sizeNewY });
  }

  // ─── Live spring simulation ────────────────────────────────────────────────

  /** Current rendered position of a node (`pi:<position>` or `ap:<key>`). Falls back to canvas
   * center before the first simulation tick has run (imperceptible — the loop starts immediately). */
  posOf(id: string): { x: number; y: number } {
    return this.simPos.get(id) ?? { x: VIEW_W / 2, y: VIEW_H / 2 };
  }

  private hashStr(s: string): number {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return h;
  }

  private ensureSimPos(id: string, pinnedX: number | null, pinnedY: number | null): void {
    if (this.simPos.has(id)) return;
    if (pinnedX !== null && pinnedY !== null) {
      this.simPos.set(id, { x: pinnedX, y: pinnedY });
    } else {
      const h = this.hashStr(id);
      this.simPos.set(id, { x: 100 + (h % 800), y: 100 + ((h >> 8) % 500) });
    }
    this.simVel.set(id, { x: 0, y: 0 });
  }

  /** One relaxation step: all-pairs repulsion (declutter) + spring attraction along every
   * WiFi (Pi<->AP) and BLE (Pi<->Pi) edge, weighted by signal strength (stronger = shorter,
   * stiffer spring). Pinned nodes and whatever's being dragged are frozen each tick — they act
   * as immovable anchors for everything else's springs, exactly like a real force-directed graph. */
  private readonly tick = (): void => {
    interface N { id: string; pinnedX: number | null; pinnedY: number | null }
    const nodes: N[] = [
      ...this.piNodes().map((p) => ({ id: `pi:${p.position}`, pinnedX: p.pinned ? p.x : null, pinnedY: p.pinned ? p.y : null })),
      ...this.apNodes().map((a) => ({ id: `ap:${a.key}`, pinnedX: a.pinned ? a.x : null, pinnedY: a.pinned ? a.y : null })),
    ];
    for (const n of nodes) this.ensureSimPos(n.id, n.pinnedX, n.pinnedY);

    interface Spring { a: string; b: string; weight: number }
    const springs: Spring[] = [];
    for (const e of this.edges()) {
      const apKey = this.bssidToKey.get(e.bssid);
      if (apKey) springs.push({ a: `pi:${e.position}`, b: `ap:${apKey}`, weight: this.rssiStrength(e.rssi) });
    }
    for (const e of this.bleEdges()) {
      springs.push({ a: `pi:${e.position_a}`, b: `pi:${e.position_b}`, weight: this.rssiStrength(e.rssi) });
    }

    const REPULSION = 15000;
    const SPRING_K = 0.02;
    const SPRING_LEN = 120;
    const DAMPING = 0.82;
    const CENTER_PULL = 0.0008;

    const posById = new Map(nodes.map((n) => [n.id, this.simPos.get(n.id)!]));
    const forces = new Map<string, { x: number; y: number }>(nodes.map((n) => [n.id, { x: 0, y: 0 }]));

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = posById.get(nodes[i].id)!;
        const b = posById.get(nodes[j].id)!;
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const distSq = Math.max(dx * dx + dy * dy, 25);
        const dist = Math.sqrt(distSq);
        const f = REPULSION / distSq;
        const fx = (dx / dist) * f;
        const fy = (dy / dist) * f;
        const fa = forces.get(nodes[i].id)!;
        fa.x += fx; fa.y += fy;
        const fb = forces.get(nodes[j].id)!;
        fb.x -= fx; fb.y -= fy;
      }
    }

    for (const s of springs) {
      const a = posById.get(s.a);
      const b = posById.get(s.b);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(Math.hypot(dx, dy), 1);
      const restLen = SPRING_LEN / Math.max(s.weight, 0.1);
      const k = SPRING_K * (0.3 + s.weight);
      const stretch = dist - restLen;
      const fx = (dx / dist) * stretch * k;
      const fy = (dy / dist) * stretch * k;
      const fa = forces.get(s.a);
      if (fa) { fa.x += fx; fa.y += fy; }
      const fb = forces.get(s.b);
      if (fb) { fb.x -= fx; fb.y -= fy; }
    }

    for (const n of nodes) {
      const pos = this.simPos.get(n.id)!;
      if (this.dragging?.id === n.id) {
        pos.x = this.dragging.x;
        pos.y = this.dragging.y;
        this.simVel.set(n.id, { x: 0, y: 0 });
        continue;
      }
      if (n.pinnedX !== null && n.pinnedY !== null) {
        pos.x = n.pinnedX;
        pos.y = n.pinnedY;
        this.simVel.set(n.id, { x: 0, y: 0 });
        continue;
      }
      const f = forces.get(n.id)!;
      f.x += (VIEW_W / 2 - pos.x) * CENTER_PULL;
      f.y += (VIEW_H / 2 - pos.y) * CENTER_PULL;
      const vel = this.simVel.get(n.id)!;
      vel.x = (vel.x + f.x) * DAMPING;
      vel.y = (vel.y + f.y) * DAMPING;
      pos.x += vel.x;
      pos.y += vel.y;
    }

    const liveIds = new Set(nodes.map((n) => n.id));
    for (const id of [...this.simPos.keys()]) {
      if (!liveIds.has(id)) {
        this.simPos.delete(id);
        this.simVel.delete(id);
      }
    }

    this.rafId = requestAnimationFrame(this.tick);
  };

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
      this.edges.set(m.edges);
      this.bleEdges.set(m.pi_ble_edges);
      this.apNodes.set(this.groupAccessPoints(m.access_points));
    } catch (e) {
      this.error.set(errorMessage(e));
    } finally {
      this.loading.set(false);
    }
  }

  /** bssid → ApGroup.key. Lets apDegree/visibleEdges/the simulation resolve a raw BSSID to its box. */
  private bssidToKey = new Map<string, string>();

  /** One box per `group_name` (several BSSIDs manually grouped — see `openApMenu`), or per
   * BSSID when ungrouped. */
  private groupAccessPoints(aps: AccessPointOut[]): ApGroup[] {
    this.bssidToKey = new Map();
    const groups = new Map<string, ApGroup>();
    for (const ap of aps) {
      const key = ap.group_name ?? ap.bssid;
      const g = groups.get(key) ?? { key, bssids: [], ssids: [], x: null, y: null, pinned: false };
      g.bssids.push(ap.bssid);
      const ssidsToAdd = ap.ssid ? [...ap.ssids, ap.ssid] : ap.ssids;
      for (const s of ssidsToAdd) {
        if (!g.ssids.includes(s)) g.ssids.push(s);
      }
      if (!g.pinned && ap.x !== null && ap.y !== null) {
        g.x = ap.x;
        g.y = ap.y;
        g.pinned = true;
      }
      groups.set(key, g);
      this.bssidToKey.set(ap.bssid, key);
    }
    return [...groups.values()];
  }

  /** Click (without dragging) an AP box: pin/unpin, or assign it to a manual group — "Group to:"
   * with a "New group…" option and every existing group name listed. BSSIDs sharing a group
   * render as one box. */
  async openApMenu(ap: ApGroup): Promise<void> {
    let groups: string[] = [];
    try {
      groups = await firstValueFrom(this.api.listAccessPointGroups());
    } catch {
      // non-fatal — menu still works without the group list
    }
    const currentlyGrouped = groups.includes(ap.key);

    const buttons: Array<{ text: string; role?: string; handler?: () => void }> = [
      ap.pinned
        ? { text: 'Unpin', handler: () => void this.unpinAp(ap) }
        : { text: 'Pin here', handler: () => void this.pinApAtCurrentPos(ap) },
      { text: 'New group…', handler: () => void this.promptNewGroup(ap) },
      ...groups.filter((g) => g !== ap.key).map((g) => ({ text: g, handler: () => void this.assignGroup(ap, g) })),
    ];
    if (currentlyGrouped) {
      buttons.push({ text: 'Remove from group', role: 'destructive', handler: () => void this.assignGroup(ap, null) });
    }
    buttons.push({ text: 'Cancel', role: 'cancel' });

    const sheet = await this.actionSheets.create({ header: this.apLabel(ap), buttons });
    await sheet.present();
  }

  async openPiMenu(pi: FloorMapPiNode): Promise<void> {
    const buttons: Array<{ text: string; role?: string; handler?: () => void }> = [
      pi.pinned
        ? { text: 'Unpin', role: 'destructive', handler: () => void this.unpinPi(pi.position) }
        : { text: 'Pin here', handler: () => void this.pinPiAtCurrentPos(pi.position) },
      { text: 'Cancel', role: 'cancel' },
    ];
    const sheet = await this.actionSheets.create({ header: `Pi ${pi.position}`, buttons });
    await sheet.present();
  }

  private async pinApAtCurrentPos(ap: ApGroup): Promise<void> {
    const pos = this.simPos.get(`ap:${ap.key}`);
    if (!pos) return;
    try {
      await Promise.all(ap.bssids.map((bssid) => firstValueFrom(this.api.placeAccessPoint(bssid, pos.x, pos.y))));
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  private async unpinAp(ap: ApGroup): Promise<void> {
    try {
      await Promise.all(ap.bssids.map((bssid) => firstValueFrom(this.api.unpinAccessPoint(bssid))));
      await this.load();
    } catch (e) {
      this.error.set(errorMessage(e));
    }
  }

  private async pinPiAtCurrentPos(position: string): Promise<void> {
    const pos = this.simPos.get(`pi:${position}`);
    if (!pos) return;
    try {
      await firstValueFrom(this.api.pinPi(position, pos.x, pos.y));
      await this.load();
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

  private async assignGroup(ap: ApGroup, groupName: string | null): Promise<void> {
    try {
      await Promise.all(ap.bssids.map((bssid) => firstValueFrom(this.api.setAccessPointGroup(bssid, groupName))));
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
  visibleApNodes(): ApGroup[] {
    const terms = this.apFilterTerms();
    if (terms.length === 0) return this.apNodes();
    return this.apNodes().filter((g) => g.ssids.some((s) => terms.some((t) => s.toLowerCase().includes(t))));
  }

  unpinnedApCount(): number {
    return this.visibleApNodes().filter((g) => !g.pinned).length;
  }

  /** Node size reflects its connection count, like Obsidian's graph view. */
  nodeRadius(degree: number): number {
    return Math.min(6 + degree * 1.5, 16);
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
    const visibleKeys = new Set(this.visibleApNodes().map((a) => a.key));
    return this.edges().filter((e) => e.position === position && visibleKeys.has(this.bssidToKey.get(e.bssid) ?? '')).length;
  }

  apDegree(key: string): number {
    return this.edges().filter((e) => this.bssidToKey.get(e.bssid) === key).length;
  }

  /** Edges with both endpoints resolved to their live simulated position, weighted by RSSI
   * (stroke width/opacity). Only to APs that survive the SSID filter — a filtered-out box's
   * connections disappear too. */
  visibleEdges(): Array<{ position: string; groupKey: string; x1: number; y1: number; x2: number; y2: number; width: number; opacity: number }> {
    const apByKey = new Map(this.visibleApNodes().map((a) => [a.key, a]));
    const out: Array<{ position: string; groupKey: string; x1: number; y1: number; x2: number; y2: number; width: number; opacity: number }> = [];
    for (const e of this.edges()) {
      const groupKey = this.bssidToKey.get(e.bssid);
      if (!groupKey || !apByKey.has(groupKey)) continue;
      const piPos = this.posOf(`pi:${e.position}`);
      const apPos = this.posOf(`ap:${groupKey}`);
      const strength = this.rssiStrength(e.rssi);
      out.push({
        position: e.position, groupKey, x1: piPos.x, y1: piPos.y, x2: apPos.x, y2: apPos.y,
        width: 0.5 + strength * 3, opacity: 0.15 + strength * 0.6,
      });
    }
    return out;
  }

  /** Pi<->Pi BLE sightings, both endpoints at their live simulated position. */
  visibleBleEdges(): Array<PiBleEdge & { x1: number; y1: number; x2: number; y2: number; width: number; opacity: number }> {
    const out: Array<PiBleEdge & { x1: number; y1: number; x2: number; y2: number; width: number; opacity: number }> = [];
    for (const e of this.bleEdges()) {
      const a = this.posOf(`pi:${e.position_a}`);
      const b = this.posOf(`pi:${e.position_b}`);
      const strength = this.rssiStrength(e.rssi);
      out.push({ ...e, x1: a.x, y1: a.y, x2: b.x, y2: b.y, width: 1.5 + strength * 3.5, opacity: 0.5 + strength * 0.5 });
    }
    return out;
  }

  private rssiStrength(rssi: number): number {
    const clamped = Math.min(Math.max(rssi, RSSI_WEAK), RSSI_STRONG);
    return (clamped - RSSI_WEAK) / (RSSI_STRONG - RSSI_WEAK);
  }

  onNodePointerDown(
    event: PointerEvent, kind: 'pi' | 'ap', id: string, wasPinned: boolean, bssids?: string[], position?: string,
  ): void {
    event.stopPropagation(); // don't also start a background pan
    this.svgEl = (event.currentTarget as SVGGraphicsElement).ownerSVGElement;
    const pt = this.toViewBox(event);
    if (!pt) return;
    this.dragging = { id, kind, wasPinned, bssids, position, x: pt.x, y: pt.y, startScreen: { x: event.clientX, y: event.clientY } };
  }

  /** Pointerdown on empty canvas (not a node, which stops propagation) — pan the view. */
  onBackgroundPointerDown(event: PointerEvent): void {
    if (this.dragging) return;
    this.svgEl = event.currentTarget as SVGSVGElement;
    this.panStart = { clientX: event.clientX, clientY: event.clientY, zoom: this.zoom() };
    this.panning.set(true);
  }

  onPointerMove(event: PointerEvent): void {
    if (this.dragging) {
      const pt = this.toViewBox(event);
      if (!pt) return;
      this.dragging = { ...this.dragging, x: pt.x, y: pt.y };
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

  /** Drag release: a near-zero-movement "drag" is treated as a click (opens the pin/group menu).
   * A real drag only persists (pins) the node if it was *already* pinned before the drag — dragging
   * a free-floating node just drops it there and lets the simulation keep going from that spot;
   * nothing becomes fixed unless you explicitly say so via the menu. */
  async onPointerUp(event?: PointerEvent): Promise<void> {
    this.panStart = null;
    this.panning.set(false);
    if (!this.dragging) return;
    const { id, kind, wasPinned, bssids, position, x, y, startScreen } = this.dragging;
    this.dragging = null;

    const moved = event ? Math.hypot(event.clientX - startScreen.x, event.clientY - startScreen.y) : Infinity;
    if (moved < FloorMapPage.CLICK_THRESHOLD_PX) {
      if (kind === 'ap') {
        const key = id.slice(3);
        const ap = this.apNodes().find((a) => a.key === key) ?? { key, bssids: bssids ?? [], ssids: [], x: null, y: null, pinned: false };
        await this.openApMenu(ap);
      } else if (position) {
        const pi = this.piNodes().find((p) => p.position === position);
        if (pi) await this.openPiMenu(pi);
      }
      return;
    }

    if (!wasPinned) return; // free node — stays free, dropped position is purely client-side
    try {
      if (kind === 'ap' && bssids) {
        await Promise.all(bssids.map((bssid) => firstValueFrom(this.api.placeAccessPoint(bssid, x, y))));
      } else if (kind === 'pi' && position) {
        await firstValueFrom(this.api.pinPi(position, x, y));
      }
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
