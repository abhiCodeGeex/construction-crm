import { Component, OnInit, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
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

export const CO_SEV: Record<string, 'secondary' | 'info' | 'success' | 'danger' | 'warn'> = {
  draft: 'secondary', priced: 'info', sent: 'warn', approved: 'success', rejected: 'danger', withdrawn: 'secondary',
};

/** Change orders on a project (Phase E block 4): raise -> price (our cost, the client's price, working days) -> send ->
 *  record the client's approval -> the contract, stage budget and dates follow. Our-error changes: Owner approves. */
@Component({
  selector: 'app-project-change-orders',
  imports: [FormsModule, DatePipe, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TableModule,
    TagModule, TextareaModule, TooltipModule],
  template: `
    @if (data(); as d) {
      <div class="row-between mb">
        <span class="muted small">Approved changes: <strong>{{ fmt(d.approved_total) }}</strong>. A change to scope, price or time is agreed here; the signed contract is never edited.</span>
        @if (d.can_write) { <p-button label="Raise change order" icon="pi pi-plus" size="small" (onClick)="openNew()" /> }
      </div>
      <p-table [value]="d.change_orders" styleClass="p-datatable-sm" dataKey="id">
        <ng-template #header><tr><th>Number</th><th>Change</th><th>Stage</th><th class="num">Price</th>@if (showCost()) { <th class="num">Cost</th> }<th>Time</th><th>Status</th><th></th></tr></ng-template>
        <ng-template #body let-c>
          <tr>
            <td>{{ c.number }}<div class="small muted">{{ c.created_at | date: 'd MMM' }}</div></td>
            <td>{{ c.title }}<div class="small muted">{{ d.reasons[c.reason] }} · {{ c.raised_by_name }}
              @if (c.requested) { · <span class="c-warn">asked by {{ c.requested.kind === 'client' ? 'the client' : 'site' }} ({{ c.requested.name }})</span> }
              @if (c.credit) { · <span class="c-good">allowance credit</span> }</div>
              @if (c.decision_reason) { <div class="small c-bad">{{ c.decision_reason }}</div> }
              @if (c.approval) { <div class="small muted">Approved by {{ c.approval.name }} ({{ c.approval.method }}) {{ c.approval.date | date: 'd MMM' }}</div> }
              @if (c.effects?.moved_tasks?.length) { <div class="small muted">Moved: {{ c.effects.moved_tasks.join(', ') }}</div> }</td>
            <td>{{ c.stage_name }}</td>
            <td class="num">{{ c.totals.total ? fmt(c.totals.total) : '—' }}</td>
            @if (showCost()) { <td class="num">{{ fmt(c.totals.cost) }}</td> }
            <td>{{ c.time_days ? (c.time_days > 0 ? '+' : '') + c.time_days + ' days' : '—' }}</td>
            <td><p-tag [value]="c.status" [severity]="sev[c.status]" /></td>
            <td class="right nowrap">
              @if (d.can_write && (c.status === 'draft' || c.status === 'priced')) {
                <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="openEdit(c)" ariaLabel="Edit" pTooltip="Edit" />
                @if (c.status === 'draft') { <p-button label="Price" size="small" [text]="true" (onClick)="act(c, 'price')" /> }
                @if (c.status === 'priced' && c.reason !== 'our_error') { <p-button label="Send" size="small" (onClick)="act(c, 'send')" /> }
              }
              @if (c.status === 'priced' && c.reason === 'our_error' && d.is_owner) { <p-button label="Approve" size="small" (onClick)="approveInternal(c)" /> }
              @if (c.status === 'sent' && d.can_approve) {
                <p-button label="Client approved" size="small" (onClick)="openApprove(c)" />
                <p-button label="Rejected" size="small" [text]="true" severity="danger" (onClick)="askReason(c, 'reject')" />
              }
              @if (d.can_write && ['draft', 'priced', 'sent'].includes(c.status)) {
                <p-button label="Withdraw" size="small" [text]="true" severity="secondary" (onClick)="askReason(c, 'withdraw')" />
              }
              @if (c.status === 'approved' && !d.has_contract && c.totals.total && !c.invoice_id && canInvoice()) {
                <p-button label="Invoice" size="small" [text]="true" (onClick)="act(c, 'invoice')" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="8" class="muted">No change orders.</td></tr></ng-template>
      </p-table>
    }

    <p-dialog [header]="f.id ? 'Edit change order' : 'Raise a change order'" [modal]="true" [(visible)]="dlg" [style]="{ width: '48rem' }" [breakpoints]="{ '800px': '98vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field req"><span>Stage</span><p-select [options]="data()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="f.stage_id" fluid appendTo="body" /></label>
          <label class="field req"><span>Why</span><p-select [options]="reasonOpts()" optionLabel="label" optionValue="value" [(ngModel)]="f.reason" fluid appendTo="body" /></label>
        </div>
        <label class="field req"><span>Title</span><input pInputText [(ngModel)]="f.title" fluid /></label>
        <label class="field"><span>What changes</span><textarea pTextarea rows="2" [(ngModel)]="f.description" fluid></textarea></label>
        <div class="small muted">Lines: what it costs us and what the client pays{{ f.reason === 'our_error' ? ' (our error: cost only)' : '' }}.</div>
        @for (ln of f.lines; track $index; let i = $index) {
          <div class="co-line">
            <input pInputText placeholder="Description" [(ngModel)]="ln.description" />
            <p-inputnumber placeholder="Qty" [(ngModel)]="ln.qty" [min]="0" [maxFractionDigits]="2" [inputStyle]="{ width: '100%' }" />
            <p-inputnumber placeholder="Cost / unit" [(ngModel)]="ln.cost_rate" [min]="0" [inputStyle]="{ width: '100%' }" />
            <p-inputnumber placeholder="Price / unit" [(ngModel)]="ln.price_rate" [min]="0" [disabled]="f.reason === 'our_error'" [inputStyle]="{ width: '100%' }" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.lines.splice(i, 1)" ariaLabel="Remove line" />
          </div>
        }
        <p-button label="Add line" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.lines.push({ description: '', qty: 1, cost_rate: null, price_rate: null })" />
        <div class="small muted">New tasks this change adds to the stage (created when it is approved)</div>
        @for (nt of f.new_tasks; track $index; let i = $index) {
          <div class="row gap"><input pInputText [(ngModel)]="nt.title" placeholder="Task" class="grow" />
            <p-inputnumber [(ngModel)]="nt.days" [min]="1" [max]="365" suffix=" d" [inputStyle]="{ width: '5rem' }" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.new_tasks.splice(i, 1)" ariaLabel="Remove task" /></div>
        }
        <p-button label="Add task" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.new_tasks.push({ title: '', days: 1 })" />
        <div class="grid2">
          <label class="field"><span>Time impact (working days)</span><p-inputnumber [(ngModel)]="f.time_days" [min]="-60" [max]="365" fluid /></label>
          <label class="field"><span>Client pays</span><p-select [options]="whenOpts()" optionLabel="label" optionValue="value" [(ngModel)]="f.payment" fluid appendTo="body" /></label>
        </div>
        <div class="row right"><p-button label="Save" icon="pi pi-check" [disabled]="!f.stage_id || !f.reason || !f.title?.trim()" (onClick)="save()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Client approved" [modal]="true" [(visible)]="apDlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <label class="field req"><span>Who approved</span><input pInputText [(ngModel)]="ap.name" fluid /></label>
        <div class="grid2">
          <label class="field req"><span>How</span><p-select [options]="data()?.methods ?? []" [(ngModel)]="ap.method" fluid appendTo="body" /></label>
          <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="ap.date" [max]="today" fluid /></label>
        </div>
        <label class="field"><span>Signed copy (optional)</span><input type="file" (change)="attach($event)" /></label>
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="ap.note" fluid /></label>
        <p class="small muted m0">Approving adds it to the contract and its payment schedule, grows the stage budget by the cost and moves the stage's tasks by the time impact.</p>
        <div class="row right"><p-button label="Record approval" [disabled]="!ap.name?.trim() || !ap.method" (onClick)="approve()" /></div>
      </div>
    </p-dialog>

    <p-dialog [header]="reasonFor === 'reject' ? 'Client rejected' : 'Withdraw'" [modal]="true" [(visible)]="rDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>Why</span><input pInputText [(ngModel)]="reason" fluid /></label>
        <div class="row right"><p-button label="Confirm" [disabled]="!reason.trim()" (onClick)="sendReason()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .nowrap { white-space: nowrap; }
    .co-line { display: grid; grid-template-columns: minmax(0, 3fr) 5rem 7rem 7rem auto; gap: .4rem; align-items: center; }
    @media (max-width: 640px) { .co-line { grid-template-columns: 1fr 1fr; } }
  `,
})
export class ProjectChangeOrdersComponent implements OnInit {
  projectId = input.required<string>();
  changed = output<void>();
  private api = inject(Api);
  private auth = inject(AuthService);
  data = signal<any>(null);
  sev = CO_SEV;
  dlg = false; apDlg = false; rDlg = false;
  f: any = { lines: [] };
  ap: any = {};
  reason = ''; reasonFor: 'reject' | 'withdraw' = 'reject';
  private pending: any = null;
  today = new Date().toISOString().slice(0, 10);

  showCost = () => this.auth.can('finance') && this.auth.user()?.role !== 'site';
  canInvoice = () => this.auth.can('finance', 'rw');
  reasonOpts = () => Object.entries(this.data()?.reasons ?? {}).map(([value, label]) => ({ value, label }));
  whenOpts = () => Object.entries(this.data()?.payment_when ?? {}).map(([value, label]) => ({ value, label }));

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.data.set(await this.api.get(`/projects/${this.projectId()}/change_orders`));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  openNew() {
    this.f = { stage_id: null, reason: 'client_request', title: '', description: '', time_days: 0, payment: 'on_approval', new_tasks: [],
      lines: [{ description: '', qty: 1, cost_rate: null, price_rate: null }] };
    this.dlg = true;
  }

  openEdit(c: any) {
    this.f = { id: c.id, stage_id: c.stage_id, reason: c.reason, title: c.title, description: c.description ?? '', time_days: c.time_days,
      payment: c.payment, new_tasks: (c.new_tasks ?? []).map((x: any) => ({ ...x })),
      lines: c.lines.map((l: any) => ({ id: l.id, description: l.description, qty: l.qty, unit: l.unit,
        cost_rate: l.cost_rate, price_rate: l.price_rate, credit: l.credit })) };
    this.dlg = true;
  }

  async save() {
    const { id, ...body } = this.f;
    body.lines = body.lines.filter((l: any) => l.description?.trim());
    body.new_tasks = (body.new_tasks ?? []).filter((x: any) => x.title?.trim());
    if (id) await this.api.put(`/change_orders/${id}`, body, 'Change order saved');
    else await this.api.post(`/projects/${this.projectId()}/change_orders`, body, 'Change order raised');
    this.dlg = false;
    await this.refresh();
  }

  async act(c: any, what: 'price' | 'send' | 'invoice') {
    const ok = { price: 'Priced', send: 'Sent to the client', invoice: 'Invoice drafted' }[what];
    await this.api.post(`/change_orders/${c.id}/${what}`, {}, ok);
    await this.refresh();
  }

  async approveInternal(c: any) {
    await this.api.post(`/change_orders/${c.id}/approve`, {}, 'Approved');
    await this.refresh();
  }

  openApprove(c: any) {
    this.pending = c;
    this.ap = { name: '', method: 'Email', date: this.today, note: '', file_key: null };
    this.apDlg = true;
  }

  async attach(ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (file) this.ap.file_key = (await this.api.upload(file)).key;
  }

  async approve() {
    await this.api.post(`/change_orders/${this.pending.id}/approve`, this.ap, 'Approval recorded');
    this.apDlg = false;
    await this.refresh();
  }

  askReason(c: any, what: 'reject' | 'withdraw') {
    this.pending = c;
    this.reasonFor = what;
    this.reason = '';
    this.rDlg = true;
  }

  async sendReason() {
    await this.api.post(`/change_orders/${this.pending.id}/${this.reasonFor}`, { reason: this.reason }, this.reasonFor === 'reject' ? 'Recorded' : 'Withdrawn');
    this.rDlg = false;
    await this.refresh();
  }

  private async refresh() {
    await this.load();
    this.changed.emit();
  }
}
