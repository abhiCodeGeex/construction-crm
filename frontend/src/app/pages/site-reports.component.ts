import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { InputTextModule } from 'primeng/inputtext';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api } from '../core/api.service';

/** Site reports (Phase F): one day across your active projects — who reported, headcount, weather — and who has not. */
@Component({
  selector: 'app-site-reports',
  imports: [FormsModule, DatePipe, RouterLink, InputTextModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Site reports</h1>
        <p class="muted">The daily report of every active project. Write and read them on the project's Site reports tab.</p>
      </div>
      <input pInputText type="date" aria-label="Day" [(ngModel)]="day" (ngModelChange)="load()" />
    </div>
    @if (data(); as d) {
      <p-table [value]="d.rows" styleClass="p-datatable-sm">
        <ng-template #header><tr><th>Project</th><th>Site supervisor</th><th>Report</th><th>On site</th><th>Weather</th><th>Issues / delays</th></tr></ng-template>
        <ng-template #body let-r>
          <tr>
            <td><a [routerLink]="['/app/projects', r.project_id]" [queryParams]="{ tab: 'site' }">{{ r.code }} {{ r.name }}</a></td>
            <td>{{ r.supervisors.join(', ') || '—' }}</td>
            <td>@if (r.report) { <p-tag value="written" severity="success" /> <span class="small muted">{{ r.report.author_name }}</span> }
              @else { <p-tag value="missing" [severity]="r.supervisors.length ? 'danger' : 'secondary'" /> }</td>
            <td>{{ r.report?.headcount ?? '—' }}</td>
            <td>{{ r.report?.weather?.kind || '—' }}</td>
            <td>@if (r.report) { {{ r.report.issues.length }} / {{ r.report.delays.length }} } @else { — }</td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="6" class="muted">No active projects.</td></tr></ng-template>
      </p-table>
    }
  `,
})
export class SiteReportsComponent implements OnInit {
  private api = inject(Api);
  data = signal<any>(null);
  day = new Date().toISOString().slice(0, 10);

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.data.set(await this.api.get(`/site-reports?date=${this.day}`));
  }
}
