import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';

const SEV: Record<string, 'success' | 'info' | 'warn' | 'danger' | 'secondary'> = {
  active: 'success', trial: 'info', pending: 'warn', read_only: 'warn', suspended: 'danger', cancelled: 'secondary',
  paid: 'success', due: 'info', overdue: 'danger', void: 'secondary', refunded: 'secondary', open: 'warn', waiting: 'info', closed: 'secondary',
};
const inr = (v: number) => '₹' + Math.round(v ?? 0).toLocaleString('en-IN');

/** Shared helper: call the Super Admin API and toast errors. */
abstract class SaBase {
  protected http = inject(HttpClient);
  protected toast = inject(MessageService);
  auth = inject(AuthService);
  sev = (s: string) => SEV[s] ?? 'secondary';
  inr = inr;

  async get<T = any>(url: string): Promise<T> {
    return firstValueFrom(this.http.get<T>('/api' + url));
  }

  async send<T = any>(method: 'post' | 'put', url: string, body: any, ok?: string): Promise<T | null> {
    try {
      const r = await firstValueFrom(method === 'post' ? this.http.post<T>('/api' + url, body) : this.http.put<T>('/api' + url, body));
      if (ok) this.toast.add({ severity: 'success', summary: ok });
      return r;
    } catch (e) {
      this.toast.add({ severity: 'error', summary: 'Not done', detail: errorText(e) });
      return null;
    }
  }
}

// ---------------------------------------------------------------- dashboard
@Component({
  selector: 'app-sa-overview',
  imports: [DatePipe, RouterLink, CardModule],
  template: `
    <div class="page-head"><div><h1>Platform dashboard</h1><p class="muted">Companies, revenue and health — counts only, never a company's private data.</p></div></div>
    @if (d(); as d) {
      <div class="stats">
        <div class="stat-card"><div><small>Companies</small><strong>{{ d.companies.total }}</strong><span class="small muted">{{ d.companies.active ?? 0 }} active · {{ d.companies.trial ?? 0 }} trial · {{ d.companies.read_only ?? 0 }} overdue · {{ d.companies.suspended ?? 0 }} suspended · {{ d.companies.cancelled ?? 0 }} cancelled</span></div></div>
        <div class="stat-card"><div><small>MRR</small><strong>{{ inr(d.mrr) }}</strong></div></div>
        <div class="stat-card"><div><small>Revenue this month</small><strong>{{ inr(d.revenue_this_month) }}</strong><span class="small muted">last month {{ inr(d.revenue_last_month) }} · year {{ inr(d.revenue_this_year) }}</span></div></div>
        <div class="stat-card"><div><small>This month</small><strong>{{ d.signups_this_month }} signups</strong><span class="small muted">{{ d.trials_converted }} converted · {{ d.cancellations_this_month }} cancelled</span></div></div>
      </div>
      <div class="grid2 top">
        <p-card header="Overdue payments">
          @for (o of d.overdue; track o.number) { <div class="row-between small"><a [routerLink]="['/sa/companies', o.company_id]">{{ o.company }}</a><span>{{ o.number }} · {{ inr(o.amount) }} · <strong class="c-bad">{{ o.days_late }} d late</strong></span></div> }
          @empty { <span class="muted small">Nothing overdue.</span> }
        </p-card>
        <p-card header="System health">
          <div class="small">Database: <strong [class.c-bad]="d.health.db !== 'ok'">{{ d.health.db }}</strong> · errors in 24 h: {{ d.health.errors_24h }}</div>
          <div class="small">Storage used: {{ (d.health.storage_bytes / 1073741824).toFixed(2) }} GB</div>
          <div class="small">Last backup: @if (d.health.last_backup) { {{ d.health.last_backup | date: 'medium' }} ({{ d.health.backup_status }}) } @else { <span class="c-warn">none recorded</span> }</div>
          <div class="small">{{ d.users }} staff users · {{ d.portal_users }} portal users</div>
        </p-card>
      </div>
    }
  `,
})
export class SaOverviewComponent extends SaBase implements OnInit {
  d = signal<any>(null);
  async ngOnInit() {
    this.d.set(await this.get('/sa/dashboard'));
  }
}

// ---------------------------------------------------------------- companies
@Component({
  selector: 'app-sa-company-list',
  imports: [DatePipe, FormsModule, RouterLink, ButtonModule, CardModule, DialogModule, InputTextModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head"><div><h1>Companies</h1><p class="muted">Search, filter and open a company to manage its plan, trial, modules and support.</p></div>
      @if (canEdit()) { <p-button label="Create a company" icon="pi pi-plus" (onClick)="dlg = true; f = { name: '', owner_email: '', owner_name: '', types: ['contractor'], plan_code: 'basic', city: '' }" /> }</div>
    <div class="row gap wrap mb">
      <input pInputText [(ngModel)]="q" placeholder="Search name" (keyup.enter)="load()" />
      <p-select [options]="statuses" [(ngModel)]="status" [showClear]="true" placeholder="Any status" (onChange)="load()" />
      <p-select [options]="plans()" optionLabel="name" optionValue="code" [(ngModel)]="plan" [showClear]="true" placeholder="Any plan" (onChange)="load()" />
      <input pInputText [(ngModel)]="city" placeholder="City" (keyup.enter)="load()" />
      <input pInputText type="date" [(ngModel)]="from" (change)="load()" title="Signed up from" />
    </div>
    <p-card>
      <p-table [value]="rows()" size="small" [rowHover]="true" [paginator]="rows().length > 25" [rows]="25">
        <ng-template #header><tr><th>Company</th><th>Plan</th><th>Users</th><th>Projects</th><th>Storage</th><th>Status</th><th>Signed up</th></tr></ng-template>
        <ng-template #body let-c><tr>
          <td><a [routerLink]="['/sa/companies', c.id]"><strong>{{ c.name }}</strong></a><br /><small class="muted">{{ c.owner_email }} · {{ c.city }}</small></td>
          <td class="cap">{{ c.plan_code }}</td><td>{{ c.usage.users }} <small class="muted">+{{ c.usage.free_users }}</small></td><td>{{ c.usage.projects }}</td>
          <td><small>{{ (c.usage.storage_bytes / 1048576).toFixed(0) }} MB</small></td>
          <td><p-tag [value]="c.status" [severity]="sev(c.status)" /></td><td><small>{{ c.created_at | date }}</small></td></tr></ng-template>
        <ng-template #emptymessage><tr><td colspan="7" class="muted">No companies match.</td></tr></ng-template>
      </p-table>
    </p-card>
    <p-dialog header="Create a company" [modal]="true" [(visible)]="dlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <label class="field req"><span>Company name</span><input pInputText [(ngModel)]="f.name" fluid /></label>
        <div class="grid2">
          <label class="field req"><span>Owner email</span><input pInputText [(ngModel)]="f.owner_email" fluid /></label>
          <label class="field"><span>Owner name</span><input pInputText [(ngModel)]="f.owner_name" fluid /></label>
          <label class="field"><span>Plan</span><p-select [options]="plans()" optionLabel="name" optionValue="code" [(ngModel)]="f.plan_code" fluid appendTo="body" /></label>
          <label class="field"><span>City</span><input pInputText [(ngModel)]="f.city" fluid /></label>
        </div>
        <label class="field"><span>Type</span><p-select [options]="types" optionLabel="label" optionValue="value" [(ngModel)]="f.types[0]" fluid appendTo="body" /></label>
        @if (temp()) { <p class="small">Temporary owner password: <strong>{{ temp() }}</strong> — share it with the owner; they change it at first sign-in.</p> }
        <div class="row right"><p-button label="Create" [disabled]="!f.name || !f.owner_email" (onClick)="create()" /></div>
      </div>
    </p-dialog>
  `,
})
export class SaCompanyListComponent extends SaBase implements OnInit {
  rows = signal<any[]>([]);
  plans = signal<any[]>([]);
  temp = signal<string | null>(null);
  canEdit = computed(() => this.auth.saCan('companies', 'rw'));
  statuses = ['pending', 'trial', 'active', 'read_only', 'suspended', 'cancelled'];
  types = [{ label: 'Architect', value: 'architect' }, { label: 'Contractor', value: 'contractor' }, { label: 'Interior designer', value: 'interior' }];
  q = ''; status: string | null = null; plan: string | null = null; city = ''; from = '';
  dlg = false;
  f: any = {};

  async ngOnInit() {
    this.plans.set(await this.get('/sa/plans'));
    await this.load();
  }

  async load() {
    const p = new URLSearchParams();
    if (this.q) p.set('q', this.q);
    if (this.status) p.set('status', this.status);
    if (this.plan) p.set('plan_code', this.plan);
    if (this.city) p.set('city', this.city);
    if (this.from) p.set('from', this.from);
    this.rows.set(await this.get(`/sa/companies?${p}`));
  }

  async create() {
    const r: any = await this.send('post', '/sa/companies', this.f, 'Company created');
    if (r) {
      this.temp.set(r.temp_password);
      await this.load();
    }
  }
}

@Component({
  selector: 'app-sa-company',
  imports: [DatePipe, FormsModule, RouterLink, ButtonModule, CardModule, CheckboxModule, InputNumberModule, InputTextModule, SelectModule, TableModule, TagModule],
  template: `
    @if (c(); as c) {
      <div class="page-head"><div><a routerLink="/sa/companies" class="small">← Companies</a><h1>{{ c.name }} <p-tag [value]="c.status" [severity]="sev(c.status)" /></h1>
        <p class="muted">{{ c.owner?.name }} · {{ c.owner_email }} · {{ c.city }} @if (c.gstin) { · GSTIN {{ c.gstin }} } · signed up {{ c.created_at | date }}</p></div></div>
      <div class="grid2 top">
        <p-card header="Plan and usage">
          <div class="small">Plan <strong class="cap">{{ c.plan_code }}</strong> ({{ c.billing_cycle || 'monthly' }}) · pays {{ inr(c.monthly_value) }}/month
            @if (c.trial_ends && c.status === 'trial') { · trial until {{ c.trial_ends | date }} } @if (c.next_renewal) { · renews {{ c.next_renewal | date }} }</div>
          <div class="small">Users {{ c.usage.users }}@if (c.limits.users) { / {{ c.limits.users }} } · projects {{ c.usage.projects }}@if (c.limits.projects) { / {{ c.limits.projects }} }
            · storage {{ (c.usage.storage_bytes / 1073741824).toFixed(2) }} / {{ c.limits.storage_gb }} GB · WhatsApp {{ c.usage.whatsapp_messages }}@if (c.limits.whatsapp) { / {{ c.limits.whatsapp }} }</div>
          <div class="small">Modules: {{ c.modules?.join(', ') }} @if (c.coupon) { · coupon {{ c.coupon.code }} ({{ c.coupon.months_left }} months left) }</div>
          <div class="small">Support access: {{ c.allow_support_login ? 'allowed by the company' : 'not allowed' }} @if (c.export_requested) { · <span class="c-warn">export requested</span> }</div>
        </p-card>
        @if (canEdit()) {
          <p-card header="Actions">
            <div class="row gap wrap">
              @if (c.status === 'pending') { <p-button label="Approve" size="small" (onClick)="act('approve')" /> }
              @if (c.status === 'suspended') { <p-button label="Reactivate" size="small" severity="success" [outlined]="true" (onClick)="act('reactivate')" /> }
              @else if (!c.deleted_at) { <p-button label="Suspend" size="small" severity="danger" [outlined]="true" (onClick)="ask('suspend', 'Why is it suspended?')" /> }
              @if (c.deleted_at) { <p-button label="Restore" size="small" (onClick)="act('restore')" /> } @else { <p-button label="Delete (kept 30 days)" size="small" severity="danger" [text]="true" (onClick)="ask('delete', 'Type DELETE to confirm')" /> }
              <p-button label="Reset owner password" size="small" [text]="true" (onClick)="resetPw()" />
            </div>
            <div class="row gap wrap mt">
              <p-inputnumber [(ngModel)]="days" [min]="1" [max]="90" suffix=" days" [inputStyle]="{ width: '6rem' }" /><p-button label="Extend trial" size="small" [outlined]="true" (onClick)="act('extend_trial', { days })" />
              <p-inputnumber [(ngModel)]="months" [min]="1" [max]="12" suffix=" mo" [inputStyle]="{ width: '5rem' }" /><p-button label="Free months" size="small" [outlined]="true" (onClick)="act('free_months', { months })" />
            </div>
            <div class="row gap wrap mt">
              <p-select [options]="plans()" optionLabel="name" optionValue="code" [(ngModel)]="planCode" placeholder="Plan" /><p-button label="Change plan" size="small" [outlined]="true" [disabled]="!planCode" (onClick)="act('change_plan', { plan_code: planCode })" />
            </div>
            <div class="row gap wrap mt">@for (m of allModules; track m) { <label class="check small"><p-checkbox [(ngModel)]="mods[m]" [binary]="true" [ariaLabel]="m" /> {{ m }}</label> }
              <p-button label="Save modules" size="small" [text]="true" (onClick)="saveModules()" /></div>
            <div class="row gap wrap mt">@for (f of features; track f) { <label class="check small"><p-checkbox [(ngModel)]="flags[f]" [binary]="true" [ariaLabel]="f" /> {{ f.replace('_', ' ') }}</label> }
              <p-button label="Save features" size="small" [text]="true" (onClick)="act('features', { features: flags })" /></div>
            <div class="row gap wrap mt"><p-inputnumber [(ngModel)]="addons.extra_users" [min]="0" prefix="+" suffix=" users" [inputStyle]="{ width: '7rem' }" />
              <p-inputnumber [(ngModel)]="addons.extra_storage_gb" [min]="0" [step]="100" prefix="+" suffix=" GB" [inputStyle]="{ width: '7rem' }" />
              <p-button label="Save add-ons" size="small" [text]="true" (onClick)="act('addons', addons)" /></div>
          </p-card>
        }
      </div>
      <div class="grid2 top mt">
        <p-card header="Payments">
          @for (i of c.invoices; track i.id) { <div class="row-between small"><span>{{ i.number }} · {{ i.created_at | date }}</span><span>{{ inr(i.total) }} <p-tag [value]="i.status" [severity]="sev(i.status)" /></span></div> }
          @empty { <span class="muted small">No invoices yet.</span> }
          @if (auth.saCan('billing', 'rw')) { <p-button label="Issue an invoice now" size="small" [text]="true" (onClick)="invoice()" /> }
        </p-card>
        <p-card header="Notes and support">
          @for (n of c.notes || []; track $index) { <div class="small"><strong>{{ n.by }}</strong> {{ n.at | date: 'short' }}: {{ n.text }}</div> }
          @if (canEdit()) { <div class="row gap mt-xs"><input pInputText [(ngModel)]="note" placeholder="Internal note" class="grow" /><p-button label="Add" size="small" [disabled]="!note.trim()" (onClick)="act('note', { text: note }); note = ''" /></div> }
          @for (t of c.tickets; track t.id) { <div class="small mt-xs">Ticket: {{ t.subject }} <p-tag [value]="t.status" [severity]="sev(t.status)" /></div> }
          @for (s of c.support_sessions; track $index) { <div class="small muted">Support session by {{ s.by }} {{ s.at | date: 'short' }} — {{ s.note }}</div> }
          @if (auth.saCan('support', 'rw')) {
            <div class="row gap wrap mt-xs">
              <input pInputText [(ngModel)]="why" placeholder="Why you need to log in" class="grow" />
              <p-button label="Log in as the company" size="small" [disabled]="!c.allow_support_login || !why.trim()" (onClick)="loginAs()" />
              @if (c.export_requested) { <p-button label="Download the export" size="small" [outlined]="true" (onClick)="exportData()" /> }
            </div>
            @if (supportToken()) { <p class="small">Support session for one hour: <a [href]="'/login?support=' + supportToken()" target="_blank" rel="noopener">open the company's app</a></p> }
          }
        </p-card>
      </div>
    }
  `,
})
export class SaCompanyComponent extends SaBase implements OnInit {
  id = input.required<string>();
  c = signal<any>(null);
  plans = signal<any[]>([]);
  supportToken = signal<string | null>(null);
  canEdit = computed(() => this.auth.saCan('companies', 'rw'));
  allModules = ['architecture', 'construction', 'interior'];
  features = ['whatsapp', 'online_payments', 'procurement', 'portal', 'selections', 'site_reports'];
  mods: Record<string, boolean> = {};
  flags: Record<string, boolean> = {};
  addons: any = {};
  days = 7; months = 1; planCode: string | null = null; note = ''; why = '';

  async ngOnInit() {
    this.plans.set(await this.get('/sa/plans'));
    await this.load();
  }

  async load() {
    const c = await this.get(`/sa/companies/${this.id()}`);
    this.c.set(c);
    this.mods = Object.fromEntries(this.allModules.map((m) => [m, (c.modules ?? []).includes(m)]));
    this.flags = Object.fromEntries(this.features.map((f) => [f, c.feature_flags?.[f] ?? true]));
    this.addons = { extra_users: c.addons?.extra_users ?? 0, extra_storage_gb: c.addons?.extra_storage_gb ?? 0 };
  }

  async act(action: string, extra: any = {}) {
    if (await this.send('post', `/sa/companies/${this.id()}/action`, { action, ...extra }, 'Done')) await this.load();
  }

  async ask(action: string, q: string) {
    const v = prompt(q);
    if (!v) return;
    if (action === 'delete' && v !== 'DELETE') return;
    await this.act(action, { reason: v });
  }

  async saveModules() {
    await this.act('modules', { modules: this.allModules.filter((m) => this.mods[m]) });
  }

  async resetPw() {
    const r: any = await this.send('post', `/sa/companies/${this.id()}/action`, { action: 'reset_owner_password' });
    if (r) alert(`Temporary password for the owner: ${r.temp_password}`);
  }

  async invoice() {
    if (await this.send('post', `/sa/companies/${this.id()}/invoice`, {}, 'Invoice issued')) await this.load();
  }

  async loginAs() {
    const r: any = await this.send('post', `/sa/companies/${this.id()}/login-as`, { reason: this.why }, 'Support session started (logged)');
    if (r) this.supportToken.set(r.token);
  }

  async exportData() {
    const data = await this.get(`/sa/companies/${this.id()}/export`);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' }));
    a.download = `${this.c().name.replace(/\W+/g, '-')}-export.json`;
    a.click();
    await this.load();
  }
}

// ---------------------------------------------------------------- plans and coupons
@Component({
  selector: 'app-sa-plans',
  imports: [FormsModule, ButtonModule, CardModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, TableModule, TagModule],
  template: `
    <div class="page-head"><div><h1>Plans and coupons</h1><p class="muted">A new price applies to new signups; companies keep their price until they renew. Yearly = 10 months.</p></div>
      @if (auth.saCan('plans', 'rw')) { <p-button label="New plan" icon="pi pi-plus" (onClick)="open()" /> }</div>
    <p-card>
      <p-table [value]="plans()" size="small">
        <ng-template #header><tr><th>Plan</th><th class="num">Monthly</th><th class="num">Yearly</th><th class="num">Users</th><th class="num">Projects</th><th class="num">Modules</th><th class="num">WhatsApp</th><th class="num">Storage GB</th><th></th></tr></ng-template>
        <ng-template #body let-p><tr [class.muted]="!p.active"><td><strong>{{ p.name }}</strong> <small class="muted">{{ p.code }}</small></td><td class="num">{{ inr(p.price_monthly) }}</td><td class="num">{{ inr(p.price_yearly) }}</td>
          <td class="num">{{ p.max_users ?? '∞' }}</td><td class="num">{{ p.max_projects ?? '∞' }}</td><td class="num">{{ p.max_modules ?? '∞' }}</td><td class="num">{{ p.whatsapp_messages ?? '∞' }}</td><td class="num">{{ p.storage_gb }}</td>
          <td class="right">@if (auth.saCan('plans', 'rw')) { <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="open(p)" ariaLabel="Edit plan" /> }</td></tr></ng-template>
      </p-table>
    </p-card>
    @if (auth.saCan('coupons')) {
      <p-card header="Coupons" styleClass="mt">
        @if (auth.saCan('coupons', 'rw')) {
          <div class="row gap wrap mb"><input pInputText [(ngModel)]="cf.code" placeholder="CODE" style="width: 8rem" /><p-inputnumber [(ngModel)]="cf.percent" suffix="% off" [min]="1" [max]="100" [inputStyle]="{ width: '7rem' }" />
            <p-inputnumber [(ngModel)]="cf.months" suffix=" months" [min]="1" [inputStyle]="{ width: '7rem' }" /><p-inputnumber [(ngModel)]="cf.max_uses" placeholder="uses" [min]="0" [inputStyle]="{ width: '5rem' }" />
            <input pInputText type="date" [(ngModel)]="cf.expires" /><p-button label="Add coupon" size="small" [disabled]="!cf.code || !cf.percent" (onClick)="addCoupon()" /></div>
        }
        @for (c of coupons(); track c.id) { <div class="row-between small"><span><strong>{{ c.code }}</strong> {{ c.percent }}% for {{ c.months }} month(s) · used {{ c.used || 0 }}@if (c.max_uses) { / {{ c.max_uses }} } @if (c.expires) { · until {{ c.expires }} }</span>
          <label class="check small"><p-checkbox [ngModel]="c.active" (ngModelChange)="toggle(c, $event)" [binary]="true" [disabled]="!auth.saCan('coupons', 'rw')" ariaLabel="Active" /> active</label></div> }
      </p-card>
    }
    <p-dialog [header]="f.id ? 'Edit plan' : 'New plan'" [modal]="true" [(visible)]="dlg" [style]="{ width: '34rem' }">
      <div class="stack">
        <div class="grid2">
          <label class="field req"><span>Code</span><input pInputText [(ngModel)]="f.code" [disabled]="!!f.id" fluid /></label>
          <label class="field req"><span>Name</span><input pInputText [(ngModel)]="f.name" fluid /></label>
          <label class="field req"><span>Monthly price (before GST)</span><p-inputnumber [(ngModel)]="f.price_monthly" [min]="0" fluid /></label>
          <label class="field"><span>Users</span><p-inputnumber [(ngModel)]="f.max_users" [min]="0" fluid placeholder="unlimited" /></label>
          <label class="field"><span>Active projects</span><p-inputnumber [(ngModel)]="f.max_projects" [min]="0" fluid placeholder="unlimited" /></label>
          <label class="field"><span>Modules</span><p-inputnumber [(ngModel)]="f.max_modules" [min]="1" [max]="3" fluid placeholder="all" /></label>
          <label class="field"><span>WhatsApp / month</span><p-inputnumber [(ngModel)]="f.whatsapp_messages" [min]="0" fluid placeholder="unlimited" /></label>
          <label class="field"><span>Storage GB</span><p-inputnumber [(ngModel)]="f.storage_gb" [min]="0" fluid /></label>
        </div>
        <label class="field"><span>Support</span><input pInputText [(ngModel)]="f.support" fluid /></label>
        <label class="check"><p-checkbox [(ngModel)]="f.active" [binary]="true" ariaLabel="Offered" /> Offered to new companies</label>
        <div class="row right"><p-button label="Save" (onClick)="save()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.num { text-align: right; }`,
})
export class SaPlansComponent extends SaBase implements OnInit {
  plans = signal<any[]>([]);
  coupons = signal<any[]>([]);
  dlg = false;
  f: any = {};
  cf: any = { months: 1 };

  async ngOnInit() {
    this.plans.set(await this.get('/sa/plans'));
    if (this.auth.saCan('coupons')) this.coupons.set(await this.get('/sa/coupons'));
  }

  open(p?: any) {
    this.f = p ? { ...p } : { code: '', name: '', price_monthly: null, active: true };
    this.dlg = true;
  }

  async save() {
    const { id, _id, created_at, price_yearly, price_monthly_gst, ...body } = this.f;
    if (await this.send(id ? 'put' : 'post', id ? `/sa/plans/${id}` : '/sa/plans', body, 'Plan saved')) {
      this.dlg = false;
      await this.ngOnInit();
    }
  }

  async addCoupon() {
    if (await this.send('post', '/sa/coupons', this.cf, 'Coupon added')) {
      this.cf = { months: 1 };
      await this.ngOnInit();
    }
  }

  async toggle(c: any, active: boolean) {
    await this.send('put', `/sa/coupons/${c.id}`, { active });
    await this.ngOnInit();
  }
}

// ---------------------------------------------------------------- billing
@Component({
  selector: 'app-sa-billing',
  imports: [DatePipe, FormsModule, RouterLink, ButtonModule, CardModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head"><div><h1>Billing</h1><p class="muted">GST invoices for subscriptions. The daily run issues invoices when trials end and plans renew, reminds, and makes a company read-only 7 days after the due date.</p></div>
      <p-button label="Run billing now" icon="pi pi-refresh" [outlined]="true" (onClick)="run()" /></div>
    <div class="row gap mb"><p-select [options]="statuses" [(ngModel)]="status" [showClear]="true" placeholder="Any status" (onChange)="load()" /></div>
    <p-card>
      <p-table [value]="rows()" size="small" [paginator]="rows().length > 25" [rows]="25">
        <ng-template #header><tr><th>Number</th><th>Company</th><th>Date</th><th class="num">Taxable</th><th class="num">GST</th><th class="num">Total</th><th>Status</th><th></th></tr></ng-template>
        <ng-template #body let-i><tr><td>{{ i.number }}@if (i.against) { <div class="small muted">against {{ i.against }}</div> }</td>
          <td><a [routerLink]="['/sa/companies', i.company_id]">{{ i.company_name }}</a></td><td>{{ i.created_at | date }}</td>
          <td class="num">{{ inr(i.subtotal) }}</td><td class="num">{{ inr(i.gst) }}</td><td class="num">{{ inr(i.total) }}</td>
          <td><p-tag [value]="i.status" [severity]="sev(i.status)" /></td>
          <td class="right nowrap">@if (i.status === 'due' || i.status === 'overdue') { <p-button label="Mark paid" size="small" [text]="true" (onClick)="paid(i)" /><p-button label="Void" size="small" [text]="true" severity="secondary" (onClick)="act(i, 'void')" /> }
            @if (i.status === 'paid') { <p-button label="Refund" size="small" [text]="true" severity="secondary" (onClick)="refund(i)" /> }</td></tr></ng-template>
      </p-table>
    </p-card>
    <p-card header="GST collected by month" styleClass="mt">
      @for (g of gst(); track g.month) { <div class="row-between small"><span>{{ g.month }} · {{ g.count }} document(s)</span><span>taxable {{ inr(g.taxable) }} · GST {{ inr(g.gst) }} (CGST {{ inr(g.cgst) }}, SGST {{ inr(g.sgst) }}, IGST {{ inr(g.igst) }})</span></div> }
      @empty { <span class="muted small">Nothing collected yet.</span> }
    </p-card>
  `,
  styles: `.num { text-align: right; } .nowrap { white-space: nowrap; }`,
})
export class SaBillingComponent extends SaBase implements OnInit {
  rows = signal<any[]>([]);
  gst = signal<any[]>([]);
  statuses = ['due', 'overdue', 'paid', 'void', 'refunded'];
  status: string | null = null;

  async ngOnInit() {
    await this.load();
    this.gst.set(await this.get('/sa/reports/gst'));
  }

  async load() {
    this.rows.set(await this.get(`/sa/invoices${this.status ? '?status=' + this.status : ''}`));
  }

  async run() {
    const r: any = await this.send('post', '/sa/billing/run', {});
    if (r) this.toast.add({ severity: 'success', summary: `${r.issued} invoice(s), ${r.reminders} reminder(s), ${r.read_only} read-only, ${r.purged} purged` });
    await this.load();
  }

  async act(i: any, action: string, extra: any = {}) {
    if (await this.send('post', `/sa/invoices/${i.id}/action`, { action, ...extra }, 'Done')) await this.ngOnInit();
  }

  async paid(i: any) {
    const ref = prompt('Bank transfer / cheque reference');
    if (ref !== null) await this.act(i, 'mark_paid', { method: 'bank_transfer', ref });
  }

  async refund(i: any) {
    const amount = Number(prompt('Refund amount (including GST)', String(i.total)));
    const reason = amount ? prompt('Why?') : null;
    if (amount && reason) await this.act(i, 'refund', { amount, reason });
  }
}

// ---------------------------------------------------------------- support tickets, announcements
@Component({
  selector: 'app-sa-support',
  imports: [DatePipe, FormsModule, RouterLink, ButtonModule, CardModule, CheckboxModule, InputTextModule, SelectModule, TagModule, TextareaModule],
  template: `
    <div class="page-head"><div><h1>Support and announcements</h1></div></div>
    @if (auth.saCan('support')) {
      <p-card header="Tickets">
        @for (t of tickets(); track t.id) {
          <div class="ticket">
            <div class="row-between"><strong>{{ t.subject }}</strong><span><a [routerLink]="['/sa/companies', t.company_id]" class="small">{{ t.company_name }}</a> <p-tag [value]="t.status" [severity]="sev(t.status)" /></span></div>
            @for (r of t.replies; track $index) { <div class="small" [class.muted]="r.side === 'support'"><strong>{{ r.by }}</strong> {{ r.at | date: 'short' }}: {{ r.text }}</div> }
            @if (auth.saCan('support', 'rw')) { <div class="row gap mt-xs"><input pInputText [(ngModel)]="drafts[t.id]" placeholder="Reply" class="grow" />
              <p-button label="Send" size="small" (onClick)="reply(t)" [disabled]="!drafts[t.id]?.trim()" /><p-button label="Close" size="small" [text]="true" (onClick)="reply(t, 'closed')" /></div> }
          </div>
        } @empty { <span class="muted small">No tickets.</span> }
      </p-card>
    }
    <p-card header="Announcements" styleClass="mt">
      @if (auth.saCan('announcements', 'rw')) {
        <div class="stack mb">
          <input pInputText [(ngModel)]="a.title" placeholder="Title" />
          <textarea pTextarea rows="3" [(ngModel)]="a.body" placeholder="Message"></textarea>
          <div class="row gap wrap"><p-select [options]="kinds" [(ngModel)]="a.kind" /><input pInputText [(ngModel)]="a.plans" placeholder="Only plans (codes, comma separated)" class="grow" />
            <label class="check small"><p-checkbox [(ngModel)]="a.email" [binary]="true" ariaLabel="Email owners" /> email the owners</label>
            <p-button label="Publish" size="small" [disabled]="!a.title?.trim()" (onClick)="publish()" /></div>
        </div>
      }
      @for (x of anns(); track x.id) { <div class="row-between small"><span><strong>{{ x.title }}</strong> · {{ x.kind }} · {{ x.created_at | date }}@if (x.audience?.plans?.length) { · plans {{ x.audience.plans.join(', ') }} }@if (x.emailed) { · emailed {{ x.emailed }} }</span>
        @if (auth.saCan('announcements', 'rw')) { <label class="check small"><p-checkbox [ngModel]="x.active" (ngModelChange)="toggle(x, $event)" [binary]="true" ariaLabel="Shown" /> shown</label> }</div> }
    </p-card>
  `,
  styles: `.ticket { border-bottom: 1px solid var(--border); padding: .5rem 0; }`,
})
export class SaSupportComponent extends SaBase implements OnInit {
  tickets = signal<any[]>([]);
  anns = signal<any[]>([]);
  drafts: Record<string, string> = {};
  kinds = ['feature', 'maintenance', 'billing'];
  a: any = { kind: 'feature', email: false };

  async ngOnInit() {
    if (this.auth.saCan('support')) this.tickets.set(await this.get('/sa/tickets'));
    this.anns.set(await this.get('/sa/announcements'));
  }

  async reply(t: any, status?: string) {
    if (await this.send('post', `/sa/tickets/${t.id}/reply`, { text: this.drafts[t.id] ?? '', ...(status ? { status } : { status: 'waiting' }) }, 'Sent')) {
      this.drafts[t.id] = '';
      await this.ngOnInit();
    }
  }

  async publish() {
    const plans = (this.a.plans ?? '').split(',').map((x: string) => x.trim()).filter(Boolean);
    if (await this.send('post', '/sa/announcements', { ...this.a, audience: { plans } }, 'Published')) {
      this.a = { kind: 'feature', email: false };
      await this.ngOnInit();
    }
  }

  async toggle(x: any, active: boolean) {
    await this.send('put', `/sa/announcements/${x.id}`, { active });
    await this.ngOnInit();
  }
}

// ---------------------------------------------------------------- reports, usage, platform settings
@Component({
  selector: 'app-sa-reports',
  imports: [RouterLink, CardModule, TableModule, DecimalPipe],
  template: `
    <div class="page-head"><div><h1>Reports and usage</h1></div></div>
    @if (r(); as r) {
      <div class="grid2 top">
        <p-card header="Revenue by plan">@for (k of keys(r.by_plan); track k) { <div class="row-between small"><span class="cap">{{ k }}</span><strong>{{ inr(r.by_plan[k]) }}</strong></div> } @empty { <span class="muted small">No revenue yet.</span> }</p-card>
        <p-card header="Revenue by month">@for (k of keys(r.by_month); track k) { <div class="row-between small"><span>{{ k }}</span><strong>{{ inr(r.by_month[k]) }}</strong></div> } @empty { <span class="muted small">No revenue yet.</span> }</p-card>
        <p-card header="Revenue by city">@for (k of keys(r.by_city); track k) { <div class="row-between small"><span>{{ k }}</span><strong>{{ inr(r.by_city[k]) }}</strong></div> } @empty { <span class="muted small">—</span> }</p-card>
        <p-card header="Trials and churn">
          <div class="small">Trial → paid: <strong>{{ r.trial_conversion ?? '—' }}{{ r.trial_conversion !== null ? '%' : '' }}</strong></div>
          @for (c of r.churn; track $index) { <div class="small">{{ c.company }}: {{ c.reason || 'no reason given' }}</div> } @empty { <div class="small muted">No cancellations.</div> }
        </p-card>
        <p-card header="Most used features">@for (f of r.feature_usage; track f.feature) { <div class="row-between small"><span>{{ f.feature }}</span><span>{{ f.records | number }} records · {{ f.companies }} companies</span></div> }</p-card>
        <p-card header="Least used">@for (f of r.least_used; track f.feature) { <div class="row-between small"><span>{{ f.feature }}</span><span>{{ f.records | number }} · {{ f.companies }} companies</span></div> }</p-card>
      </div>
    }
    <p-card header="Usage against plans" styleClass="mt">
      <p-table [value]="usage()" size="small">
        <ng-template #header><tr><th>Company</th><th>Plan</th><th>Users</th><th>Projects</th><th>WhatsApp (cost)</th><th>Pays / month</th><th>Near a limit</th></tr></ng-template>
        <ng-template #body let-u><tr><td><a [routerLink]="['/sa/companies', u.id]">{{ u.name }}</a></td><td>{{ u.plan }}</td><td>{{ u.usage.users }}@if (u.limits.users) { / {{ u.limits.users }} }</td>
          <td>{{ u.usage.projects }}@if (u.limits.projects) { / {{ u.limits.projects }} }</td><td>{{ u.usage.whatsapp_messages }} ({{ inr(u.whatsapp_cost) }})</td><td>{{ inr(u.pays_monthly) }}</td>
          <td class="c-warn small">@for (n of u.near_limit; track n.what) { {{ n.what }} {{ n.used }}/{{ n.limit }} }</td></tr></ng-template>
      </p-table>
    </p-card>
  `,
})
export class SaReportsComponent extends SaBase implements OnInit {
  r = signal<any>(null);
  usage = signal<any[]>([]);
  keys = (o: any) => Object.keys(o ?? {});

  async ngOnInit() {
    if (this.auth.saCan('reports')) this.r.set(await this.get('/sa/reports/overview'));
    this.usage.set(await this.get('/sa/usage'));
  }
}

@Component({
  selector: 'app-sa-settings',
  imports: [DatePipe, FormsModule, ButtonModule, CardModule, CheckboxModule, InputTextModule, TextareaModule],
  template: `
    <div class="page-head"><div><h1>Platform settings</h1><p class="muted">Keys are never shown again once saved; leave the masked value to keep them.</p></div></div>
    <div class="grid2 top">
      <p-card header="Branding and sign-up">
        <div class="stack">
          <label class="field"><span>Platform name</span><input pInputText [(ngModel)]="s.platform_name" fluid /></label>
          <label class="field"><span>Logo link</span><input pInputText [(ngModel)]="s.logo_url" fluid /></label>
          <label class="field"><span>Login page message</span><input pInputText [(ngModel)]="s.login_message" fluid /></label>
          <label class="check"><p-checkbox [(ngModel)]="s.signup_needs_approval" [binary]="true" ariaLabel="Approve signups" /> New companies wait for approval</label>
        </div>
      </p-card>
      <p-card header="Providers">
        <div class="stack">
          <div class="grid2"><label class="field"><span>Payment gateway</span><input pInputText [(ngModel)]="s.gateway" placeholder="sandbox / razorpay / stripe" fluid /></label>
            <label class="field"><span>Gateway key</span><input pInputText [(ngModel)]="s.gateway_key" fluid /></label></div>
          <label class="field"><span>Gateway secret</span><input pInputText [(ngModel)]="s.gateway_secret" fluid /></label>
          <div class="grid2"><label class="field"><span>WhatsApp phone id</span><input pInputText [(ngModel)]="s.whatsapp_phone_id" fluid /></label>
            <label class="field"><span>WhatsApp token</span><input pInputText [(ngModel)]="s.whatsapp_token" fluid /></label></div>
          <div class="grid2"><label class="field"><span>SMTP host</span><input pInputText [(ngModel)]="s.smtp_host" fluid /></label>
            <label class="field"><span>SMTP user</span><input pInputText [(ngModel)]="s.smtp_user" fluid /></label>
            <label class="field"><span>SMTP password</span><input pInputText [(ngModel)]="s.smtp_password" fluid /></label>
            <label class="field"><span>From email</span><input pInputText [(ngModel)]="s.smtp_from" fluid /></label></div>
          <div class="grid2"><label class="field"><span>SMS provider</span><input pInputText [(ngModel)]="s.sms_provider" fluid /></label>
            <label class="field"><span>SMS key</span><input pInputText [(ngModel)]="s.sms_key" fluid /></label></div>
        </div>
      </p-card>
    </div>
    <p-card header="Terms and privacy" styleClass="mt">
      <div class="grid2"><label class="field"><span>Terms of service</span><textarea pTextarea rows="8" [(ngModel)]="s.terms"></textarea></label>
        <label class="field"><span>Privacy policy</span><textarea pTextarea rows="8" [(ngModel)]="s.privacy"></textarea></label></div>
    </p-card>
    @if (auth.saCan('settings', 'rw')) { <div class="row right mt"><p-button label="Save" icon="pi pi-check" (onClick)="save()" /></div> }
    @if (bk(); as b) {
      <p-card header="Backups" styleClass="mt">
        <div class="row-between small mb-xs"><span>Daily at {{ b.hour }}:00, the last {{ b.keep }} kept. Last: @if (b.status?.last_ok) { {{ b.status.last_ok | date: 'medium' }} ({{ b.status.status }}) } @else { none }
          @if (b.status?.status === 'failed') { <span class="c-bad">— {{ b.status.error }}</span> }</span>
          @if (auth.saCan('settings', 'rw')) { <p-button label="Back up now" size="small" [outlined]="true" [loading]="busy" (onClick)="backup()" /> }</div>
        @for (x of b.backups; track x.name) { <div class="row-between small"><span>{{ x.name }}</span><span>{{ x.collections }} collections · {{ (x.size / 1048576).toFixed(1) }} MB</span></div> }
        @empty { <span class="muted small">No backups yet.</span> }
        <p class="small muted m0 mt-xs">Restore from the server: <code>docker compose exec backup python -m app.backup restore &lt;folder&gt; --yes</code></p>
      </p-card>
    }
  `,
})
export class SaSettingsComponent extends SaBase implements OnInit {
  s: any = {};
  bk = signal<any>(null);
  busy = false;

  async ngOnInit() {
    this.s = await this.get('/sa/settings');
    if (this.auth.saCan('settings')) this.bk.set(await this.get('/sa/backups').catch(() => null));
  }

  async backup() {
    this.busy = true;
    await this.send('post', '/sa/backups/run', {}, 'Backup done');
    this.busy = false;
    this.bk.set(await this.get('/sa/backups'));
  }

  async save() {
    const r = await this.send('put', '/sa/settings', this.s, 'Saved');
    if (r) this.s = r;
  }
}
