import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { INVOICE_KIND, INVOICE_SEV } from './projects/project-invoices.component';

const COST_SEV: Record<string, 'secondary' | 'success' | 'danger' | 'warn'> = {
  draft: 'secondary', submitted: 'warn', approved: 'success', rejected: 'danger', void: 'secondary',
};

/** Finance (Phase E). Every project's costs (waiting approvals first) and invoices in one place. Costs are recorded,
 *  approved and voided on each project's Money tab, where the stage budget is in view. */
@Component({
  selector: 'app-finance',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectButtonModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Finance</h1>
        <p class="muted">Costs and invoices across your projects. Record costs and raise invoices on the project's Money tab, next to its budgets and payment schedule.</p>
      </div>
    </div>
    <p-selectbutton class="mb block" [options]="views" [(ngModel)]="view" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" />
    @if (view === 'gst') {
      <div class="row gap wrap mb">
        <label class="field"><span>Month</span><input pInputText type="month" [(ngModel)]="month" (change)="load()" /></label>
      </div>
      @if (gst(); as gs) {
        @if (!gs.enabled) { <p class="small muted">GST split is off (Settings → Currency, tax & numbering); tax is shown under its single label.</p> }
        <div class="stats">
          <div class="stat-card"><div><small>Taxable value</small><strong>{{ fmt(gs.totals.taxable) }}</strong></div></div>
          <div class="stat-card"><div><small>CGST</small><strong>{{ fmt(gs.totals.cgst) }}</strong></div></div>
          <div class="stat-card"><div><small>SGST</small><strong>{{ fmt(gs.totals.sgst) }}</strong></div></div>
          <div class="stat-card"><div><small>IGST</small><strong>{{ fmt(gs.totals.igst) }}</strong></div></div>
        </div>
        <div class="grid2 top">
          <div><h3 class="mt0">Invoices and credit notes · {{ gs.totals.invoices }} / {{ gs.totals.credit_notes }}</h3>
            <p-table [value]="gs.rows" styleClass="p-datatable-sm" [paginator]="gs.rows.length > 20" [rows]="20">
              <ng-template #header><tr><th>Number</th><th>Client</th><th>Place of supply</th><th class="num">Taxable</th><th class="num">Tax</th></tr></ng-template>
              <ng-template #body let-x><tr><td><a [routerLink]="['/app/invoices', x.id]">{{ x.number }}</a><div class="small muted">{{ x.date | date: 'd MMM' }}</div></td>
                <td>{{ x.client }}@if (x.client_gstin) { <div class="small muted">{{ x.client_gstin }}</div> }</td><td class="small">{{ x.place_of_supply || '—' }}</td>
                <td class="num">{{ fmt(x.taxable) }}</td><td class="num">{{ fmt(x.cgst + x.sgst + x.igst) }}</td></tr></ng-template>
              <ng-template #emptymessage><tr><td colspan="5" class="muted">No invoices issued this month.</td></tr></ng-template>
            </p-table></div>
          <div><h3 class="mt0">By HSN / SAC</h3>
            <p-table [value]="gs.by_hsn" styleClass="p-datatable-sm">
              <ng-template #header><tr><th>Code</th><th class="num">Taxable</th><th class="num">Tax</th></tr></ng-template>
              <ng-template #body let-h><tr><td>{{ h.hsn }}</td><td class="num">{{ fmt(h.taxable) }}</td><td class="num">{{ fmt(h.tax) }}</td></tr></ng-template>
            </p-table></div>
        </div>
      }
    } @else if (view === 'petty') {
      @if (petty(); as pc) {
        <div class="row-between mb">
          <span class="muted small">Cash handed to staff for site expenses. An expense marked "paid from petty cash" comes off the holder's balance; a rejected one goes back on.</span>
          @if (pc.can_write) { <p-button label="Give or take back cash" icon="pi pi-plus" size="small" (onClick)="openPetty()" /> }
        </div>
        <p-table [value]="pc.holders" styleClass="p-datatable-sm mb">
          <ng-template #header><tr><th>Holder</th><th class="num">Given</th><th class="num">Returned</th><th class="num">Spent</th><th class="num">Balance</th></tr></ng-template>
          <ng-template #body let-h><tr><td>{{ h.holder_name }}</td><td class="num">{{ fmt(h.given) }}</td><td class="num">{{ fmt(h.returned) }}</td>
            <td class="num">{{ fmt(h.spent) }}</td><td class="num"><strong [class.c-bad]="h.balance < 0">{{ fmt(h.balance) }}</strong></td></tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="5" class="muted">No petty cash given yet.</td></tr></ng-template>
        </p-table>
        <div class="grid2 top">
          <div><h3 class="mt0">Cash given and returned</h3>
            <p-table [value]="pc.entries" styleClass="p-datatable-sm" [paginator]="pc.entries.length > 15" [rows]="15">
              <ng-template #body let-e><tr [class.muted]="e.status === 'void'"><td>{{ e.date | date: 'd MMM y' }}</td><td>{{ e.holder_name }}</td>
                <td>{{ pc.kinds[e.kind] }}@if (e.note) { <div class="small muted">{{ e.note }}</div> }@if (e.status === 'void') { <div class="small c-bad">Void: {{ e.void_reason }}</div> }</td>
                <td class="num">{{ fmt(e.amount) }}</td>
                <td class="right">@if (pc.can_write && e.status !== 'void') { <p-button label="Void" size="small" [text]="true" severity="secondary" (onClick)="askVoidPetty(e)" /> }</td></tr></ng-template>
              <ng-template #emptymessage><tr><td colspan="5" class="muted">Nothing yet.</td></tr></ng-template>
            </p-table></div>
          <div><h3 class="mt0">Paid from petty cash</h3>
            <p-table [value]="pc.spends" styleClass="p-datatable-sm" [paginator]="pc.spends.length > 15" [rows]="15">
              <ng-template #body let-c><tr><td>{{ c.date | date: 'd MMM y' }}</td><td>{{ c.created_by_name }}</td>
                <td><a [routerLink]="['/app/projects', c.project_id]" [queryParams]="{ tab: 'money' }">{{ c.description }}</a><div class="small muted">{{ c.project_name }}</div></td>
                <td class="num">{{ fmt(c.amount + (c.tax || 0)) }}</td><td><p-tag [value]="c.status" [severity]="sev[c.status]" /></td></tr></ng-template>
              <ng-template #emptymessage><tr><td colspan="5" class="muted">Nothing yet.</td></tr></ng-template>
            </p-table></div>
        </div>
      }
    } @else if (view === 'receivables') {
      @if (recv(); as r) {
        <div class="stats">
          @for (b of r.buckets; track b.key) {
            <div class="stat-card"><div><small>{{ b.label }}</small><strong [class.c-bad]="b.key !== 'current' && b.total > 0">{{ fmt(b.total) }}</strong></div></div>
          }
        </div>
        <div class="grid2">
          <div>
            <h3 class="mt0">By client</h3>
            <p-table [value]="r.by_client" styleClass="p-datatable-sm">
              <ng-template #header><tr><th>Client</th><th class="num">Owed</th><th class="num">Oldest</th></tr></ng-template>
              <ng-template #body let-c><tr><td>{{ c.client }}</td><td class="num">{{ fmt(c.balance) }}</td>
                <td class="num" [class.c-bad]="c.oldest_days > 0">{{ c.oldest_days > 0 ? c.oldest_days + ' days late' : 'not due' }}</td></tr></ng-template>
              <ng-template #emptymessage><tr><td colspan="3" class="muted">Nothing owed.</td></tr></ng-template>
            </p-table>
          </div>
          <div>
            <h3 class="mt0">Open invoices · {{ fmt(r.total) }}</h3>
            <p-table [value]="r.rows" styleClass="p-datatable-sm" [paginator]="r.rows.length > 15" [rows]="15">
              <ng-template #header><tr><th>Invoice</th><th>Due</th><th class="num">Left to pay</th></tr></ng-template>
              <ng-template #body let-i><tr>
                <td><a [routerLink]="['/app/invoices', i.id]">{{ i.number }}</a><div class="small muted">{{ i.client_name }} · {{ i.project_code }}</div></td>
                <td [class.c-bad]="i.days_late > 0">{{ i.due_date | date: 'd MMM y' }}@if (i.days_late > 0) { <div class="small">{{ i.days_late }} days late</div> }</td>
                <td class="num">{{ fmt(i.balance) }}</td></tr></ng-template>
            </p-table>
          </div>
        </div>
      }
    } @else if (view === 'invoices') {
      <div class="row gap wrap mb">
        <p-selectbutton [options]="invStatuses" [(ngModel)]="invStatus" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" />
        <span class="muted small grow right">{{ invoices().length }} · balance {{ fmt(balance()) }}</span>
      </div>
      <p-table [value]="invoices()" styleClass="p-datatable-sm" [paginator]="invoices().length > 25" [rows]="25">
        <ng-template #header><tr><th>Number</th><th>Project</th><th>Client</th><th>Due</th><th class="num">Total</th><th class="num">Balance</th><th>Status</th></tr></ng-template>
        <ng-template #body let-i>
          <tr>
            <td><a [routerLink]="['/app/invoices', i.id]">{{ i.number || 'Draft' }}</a><div class="small muted">{{ kind[i.kind] }}</div></td>
            <td>{{ i.project_code }} {{ i.project_name }}</td>
            <td>{{ i.client_name }}</td>
            <td [class.c-bad]="i.overdue">{{ i.due_date ? (i.due_date | date: 'd MMM y') : '—' }}</td>
            <td class="num">{{ fmt(i.total) }}</td>
            <td class="num">{{ i.kind === 'credit_note' || i.status === 'void' ? '—' : fmt(i.balance) }}</td>
            <td><p-tag [value]="i.overdue ? 'overdue' : i.status" [severity]="i.overdue ? 'danger' : isev[i.status]" /></td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="7" class="muted">Nothing here.</td></tr></ng-template>
      </p-table>
    } @else {
    <div class="row gap wrap mb">
      <p-selectbutton [options]="statuses" [(ngModel)]="status" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" />
      <p-select [options]="categories()" [(ngModel)]="category" [showClear]="true" placeholder="Any category" (onChange)="load()" />
      <span class="muted small grow right">{{ rows().length }} cost(s) · {{ fmt(total()) }}</span>
    </div>
    <p-table [value]="rows()" styleClass="p-datatable-sm" [paginator]="rows().length > 25" [rows]="25">
      <ng-template #header><tr><th>Date</th><th>Project</th><th>What</th><th>Category</th><th class="num">Amount</th><th>Status</th></tr></ng-template>
      <ng-template #body let-c>
        <tr>
          <td>{{ c.date | date: 'd MMM y' }}</td>
          <td><a [routerLink]="['/app/projects', c.project_id]" [queryParams]="{ tab: 'money' }">{{ c.project_code }} {{ c.project_name }}</a>
            <div class="small muted">{{ c.stage_name }}</div></td>
          <td>{{ c.description }}<div class="small muted">@if (c.vendor_name) { {{ c.vendor_name }} · } {{ c.created_by_name }}</div></td>
          <td>{{ c.category }}</td>
          <td class="num">{{ fmt(c.amount) }}</td>
          <td><p-tag [value]="c.status" [severity]="sev[c.status]" /></td>
        </tr>
      </ng-template>
      <ng-template #emptymessage><tr><td colspan="6" class="muted">Nothing here.</td></tr></ng-template>
    </p-table>
    }

    <p-dialog header="Petty cash" [modal]="true" [(visible)]="pettyDlg" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        <p-selectbutton [options]="pettyKinds" [(ngModel)]="pf.kind" optionLabel="label" optionValue="value" [allowEmpty]="false" />
        <label class="field req"><span>Staff member</span><p-select [options]="petty()?.staff ?? []" optionLabel="name" optionValue="id" [(ngModel)]="pf.holder_id" [filter]="true" fluid appendTo="body" /></label>
        <div class="grid2">
          <label class="field req"><span>Amount</span><p-inputnumber [(ngModel)]="pf.amount" [min]="0" fluid /></label>
          <label class="field req"><span>Date</span><input pInputText type="date" [(ngModel)]="pf.date" fluid /></label>
        </div>
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="pf.note" fluid /></label>
        <div class="row right"><p-button label="Save" icon="pi pi-check" [disabled]="!pf.holder_id || !pf.amount" (onClick)="savePetty()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Void this entry" [modal]="true" [(visible)]="voidDlg" [style]="{ width: '26rem' }">
      <div class="stack">
        <label class="field req"><span>Why</span><input pInputText [(ngModel)]="voidReason" fluid /></label>
        <div class="row right"><p-button label="Void" severity="danger" [disabled]="!voidReason.trim()" (onClick)="voidPetty()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.num { text-align: right; font-variant-numeric: tabular-nums; }`,
})
export class FinanceComponent implements OnInit {
  private api = inject(Api);
  private auth = inject(AuthService);
  rows = signal<any[]>([]);
  categories = signal<string[]>([]);
  sev = COST_SEV;
  statuses = [{ label: 'Waiting approval', value: 'submitted' }, { label: 'Approved', value: 'approved' },
    { label: 'Drafts', value: 'draft' }, { label: 'Rejected', value: 'rejected' }, { label: 'Void', value: 'void' }, { label: 'All', value: '' }];
  status = 'submitted';
  views = [{ label: 'Costs', value: 'costs' }, { label: 'Invoices', value: 'invoices' }, { label: 'Receivables', value: 'receivables' }];
  view = 'costs';
  invoices = signal<any[]>([]);
  recv = signal<any>(null);
  invStatuses = [{ label: 'Unpaid', value: 'unpaid' }, { label: 'Drafts', value: 'draft' }, { label: 'Paid', value: 'paid' },
    { label: 'Void', value: 'void' }, { label: 'All', value: '' }];
  invStatus = 'unpaid';
  kind = INVOICE_KIND;
  isev = INVOICE_SEV;
  category: string | null = null;

  // Phase I: GST summary and petty cash
  gst = signal<any>(null);
  petty = signal<any>(null);
  month = new Date().toISOString().slice(0, 7);
  pettyDlg = false; voidDlg = false;
  pf: any = {};
  voidEntry: any = null;
  voidReason = '';
  pettyKinds = [{ label: 'Give cash', value: 'advance' }, { label: 'Take back cash', value: 'return' }];

  async ngOnInit() {
    const role = this.auth.user()?.role;
    if (role === 'owner' || role === 'accounts') this.views = [...this.views, { label: 'GST', value: 'gst' }];
    this.views = [...this.views, { label: 'Petty cash', value: 'petty' }];
    const tab = new URLSearchParams(location.search).get('tab');
    if (tab && this.views.some((v) => v.value === tab)) this.view = tab;
    await this.load();
  }

  openPetty() {
    this.pf = { kind: 'advance', holder_id: null, amount: null, date: new Date().toISOString().slice(0, 10), mode: 'Cash', note: '' };
    this.pettyDlg = true;
  }

  async savePetty() {
    await this.api.post('/finance/petty-cash', this.pf, this.pf.kind === 'advance' ? 'Cash given' : 'Cash taken back');
    this.pettyDlg = false;
    await this.load();
  }

  askVoidPetty(e: any) {
    this.voidEntry = e;
    this.voidReason = '';
    this.voidDlg = true;
  }

  async voidPetty() {
    await this.api.post(`/petty-cash/${this.voidEntry.id}/void`, { reason: this.voidReason }, 'Voided');
    this.voidDlg = false;
    await this.load();
  }

  async load() {
    if (this.view === 'gst') {
      this.gst.set(await this.api.get(`/finance/gst?month=${this.month}`));
      return;
    }
    if (this.view === 'petty') {
      this.petty.set(await this.api.get('/finance/petty-cash'));
      return;
    }
    if (this.view === 'receivables') {
      this.recv.set(await this.api.get('/finance/receivables'));
      return;
    }
    if (this.view === 'invoices') {
      this.invoices.set(await this.api.get(`/invoices${this.invStatus ? '?status=' + this.invStatus : ''}`));
      return;
    }
    const q = new URLSearchParams();
    if (this.status) q.set('status', this.status);
    if (this.category) q.set('category', this.category);
    const r = await this.api.get(`/finance/costs?${q}`);
    this.rows.set(r.costs);
    this.categories.set(r.categories);
  }

  balance() {
    return this.invoices().filter((i) => i.kind !== 'credit_note' && i.status !== 'void').reduce((a, i) => a + (i.balance || 0), 0);
  }

  total() {
    return this.rows().reduce((a, c) => a + (c.amount || 0), 0);
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }
}
