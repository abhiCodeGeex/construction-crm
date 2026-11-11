import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { TagModule } from 'primeng/tag';
import { Api, label, money } from '../core/api.service';

/** Supplier portal (Phase H block 4): their own purchase orders and prices only, acknowledge, update the delivery date,
 *  upload an invoice against a PO, answer requests for quotation, and see their bills' status. Hidden for clients. */
@Component({
  selector: 'app-portal-supplier',
  imports: [FormsModule, DatePipe, ButtonModule, DialogModule, InputNumberModule, InputTextModule, TagModule],
  template: `
    @if (d(); as v) {
      @if (v.rfqs.length) {
        <h3>Requests for quotation</h3>
        @for (r of v.rfqs; track r.id) {
          <div class="box"><div class="row-between"><strong>{{ r.number }} · {{ r.project }}</strong><span class="small muted">quotes due {{ r.due_date | date: 'd MMM' }}</span></div>
            @for (l of r.lines; track l.id) { <div class="small">{{ l.qty }} {{ l.unit || '' }} {{ l.description }}@if (r.my_quote?.rates?.[l.id] != null) { · your rate {{ fmt(r.my_quote.rates[l.id]) }} }</div> }
            <div class="row right mt"><p-button [label]="r.my_quote ? 'Change my quote' : 'Send my quote'" size="small" (onClick)="openQuote(r)" /></div></div>
        }
      }
      @if (v.purchase_orders.length) {
        <h3>Your purchase orders</h3>
        @for (o of v.purchase_orders; track o.id) {
          <div class="box"><div class="row-between wrap gap"><strong>{{ o.number }} · {{ o.project }}@if (o.revision) { <span class="small"> rev {{ o.revision }}</span> }</strong>
              <p-tag [value]="label(o.status)" /></div>
            <div class="small muted">Deliver by {{ o.expected_date ? (o.expected_date | date: 'd MMM y') : '—' }}@if (o.delivery_address) { · {{ o.delivery_address }} }</div>
            <table class="ln"><tbody>@for (l of o.lines; track l.id) {
              <tr><td>{{ l.description }}</td><td class="num">{{ l.qty }} {{ l.unit || '' }}</td><td class="num">{{ fmt(l.rate) }}</td><td class="num">{{ fmt(l.amount) }}</td>
                <td class="num small muted">{{ l.accepted }} received · {{ l.billed }} billed</td></tr> }</tbody></table>
            <div class="small right">Total {{ fmt(o.total) }} <span class="muted">(incl. tax {{ fmt(o.tax) }})</span></div>
            <div class="row gap right mt wrap">
              @if (o.status === 'sent') { <p-button label="Acknowledge" size="small" (onClick)="openAck(o)" /> }
              @if (!['received', 'closed'].includes(o.status)) { <p-button label="Change delivery date" size="small" [outlined]="true" (onClick)="openDate(o)" /> }
              @if (canInvoice(o)) { <p-button label="Upload invoice" size="small" [outlined]="true" (onClick)="openInv(o)" /> }
            </div>
            @if (o.acknowledged) { <div class="small muted">Acknowledged by {{ o.acknowledged.name }} on {{ o.acknowledged.date | date: 'd MMM y' }}</div> }
          </div>
        }
      }
      @if (v.bills.length) {
        <h3>Your bills</h3>
        @for (b of v.bills; track b.bill_no) {
          <div class="ms-row small"><span class="grow">{{ b.bill_no }} · {{ b.po_number }} · {{ b.date | date: 'd MMM y' }}</span>
            <span>{{ fmt(b.total) }}@if (b.paid) { · paid {{ fmt(b.paid) }} }</span><p-tag [value]="billLabel(b.status)" [severity]="b.status === 'paid' ? 'success' : 'info'" /></div>
        }
      }
    }

    <p-dialog header="Acknowledge the order" [modal]="true" [(visible)]="ackDlg" [style]="{ width: '26rem' }">
      <div class="stack"><p class="small m0">Type your name to confirm you accept {{ cur?.number }}.</p>
        <input pInputText [(ngModel)]="name" fluid aria-label="Your name" />
        <div class="row right"><p-button label="Acknowledge" [disabled]="!name.trim()" (onClick)="ack()" /></div></div>
    </p-dialog>
    <p-dialog header="Change the delivery date" [modal]="true" [(visible)]="dateDlg" [style]="{ width: '26rem' }">
      <div class="stack"><input pInputText type="date" [(ngModel)]="date" fluid aria-label="New date" />
        <input pInputText [(ngModel)]="note" placeholder="Why (optional)" fluid />
        <div class="row right"><p-button label="Save" [disabled]="!date" (onClick)="saveDate()" /></div></div>
    </p-dialog>
    <p-dialog header="Upload your invoice" [modal]="true" [(visible)]="invDlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="grid2"><label class="field req"><span>Invoice no.</span><input pInputText [(ngModel)]="inv.bill_no" fluid /></label>
          <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="inv.date" fluid /></label></div>
        @for (l of inv.lines; track l.line_id) {
          <div class="row gap"><span class="grow small">{{ l.description }}</span><p-inputnumber [(ngModel)]="l.qty" [min]="0" placeholder="Qty" [inputStyle]="{ width: '6rem' }" />
            <p-inputnumber [(ngModel)]="l.rate" [min]="0" placeholder="Rate" [inputStyle]="{ width: '7rem' }" /></div>
        }
        <label class="field req"><span>Invoice file</span><input type="file" accept="application/pdf,image/*" (change)="file($event)" /></label>
        <div class="row right"><p-button label="Send" [loading]="busy" [disabled]="!inv.bill_no || !inv.file_key" (onClick)="saveInv()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Your quote" [modal]="true" [(visible)]="qDlg" [style]="{ width: '30rem' }">
      <div class="stack">
        @for (l of rfq?.lines ?? []; track l.id) { <div class="row gap"><span class="grow small">{{ l.qty }} {{ l.unit || '' }} {{ l.description }}</span><p-inputnumber [(ngModel)]="q.rates[l.id]" [min]="0" placeholder="Rate" /></div> }
        <div class="row gap"><p-inputnumber [(ngModel)]="q.tax_pct" placeholder="Tax %" /><p-inputnumber [(ngModel)]="q.delivery_days" placeholder="Delivery days" /></div>
        <div class="row right"><p-button label="Send quote" (onClick)="saveQuote()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .box { border: 1px solid var(--border); border-radius: var(--radius); padding: .7rem .9rem; margin-bottom: .6rem; background: var(--surface); }
    .ln { width: 100%; border-collapse: collapse; margin: .4rem 0; }
    .ln td { padding: .25rem .3rem; border-bottom: 1px solid var(--border); }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
  `,
})
export class PortalSupplierComponent implements OnInit {
  currency = input('INR');
  private api = inject(Api);
  d = signal<any>(null);
  label = label;
  cur: any = null;
  rfq: any = null;
  ackDlg = false; dateDlg = false; invDlg = false; qDlg = false; busy = false;
  name = ''; date = ''; note = '';
  inv: any = { lines: [] };
  q: any = { rates: {} };

  async ngOnInit() {
    try {
      this.d.set(await this.api.get('/portal/purchase-orders'));
    } catch { this.d.set(null); }
  }

  fmt(v: number) {
    return money(v, this.currency());
  }

  billLabel(s: string) {
    return { draft: 'received, being checked', matched: 'checked', on_hold: 'being checked', approved: 'approved', part_paid: 'part paid', paid: 'paid' }[s] ?? s;
  }

  canInvoice(o: any) {
    return o.lines.some((l: any) => l.accepted > l.billed);
  }

  openAck(o: any) { this.cur = o; this.name = ''; this.ackDlg = true; }
  openDate(o: any) { this.cur = o; this.date = o.expected_date ?? ''; this.note = ''; this.dateDlg = true; }

  openInv(o: any) {
    this.cur = o;
    this.inv = { bill_no: '', date: new Date().toISOString().slice(0, 10), file_key: null,
      lines: o.lines.filter((l: any) => l.accepted > l.billed).map((l: any) => ({ line_id: l.id, description: l.description, qty: l.accepted - l.billed, rate: l.rate })) };
    this.invDlg = true;
  }

  openQuote(r: any) {
    this.rfq = r;
    this.q = { rates: { ...(r.my_quote?.rates ?? {}) }, tax_pct: r.my_quote?.tax_pct ?? null, delivery_days: r.my_quote?.delivery_days ?? null };
    this.qDlg = true;
  }

  async ack() {
    await this.api.post(`/portal/purchase-orders/${this.cur.id}/acknowledge`, { name: this.name }, 'Thank you — acknowledged');
    this.ackDlg = false;
    await this.ngOnInit();
  }

  async saveDate() {
    await this.api.post(`/portal/purchase-orders/${this.cur.id}/delivery-date`, { date: this.date, note: this.note }, 'Delivery date updated');
    this.dateDlg = false;
    await this.ngOnInit();
  }

  async file(e: Event) {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (!f) return;
    this.busy = true;
    try { this.inv.file_key = (await this.api.upload(f, true)).key; } finally { this.busy = false; }
  }

  async saveInv() {
    const lines = this.inv.lines.filter((l: any) => l.qty > 0).map((l: any) => ({ line_id: l.line_id, qty: l.qty, rate: l.rate }));
    await this.api.post(`/portal/purchase-orders/${this.cur.id}/invoice`, { ...this.inv, lines }, 'Invoice sent');
    this.invDlg = false;
    await this.ngOnInit();
  }

  async saveQuote() {
    const lines = Object.entries(this.q.rates).filter(([, v]) => v != null).map(([line_id, rate]) => ({ line_id, rate }));
    await this.api.post(`/portal/rfqs/${this.rfq.id}/quote`, { lines, tax_pct: this.q.tax_pct, delivery_days: this.q.delivery_days }, 'Quote sent');
    this.qDlg = false;
    await this.ngOnInit();
  }
}
