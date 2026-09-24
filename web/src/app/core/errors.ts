import { HttpErrorResponse } from '@angular/common/http';

/** Human-readable message from a backend error (FastAPI returns {detail: string | [...]}). */
export function errorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0) {
      return "Can't reach the server";
    }
    const detail = (err.error as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string };
      return first.msg ?? `Request failed (${err.status})`;
    }
    return `Request failed (${err.status})`;
  }
  return err instanceof Error ? err.message : 'Unexpected error';
}
