import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { TooltipModule } from 'primeng/tooltip';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { InputNumberModule } from 'primeng/inputnumber';
import { MultiSelectModule } from 'primeng/multiselect';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, SERVICE_LABEL } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { CHANNEL_LABEL } from '../shared/followup-dialog.component';

/** Settings → Sales: pipelines per service, loss reasons, website form, message templates. */
@Component({
  selector: 'app-sales-settings',
  imports: [TooltipModule, FormsModule, ButtonModule, CardModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, MultiSelectModule, SelectModule, TableModule, TagModule, TextareaModule],
  template: `
    @if (meta(); as m) {
      <div class="tpl-grid">
        @for (svc of m.services; track svc) {
          <p-card><ng-template #title>{{ label[svc] }} pipeline</ng-template>
            <ol class="pipe-edit">
              @for (st of draft[svc]; track $index; let i = $index; let last = $last) {
                <li><input placeholder="Stage name" pInputText [(ngModel)]="draft[svc][i]" [disabled]="!canEdit()" />
                  @if (canEdit()) {
                    <p-button icon="pi pi-arrow-up" [text]="true" size="small" [disabled]="i === 0" (onClick)="swap(svc, i, i - 1)" ariaLabel="Move up" pTooltip="Move up"/>
                    <p-button icon="pi pi-arrow-down" [text]="true" size="small" [disabled]="last" (onClick)="swap(svc, i, i + 1)" ariaLabel="Move down" pTooltip="Move down"/>
                    <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="draft[svc].splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/> }</li>
              }
              <li class="muted"><i class="pi pi-trophy"></i> Won · <i class="pi pi-times-circle"></i> Lost <small>(fixed)</small></li>
            </ol>
            @if (canEdit()) { <p-button label="Add stage" icon="pi pi-plus" size="small" [text]="true" (onClick)="draft[svc].push('')" /> }
          </p-card>
        }
        <p-card><ng-template #title>Loss reasons</ng-template>
          @for (r of reasons; track $index; let i = $index) {
            <div class="row gap mb-xs"><input placeholder="Reason" pInputText [(ngModel)]="reasons[i]" [disabled]="!canEdit()" class="grow" />
              @if (canEdit()) { <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="reasons.splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/> }</div>
          }
          @if (canEdit()) { <p-button label="Add reason" icon="pi pi-plus" size="small" [text]="true" (onClick)="reasons.push('')" /> }
        </p-card>
      </div>
      @if (canEdit()) { <div class="row right mt"><p-button label="Save pipelines & reasons" icon="pi pi-check" (onClick)="savePipelines()" /></div> }

      <p-card styleClass="mt"><ng-template #title>Sales rules</ng-template>
        <div class="grid3">
          <label class="field"><span>Sales manager <small class="muted">(gets escalations and approvals; empty = every owner)</small></span>
            <p-select [options]="m.staff" [(ngModel)]="ss.manager_id" optionLabel="name" optionValue="id" [showClear]="true" [disabled]="!canEdit()" fluid appendTo="body" /></label>
          <label class="field"><span>Contact a new lead within (minutes)</span><p-inputnumber [(ngModel)]="ss.response_minutes" [min]="1" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>Tell the manager when a follow-up is late by (days)</span><p-inputnumber [(ngModel)]="ss.followup_escalate_days" [min]="1" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>Hot lead idle alert after (days)</span><p-inputnumber [(ngModel)]="ss.hot_idle_days" [min]="1" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>Discount above this needs approval (%)</span><p-inputnumber [(ngModel)]="ss.max_discount_pct" [min]="0" [max]="100" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>Margin below this needs approval (%)</span><p-inputnumber [(ngModel)]="ss.min_margin_pct" [min]="0" [max]="100" [disabled]="!canEdit()" fluid /></label>
        </div>
        <label class="check mt"><p-checkbox [(ngModel)]="ss.own_leads_only" [binary]="true" [disabled]="!canEdit()" /> Salespeople see only their own leads (the owner and the sales manager see all)</label>
        @if (canEdit()) { <div class="row right mt"><p-button label="Save sales rules" icon="pi pi-check" (onClick)="saveRules()" /></div> }
      </p-card>

      <p-card styleClass="mt"><ng-template #title>Assignment rules — who gets a new lead</ng-template>
        <p class="muted small">Used for website enquiries, imports without an owner and new leads set to “Auto”. The first matching rule wins and
          its people take turns (round-robin). No match → the lead stays unassigned and the sales manager is told.</p>
        @for (r of assign; track $index; let i = $index) {
          <div class="row gap wrap mb-xs">
            <span class="muted small">{{ i + 1 }}.</span>
            <p-select [options]="svcOptions()" [(ngModel)]="r.service" optionLabel="label" optionValue="value" placeholder="Any service" [showClear]="true" [disabled]="!canEdit()" appendTo="body" />
            @if (m.branches?.length) { <p-select [options]="m.branches" [(ngModel)]="r.branch" placeholder="Any branch" [showClear]="true" [disabled]="!canEdit()" appendTo="body" /> }
            <p-multiselect [options]="m.staff" [(ngModel)]="r.user_ids" optionLabel="name" optionValue="id" placeholder="Salespeople" display="chip" [disabled]="!canEdit()" appendTo="body" class="grow" />
            @if (canEdit()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="assign.splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/> }
          </div>
        } @empty { <p class="muted small">No rules — new website leads arrive unassigned.</p> }
        @if (canEdit()) { <div class="row-between mt-xs"><p-button label="Add rule" icon="pi pi-plus" size="small" [text]="true" (onClick)="assign.push({ service: null, branch: null, user_ids: [] })" />
          <p-button label="Save assignment rules" icon="pi pi-check" (onClick)="saveAssign()" /></div> }
      </p-card>

      <p-card styleClass="mt"><ng-template #title>Package rates — for the ballpark on a lead (area × rate)</ng-template>
        <div class="tpl-grid">
          @for (svc of m.services; track svc) {
            <div class="gate"><strong>{{ label[svc] }}</strong>
              @for (p of pkgs[svc]; track $index; let i = $index) {
                <div class="row gap mt-xs"><input pInputText [(ngModel)]="p.name" placeholder="Package" [disabled]="!canEdit()" style="width: 8rem" />
                  <p-inputnumber [(ngModel)]="p.rate" [min]="0" placeholder="Rate" [disabled]="!canEdit()" [inputStyle]="{ width: '7rem' }" />
                  <p-select placeholder="Unit" [options]="rateUnits" [(ngModel)]="p.unit" optionLabel="label" optionValue="value" [disabled]="!canEdit()" appendTo="body" />
                  @if (canEdit()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="pkgs[svc].splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/> }</div>
              } @empty { <p class="muted small">No packages yet.</p> }
              @if (canEdit()) { <p-button label="Add package" icon="pi pi-plus" size="small" [text]="true" (onClick)="pkgs[svc].push({ name: '', rate: null, unit: 'sqft' })" /> }
            </div>
          }
        </div>
        @if (canEdit()) { <div class="row right mt"><p-button label="Save package rates" icon="pi pi-check" (onClick)="savePkgs()" /></div> }
      </p-card>

      <p-card styleClass="mt"><ng-template #title>Stage rules — what must be done before a lead leaves a stage</ng-template>
        <p class="muted small">Moving a lead forward needs every stage it passes to meet its rules. Moving back is always allowed. The owner can override with a reason, which is logged.</p>
        @for (svc of m.services; track svc) {
          <h4>{{ label[svc] }}</h4>
          <div class="tpl-grid">
            @for (st of m.pipelines[svc]; track st) {
              <div class="gate rule-card">
                <strong>{{ st }}</strong>
                <label class="field"><span>Checklist (one per line)</span><textarea pTextarea rows="4" [(ngModel)]="rules[svc][st].checklist_text" [disabled]="!canEdit()"></textarea></label>
                <label class="field"><span>Required steps</span><p-multiselect [options]="reqOptions()" [(ngModel)]="rules[svc][st].requires" optionLabel="label" optionValue="value" [disabled]="!canEdit()" display="chip" fluid appendTo="body" /></label>
                <div class="grid2">
                  <label class="field"><span>Day limit</span><p-inputnumber [(ngModel)]="rules[svc][st].max_days" [min]="1" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>Win probability %</span><p-inputnumber [(ngModel)]="rules[svc][st].probability" [min]="0" [max]="100" [disabled]="!canEdit()" fluid /></label>
                </div>
              </div>
            }
          </div>
        }
        @if (canEdit()) { <div class="row right mt"><p-button label="Save stage rules" icon="pi pi-check" (onClick)="saveStageRules()" /></div> }
      </p-card>

      <p-card styleClass="mt"><ng-template #title>Email sending (SMTP)</ng-template>
        <p class="muted small">When set up, every notification is also emailed to the person (each user can switch emails off), and client emails such as visit reminders are sent. Leave the server empty to switch email off.</p>
        <div class="grid3">
          <label class="field"><span>SMTP server</span><input pInputText [(ngModel)]="em.host" placeholder="smtp.example.com" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>Port</span><p-inputnumber [(ngModel)]="em.port" [useGrouping]="false" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>From address</span><input pInputText [(ngModel)]="em.from_address" placeholder="crm@yourfirm.com" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>Username</span><input pInputText [(ngModel)]="em.username" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>Password</span><input pInputText type="password" [(ngModel)]="em.password" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>App address for links</span><input pInputText [(ngModel)]="em.app_url" [placeholder]="origin" [disabled]="!canEdit()" fluid /></label>
        </div>
        <label class="check mt"><p-checkbox [(ngModel)]="em.use_tls" [binary]="true" [disabled]="!canEdit()" /> Use STARTTLS</label>
        <div class="row gap right mt">
          <p-tag [value]="em.ready ? 'Email is on' : 'Email is off'" [severity]="em.ready ? 'success' : 'secondary'" />
          @if (canEdit()) {
            <p-button label="Send test email to me" icon="pi pi-send" [outlined]="true" [disabled]="!em.ready" (onClick)="testEmail()" />
            <p-button label="Save email settings" icon="pi pi-check" (onClick)="saveEmail()" /> }
        </div>
      </p-card>

      @if (m.form_key) {
        <p-card styleClass="mt"><ng-template #title>Website enquiry form</ng-template>
          <p class="muted">Enquiries from this form arrive as <strong>Website form</strong> leads (unassigned). Repeat enquiries from the same phone or email are added to the open lead instead of creating a duplicate.</p>
          <div class="row gap"><input aria-label="Website form link" title="Website form link" pInputText [value]="formUrl()" readonly class="grow" />
            <p-button label="Copy link" icon="pi pi-copy" [outlined]="true" (onClick)="copy(formUrl())" />
            <a [href]="formUrl()" target="_blank" rel="noopener"><p-button label="Open" icon="pi pi-external-link" [text]="true" /></a></div>
          <label class="field mt"><span>Embed on your website</span><textarea pTextarea rows="3" [value]="embed()" readonly fluid></textarea></label>
          @if (canEdit()) { <p-button label="Regenerate link" icon="pi pi-refresh" severity="warn" [text]="true" (onClick)="rotate()" /><small class="muted">The old link stops working.</small> }
        </p-card>
      }

      <p-card styleClass="mt">
        <ng-template #title><div class="row-between"><span>Message templates</span>
          @if (canEdit()) { <p-button label="New template" icon="pi pi-plus" size="small" (onClick)="editTpl()" /> }</div></ng-template>
        <p class="muted small">Merge fields: @for (f of mergeFields; track f) { <code>{{ mf(f) }}</code> } </p>
        <p-table [value]="templates()" size="small">
          <ng-template #header><tr><th>Name</th><th>Channel</th><th>Text</th><th></th></tr></ng-template>
          <ng-template #body let-t><tr><td><strong>{{ t.name }}</strong></td><td><p-tag [value]="chan[t.channel]" severity="secondary" /></td>
            <td><small class="muted pre">{{ t.body.length > 140 ? t.body.slice(0, 140) + '…' : t.body }}</small></td>
            <td class="right nowrap">@if (canEdit()) { <p-button icon="pi pi-pencil" [text]="true" (onClick)="editTpl(t)" ariaLabel="Edit" pTooltip="Edit"/>
              <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="deleteTpl(t)" ariaLabel="Delete" pTooltip="Delete"/> }</td></tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No message templates yet.</td></tr></ng-template>
      </p-table>
      </p-card>
    }

    <p-dialog [header]="tf.id ? 'Edit template' : 'New template'" [modal]="true" [(visible)]="tplDlg" [style]="{ width: '36rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Name</span><input pInputText [(ngModel)]="tf.name" fluid /></label>
          <label class="field"><span>Channel</span><p-select [options]="channels" [(ngModel)]="tf.channel" optionLabel="label" optionValue="value" fluid appendTo="body" /></label>
        </div>
        @if (tf.channel === 'email') { <label class="field"><span>Subject</span><input pInputText [(ngModel)]="tf.subject" fluid /></label> }
        <label class="field"><span>Text</span><textarea pTextarea rows="7" [(ngModel)]="tf.body" fluid></textarea>
          <small class="muted">{{ tf.body?.length || 0 }} characters{{ tf.channel === 'sms' ? ' (max 480)' : '' }}</small></label>
        <div class="chips">@for (f of mergeFields; track f) { <button type="button" class="chip" (click)="insert(f)">+ {{ f }}</button> }</div>
        <div class="row gap right"><p-button label="Save" icon="pi pi-check" (onClick)="saveTpl()" /></div>
      </div>
    </p-dialog>
  `,
})
export class SalesSettingsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  private toast = inject(MessageService);
  meta = signal<any>(null);
  templates = signal<any[]>([]);
  canEdit = computed(() => this.auth.can('settings', 'rw'));
  formUrl = computed(() => `${location.origin}/f/${this.meta()?.form_key}`);
  embed = computed(() => `<iframe src="${this.formUrl()}" width="100%" height="760" style="border:0" title="Enquiry form"></iframe>`);
  label = SERVICE_LABEL;
  chan = CHANNEL_LABEL;
  channels = [{ value: 'email', label: 'Email' }, { value: 'sms', label: 'SMS' }, { value: 'whatsapp', label: 'WhatsApp' }];
  mergeFields = ['client', 'name', 'project', 'amount', 'company', 'date', 'salesperson'];
  draft: Record<string, string[]> = {};
  reasons: string[] = [];
  ss: any = {};
  rules: Record<string, Record<string, any>> = {};
  em: any = {};
  pkgs: Record<string, any[]> = {};
  assign: any[] = [];
  svcOptions = computed(() => (this.meta()?.services ?? []).map((s: string) => ({ value: s, label: SERVICE_LABEL[s] })));
  rateUnits = [{ label: 'per sq ft', value: 'sqft' }, { label: 'per m²', value: 'sqm' }];
  origin = location.origin;
  reqOptions = computed(() => Object.entries(this.meta()?.requirements ?? {}).map(([value, label]) => ({ value, label })));
  tplDlg = false;
  tf: any = {};

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const m = await this.api.get('/leads/meta');
    this.meta.set(m);
    this.draft = Object.fromEntries(m.services.map((s: string) => [s, [...m.pipelines[s]]]));
    this.reasons = [...m.loss_reasons];
    this.ss = { ...m.sales_settings };
    this.rules = Object.fromEntries(m.services.map((s: string) => [s, Object.fromEntries(m.pipelines[s].map((st: string) => {
      const r = m.stage_rules[s][st];
      return [st, { checklist_text: (r.checklist || []).join('\n'), requires: [...(r.requires || [])], max_days: r.max_days ?? null, probability: r.probability ?? null }];
    }))]));
    this.assign = ((await this.api.get('/leads/assignment')).rules ?? []).map((r: any) => ({ ...r, user_ids: [...r.user_ids] }));
    const rates = await this.api.get('/leads/package-rates');
    this.pkgs = Object.fromEntries(m.services.map((s: string) => [s, (rates[s] ?? []).map((p: any) => ({ ...p }))]));
    this.templates.set(await this.api.get('/message_templates'));
    if (this.auth.can('settings')) this.em = { port: 587, use_tls: true, ...(await this.api.get('/settings/email')) };
  }

  async saveAssign() {
    await this.api.put('/leads/assignment', { rules: this.assign }, 'Assignment rules saved');
    await this.load();
  }

  async savePkgs() {
    await this.api.put('/leads/package-rates', { package_rates: this.pkgs }, 'Package rates saved');
    await this.load();
  }

  async saveRules() {
    await this.api.put('/leads/settings', this.ss, 'Sales rules saved');
    await this.load();
  }

  async saveStageRules() {
    const stage_rules = Object.fromEntries(Object.entries(this.rules).map(([s, stages]) => [s, Object.fromEntries(Object.entries(stages).map(([st, r]) =>
      [st, { checklist: r.checklist_text.split('\n').map((x: string) => x.trim()).filter(Boolean), requires: r.requires, max_days: r.max_days, probability: r.probability }]))]));
    await this.api.put('/leads/settings', { stage_rules }, 'Stage rules saved');
    await this.load();
  }

  async saveEmail() {
    const { ready, ...body } = this.em;
    this.em = { ...(await this.api.put('/settings/email', body, body.host ? 'Email settings saved' : 'Email switched off')) };
  }

  async testEmail() {
    const r = await this.api.post('/settings/email/test', {});
    this.toast.add({ severity: 'success', summary: `Test email sent to ${r.to}`, life: 3000 });
  }

  mf(f: string) {
    return '{' + '{' + f + '}' + '}';
  }

  insert(f: string) {
    this.tf.body = (this.tf.body || '') + this.mf(f);
  }

  swap(svc: string, i: number, j: number) {
    const a = this.draft[svc];
    [a[i], a[j]] = [a[j], a[i]];
  }

  async savePipelines() {
    await this.api.put('/leads/pipelines', { pipelines: this.draft, loss_reasons: this.reasons }, 'Pipelines saved');
    await this.load();
  }

  async rotate() {
    await this.api.post('/leads/form-key', {}, 'New link created');
    await this.load();
  }

  copy(text: string) {
    navigator.clipboard?.writeText(text).then(() => this.toast.add({ severity: 'success', summary: 'Copied', life: 1500 }));
  }

  editTpl(t?: any) {
    this.tf = t ? { ...t } : { name: '', channel: 'whatsapp', subject: '', body: '' };
    this.tplDlg = true;
  }

  async saveTpl() {
    const body = { name: this.tf.name, channel: this.tf.channel, subject: this.tf.subject, body: this.tf.body };
    if (this.tf.id) await this.api.put(`/message_templates/${this.tf.id}`, body, 'Template saved');
    else await this.api.post('/message_templates', body, 'Template created');
    this.tplDlg = false;
    await this.load();
  }

  async deleteTpl(t: any) {
    await this.api.del(`/message_templates/${t.id}`, 'Template deleted');
    await this.load();
  }
}
