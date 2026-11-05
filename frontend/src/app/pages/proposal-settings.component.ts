import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { TooltipModule } from 'primeng/tooltip';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, SERVICE_LABEL, label } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Settings -> Proposals & branding (Phase D): logo, colour and footer for proposals / contracts; proposal templates. */
@Component({
  selector: 'app-proposal-settings',
  imports: [TooltipModule, FormsModule, ButtonModule, CardModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TableModule, TagModule, TextareaModule],
  template: `
    <p-card><ng-template #title>Branding on proposals and contracts</ng-template>
      <div class="grid2 top">
        <div class="stack">
          <div class="field"><span>Logo (PNG, JPG or WEBP)</span>
            <div class="row gap">@if (b.logo_url) { <img [src]="b.logo_url + '?v=' + ver" alt="Logo" class="doc-logo" /> }
              @if (canEdit()) { <input type="file" accept=".png,.jpg,.jpeg,.webp" (change)="logo($event)" />
                @if (b.logo_key) { <p-button label="Remove" size="small" [text]="true" severity="danger" (onClick)="b.logo_key = null; b.logo_url = null" /> } }</div></div>
          <label class="field"><span>Brand colour</span><div class="row gap"><input type="color" [(ngModel)]="b.primary" [disabled]="!canEdit()" /><input pInputText [(ngModel)]="b.primary" [disabled]="!canEdit()" style="width: 7rem" /></div></label>
          <label class="field"><span>Address</span><input pInputText [(ngModel)]="b.address" [disabled]="!canEdit()" fluid /></label>
        </div>
        <div class="stack">
          <div class="grid2">
            <label class="field"><span>Phone</span><input pInputText [(ngModel)]="b.phone" [disabled]="!canEdit()" fluid /></label>
            <label class="field"><span>Email</span><input pInputText [(ngModel)]="b.email" [disabled]="!canEdit()" fluid /></label>
          </div>
          <label class="field"><span>Website</span><input pInputText [(ngModel)]="b.website" [disabled]="!canEdit()" fluid /></label>
          <label class="field"><span>Footer (bank details, registration…)</span><textarea pTextarea rows="2" [(ngModel)]="b.footer" [disabled]="!canEdit()" fluid></textarea></label>
        </div>
      </div>
      @if (canEdit()) { <div class="row right"><p-button label="Save branding" icon="pi pi-check" (onClick)="saveBranding()" /></div> }
    </p-card>

    <p-card styleClass="mt">
      <ng-template #title><div class="row-between"><span>Proposal templates</span>@if (canEdit()) { <p-button label="New template" icon="pi pi-plus" size="small" (onClick)="edit()" /> }</div></ng-template>
      <p-table [value]="templates()" size="small">
        <ng-template #header><tr><th>Name</th><th>Type</th><th>Service</th><th>Lines</th><th>Payment schedule</th><th></th></tr></ng-template>
        <ng-template #body let-x><tr><td><strong>{{ x.name }}</strong></td><td>{{ label(x.type) }}</td><td>{{ svc[x.service] || '—' }}</td><td>{{ x.items?.length || 0 }}</td>
          <td><small>{{ x.payment_schedule?.length ? x.payment_schedule.length + ' payment(s)' : 'default (10% on signing + per stage)' }}</small></td>
          <td class="right nowrap">@if (canEdit()) { <p-button icon="pi pi-pencil" [text]="true" (onClick)="edit(x)" ariaLabel="Edit" pTooltip="Edit"/><p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="del(x)" ariaLabel="Delete" pTooltip="Delete"/> }</td></tr></ng-template>
        <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No proposal templates yet.</td></tr></ng-template>
      </p-table>
    </p-card>

    <p-dialog [header]="tf.id ? 'Edit template' : 'New template'" [modal]="true" [(visible)]="dlg" [style]="{ width: '50rem' }" [breakpoints]="{ '820px': '96vw' }">
      <div class="stack">
        <div class="grid3">
          <label class="field"><span>Name</span><input pInputText [(ngModel)]="tf.name" fluid /></label>
          <label class="field"><span>Type</span><p-select [options]="types" [(ngModel)]="tf.type" optionLabel="label" optionValue="value" fluid appendTo="body" /></label>
          <label class="field"><span>Service (for the schedule's stages)</span><p-select [options]="services()" [(ngModel)]="tf.service" optionLabel="label" optionValue="value" (onChange)="loadStages()" fluid appendTo="body" /></label>
        </div>
        <label class="field"><span>Introduction</span><textarea pTextarea rows="2" [(ngModel)]="tf.intro" fluid></textarea></label>
        <label class="field"><span>Scope</span><textarea pTextarea rows="2" [(ngModel)]="tf.scope_text" fluid></textarea></label>
        <label class="field"><span>Terms</span><textarea pTextarea rows="3" [(ngModel)]="tf.terms" fluid></textarea></label>
        <strong>Default lines</strong>
        @for (it of tf.items; track $index; let i = $index) {
          <div class="row gap wrap"><input pInputText [(ngModel)]="it.description" placeholder="Description" class="grow" />
            <p-inputnumber [(ngModel)]="it.qty" [min]="0" placeholder="Qty" [inputStyle]="{ width: '4rem' }" /><input pInputText [(ngModel)]="it.unit" placeholder="Unit" style="width: 4rem" />
            <p-inputnumber [(ngModel)]="it.rate" [min]="0" placeholder="Rate" [inputStyle]="{ width: '6rem' }" />
            <label class="check"><p-checkbox [(ngModel)]="it.optional" [binary]="true" /> optional</label>
            <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="tf.items.splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/></div>
        }
        <p-button label="Add line" icon="pi pi-plus" size="small" [text]="true" (onClick)="tf.items.push({ description: '', qty: 1, unit: '', rate: null, optional: false })" />
        <strong>Payment schedule <small class="muted">(leave empty for the default)</small></strong>
        @for (r of tf.payment_schedule; track $index; let i = $index) {
          <div class="row gap wrap"><input pInputText [(ngModel)]="r.name" placeholder="Payment" class="grow" />
            <p-inputnumber placeholder="%" [(ngModel)]="r.pct" [min]="0" [max]="100" suffix="%" [inputStyle]="{ width: '5rem' }" />
            <p-select placeholder="When" [options]="triggers" [(ngModel)]="r.trigger" optionLabel="label" optionValue="value" appendTo="body" />
            @if (r.trigger === 'stage') { <p-select [options]="stages()" [(ngModel)]="r.stage" placeholder="Stage" appendTo="body" /> }
            @if (r.trigger === 'date') { <input aria-label="Date" title="Date" pInputText type="date" [(ngModel)]="r.date" /> }
            <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="tf.payment_schedule.splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/></div>
        }
        <p-button label="Add payment" icon="pi pi-plus" size="small" [text]="true" [disabled]="!tf.service" (onClick)="tf.payment_schedule.push({ name: '', pct: null, trigger: 'stage' })" />
        <div class="row right"><p-button label="Save template" icon="pi pi-check" (onClick)="save()" /></div>
      </div>
    </p-dialog>
  `,
})
export class ProposalSettingsComponent implements OnInit {
  private api = inject(Api);
  auth = inject(AuthService);
  canEdit = computed(() => this.auth.can('settings', 'rw'));
  templates = signal<any[]>([]);
  stages = signal<string[]>([]);
  stageTpl = signal<any[]>([]);
  services = computed(() => ((this.auth.company() as any)?.modules ?? []).map((s: string) => ({ value: s, label: SERVICE_LABEL[s] })));
  svc = SERVICE_LABEL;
  label = label;
  types = [{ value: 'fee', label: 'Fee proposal' }, { value: 'construction', label: 'Construction estimate' }, { value: 'interior', label: 'Interior quote' }];
  triggers = [{ value: 'signing', label: 'On signing' }, { value: 'stage', label: 'When a stage is complete' }, { value: 'date', label: 'On a date' }];
  b: any = {};
  tf: any = {};
  dlg = false;
  ver = 0;

  async ngOnInit() {
    this.b = await this.api.get('/company/branding');
    this.templates.set(await this.api.get('/proposal_templates'));
    if (this.auth.can('projects')) this.stageTpl.set((await this.api.get('/stage_templates')).templates);
  }

  async logo(ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (!file) return;
    const up = await this.api.upload(file);
    this.b = { ...this.b, ...(await this.api.put('/company/branding', { logo_key: up.key }, 'Logo saved')) };
    this.ver++;
  }

  async saveBranding() {
    const { logo_key, primary, address, phone, email, website, footer } = this.b;
    this.b = await this.api.put('/company/branding', { logo_key, primary, address, phone, email, website, footer }, 'Branding saved');
    this.ver++;
  }

  loadStages() {
    const tpl = this.stageTpl().find((x) => x.service === this.tf.service && x.is_default) ?? this.stageTpl().find((x) => x.service === this.tf.service);
    this.stages.set((tpl?.stages ?? []).map((s: any) => s.name));
  }

  edit(x?: any) {
    this.tf = x ? JSON.parse(JSON.stringify({ ...x, items: x.items ?? [], payment_schedule: x.payment_schedule ?? [] }))
      : { name: '', type: 'fee', service: this.services()[0]?.value ?? null, intro: '', scope_text: '', terms: '', items: [], payment_schedule: [] };
    this.loadStages();
    this.dlg = true;
  }

  async save() {
    const { id, created_at, updated_at, company_id, created_by, ...body } = this.tf;
    body.items = body.items.filter((i: any) => i.description?.trim());
    if (id) await this.api.put(`/proposal_templates/${id}`, body, 'Template saved');
    else await this.api.post('/proposal_templates', body, 'Template created');
    this.dlg = false;
    this.templates.set(await this.api.get('/proposal_templates'));
  }

  async del(x: any) {
    await this.api.del(`/proposal_templates/${x.id}`, 'Template deleted');
    this.templates.set(await this.api.get('/proposal_templates'));
  }
}
