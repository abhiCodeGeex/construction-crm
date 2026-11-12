import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ConfirmationService, MessageService } from 'primeng/api';
import { AvatarModule } from 'primeng/avatar';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';
import { ThemeService } from '../core/theme.service';

const SA_NAV = [
  { path: '/sa', label: 'Dashboard', icon: 'pi pi-chart-line', area: 'dashboard', exact: true },
  { path: '/sa/companies', label: 'Companies', icon: 'pi pi-building', area: 'companies' },
  { path: '/sa/plans', label: 'Plans and coupons', icon: 'pi pi-tags', area: 'dashboard' },
  { path: '/sa/billing', label: 'Billing', icon: 'pi pi-receipt', area: 'billing' },
  { path: '/sa/support', label: 'Support and news', icon: 'pi pi-comments', area: 'dashboard' },
  { path: '/sa/reports', label: 'Reports and usage', icon: 'pi pi-chart-bar', area: 'dashboard' },
  { path: '/sa/settings', label: 'Platform settings', icon: 'pi pi-cog', area: 'dashboard' },
  { path: '/sa/team', label: 'Super Admin team', icon: 'pi pi-users', area: 'settings' },
  { path: '/sa/access', label: 'My access', icon: 'pi pi-shield', area: 'dashboard' },
  { path: '/sa/audit', label: 'Audit log', icon: 'pi pi-history', area: 'dashboard' },
];

const SEVERITY: Record<string, 'success' | 'info' | 'warn' | 'danger' | 'secondary'> = {
  active: 'success', trial: 'info', read_only: 'warn', suspended: 'danger', cancelled: 'secondary',
};

@Component({
  selector: 'app-sa-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, AvatarModule, ButtonModule, TagModule],
  template: `
    <div class="layout sa">
      <aside class="sidebar">
        <div class="logo"><span class="mark"><i class="pi pi-shield"></i></span><span class="txt">Super Admin</span></div>
        <nav>
          @for (n of nav(); track n.path) {
            <a [routerLink]="n.path" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: !!n.exact }"><i [class]="n.icon"></i><span class="txt">{{ n.label }}</span></a>
          }
        </nav>
      </aside>
      <div class="main">
        <header class="topbar">
          <div class="company-name">BuildSuite platform</div>
          <span class="spacer"></span>
          <p-button [icon]="theme.dark() ? 'pi pi-sun' : 'pi pi-moon'" [rounded]="true" [text]="true" severity="secondary" (onClick)="theme.toggle()" />
          <div class="who static">
            <p-avatar icon="pi pi-shield" shape="circle" styleClass="avatar" />
            <span class="who-text"><strong>{{ auth.sa()?.user?.name }}</strong><small class="cap">{{ auth.sa()?.user?.role }}</small></span>
          </div>
          <p-button icon="pi pi-sign-out" [text]="true" severity="secondary" (onClick)="auth.saLogout()" ariaLabel="Sign out" />
        </header>
        <main class="content"><router-outlet /></main>
      </div>
    </div>
  `,
})
export class SaShellComponent {
  auth = inject(AuthService);
  theme = inject(ThemeService);
  nav = computed(() => SA_NAV.filter((n) => this.auth.saCan(n.area)));
}

@Component({
  selector: 'app-sa-dashboard',
  template: `
    <div class="page-head"><div><h1>Platform dashboard</h1><p class="muted">Companies and users across the platform — counts only, no private data.</p></div></div>
    @if (d(); as d) {
      <div class="stats">
        <div class="stat-card"><span class="stat-icon indigo"><i class="pi pi-building"></i></span><div><small>Companies</small><strong>{{ d.companies.total }}</strong></div></div>
        <div class="stat-card"><span class="stat-icon teal"><i class="pi pi-check-circle"></i></span><div><small>Active</small><strong>{{ d.companies.active ?? 0 }}</strong></div></div>
        <div class="stat-card"><span class="stat-icon amber"><i class="pi pi-clock"></i></span><div><small>On trial</small><strong>{{ d.companies.trial ?? 0 }}</strong></div></div>
        <div class="stat-card"><span class="stat-icon pink"><i class="pi pi-ban"></i></span><div><small>Suspended</small><strong>{{ d.companies.suspended ?? 0 }}</strong></div></div>
        <div class="stat-card"><span class="stat-icon indigo"><i class="pi pi-users"></i></span><div><small>Staff users</small><strong>{{ d.users }}</strong></div></div>
        <div class="stat-card"><span class="stat-icon teal"><i class="pi pi-globe"></i></span><div><small>Portal users</small><strong>{{ d.portal_users }}</strong></div></div>
      </div>
    }
  `,
})
export class SaDashboardComponent implements OnInit {
  private http = inject(HttpClient);
  d = signal<any>(null);
  async ngOnInit() {
    this.d.set(await firstValueFrom(this.http.get('/api/sa/dashboard')));
  }
}

@Component({
  selector: 'app-sa-companies',
  imports: [DatePipe, ButtonModule, CardModule, TableModule, TagModule],
  template: `
    <div class="page-head"><div><h1>Companies</h1><p class="muted">Suspending a company signs all its users out immediately.</p></div></div>
    <p-card>
      <p-table [value]="rows()" size="small" [rowHover]="true">
        <ng-template #header><tr><th>Company</th><th>Plan</th><th>Modules</th><th>Users</th><th>Status</th><th>Signed up</th><th></th></tr></ng-template>
        <ng-template #body let-c>
          <tr>
            <td><strong>{{ c.name }}</strong><br /><small class="muted">{{ c.owner_email }}</small></td>
            <td class="cap">{{ c.plan_code }}</td>
            <td><small>{{ c.modules?.join(', ') }}</small></td>
            <td>{{ c.usage.users }} <small class="muted">+{{ c.usage.free_users }} free</small></td>
            <td><p-tag [value]="c.status" [severity]="sev(c.status)" /></td>
            <td><small>{{ c.created_at | date }}</small></td>
            <td class="right">
              @if (c.status === 'suspended') {
                <p-button label="Reactivate" size="small" severity="success" [outlined]="true" [disabled]="!canEdit()" (onClick)="act(c, 'reactivate')" />
              } @else {
                <p-button label="Suspend" size="small" severity="danger" [outlined]="true" [disabled]="!canEdit()" (onClick)="act(c, 'suspend')" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="20" class="muted center small">Nothing to show yet.</td></tr></ng-template>
      </p-table>
      @if (!canEdit()) { <p class="muted small"><i class="pi pi-eye"></i> Your role can view companies but not change them.</p> }
    </p-card>
  `,
})
export class SaCompaniesComponent implements OnInit {
  private http = inject(HttpClient);
  private auth = inject(AuthService);
  private toast = inject(MessageService);
  private confirm = inject(ConfirmationService);
  rows = signal<any[]>([]);
  canEdit = computed(() => this.auth.saCan('companies', 'rw'));
  sev = (s: string) => SEVERITY[s] ?? 'secondary';

  async ngOnInit() {
    this.rows.set(await firstValueFrom(this.http.get<any[]>('/api/sa/companies')));
  }

  act(c: any, action: string) {
    this.confirm.confirm({
      header: `${action === 'suspend' ? 'Suspend' : 'Reactivate'} ${c.name}?`,
      message: action === 'suspend' ? 'All users of this company are blocked until it is reactivated. No data is deleted.' : 'Users will be able to sign in again.',
      icon: 'pi pi-exclamation-triangle',
      acceptButtonProps: { label: action === 'suspend' ? 'Suspend' : 'Reactivate', severity: action === 'suspend' ? 'danger' : 'success' },
      rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: async () => {
        try {
          await firstValueFrom(this.http.post(`/api/sa/companies/${c.id}/action`, { action }));
          this.toast.add({ severity: 'success', summary: `${c.name} ${action === 'suspend' ? 'suspended' : 'reactivated'}` });
          await this.ngOnInit();
        } catch (e) {
          this.toast.add({ severity: 'error', summary: 'Not changed', detail: errorText(e) });
        }
      },
    });
  }
}

@Component({
  selector: 'app-sa-team',
  imports: [FormsModule, DatePipe, ButtonModule, CardModule, DialogModule, InputTextModule, MessageModule, PasswordModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div><h1>Super Admin team</h1><p class="muted">Owner · Billing · Support · Sales · Viewer. Every action is logged.</p></div>
      <p-button label="Add member" icon="pi pi-plus" (onClick)="open()" />
    </div>
    <p-card>
      <p-table [value]="rows()" size="small">
        <ng-template #header><tr><th>Name</th><th>Role</th><th>Status</th><th>Two-factor</th><th>Added</th><th></th></tr></ng-template>
        <ng-template #body let-u>
          <tr>
            <td><strong>{{ u.name }}</strong><br /><small class="muted">{{ u.email }}</small></td>
            <td class="cap">{{ u.role }}</td>
            <td><p-tag [value]="u.active === false ? 'Inactive' : 'Active'" [severity]="u.active === false ? 'danger' : 'success'" /></td>
            <td><p-tag [value]="u.two_factor === 'on' ? 'On' : 'Not set up yet'" [severity]="u.two_factor === 'on' ? 'success' : 'warn'" /></td>
            <td><small>{{ u.created_at | date }}</small></td>
            <td class="right">
              @if (u.id !== auth.sa()?.user?.id) {
                @if (u.two_factor === 'on') {
                  <p-button label="Reset two-factor" size="small" [text]="true" severity="warn" (onClick)="resetTwoFactor(u)" />
                }
                <p-button [label]="u.active === false ? 'Activate' : 'Deactivate'" size="small" [text]="true" (onClick)="toggle(u)" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="20" class="muted center small">Nothing to show yet.</td></tr></ng-template>
      </p-table>
    </p-card>
    <p-dialog header="Add team member" [modal]="true" [(visible)]="dialog" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '96vw' }">
      <form class="stack" (ngSubmit)="save()">
        <label class="field"><span>Name</span><input pInputText name="name" [(ngModel)]="f.name" fluid /></label>
        <label class="field"><span>Email</span><input pInputText name="email" [(ngModel)]="f.email" fluid /></label>
        <label class="field"><span>Role</span><p-select name="role" [(ngModel)]="f.role" [options]="roles" fluid appendTo="body" /></label>
        <label class="field"><span>Password</span><p-password name="pw" [(ngModel)]="f.password" [toggleMask]="true" [feedback]="false" fluid appendTo="body" />
          <small class="hint" [class.ok]="f.password.length >= 8"><i class="pi" [class.pi-check-circle]="f.password.length >= 8" [class.pi-info-circle]="f.password.length < 8"></i> At least 8 characters</small></label>
        @if (error()) { <p-message severity="error" [text]="error()" /> }
        <div class="row gap right"><p-button type="submit" label="Add" icon="pi pi-check" /></div>
      </form>
    </p-dialog>
  `,
})
export class SaTeamComponent implements OnInit {
  auth = inject(AuthService);
  private http = inject(HttpClient);
  private toast = inject(MessageService);
  private confirm = inject(ConfirmationService);
  rows = signal<any[]>([]);
  dialog = false;
  error = signal('');
  roles = ['owner', 'billing', 'support', 'sales', 'viewer'];
  f = { name: '', email: '', role: 'viewer', password: '' };

  async ngOnInit() {
    this.rows.set(await firstValueFrom(this.http.get<any[]>('/api/sa/team')));
  }

  open() {
    this.f = { name: '', email: '', role: 'viewer', password: '' };
    this.error.set('');
    this.dialog = true;
  }

  async save() {
    try {
      await firstValueFrom(this.http.post('/api/sa/team', this.f));
      this.dialog = false;
      this.toast.add({ severity: 'success', summary: 'Member added', detail: 'They set up their authenticator app the first time they sign in.' });
      await this.ngOnInit();
    } catch (e) {
      this.error.set(errorText(e));
    }
  }

  /** Lost or new phone: their next sign-in asks them to set up the authenticator app again. */
  resetTwoFactor(u: any) {
    this.confirm.confirm({
      header: 'Reset two-factor?', icon: 'pi pi-exclamation-triangle',
      message: `${u.name}'s current authenticator stops working. At their next sign-in they scan a new QR code.`,
      accept: async () => {
        try {
          await firstValueFrom(this.http.put(`/api/sa/team/${u.id}`, { reset_two_factor: true }));
          this.toast.add({ severity: 'success', summary: 'Two-factor reset', detail: `${u.name} sets it up again at the next sign-in.` });
          await this.ngOnInit();
        } catch (e) {
          this.toast.add({ severity: 'error', summary: 'Not changed', detail: errorText(e) });
        }
      },
    });
  }

  async toggle(u: any) {
    try {
      await firstValueFrom(this.http.put(`/api/sa/team/${u.id}`, { active: u.active === false }));
      await this.ngOnInit();
    } catch (e) {
      this.toast.add({ severity: 'error', summary: 'Not changed', detail: errorText(e) });
    }
  }
}

@Component({
  selector: 'app-sa-access',
  imports: [ButtonModule, CardModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div><h1>My access</h1><p class="muted">Real requests against each Super Admin area — 200 allowed, 403 blocked.</p></div>
      <p-button label="Test all" icon="pi pi-play" (onClick)="testAll()" />
    </div>
    <p-card>
      <p-table [value]="matrix()" size="small">
        <ng-template #header><tr><th>Role</th>@for (a of areas(); track a) { <th class="center cap">{{ a }}</th> }</tr></ng-template>
        <ng-template #body let-r>
          <tr [class.me]="r.role === auth.sa()?.user?.role">
            <td>{{ r.label }}</td>
            @for (a of areas(); track a) {
              <td class="center">
                @if (r.perms[a] === 'rw') { <i class="pi pi-pencil c-ok"></i> } @else if (r.perms[a] === 'r') { <i class="pi pi-eye c-warn"></i> } @else { <span class="muted">—</span> }
                @if (r.role === auth.sa()?.user?.role && results()[a]; as res) {
                  <br /><p-tag [value]="res" [severity]="res.includes('403') ? 'danger' : 'success'" />
                }
              </td>
            }
          </tr>
        </ng-template>
      </p-table>
      <p class="muted small">Your row is highlighted; results show read/write status codes.</p>
    </p-card>
  `,
})
export class SaAccessComponent implements OnInit {
  auth = inject(AuthService);
  private http = inject(HttpClient);
  matrix = signal<any[]>([]);
  areas = signal<string[]>([]);
  results = signal<Record<string, string>>({});

  async ngOnInit() {
    const m = await firstValueFrom(this.http.get<any>('/api/sa/matrix'));
    this.areas.set(m.areas);
    this.matrix.set(m.roles);
  }

  private async code(method: 'GET' | 'POST', area: string) {
    try {
      await firstValueFrom(method === 'GET' ? this.http.get(`/api/sa/probe/${area}`) : this.http.post(`/api/sa/probe/${area}`, {}));
      return 200;
    } catch (e: any) {
      return e.status;
    }
  }

  async testAll() {
    for (const a of this.areas()) {
      const r = await this.code('GET', a);
      const w = await this.code('POST', a);
      this.results.update((x) => ({ ...x, [a]: `R ${r} · W ${w}` }));
    }
  }
}

@Component({
  selector: 'app-sa-audit',
  imports: [DatePipe, CardModule, TableModule],
  template: `
    <div class="page-head"><div><h1>Audit log</h1><p class="muted">Every Super Admin action — who did what, when.</p></div></div>
    <p-card>
      <p-table [value]="rows()" size="small" [paginator]="true" [rows]="15">
        <ng-template #header><tr><th>When</th><th>Who</th><th>Role</th><th>Action</th><th>Target</th></tr></ng-template>
        <ng-template #body let-a>
          <tr><td><small>{{ a.at | date: 'short' }}</small></td><td>{{ a.by }}</td><td class="cap">{{ a.role }}</td><td>{{ a.action }}</td><td><small>{{ a.target }} {{ a.note }}</small></td></tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="20" class="muted center small">Nothing to show yet.</td></tr></ng-template>
      </p-table>
    </p-card>
  `,
})
export class SaAuditComponent implements OnInit {
  private http = inject(HttpClient);
  rows = signal<any[]>([]);
  async ngOnInit() {
    this.rows.set(await firstValueFrom(this.http.get<any[]>('/api/sa/audit')));
  }
}

@Component({
  selector: 'app-sa-forbidden',
  template: `<div class="empty-state"><i class="pi pi-lock c-bad"></i><h3>Your Super Admin role cannot open this page</h3></div>`,
})
export class SaForbiddenComponent {}
