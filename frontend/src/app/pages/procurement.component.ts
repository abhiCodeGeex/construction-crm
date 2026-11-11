import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, label, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { ProcurementReportComponent } from './procurement-report.component';

export const PO_SEV: Record<string, 'secondary' | 'info' | 'success' | 'warn' | 'danger'> = {
  draft: 'secondary', waiting_approval: 'warn', approved: 'info', rejected: 'danger', sent: 'info', acknowledged: 'info',
  part_received: 'warn', received: 'success', closed: 'secondary', cancelled: 'secondary',
};
const VENDOR_TYPES = ['supplier', 'subcontractor', 'contractor', 'consultant'];

/** Procurement (Phase H): requests -> quotes compared side by side -> purchase orders -> deliveries -> supplier bills. */
@Component({
  selector: 'app-procurement',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, MultiSelectModule,
    SelectButtonModule, SelectModule, TableModule, TagModule, ProcurementReportComponent],
  template: `
    <div class="page-head"><div><h1>Procurement</h1>
      <p class="muted">Ask for material, compare suppliers' quotes, order, receive and match the bills. A purchase order is money ordered; only an approved bill is spent.</p></div></div>
    <p-selectbutton class="mb block" [options]="views" [(ngModel)]="view" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" />

    @switch (view) {
      @case ('report') { <app-procurement-report /> }
      @case ('requests') {
        <div class="row gap mb">
          <p-button label="New request" icon="pi pi-plus" size="small" (onClick)="openPr()" />
          @if (canWrite() && picked.length) { <p-button label="Ask for quotes ({{ picked.length }})" icon="pi pi-send" size="small" [outlined]="true" (onClick)="openRfq()" /> }
        </div>
        <p-table [value]="rows()" styleClass="p-datatable-sm" [(selection)]="picked" dataKey="id">
          <ng-template #header><tr>@if (canWrite()) { <th style="width: 3rem"></th> }<th>Request</th><th>Project</th><th>Items</th><th>Asked by</th><th>Status</th></tr></ng-template>
          <ng-template #body let-r><tr>
            @if (canWrite()) { <td>@if (r.status === 'open') { <p-tableCheckbox [value]="r" /> }</td> }
            <td>{{ r.number }}<div class="small muted">{{ r.created_at | date: 'd MMM' }} · {{ label(r.source) }}</div></td>
            <td>{{ r.project_name }}<div class="small muted">{{ r.stage_name }}</div></td>
            <td class="small">@for (l of r.lines; track l.id) { <div>{{ l.qty }} {{ l.unit || '' }} {{ l.description }}@if (l.needed_by) { <span class="muted"> · by {{ l.needed_by | date: 'd MMM' }}</span> }</div> }</td>
            <td>{{ r.requested_by_name }}</td><td><p-tag [value]="label(r.status)" [severity]="r.status === 'open' ? 'warn' : 'secondary'" /></td></tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="6" class="muted">No requests.</td></tr></ng-template>
        </p-table>
      }
      @case ('rfqs') {
        <p-table [value]="rows()" styleClass="p-datatable-sm">
          <ng-template #header><tr><th>RFQ</th><th>Project</th><th>Suppliers</th><th>Quotes due</th><th>Status</th><th></th></tr></ng-template>
          <ng-template #body let-r><tr>
            <td>{{ r.number }}</td><td>{{ r.project_name }}</td>
            <td class="small">@for (s of r.suppliers; track s.contact_id) { <div>{{ s.name }}@if (s.warning) { <span class="c-warn"> · {{ s.warning }}</span> }</div> }</td>
            <td>{{ r.due_date | date: 'd MMM' }}</td><td><p-tag [value]="r.status" severity="info" /> <span class="small muted">{{ r.quotes.length }} quote(s)</span></td>
            <td class="right nowrap">@if (canWrite() && r.status === 'draft') { <p-button label="Send" size="small" (onClick)="sendRfq(r)" /> }
              <p-button label="Compare" size="small" [text]="true" (onClick)="openCompare(r)" /></td></tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="6" class="muted">No requests for quotation.</td></tr></ng-template>
        </p-table>
      }
      @case ('pos') {
        @if (canWrite()) { <div class="row mb"><p-button label="New purchase order" icon="pi pi-plus" size="small" (onClick)="openPo()" /></div> }
        <p-table [value]="rows()" styleClass="p-datatable-sm" [paginator]="rows().length > 25" [rows]="25">
          <ng-template #header><tr><th>PO</th><th>Supplier</th><th>Project</th>@if (money()) { <th class="num">Total</th> }<th>Expected</th><th>Status</th></tr></ng-template>
          <ng-template #body let-r><tr>
            <td><a [routerLink]="['/app/purchase-orders', r.id]">{{ r.number || 'Draft' }}</a><div class="small muted">{{ label(r.source) }}</div></td>
            <td>{{ r.vendor_name }}</td><td>{{ r.project_name }}</td>
            @if (money()) { <td class="num">{{ fmt(r.total) }}</td> }
            <td [class.c-bad]="late(r)">{{ r.expected_date ? (r.expected_date | date: 'd MMM y') : '—' }}</td>
            <td><p-tag [value]="label(r.status)" [severity]="sev[r.status]" /></td></tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="6" class="muted">No purchase orders.</td></tr></ng-template>
        </p-table>
      }
      @case ('grns') {
        <p-table [value]="rows()" styleClass="p-datatable-sm">
          <ng-template #header><tr><th>Receipt</th><th>PO</th><th>Supplier</th><th>Date</th><th>Received</th><th>By</th></tr></ng-template>
          <ng-template #body let-r><tr>
            <td>{{ r.number }}@if (r.challan) { <div class="small muted">challan {{ r.challan }}</div> }</td>
            <td><a [routerLink]="['/app/purchase-orders', r.po_id]">{{ r.po_number }}</a></td><td>{{ r.vendor_name }}</td><td>{{ r.date | date: 'd MMM y' }}</td>
            <td class="small">@for (l of r.lines; track l.line_id) { <div>{{ l.accepted }} {{ l.unit || '' }} {{ l.description }}@if (l.rejected) { <span class="c-bad"> · {{ l.rejected }} rejected ({{ l.reason }})</span> }</div> }</td>
            <td>{{ r.received_by }}</td></tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="6" class="muted">No deliveries yet.</td></tr></ng-template>
        </p-table>
      }
      @case ('bills') {
        @if (pay(); as p) {
          <div class="row gap mb wrap small">Owed to suppliers: <strong>{{ fmt(p.total) }}</strong>
            @for (b of p.buckets; track b.key) { @if (b.total) { <span [class.c-bad]="b.key !== 'current'">· {{ b.label }} {{ fmt(b.total) }}</span> } }</div>
        }
        @if (canBill()) { <div class="row mb"><p-button label="Enter a bill" icon="pi pi-plus" size="small" (onClick)="openBill()" /></div> }
        <p-table [value]="rows()" styleClass="p-datatable-sm">
          <ng-template #header><tr><th>Bill</th><th>Supplier</th><th>PO</th><th class="num">Total</th><th class="num">Left to pay</th><th>Status</th><th></th></tr></ng-template>
          <ng-template #body let-b><tr>
            <td>{{ b.bill_no }}<div class="small muted">{{ b.date | date: 'd MMM' }} · due {{ b.due_date | date: 'd MMM' }}@if (b.source === 'portal') { · uploaded by the supplier }</div>
              @for (pr of b.problems; track $index) { <div class="small c-bad">{{ pr }}</div> }</td>
            <td>{{ b.vendor_name }}</td><td><a [routerLink]="['/app/purchase-orders', b.po_id]">{{ b.po_number }}</a></td>
            <td class="num">{{ fmt(b.total) }}</td><td class="num">{{ ['approved', 'part_paid'].includes(b.status) ? fmt(b.balance) : '—' }}</td>
            <td><p-tag [value]="label(b.status)" [severity]="b.status === 'on_hold' ? 'danger' : b.status === 'paid' ? 'success' : 'info'" /></td>
            <td class="right nowrap">
              @if (b.status === 'draft' && canBill()) { <p-button label="Check" size="small" (onClick)="billAct(b, 'check')" /> }
              @if (b.status === 'matched' && canBill()) { <p-button label="Approve" size="small" (onClick)="billAct(b, 'approve')" /> }
              @if (b.status === 'on_hold' && isFinance()) { <p-button label="Accept anyway" size="small" [text]="true" (onClick)="askReason(b, 'override')" /> }
              @if (['approved', 'part_paid'].includes(b.status) && auth.can('finance', 'rw')) { <p-button label="Record payment" size="small" [text]="true" (onClick)="openPay(b)" /> }
              @if (b.status !== 'void' && !b.paid && isFinance()) { <p-button label="Void" size="small" [text]="true" severity="secondary" (onClick)="askReason(b, 'void')" /> }
            </td></tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="7" class="muted">No bills.</td></tr></ng-template>
        </p-table>
      }
    }

    <!-- new purchase request -->
    <p-dialog header="Ask for material" [modal]="true" [(visible)]="prDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field req"><span>Project</span><p-select [options]="projects()" optionLabel="name" optionValue="id" [(ngModel)]="pf.project_id" (onChange)="pickProject()" [filter]="true" fluid appendTo="body" /></label>
          <label class="field req"><span>Stage</span><p-select [options]="stages()" optionLabel="name" optionValue="id" [(ngModel)]="pf.stage_id" fluid appendTo="body" /></label>
        </div>
        @for (l of pf.lines; track $index; let i = $index) {
          <div class="ln4"><input pInputText placeholder="Item" [(ngModel)]="l.description" /><p-inputnumber placeholder="Qty" [(ngModel)]="l.qty" [min]="0" [inputStyle]="{ width: '100%' }" />
            <input pInputText placeholder="Unit" [(ngModel)]="l.unit" /><input pInputText type="date" [(ngModel)]="l.needed_by" aria-label="Needed by" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="pf.lines.splice(i, 1)" ariaLabel="Remove" /></div>
        }
        <p-button label="Add item" icon="pi pi-plus" size="small" [text]="true" (onClick)="pf.lines.push({ description: '', qty: 1, unit: '', needed_by: '' })" />
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="pf.note" fluid /></label>
        <div class="row right"><p-button label="Send request" icon="pi pi-check" [disabled]="!pf.project_id || !pf.stage_id" (onClick)="savePr()" /></div>
      </div>
    </p-dialog>

    <!-- RFQ -->
    <p-dialog header="Ask suppliers for quotes" [modal]="true" [(visible)]="rfqDlg" [style]="{ width: '34rem' }">
      <div class="stack">
        <label class="field req"><span>Suppliers</span><p-multiselect [options]="vendors()" optionLabel="name" optionValue="id" [(ngModel)]="rf.supplier_ids" [filter]="true" display="chip" fluid appendTo="body" /></label>
        <label class="field"><span>Quotes due</span><input pInputText type="date" [(ngModel)]="rf.due_date" fluid /></label>
        <div class="row right"><p-button label="Create and send" icon="pi pi-send" [disabled]="!rf.supplier_ids?.length" (onClick)="saveRfq()" /></div>
      </div>
    </p-dialog>

    <!-- compare quotes -->
    <p-dialog [header]="'Compare quotes · ' + (cmp()?.rfq?.number ?? '')" [modal]="true" [(visible)]="cmpDlg" [style]="{ width: '64rem' }" [breakpoints]="{ '1000px': '100vw' }">
      @if (cmp(); as c) {
        <div class="cmp-wrap"><table class="cmp">
          <thead><tr><th>Item</th><th class="num">Library</th>@for (q of c.quotes; track q.supplier_id) { <th class="num">{{ q.supplier_name }}@if (q.late) { <div class="small c-warn">late</div> }</th> }<th>Award to</th></tr></thead>
          <tbody>
            @for (l of c.lines; track l.id) {
              <tr><td>{{ l.qty }} {{ l.unit || '' }} {{ l.description }}</td>
                <td class="num small">{{ l.library_rate ? fmt(l.library_rate) : '—' }}@if (l.last_actual) { <div class="muted">last {{ fmt(l.last_actual) }}</div> }</td>
                @for (q of c.quotes; track q.supplier_id) { <td class="num" [class.best]="offer(l, q.supplier_id)?.lowest">{{ offer(l, q.supplier_id) ? fmt(offer(l, q.supplier_id).rate) : '—' }}</td> }
                <td><p-select [options]="offerOpts(l)" optionLabel="label" optionValue="value" [(ngModel)]="awardPick[l.id]" placeholder="—" appendTo="body" /></td></tr>
            }
            <tr class="tot"><td>Total before tax</td><td></td>@for (q of c.quotes; track q.supplier_id) { <td class="num" [class.best]="q.lowest">{{ fmt(q.subtotal) }}<div class="small muted">{{ q.delivery_days }} days</div></td> }<td></td></tr>
          </tbody>
        </table></div>
        @if (c.rfq.status !== 'awarded' && canWrite()) {
          <div class="row gap mt wrap">
            <p-select [options]="supplierOpts()" optionLabel="label" optionValue="value" [(ngModel)]="quoteFor" placeholder="Enter a quote for…" appendTo="body" (onChange)="startQuote()" />
            <input pInputText class="grow" [(ngModel)]="awardReason" placeholder="Reason, if not the lowest" />
            <p-button label="Award" icon="pi pi-check" [disabled]="!awardCount()" (onClick)="award()" />
          </div>
          @if (quoteFor) {
            <div class="stack mt">
              @for (l of c.lines; track l.id) { <div class="row gap"><span class="grow small">{{ l.description }}</span><p-inputnumber [(ngModel)]="qf.rates[l.id]" [min]="0" placeholder="Rate" /></div> }
              <div class="row gap"><p-inputnumber [(ngModel)]="qf.tax_pct" placeholder="Tax %" /><p-inputnumber [(ngModel)]="qf.delivery_days" placeholder="Delivery days" />
                <p-button label="Save quote" size="small" (onClick)="saveQuote()" /></div>
            </div>
          }
        }
      }
    </p-dialog>

    <!-- direct PO -->
    <p-dialog header="New purchase order" [modal]="true" [(visible)]="poDlg" [style]="{ width: '50rem' }" [breakpoints]="{ '820px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field req"><span>Project</span><p-select [options]="projects()" optionLabel="name" optionValue="id" [(ngModel)]="of.project_id" (onChange)="pickProject(of.project_id)" [filter]="true" fluid appendTo="body" /></label>
          <label class="field req"><span>Supplier</span><p-select [options]="vendors()" optionLabel="name" optionValue="id" [(ngModel)]="of.vendor_id" [filter]="true" fluid appendTo="body" /></label>
        </div>
        @for (l of of.lines; track $index; let i = $index) {
          <div class="ln6"><input pInputText placeholder="Item" [(ngModel)]="l.description" />
            <p-select [options]="stages()" optionLabel="name" optionValue="id" [(ngModel)]="l.stage_id" placeholder="Stage" appendTo="body" />
            <p-inputnumber placeholder="Qty" [(ngModel)]="l.qty" [min]="0" [inputStyle]="{ width: '100%' }" /><input pInputText placeholder="Unit" [(ngModel)]="l.unit" />
            <p-inputnumber placeholder="Rate" [(ngModel)]="l.unit_cost" [min]="0" [inputStyle]="{ width: '100%' }" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="of.lines.splice(i, 1)" ariaLabel="Remove" /></div>
        }
        <p-button label="Add line" icon="pi pi-plus" size="small" [text]="true" (onClick)="of.lines.push({ description: '', stage_id: null, qty: 1, unit: '', unit_cost: null })" />
        <div class="grid2">
          <label class="field"><span>Expected delivery</span><input pInputText type="date" [(ngModel)]="of.expected_date" fluid /></label>
          <label class="field"><span>Why no quotes? (needed above the approval limit)</span><input pInputText [(ngModel)]="of.direct_reason" fluid /></label>
        </div>
        <div class="row right"><p-button label="Save draft" icon="pi pi-check" [disabled]="!of.project_id || !of.vendor_id" (onClick)="savePo()" /></div>
      </div>
    </p-dialog>

    <!-- bill -->
    <p-dialog header="Enter a supplier bill" [modal]="true" [(visible)]="billDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '100vw' }">
      <div class="stack">
        <label class="field req"><span>Purchase order</span><p-select [options]="billablePos()" optionLabel="label" optionValue="id" [(ngModel)]="bf.po_id" (onChange)="pickBillPo()" [filter]="true" fluid appendTo="body" /></label>
        <div class="grid3">
          <label class="field req"><span>Bill number</span><input pInputText [(ngModel)]="bf.bill_no" fluid /></label>
          <label class="field"><span>Bill date</span><input pInputText type="date" [(ngModel)]="bf.date" fluid /></label>
          <label class="field"><span>Due</span><input pInputText type="date" [(ngModel)]="bf.due_date" fluid /></label>
        </div>
        @for (l of bf.lines; track l.line_id) {
          <div class="row gap"><span class="grow small">{{ l.description }} <span class="muted">· received {{ l.free }}</span></span>
            <p-inputnumber [(ngModel)]="l.qty" [min]="0" placeholder="Qty" [inputStyle]="{ width: '6rem' }" /><p-inputnumber [(ngModel)]="l.rate" [min]="0" placeholder="Rate" [inputStyle]="{ width: '7rem' }" /></div>
        }
        <div class="row right"><p-button label="Save and match" icon="pi pi-check" [disabled]="!bf.po_id || !bf.bill_no" (onClick)="saveBill()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Record a payment to the supplier" [modal]="true" [(visible)]="payDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p class="m0 small">{{ target?.bill_no }} · {{ target?.vendor_name }} · {{ fmt(target?.balance) }} left</p>
        <div class="grid2"><label class="field"><span>Amount</span><p-inputnumber [(ngModel)]="pay_.amount" [min]="0" fluid /></label>
          <label class="field"><span>Mode</span><p-select [options]="modes" [(ngModel)]="pay_.mode" fluid appendTo="body" /></label></div>
        <label class="field"><span>Reference</span><input pInputText [(ngModel)]="pay_.reference" fluid /></label>
        <div class="row right"><p-button label="Record" [disabled]="!pay_.amount" (onClick)="savePay()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Why?" [modal]="true" [(visible)]="reasonDlg" [style]="{ width: '26rem' }">
      <div class="stack"><input pInputText [(ngModel)]="reason" fluid aria-label="Reason" />
        <div class="row right"><p-button label="Confirm" [disabled]="!reason.trim()" (onClick)="sendReason()" /></div></div>
    </p-dialog>
  `,
  styles: `
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .nowrap { white-space: nowrap; }
    .ln4 { display: grid; grid-template-columns: minmax(0, 2fr) 6rem 5rem 9rem auto; gap: .35rem; align-items: center; }
    .ln6 { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1.2fr) 5.5rem 4.5rem 7rem auto; gap: .35rem; align-items: center; }
    @media (max-width: 760px) { .ln4, .ln6 { grid-template-columns: 1fr 1fr; } }
    .cmp-wrap { overflow-x: auto; }
    .cmp { width: 100%; border-collapse: collapse; }
    .cmp th, .cmp td { border-bottom: 1px solid var(--border); padding: .4rem; }
    .cmp .best { background: color-mix(in srgb, var(--good, #16a34a) 14%, transparent); font-weight: 600; }
    .cmp .tot td { font-weight: 600; }
  `,
})
export class ProcurementComponent implements OnInit {
  tab = input<string>();
  auth = inject(AuthService);
  private api = inject(Api);
  views = [{ label: 'Requests', value: 'requests' }, { label: 'Quotes', value: 'rfqs' }, { label: 'Purchase orders', value: 'pos' },
    { label: 'Deliveries', value: 'grns' }, { label: 'Bills', value: 'bills' }, { label: 'Report', value: 'report' }];
  view = 'requests';
  rows = signal<any[]>([]);
  pay = signal<any>(null);
  projects = signal<any[]>([]);
  stages = signal<any[]>([]);
  contacts = signal<any[]>([]);
  cmp = signal<any>(null);
  allPos = signal<any[]>([]);
  picked: any[] = [];
  sev = PO_SEV;
  label = label;
  modes = ['Bank transfer', 'UPI', 'Cheque', 'Cash', 'Card'];
  prDlg = false; rfqDlg = false; cmpDlg = false; poDlg = false; billDlg = false; payDlg = false; reasonDlg = false;
  pf: any = {}; rf: any = {}; of: any = {}; bf: any = {}; qf: any = { rates: {} }; pay_: any = {};
  awardPick: Record<string, string> = {};
  awardReason = '';
  quoteFor: string | null = null;
  target: any = null;
  reason = ''; reasonFor = '';

  canWrite = () => this.auth.can('procurement', 'rw');
  canBill = () => this.auth.can('procurement', 'rw') || this.auth.can('finance', 'rw');
  isFinance = () => ['owner', 'accounts'].includes(this.auth.user()?.role ?? '');
  money = () => this.auth.user()?.role !== 'site';
  vendors = computed(() => this.contacts().filter((c: any) => (c.types ?? []).some((t: string) => VENDOR_TYPES.includes(t))));
  billablePos = computed(() => this.allPos().filter((p: any) => ['sent', 'acknowledged', 'part_received', 'received', 'approved'].includes(p.status))
    .map((p: any) => ({ ...p, label: `${p.number} · ${p.vendor_name} · ${p.project_name}` })));
  supplierOpts = computed(() => (this.cmp()?.rfq?.suppliers ?? []).map((s: any) => ({ value: s.contact_id, label: s.name })));

  async ngOnInit() {
    if (this.tab()) this.view = this.tab()!;
    await this.load();
    this.projects.set(await this.api.get('/projects'));
    if (this.auth.can('contacts')) this.contacts.set(await this.api.get('/contacts'));
  }

  async load() {
    if (this.view === 'report') return;
    const url = { requests: '/purchase-requests?status=open,quoting', rfqs: '/rfqs', pos: '/purchase-orders', grns: '/goods-receipts', bills: '/vendor-bills' }[this.view]!;
    this.rows.set(await this.api.get(url));
    this.picked = [];
    if (this.view === 'bills' && this.auth.can('finance')) this.pay.set(await this.api.get('/finance/payables'));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  late(r: any) {
    return r.expected_date && r.expected_date < new Date().toISOString().slice(0, 10) && !['received', 'closed', 'cancelled'].includes(r.status);
  }

  async pickProject(id = this.pf.project_id) {
    const p = await this.api.get(`/projects/${id}`);
    this.stages.set(p.stages.map((s: any) => ({ id: s.id, name: s.name })));
  }

  openPr() {
    this.pf = { project_id: null, stage_id: null, note: '', lines: [{ description: '', qty: 1, unit: '', needed_by: '' }] };
    this.prDlg = true;
  }

  async savePr() {
    const lines = this.pf.lines.filter((l: any) => l.description?.trim() && l.qty).map((l: any) => ({ ...l, needed_by: l.needed_by || null }));
    await this.api.post(`/projects/${this.pf.project_id}/purchase-requests`, { stage_id: this.pf.stage_id, note: this.pf.note, lines }, 'Request sent');
    this.prDlg = false;
    await this.load();
  }

  openRfq() {
    this.rf = { supplier_ids: [], due_date: new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10) };
    this.rfqDlg = true;
  }

  async saveRfq() {
    const r = await this.api.post('/rfqs', { project_id: this.picked[0].project_id, request_ids: this.picked.map((x) => x.id), ...this.rf });
    await this.api.post(`/rfqs/${r.id}/send`, {}, 'Sent to the suppliers');
    this.rfqDlg = false;
    this.view = 'rfqs';
    await this.load();
  }

  async sendRfq(r: any) {
    await this.api.post(`/rfqs/${r.id}/send`, {}, 'Sent');
    await this.load();
  }

  async openCompare(r: any) {
    this.cmp.set(await this.api.get(`/rfqs/${r.id}/compare`));
    this.awardPick = {};
    this.awardReason = '';
    this.quoteFor = null;
    this.cmpDlg = true;
  }

  offer(l: any, sid: string) {
    return l.offers.find((o: any) => o.supplier_id === sid);
  }

  offerOpts(l: any) {
    return l.offers.map((o: any) => ({ value: o.supplier_id, label: `${this.cmp().quotes.find((q: any) => q.supplier_id === o.supplier_id)?.supplier_name} · ${this.fmt(o.rate)}` }));
  }

  awardCount() {
    return Object.values(this.awardPick).filter(Boolean).length;
  }

  startQuote() {
    const q = (this.cmp().rfq.quotes ?? []).find((x: any) => x.supplier_id === this.quoteFor);
    this.qf = { rates: { ...(q?.rates ?? {}) }, tax_pct: q?.tax_pct ?? null, delivery_days: q?.delivery_days ?? null };
  }

  async saveQuote() {
    const lines = Object.entries(this.qf.rates).filter(([, v]) => v != null).map(([line_id, rate]) => ({ line_id, rate }));
    await this.api.post(`/rfqs/${this.cmp().rfq.id}/quotes`, { supplier_id: this.quoteFor, lines, tax_pct: this.qf.tax_pct, delivery_days: this.qf.delivery_days }, 'Quote saved');
    this.quoteFor = null;
    this.cmp.set(await this.api.get(`/rfqs/${this.cmp().rfq.id}/compare`));
  }

  async award() {
    const lines = Object.entries(this.awardPick).filter(([, s]) => s).map(([line_id, supplier_id]) => ({ line_id, supplier_id }));
    await this.api.post(`/rfqs/${this.cmp().rfq.id}/award`, { lines, reason: this.awardReason }, 'Draft purchase orders created');
    this.cmpDlg = false;
    this.view = 'pos';
    await this.load();
  }

  openPo() {
    this.of = { project_id: null, vendor_id: null, expected_date: '', direct_reason: '', lines: [{ description: '', stage_id: null, qty: 1, unit: '', unit_cost: null }] };
    this.poDlg = true;
  }

  async savePo() {
    const body = { ...this.of, expected_date: this.of.expected_date || null, lines: this.of.lines.filter((l: any) => l.description?.trim()) };
    const po = await this.api.post('/purchase-orders', body, 'Draft saved');
    this.poDlg = false;
    window.location.href = `/app/purchase-orders/${po.id}`;
  }

  async openBill() {
    this.allPos.set(await this.api.get('/purchase-orders'));
    this.bf = { po_id: null, bill_no: '', date: new Date().toISOString().slice(0, 10), due_date: '', lines: [] };
    this.billDlg = true;
  }

  pickBillPo() {
    const po = this.allPos().find((p: any) => p.id === this.bf.po_id);
    this.bf.lines = (po?.lines ?? []).map((l: any) => ({ line_id: l.id, description: l.description, free: l.accepted_qty - l.billed_qty,
      qty: Math.max(0, l.accepted_qty - l.billed_qty), rate: l.unit_cost }));
  }

  async saveBill() {
    const lines = this.bf.lines.filter((l: any) => l.qty > 0).map((l: any) => ({ line_id: l.line_id, qty: l.qty, rate: l.rate }));
    const b = await this.api.post('/vendor-bills', { ...this.bf, due_date: this.bf.due_date || null, lines });
    this.billDlg = false;
    this.view = 'bills';
    await this.load();
    if (b.status === 'on_hold') this.api.toastError({ error: { error: `On hold: ${b.problems[0]}` } } as any);
  }

  async billAct(b: any, what: string) {
    await this.api.post(`/vendor-bills/${b.id}/${what}`, {}, what === 'approve' ? 'Approved — recorded as cost' : 'Checked');
    await this.load();
  }

  openPay(b: any) {
    this.target = b;
    this.pay_ = { amount: b.balance, mode: 'Bank transfer', reference: '' };
    this.payDlg = true;
  }

  async savePay() {
    await this.api.post('/vendor-payments', { ...this.pay_, allocations: [{ bill_id: this.target.id, amount: this.pay_.amount }] }, 'Payment recorded');
    this.payDlg = false;
    await this.load();
  }

  askReason(b: any, what: string) {
    this.target = b;
    this.reasonFor = what;
    this.reason = '';
    this.reasonDlg = true;
  }

  async sendReason() {
    await this.api.post(`/vendor-bills/${this.target.id}/${this.reasonFor}`, { reason: this.reason }, 'Done');
    this.reasonDlg = false;
    await this.load();
  }
}
