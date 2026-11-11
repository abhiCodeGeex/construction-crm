import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { CO_SEV } from './projects/project-change-orders.component';

/** Change orders across your projects (Phase E block 4). Raised, priced and decided on each project's Change orders tab. */
@Component({
  selector: 'app-change-orders',
  imports: [FormsModule, DatePipe, RouterLink, SelectButtonModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Change orders</h1>
        <p class="muted">Every change to scope, price or time across your projects. Raise and decide them on the project's Change orders tab.</p>
      </div>
    </div>
    <div class="row gap wrap mb">
      <p-selectbutton [options]="statuses" [(ngModel)]="status" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" />
      <span class="muted small grow right">{{ rows().length }} · {{ fmt(total()) }}</span>
    </div>
    <p-table [value]="rows()" styleClass="p-datatable-sm" [paginator]="rows().length > 25" [rows]="25">
      <ng-template #header><tr><th>Number</th><th>Project</th><th>Change</th><th class="num">Price</th><th>Time</th><th>Status</th></tr></ng-template>
      <ng-template #body let-c>
        <tr>
          <td>{{ c.number }}<div class="small muted">{{ c.created_at | date: 'd MMM y' }}</div></td>
          <td><a [routerLink]="['/app/projects', c.project_id]" [queryParams]="{ tab: 'changes' }">{{ c.project_code }} {{ c.project_name }}</a>
            <div class="small muted">{{ c.stage_name }}</div></td>
          <td>{{ c.title }}<div class="small muted">{{ reasons()[c.reason] }}</div></td>
          <td class="num">{{ c.totals.total ? fmt(c.totals.total) : '—' }}</td>
          <td>{{ c.time_days ? (c.time_days > 0 ? '+' : '') + c.time_days + ' days' : '—' }}</td>
          <td><p-tag [value]="c.status" [severity]="sev[c.status]" /></td>
        </tr>
      </ng-template>
      <ng-template #emptymessage><tr><td colspan="6" class="muted">Nothing here.</td></tr></ng-template>
    </p-table>
  `,
  styles: `.num { text-align: right; font-variant-numeric: tabular-nums; }`,
})
export class ChangeOrdersComponent implements OnInit {
  private api = inject(Api);
  private auth = inject(AuthService);
  rows = signal<any[]>([]);
  reasons = signal<Record<string, string>>({});
  sev = CO_SEV;
  statuses = [{ label: 'With the client', value: 'sent' }, { label: 'Being priced', value: 'draft' }, { label: 'Priced', value: 'priced' },
    { label: 'Approved', value: 'approved' }, { label: 'Rejected', value: 'rejected' }, { label: 'All', value: '' }];
  status = 'sent';

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const r = await this.api.get(`/change_orders${this.status ? '?status=' + this.status : ''}`);
    this.rows.set(r.change_orders);
    this.reasons.set(r.reasons);
  }

  total() {
    return this.rows().reduce((a, c) => a + (c.totals?.total || 0), 0);
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }
}
