import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../core/api.service';
import { INVOICE_KIND, INVOICE_SEV } from './projects/project-invoices.component';

/** One invoice or credit note, laid out to print (Phase E block 2): company letterhead, client, lines with tax,
 *  totals, balance and the credit notes against it. Printing uses the browser's own print. */
@Component({
  selector: 'app-invoice-view',
  imports: [DatePipe, RouterLink, ButtonModule, TagModule],
  template: `
    @if (inv(); as i) {
      <div class="row-between mb no-print">
        @if (i.project_id) { <a [routerLink]="['/app/projects', i.project_id]" [queryParams]="{ tab: 'money' }"><i class="pi pi-arrow-left"></i> {{ i.project_code }} {{ i.project_name }}</a> }
        @else { <a routerLink="/app/finance"><i class="pi pi-arrow-left"></i> Finance</a> }
        <span class="row gap"><p-tag [value]="i.overdue ? 'overdue' : i.status" [severity]="i.overdue ? 'danger' : sev[i.status]" />
          <p-button label="Print" icon="pi pi-print" size="small" (onClick)="print()" /></span>
      </div>
      <article class="sheet">
        <header class="row-between top">
          <div>
            @if (i.company.logo_url) { <img [src]="i.company.logo_url" alt="" class="logo" /> }
            <h2 class="m0" [style.color]="i.company.primary">{{ i.company.name }}</h2>
            <div class="small muted">@if (i.company.address) { {{ i.company.address }}<br /> }
              @if (i.company.gstin) { GSTIN {{ i.company.gstin }} · } {{ i.company.phone }} {{ i.company.email }}</div>
          </div>
          <div class="right">
            <h1 class="m0">{{ kind[i.kind] === 'Credit note' ? 'Credit note' : 'Tax invoice' }}</h1>
            <div><strong>{{ i.number || 'DRAFT' }}</strong></div>
            <div class="small">Date {{ i.date | date: 'd MMM y' }}</div>
            @if (i.due_date) { <div class="small">Due {{ i.due_date | date: 'd MMM y' }}</div> }
            @if (i.credit_of_number) { <div class="small">Against invoice {{ i.credit_of_number }}</div> }
          </div>
        </header>
        <section class="row-between parties">
          <div><div class="small muted">Bill to</div><strong>{{ i.client_name || '—' }}</strong>
            <div class="small">@if (i.client_address) { {{ i.client_address }}<br /> } @if (i.client_gstin) { GSTIN {{ i.client_gstin }} }</div></div>
          <div class="right"><div class="small muted">Project</div>{{ i.project_code }} {{ i.project_name }}
            @if (i.contract_number) { <div class="small">Contract {{ i.contract_number }}</div> }
            @if (i.gst?.place_of_supply) { <div class="small">Place of supply: {{ i.gst.place_of_supply }}</div> }</div>
        </section>
        <table class="lines">
          <thead><tr><th>Description</th>@if (hasHsn(i)) { <th>HSN/SAC</th> }<th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th><th class="num">{{ i.tax_label }}</th></tr></thead>
          <tbody>
            @for (l of i.lines; track l.id) {
              <tr><td>{{ l.description }}</td>@if (hasHsn(i)) { <td>{{ l.hsn || '—' }}</td> }<td class="num">{{ l.qty }}</td><td class="num">{{ fmt(l.rate) }}</td><td class="num">{{ fmt(l.amount) }}</td>
                <td class="num">{{ fmt(l.tax) }} <span class="small muted">{{ l.tax_pct }}%</span></td></tr>
            }
          </tbody>
        </table>
        <div class="totals">
          <div><span>Subtotal</span><span>{{ fmt(i.subtotal) }}</span></div>
          @if (i.gst; as g) {
            @if (g.mode === 'inter') { <div><span>IGST</span><span>{{ fmt(g.igst) }}</span></div> }
            @else { <div><span>CGST</span><span>{{ fmt(g.cgst) }}</span></div><div><span>SGST</span><span>{{ fmt(g.sgst) }}</span></div> }
          } @else { <div><span>{{ i.tax_label }}</span><span>{{ fmt(i.tax) }}</span></div> }
          <div class="grand"><span>Total</span><span>{{ fmt(i.total) }}</span></div>
          @if (i.retention) { <div><span>Retention held</span><span>− {{ fmt(i.retention) }}</span></div>
            <div><span>Due now</span><span>{{ fmt(i.total - i.retention) }}</span></div> }
          @if (i.kind !== 'credit_note' && (i.credited || i.paid)) {
            @if (i.credited) { <div><span>Credited</span><span>− {{ fmt(i.credited) }}</span></div> }
            @if (i.paid) { <div><span>Received</span><span>− {{ fmt(i.paid) }}</span></div> }
            <div class="grand"><span>Balance due</span><span>{{ fmt(i.balance) }}</span></div>
          }
        </div>
        @if (i.notes) { <p class="notes">{{ i.notes }}</p> }
        @if (i.reason) { <p class="notes">Reason: {{ i.reason }}</p> }
        @if (i.company.footer) { <footer class="small muted">{{ i.company.footer }}</footer> }
      </article>
      @if (i.payments?.length) {
        <div class="no-print mt"><strong>Payments</strong>
          @for (x of i.payments; track x.id) { <div>{{ x.number }} · {{ x.date | date: 'd MMM y' }} · {{ fmt(x.amount) }} {{ x.kind === 'advance' ? '(advance taken on the lead)' : '' }}</div> }</div>
      }
      @if (i.credit_notes?.length) {
        <div class="no-print mt"><strong>Credit notes</strong>
          @for (c of i.credit_notes; track c.id) { <div><a [routerLink]="['/app/invoices', c.id]">{{ c.number }}</a> · {{ fmt(c.total) }} · {{ c.reason }}</div> }</div>
      }
      @if (i.void_reason) { <p class="c-bad no-print">Void: {{ i.void_reason }}</p> }
    }
  `,
  styles: `
    .sheet { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 2rem; max-width: 52rem; }
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
    footer { margin-top: 2rem; border-top: 1px solid var(--border); padding-top: .6rem; }
    @media print { .no-print { display: none !important; } .sheet { border: 0; padding: 0; } }
  `,
})
export class InvoiceViewComponent implements OnInit {
  id = input.required<string>();
  private api = inject(Api);
  inv = signal<any>(null);
  sev = INVOICE_SEV;
  kind = INVOICE_KIND;

  async ngOnInit() {
    this.inv.set(await this.api.get(`/invoices/${this.id()}`));
  }

  hasHsn(i: any) {
    return (i.lines ?? []).some((l: any) => l.hsn);
  }

  fmt(v: number) {
    return money(v, this.inv()?.currency ?? this.inv()?.company?.currency ?? 'INR');  // Phase L: the invoice's own currency
  }

  print() {
    window.print();
  }
}
