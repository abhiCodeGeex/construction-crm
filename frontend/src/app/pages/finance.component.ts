import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
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
  imports: [FormsModule, DatePipe, RouterLink, SelectButtonModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Finance</h1>
        <p class="muted">Costs and invoices across your projects. Record costs and raise invoices on the project's Money tab, next to its budgets and payment schedule.</p>
      </div>
    </div>
    <p-selectbutton class="mb block" [options]="views" [(ngModel)]="view" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" />
    @if (view === 'receivables') {
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

  async ngOnInit() {
    await this.load();
  }

  async load() {
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
