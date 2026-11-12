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
  { path: 'forgot', canActivate: [guestGuard], loadComponent: () => import('./auth/password-reset.component').then((m) => m.ForgotPasswordComponent) },
  { path: 'reset/:token', loadComponent: () => import('./auth/password-reset.component').then((m) => m.ResetPasswordComponent) },
  { path: 'signup', canActivate: [guestGuard], loadComponent: () => import('./auth/signup.component').then((m) => m.SignupComponent) },
  {
    path: 'app',
    canActivate: [staffGuard],
    loadComponent: () => import('./app-shell/shell.component').then((m) => m.ShellComponent),
    children: [
      { path: '', loadComponent: () => import('./pages/home.component').then((m) => m.HomeComponent) },
      { path: 'access', loadComponent: () => import('./pages/access.component').then((m) => m.AccessComponent) },
      { path: 'users', canActivate: [staffGuard], data: { area: 'users' }, loadComponent: () => import('./pages/users.component').then((m) => m.UsersComponent) },
      { path: 'leads', canActivate: [staffGuard], data: { area: 'leads' }, loadComponent: () => import('./pages/leads/leads.component').then((m) => m.LeadsComponent) },
      { path: 'leads/:id', canActivate: [staffGuard], data: { area: 'leads' }, loadComponent: () => import('./pages/leads/lead-detail.component').then((m) => m.LeadDetailComponent) },
      { path: 'proposals', canActivate: [staffGuard], data: { area: 'proposals' }, loadComponent: () => import('./pages/proposals/proposals.component').then((m) => m.ProposalsComponent) },
      { path: 'proposals/:id', canActivate: [staffGuard], data: { area: 'proposals' }, loadComponent: () => import('./pages/proposals/proposal-builder.component').then((m) => m.ProposalBuilderComponent) },
      { path: 'proposals/:id/preview', canActivate: [staffGuard], data: { area: 'proposals' }, loadComponent: () => import('./pages/proposals/proposal-view.component').then((m) => m.ProposalViewComponent) },
      { path: 'contracts/:id', canActivate: [staffGuard], loadComponent: () => import('./pages/proposals/contract.component').then((m) => m.ContractComponent) },
      { path: 'followups', canActivate: [staffGuard], data: { area: 'followups' }, loadComponent: () => import('./pages/followups.component').then((m) => m.FollowupsComponent) },
      { path: 'reports', canActivate: [staffGuard], data: { area: 'reports' }, loadComponent: () => import('./pages/reports.component').then((m) => m.ReportsComponent) },
      { path: 'contacts', canActivate: [staffGuard], data: { area: 'contacts' }, loadComponent: () => import('./pages/contacts/contacts.component').then((m) => m.ContactsComponent) },
      { path: 'contacts/:id', canActivate: [staffGuard], data: { area: 'contacts' }, loadComponent: () => import('./pages/contacts/contact-detail.component').then((m) => m.ContactDetailComponent) },
      { path: 'projects', canActivate: [staffGuard], data: { area: 'projects' }, loadComponent: () => import('./pages/projects/projects.component').then((m) => m.ProjectsComponent) },
      { path: 'projects/:id', canActivate: [staffGuard], data: { area: 'projects' }, loadComponent: () => import('./pages/projects/project-detail.component').then((m) => m.ProjectDetailComponent) },
      { path: 'invoices/:id', canActivate: [staffGuard], data: { area: 'finance' }, loadComponent: () => import('./pages/invoice-view.component').then((m) => m.InvoiceViewComponent) },
      { path: 'inbox', canActivate: [staffGuard], data: { area: 'messages' }, loadComponent: () => import('./pages/inbox.component').then((m) => m.InboxComponent) },
      { path: 'site-reports', canActivate: [staffGuard], data: { area: 'site' }, loadComponent: () => import('./pages/site-reports.component').then((m) => m.SiteReportsComponent) },
      { path: 'selections', canActivate: [staffGuard], data: { area: 'selections' }, loadComponent: () => import('./pages/selections.component').then((m) => m.SelectionsComponent) },
      { path: 'documents', canActivate: [staffGuard], data: { area: 'documents' }, loadComponent: () => import('./pages/documents.component').then((m) => m.DocumentsComponent) },
      { path: 'change-orders', canActivate: [staffGuard], data: { area: 'change_orders' }, loadComponent: () => import('./pages/change-orders.component').then((m) => m.ChangeOrdersComponent) },
      { path: 'procurement', canActivate: [staffGuard], data: { area: 'procurement' }, loadComponent: () => import('./pages/procurement.component').then((m) => m.ProcurementComponent) },
      { path: 'purchase-orders/:id', canActivate: [staffGuard], data: { area: 'procurement' }, loadComponent: () => import('./pages/purchase-order.component').then((m) => m.PurchaseOrderComponent) },
      { path: 'finance', canActivate: [staffGuard], data: { area: 'finance' }, loadComponent: () => import('./pages/finance.component').then((m) => m.FinanceComponent) },
      { path: 'settings', canActivate: [staffGuard], data: { area: 'settings' }, loadComponent: () => import('./pages/settings.component').then((m) => m.SettingsComponent) },
      { path: 'm/:area', canActivate: [staffGuard], loadComponent: () => import('./pages/area.component').then((m) => m.AreaComponent) },
      { path: 'forbidden', loadComponent: () => import('./pages/area.component').then((m) => m.ForbiddenComponent) },
    ],
  },
  { path: 'f/:key', loadComponent: () => import('./pages/public-form.component').then((m) => m.PublicFormComponent) },
  { path: 'p/:token', loadComponent: () => import('./pages/proposals/proposal-view.component').then((m) => m.ProposalViewComponent) },
  { path: 'q/:token', loadComponent: () => import('./pages/public-questionnaire.component').then((m) => m.PublicQuestionnaireComponent) },
  { path: 'portal', canActivate: [portalGuard], loadComponent: () => import('./pages/portal.component').then((m) => m.PortalComponent) },
  { path: 'sa/login', loadComponent: () => import('./superadmin/sa-login.component').then((m) => m.SaLoginComponent) },
  {
    path: 'sa',
    canActivate: [saGuard],
    loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaShellComponent),
    children: [
      { path: '', loadComponent: () => import('./superadmin/sa-platform.component').then((m) => m.SaOverviewComponent) },
      { path: 'companies', canActivate: [saGuard], data: { area: 'companies' }, loadComponent: () => import('./superadmin/sa-platform.component').then((m) => m.SaCompanyListComponent) },
      { path: 'companies/:id', canActivate: [saGuard], data: { area: 'companies' }, loadComponent: () => import('./superadmin/sa-platform.component').then((m) => m.SaCompanyComponent) },
      { path: 'plans', loadComponent: () => import('./superadmin/sa-platform.component').then((m) => m.SaPlansComponent) },
      { path: 'billing', canActivate: [saGuard], data: { area: 'billing' }, loadComponent: () => import('./superadmin/sa-platform.component').then((m) => m.SaBillingComponent) },
      { path: 'support', loadComponent: () => import('./superadmin/sa-platform.component').then((m) => m.SaSupportComponent) },
      { path: 'reports', loadComponent: () => import('./superadmin/sa-platform.component').then((m) => m.SaReportsComponent) },
      { path: 'settings', loadComponent: () => import('./superadmin/sa-platform.component').then((m) => m.SaSettingsComponent) },
      { path: 'team', canActivate: [saGuard], data: { area: 'settings' }, loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaTeamComponent) },
      { path: 'access', loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaAccessComponent) },
      { path: 'audit', loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaAuditComponent) },
      { path: 'forbidden', loadComponent: () => import('./superadmin/sa-pages.component').then((m) => m.SaForbiddenComponent) },
    ],
  },
  { path: '**', redirectTo: 'login' },
];
