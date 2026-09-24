import { Role } from './models';

const RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

/** True if `role` is at least `required` (viewer < operator < admin). Unknown/missing role → false. */
export function hasRole(role: string | null | undefined, required: Role): boolean {
  if (!role || !(role in RANK)) {
    return false;
  }
  return RANK[role as Role] >= RANK[required];
}
