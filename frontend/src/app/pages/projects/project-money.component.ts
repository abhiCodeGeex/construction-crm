import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ConfirmationService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { ProgressBarModule } from 'primeng/progressbar';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TooltipModule } from 'primeng/tooltip';
import { Api, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { ProjectInvoicesComponent } from './project-invoices.component';

const COST_SEV: Record<string, 'secondary' | 'info' | 'success' | 'danger' | 'warn'> = {
  draft: 'secondary', submitted: 'warn', approved: 'success', rejected: 'danger', void: 'secondary',
};
const VENDOR_TYPES = ['supplier', 'subcontractor', 'contractor', 'consultant'];

/** Project money (Phase E block 1): budget vs actual per stage and the costs behind it. Only approved costs are
 *  actual, submitted ones are committed. A Site Supervisor sees and logs only their own site expenses. */
@Component({
  selector: 'app-project-money',
  imports: [FormsModule, DatePipe, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, ProgressBarModule,
    SelectModule, TableModule, TagModule, TooltipModule, ProjectInvoicesComponent],
  template: `
    @if (data(); as d) {
      @if (summary(); as s) {
        <div class="money-strip mb">
          <div><small>Contract{{ s.contract_value !== null && s.revised_value !== s.contract_value ? ' → revised' : '' }}</small>
            <strong>@if (s.contract_value !== null && s.revised_value !== s.contract_value) { {{ fmt(s.contract_value) }} → } {{ fmt(s.revised_value) }}</strong></div>
          <div><small>Invoiced</small><strong>{{ fmt(s.invoiced) }}</strong></div>
          <div><small>Received</small><strong>{{ fmt(s.received) }}</strong></div>
          <div><small>Owed by the client</small><strong [class.c-warn]="s.receivable > 0">{{ fmt(s.receivable) }}</strong></div>
          <div><small>Still to invoice</small><strong>{{ fmt(s.to_invoice) }}</strong></div>
          @if (s.retention_held) { <div><small>Retention held</small><strong>{{ fmt(s.retention_held) }}</strong></div> }
          @if (s.margin !== undefined) { <div><small>Margin so far</small><strong [class.c-bad]="s.margin < 0">{{ fmt(s.margin) }}@if (s.margin_pct !== null) { <span class="small muted"> {{ s.margin_pct }}%</span> }</strong></div> }
        </div>
      }
      @if (d.budget; as b) {
        <div class="stats">
          <div class="stat-card"><div class="stat-icon indigo"><i class="pi pi-wallet"></i></div>
            <div><small>Budget</small><strong>{{ fmt(b.budget) }}</strong></div></div>
          <div class="stat-card"><div class="stat-icon teal"><i class="pi pi-check-circle"></i></div>
            <div><small>Actual (approved)</small><strong [class.c-bad]="b.budget && b.spent > b.budget">{{ fmt(b.spent) }}</strong>
              <span class="small muted">{{ b.budget ? pct(b.spent, b.budget) + '% of budget' : 'no budget set' }}</span></div></div>
          <div class="stat-card"><div class="stat-icon amber"><i class="pi pi-hourglass"></i></div>
            <div><small>Committed (waiting approval)</small><strong>{{ fmt(b.committed) }}</strong></div></div>
          <div class="stat-card"><div class="stat-icon pink"><i class="pi pi-chart-line"></i></div>
            <div><small>Remaining</small><strong [class.c-bad]="b.budget - b.spent < 0">{{ fmt(b.budget - b.spent) }}</strong></div></div>
        </div>

        <div class="row-between">
          <h3 class="mt0">Budget vs actual by stage</h3>
          @if (d.perms.can_set_budget) { <p-button label="Budgets from estimate" icon="pi pi-calculator" size="small" [text]="true" (onClick)="openPlan()" /> }
        </div>
        <p-table [value]="b.stages" styleClass="p-datatable-sm mb">
          <ng-template #header><tr><th>Stage</th><th class="num">Budget</th><th class="num">Actual</th><th class="num">Committed</th><th class="num" title="On open purchase orders, not billed yet">Ordered</th><th style="width: 30%">Used</th></tr></ng-template>
          <ng-template #body let-s>
            <tr>
              <td>{{ s.name }}</td>
              <td class="num">{{ s.budget ? fmt(s.budget) : '—' }}</td>
              <td class="num" [class.c-bad]="s.level === 'red'">{{ fmt(s.spent) }}</td>
              <td class="num">{{ s.committed ? fmt(s.committed) : '—' }}</td>
              <td class="num" [class.c-warn]="s.budget && s.spent + s.committed + (s.ordered || 0) > s.budget">{{ s.ordered ? fmt(s.ordered) : '—' }}</td>
              <td>@if (s.budget) {
                <p-progressbar [value]="s.pct > 100 ? 100 : s.pct" [showValue]="false" [styleClass]="'bar-' + s.level" />
                <span class="small" [class.c-bad]="s.level === 'red'" [class.c-warn]="s.level === 'amber'">{{ s.pct }}%</span>
              } @else { <span class="small muted">no budget</span> }</td>
            </tr>
          </ng-template>
        </p-table>
      }

      <div class="row-between mb">
        <h3 class="m0">{{ d.perms.can_add ? 'Costs' : 'My site expenses' }}</h3>
        @if (d.perms.can_add || d.perms.can_add_site_expense) {
          <p-button [label]="d.perms.can_add ? 'Record cost' : 'Log site expense'" icon="pi pi-plus" size="small" (onClick)="openNew()" />
        }
      </div>
      @if (d.perms.can_add_site_expense) {
        <p class="small muted">Site expenses up to {{ fmt(d.perms.site_expense_limit) }} each; every one waits for the PM's approval.</p>
      }
      <p-table [value]="d.costs" styleClass="p-datatable-sm" [paginator]="d.costs.length > 15" [rows]="15">
        <ng-template #header><tr><th>Date</th><th>What</th><th>Stage</th><th>Category</th><th class="num">Amount</th><th>Status</th><th></th></tr></ng-template>
        <ng-template #body let-c>
          <tr>
            <td>{{ c.date | date: 'd MMM' }}</td>
            <td>{{ c.description }}@if (c.paid_from_float) { <p-tag value="petty cash" severity="secondary" styleClass="ml-xs" /> }
              <div class="small muted">@if (c.vendor_name) { {{ c.vendor_name }} · } @if (c.bill_no) { bill {{ c.bill_no }} · } {{ c.created_by_name }}
                @for (f of c.files; track f.key) { · <a [href]="'/api/files/' + f.key" target="_blank" rel="noopener">{{ f.name }}</a> }</div>
              @if (c.reject_reason) { <div class="small c-bad">Rejected: {{ c.reject_reason }}</div> }
              @if (c.void_reason) { <div class="small muted">Void: {{ c.void_reason }}</div> }
              @if (c.overspend_reason) { <div class="small c-warn">Over budget by {{ fmt(c.overspend_amount) }}: {{ d.reasons[c.overspend_reason] }}</div> }
            </td>
            <td>{{ c.stage_name }}</td>
            <td>{{ c.category }}</td>
            <td class="num">{{ fmt(c.amount) }}@if (c.tax) { <div class="small muted">+ {{ fmt(c.tax) }} tax</div> }</td>
            <td><p-tag [value]="c.status" [severity]="sev[c.status]" />
              @if (c.status === 'submitted' && c.over_budget) { <div class="small c-warn">{{ fmt(c.over_budget) }} over budget</div> }</td>
            <td class="nowrap right">
              @if ((c.status === 'draft' || c.status === 'rejected') && mine(c)) {
                <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="openEdit(c)" ariaLabel="Edit" pTooltip="Edit" />
                @if (c.status === 'draft') { <p-button label="Submit" size="small" [text]="true" (onClick)="act(c, 'submit')" /> }
                <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="remove(c)" ariaLabel="Delete" pTooltip="Delete" />
              }
              @if (c.status === 'submitted' && d.perms.can_approve) {
                <p-button label="Approve" size="small" (onClick)="approve(c)" />
                <p-button label="Reject" size="small" [text]="true" severity="danger" (onClick)="askReason(c, 'reject')" />
              }
              @if (c.status === 'approved' && d.perms.can_void) {
                <p-button label="Void" size="small" [text]="true" severity="secondary" (onClick)="askReason(c, 'void')" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="7" class="muted">No costs recorded yet.</td></tr></ng-template>
      </p-table>
      @if (canSeeInvoices()) { <app-project-invoices [projectId]="project().id" (changed)="load(); changed.emit()" /> }
    }

    <p-dialog [header]="f.id ? 'Edit cost' : (data()?.perms?.can_add ? 'Record a cost' : 'Log a site expense')" [modal]="true" [(visible)]="dlg"
              [style]="{ width: '36rem' }" [breakpoints]="{ '640px': '96vw' }">
      <form class="stack" (ngSubmit)="save(false)">
        <div class="grid2">
          <label class="field req"><span>Stage</span><p-select name="st" [options]="data()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="f.stage_id" fluid appendTo="body" /></label>
          @if (data()?.perms?.can_add) {
            <label class="field req"><span>Category</span><p-select name="ca" [options]="data()?.categories ?? []" [(ngModel)]="f.category" fluid appendTo="body" /></label>
          }
        </div>
        <label class="field req"><span>What is it for</span><input pInputText name="de" [(ngModel)]="f.description" fluid /></label>
        <div class="grid2">
          <label class="field req"><span>Date</span><input pInputText type="date" name="da" [(ngModel)]="f.date" [max]="today" fluid /></label>
          <label class="field req"><span>Amount (before tax)</span><p-inputnumber name="am" [(ngModel)]="f.amount" [min]="0" fluid /></label>
        </div>
        @if (data()?.perms?.can_add) {
          <div class="grid2">
            <label class="field"><span>Tax</span><p-inputnumber name="tx" [(ngModel)]="f.tax" [min]="0" fluid /></label>
            <label class="field"><span>Vendor</span><p-select name="ve" [options]="vendors()" optionLabel="name" optionValue="id" [(ngModel)]="f.vendor_id" [showClear]="true" [filter]="true" fluid appendTo="body" placeholder="Supplier, subcontractor…" /></label>
          </div>
          <div class="grid2">
            <label class="field"><span>Quantity</span><p-inputnumber name="qt" [(ngModel)]="f.qty" [min]="0" [maxFractionDigits]="2" fluid /></label>
            <label class="field"><span>Unit</span><input pInputText name="un" [(ngModel)]="f.unit" placeholder="bag, sq ft, day…" fluid /></label>
          </div>
        }
        <div class="grid2">
          <label class="field"><span>Bill / receipt number</span><input pInputText name="bn" [(ngModel)]="f.bill_no" fluid /></label>
          <label class="field"><span>Bill photo or PDF</span><input type="file" (change)="attach($event)" accept="image/*,application/pdf" /></label>
        </div>
        @if (f.files?.length) { <div class="small muted">{{ f.files.length }} file(s) attached</div> }
        @if (float(); as fl) {
          <label class="check"><p-checkbox name="pf" [(ngModel)]="f.paid_from_float" [binary]="true" ariaLabel="Paid from my petty cash" />
            Paid from my petty cash <span class="small muted">({{ fmt(fl.balance) }} left)</span></label>
        }
        <div class="row gap right">
          @if (data()?.perms?.can_add) { <p-button type="submit" label="Save draft" severity="secondary" [disabled]="!valid()" /> }
          <p-button label="Submit" icon="pi pi-send" (onClick)="save(true)" [disabled]="!valid()" />
        </div>
      </form>
    </p-dialog>

    <p-dialog header="Stage budgets from the estimate" [modal]="true" [(visible)]="planDlg" [style]="{ width: '40rem' }" [breakpoints]="{ '640px': '96vw' }">
      @if (plan(); as pl) {
        <div class="stack">
          <p class="small muted m0">From estimate {{ pl.estimate_number }}: each stage gets the cost (with overheads) of the estimate lines tagged to it{{ pl.tagged ? '; untagged lines are spread over those stages' : '; no line is tagged, so the cost is spread evenly' }}.</p>
          <p-table [value]="pl.rows" size="small">
            <ng-template #header><tr><th></th><th>Stage</th><th class="num">Now</th><th class="num">From the estimate</th></tr></ng-template>
            <ng-template #body let-r><tr>
              <td><p-checkbox [(ngModel)]="picked[r.stage_id]" [binary]="true" [ariaLabel]="r.stage" [disabled]="!r.proposed" /></td>
              <td>{{ r.stage }}</td><td class="num">{{ r.current ? fmt(r.current) : '—' }}</td><td class="num">{{ r.proposed ? fmt(r.proposed) : '—' }}</td></tr></ng-template>
          </p-table>
          <div class="row right"><p-button label="Apply to the ticked stages" [disabled]="!pickedIds().length" (onClick)="applyPlan()" /></div>
        </div>
      } @else { <p class="muted">This project has no approved estimate to take budgets from.</p> }
    </p-dialog>

    <p-dialog [header]="reasonFor === 'void' ? 'Void this cost' : 'Reject this cost'" [modal]="true" [(visible)]="reasonDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>Why</span><input pInputText [(ngModel)]="reason" fluid /></label>
        <div class="row right"><p-button [label]="reasonFor === 'void' ? 'Void' : 'Reject'" severity="danger" [disabled]="!reason.trim()" (onClick)="sendReason()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Over the stage budget" [modal]="true" [(visible)]="overDlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <p class="m0">This cost takes {{ pendingCost?.stage_name }} {{ fmt(pendingCost?.over_budget) }} over its budget. Why?</p>
        <p-select [options]="reasonOptions()" optionLabel="label" optionValue="value" [(ngModel)]="overReason" fluid appendTo="body" placeholder="Choose a reason" />
        @if (overReason === 'client_change') { <p class="small muted m0">The client pays for this: raise a change order for the overspend.</p> }
        <div class="row right"><p-button label="Approve" [disabled]="!overReason" (onClick)="approve(pendingCost, overReason)" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .nowrap { white-space: nowrap; }
    .money-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .75rem; background: var(--surface);
      border: 1px solid var(--border); border-radius: var(--radius); padding: .9rem 1rem; }
    .money-strip small { display: block; color: var(--muted); }
    .money-strip strong { font-variant-numeric: tabular-nums; }
    :host ::ng-deep .bar-amber .p-progressbar-value { background: var(--warn, #d97706); }
    :host ::ng-deep .bar-red .p-progressbar-value { background: var(--bad, #dc2626); }
  `,
})
export class ProjectMoneyComponent implements OnInit {
  project = input.required<any>();
  contacts = input<any[]>([]);
  changed = output<void>();
  private api = inject(Api);
  private auth = inject(AuthService);
  private confirm = inject(ConfirmationService);
  data = signal<any>(null);
  sev = COST_SEV;
  dlg = false; reasonDlg = false; overDlg = false;
  f: any = {};
  reason = ''; reasonFor: 'reject' | 'void' = 'reject';
  overReason = '';
  pendingCost: any = null;
  today = new Date().toISOString().slice(0, 10);
  canSeeInvoices = () => this.auth.can('finance');

  vendors = computed(() => this.contacts().filter((c: any) => (c.types ?? []).some((t: string) => VENDOR_TYPES.includes(t))));
  reasonOptions = computed(() => Object.entries(this.data()?.reasons ?? {}).map(([value, label]) => ({ value, label })));

  async ngOnInit() {
    await this.load();
  }

  summary = signal<any>(null);

  async load() {
    this.data.set(await this.api.get(`/projects/${this.project().id}/costs`));
    if (this.auth.can('finance')) this.summary.set(await this.api.get(`/projects/${this.project().id}/finance`));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  pct(a: number, b: number) {
    return Math.round((a / b) * 100);
  }

  mine(c: any) {
    return c.created_by === this.auth.user()?.id || this.data()?.perms?.can_add;
  }

  valid() {
    return this.f.stage_id && this.f.description?.trim() && this.f.amount > 0 && this.f.date && (this.f.category || !this.data()?.perms?.can_add);
  }

  openNew() {
    this.f = { stage_id: null, category: 'Material', description: '', date: this.today, amount: null, tax: null,
      vendor_id: null, qty: null, unit: '', bill_no: '', files: [], paid_from_float: false };
    this.loadFloat();
    this.dlg = true;
  }

  openEdit(c: any) {
    this.f = { id: c.id, stage_id: c.stage_id, category: c.category, description: c.description, date: c.date, amount: c.amount,
      tax: c.tax, vendor_id: c.vendor_id, qty: c.qty, unit: c.unit ?? '', bill_no: c.bill_no ?? '', files: (c.files ?? []).map((x: any) => x.key),
      paid_from_float: !!c.paid_from_float };
    this.loadFloat();
    this.dlg = true;
  }

  // ---- Phase I: petty cash and budgets from the estimate ----
  float = signal<any>(null);
  plan = signal<any>(null);
  planDlg = false;
  picked: Record<string, boolean> = {};
  pickedIds = () => Object.keys(this.picked).filter((k) => this.picked[k]);

  async loadFloat() {
    this.float.set((await this.api.get('/finance/petty-cash')).mine);
  }

  async openPlan() {
    const pl = await this.api.get(`/projects/${this.project().id}/budget-from-estimate`);
    this.plan.set(pl);
    this.picked = {};
    for (const r of pl?.rows ?? []) this.picked[r.stage_id] = !!r.proposed && !r.current;
    this.planDlg = true;
  }

  async applyPlan() {
    await this.api.post(`/projects/${this.project().id}/budget-from-estimate`, { stage_ids: this.pickedIds() }, 'Budgets set');
    this.planDlg = false;
    await this.refresh();
  }

  async attach(ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (file) this.f.files = [...(this.f.files ?? []), (await this.api.upload(file)).key];
  }

  async save(submit: boolean) {
    const { id, ...body } = this.f;
    if (!this.data()?.perms?.can_add) {
      for (const k of ['category', 'tax', 'vendor_id', 'qty', 'unit']) delete body[k];
    }
    if (id) {
      await this.api.put(`/costs/${id}`, body, 'Cost saved');
      if (submit) await this.api.post(`/costs/${id}/submit`, {}, 'Submitted');
    } else {
      await this.api.post(`/projects/${this.project().id}/costs`, { ...body, submit }, submit ? 'Cost submitted' : 'Draft saved');
    }
    this.dlg = false;
    await this.refresh();
  }

  async act(c: any, what: 'submit') {
    await this.api.post(`/costs/${c.id}/${what}`, {}, 'Submitted');
    await this.refresh();
  }

  async approve(c: any, overspend_reason?: string) {
    if (c.over_budget && !overspend_reason) {
      this.pendingCost = c;
      this.overReason = '';
      this.overDlg = true;
      return;
    }
    await this.api.post(`/costs/${c.id}/approve`, overspend_reason ? { overspend_reason } : {}, 'Approved');
    this.overDlg = false;
    await this.refresh();
  }

  askReason(c: any, what: 'reject' | 'void') {
    this.pendingCost = c;
    this.reasonFor = what;
    this.reason = '';
    this.reasonDlg = true;
  }

  async sendReason() {
    await this.api.post(`/costs/${this.pendingCost.id}/${this.reasonFor}`, { reason: this.reason }, this.reasonFor === 'void' ? 'Voided' : 'Rejected');
    this.reasonDlg = false;
    await this.refresh();
  }

  remove(c: any) {
    this.confirm.confirm({ header: `Delete ${c.description}?`, icon: 'pi pi-trash', message: 'This draft is removed.',
      accept: async () => { await this.api.del(`/costs/${c.id}`, 'Deleted'); await this.refresh(); } });
  }

  private async refresh() {
    await this.load();
    this.changed.emit();
  }
}
