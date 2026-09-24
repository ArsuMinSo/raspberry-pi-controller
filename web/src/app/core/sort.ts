/**
 * Numeric-aware position sort — same rule as the TUI (frontend/screens/home.py `_position_sort_key`):
 * "9" < "10", legacy "01-003" → [1, 3].
 */
export function positionSortKey(position: string | null | undefined): number[] {
  return (position ?? '')
    .split('-')
    .filter((part) => /^\d+$/.test(part))
    .map((part) => parseInt(part, 10));
}

export function comparePositions(a: string | null | undefined, b: string | null | undefined): number {
  const ka = positionSortKey(a);
  const kb = positionSortKey(b);
  for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
    if (ka[i] !== kb[i]) {
      return ka[i] - kb[i];
    }
  }
  return ka.length - kb.length;
}
