import { WritableSignal, signal } from '@angular/core';

export interface ColumnDef<Col extends string> {
  key: Col;
  label: string;
  defaultWidth?: number; // px
  defaultVisible?: boolean; // default true
}

interface StoredState {
  visible: string[];
  widths: Record<string, number>;
}

const DEFAULT_WIDTH = 120;
const MIN_WIDTH = 40;

/** Per-table column visibility + width, persisted per-browser under a storage key. */
export class TableColumns<Col extends string> {
  readonly visible: WritableSignal<Set<Col>>;
  readonly widths: WritableSignal<Record<Col, number>>;
  private readonly storageKey: string;

  constructor(readonly defs: ColumnDef<Col>[], storageKey: string) {
    this.storageKey = `pic.cols.${storageKey}`;
    const stored = this.readStored();
    this.visible = signal(stored ? new Set(stored.visible as Col[]) : this.defaultVisible());
    this.widths = signal(stored ? { ...this.defaultWidths(), ...stored.widths } : this.defaultWidths());
  }

  private defaultVisible(): Set<Col> {
    return new Set(this.defs.filter((d) => d.defaultVisible !== false).map((d) => d.key));
  }

  private defaultWidths(): Record<Col, number> {
    return Object.fromEntries(this.defs.map((d) => [d.key, d.defaultWidth ?? DEFAULT_WIDTH])) as Record<Col, number>;
  }

  private readStored(): StoredState | null {
    try {
      const raw = localStorage.getItem(this.storageKey);
      return raw ? (JSON.parse(raw) as StoredState) : null;
    } catch {
      return null;
    }
  }

  private persist(): void {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify({ visible: [...this.visible()], widths: this.widths() }));
    } catch {
      // private window / blocked storage — visibility and widths just won't persist across reloads
    }
  }

  isVisible(col: Col): boolean {
    return this.visible().has(col);
  }

  toggle(col: Col): void {
    const next = new Set(this.visible());
    if (next.has(col)) {
      if (next.size === 1) {
        return; // always keep at least one column visible
      }
      next.delete(col);
    } else {
      next.add(col);
    }
    this.visible.set(next);
    this.persist();
  }

  width(col: Col): number {
    return this.widths()[col];
  }

  reset(): void {
    this.visible.set(this.defaultVisible());
    this.widths.set(this.defaultWidths());
    this.persist();
  }

  /** Drag-to-resize a column from a handle at its right edge. */
  startResize(col: Col, down: PointerEvent): void {
    const startX = down.clientX;
    const startWidth = this.widths()[col];
    const handle = down.target as HTMLElement;
    handle.setPointerCapture(down.pointerId);
    down.preventDefault();
    down.stopPropagation();

    const move = (e: PointerEvent): void => {
      const w = Math.max(MIN_WIDTH, Math.round(startWidth + (e.clientX - startX)));
      this.widths.set({ ...this.widths(), [col]: w });
    };
    const up = (): void => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      this.persist();
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
  }
}
