import { Routes } from '@angular/router';
import { guestGuard, portalGuard, saGuard, staffGuard } from './core/guards';

/**
 * Each future module adds its own lazy route under /app with `data: { area }` — the staff guard
 * then enforces the same permission the API enforces. The `m/:area` placeholder stays as the
 * fallback for modules not built yet.
 */
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'login' },
  { path: 'login', canActivate: [guestGuard], loadComponent: () => import('./auth/login.component').then((m) => m.LoginComponent) },
  { path: 'signup', canActivate: [guestGuard], loadComponent: () => import('./auth/signup.component').then((m) => m.SignupComponent) },
  {
    path: 'app',
    canActivate: [staffGuard],
    loadComponent: () => import('./app-shell/shell.component').then((m) => m.ShellComponent),
    children: [
      { path: '', loadComponent: () => import('./pages/home.component').then((m) => m.HomeComponent) },
      { path: 'access', loadComponent: () => import('./pages/access.component').then((m) => m.AccessComponent) },
      { path: 'users', canActivate: [staffGuard], data: { area: 'users' }, loadComponent: () => import('./pages/users.component').then((m) => m.UsersComponent) },
      { path: 'settings', canActivate: [staffGuard], data: { area: 'settings' }, loadComponent: () => import('./pages/settings.component').then((m) => m.SettingsComponent) },
      { path: 'm/:area', canActivate: [staffGuard], loadComponent: () => import('./pages/area.component').then((m) => m.AreaComponent) },
      { path: 'forbidden', loadComponent: () => import('./pages/area.component').then((m) => m.ForbiddenComponent) },
    ],
  },
  { path: 'portal', canActivate: [portalGuard], loadComponent: () => import('./pages/portal.component').then((m) => m.PortalComponent) },
  { path: 'sa/login', loadComponent: () => import('./superadmin/sa-login.component').then((m) => m.SaLoginComponent) },
  {
    path: 'sa',
    canActivate: [saGuard],
    loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaShellComponent),
    children: [
      { path: '', loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaDashboardComponent) },
      { path: 'companies', canActivate: [saGuard], data: { area: 'companies' }, loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaCompaniesComponent) },
      { path: 'team', canActivate: [saGuard], data: { area: 'settings' }, loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaTeamComponent) },
      { path: 'access', loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaAccessComponent) },
      { path: 'audit', loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaAuditComponent) },
      { path: 'forbidden', loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaForbiddenComponent) },
    ],
  },
  { path: '**', redirectTo: 'login' },
];
