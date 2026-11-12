import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { Api, label, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { PO_SEV } from './procurement.component';

const OVERSPEND = [{ value: 'client_change', label: 'Client changed something' }, { value: 'our_mistake', label: 'Our mistake' }, { value: 'price_rise', label: 'Price rise' }];
const REJECT = ['Damaged', 'Wrong item', 'Short', 'Quality'];
const SIGNOFF = ['In person', 'Email', 'WhatsApp', 'Phone', 'Signed document'];

/** One purchase order (Phase H): laid out to print, with its approval, sending, acknowledgement, deliveries (GRN),
 *  amendments and close-out. A Site Supervisor sees items and quantities and records deliveries, never prices. */
@Component({
  selector: 'app-purchase-order',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TagModule],
  template: `
    @if (po(); as o) {
      <div class="row-between mb no-print wrap gap">
        <a routerLink="/app/procurement" [queryParams]="{ tab: 'pos' }"><i class="pi pi-arrow-left"></i> Procurement</a>
        <span class="row gap wrap"><p-tag [value]="label(o.status)" [severity]="sev[o.status]" />
          @if (canWrite()) {
            @if (['draft', 'rejected'].includes(o.status)) { <p-button label="Submit" icon="pi pi-check" size="small" (onClick)="act('submit')" />
              <p-button label="Delete" size="small" [text]="true" severity="secondary" (onClick)="del()" /> }
            @if (o.status === 'waiting_approval') {
              <p-button label="Approve" icon="pi pi-check" size="small" (onClick)="approve()" />
              <p-button label="Reject" size="small" [outlined]="true" severity="danger" (onClick)="ask('reject')" /> }
            @if (['approved', 'sent', 'acknowledged', 'part_received'].includes(o.status)) {
              <p-button [label]="o.status === 'approved' ? 'Send to supplier' : 'Send again'" icon="pi pi-send" size="small" (onClick)="send()" /> }
            @if (o.status === 'sent') { <p-button label="Mark acknowledged" size="small" [outlined]="true" (onClick)="ackDlg = true" /> }
            @if (['approved', 'sent', 'acknowledged', 'part_received'].includes(o.status) && money()) { <p-button label="Amend" size="small" [outlined]="true" (onClick)="openAmend()" /> }
            @if (['approved', 'sent', 'acknowledged', 'part_received', 'received'].includes(o.status) && hasOpen()) { <p-button label="Short-close" size="small" [text]="true" (onClick)="ask('short-close')" /> }
            @if (!['draft', 'rejected', 'cancelled', 'closed'].includes(o.status) && !touched()) { <p-button label="Cancel PO" size="small" [text]="true" severity="danger" (onClick)="ask('cancel')" /> }
          }
          @if (canReceive()) { <p-button label="Record delivery" icon="pi pi-truck" size="small" (onClick)="openGrn()" /> }
          <p-button label="Print" icon="pi pi-print" size="small" [text]="true" (onClick)="print()" /></span>
      </div>
      @if (o.approval?.needs?.length && o.status === 'waiting_approval') {
        <p class="note no-print">Waiting for {{ o.approval.needs.includes('owner') ? 'an Owner (above the approval limit)' : '' }}{{ o.approval.needs.length > 1 ? ' and ' : '' }}{{ o.approval.needs.includes('budget') ? 'budget approval (takes a stage over budget)' : '' }}.</p>
      }
      @if (o.status === 'rejected' && o.approval?.reason) { <p class="note c-bad no-print">Rejected: {{ o.approval.reason }}</p> }
      <article class="sheet">
        <header class="row-between top">
          <div>
            @if (o.company?.logo_url) { <img [src]="o.company.logo_url" alt="" class="logo" /> }
            <h2 class="m0" [style.color]="o.company?.primary">{{ o.company?.name ?? '' }}</h2>
            @if (o.company) { <div class="small muted">@if (o.company.address) { {{ o.company.address }}<br /> }
              @if (o.company.gstin) { GSTIN {{ o.company.gstin }} · } {{ o.company.phone }} {{ o.company.email }}</div> }
          </div>
          <div class="right"><h1 class="m0">Purchase order</h1><div><strong>{{ o.number || 'DRAFT' }}</strong>@if (o.revisions?.length) { <span class="small"> rev {{ o.revisions.length }}</span> }</div>
            <div class="small">Date {{ (o.approved_at || o.created_at) | date: 'd MMM y' }}</div>
            @if (o.expected_date) { <div class="small">Deliver by {{ o.expected_date | date: 'd MMM y' }}</div> }</div>
        </header>
        <section class="row-between parties">
          <div><div class="small muted">Supplier</div><strong>{{ o.vendor_name }}</strong><div class="small">{{ o.vendor_email }}</div></div>
          <div class="right"><div class="small muted">Deliver to</div>{{ o.project_name }}<div class="small">{{ o.delivery_address }}</div></div>
        </section>
        <table class="lines">
          <thead><tr><th>Item</th><th class="num">Qty</th>@if (money()) { <th class="num">Rate</th><th class="num">Amount</th><th class="num">Tax</th> }
            <th class="num no-print">Received</th><th class="num no-print">Billed</th></tr></thead>
          <tbody>
            @for (l of o.lines; track l.id) {
              <tr><td>{{ l.description }}<div class="small muted no-print">{{ stage(l.stage_id) }}</div></td><td class="num">{{ l.qty }} {{ l.unit || '' }}</td>
                @if (money()) { <td class="num">{{ fmt(l.unit_cost) }}</td><td class="num">{{ fmt(l.cost) }}</td><td class="num">{{ fmt(l.tax) }} <span class="small muted">{{ l.tax_pct }}%</span></td> }
                <td class="num no-print">{{ l.accepted_qty || 0 }}@if (l.short_closed_qty) { <div class="small muted">{{ l.short_closed_qty }} closed</div> }</td>
                <td class="num no-print">{{ l.billed_qty || 0 }}</td></tr>
            }
          </tbody>
        </table>
        @if (money()) {
          <div class="totals"><div><span>Subtotal</span><span>{{ fmt(o.cost) }}</span></div><div><span>Tax</span><span>{{ fmt(o.tax) }}</span></div>
            <div class="grand"><span>Total</span><span>{{ fmt(o.total) }}</span></div></div>
        }
        @if (o.terms) { <p class="notes small">{{ o.terms }}</p> }
        @if (o.acknowledged) { <footer class="small">Acknowledged by {{ o.acknowledged.name }} ({{ o.acknowledged.method }}) on {{ o.acknowledged.date | date: 'd MMM y' }}</footer> }
      </article>

      <div class="no-print mt">
        @if (o.vendor_updates?.length) { <h3>Supplier updates</h3>
          @for (u of o.vendor_updates; track $index) { <div class="small">{{ u.at | date: 'd MMM, HH:mm' }} · delivery {{ u.was ?? '—' }} → <strong>{{ u.date }}</strong>@if (u.note) { · {{ u.note }} }</div> } }
        <h3>Deliveries</h3>
        @for (r of o.receipts; track r.id) {
          <div class="grn"><div class="row-between"><strong>{{ r.number }}@if (r.reversed) { <span class="c-bad small"> reversed: {{ r.reversed.reason }}</span> }@if (r.location?.kind === 'warehouse') { <span class="small muted"> · into {{ r.location.name }}</span> }</strong>
            <span class="small muted">{{ r.date | date: 'd MMM y' }} · {{ r.received_by }}@if (r.challan) { · challan {{ r.challan }} }
              @if (!r.reversed && !r.returns?.length && canReverse()) { <p-button label="Reverse" size="small" [text]="true" severity="secondary" (onClick)="reverse(r)" /> }</span></div>
            @for (l of r.lines; track l.line_id) { <div class="small">{{ l.accepted }} {{ l.unit || '' }} {{ l.description }} accepted@if (l.rejected) { <span class="c-bad"> · {{ l.rejected }} rejected ({{ l.reason }})</span> }@if (l.returned) { <span> · {{ l.returned }} returned</span> }</div> }
          </div>
        } @empty { <p class="muted small">Nothing received yet.</p> }
        @if (o.revisions?.length) { <h3>Amendments</h3>
          @for (v of o.revisions; track v.rev) { <div class="small">Rev {{ v.rev }} · {{ v.at | date: 'd MMM y' }} · {{ v.by }}@if (money()) { · {{ fmt(v.old_total) }} → {{ fmt(v.new_total) }} } · {{ v.reason }}</div> } }
        @if (o.cancel_reason) { <p class="small c-bad">Cancelled: {{ o.cancel_reason }}</p> }
        @if (o.short_close_reason) { <p class="small muted">Short-closed: {{ o.short_close_reason }}</p> }
      </div>
    }

    <p-dialog header="Record a delivery" [modal]="true" [(visible)]="grnDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="gf.date" fluid /></label>
          <label class="field"><span>Challan / delivery note no.</span><input pInputText [(ngModel)]="gf.challan" fluid /></label>
          @if (stores().length) { <label class="field"><span>Received at</span><p-select [options]="stores()" optionLabel="label" optionValue="value" [(ngModel)]="gf.location" fluid appendTo="body" /></label> }
        </div>
        @for (l of gf.lines; track l.line_id) {
          <div class="grn-ln"><span class="small">{{ l.description }}<div class="muted">{{ l.left }} {{ l.unit || '' }} still to come</div></span>
            <p-inputnumber [(ngModel)]="l.received" [min]="0" placeholder="Received" [inputStyle]="{ width: '100%' }" />
            <p-inputnumber [(ngModel)]="l.rejected" [min]="0" placeholder="Rejected" [inputStyle]="{ width: '100%' }" />
            <p-select [options]="reject" [(ngModel)]="l.reason" placeholder="Why rejected" [disabled]="!l.rejected" appendTo="body" /></div>
        }
        <label class="field"><span>Photos</span><input type="file" accept="image/*" multiple capture="environment" (change)="photos($event)" />
          @if (gf.photos.length) { <small class="muted">{{ gf.photos.length }} photo(s) attached</small> }</label>
        <div class="row right"><p-button label="Save delivery" icon="pi pi-check" [loading]="busy" (onClick)="saveGrn()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Amend the order" [modal]="true" [(visible)]="amDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '100vw' }">
      <div class="stack">
        <p class="small muted m0">An increase sends the PO back for approval before it goes to the supplier again.</p>
        @for (l of am.lines; track l.id) {
          <div class="row gap"><span class="grow small">{{ l.description }}</span><p-inputnumber [(ngModel)]="l.qty" [min]="0" placeholder="Qty" [inputStyle]="{ width: '6rem' }" />
            <p-inputnumber [(ngModel)]="l.unit_cost" [min]="0" placeholder="Rate" [inputStyle]="{ width: '7rem' }" /></div>
        }
        <label class="field req"><span>Why does the order change?</span><input pInputText [(ngModel)]="am.reason" fluid /></label>
        <div class="row right"><p-button label="Save amendment" [disabled]="!am.reason?.trim()" (onClick)="saveAmend()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Acknowledged by the supplier" [modal]="true" [(visible)]="ackDlg" [style]="{ width: '28rem' }">
      <div class="stack"><label class="field"><span>Name</span><input pInputText [(ngModel)]="ack.name" fluid /></label>
        <label class="field"><span>How</span><p-select [options]="signoff" [(ngModel)]="ack.method" fluid appendTo="body" /></label>
        <div class="row right"><p-button label="Save" [disabled]="!ack.name?.trim() || !ack.method" (onClick)="saveAck()" /></div></div>
    </p-dialog>

    <p-dialog header="Approve over budget" [modal]="true" [(visible)]="apDlg" [style]="{ width: '28rem' }">
      <div class="stack"><p class="small m0">This PO takes a stage over its budget. Why?</p>
        <p-select [options]="overspend" optionLabel="label" optionValue="value" [(ngModel)]="overReason" fluid appendTo="body" />
        <div class="row right"><p-button label="Approve" [disabled]="!overReason" (onClick)="act('approve', { overspend_reason: overReason })" /></div></div>
    </p-dialog>

    <p-dialog header="Why?" [modal]="true" [(visible)]="reasonDlg" [style]="{ width: '26rem' }">
      <div class="stack"><input pInputText [(ngModel)]="reason" fluid aria-label="Reason" />
        <div class="row right"><p-button label="Confirm" [disabled]="!reason.trim()" (onClick)="act(reasonFor, { reason })" /></div></div>
    </p-dialog>
  `,
  styles: `
    .sheet { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 2rem; max-width: 56rem; }
    .top { align-items: flex-start; border-bottom: 2px solid var(--border); padding-bottom: 1rem; }
    .logo { max-height: 48px; margin-bottom: .4rem; }
    .parties { margin: 1.2rem 0; align-items: flex-start; }
    .lines { width: 100%; border-collapse: collapse; }
    .lines th, .lines td { padding: .5rem .4rem; border-bottom: 1px solid var(--border); text-align: left; }
    .num { text-align: right !important; font-variant-numeric: tabular-nums; }
    .totals { margin-left: auto; width: min(100%, 20rem); margin-top: 1rem; }
    .totals div { display: flex; justify-content: space-between; padding: .25rem 0; font-variant-numeric: tabular-nums; }
    .totals .grand { font-weight: 700; border-top: 1px solid var(--border); }
    .notes { white-space: pre-wrap; margin-top: 1rem; }
    .note { background: var(--surface); border-left: 3px solid var(--warn, #d97706); padding: .5rem .8rem; }
    footer { margin-top: 2rem; border-top: 1px solid var(--border); padding-top: .6rem; }
    .grn { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .8rem; margin-bottom: .5rem; background: var(--surface); }
    .grn-ln { display: grid; grid-template-columns: minmax(0, 2fr) 6.5rem 6.5rem 9rem; gap: .4rem; align-items: center; }
    @media (max-width: 760px) { .grn-ln { grid-template-columns: 1fr 1fr; } }
    @media print { .no-print { display: none !important; } .sheet { border: 0; padding: 0; } }
  `,
})
export class PurchaseOrderComponent implements OnInit {
  id = input.required<string>();
  auth = inject(AuthService);
  private api = inject(Api);
  po = signal<any>(null);
  stages = signal<Record<string, string>>({});
  sev = PO_SEV;
  label = label;
  reject = REJECT;
  signoff = SIGNOFF;
  overspend = OVERSPEND;
  grnDlg = false; amDlg = false; ackDlg = false; apDlg = false; reasonDlg = false; busy = false;
  gf: any = { lines: [], photos: [] };
  am: any = { lines: [] };
  ack: any = { name: '', method: 'Email' };
  overReason = '';
  reason = ''; reasonFor = '';

  canWrite = () => this.auth.can('procurement', 'rw');
  money = () => this.po() && 'total' in this.po();
  hasOpen = () => (this.po()?.lines ?? []).some((l: any) => (l.accepted_qty || 0) + (l.short_closed_qty || 0) < l.qty);
  touched = () => (this.po()?.lines ?? []).some((l: any) => l.received_qty || l.billed_qty);
  canReceive = () => ['approved', 'sent', 'acknowledged', 'part_received'].includes(this.po()?.status)
    && (this.canWrite() || this.auth.user()?.role === 'site');

  async ngOnInit() {
    await this.load();
    try {
      const p = await this.api.get(`/projects/${this.po().project_id}`);
      this.stages.set(Object.fromEntries(p.stages.map((s: any) => [s.id, s.name])));
    } catch { /* stage names are a nicety */ }
  }

  async load() {
    this.po.set(await this.api.get(`/purchase-orders/${this.id()}`));
  }

  stage(id: string) {
    return this.stages()[id] ?? '';
  }

  fmt(v: number) {
    return money(v, this.po()?.company?.currency ?? (this.auth.company() as any)?.currency ?? 'INR');
  }

  print() {
    window.print();
  }

  async act(what: string, body: any = {}) {
    const r = await this.api.post(`/purchase-orders/${this.id()}/${what}`, body, 'Done');
    this.apDlg = this.reasonDlg = false;
    if (r?.id) this.po.set({ ...this.po(), ...r });
    await this.load();
  }

  approve() {
    if ((this.po().approval?.needs ?? []).includes('budget')) { this.overReason = ''; this.apDlg = true; } else this.act('approve');
  }

  async send() {
    await this.api.post(`/purchase-orders/${this.id()}/send`, { email: true, whatsapp: true }, 'Sent to the supplier');
    await this.load();
  }

  ask(what: string) {
    this.reasonFor = what;
    this.reason = '';
    this.reasonDlg = true;
  }

  async del() {
    if (!confirm('Delete this draft purchase order?')) return;
    await this.api.del(`/purchase-orders/${this.id()}`, 'Deleted');
    window.location.href = '/app/procurement?tab=pos';
  }

  async saveAck() {
    await this.api.post(`/purchase-orders/${this.id()}/acknowledge`, this.ack, 'Acknowledged');
    this.ackDlg = false;
    await this.load();
  }

  stores = signal<any[]>([]);
  canReverse = () => this.auth.can('procurement', 'rw');

  async reverse(r: any) {
    const reason = prompt(`Reverse ${r.number}? Say why (it is only allowed when nothing of it was billed, returned or used).`);
    if (!reason?.trim()) return;
    await this.api.post(`/goods-receipts/${r.id}/reverse`, { reason }, 'Delivery reversed');
    await this.load();
  }  // Phase I: receive at the site or into a warehouse

  openGrn() {
    this.api.get('/settings/warehouses').then((w: any[]) => this.stores.set(w.length ? [{ label: 'The project site', value: 'site' }, ...w.map((x) => ({ label: x.name, value: x.id }))] : []));
    this.gf = { date: new Date().toISOString().slice(0, 10), challan: '', photos: [], location: 'site',
      lines: this.po().lines.map((l: any) => ({ line_id: l.id, description: l.description, unit: l.unit,
        left: Math.max(0, l.qty - (l.accepted_qty || 0) - (l.short_closed_qty || 0)), received: null, rejected: null, reason: null })) };
    this.grnDlg = true;
  }

  async photos(e: Event) {
    const files = Array.from((e.target as HTMLInputElement).files ?? []);
    this.busy = true;
    try {
      for (const f of files) this.gf.photos.push((await this.api.upload(f)).key);
    } finally { this.busy = false; }
  }

  async saveGrn() {
    const lines = this.gf.lines.filter((l: any) => l.received).map((l: any) => ({ line_id: l.line_id, received: l.received, rejected: l.rejected || 0, reason: l.reason }));
    await this.api.post(`/purchase-orders/${this.id()}/receipts`, { date: this.gf.date, challan: this.gf.challan, photos: this.gf.photos, location: this.gf.location, lines }, 'Delivery recorded');
    this.grnDlg = false;
    await this.load();
  }

  openAmend() {
    this.am = { reason: '', lines: this.po().lines.map((l: any) => ({ id: l.id, description: l.description, qty: l.qty, unit_cost: l.unit_cost })) };
    this.amDlg = true;
  }

  async saveAmend() {
    await this.api.post(`/purchase-orders/${this.id()}/amend`, this.am, 'Amended');
    this.amDlg = false;
    await this.load();
  }
}
