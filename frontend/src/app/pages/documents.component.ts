import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, label } from '../core/api.service';

/** Documents & drawings (Phase F): the latest documents across your projects. Each project's Documents tab holds
 *  its folders, revisions and transmittals. */
@Component({
  selector: 'app-documents',
  imports: [FormsModule, DatePipe, RouterLink, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Documents & drawings</h1>
        <p class="muted">The latest documents across your projects. Open a project's Documents tab for its folders, revisions and transmittals.</p>
      </div>
    </div>
    <div class="row gap mb">
      <p-select [options]="kinds()" optionLabel="label" optionValue="value" [(ngModel)]="kind" [showClear]="true" placeholder="Any kind" (onChange)="load()" />
    </div>
    <p-table [value]="rows()" styleClass="p-datatable-sm" [paginator]="rows().length > 25" [rows]="25">
      <ng-template #header><tr><th>Document</th><th>Project</th><th>Folder</th><th>Rev</th><th>Updated</th></tr></ng-template>
      <ng-template #body let-d>
        <tr>
          <td><a [href]="d.current.url" target="_blank" rel="noopener">{{ d.name }}</a><div class="small muted">{{ label(d.kind) }}</div></td>
          <td><a [routerLink]="['/app/projects', d.project_id]" [queryParams]="{ tab: 'documents' }">{{ d.project_name }}</a></td>
          <td>{{ d.folder }}</td>
          <td><p-tag [value]="d.current_rev" severity="info" />@if (d.status) { <div class="small muted">{{ label(d.status) }}</div> }</td>
          <td class="small">{{ d.current.at | date: 'd MMM y' }}<div class="muted">{{ d.current.by }}</div></td>
        </tr>
      </ng-template>
      <ng-template #emptymessage><tr><td colspan="5" class="muted">No documents yet.</td></tr></ng-template>
    </p-table>
  `,
})
export class DocumentsComponent implements OnInit {
  private api = inject(Api);
  rows = signal<any[]>([]);
  kinds = signal<any[]>([]);
  kind: string | null = null;
  label = label;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const r = await this.api.get(`/documents${this.kind ? '?kind=' + this.kind : ''}`);
    this.rows.set(r.documents);
    this.kinds.set(r.kinds.map((k: string) => ({ value: k, label: label(k) })));
  }
}
