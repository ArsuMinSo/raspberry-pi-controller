import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { API, AuthService } from './auth.service';

/** Adds the Bearer token to API calls; a 401 (session expired/revoked) sends the user to the login page. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  if (!req.url.startsWith(API)) {
    return next(req);
  }
  const token = auth.token;
  const isLogin = req.url === `${API}/auth/login`;
  const authed = token && !isLogin ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;

  return next(authed).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && !isLogin && token) {
        auth.endSession('expired');
      }
      return throwError(() => err);
    }),
  );
};
