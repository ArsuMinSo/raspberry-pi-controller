import { Role } from './models';

const RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

/** True if `role` is at least `required` (viewer < operator < admin). Unknown/missing role → false. */
export function hasRole(role: string | null | undefined, required: Role): boolean {
  if (!role || !(role in RANK)) {
    return false;
  }
  return RANK[role as Role] >= RANK[required];
}

export const ROLES: Role[] = ['viewer', 'operator', 'admin'];

const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{1,31}$/;

/** Same rule as the server (backend/auth.py check_username). */
export function usernameProblem(username: string): string | null {
  if (!USERNAME_RE.test(username)) {
    return "Username: 2–32 characters, lowercase letters, digits, '.', '_' or '-'";
  }
  if (username.startsWith('local-tui')) {
    return "Username 'local-tui…' is reserved";
  }
  return null;
}
