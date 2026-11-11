import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../core/api.service';

/** The client's invoices in the portal (Phase G block 2): what is owed, what was paid, and Pay online. */
@Component({
  selector: 'app-portal-invoices',
  imports: [FormsModule, DatePipe, ButtonModule, DialogModule, InputNumberModule, TagModule],
  template: `
    @if (d(); as d) {
      @if (d.invoices.length) {
        <div class="row-between"><h4>Invoices</h4>@if (d.balance > 0) { <span>Left to pay: <strong>{{ fmt(d.balance) }}</strong></span> }</div>
        @for (i of d.invoices; track i.id) {
          <div class="inv">
            <span class="grow"><strong>{{ i.number }}</strong> <span class="small muted">{{ i.kind === 'credit_note' ? 'Credit note' : '' }} {{ i.date | date: 'mediumDate' }}
              @if (i.due_date && i.kind !== 'credit_note') { · due {{ i.due_date | date: 'mediumDate' }} }</span>
              @for (l of i.lines; track l.id) { <div class="small muted">{{ l.description }}</div> }</span>
            <span class="right"><strong>{{ i.kind === 'credit_note' ? '−' : '' }}{{ fmt(i.total) }}</strong>
              @if (i.kind !== 'credit_note') { <div><p-tag [value]="i.overdue ? 'overdue' : i.status === 'part_paid' ? 'part paid' : i.status" [severity]="i.status === 'paid' ? 'success' : i.overdue ? 'danger' : 'warn'" /></div> }
              @if (d.pay_enabled && i.kind !== 'credit_note' && i.balance > 0) { <p-button label="Pay {{ fmt(i.balance) }}" icon="pi pi-credit-card" size="small" (onClick)="openPay(i)" styleClass="mt-xs" /> }
            </span>
          </div>
        }
      }
      @if (d.receipts.length) {
        <h4>Payments received</h4>
        @for (r of d.receipts; track r.number) {
          <div class="ms-row"><span class="grow small">{{ r.number }} · {{ r.date | date: 'mediumDate' }} · {{ r.mode }} · for {{ r.invoices.join(', ') }}</span><strong>{{ fmt(r.amount) }}</strong></div>
        }
      }
    }

    <p-dialog header="Pay online" [modal]="true" [(visible)]="dlg" [style]="{ width: '26rem' }">
      <div class="stack">
        <p class="m0">Invoice <strong>{{ target?.number }}</strong> · {{ fmt(target?.balance) }} left to pay</p>
        <label class="field"><span>Amount</span><p-inputnumber [(ngModel)]="amount" [min]="1" [max]="target?.balance" fluid /></label>
        <p class="small muted m0">You pay on the payment page (UPI, card or net banking). Your receipt arrives by email once the payment goes through.</p>
        <div class="row right"><p-button label="Go to payment" icon="pi pi-external-link" [loading]="busy()" [disabled]="!amount" (onClick)="pay()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .inv { display: flex; gap: .75rem; border: 1px solid var(--border); border-radius: 10px; padding: .6rem .8rem; margin-bottom: .5rem; }
    .mt-xs { margin-top: .35rem; }
  `,
})
export class PortalInvoicesComponent implements OnInit {
  projectId = input.required<string>();
  currency = input('INR');
  private api = inject(Api);
  d = signal<any>(null);
  busy = signal(false);
  dlg = false;
  target: any = null;
  amount: number | null = null;

  async ngOnInit() {
    try {
      this.d.set(await this.api.get(`/portal/projects/${this.projectId()}/invoices`));
    } catch {
      this.d.set(null);  // not the client on this project: no invoices section
    }
  }

  fmt(v: number) {
    return money(v, this.currency());
  }

  openPay(i: any) {
    this.target = i;
    this.amount = i.balance;
    this.dlg = true;
  }

  async pay() {
    this.busy.set(true);
    try {
      const link = await this.api.post(`/portal/invoices/${this.target.id}/pay`, { amount: this.amount });
      window.location.href = link.url;
    } finally {
      this.busy.set(false);
    }
  }
}
