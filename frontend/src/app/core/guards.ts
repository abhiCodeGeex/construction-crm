import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';
import { Level } from './models';

/** Signed-in company staff. Route data { area, level } adds a permission check. */
export const staffGuard: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.session()) return router.parseUrl('/login');
  if (!auth.isStaff()) return router.parseUrl('/portal');
  const area = (route.data?.['area'] ?? route.params?.['area']) as string | undefined;
  const level = (route.data?.['level'] as Level) ?? 'r';
  if (area && !auth.can(area, level)) return router.parseUrl(`/app/forbidden?area=${area}`);
  return true;
};

/** Clients, vendors, subcontractors, consultants. */
export const portalGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.session()) return router.parseUrl('/login');
  return auth.isExternal() ? true : router.parseUrl('/app');
};

/** Login / signup pages redirect away when already signed in. */
export const guestGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.session() ? inject(Router).parseUrl(auth.homeFor()) : true;
};

export const saGuard: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.sa()) return router.parseUrl('/sa/login');
  const area = route.data?.['area'] as string | undefined;
  if (area && !auth.saCan(area)) return router.parseUrl('/sa/forbidden');
  return true;
};
