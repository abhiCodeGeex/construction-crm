import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { AuthService } from './auth.service';

/** Adds the right bearer token (Super Admin vs company) and ends the session on 401. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const isSa = req.url.startsWith('/api/sa/');
  const token = isSa ? auth.sa()?.token : auth.session()?.token;
  const authed = token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
  const isLogin = req.url.endsWith('/login') || req.url.endsWith('/signup');

  return next(authed).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status === 401 && !isLogin) {
        if (isSa) auth.saLogout();
        else auth.logout();
      }
      return throwError(() => err);
    }),
  );
};

export function errorText(err: unknown): string {
  const e = err as HttpErrorResponse;
  return e?.error?.error || e?.message || 'Something went wrong';
}
