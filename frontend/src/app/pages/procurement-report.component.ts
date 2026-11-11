import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { CardModule } from 'primeng/card';
import { TableModule } from 'primeng/table';
import { Api, label, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Procurement report (Phase H): PO status, late deliveries, supplier on-time %, open requests; spend by supplier and
 *  price variance only for roles that see money (the server leaves them out for the others). */
@Component({
  selector: 'app-procurement-report',
  imports: [DatePipe, CardModule, TableModule],
  template: `
    @if (r(); as r) {
      <div class="stats">
        <div class="stat-card"><span class="stat-icon indigo"><i class="pi pi-inbox"></i></span><div><small>Open requests</small><strong>{{ r.open_requests }}</strong></div></div>
        <div class="stat-card"><span class="stat-icon pink"><i class="pi pi-clock"></i></span><div><small>Late deliveries</small><strong [class.c-bad]="r.late.length">{{ r.late.length }}</strong></div></div>
        @if (r.money_view) {
          <div class="stat-card"><span class="stat-icon teal"><i class="pi pi-wallet"></i></span><div><small>Spend (approved bills)</small><strong>{{ fmt(spendTotal()) }}</strong></div></div>
        }
      </div>
      <div class="grid2 top">
        <p-card header="Purchase orders by status">
          @for (x of r.po_status; track x.status) {
            <div class="row-between"><span>{{ label(x.status) }} <span class="muted small">× {{ x.count }}</span></span>@if (r.money_view) { <strong>{{ fmt(x.value) }}</strong> }</div>
          } @empty { <span class="muted small">No purchase orders yet.</span> }
        </p-card>
        <p-card header="Suppliers on time">
          @for (s of r.suppliers; track s.vendor) {
            <div class="row-between"><span>{{ s.vendor }} <span class="muted small">{{ s.orders }} order(s)</span></span>
              <strong [class.c-bad]="s.on_time_pct !== null && s.on_time_pct < 80">{{ s.on_time_pct === null ? '—' : s.on_time_pct + '%' }}</strong></div>
          } @empty { <span class="muted small">No orders with a delivery date.</span> }
        </p-card>
        <p-card header="Late deliveries">
          @for (l of r.late; track l.number) {
            <div class="row-between small"><span>{{ l.number }} · {{ l.vendor }} · {{ l.project }}</span><strong class="c-bad">{{ l.days_late }} d</strong></div>
          } @empty { <span class="muted small">Nothing late.</span> }
        </p-card>
        @if (r.money_view) {
          <p-card header="Spend by supplier">
            @for (s of r.spend; track s.vendor) { <div class="row-between"><span>{{ s.vendor }}</span><strong>{{ fmt(s.amount) }}</strong></div> }
            @empty { <span class="muted small">No approved bills yet.</span> }
          </p-card>
        }
      </div>
      @if (r.money_view && r.price_variance?.length) {
        <p-card header="Billed rate against the rate library" styleClass="mt">
          <p-table [value]="r.price_variance" size="small">
            <ng-template #header><tr><th>Item</th><th>Supplier</th><th class="right">Library</th><th class="right">Billed</th><th class="right">Variance</th></tr></ng-template>
            <ng-template #body let-v><tr><td>{{ v.item }}</td><td>{{ v.vendor }}</td><td class="right">{{ fmt(v.library_rate) }}</td><td class="right">{{ fmt(v.billed_rate) }}</td>
              <td class="right" [class.c-bad]="v.variance_pct > 5">{{ v.variance_pct }}%</td></tr></ng-template>
          </p-table>
        </p-card>
      }
    }
  `,
})
export class ProcurementReportComponent implements OnInit {
  private api = inject(Api);
  private auth = inject(AuthService);
  r = signal<any>(null);
  label = label;

  async ngOnInit() {
    this.r.set(await this.api.get('/reports/procurement'));
  }

  spendTotal() {
    return (this.r()?.spend ?? []).reduce((a: number, s: any) => a + s.amount, 0);
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }
}
