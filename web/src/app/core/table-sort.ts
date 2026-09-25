import { signal } from '@angular/core';

/** Click-to-sort state for a data table. Comparators are provided per column; `apply()` sorts a copy. */
export class TableSort<T, C extends string> {
  readonly column = signal<C | null>(null);
  readonly dir = signal<'asc' | 'desc'>('asc');

  constructor(private readonly comparators: Record<C, (a: T, b: T) => number>, defaultColumn?: C) {
    if (defaultColumn) {
      this.column.set(defaultColumn);
    }
  }

  sortBy(col: C): void {
    if (this.column() === col) {
      this.dir.set(this.dir() === 'asc' ? 'desc' : 'asc');
    } else {
      this.column.set(col);
      this.dir.set('asc');
    }
  }

  indicator(col: C): string {
    if (this.column() !== col) {
      return '';
    }
    return this.dir() === 'asc' ? ' ▲' : ' ▼';
  }

  apply(items: T[]): T[] {
    const col = this.column();
    if (!col) {
      return items;
    }
    const cmp = this.comparators[col];
    const mul = this.dir() === 'desc' ? -1 : 1;
    return [...items].sort((a, b) => cmp(a, b) * mul);
  }
}

/** Numeric-aware IPv4 compare ("10.10.20.9" before "10.10.20.10"). Nulls sort last. */
export function compareIps(a: string | null, b: string | null): number {
  if (!a && !b) return 0;
  if (!a) return 1;
  if (!b) return -1;
  const aParts = a.split('.').map((x) => parseInt(x, 10));
  const bParts = b.split('.').map((x) => parseInt(x, 10));
  for (let i = 0; i < 4; i++) {
    if (aParts[i] !== bParts[i]) return aParts[i] - bParts[i];
  }
  return 0;
}

/** Compare nullable dates/strings; nulls sort last. */
export function compareDates(a: string | null, b: string | null): number {
  if (!a && !b) return 0;
  if (!a) return 1;
  if (!b) return -1;
  return new Date(a).getTime() - new Date(b).getTime();
}

/** Case-insensitive nullable string compare; nulls sort last. */
export function compareStrings(a: string | null | undefined, b: string | null | undefined): number {
  if (!a && !b) return 0;
  if (!a) return 1;
  if (!b) return -1;
  return a.localeCompare(b);
}
