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

const COST_SEV: Record<string, 'secondary' | 'success' | 'danger' | 'warn'> = {
  draft: 'secondary', submitted: 'warn', approved: 'success', rejected: 'danger', void: 'secondary',
};

/** Finance (Phase E). Block 1: every project's costs in one list, waiting approvals first. Costs are recorded,
 *  approved and voided on each project's Money tab, where the stage budget is in view. */
@Component({
  selector: 'app-finance',
  imports: [FormsModule, DatePipe, RouterLink, SelectButtonModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Finance</h1>
        <p class="muted">Costs across your projects. Record, approve and void them on the project's Money tab, next to its stage budgets.</p>
      </div>
    </div>
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
  category: string | null = null;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const q = new URLSearchParams();
    if (this.status) q.set('status', this.status);
    if (this.category) q.set('category', this.category);
    const r = await this.api.get(`/finance/costs?${q}`);
    this.rows.set(r.costs);
    this.categories.set(r.categories);
  }

  total() {
    return this.rows().reduce((a, c) => a + (c.amount || 0), 0);
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }
}
