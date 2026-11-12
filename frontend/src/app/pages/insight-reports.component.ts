import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { CardModule } from 'primeng/card';
import { TableModule } from 'primeng/table';
import { Api, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Reports added in Phase I block 5: projects (delayed, milestones, open items), cash flow, team workload and what
 *  has waited longest on the client. Each part loads only for roles that may see it. */
@Component({
  selector: 'app-insight-reports',
  imports: [DatePipe, RouterLink, CardModule, TableModule],
  template: `
    @if (proj(); as r) {
      <div class="grid2 top mt">
        <p-card header="Delayed projects">
          @for (x of r.delayed; track x.project_id) {
            <div class="row-between small"><a [routerLink]="['/app/projects', x.project_id]">{{ x.project }}</a>
              <span>@if (x.late_days) { <strong class="c-bad">{{ x.late_days }} d late</strong> · } {{ x.late_tasks }} late task(s)@if (x.late_stages.length) { · {{ x.late_stages.join(', ') }} }</span></div>
          } @empty { <span class="muted small">Nothing is late.</span> }
        </p-card>
        <p-card header="Milestones late or due in 14 days">
          @for (m of r.milestones; track $index) {
            <div class="row-between small"><span>{{ m.milestone }} <span class="muted">· {{ m.project }}</span></span><strong [class.c-bad]="m.late">{{ m.due | date: 'd MMM' }}</strong></div>
          } @empty { <span class="muted small">No milestones due.</span> }
        </p-card>
      </div>
      @if (r.open_items.length) {
        <p-card header="Open snags, issues and approvals" styleClass="mt">
          <p-table [value]="r.open_items" size="small">
            <ng-template #header><tr><th>Project</th><th class="num">Snags</th><th class="num">Late snags</th><th class="num">Issues</th><th class="num">Approvals pending</th><th class="num">Change orders with the client</th></tr></ng-template>
            <ng-template #body let-x><tr><td><a [routerLink]="['/app/projects', x.project_id]">{{ x.project }}</a></td><td class="num">{{ x.snags_open }}</td>
              <td class="num" [class.c-bad]="x.snags_late">{{ x.snags_late }}</td><td class="num">{{ x.issues_open }}</td><td class="num">{{ x.approvals_pending }}</td>
              <td class="num">{{ x.change_orders_waiting }}</td></tr></ng-template>
          </p-table>
        </p-card>
      }
    }
    @if (cash(); as c) {
      <p-card header="Cash flow" styleClass="mt">
        <p-table [value]="c.months" size="small">
          <ng-template #header><tr><th>Month</th><th class="num">In</th><th class="num">Out</th><th class="num">Due in</th><th class="num">Due out</th><th class="num">Net</th><th class="num">Running</th></tr></ng-template>
          <ng-template #body let-m><tr [class.muted]="m.past"><td>{{ m.month }}</td><td class="num">{{ fmt(m.in) }}</td><td class="num">{{ fmt(m.out) }}</td>
            <td class="num">{{ fmt(m.expected_in) }}</td><td class="num">{{ fmt(m.expected_out) }}</td><td class="num" [class.c-bad]="m.net < 0">{{ fmt(m.net) }}</td>
            <td class="num" [class.c-bad]="m.running < 0">{{ fmt(m.running) }}</td></tr></ng-template>
        </p-table>
        <p class="small muted m0 mt-xs">Past months: money received and paid. This month on: what invoices, supplier bills and open purchase orders say is due (late items count as due now).</p>
      </p-card>
    }
    @if (team(); as t) {
      <p-card [header]="'Team workload · next 4 weeks (' + t.capacity_days + ' working days)'" styleClass="mt">
        <p-table [value]="t.people" size="small">
          <ng-template #header><tr><th>Person</th><th class="num">Open tasks</th><th class="num">Overdue</th><th class="num">Days of work</th><th class="num">Load</th></tr></ng-template>
          <ng-template #body let-x><tr><td>{{ x.name }} <span class="small muted">{{ x.projects.length }} project(s)</span></td><td class="num">{{ x.open }}</td>
            <td class="num" [class.c-bad]="x.overdue">{{ x.overdue }}</td><td class="num">{{ x.load_days }}</td>
            <td class="num" [class.c-bad]="x.utilisation_pct > 100" [class.c-warn]="x.utilisation_pct > 80 && x.utilisation_pct <= 100">{{ x.utilisation_pct }}%</td></tr></ng-template>
        </p-table>
      </p-card>
    }
    @if (wait(); as w) {
      <div class="grid2 top mt">
        <p-card header="Client approvals waiting longest">
          @for (x of w.approvals; track $index) { <div class="row-between small"><span>{{ x.kind }}: {{ x.what }} <span class="muted">· {{ x.project }}</span></span><strong [class.c-bad]="x.days > 7">{{ x.days }} d</strong></div> }
          @empty { <span class="muted small">Nothing waiting on the client.</span> }
        </p-card>
        <p-card header="Payments waiting longest">
          @for (x of w.payments; track $index) { <div class="row-between small"><span>{{ x.what }} · {{ x.client }} <span class="muted">· {{ fmt(x.amount) }}</span></span><strong class="c-bad">{{ x.days }} d late</strong></div> }
          @empty { <span class="muted small">No late payments.</span> }
        </p-card>
      </div>
    }
  `,
  styles: `.num { text-align: right; font-variant-numeric: tabular-nums; }`,
})
export class InsightReportsComponent implements OnInit {
  private api = inject(Api);
  private auth = inject(AuthService);
  proj = signal<any>(null);
  cash = signal<any>(null);
  team = signal<any>(null);
  wait = signal<any>(null);

  async ngOnInit() {
    const role = this.auth.user()?.role ?? '';
    const jobs: Promise<void>[] = [];
    if (this.auth.can('reports')) {
      jobs.push(this.api.get('/reports/projects').then((r) => this.proj.set(r)));
      jobs.push(this.api.get('/reports/team').then((r) => this.team.set(r)));
    }
    if (this.auth.can('finance') && role !== 'site') jobs.push(this.api.get('/reports/cashflow').then((r) => this.cash.set(r)).catch(() => undefined));
    if (this.auth.can('followups')) jobs.push(this.api.get('/reports/waiting').then((r) => this.wait.set(r)));
    await Promise.all(jobs);
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }
}
