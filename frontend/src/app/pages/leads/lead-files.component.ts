import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, label } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** Lead files (C+3): photos, client drawings, brief, proposals and other files, by folder and room. */
@Component({
  selector: 'app-lead-files',
  imports: [FormsModule, DatePipe, ButtonModule, CardModule, InputTextModule, SelectModule, SelectButtonModule, TableModule, TagModule],
  template: `
    <p-card>
      <ng-template #title>Files</ng-template>
      @if (editable()) {
        <div class="row gap wrap mb">
          <p-select [options]="folderOpts()" [(ngModel)]="folder" optionLabel="label" optionValue="value" />
          <p-select [options]="rooms()" [(ngModel)]="roomId" optionLabel="name" optionValue="id" placeholder="Room (optional)" [showClear]="true" />
          <input pInputText [(ngModel)]="caption" placeholder="Caption (optional)" class="grow" />
          <label class="p-button p-button-sm p-button-outlined"><i class="pi pi-upload mr"></i>Upload
            <input type="file" hidden (change)="upload($event)" accept=".pdf,.png,.jpg,.jpeg,.webp,.heic,.doc,.docx,.xlsx,.xls,.csv,.dwg,.dxf,.mp4,.mov" /></label>
        </div>
      }
      <div class="filters"><p-selectbutton [options]="filterOpts()" [ngModel]="filter()" (onChange)="filter.set($event.value ?? '')" optionLabel="label" optionValue="value" [allowEmpty]="false" /> <small class="muted">{{ shown().length }} of {{ files().length }} files</small></div>
      <p-table [value]="shown()" size="small">
        <ng-template #header><tr><th>File</th><th>Folder</th><th>Room</th><th>Added</th><th></th></tr></ng-template>
        <ng-template #body let-f><tr>
          <td><a href="" (click)="$event.preventDefault(); api.openFile(f.url)">{{ f.name }}</a>@if (f.caption) { <br /><small class="muted">{{ f.caption }}</small> }</td>
          <td><p-tag [value]="label(f.folder)" severity="secondary" /></td><td>{{ f.room || '—' }}</td>
          <td><small>{{ f.created_at | date: 'd MMM y' }} · {{ (f.size / 1024 / 1024).toFixed(1) }} MB</small></td>
          <td class="right">@if (editable() && (f.created_by === auth.user()?.id || auth.user()?.role === 'owner')) {
            <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="remove(f)" /> }</td></tr></ng-template>
        <ng-template #emptymessage><tr><td colspan="5" class="muted center">No files</td></tr></ng-template>
      </p-table>
    </p-card>
  `,
})
export class LeadFilesComponent implements OnInit {
  lead = input.required<any>();
  changed = output<void>();
  api = inject(Api);
  auth = inject(AuthService);
  files = signal<any[]>([]);
  folders = signal<string[]>([]);
  rooms = computed(() => this.lead()?.measurements?.rooms ?? []);
  editable = computed(() => this.lead()?.status === 'open' && this.lead()?.can_edit);
  folderOpts = computed(() => this.folders().map((f) => ({ value: f, label: label(f) })));
  filterOpts = computed(() => [{ value: '', label: 'All' }, ...this.folderOpts()]);
  shown = computed(() => this.files().filter((f) => !this.filter() || f.folder === this.filter()));
  label = label;
  folder = 'photos';
  roomId: string | null = null;
  caption = '';
  filter = signal('');

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const r = await this.api.get(`/leads/${this.lead().id}/files`);
    this.files.set(r.files);
    this.folders.set(r.folders);
  }

  async upload(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const up = await this.api.upload(file);
    await this.api.post(`/leads/${this.lead().id}/files`, { key: up.key, folder: this.folder, room_id: this.roomId, caption: this.caption }, 'File added');
    this.caption = '';
    this.filter.set(''); // show the new file whatever filter was on
    await this.load();
    this.changed.emit();
  }

  async remove(f: any) {
    await this.api.del(`/lead_files/${f.id}`, 'File removed');
    await this.load();
    this.changed.emit();
  }
}
