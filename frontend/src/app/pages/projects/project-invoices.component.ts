import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ConfirmationService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { TooltipModule } from 'primeng/tooltip';
import { Api, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

export const INVOICE_SEV: Record<string, 'secondary' | 'info' | 'success' | 'danger' | 'warn'> = {
  draft: 'secondary', sent: 'info', part_paid: 'warn', paid: 'success', void: 'secondary',
};
export const INVOICE_KIND: Record<string, string> = { schedule: 'Contract payment', manual: 'Invoice', credit_note: 'Credit note' };

/** Invoices on the project's Money tab (Phase E block 2): the contract's payment schedule with *Raise invoice* on
 *  each due row, extra (manual) invoices, sending (which issues the number), credit notes and void. */
@Component({
  selector: 'app-project-invoices',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule,
    SelectModule, TableModule, TagModule, TextareaModule, TooltipModule],
  template: `
    @if (data(); as d) {
      @if (d.contract; as c) {
        <h3 class="mt">Payment schedule · contract {{ c.number }} · {{ fmt(c.value) }}</h3>
        <p-table [value]="c.payment_schedule" styleClass="p-datatable-sm mb">
          <ng-template #header><tr><th>Payment</th><th>When</th><th class="num">Amount</th><th>State</th><th></th></tr></ng-template>
          <ng-template #body let-r>
            <tr>
              <td>{{ r.name }} <span class="muted small">{{ r.pct }}%</span></td>
              <td class="small">@switch (r.trigger) {
                @case ('signing') { On signing }
                @case ('date') { On {{ r.date | date: 'd MMM y' }} }
                @default { {{ r.stage }} complete @if (r.milestone?.due) { <span class="muted">(due {{ r.milestone.due | date: 'd MMM' }})</span> } }
              }</td>
              <td class="num">{{ fmt(r.amount) }}</td>
              <td>@if (r.status) { <p-tag [value]="r.status" severity="success" /> } @else { <p-tag [value]="r.state" [severity]="r.state === 'due' ? 'warn' : 'secondary'" /> }</td>
              <td class="right">@if (!r.status && d.can_write) {
                @if (r.state === 'due') { <p-button label="Raise invoice" size="small" (onClick)="raise(c, r)" /> }
                @else if (d.is_owner) { <p-button label="Invoice early" size="small" [text]="true" (onClick)="askEarly(c, r)" /> }
              }</td>
            </tr>
          </ng-template>
        </p-table>
      }

      <div class="row-between mb">
        <h3 class="m0">Invoices</h3>
        @if (d.can_write) { <p-button label="New invoice" icon="pi pi-plus" size="small" (onClick)="openNew()" /> }
      </div>
      <p-table [value]="d.invoices" styleClass="p-datatable-sm">
        <ng-template #header><tr><th>Number</th><th>Kind</th><th>Date</th><th>Due</th><th class="num">Total</th><th class="num">Balance</th><th>Status</th><th></th></tr></ng-template>
        <ng-template #body let-i>
          <tr>
            <td><a [routerLink]="['/app/invoices', i.id]">{{ i.number || 'Draft' }}</a>
              @if (i.credit_of_number) { <div class="small muted">against {{ i.credit_of_number }}</div> }</td>
            <td>{{ kind[i.kind] }}@if (i.schedule_row) { <div class="small muted">{{ i.schedule_row }}</div> }</td>
            <td>{{ i.date | date: 'd MMM y' }}</td>
            <td [class.c-bad]="i.overdue">{{ i.due_date ? (i.due_date | date: 'd MMM y') : '—' }}</td>
            <td class="num">{{ i.kind === 'credit_note' ? '−' : '' }}{{ fmt(i.total) }}</td>
            <td class="num">{{ i.kind === 'credit_note' || i.status === 'void' ? '—' : fmt(i.balance) }}</td>
            <td><p-tag [value]="i.overdue ? 'overdue' : i.status" [severity]="i.overdue ? 'danger' : sev[i.status]" /></td>
            <td class="right nowrap">
              @if (d.can_write && i.status === 'draft') {
                @if (i.kind === 'manual') { <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="openEdit(i)" ariaLabel="Edit" pTooltip="Edit" /> }
                <p-button label="Send" size="small" (onClick)="askSend(i)" />
                <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="remove(i)" ariaLabel="Delete" pTooltip="Delete" />
              }
              @if (d.can_write && i.kind !== 'credit_note' && ['sent', 'part_paid'].includes(i.status) && i.balance > 0) {
                <p-button label="Credit note" size="small" [text]="true" (onClick)="askCredit(i)" />
              }
              @if (d.can_void && i.status === 'sent' && i.kind !== 'credit_note' && !i.credited && !i.paid) {
                <p-button label="Void" size="small" [text]="true" severity="secondary" (onClick)="askVoid(i)" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="8" class="muted">No invoices yet.</td></tr></ng-template>
      </p-table>

      @if (rc(); as r) {
        @if (r.advances.length) {
          <h3 class="mt">Advances taken on the lead</h3>
          <p-table [value]="r.advances" styleClass="p-datatable-sm">
            <ng-template #body let-a>
              <tr>
                <td>{{ a.number }} · {{ a.kind }}</td><td>{{ a.date | date: 'd MMM y' }}</td><td>{{ a.mode }}</td>
                <td class="num">{{ fmt(a.amount) }}</td>
                <td class="right">@if (a.applied_invoice_number) { <span class="small muted">applied to {{ a.applied_invoice_number }}</span> }
                  @else if (r.can_write && openInvoices().length) { <p-button label="Apply to invoice" size="small" [text]="true" (onClick)="askApply(a)" /> }</td>
              </tr>
            </ng-template>
          </p-table>
        }
        <div class="row-between mt mb">
          <h3 class="m0">Payments received</h3>
          @if (r.can_write && openInvoices().length) { <p-button label="Record payment" icon="pi pi-plus" size="small" (onClick)="openPay()" /> }
        </div>
        <p-table [value]="r.receipts" styleClass="p-datatable-sm">
          <ng-template #header><tr><th>Receipt</th><th>Date</th><th>Mode</th><th>For</th><th class="num">Amount</th><th></th></tr></ng-template>
          <ng-template #body let-x>
            <tr [class.muted]="x.status === 'void'">
              <td>{{ x.number }}@if (x.status === 'void') { <div class="small c-bad">Void: {{ x.void_reason }}</div> }</td>
              <td>{{ x.date | date: 'd MMM y' }}</td>
              <td>{{ x.mode }}@if (x.reference) { <div class="small muted">{{ x.reference }}</div> }</td>
              <td class="small">@for (a of x.allocations; track a.invoice_id) { <div>{{ a.invoice_number }} · {{ fmt(a.amount) }}</div> }</td>
              <td class="num">{{ fmt(x.amount) }}</td>
              <td class="right">@if (r.can_void && x.status !== 'void') { <p-button label="Void" size="small" [text]="true" severity="secondary" (onClick)="askVoidReceipt(x)" /> }</td>
            </tr>
          </ng-template>
          <ng-template #emptymessage><tr><td colspan="6" class="muted">No payments yet.</td></tr></ng-template>
        </p-table>
      }
    }

    <p-dialog header="Record a payment" [modal]="true" [(visible)]="payDlg" [style]="{ width: '40rem' }" [breakpoints]="{ '700px': '98vw' }">
      <div class="stack">
        <div class="grid3">
          <label class="field req"><span>Date</span><input pInputText type="date" [(ngModel)]="pf.date" fluid /></label>
          <label class="field req"><span>Mode</span><p-select [options]="rc()?.modes ?? []" [(ngModel)]="pf.mode" fluid appendTo="body" /></label>
          <label class="field" [class.req]="pf.mode !== 'Cash'"><span>Reference</span><input pInputText [(ngModel)]="pf.reference" placeholder="UTR / cheque no." fluid /></label>
        </div>
        <div class="small muted">How much of this payment goes to each invoice:</div>
        @for (a of pf.allocations; track a.invoice_id) {
          <div class="alloc-row"><span>{{ a.number }} <span class="small muted">· {{ fmt(a.balance) }} left</span></span>
            <p-inputnumber [(ngModel)]="a.amount" [min]="0" [max]="a.balance" [inputStyle]="{ width: '100%' }" /></div>
        }
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="pf.note" fluid /></label>
        <div class="row-between"><strong>Total {{ fmt(payTotal()) }}</strong>
          <p-button label="Record" icon="pi pi-check" [disabled]="!payTotal() || !pf.mode || (pf.mode !== 'Cash' && !pf.reference)" (onClick)="savePay()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Apply the advance" [modal]="true" [(visible)]="applyDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p class="m0">{{ pendingAdvance?.number }} · {{ fmt(pendingAdvance?.amount) }} settles part of:</p>
        <p-select [options]="openInvoices()" optionLabel="label" optionValue="id" [(ngModel)]="applyTo" fluid appendTo="body" placeholder="Choose an invoice" />
        <div class="row right"><p-button label="Apply" [disabled]="!applyTo" (onClick)="apply()" /></div>
      </div>
    </p-dialog>

    <p-dialog [header]="f.id ? 'Edit invoice' : 'New invoice'" [modal]="true" [(visible)]="dlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '98vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="f.date" fluid /></label>
          <label class="field"><span>Due</span><input pInputText type="date" [(ngModel)]="f.due_date" fluid /></label>
        </div>
        @for (ln of f.lines; track $index; let i = $index) {
          <div class="line-row">
            <input pInputText placeholder="Description" [(ngModel)]="ln.description" />
            <p-inputnumber placeholder="Qty" [(ngModel)]="ln.qty" [min]="0" [maxFractionDigits]="2" [inputStyle]="{ width: '100%' }" />
            <p-inputnumber placeholder="Rate" [(ngModel)]="ln.rate" [min]="0" [inputStyle]="{ width: '100%' }" />
            <p-inputnumber placeholder="Tax %" [(ngModel)]="ln.tax_pct" [min]="0" [max]="100" [inputStyle]="{ width: '100%' }" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.lines.splice(i, 1)" ariaLabel="Remove line" />
          </div>
        }
        <div class="row-between">
          <p-button label="Add line" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.lines.push({ description: '', qty: 1, rate: null, tax_pct: data()?.tax_rate })" />
          <strong>{{ fmt(draftTotal()) }}</strong>
        </div>
        <label class="field"><span>Notes for the client</span><textarea pTextarea rows="2" [(ngModel)]="f.notes" fluid></textarea></label>
        <div class="row right"><p-button label="Save draft" icon="pi pi-check" (onClick)="saveManual()" [disabled]="!f.lines.length" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Send invoice" [modal]="true" [(visible)]="sendDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p class="m0">Sending issues the invoice number. It can then only be changed by a credit note.</p>
        @if (pending?.client_email) {
          <label class="check"><p-checkbox [(ngModel)]="sendEmail" [binary]="true" ariaLabel="Email it to the client" /> Email it to {{ pending.client_email }}</label>
        } @else { <p class="small muted m0">The client has no email address; share the printed invoice.</p> }
        <div class="row right"><p-button label="Send" icon="pi pi-send" (onClick)="send()" /></div>
      </div>
    </p-dialog>

    <p-dialog [header]="reasonFor === 'early' ? 'Invoice before it is due' : reasonFor === 'void' ? 'Void invoice' : reasonFor === 'receipt' ? 'Void payment' : 'Credit note'" [modal]="true"
              [(visible)]="reasonDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        @if (reasonFor === 'credit') {
          <label class="field req"><span>Amount (including tax)</span><p-inputnumber [(ngModel)]="creditAmount" [min]="0" [max]="pending?.total - pending?.credited" fluid /></label>
        }
        <label class="field req"><span>Why</span><input pInputText [(ngModel)]="reason" fluid /></label>
        <div class="row right"><p-button label="Confirm" [disabled]="!reason.trim() || (reasonFor === 'credit' && !creditAmount)" (onClick)="sendReason()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .nowrap { white-space: nowrap; }
    .line-row { display: grid; grid-template-columns: minmax(0, 3fr) 5rem 7rem 5rem auto; gap: .4rem; align-items: center; }
    @media (max-width: 640px) { .line-row { grid-template-columns: 1fr 1fr; } }
    .alloc-row { display: grid; grid-template-columns: minmax(0, 1fr) 10rem; gap: .5rem; align-items: center; }
  `,
})
export class ProjectInvoicesComponent implements OnInit {
  projectId = input.required<string>();
  changed = output<void>();
  private api = inject(Api);
  private auth = inject(AuthService);
  private confirm = inject(ConfirmationService);
  data = signal<any>(null);
  sev = INVOICE_SEV;
  kind = INVOICE_KIND;
  dlg = false; sendDlg = false; reasonDlg = false;
  f: any = { lines: [] };
  pending: any = null;
  private pendingRow: any = null;
  sendEmail = true;
  reason = ''; reasonFor: 'early' | 'void' | 'credit' | 'receipt' = 'void';
  creditAmount: number | null = null;
  rc = signal<any>(null);
  payDlg = false; applyDlg = false;
  pf: any = { allocations: [] };
  pendingAdvance: any = null;
  applyTo: string | null = null;
  openInvoices = computed(() => (this.data()?.invoices ?? [])
    .filter((i: any) => i.kind !== 'credit_note' && ['sent', 'part_paid'].includes(i.status))
    .map((i: any) => ({ ...i, label: `${i.number} · ${this.fmt(i.balance)} left` })));

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const [inv, rc] = await Promise.all([this.api.get(`/projects/${this.projectId()}/invoices`), this.api.get(`/projects/${this.projectId()}/receipts`)]);
    this.data.set(inv);
    this.rc.set(rc);
  }

  openPay() {
    this.pf = { date: new Date().toISOString().slice(0, 10), mode: 'Bank transfer', reference: '', note: '',
      allocations: this.openInvoices().map((i: any) => ({ invoice_id: i.id, number: i.number, balance: i.balance, amount: null })) };
    this.payDlg = true;
  }

  payTotal() {
    return (this.pf.allocations ?? []).reduce((a: number, x: any) => a + (x.amount || 0), 0);
  }

  async savePay() {
    const allocations = this.pf.allocations.filter((a: any) => a.amount > 0).map((a: any) => ({ invoice_id: a.invoice_id, amount: a.amount }));
    await this.api.post(`/projects/${this.projectId()}/receipts`, { date: this.pf.date, mode: this.pf.mode, reference: this.pf.reference,
      note: this.pf.note, amount: Math.round(this.payTotal() * 100) / 100, allocations }, 'Payment recorded');
    this.payDlg = false;
    await this.refresh();
  }

  askApply(a: any) {
    this.pendingAdvance = a;
    this.applyTo = null;
    this.applyDlg = true;
  }

  async apply() {
    await this.api.post(`/lead_receipts/${this.pendingAdvance.id}/apply`, { invoice_id: this.applyTo }, 'Advance applied');
    this.applyDlg = false;
    await this.refresh();
  }

  askVoidReceipt(x: any) {
    this.pending = x;
    this.open('receipt');
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  draftTotal() {
    return (this.f.lines ?? []).reduce((a: number, l: any) => a + (l.qty || 0) * (l.rate || 0) * (1 + (l.tax_pct || 0) / 100), 0);
  }

  async raise(c: any, r: any, early_reason?: string) {
    await this.api.post(`/contracts/${c.id}/schedule/${r.id}/invoice`, early_reason ? { early_reason } : {}, 'Invoice drafted');
    await this.refresh();
  }

  askEarly(c: any, r: any) {
    this.pending = c;
    this.pendingRow = r;
    this.open('early');
  }

  openNew() {
    this.f = { date: new Date().toISOString().slice(0, 10), due_date: null, notes: '',
      lines: [{ description: '', qty: 1, rate: null, tax_pct: this.data()?.tax_rate }] };
    this.dlg = true;
  }

  openEdit(i: any) {
    this.f = { id: i.id, date: i.date, due_date: i.due_date, notes: i.notes ?? '',
      lines: i.lines.map((l: any) => ({ description: l.description, qty: l.qty, rate: l.rate, tax_pct: l.tax_pct })) };
    this.dlg = true;
  }

  async saveManual() {
    const { id, ...body } = this.f;
    if (!body.due_date) delete body.due_date;
    if (id) await this.api.put(`/invoices/${id}`, body, 'Invoice saved');
    else await this.api.post(`/projects/${this.projectId()}/invoices`, body, 'Invoice drafted');
    this.dlg = false;
    await this.refresh();
  }

  askSend(i: any) {
    this.pending = i;
    this.sendEmail = !!i.client_email;
    this.sendDlg = true;
  }

  async send() {
    await this.api.post(`/invoices/${this.pending.id}/send`, { email: this.sendEmail && !!this.pending.client_email }, 'Invoice sent');
    this.sendDlg = false;
    await this.refresh();
  }

  askVoid(i: any) {
    this.pending = i;
    this.open('void');
  }

  askCredit(i: any) {
    this.pending = i;
    this.creditAmount = null;
    this.open('credit');
  }

  private open(what: 'early' | 'void' | 'credit' | 'receipt') {
    this.reasonFor = what;
    this.reason = '';
    this.reasonDlg = true;
  }

  async sendReason() {
    if (this.reasonFor === 'early') await this.raise(this.pending, this.pendingRow, this.reason);
    else if (this.reasonFor === 'void') await this.api.post(`/invoices/${this.pending.id}/void`, { reason: this.reason }, 'Invoice voided');
    else if (this.reasonFor === 'receipt') await this.api.post(`/receipts/${this.pending.id}/void`, { reason: this.reason }, 'Payment voided');
    else await this.api.post(`/invoices/${this.pending.id}/credit-note`, { amount: this.creditAmount, reason: this.reason }, 'Credit note issued');
    this.reasonDlg = false;
    await this.refresh();
  }

  remove(i: any) {
    this.confirm.confirm({ header: 'Delete this draft invoice?', icon: 'pi pi-trash', message: 'A contract payment goes back to the schedule.',
      accept: async () => { await this.api.del(`/invoices/${i.id}`, 'Deleted'); await this.refresh(); } });
  }

  private async refresh() {
    await this.load();
    this.changed.emit();
  }
}
