import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** Phase D proposal builder (§5): fee proposal, construction estimate or interior quote; lines, optional items,
 *  discount, tax, payment schedule; approval; send with a client link. */
@Component({
  selector: 'app-proposal-builder',
  imports: [FormsModule, DatePipe, DecimalPipe, RouterLink, ButtonModule, CardModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule,
    MessageModule, SelectModule, SelectButtonModule, TableModule, TagModule, TextareaModule],
  template: `
    @if (p(); as p) {
      <div class="page-head">
        <div>
          <a [routerLink]="['/app/leads', p.lead_id]" class="small"><i class="pi pi-arrow-left"></i> {{ p.lead_title }}</a>
          <h1>{{ p.number }} v{{ p.version }} · {{ p.meta.types[p.type] }}</h1>
          <div class="row gap"><p-tag [value]="label(p.status)" [severity]="p.status === 'accepted' ? 'success' : p.status === 'sent' ? 'info' : 'secondary'" />
            @if (p.view_count) { <small class="muted">opened {{ p.view_count }}× · last {{ p.last_viewed_at | date: 'd MMM, h:mm a' }}</small> }
            @if (p.approval?.status) { <p-tag [value]="'Approval ' + p.approval.status" [severity]="p.approval.status === 'approved' ? 'success' : p.approval.status === 'pending' ? 'warn' : 'danger'" /> }</div>
        </div>
        <div class="row gap wrap">
          <p-button label="Preview" icon="pi pi-eye" [outlined]="true" (onClick)="preview()" />
          @if (editable()) {
            <p-button label="Save" icon="pi pi-save" [outlined]="true" (onClick)="save()" />
            @if (p.breaches.length && !p.meta.is_approver && p.approval?.status !== 'approved') {
              <p-button label="Ask for approval" icon="pi pi-check-circle" severity="warn" [disabled]="p.approval?.status === 'pending'" (onClick)="askApproval()" /> }
            @if (p.approval?.status === 'pending' && p.meta.is_approver) {
              <p-button label="Approve" severity="success" (onClick)="decide(true)" /><p-button label="Refuse" severity="danger" [text]="true" (onClick)="refuseDlg = true" /> }
            <p-button label="Send to client" icon="pi pi-send" (onClick)="sendDlg = true" />
          }
          @if (p.link) { <p-button label="Client link" icon="pi pi-link" [text]="true" (onClick)="copy(origin + p.link)" /> }
        </div>
      </div>
      @if (p.breaches.length && editable()) { <p-message severity="warn" text="Needs the owner / sales manager's approval before sending: {{ p.breaches.join('; ') }}" styleClass="mb" /> }

      <div class="grid2 top">
        <div class="stack">
          <p-card><ng-template #title>Proposal</ng-template>
            <div class="stack">
              <div class="grid2">
                <label class="field"><span>Title</span><input pInputText [(ngModel)]="f.title" [disabled]="!editable()" fluid /></label>
                <label class="field"><span>Valid until</span><input pInputText type="date" [(ngModel)]="f.valid_until" [disabled]="!editable()" fluid /></label>
              </div>
              <label class="field"><span>Introduction</span><textarea pTextarea rows="3" [(ngModel)]="f.intro" [disabled]="!editable()" fluid></textarea></label>
              <label class="field"><span>Scope of work</span><textarea pTextarea rows="4" [(ngModel)]="f.scope_text" [disabled]="!editable()" fluid></textarea></label>
              <label class="field"><span>Terms</span><textarea pTextarea rows="3" [(ngModel)]="f.terms" [disabled]="!editable()" fluid></textarea></label>
              <div class="field"><span>Attached file (optional)</span>
                <div class="row gap">@if (f.file_key) { <a href="" (click)="$event.preventDefault(); api.openFile('/api/files/' + f.file_key)">open</a>
                  @if (editable()) { <a href="" (click)="$event.preventDefault(); f.file_key = null">remove</a> } }
                  @if (editable()) { <input type="file" accept=".pdf,.doc,.docx" (change)="attach($event)" /> }</div></div>
            </div>
          </p-card>

          @if (p.type === 'fee' || p.type === 'interior') {
            <p-card><ng-template #title>{{ p.type === 'interior' ? 'Design fee' : 'Fee' }}</ng-template>
              <div class="stack">
                <p-selectbutton [options]="feeBases()" [(ngModel)]="fee.basis" optionLabel="label" optionValue="value" [allowEmpty]="false" [disabled]="!editable()" />
                <div class="grid3">
                  @switch (fee.basis) {
                    @case ('fixed') { <label class="field"><span>Amount</span><p-inputnumber [(ngModel)]="fee.amount" [min]="0" [disabled]="!editable()" fluid /></label> }
                    @case ('hourly') { <label class="field"><span>Hours</span><p-inputnumber [(ngModel)]="fee.hours" [min]="0" [disabled]="!editable()" fluid /></label>
                      <label class="field"><span>Rate / hour</span><p-inputnumber [(ngModel)]="fee.rate" [min]="0" [disabled]="!editable()" fluid /></label> }
                    @case ('percent') { <label class="field"><span>% of project cost</span><p-inputnumber [(ngModel)]="fee.pct" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!editable()" fluid /></label>
                      <label class="field"><span>Project cost</span><p-inputnumber [(ngModel)]="fee.project_cost" [min]="0" [disabled]="!editable()" fluid /></label> }
                    @case ('per_area') { <label class="field"><span>Area</span><p-inputnumber [(ngModel)]="fee.area" [min]="0" [disabled]="!editable()" fluid /></label>
                      <label class="field"><span>Rate per {{ fee.area_unit === 'sqm' ? 'm²' : 'sq ft' }}</span><p-inputnumber [(ngModel)]="fee.rate" [min]="0" [disabled]="!editable()" fluid /></label>
                      <div class="field"><span>Unit</span><p-selectbutton [options]="units" [(ngModel)]="fee.area_unit" optionLabel="label" optionValue="value" [allowEmpty]="false" [disabled]="!editable()" /></div> }
                  }
                </div>
                @if (p.type === 'fee') {
                  <strong class="small">Split the fee across stages (optional, must total 100%)</strong>
                  @for (s of fee.stages; track $index; let i = $index) {
                    <div class="row gap"><p-select [options]="p.meta.stages" [(ngModel)]="s.name" [editable]="true" [disabled]="!editable()" appendTo="body" />
                      <p-inputnumber [(ngModel)]="s.pct" [min]="0" [max]="100" suffix="%" [disabled]="!editable()" [inputStyle]="{ width: '6rem' }" />
                      @if (editable()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="fee.stages.splice(i, 1)" /> }</div>
                  }
                  @if (editable()) { <p-button label="Add stage" icon="pi pi-plus" size="small" [text]="true" (onClick)="fee.stages.push({ name: '', pct: null })" /> }
                }
              </div>
            </p-card>
          }

          @if (p.type === 'construction') {
            <p-card><ng-template #title>From estimate {{ p.estimate_number }}</ng-template>
              <p class="small muted">Every estimate line is priced for the client at its share of the estimate's price (cost, overheads and markup stay internal). To change quantities or rates, make a new estimate version, approve it and choose it here.</p>
              @if (editable()) { <p-select [options]="estimates()" [(ngModel)]="f.estimate_id" optionLabel="label" optionValue="id" fluid appendTo="body" /> }
            </p-card>
          }

          @if (p.type === 'interior') {
            <p-card><ng-template #title>Products</ng-template>
              <p-table [value]="products" size="small" [scrollable]="true">
                <ng-template #header><tr><th>Room</th><th>Product</th><th>Brand</th><th class="right">Qty</th><th>Unit</th><th class="right">Trade price</th><th class="right">Markup %</th><th class="right">Client price</th><th>Optional</th><th></th></tr></ng-template>
                <ng-template #body let-r let-i="rowIndex"><tr>
                  <td><input pInputText [(ngModel)]="r.room" [disabled]="!editable()" style="width: 6rem" /></td>
                  <td><input pInputText [(ngModel)]="r.name" [disabled]="!editable()" style="width: 9rem" /></td>
                  <td><input pInputText [(ngModel)]="r.brand" [disabled]="!editable()" style="width: 6rem" /></td>
                  <td class="right"><p-inputnumber [(ngModel)]="r.qty" [min]="0" [disabled]="!editable()" [inputStyle]="{ width: '4rem' }" /></td>
                  <td><input pInputText [(ngModel)]="r.unit" [disabled]="!editable()" style="width: 3.5rem" /></td>
                  <td class="right"><p-inputnumber [(ngModel)]="r.trade_price" [min]="0" [disabled]="!editable()" [inputStyle]="{ width: '6rem' }" /></td>
                  <td class="right"><p-inputnumber [(ngModel)]="r.markup_pct" [min]="0" [disabled]="!editable()" [inputStyle]="{ width: '4rem' }" /></td>
                  <td class="right">{{ fmt((r.trade_price || 0) * (1 + (r.markup_pct || 0) / 100)) }}</td>
                  <td class="center"><p-checkbox [(ngModel)]="r.optional" [binary]="true" [disabled]="!editable()" /></td>
                  <td>@if (editable()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="products.splice(i, 1)" /> }</td></tr></ng-template>
              </p-table>
              @if (editable()) { <p-button label="Add product" icon="pi pi-plus" size="small" [text]="true" (onClick)="products.push({ room: '', name: '', qty: 1, unit: 'nos', trade_price: null, markup_pct: 25, optional: false })" /> }
            </p-card>
          }

          @if (p.type === 'simple') {
            <p-card><ng-template #title>Value</ng-template>
              <p-inputnumber [(ngModel)]="f.value" [min]="0" [disabled]="!editable()" fluid />
            </p-card>
          } @else {
            <p-card><ng-template #title>More lines (extra services, allowances, options)</ng-template>
              @for (it of extra; track $index; let i = $index) {
                <div class="row gap wrap mb-xs">
                  <input pInputText [(ngModel)]="it.section" placeholder="Section" [disabled]="!editable()" style="width: 7rem" />
                  <input pInputText [(ngModel)]="it.description" placeholder="Description" [disabled]="!editable()" class="grow" />
                  <p-inputnumber [(ngModel)]="it.qty" [min]="0" placeholder="Qty" [disabled]="!editable()" [inputStyle]="{ width: '4rem' }" />
                  <input pInputText [(ngModel)]="it.unit" placeholder="Unit" [disabled]="!editable()" style="width: 4rem" />
                  <p-inputnumber [(ngModel)]="it.rate" [min]="0" placeholder="Rate" [disabled]="!editable()" [inputStyle]="{ width: '6rem' }" />
                  <label class="check"><p-checkbox [(ngModel)]="it.optional" [binary]="true" [disabled]="!editable()" /> optional</label>
                  @if (editable()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="extra.splice(i, 1)" /> }
                </div>
              }
              @if (editable()) { <p-button label="Add line" icon="pi pi-plus" size="small" [text]="true" (onClick)="extra.push({ section: '', description: '', qty: 1, unit: '', rate: null, optional: false })" /> }
            </p-card>
          }
        </div>

        <div class="stack">
          <p-card><ng-template #title>Price</ng-template>
            @if (p.items?.length) {
              <p-table [value]="p.items" size="small">
                <ng-template #body let-i><tr [class.muted]="i.optional"><td>{{ i.section ? i.section + ' · ' : '' }}{{ i.description }}{{ i.optional ? ' (optional)' : '' }}</td>
                  <td class="right nowrap">{{ i.qty | number: '1.0-2' }} {{ i.unit || '' }}</td><td class="right">{{ fmt(i.amount) }}</td></tr></ng-template>
              </p-table>
            }
            <div class="grid2 mt-xs">
              <label class="field"><span>Discount % <small class="muted">(limit {{ p.meta.limits.max_discount_pct }}%)</small></span><p-inputnumber [(ngModel)]="f.discount_pct" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!editable() || p.type === 'simple'" fluid /></label>
              <label class="field"><span>{{ p.meta.tax_label }} %</span><p-inputnumber [(ngModel)]="f.tax_pct" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!editable() || p.type === 'simple'" fluid /></label>
            </div>
            @if (p.totals; as tt) {
              <table class="totals small mt-xs">
                <tr><td>Subtotal</td><td class="right">{{ fmt(tt.subtotal) }}</td></tr>
                <tr><td>Discount</td><td class="right">− {{ fmt(tt.discount) }}</td></tr>
                <tr><td>{{ p.meta.tax_label }}</td><td class="right">{{ fmt(tt.tax) }}</td></tr>
                <tr><td><strong>Total</strong></td><td class="right"><strong>{{ fmt(tt.total) }}</strong></td></tr>
                @if (tt.optional_available) { <tr><td class="muted">Options the client can add</td><td class="right muted">{{ fmt(tt.optional_available) }}</td></tr> }
                @if (tt.cost != null) { <tr><td class="muted">Internal cost · margin</td><td class="right" [class.c-bad]="tt.margin_pct < p.meta.limits.min_margin_pct">{{ fmt(tt.cost) }} · {{ tt.margin_pct | number: '1.1-1' }}%</td></tr> }
              </table>
            }
            @if (editable()) { <small class="muted">Save to recalculate.</small> }
          </p-card>

          <p-card><ng-template #title>Payment schedule <small class="muted">(becomes the contract's schedule)</small></ng-template>
            @for (r of schedule; track $index; let i = $index) {
              <div class="row gap wrap mb-xs">
                <input pInputText [(ngModel)]="r.name" placeholder="Payment" [disabled]="!editable()" class="grow" />
                <p-inputnumber [(ngModel)]="r.pct" [min]="0" [max]="100" suffix="%" [maxFractionDigits]="2" [disabled]="!editable()" [inputStyle]="{ width: '5rem' }" />
                <p-select [options]="triggers()" [(ngModel)]="r.trigger" optionLabel="label" optionValue="value" [disabled]="!editable()" appendTo="body" />
                @if (r.trigger === 'stage') { <p-select [options]="p.meta.stages" [(ngModel)]="r.stage" placeholder="Stage" [disabled]="!editable()" appendTo="body" /> }
                @if (r.trigger === 'date') { <input pInputText type="date" [(ngModel)]="r.date" [disabled]="!editable()" /> }
                @if (editable()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="schedule.splice(i, 1)" /> }
              </div>
            }
            <div class="row-between"><small [class.c-bad]="schedTotal() !== 100">Total {{ schedTotal() }}%{{ schedTotal() !== 100 ? ' — must be 100%' : '' }}</small>
              @if (editable()) { <p-button label="Add payment" icon="pi pi-plus" size="small" [text]="true" (onClick)="schedule.push({ name: '', pct: null, trigger: 'stage' })" /> }</div>
          </p-card>

          @if (p.acceptance) {
            <p-card><ng-template #title>Accepted</ng-template>
              <div class="small">{{ p.acceptance.name }} · {{ p.acceptance.method }} · {{ p.acceptance.at | date: 'd MMM y, h:mm a' }}</div>
              @if (p.acceptance.signature) { <img [src]="p.acceptance.signature" alt="Signature" class="sig-img" /> }
              @if (p.contract_id) { <a [routerLink]="['/app/contracts', p.contract_id]">Open the contract →</a> }
            </p-card>
          }
        </div>
      </div>

      <p-dialog header="Send to the client" [modal]="true" [(visible)]="sendDlg" [style]="{ width: '30rem' }">
        <div class="stack">
          <p class="small muted">The client gets a private link to view the proposal, choose options and accept with a signature. Email sends it (with the file) when email is set up; otherwise copy the link and share it.</p>
          <p-selectbutton [options]="channels" [(ngModel)]="channel" optionLabel="label" optionValue="value" [allowEmpty]="false" />
          <div class="row right"><p-button label="Send" icon="pi pi-send" (onClick)="send()" /></div>
        </div>
      </p-dialog>

      <p-dialog header="Sent — the client's link" [modal]="true" [(visible)]="linkDlg" [style]="{ width: '34rem' }">
        <div class="stack"><div class="row gap"><input pInputText [value]="sentLink" readonly class="grow" /><p-button icon="pi pi-copy" (onClick)="copy(sentLink)" /></div>
          <small class="muted">You are told when the client opens it, and reminded if it is opened but not answered.</small></div>
      </p-dialog>

      <p-dialog header="Refuse" [modal]="true" [(visible)]="refuseDlg" [style]="{ width: '26rem' }">
        <div class="stack"><input pInputText [(ngModel)]="refuseNote" placeholder="Why" />
          <div class="row right"><p-button label="Refuse" severity="danger" (onClick)="decide(false)" [disabled]="!refuseNote.trim()" /></div></div>
      </p-dialog>
    }
  `,
})
export class ProposalBuilderComponent implements OnInit {
  id = input.required<string>();
  api = inject(Api);
  private auth = inject(AuthService);
  private router = inject(Router);
  private toast = inject(MessageService);
  p = signal<any>(null);
  estimates = signal<any[]>([]);
  editable = computed(() => this.p()?.status === 'draft' && this.auth.can('proposals', 'rw'));
  feeBases = computed(() => Object.entries(this.p()?.meta?.fee_bases ?? {}).filter(([k]) => this.p()?.type !== 'interior' || ['fixed', 'per_area'].includes(k))
    .map(([value, label]) => ({ value, label })));
  triggers = computed(() => Object.entries(this.p()?.meta?.triggers ?? {}).map(([value, label]) => ({ value, label })));
  label = label;
  origin = location.origin;
  units = [{ label: 'sq ft', value: 'sqft' }, { label: 'm²', value: 'sqm' }];
  channels = [{ label: 'Email', value: 'email' }, { label: 'WhatsApp', value: 'whatsapp' }, { label: 'In person', value: 'in_person' }, { label: 'Other', value: 'other' }];
  f: any = {};
  fee: any = { basis: 'fixed', stages: [] };
  products: any[] = [];
  extra: any[] = [];
  schedule: any[] = [];
  channel = 'email';
  sendDlg = false;
  linkDlg = false;
  refuseDlg = false;
  refuseNote = '';
  sentLink = '';

  async ngOnInit() {
    await this.load();
  }

  fmt(v: number | null | undefined) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  schedTotal() {
    return Math.round(this.schedule.reduce((a, r) => a + (r.pct || 0), 0) * 100) / 100;
  }

  async load(p?: any) {
    p = p ?? (await this.api.get(`/proposals/${this.id()}`));
    if (!p.meta) p = await this.api.get(`/proposals/${this.id()}`);
    this.p.set(p);
    this.f = { title: p.title, valid_until: p.valid_until, intro: p.intro ?? '', scope_text: p.scope_text ?? '', terms: p.terms ?? '',
      file_key: p.file_key, discount_pct: p.discount_pct, tax_pct: p.tax_pct, value: p.value, estimate_id: p.estimate_id };
    this.fee = { basis: p.type === 'interior' ? 'fixed' : 'fixed', stages: [], area_unit: 'sqft', ...(p.fee ?? {}) };
    this.fee.stages = (this.fee.stages ?? []).map((s: any) => ({ ...s }));
    this.products = (p.products ?? []).map((x: any) => ({ ...x }));
    this.extra = (p.extra_items ?? []).map((x: any) => ({ ...x }));
    this.schedule = (p.payment_schedule ?? []).map((x: any) => ({ ...x }));
    if (p.type === 'construction' && this.estimates().length === 0) {
      const r = await this.api.get(`/leads/${p.lead_id}/estimates`);
      this.estimates.set(r.estimates.filter((e: any) => e.status === 'approved').map((e: any) => ({ ...e, label: `${e.number} v${e.version} · ${this.fmt(e.totals.total)}` })));
    }
  }

  body() {
    const p = this.p();
    const b: any = { ...this.f, payment_schedule: this.schedule };
    if (p.type === 'fee' || p.type === 'interior') b.fee = this.feeFilled() ? this.fee : null;
    if (p.type === 'interior') b.products = this.products.filter((x) => x.name?.trim());
    if (p.type !== 'simple') b.extra_items = this.extra.filter((x) => x.description?.trim());
    if (p.type !== 'simple') delete b.value;
    if (p.type !== 'construction') delete b.estimate_id;
    return b;
  }

  private feeFilled() {
    const f = this.fee;
    return ({ fixed: f.amount, hourly: f.hours && f.rate, percent: f.pct && f.project_cost, per_area: f.area && f.rate } as any)[f.basis];
  }

  async save(quiet = false) {
    const p = await this.api.put(`/proposals/${this.id()}`, this.body(), quiet ? undefined : 'Saved');
    await this.load(p);
  }

  async askApproval() {
    await this.save(true);
    await this.load(await this.api.post(`/proposals/${this.id()}/approval`, {}, 'Sent for approval'));
  }

  async decide(approve: boolean) {
    await this.load(await this.api.post(`/proposals/${this.id()}/approval/decide`, { approve, note: approve ? undefined : this.refuseNote }, approve ? 'Approved' : 'Refused'));
    this.refuseDlg = false;
  }

  async send() {
    await this.save(true);
    const r = await this.api.post(`/proposals/${this.id()}/send`, { channel: this.channel }, 'Sent');
    this.sendDlg = false;
    this.sentLink = r.link_full;
    this.linkDlg = true;
    await this.load();
  }

  async attach(ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (file) this.f.file_key = (await this.api.upload(file)).key;
  }

  async preview() {
    if (this.editable()) await this.save(true);
    window.open(`/app/proposals/${this.id()}/preview`, '_blank');
  }

  copy(text: string) {
    navigator.clipboard?.writeText(text).then(() => this.toast.add({ severity: 'success', summary: 'Link copied', life: 1500 }));
  }
}
