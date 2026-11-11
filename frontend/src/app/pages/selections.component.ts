import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { SEL_SEV } from './projects/project-selections.component';

/** Selections (Phase F): items across your projects, those waiting on the client first. */
@Component({
  selector: 'app-selections',
  imports: [FormsModule, DatePipe, RouterLink, SelectButtonModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Selections</h1>
        <p class="muted">Finishes and fittings the clients choose, across your projects. Options and choices are kept on each project's Selections tab.</p>
      </div>
    </div>
    <p-selectbutton class="mb block" [options]="filters" [(ngModel)]="filter" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" />
    <p-table [value]="rows()" styleClass="p-datatable-sm" [paginator]="rows().length > 25" [rows]="25">
      <ng-template #header><tr><th>Item</th><th>Project</th><th>Choose by</th><th class="num">Allowance</th><th class="num">Chosen</th><th>Status</th></tr></ng-template>
      <ng-template #body let-s>
        <tr>
          <td>{{ s.item }}<div class="small muted">{{ s.room }}</div></td>
          <td><a [routerLink]="['/app/projects', s.project_id]" [queryParams]="{ tab: 'selections' }">{{ s.project_name }}</a><div class="small muted">{{ s.stage_name }}</div></td>
          <td [class.c-bad]="s.overdue">{{ s.due_date ? (s.due_date | date: 'd MMM y') : '—' }}</td>
          <td class="num">{{ fmt(s.allowance) }}</td>
          <td class="num">@if (s.chosen) { {{ fmt(s.chosen.price) }}<div class="small" [class.c-bad]="s.difference > 0">{{ s.difference > 0 ? '+' : '' }}{{ fmt(s.difference) }}</div> } @else { — }</td>
          <td><p-tag [value]="statuses()[s.status]" [severity]="sev[s.status]" /></td>
        </tr>
      </ng-template>
      <ng-template #emptymessage><tr><td colspan="6" class="muted">Nothing here.</td></tr></ng-template>
    </p-table>
  `,
  styles: `.num { text-align: right; font-variant-numeric: tabular-nums; }`,
})
export class SelectionsComponent implements OnInit {
  private api = inject(Api);
  private auth = inject(AuthService);
  rows = signal<any[]>([]);
  statuses = signal<Record<string, string>>({});
  sev = SEL_SEV;
  filters = [{ label: 'Waiting on the client', value: 'open,options_sent' }, { label: 'To order', value: 'chosen,confirmed' },
    { label: 'Ordered', value: 'ordered' }, { label: 'Installed', value: 'installed' }, { label: 'All', value: '' }];
  filter = 'open,options_sent';

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const r = await this.api.get(`/selections${this.filter ? '?status=' + this.filter : ''}`);
    this.rows.set(r.selections);
    this.statuses.set(r.statuses);
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }
}
