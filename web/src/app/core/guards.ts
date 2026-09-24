import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';
import { Role } from './models';

/** Logged in, and not forced to change the password first (the account page itself is exempt). */
export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.loggedIn()) {
    return router.createUrlTree(['/login']);
  }
  if (auth.user()?.must_change_password && !state.url.startsWith('/account')) {
    return router.createUrlTree(['/account'], { queryParams: { force: 1 } });
  }
  return true;
};

/** Login page only when logged out. */
export const guestGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.loggedIn() ? inject(Router).createUrlTree(['/inventory']) : true;
};

/** Page needs at least `role` (the server enforces it too); others go to the inventory. */
export function roleGuard(role: Role): CanActivateFn {
  return () => {
    const auth = inject(AuthService);
    return auth.can(role) ? true : inject(Router).createUrlTree(['/inventory']);
  };
}
