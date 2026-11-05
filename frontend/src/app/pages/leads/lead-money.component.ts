import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

const EST_SEVERITY: Record<string, 'info' | 'success' | 'warn' | 'danger' | 'secondary'> = {
  draft: 'secondary', pending_approval: 'warn', approved: 'success', refused: 'danger',
};

/** Lead step 5a (C+2) and pre-sales money (C+3): internal estimates with approval, rate library, expenses, receipts. */
@Component({
  selector: 'app-lead-money',
  imports: [FormsModule, DatePipe, DecimalPipe, ButtonModule, CardModule, DialogModule, InputNumberModule, InputTextModule, MessageModule,
    SelectModule, TableModule, TagModule],
  template: `
    <div class="stack">
      @if (auth.can('proposals')) {
        <p-card>
          <ng-template #title><div class="row-between"><span>Estimates (internal — never shown to the client)</span>
            <span class="row gap">
              <p-button label="Rate library" icon="pi pi-book" size="small" [text]="true" (onClick)="openRates()" />
              @if (canEst()) { <p-button label="New estimate" icon="pi pi-plus" size="small" (onClick)="newEstimate()" /> }</span></div></ng-template>
          <p-table [value]="estimates()" size="small">
            <ng-template #header><tr><th>Estimate</th><th>Status</th><th class="right">Cost</th><th class="right">Total</th><th class="right">Margin</th><th></th></tr></ng-template>
            <ng-template #body let-e><tr>
              <td><strong>{{ e.number }}</strong> v{{ e.version }} · {{ e.title }}<br /><small class="muted">{{ e.lines.length }} line(s)</small></td>
              <td><p-tag [value]="label(e.status)" [severity]="sev[e.status]" />
                @if (e.approval?.reasons?.length && e.status !== 'approved') { <br /><small class="muted">{{ e.approval.reasons.join('; ') }}</small> }
                @if (e.status === 'refused') { <br /><small class="c-bad">{{ e.approval.note }}</small> }</td>
              <td class="right">{{ fmt(e.totals?.cost) }}</td><td class="right"><strong>{{ fmt(e.totals?.total) }}</strong></td>
              <td class="right" [class.c-bad]="e.totals?.margin_pct < limits().min_margin_pct">{{ e.totals?.margin_pct | number: '1.1-1' }}%</td>
              <td class="right nowrap">
                <p-button [icon]="canEditEst(e) ? 'pi pi-pencil' : 'pi pi-eye'" [text]="true" (onClick)="openEstimate(e)" />
                @if (canEst()) { <p-button icon="pi pi-copy" [text]="true" ariaLabel="New version from this" (onClick)="newEstimate(e)" /> }
                @if (e.status === 'pending_approval' && isApprover()) {
                  <p-button label="Approve" size="small" [text]="true" severity="success" (onClick)="decide(e, true)" />
                  <p-button label="Refuse" size="small" [text]="true" severity="danger" (onClick)="refuse = { e, note: '' }; refuseDlg = true" /> }
              </td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="6" class="muted center">No estimate yet</td></tr></ng-template>
          </p-table>
        </p-card>
      }

      <div class="grid2 top">
        <p-card>
          <ng-template #title><div class="row-between"><span>Pre-sales spend</span><strong>{{ fmt(money_()?.totals?.spent) }}</strong></div></ng-template>
          <p-table [value]="money_()?.expenses ?? []" size="small">
            <ng-template #body let-x><tr><td>{{ x.category }}<br /><small class="muted">{{ x.note }}</small></td><td><small>{{ x.date | date: 'd MMM' }}</small></td>
              <td class="right">{{ fmt(x.amount) }}</td>
              <td class="right">@if (editable() && !x.visit_id) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="delExpense(x)" /> }
                @if (x.visit_id) { <small class="muted">visit</small> }</td></tr></ng-template>
            <ng-template #emptymessage><tr><td class="muted center">Nothing spent yet</td></tr></ng-template>
          </p-table>
          @if (editable()) {
            <div class="row gap wrap mt-xs">
              <p-select [options]="money_()?.categories ?? []" [(ngModel)]="xf.category" placeholder="Category" appendTo="body" />
              <p-inputnumber [(ngModel)]="xf.amount" [min]="0" placeholder="Amount" [inputStyle]="{ width: '7rem' }" />
              <input pInputText type="date" [(ngModel)]="xf.date" />
              <input pInputText [(ngModel)]="xf.note" placeholder="Note" class="grow" />
              <p-button icon="pi pi-plus" (onClick)="addExpense()" [disabled]="!xf.category || !xf.amount" />
            </div>
          }
        </p-card>

        <p-card>
          <ng-template #title><div class="row-between"><span>Money received</span><strong>{{ fmt(money_()?.totals?.received) }}</strong></div></ng-template>
          <p-table [value]="money_()?.receipts ?? []" size="small">
            <ng-template #body let-r><tr [class.strike]="r.status === 'void'"><td><strong>{{ r.number }}</strong> {{ r.kind }}<br />
              <small class="muted">{{ r.mode }}{{ r.reference ? ' · ' + r.reference : '' }}{{ r.status === 'void' ? ' · void: ' + r.void_reason : '' }}</small></td>
              <td><small>{{ r.date | date: 'd MMM y' }}</small></td><td class="right">{{ fmt(r.amount) }}</td>
              <td class="right">@if (r.status !== 'void' && auth.user()?.role === 'owner' && editable()) { <p-button label="Void" size="small" [text]="true" severity="danger" (onClick)="voidR = { r, reason: '' }; voidDlg = true" /> }</td></tr></ng-template>
            <ng-template #emptymessage><tr><td class="muted center">No advance received</td></tr></ng-template>
          </p-table>
          @if (editable()) { <p-button label="Record an advance" icon="pi pi-wallet" size="small" [outlined]="true" styleClass="mt-xs" (onClick)="openReceipt()" /> }
        </p-card>
      </div>
    </div>

    <p-dialog [header]="ef.number + ' · ' + ef.title" [modal]="true" [(visible)]="estDlg" [style]="{ width: '72rem' }" [breakpoints]="{ '1100px': '98vw' }">
      @if (estDlg) {
        <div class="stack">
          <p-table [value]="ef.lines" size="small" [scrollable]="true">
            <ng-template #header><tr><th>Description</th><th>Room / quantity from</th><th class="right">Qty</th><th>Unit</th><th class="right">Material rate</th><th class="right">Labour rate</th><th class="right">Line cost</th><th></th></tr></ng-template>
            <ng-template #body let-ln let-i="rowIndex"><tr>
              <td><input pInputText [(ngModel)]="ln.description" [disabled]="!estEditable()" style="width: 13rem" />
                <br /><p-select [options]="workTypes()" [(ngModel)]="ln.work_type" placeholder="Work type" [showClear]="true" [disabled]="!estEditable()" appendTo="body" styleClass="mt-xs" /></td>
              <td><p-select [options]="rooms()" [(ngModel)]="ln.room_id" optionLabel="name" optionValue="id" placeholder="Room" [showClear]="true" [disabled]="!estEditable()" appendTo="body" />
                <br /><p-select [options]="sources()" [(ngModel)]="ln.qty_source" optionLabel="label" optionValue="value" [disabled]="!estEditable()" appendTo="body" styleClass="mt-xs" /></td>
              <td class="right">@if (ln.qty_source === 'manual') { <p-inputnumber [(ngModel)]="ln.qty" [min]="0" [maxFractionDigits]="2" [disabled]="!estEditable()" [inputStyle]="{ width: '5rem' }" /> }
                @else { {{ measuredQty(ln) }} }</td>
              <td><input pInputText [(ngModel)]="ln.unit" [disabled]="!estEditable()" style="width: 4.5rem" /></td>
              <td class="right"><p-select [options]="matRates()" [(ngModel)]="ln.material_rate_id" optionLabel="label" optionValue="id" placeholder="from library" [showClear]="true" (onChange)="pickRate(ln, 'material')" [disabled]="!estEditable()" appendTo="body" />
                <br /><p-inputnumber [(ngModel)]="ln.material_rate" [min]="0" [disabled]="!estEditable()" [inputStyle]="{ width: '6rem' }" /></td>
              <td class="right"><p-select [options]="labRates()" [(ngModel)]="ln.labour_rate_id" optionLabel="label" optionValue="id" placeholder="from library" [showClear]="true" (onChange)="pickRate(ln, 'labour')" [disabled]="!estEditable()" appendTo="body" />
                <br /><p-inputnumber [(ngModel)]="ln.labour_rate" [min]="0" [disabled]="!estEditable()" [inputStyle]="{ width: '6rem' }" /></td>
              <td class="right">{{ fmt(ln.line_cost) }}</td>
              <td>@if (estEditable()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="ef.lines.splice(i, 1)" /> }</td></tr></ng-template>
          </p-table>
          @if (estEditable()) { <p-button label="Add line" icon="pi pi-plus" size="small" [text]="true" (onClick)="ef.lines.push(blankLine())" /> }
          <div class="grid2 top">
            <div class="grid2">
              <label class="field"><span>Overheads %</span><p-inputnumber [(ngModel)]="ef.overhead_pct" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!estEditable()" fluid /></label>
              <label class="field"><span>Markup %</span><p-inputnumber [(ngModel)]="ef.markup_pct" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!estEditable()" fluid /></label>
              <label class="field"><span>Discount % <small class="muted">(limit {{ limits().max_discount_pct }}%)</small></span><p-inputnumber [(ngModel)]="ef.discount_pct" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!estEditable()" fluid /></label>
              <label class="field"><span>Tax %</span><p-inputnumber [(ngModel)]="ef.tax_pct" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!estEditable()" fluid /></label>
            </div>
            @if (ef.totals; as tt) {
              <table class="totals small">
                <tr><td>Material</td><td class="right">{{ fmt(tt.material) }}</td></tr><tr><td>Labour</td><td class="right">{{ fmt(tt.labour) }}</td></tr>
                <tr><td>Overheads</td><td class="right">{{ fmt(tt.overheads) }}</td></tr><tr><td><strong>Cost</strong></td><td class="right"><strong>{{ fmt(tt.cost) }}</strong></td></tr>
                <tr><td>Markup</td><td class="right">{{ fmt(tt.markup_amount) }}</td></tr><tr><td>Discount</td><td class="right">− {{ fmt(tt.discount) }}</td></tr>
                <tr><td>Subtotal</td><td class="right">{{ fmt(tt.subtotal) }}</td></tr><tr><td>Tax</td><td class="right">{{ fmt(tt.tax) }}</td></tr>
                <tr><td><strong>Total to client</strong></td><td class="right"><strong>{{ fmt(tt.total) }}</strong></td></tr>
                <tr><td>Margin</td><td class="right" [class.c-bad]="tt.margin_pct < limits().min_margin_pct">{{ fmt(tt.margin) }} ({{ tt.margin_pct | number: '1.1-1' }}%)</td></tr>
              </table>
            }
          </div>
          @if (estEditable()) {
            <div class="row gap right">
              <small class="muted">Save to recalculate. Margin under {{ limits().min_margin_pct }}% or a discount over {{ limits().max_discount_pct }}% goes to the owner / sales manager.</small>
              <p-button label="Save" icon="pi pi-save" [outlined]="true" (onClick)="saveEstimate()" />
              <p-button label="Save & submit" icon="pi pi-send" (onClick)="saveEstimate(true)" />
            </div>
          }
        </div>
      }
    </p-dialog>

    <p-dialog header="Refuse the estimate" [modal]="true" [(visible)]="refuseDlg" [style]="{ width: '26rem' }">
      <div class="stack"><label class="field"><span>Why?</span><input pInputText [(ngModel)]="refuse.note" fluid /></label>
        <div class="row right"><p-button label="Refuse" severity="danger" (onClick)="decide(refuse.e, false, refuse.note)" [disabled]="!refuse.note?.trim()" /></div></div>
    </p-dialog>

    <p-dialog header="Record an advance" [modal]="true" [(visible)]="recDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p-select [options]="money_()?.receipt_kinds ?? []" [(ngModel)]="rf.kind" placeholder="What for" fluid appendTo="body" />
        <div class="grid2"><label class="field"><span>Amount</span><p-inputnumber [(ngModel)]="rf.amount" [min]="0" fluid /></label>
          <label class="field"><span>Date</span><input pInputText type="date" [max]="today" [(ngModel)]="rf.date" fluid /></label></div>
        <div class="grid2"><p-select [options]="money_()?.modes ?? []" [(ngModel)]="rf.mode" placeholder="Mode" fluid appendTo="body" />
          <input pInputText [(ngModel)]="rf.reference" placeholder="Reference (UPI / cheque no.)" /></div>
        <input pInputText [(ngModel)]="rf.note" placeholder="Note" />
        <div class="row right"><p-button label="Save receipt" (onClick)="addReceipt()" [disabled]="!rf.kind || !rf.amount || !rf.mode" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Void receipt" [modal]="true" [(visible)]="voidDlg" [style]="{ width: '26rem' }">
      <div class="stack"><label class="field"><span>Reason</span><input pInputText [(ngModel)]="voidR.reason" fluid /></label>
        <div class="row right"><p-button label="Void" severity="danger" (onClick)="voidReceipt()" [disabled]="!voidR.reason?.trim()" /></div></div>
    </p-dialog>

    <p-dialog header="Rate library" [modal]="true" [(visible)]="ratesDlg" [style]="{ width: '56rem' }" [breakpoints]="{ '900px': '98vw' }">
      <p-table [value]="rates()" size="small" [scrollable]="true" scrollHeight="50vh">
        <ng-template #header><tr><th>Kind</th><th>Name</th><th>Category</th><th>Unit</th><th class="right">Rate</th><th></th></tr></ng-template>
        <ng-template #body let-r><tr><td>{{ label(r.kind) }}</td><td>{{ r.name }}{{ r.brand ? ' · ' + r.brand : '' }}</td><td>{{ r.category || '—' }}</td><td>{{ r.unit }}</td>
          <td class="right">{{ fmt(r.rate) }}</td><td class="right">@if (canEst()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="delRate(r)" /> }</td></tr></ng-template>
        <ng-template #emptymessage><tr><td colspan="6" class="muted center">No rates yet</td></tr></ng-template>
      </p-table>
      @if (canEst()) {
        <div class="row gap wrap mt">
          <p-select [options]="kinds" [(ngModel)]="nr.kind" optionLabel="label" optionValue="value" appendTo="body" />
          <input pInputText [(ngModel)]="nr.name" placeholder="Name" />
          <p-select [options]="workTypes()" [(ngModel)]="nr.category" placeholder="Category" [showClear]="true" appendTo="body" />
          <input pInputText [(ngModel)]="nr.unit" placeholder="Unit (sq ft, nos)" style="width: 8rem" />
          <p-inputnumber [(ngModel)]="nr.rate" [min]="0" placeholder="Rate" [inputStyle]="{ width: '6rem' }" />
          <p-button icon="pi pi-plus" (onClick)="addRate()" [disabled]="!nr.name || !nr.unit || nr.rate == null" />
        </div>
      }
    </p-dialog>
  `,
})
export class LeadMoneyComponent implements OnInit {
  lead = input.required<any>();
  changed = output<void>();
  private api = inject(Api);
  auth = inject(AuthService);
  estimates = signal<any[]>([]);
  meta = signal<any>(null);
  money_ = signal<any>(null);
  rates = signal<any[]>([]);
  editable = computed(() => this.lead()?.status === 'open' && this.lead()?.can_edit);
  canEst = computed(() => this.lead()?.status === 'open' && this.auth.can('proposals', 'rw'));
  isApprover = computed(() => this.auth.user()?.role === 'owner' || this.auth.user()?.id === this.meta()?.manager_id);
  rooms = computed(() => this.meta()?.rooms ?? []);
  workTypes = computed(() => this.meta()?.work_types ?? []);
  limits = computed(() => this.meta()?.limits ?? { min_margin_pct: 0, max_discount_pct: 100 });
  sources = computed(() => [{ value: 'manual', label: 'Typed quantity' }, ...Object.entries(this.meta()?.measure_sources ?? {}).map(([value, label]) => ({ value, label }))]);
  matRates = computed(() => this.rates().filter((r) => r.kind !== 'labour').map((r) => ({ ...r, label: `${r.name} · ${r.rate}/${r.unit}` })));
  labRates = computed(() => this.rates().filter((r) => r.kind === 'labour').map((r) => ({ ...r, label: `${r.name} · ${r.rate}/${r.unit}` })));
  sev = EST_SEVERITY;
  label = label;
  kinds = [{ label: 'Material', value: 'material' }, { label: 'Labour', value: 'labour' }, { label: 'Product', value: 'product' }];
  today = new Date().toISOString().slice(0, 10);
  ef: any = {};
  xf: any = {};
  rf: any = {};
  nr: any = { kind: 'material' };
  refuse: any = {};
  voidR: any = {};
  estDlg = false; refuseDlg = false; recDlg = false; voidDlg = false; ratesDlg = false;

  async ngOnInit() {
    await this.load();
  }

  fmt(v: number | null | undefined) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  async load() {
    const id = this.lead().id;
    if (this.auth.can('proposals')) {
      const r = await this.api.get(`/leads/${id}/estimates`);
      const lm = await this.api.get('/leads/meta');
      this.meta.set({ ...r, manager_id: lm.sales_settings?.manager_id });
      this.estimates.set(r.estimates);
      this.rates.set((await this.api.get('/rates')).rates);
    }
    this.money_.set(await this.api.get(`/leads/${id}/money`));
    this.xf = { category: null, amount: null, date: this.today, note: '' };
  }

  private async done() {
    await this.load();
    this.changed.emit();
  }

  canEditEst(e: any) {
    return this.canEst() && (e.status === 'draft' || e.status === 'refused');
  }

  estEditable() {
    return this.canEditEst(this.ef);
  }

  blankLine() {
    return { description: '', room_id: null, qty_source: 'manual', qty: null, unit: '', material_rate: 0, labour_rate: 0, work_type: null };
  }

  measuredQty(ln: any) {
    const r = this.rooms().find((x: any) => x.id === ln.room_id);
    return r ? r[ln.qty_source] : '—';
  }

  pickRate(ln: any, kind: 'material' | 'labour') {
    const r = this.rates().find((x) => x.id === (kind === 'material' ? ln.material_rate_id : ln.labour_rate_id));
    if (!r) return;
    if (kind === 'material') ln.material_rate = r.rate;
    else ln.labour_rate = r.rate;
    if (!ln.unit) ln.unit = r.unit;
    if (!ln.description) ln.description = r.name;
    if (!ln.work_type && r.category) ln.work_type = r.category;
  }

  async newEstimate(from?: any) {
    const e = await this.api.post(`/leads/${this.lead().id}/estimates`, from ? { copy_from: from.id } : {}, 'Estimate started');
    await this.done();
    this.openEstimate(e);
  }

  openEstimate(e: any) {
    this.ef = JSON.parse(JSON.stringify(e));
    if (!this.ef.lines.length && this.estEditable()) this.ef.lines.push(this.blankLine());
    this.estDlg = true;
  }

  async saveEstimate(submit = false) {
    const lines = this.ef.lines.filter((l: any) => l.description?.trim());
    let e = await this.api.put(`/estimates/${this.ef.id}`, { title: this.ef.title, lines, overhead_pct: this.ef.overhead_pct, markup_pct: this.ef.markup_pct,
      discount_pct: this.ef.discount_pct, tax_pct: this.ef.tax_pct }, submit ? undefined : 'Estimate saved');
    if (submit) {
      e = await this.api.post(`/estimates/${this.ef.id}/submit`, {});
      this.estDlg = false;
    } else this.ef = JSON.parse(JSON.stringify(e));
    await this.done();
  }

  async decide(e: any, approve: boolean, note?: string) {
    await this.api.post(`/estimates/${e.id}/decide`, { approve, note }, approve ? 'Approved' : 'Refused');
    this.refuseDlg = false;
    await this.done();
  }

  async addExpense() {
    await this.api.post(`/leads/${this.lead().id}/expenses`, this.xf, 'Expense added');
    await this.done();
  }

  async delExpense(x: any) {
    await this.api.del(`/lead_expenses/${x.id}`, 'Expense removed');
    await this.done();
  }

  openReceipt() {
    this.rf = { kind: null, amount: null, date: this.today, mode: null, reference: '', note: '' };
    this.recDlg = true;
  }

  async addReceipt() {
    await this.api.post(`/leads/${this.lead().id}/receipts`, this.rf, 'Receipt saved');
    this.recDlg = false;
    await this.done();
  }

  async voidReceipt() {
    await this.api.post(`/lead_receipts/${this.voidR.r.id}/void`, { reason: this.voidR.reason }, 'Receipt voided');
    this.voidDlg = false;
    await this.done();
  }

  async openRates() {
    this.rates.set((await this.api.get('/rates')).rates);
    this.nr = { kind: 'material', name: '', category: null, unit: '', rate: null };
    this.ratesDlg = true;
  }

  async addRate() {
    await this.api.post('/rates', this.nr, 'Rate added');
    await this.openRates();
  }

  async delRate(r: any) {
    const res = await this.api.del(`/rates/${r.id}`, 'Rate removed');
    if (res?.archived) this.rates.set(this.rates().filter((x) => x.id !== r.id));
    else await this.openRates();
  }
}
