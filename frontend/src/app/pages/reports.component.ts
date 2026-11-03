import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { TableModule } from 'primeng/table';
import { Api, SERVICE_LABEL, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** §2 conversion by source / service / salesperson, win-loss reasons, pipeline value; §16 follow-ups per user. */
@Component({
  selector: 'app-reports',
  imports: [FormsModule, ButtonModule, CardModule, InputTextModule, MessageModule, TableModule],
  template: `
    <div class="page-head">
      <div><h1>Reports</h1><p class="muted">Sales conversion and follow-up discipline. Finance and project reports arrive with their phases.</p></div>
      @if (auth.can('leads')) {
        <div class="row gap">
          <input pInputText type="date" [(ngModel)]="from" /> <span class="muted">to</span> <input pInputText type="date" [(ngModel)]="to" />
          <p-button label="Apply" icon="pi pi-filter" [outlined]="true" (onClick)="load()" />
        </div>
      }
    </div>

    @if (!auth.can('leads') && !canFollowups()) { <p-message severity="info" text="Reports available to your role arrive with later phases." /> }

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
          </p-table>
        </p-card>
      }

      <p-card styleClass="mt"><ng-template #title>Loss reasons</ng-template>
        @for (r of s.loss_reasons; track r.reason) {
          <div class="bar-row"><span class="w-16">{{ r.reason }}</span><div class="bar red"><div [style.width.%]="r.count / maxLoss() * 100"></div></div><span class="w-3 right">{{ r.count }}</span></div>
        } @empty { <p class="muted">No lost leads in this period.</p> }
      </p-card>
    }

    @if (fu(); as fu) {
      <p-card styleClass="mt"><ng-template #title>Follow-ups per user</ng-template>
        <p-table [value]="fu" size="small">
          <ng-template #header><tr><th>User</th><th class="right">Open</th><th class="right">Overdue</th><th class="right">Done</th><th class="right">Done on time</th><th class="right">Cancelled</th></tr></ng-template>
          <ng-template #body let-r><tr><td>{{ r.owner }}</td><td class="right">{{ r.open }}</td><td class="right" [class.c-bad]="r.overdue">{{ r.overdue }}</td>
            <td class="right">{{ r.done }}</td><td class="right">{{ pct(r.on_time_pct) }}</td><td class="right">{{ r.cancelled }}</td></tr></ng-template>
        </p-table>
      </p-card>
    }
  `,
})
export class ReportsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  s = signal<any>(null);
  fu = signal<any[] | null>(null);
  services = signal<string[]>([]);
  label = SERVICE_LABEL;
  from = '';
  to = '';
  groups = [{ key: 'by_source', label: 'source' }, { key: 'by_service', label: 'service' }, { key: 'by_salesperson', label: 'salesperson' }];
  canFollowups = () => ['owner', 'pm'].includes(this.auth.user()?.role ?? '');

  async ngOnInit() {
    await this.load();
    if (this.canFollowups()) this.fu.set(await this.api.get('/reports/followups'));
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
