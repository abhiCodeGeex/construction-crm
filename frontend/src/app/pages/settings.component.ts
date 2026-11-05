import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { TextareaModule } from 'primeng/textarea';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { Api, SERVICE_LABEL } from '../core/api.service';
import { SalesSettingsComponent } from './sales-settings.component';
import { ProposalSettingsComponent } from './proposal-settings.component';
import { AuthService } from '../core/auth.service';

@Component({
  selector: 'app-settings',
  imports: [FormsModule, DatePipe, ButtonModule, CardModule, CheckboxModule, TextareaModule, DialogModule, InputNumberModule, InputTextModule, MessageModule, SelectButtonModule,
    SelectModule, TableModule, TabsModule, TagModule, ToggleSwitchModule, SalesSettingsComponent, ProposalSettingsComponent],
  template: `
    <div class="page-head"><div><h1>Company settings</h1><p class="muted">Company setup, stage templates, role permissions and the audit log.</p></div></div>
    @if (!canEdit()) { <p-message severity="info" icon="pi pi-eye" text="Read-only: only the owner can change company settings." styleClass="mb" /> }

    <p-tabs value="company" [scrollable]="true">
      <p-tablist>
        <p-tab value="company"><i class="pi pi-building mr"></i>Company</p-tab>
        <p-tab value="setup"><i class="pi pi-sitemap mr"></i>Branches, tax & numbering</p-tab>
        <p-tab value="templates"><i class="pi pi-list mr"></i>Stage templates</p-tab>
        <p-tab value="sales"><i class="pi pi-bullseye mr"></i>Sales & templates</p-tab>
        <p-tab value="proposals"><i class="pi pi-file-edit mr"></i>Proposals & branding</p-tab>
        <p-tab value="roles"><i class="pi pi-shield mr"></i>Roles & permissions</p-tab>
        <p-tab value="audit"><i class="pi pi-history mr"></i>Audit log</p-tab>
      </p-tablist>
      <p-tabpanels>
        <!-- company -->
        <p-tabpanel value="company">
          @if (c(); as c) {
            <div class="grid2 top">
              <p-card><ng-template #title>Profile</ng-template>
                <div class="stack">
                  <label class="field"><span>Company name</span><input pInputText [(ngModel)]="c.name" [disabled]="!canEdit()" fluid /></label>
                  <div class="grid2">
                    <label class="field"><span>City</span><input pInputText [(ngModel)]="c.city" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>GSTIN</span><input pInputText [(ngModel)]="c.gstin" [disabled]="!canEdit()" fluid /></label>
                  </div>
                  <label class="check"><p-toggleswitch [(ngModel)]="c.allow_support_login" [disabled]="!canEdit()" /> Allow BuildSuite support to sign in to help (always logged)</label>
                </div>
              </p-card>
              <p-card><ng-template #title>Modules</ng-template>
                <p class="muted small">Your {{ auth.session()?.limits?.plan }} plan includes {{ auth.session()?.limits?.modules }} module(s). Projects can only use enabled modules.</p>
                <p-selectbutton [options]="modules" [(ngModel)]="c.modules" [multiple]="true" optionLabel="label" optionValue="value" [disabled]="!canEdit()" />
              </p-card>
            </div>
            @if (canEdit()) { <div class="row right mt"><p-button label="Save" icon="pi pi-check" (onClick)="saveCompany()" /></div> }
          }
        </p-tabpanel>

        <!-- setup -->
        <p-tabpanel value="setup">
          @if (c(); as c) {
            <div class="grid2 top">
              <p-card><ng-template #title>Branches / offices</ng-template>
                <p-table [value]="setup.branches" size="small">
                  <ng-template #header><tr><th>Name</th><th>City</th><th>GSTIN</th><th></th></tr></ng-template>
                  <ng-template #body let-b let-i="rowIndex">
                    <tr><td><input pInputText [(ngModel)]="b.name" [disabled]="!canEdit()" /></td><td><input pInputText [(ngModel)]="b.city" [disabled]="!canEdit()" /></td>
                      <td><input pInputText [(ngModel)]="b.gstin" [disabled]="!canEdit()" /></td>
                      <td>@if (canEdit()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="setup.branches.splice(i, 1)" /> }</td></tr>
                  </ng-template>
                </p-table>
                @if (canEdit()) { <p-button label="Add branch" icon="pi pi-plus" size="small" [text]="true" (onClick)="setup.branches.push({ name: '', city: '' })" /> }
              </p-card>
              <p-card><ng-template #title>Currency, tax & numbering</ng-template>
                <div class="stack">
                  <div class="grid3">
                    <label class="field"><span>Currency</span><p-select [options]="currencies" [(ngModel)]="setup.currency" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Tax label</span><input pInputText [(ngModel)]="setup.tax_label" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Tax rate %</span><p-inputnumber [(ngModel)]="setup.tax_rate" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!canEdit()" fluid /></label>
                  </div>
                  <label class="field"><span>Project number format</span>
                    <input pInputText [(ngModel)]="setup.prj" (ngModelChange)="preview()" [disabled]="!canEdit()" fluid />
                    <small class="muted">Use <code>{{ '{' }}n{{ '}' }}</code> (or <code>{{ '{' }}n:04d{{ '}' }}</code> for padding) and optional <code>{{ '{' }}year{{ '}' }}</code>. Next number: <strong>{{ nextNo() }}</strong></small></label>
                </div>
              </p-card>
              <p-card><ng-template #title>Working days & holidays</ng-template>
                <div class="stack">
                  <small class="muted">Used for task lags, moving dependent tasks, delay days and the finish forecast — a Sunday or a holiday never counts as a day of work.</small>
                  <div class="row gap wrap">
                    @for (d of cal.weekdays; track $index; let i = $index) {
                      <label class="check"><p-checkbox [binary]="true" [ngModel]="cal.working_days.includes(i)" (onChange)="toggleDay(i, $event.checked)" [disabled]="!canEdit()" /> {{ d }}</label>
                    }
                  </div>
                  @for (h of cal.holidays; track $index; let i = $index) {
                    <div class="row gap"><input pInputText type="date" [(ngModel)]="h.date" [disabled]="!canEdit()" />
                      <input pInputText [(ngModel)]="h.name" placeholder="Holiday name" class="grow" [disabled]="!canEdit()" />
                      @if (canEdit()) { <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="cal.holidays.splice(i, 1)" /> }</div>
                  }
                  @if (canEdit()) {
                    <div class="row-between"><p-button label="Add holiday" icon="pi pi-plus" size="small" [text]="true" (onClick)="cal.holidays.push({ date: '', name: '' })" />
                      <p-button label="Save calendar" icon="pi pi-check" size="small" (onClick)="saveCalendar()" /></div>
                  }
                </div>
              </p-card>
            </div>
            @if (canEdit()) { <div class="row right mt"><p-button label="Save setup" icon="pi pi-check" (onClick)="saveSetup()" /></div> }
          }
        </p-tabpanel>

        <!-- templates -->
        <p-tabpanel value="templates">
          <div class="row-between mb">
            <span class="muted">New projects use the default template of each service. Durations set the default stage length.</span>
            @if (canEdit()) {
              <div class="row gap">
                @for (pr of presets(); track pr.key) { <p-button [label]="'Add ' + pr.name" icon="pi pi-plus" size="small" [outlined]="true" [disabled]="hasTemplate(pr.name)" (onClick)="addPreset(pr.key)" /> }
                <p-button label="New template" icon="pi pi-plus" size="small" (onClick)="editTemplate()" />
              </div>
            }
          </div>
          <div class="tpl-grid">
            @for (t of templates(); track t.id) {
              <p-card>
                <ng-template #title><div class="row-between"><span>{{ t.name }}</span>
                  @if (t.is_default) { <p-tag value="Default" severity="success" /> }</div></ng-template>
                <ng-template #subtitle>{{ svc[t.service] }} · {{ t.stages.length }} stages · {{ total(t) }} days</ng-template>
                <ol class="tpl-stages">@for (s of t.stages; track s.name) { <li>{{ s.name }} <small class="muted">{{ s.duration_days }} d{{ s.checklist?.length ? ' · ' + s.checklist.length + ' closing checks' : '' }}{{ s.client_signoff ? ' · client sign-off' : '' }}</small></li> }</ol>
                @if (canEdit()) {
                  <div class="row gap">
                    <p-button label="Edit" icon="pi pi-pencil" size="small" [text]="true" (onClick)="editTemplate(t)" />
                    @if (!t.is_default) {
                      <p-button label="Make default" icon="pi pi-star" size="small" [text]="true" (onClick)="makeDefault(t)" />
                      <p-button label="Delete" icon="pi pi-trash" size="small" severity="danger" [text]="true" (onClick)="deleteTemplate(t)" />
                    }
                  </div>
                }
              </p-card>
            }
          </div>
        </p-tabpanel>

        <p-tabpanel value="sales"><app-sales-settings /></p-tabpanel>
        <p-tabpanel value="proposals"><app-proposal-settings /></p-tabpanel>

        <!-- roles -->
        <p-tabpanel value="roles">
          <p class="muted">Adjust what each staff role can do. Defaults come from the product; your changes are stored separately and can be reset. The Owner always has full access.</p>
          @if (roles(); as r) {
            <div class="scroll-x">
              <p-table [value]="r.roles" size="small" styleClass="matrix">
                <ng-template #header><tr><th>Role</th>@for (a of r.areas; track a) { <th class="center cap">{{ a.replace('_', ' ') }}</th> }<th></th></tr></ng-template>
                <ng-template #body let-row>
                  <tr>
                    <td><strong>{{ row.label }}</strong> @if (hasOverrides(row)) { <p-tag value="custom" severity="warn" /> }</td>
                    @for (a of r.areas; track a) {
                      <td class="center">
                        @if (row.locked || !canEdit()) {
                          <span [class]="cellClass(row.effective[a])">{{ cell(row.effective[a]) }}</span>
                        } @else {
                          <button class="perm" [class]="cellClass(row.draft[a])" [class.changed]="(row.draft[a] || '') !== (row.defaults[a] || '')"
                                  (click)="cycle(row, a)" [title]="'Click to change · default: ' + cell(row.defaults[a])">{{ cell(row.draft[a]) }}</button>
                        }
                      </td>
                    }
                    <td class="nowrap">@if (!row.locked && canEdit()) {
                      <p-button label="Save" size="small" [text]="true" [disabled]="!dirty(row)" (onClick)="saveRole(row)" />
                      <p-button label="Reset" size="small" [text]="true" severity="secondary" [disabled]="!hasOverrides(row)" (onClick)="resetRole(row)" /> }</td>
                  </tr>
                </ng-template>
              </p-table>
            </div>
            <p class="muted small">✏️ read + write · 👁 read · — none. Changed cells are outlined. Changes apply to users on their next request.</p>
          }
        </p-tabpanel>

        <!-- audit -->
        <p-tabpanel value="audit">
          <p-table [value]="audit()" size="small" [paginator]="true" [rows]="15">
            <ng-template #header><tr><th>When</th><th>Who</th><th>Action</th><th>What</th><th>Changes</th></tr></ng-template>
            <ng-template #body let-a>
              <tr><td class="nowrap"><small>{{ a.at | date: 'short' }}</small></td><td>{{ a.user_name || '—' }}</td><td class="cap">{{ a.action }}</td>
                <td>{{ a.collection }} @if (a.note) { <small class="muted">· {{ a.note }}</small> }</td><td><small class="muted">{{ changed(a) }}</small></td></tr>
            </ng-template>
          </p-table>
        </p-tabpanel>
      </p-tabpanels>
    </p-tabs>

    <p-dialog [header]="tf.id ? 'Edit template' : 'New template'" [modal]="true" [(visible)]="tplDlg" [style]="{ width: '36rem' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Name</span><input pInputText [(ngModel)]="tf.name" fluid /></label>
          <label class="field"><span>Service</span><p-select [options]="modules" [(ngModel)]="tf.service" optionLabel="label" optionValue="value" fluid appendTo="body" /></label>
        </div>
        <p-table [value]="tf.stages" size="small">
          <ng-template #header><tr><th>#</th><th>Stage <small class="muted">· closing checklist, one per line</small></th><th>Days</th><th></th></tr></ng-template>
          <ng-template #body let-s let-i="rowIndex">
            <tr><td>{{ i + 1 }}</td><td><input pInputText [(ngModel)]="s.name" fluid />
              <textarea pTextarea rows="2" [ngModel]="(s.checklist ?? []).join('\n')" (ngModelChange)="s.checklist = splitLines($event)" placeholder="Checks before this stage can close" class="mt-xs" fluid></textarea>
              <label class="check small"><p-checkbox [binary]="true" [(ngModel)]="s.client_signoff" /> Needs the client's sign-off</label></td>
              <td><p-inputnumber [(ngModel)]="s.duration_days" [min]="1" [max]="3650" [showButtons]="false" inputStyleClass="w-5" /></td>
              <td class="nowrap"><p-button icon="pi pi-arrow-up" [text]="true" size="small" [disabled]="i === 0" (onClick)="swap(i, i - 1)" />
                <p-button icon="pi pi-arrow-down" [text]="true" size="small" [disabled]="i === tf.stages.length - 1" (onClick)="swap(i, i + 1)" />
                <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="tf.stages.splice(i, 1)" /></td></tr>
          </ng-template>
        </p-table>
        <p-button label="Add stage" icon="pi pi-plus" size="small" [text]="true" (onClick)="tf.stages.push({ name: '', duration_days: 14, checklist: [], client_signoff: false })" />
        <label class="check"><p-toggleswitch [(ngModel)]="tf.is_default" /> Default for this service</label>
        <div class="row gap right"><p-button label="Save template" icon="pi pi-check" (onClick)="saveTemplate()" /></div>
      </div>
    </p-dialog>
  `,
})
export class SettingsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  c = signal<any>(null);
  audit = signal<any[]>([]);
  templates = signal<any[]>([]);
  presets = signal<any[]>([]);
  roles = signal<any>(null);
  nextNo = signal('');
  canEdit = computed(() => this.auth.can('settings', 'rw'));
  svc = SERVICE_LABEL;
  modules = Object.entries(SERVICE_LABEL).map(([value, label]) => ({ value, label }));
  currencies = ['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD', 'AUD'];
  setup: any = { branches: [] };
  cal: any = { weekdays: [], working_days: [], holidays: [] };
  tplDlg = false;
  tf: any = { stages: [] };

  async ngOnInit() {
    await Promise.all([this.loadCompany(), this.loadTemplates(), this.loadRoles(), this.loadAudit(), this.loadCalendar()]);
  }

  async loadCalendar() {
    const c = await this.api.get('/settings/calendar');
    this.cal = { weekdays: c.weekdays, working_days: [...c.working_days], holidays: c.holidays.map((h: any) => ({ ...h })) };
  }

  toggleDay(i: number, on: boolean) {
    this.cal.working_days = on ? [...new Set([...this.cal.working_days, i])].sort() : this.cal.working_days.filter((d: number) => d !== i);
  }

  async saveCalendar() {
    await this.api.put('/settings/calendar', { working_days: this.cal.working_days, holidays: this.cal.holidays.filter((h: any) => h.date || h.name) },
      'Working days saved');
    await this.loadCalendar();
  }

  splitLines(v: string) {
    return v.split('\n').map((x) => x.trim()).filter(Boolean);
  }

  async loadCompany() {
    const c = await this.api.get('/company');
    this.c.set(c);
    this.setup = { branches: (c.branches ?? []).map((b: any) => ({ ...b })), currency: c.currency ?? 'INR', tax_label: c.tax_label ?? 'GST',
      tax_rate: c.tax_rate ?? 18, prj: c.numbering?.PRJ ?? 'PRJ-{n:04d}' };
    this.preview();
  }

  async loadTemplates() {
    const r = await this.api.get('/stage_templates');
    this.templates.set(r.templates);
    this.presets.set(r.presets);
  }

  async loadRoles() {
    const r = await this.api.get('/roles');
    r.roles.forEach((row: any) => (row.draft = { ...row.effective }));
    this.roles.set(r);
  }

  async loadAudit() {
    this.audit.set(await this.api.get('/audit'));
  }

  changed(a: any) {
    return a.changes ? Object.keys(a.changes).filter((k) => k !== 'password').join(', ') : '';
  }

  async saveCompany() {
    const c = this.c();
    await this.api.put('/company', { name: c.name, city: c.city, gstin: c.gstin, modules: c.modules, allow_support_login: c.allow_support_login }, 'Settings saved');
    await this.auth.refresh();
    await Promise.all([this.loadCompany(), this.loadAudit()]);
  }

  async preview() {
    try {
      this.nextNo.set((await this.api.get(`/company/numbering/preview?format=${encodeURIComponent(this.setup.prj)}`)).next);
    } catch {
      this.nextNo.set('invalid format');
    }
  }

  async saveSetup() {
    await this.api.put('/company/setup', { branches: this.setup.branches, currency: this.setup.currency, tax_label: this.setup.tax_label,
      tax_rate: this.setup.tax_rate, numbering: { PRJ: this.setup.prj } }, 'Setup saved');
    await this.auth.refresh();
    await Promise.all([this.loadCompany(), this.loadAudit()]);
  }

  // templates
  total(t: any) {
    return t.stages.reduce((a: number, s: any) => a + s.duration_days, 0);
  }

  hasTemplate(name: string) {
    return this.templates().some((t) => t.name === name);
  }

  async addPreset(key: string) {
    await this.api.post('/stage_templates', { preset: key }, 'Template added');
    await this.loadTemplates();
  }

  editTemplate(t?: any) {
    this.tf = t ? { id: t.id, name: t.name, service: t.service, is_default: t.is_default, stages: t.stages.map((s: any) => ({ ...s })) }
      : { name: '', service: 'architecture', is_default: false, stages: [{ name: '', duration_days: 14, checklist: [], client_signoff: true }] };
    this.tplDlg = true;
  }

  swap(i: number, j: number) {
    const s = this.tf.stages;
    [s[i], s[j]] = [s[j], s[i]];
  }

  async saveTemplate() {
    const body = { name: this.tf.name, service: this.tf.service, stages: this.tf.stages, is_default: this.tf.is_default };
    if (this.tf.id) await this.api.put(`/stage_templates/${this.tf.id}`, body, 'Template saved');
    else await this.api.post('/stage_templates', body, 'Template created');
    this.tplDlg = false;
    await this.loadTemplates();
  }

  async makeDefault(t: any) {
    await this.api.put(`/stage_templates/${t.id}`, { is_default: true }, `${t.name} is now the default`);
    await this.loadTemplates();
  }

  async deleteTemplate(t: any) {
    await this.api.del(`/stage_templates/${t.id}`, 'Template deleted');
    await this.loadTemplates();
  }

  // roles
  cell(v?: string) {
    return v === 'rw' ? '✏️' : v === 'r' ? '👁' : '—';
  }

  cellClass(v?: string) {
    return 'perm-cell ' + (v === 'rw' ? 'c-ok' : v === 'r' ? 'c-warn' : 'muted');
  }

  cycle(row: any, area: string) {
    const order = ['', 'r', 'rw'];
    row.draft[area] = order[(order.indexOf(row.draft[area] ?? '') + 1) % 3];
    this.roles.set({ ...this.roles() });
  }

  dirty(row: any) {
    return this.roles().areas.some((a: string) => (row.draft[a] ?? '') !== (row.effective[a] ?? ''));
  }

  hasOverrides(row: any) {
    return Object.keys(row.overrides ?? {}).length > 0;
  }

  async saveRole(row: any) {
    const perms: any = {};
    for (const a of this.roles().areas) perms[a] = row.draft[a] ?? '';
    await this.api.put(`/roles/${row.role}`, { perms }, `${row.label} permissions saved`);
    await Promise.all([this.loadRoles(), this.loadAudit()]);
  }

  async resetRole(row: any) {
    await this.api.put(`/roles/${row.role}`, { perms: {} }, `${row.label} reset to default`);
    await Promise.all([this.loadRoles(), this.loadAudit()]);
  }
}
