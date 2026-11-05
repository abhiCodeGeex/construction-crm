import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { TagModule } from 'primeng/tag';
import { Api, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** A signed contract (§5): value, lines, signature and the payment schedule with what is due now. */
@Component({
  selector: 'app-contract',
  imports: [DatePipe, DecimalPipe, RouterLink, ButtonModule, TagModule],
  template: `
    @if (c(); as c) {
      <div class="row-between no-print mb"><a [routerLink]="c.project_id ? ['/app/projects', c.project_id] : ['/app/leads', c.lead_id]" class="small"><i class="pi pi-arrow-left"></i> {{ c.project_code || c.lead_title }}</a>
        <p-button label="Print / save as PDF" icon="pi pi-print" [text]="true" (onClick)="print()" /></div>
      <article class="doc" [style.--brand]="brand()?.primary">
        <header class="doc-head">
          <div>@if (brand()?.logo_url) { <img [src]="brand().logo_url" alt="" class="doc-logo" /> } @else { <strong class="doc-co">{{ brand()?.name }}</strong> }</div>
          <div class="right small"><strong>{{ brand()?.name }}</strong><br />{{ brand()?.address }}<br />{{ brand()?.phone }} {{ brand()?.email }}</div>
        </header>
        <h1 class="doc-title">Contract {{ c.number }}</h1>
        <div class="row-between small doc-meta"><span>Client <strong>{{ c.client_name }}</strong> — {{ c.lead_title }}<br />From proposal {{ c.proposal_number }}</span>
          <span class="right">Signed {{ c.signed_at | date: 'd MMM y' }}<br />Value <strong>{{ fmt(c.value) }}</strong></span></div>
        @if (c.items?.length) {
          <table class="doc-table"><thead><tr><th>Item</th><th class="right">Qty</th><th class="right">Amount</th></tr></thead>
            <tbody>@for (i of c.items; track i.id) { <tr><td>{{ i.section ? i.section + ' · ' : '' }}{{ i.description }}</td><td class="right">{{ i.qty | number: '1.0-2' }} {{ i.unit || '' }}</td><td class="right">{{ fmt(i.amount) }}</td></tr> }</tbody></table>
        }
        <h3>Payment schedule</h3>
        <table class="doc-table">
          <thead><tr><th>Payment</th><th>When</th><th class="right">%</th><th class="right">Amount</th><th class="no-print">Now</th></tr></thead>
          <tbody>@for (r of c.payment_schedule; track r.id) {
            <tr><td>{{ r.name }}</td><td class="small">{{ r.trigger === 'signing' ? 'On signing' : r.trigger === 'date' ? r.date : (r.milestone?.name || r.stage + ' complete') }}
                @if (r.milestone?.due) { <span class="muted"> · planned {{ r.milestone.due | date: 'd MMM y' }}</span> }</td>
              <td class="right">{{ r.pct }}</td><td class="right">{{ fmt(r.amount) }}</td>
              <td class="no-print"><p-tag [value]="label(r.state)" [severity]="r.state === 'due' ? 'warn' : 'secondary'" /></td></tr> }</tbody>
        </table>
        @if (c.terms) { <h3>Terms</h3><p class="pre small">{{ c.terms }}</p> }
        <section class="doc-sign"><h3>Accepted</h3>
          @if (c.acceptance?.signature) { <img [src]="c.acceptance.signature" alt="Signature" class="sig-img" /> }
          <div>{{ c.acceptance?.name }} · {{ c.acceptance?.at | date: 'd MMM y, h:mm a' }} · {{ c.acceptance?.method }}{{ c.acceptance?.ip ? ' · IP ' + c.acceptance.ip : '' }}</div></section>
        <p class="small muted no-print">Invoices against this schedule arrive with Finance (Phase E). Changes to scope or value are made with change orders.</p>
      </article>
    }
  `,
})
export class ContractComponent implements OnInit {
  id = input.required<string>();
  private api = inject(Api);
  private auth = inject(AuthService);
  c = signal<any>(null);
  brand = signal<any>(null);
  label = label;

  async ngOnInit() {
    this.c.set(await this.api.get(`/contracts/${this.id()}`));
    this.brand.set(await this.api.get('/company/branding'));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  print() {
    window.print();
  }
}
