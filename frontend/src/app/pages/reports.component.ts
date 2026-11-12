import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { TableModule } from 'primeng/table';
import { Api, SERVICE_LABEL, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { ProcurementReportComponent } from './procurement-report.component';
import { InsightReportsComponent } from './insight-reports.component';

/** §2 conversion by source / service / salesperson, win-loss reasons, pipeline value; §16 follow-ups per user. */
@Component({
  selector: 'app-reports',
  imports: [FormsModule, ButtonModule, CardModule, InputTextModule, MessageModule, TableModule, ProcurementReportComponent, InsightReportsComponent],
  template: `
    <div class="page-head">
      <div><h1>Reports</h1><p class="muted">Sales conversion, follow-up discipline and project money.</p></div>
      @if (auth.can('leads')) {
        <div class="row gap">
          <input aria-label="From date" title="From date" pInputText type="date" [(ngModel)]="from" /> <span class="muted">to</span> <input aria-label="To date" title="To date" pInputText type="date" [(ngModel)]="to" />
          <p-button label="Apply" icon="pi pi-filter" [outlined]="true" (onClick)="load()" />
        </div>
      }
    </div>

    @if (!auth.can('leads') && !canFollowups() && !auth.can('reports') && !auth.can('procurement')) { <p-message severity="info" text="No reports are available to your role." /> }

    @if (s(); as s) {
      <div class="stats">
        <div class="stat-card"><span class="stat-icon indigo"><i class="pi pi-bullseye"></i></span><div><small>Leads</small><strong>{{ s.totals.leads }}</strong><small class="muted">{{ s.totals.open }} open</small></div></div>
        <div class="stat-card"><span class="stat-icon teal"><i class="pi pi-percentage"></i></span><div><small>Conversion (won ÷ closed)</small><strong>{{ pct(s.totals.conversion) }}</strong><small class="muted">{{ s.totals.won }} won · {{ s.totals.lost }} lost</small></div></div>
        <div class="stat-card"><span class="stat-icon amber"><i class="pi pi-wallet"></i></span><div><small>Open pipeline value</small><strong>{{ fmt(s.totals.open_value) }}</strong></div></div>
        <div class="stat-card"><span class="stat-icon pink"><i class="pi pi-trophy"></i></span><div><small>Won value</small><strong>{{ fmt(s.totals.won_value) }}</strong><small class="muted">Bid hit rate {{ pct(s.bids.hit_rate) }}</small></div></div>
      </div>

      <div class="grid2 top">
        @for (svc of services(); track svc) {
          <p-card><ng-template #title>{{ label[svc] }} pipeline</ng-template>
            @for (st of s.pipelines[svc]; track st.stage) {
              <div class="bar-row"><span class="w-12">{{ st.stage }}</span>
                <div class="bar"><div [style.width.%]="barPct(st.count, svc)"></div></div>
                <span class="w-3 right">{{ st.count }}</span><small class="muted w-8 right">{{ fmt(st.value) }}</small></div>
            }
          </p-card>
        }
      </div>

      @for (g of groups; track g.key) {
        <p-card styleClass="mt"><ng-template #title>Conversion by {{ g.label }}</ng-template>
          <p-table [value]="s[g.key]" size="small">
            <ng-template #header><tr><th>{{ g.label }}</th><th class="right">Leads</th><th class="right">Open</th><th class="right">Won</th><th class="right">Lost</th>
              <th class="right">Conversion</th><th class="right">Won value</th><th class="right">Avg first response</th></tr></ng-template>
            <ng-template #body let-r><tr><td>{{ g.key === 'by_service' ? label[r.key] || r.key : r.key }}</td><td class="right">{{ r.leads }}</td><td class="right">{{ r.open }}</td>
              <td class="right">{{ r.won }}</td><td class="right">{{ r.lost }}</td><td class="right"><strong>{{ pct(r.conversion) }}</strong></td>
              <td class="right">{{ fmt(r.won_value) }}</td><td class="right">{{ hours(r.avg_response_hours) }}</td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No data for this period.</td></tr></ng-template>
      </p-table>
        </p-card>
      }

      <p-card styleClass="mt"><ng-template #title>Loss reasons</ng-template>
        @for (r of s.loss_reasons; track r.reason) {
          <div class="bar-row"><span class="w-16">{{ r.reason }}</span><div class="bar red"><div [style.width.%]="r.count / maxLoss() * 100"></div></div><span class="w-3 right">{{ r.count }}</span></div>
        } @empty { <p class="muted">No lost leads in this period.</p> }
      </p-card>

      <div class="stats mt">
        <div class="stat-card"><div><small>Site visit → won</small><strong>{{ pct(s.visit_to_win) }}</strong><small class="muted">of closed leads with a visit</small></div></div>
        <div class="stat-card"><div><small>Proposal → won</small><strong>{{ pct(s.proposal_to_win) }}</strong><small class="muted">of closed leads with a proposal</small></div></div>
        <div class="stat-card"><div><small>Average discount</small><strong>{{ pct(s.avg_discount_pct) }}</strong><small class="muted">first proposal → accepted</small></div></div>
        <div class="stat-card"><div><small>Contacted within {{ s.response_target_minutes }} min</small><strong>{{ pct(s.response_target_met_pct) }}</strong><small class="muted">response target met</small></div></div>
      </div>

      <div class="grid2 top mt">
        @for (svc of services(); track svc) {
          @if (s.funnel?.[svc]; as f) {
            <p-card><ng-template #title>Funnel — {{ label[svc] }}</ng-template>
              @for (st of f; track st.stage) {
                <div class="bar-row"><span class="w-16">{{ st.stage }}</span><div class="bar"><div [style.width.%]="f[0].reached ? st.reached / f[0].reached * 100 : 0"></div></div>
                  <span class="w-3 right">{{ st.reached }}</span><small class="muted w-6 right">{{ st.drop_off_pct != null ? '−' + st.drop_off_pct + '%' : '' }}</small></div>
              }
            </p-card>
          }
        }
        <p-card><ng-template #title>Average time in each stage</ng-template>
          <p-table [value]="s.time_in_stage" size="small">
            <ng-template #body let-r><tr><td>{{ r.stage }}</td><td class="right">{{ r.avg_days }} days</td><td class="right muted">{{ r.leads }} lead(s)</td></tr></ng-template>
            <ng-template #emptymessage><tr><td class="muted">No data</td></tr></ng-template>
          </p-table>
        </p-card>
        <p-card><ng-template #title>Forecast by expected close month</ng-template>
          <p-table [value]="s.forecast" size="small">
            <ng-template #header><tr><th>Month</th><th class="right">Leads</th><th class="right">Value</th><th class="right">Weighted</th></tr></ng-template>
            <ng-template #body let-r><tr><td>{{ r.month }}</td><td class="right">{{ r.leads }}</td><td class="right">{{ fmt(r.value) }}</td><td class="right"><strong>{{ fmt(r.weighted) }}</strong></td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="4" class="muted">Set expected close dates on leads to see the forecast.</td></tr></ng-template>
          </p-table>
        </p-card>
        <p-card><ng-template #title>Losses to competitors</ng-template>
          <p-table [value]="s.competitors" size="small">
            <ng-template #body let-r><tr><td>{{ r.competitor }}</td><td class="right">{{ r.losses }} lost</td><td class="right">{{ fmt(r.value_lost) }}</td></tr></ng-template>
            <ng-template #emptymessage><tr><td class="muted">No competitor recorded on lost leads.</td></tr></ng-template>
          </p-table>
        </p-card>
        <p-card><ng-template #title>Cost to acquire and return per source</ng-template>
          <p-table [value]="s.cost_by_source" size="small">
            <ng-template #header><tr><th>Source</th><th class="right">Pre-sales spend</th><th class="right">Won</th><th class="right">Cost per win</th><th class="right">Return</th></tr></ng-template>
            <ng-template #body let-r><tr><td>{{ r.source }}</td><td class="right">{{ fmt(r.spent) }}</td><td class="right">{{ r.won }}</td>
              <td class="right">{{ fmt(r.cost_per_win) }}</td><td class="right">{{ r.roi != null ? r.roi + '×' : '—' }}</td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No leads or spending in this period.</td></tr></ng-template>
      </p-table>
        </p-card>
        <p-card><ng-template #title>Salesperson leaderboard</ng-template>
          <p-table [value]="s.leaderboard" size="small">
            <ng-template #header><tr><th>Salesperson</th><th class="right">Leads</th><th class="right">Won</th><th class="right">Conversion</th><th class="right">Won value</th><th class="right">Contacts (30 d)</th></tr></ng-template>
            <ng-template #body let-r><tr><td>{{ r.salesperson }}</td><td class="right">{{ r.leads }}</td><td class="right">{{ r.won }}</td><td class="right">{{ pct(r.conversion) }}</td>
              <td class="right">{{ fmt(r.won_value) }}</td><td class="right">{{ r.activities_30d }}</td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No salespeople with leads in this period.</td></tr></ng-template>
      </p-table>
        </p-card>
      </div>
    }

    @if (fu(); as fu) {
      <p-card styleClass="mt"><ng-template #title>Follow-ups per user</ng-template>
        <p-table [value]="fu" size="small">
          <ng-template #header><tr><th>User</th><th class="right">Open</th><th class="right">Overdue</th><th class="right">Done</th><th class="right">Done on time</th><th class="right">Cancelled</th></tr></ng-template>
          <ng-template #body let-r><tr><td>{{ r.owner }}</td><td class="right">{{ r.open }}</td><td class="right" [class.c-bad]="r.overdue">{{ r.overdue }}</td>
            <td class="right">{{ r.done }}</td><td class="right">{{ pct(r.on_time_pct) }}</td><td class="right">{{ r.cancelled }}</td></tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No follow-ups in this period.</td></tr></ng-template>
      </p-table>
      </p-card>
    }
    @if (fin(); as f) {
      <p-card header="Project money" styleClass="mt">
        <p-table [value]="f.projects" size="small" [scrollable]="true">
          <ng-template #header><tr><th>Project</th><th class="right">Value (revised)</th><th class="right">Invoiced</th><th class="right">Received</th>
            <th class="right">Owed</th><th class="right">To invoice</th>@if (f.money_view) { <th class="right">Budget</th><th class="right">Actual</th><th class="right">Margin</th> }</tr></ng-template>
          <ng-template #body let-r><tr><td>{{ r.code }} {{ r.name }}</td><td class="right">{{ fmt(r.revised_value) }}</td><td class="right">{{ fmt(r.invoiced) }}</td>
            <td class="right">{{ fmt(r.received) }}</td><td class="right" [class.c-warn]="r.receivable > 0">{{ fmt(r.receivable) }}</td><td class="right">{{ fmt(r.to_invoice) }}</td>
            @if (f.money_view) { <td class="right">{{ fmt(r.budget) }}</td><td class="right" [class.c-bad]="r.budget && r.actual > r.budget">{{ fmt(r.actual) }}</td>
              <td class="right" [class.c-bad]="r.margin < 0">{{ fmt(r.margin) }}@if (r.margin_pct !== null) { <span class="muted small"> {{ r.margin_pct }}%</span> }</td> }</tr></ng-template>
          <ng-template #footer><tr><th>Total</th><th class="right">{{ fmt(f.total.revised_value) }}</th><th class="right">{{ fmt(f.total.invoiced) }}</th>
            <th class="right">{{ fmt(f.total.received) }}</th><th class="right">{{ fmt(f.total.receivable) }}</th><th class="right">{{ fmt(f.total.to_invoice) }}</th>
            @if (f.money_view) { <th class="right">{{ fmt(f.total.budget) }}</th><th class="right">{{ fmt(f.total.actual) }}</th><th class="right">{{ fmt(f.total.margin) }}</th> }</tr></ng-template>
          <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No projects.</td></tr></ng-template>
        </p-table>
      </p-card>
      <div class="grid2 mt">
        <p-card header="Owed by clients, by age">
          @for (b of f.ageing; track b.key) { <div class="row-between"><span>{{ b.label }}</span><strong [class.c-bad]="b.key !== 'current' && b.total > 0">{{ fmt(b.total) }}</strong></div> }
        </p-card>
        <p-card header="Approved change orders by reason">
          @for (c of f.change_orders; track c.reason) { <div class="row-between"><span>{{ c.reason }} <span class="muted small">× {{ c.count }}</span></span><strong>{{ fmt(c.total) }}</strong></div> }
          @empty { <span class="muted small">None yet.</span> }
        </p-card>
        @if (f.money_view) {
          <p-card header="Costs by category">
            @for (c of f.by_category; track c.category) { <div class="row-between"><span>{{ c.category }}</span><strong>{{ fmt(c.total) }}</strong></div> }
            @empty { <span class="muted small">No approved costs yet.</span> }
          </p-card>
          <p-card header="Stages over budget">
            @for (o of f.over_budget; track o.project_id + o.stage) { <div class="row-between"><span>{{ o.project }} · {{ o.stage }}</span><strong class="c-bad">+{{ fmt(o.over) }}</strong></div> }
            @empty { <span class="muted small">None.</span> }
          </p-card>
        }
      </div>
    }
    @if (auth.can('procurement')) {
      <h2 class="mt">Procurement</h2>
      <app-procurement-report />
    }
    @if (auth.can('reports') || auth.can('followups')) {
      <h2 class="mt">Projects, cash flow and team</h2>
      <app-insight-reports />
    }
  `,
})
export class ReportsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  s = signal<any>(null);
  fu = signal<any[] | null>(null);
  services = signal<string[]>([]);
  fin = signal<any>(null);
  label = SERVICE_LABEL;
  from = '';
  to = '';
  groups = [{ key: 'by_source', label: 'source' }, { key: 'by_service', label: 'service' }, { key: 'by_salesperson', label: 'salesperson' }];
  canFollowups = () => ['owner', 'pm'].includes(this.auth.user()?.role ?? '');

  async ngOnInit() {
    await this.load();
    if (this.canFollowups()) this.fu.set(await this.api.get('/reports/followups'));
    if (this.auth.can('reports')) this.fin.set(await this.api.get('/reports/finance'));
  }

  async load() {
    if (!this.auth.can('leads')) return;
    const p = new URLSearchParams();
    if (this.from) p.set('from', this.from);
    if (this.to) p.set('to', this.to);
    const s = await this.api.get(`/reports/sales?${p}`);
    this.s.set(s);
    this.services.set(Object.keys(s.pipelines));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  pct(v: number | null) {
    return v == null ? '—' : `${v}%`;
  }

  hours(h: number | null) {
    return h == null ? '—' : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${h} h` : `${Math.round(h / 24)} d`;
  }

  barPct(count: number, svc: string) {
    const max = Math.max(1, ...this.s().pipelines[svc].map((x: any) => x.count));
    return (count / max) * 100;
  }

  maxLoss() {
    return Math.max(1, ...this.s().loss_reasons.map((r: any) => r.count));
  }
}
