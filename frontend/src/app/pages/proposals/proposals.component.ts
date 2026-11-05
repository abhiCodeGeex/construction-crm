import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { Api, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** Proposals & estimates (Phase D): every proposal with its status and views, and every signed contract. */
@Component({
  selector: 'app-proposals',
  imports: [FormsModule, DatePipe, SelectButtonModule, TableModule, TabsModule, TagModule],
  template: `
    <div class="page-head"><div><h1>Proposals & contracts</h1><p class="muted">Proposals are made from a lead (Leads → a lead → Proposals). Accepted proposals become contracts.</p></div></div>
    <p-tabs value="proposals">
      <p-tablist><p-tab value="proposals"><i class="pi pi-file-edit mr"></i>Proposals</p-tab><p-tab value="contracts" (click)="loadContracts()"><i class="pi pi-verified mr"></i>Contracts</p-tab></p-tablist>
      <p-tabpanels>
        <p-tabpanel value="proposals">
          <div class="filters"><p-selectbutton [options]="statuses" [(ngModel)]="status" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" /></div>
          <p-table [value]="rows()" size="small" [rowHover]="true" [paginator]="rows().length > 25" [rows]="25">
            <ng-template #header><tr><th>Proposal</th><th>Lead</th><th>Type</th><th class="right">Total</th><th>Valid until</th><th>Status</th><th>Opened</th></tr></ng-template>
            <ng-template #body let-p><tr class="clickable" (click)="router.navigate(['/app/proposals', p.id])">
              <td><strong>{{ p.number }}</strong> v{{ p.version }}<br /><small class="muted">{{ p.title }}</small></td><td>{{ p.lead_title }}</td>
              <td><small>{{ label(p.type) }}</small></td><td class="right">{{ fmt(p.value) }}</td><td><small>{{ p.valid_until | date: 'd MMM y' }}</small></td>
              <td><p-tag [value]="label(p.status)" [severity]="sev(p.status)" /></td>
              <td><small>{{ p.view_count ? p.view_count + '× · ' + (p.last_viewed_at | date: 'd MMM') : '—' }}</small></td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="7" class="muted center">No proposals</td></tr></ng-template>
          </p-table>
        </p-tabpanel>
        <p-tabpanel value="contracts">
          <p-table [value]="contracts()" size="small" [rowHover]="true">
            <ng-template #header><tr><th>Contract</th><th>Client</th><th>Lead / project</th><th class="right">Value</th><th>Signed</th><th>Due now</th></tr></ng-template>
            <ng-template #body let-c><tr class="clickable" (click)="router.navigate(['/app/contracts', c.id])">
              <td><strong>{{ c.number }}</strong><br /><small class="muted">from {{ c.proposal_number }}</small></td><td>{{ c.client_name }}</td>
              <td>{{ c.lead_title }}{{ c.project_code ? ' · ' + c.project_code : '' }}</td><td class="right">{{ fmt(c.value) }}</td>
              <td><small>{{ c.signed_at | date: 'd MMM y' }}</small></td><td class="right">{{ fmt(due(c)) }}</td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="6" class="muted center">No contracts yet</td></tr></ng-template>
          </p-table>
        </p-tabpanel>
      </p-tabpanels>
    </p-tabs>
  `,
})
export class ProposalsComponent implements OnInit {
  private api = inject(Api);
  private auth = inject(AuthService);
  router = inject(Router);
  rows = signal<any[]>([]);
  contracts = signal<any[]>([]);
  label = label;
  status = '';
  statuses = [{ label: 'All', value: '' }, { label: 'Draft', value: 'draft' }, { label: 'Sent', value: 'sent' }, { label: 'Accepted', value: 'accepted' },
    { label: 'Changes asked', value: 'revision_requested' }, { label: 'Rejected', value: 'rejected' }, { label: 'Expired', value: 'expired' }];

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.rows.set(await this.api.get(`/proposals${this.status ? '?status=' + this.status : ''}`));
  }

  async loadContracts() {
    this.contracts.set(await this.api.get('/contracts'));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  sev(s: string): any {
    return ({ accepted: 'success', sent: 'info', draft: 'secondary', rejected: 'danger', expired: 'danger', revision_requested: 'warn' } as any)[s] ?? 'secondary';
  }

  due(c: any) {
    return (c.payment_schedule ?? []).filter((r: any) => r.state === 'due').reduce((a: number, r: any) => a + r.amount, 0);
  }
}
