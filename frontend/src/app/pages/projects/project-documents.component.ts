import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ConfirmationService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectButtonModule } from 'primeng/selectbutton';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TooltipModule } from 'primeng/tooltip';
import { Api, label } from '../../core/api.service';

/** The project's documents (Phase F block 1): folders, revisions R0, R1…, plus the lead's files and task files
 *  listed (not copied) so every file of the project is in one place. */
@Component({
  selector: 'app-project-documents',
  imports: [FormsModule, DatePipe, DecimalPipe, ButtonModule, CheckboxModule, DialogModule, InputTextModule, MultiSelectModule,
    SelectButtonModule, SelectModule, TableModule, TagModule, TooltipModule],
  template: `
    <div class="row-between mb">
      <p-selectbutton [options]="views" [(ngModel)]="view" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="loadView()" />
      @if (view === 'transmittals' && data()?.can_write) { <p-button label="Issue documents" icon="pi pi-send" size="small" (onClick)="openTransmittal()" /> }
    </div>
    @if (view === 'register') {
      @if (reg(); as r) {
        <p-table [value]="r.drawings" styleClass="p-datatable-sm">
          <ng-template #header><tr><th>Number</th><th>Title</th><th>Discipline</th><th>Scale</th><th>Rev</th><th>Status</th><th>Last issued</th></tr></ng-template>
          <ng-template #body let-x>
            <tr><td><a [href]="x.url" target="_blank" rel="noopener">{{ x.number }}</a></td><td>{{ x.name }}<div class="small muted">{{ x.stage_name }}</div></td>
              <td>{{ x.discipline || '—' }}</td><td>{{ x.scale || '—' }}</td><td><p-tag [value]="x.rev" severity="info" /></td>
              <td>{{ r.statuses[x.status] || '—' }}</td><td class="small">@if (x.last_issued) { {{ x.last_issued_rev }} · {{ x.last_issued | date: 'd MMM y' }} } @else { not issued }</td></tr>
          </ng-template>
          <ng-template #emptymessage><tr><td colspan="7" class="muted">No drawings yet. Add a document of kind “drawing” with its number.</td></tr></ng-template>
        </p-table>
      }
    } @else if (view === 'comments') {
      @for (c of comments(); track c.id) {
        <div class="cmt">
          <div class="row-between"><span><strong>{{ c.number || c.document_name }} {{ c.rev }}</strong> <span class="small muted">· {{ c.author }} ({{ c.side }}) · {{ c.created_at | date: 'd MMM y' }}</span></span>
            <p-tag [value]="c.status" [severity]="c.status === 'open' ? 'warn' : c.status === 'answered' ? 'info' : 'secondary'" /></div>
          <div>{{ c.text }}</div>
          @if (c.reply) { <div class="small c-good">Reply: {{ c.reply.text }} — {{ c.reply.by }}</div> }
          @if (data()?.can_write) {
            @if (replyTo === c) {
              <div class="row gap"><input pInputText class="grow" [(ngModel)]="replyText" placeholder="Reply to {{ c.author }}" />
                <p-button label="Send" size="small" [disabled]="!replyText.trim()" (onClick)="reply(c)" /></div>
            } @else {
              <div class="row gap right">
                <p-button label="Reply" size="small" [text]="true" (onClick)="replyTo = c; replyText = ''" />
                @if (!c.task_id) { <p-button label="Make a task" size="small" [text]="true" (onClick)="commentTask(c)" /> }
                @if (c.status !== 'closed') { <p-button label="Close" size="small" [text]="true" severity="secondary" (onClick)="commentStatus(c, 'closed')" /> }
              </div>
            }
          }
        </div>
      } @empty { <p class="muted">No comments from the client or consultants.</p> }
    } @else if (view === 'transmittals') {
      @if (trs(); as tl) {
        <p-table [value]="tl.transmittals" styleClass="p-datatable-sm">
          <ng-template #header><tr><th>Number</th><th>To</th><th>Purpose</th><th>Documents</th><th>Acknowledged</th></tr></ng-template>
          <ng-template #body let-x>
            <tr><td>{{ x.number }}<div class="small muted">{{ x.created_at | date: 'd MMM y' }} · {{ x.sent_by_name }}</div></td>
              <td>@for (r of x.to; track r.contact_id) { <div>{{ r.name }} <span class="small muted">{{ x.emailed[r.contact_id] || '' }}</span></div> }</td>
              <td>{{ tl.purposes[x.purpose] }}</td>
              <td class="small">@for (it of x.items; track it.document_id) { <div>{{ it.number || it.name }} {{ it.rev }}</div> }</td>
              <td>@if (x.acknowledged) { {{ x.acknowledged.by }} <div class="small muted">{{ x.acknowledged.date | date: 'd MMM y' }}</div> }
                @else if (data()?.can_write) { <p-button label="Record" size="small" [text]="true" (onClick)="openAck(x)" /> } @else { — }</td></tr>
          </ng-template>
          <ng-template #emptymessage><tr><td colspan="5" class="muted">Nothing issued yet.</td></tr></ng-template>
        </p-table>
      }
    } @else { @if (data(); as d) {
      <div class="docs">
        <nav class="folders">
          @for (f of allFolders(); track f) {
            <button type="button" class="folder" [class.on]="folder() === f" (click)="folder.set(f)">
              <i class="pi" [class.pi-folder]="!isVirtual(f)" [class.pi-link]="isVirtual(f)"></i> {{ f }} <span class="muted small">{{ count(f) }}</span>
            </button>
          }
        </nav>
        <div class="list">
          <div class="row-between mb">
            <strong>{{ folder() }}</strong>
            @if (d.can_write && !isVirtual(folder())) { <p-button label="Add document" icon="pi pi-upload" size="small" (onClick)="openNew()" /> }
          </div>
          @if (folder() === 'From the lead') {
            <p-table [value]="d.lead_files" styleClass="p-datatable-sm">
              <ng-template #body let-f><tr><td><a [href]="f.url" target="_blank" rel="noopener">{{ f.name }}</a></td><td>{{ label(f.folder) }}</td>
                <td>{{ f.caption || '' }}</td><td class="small muted">{{ f.created_at | date: 'd MMM y' }}</td></tr></ng-template>
              <ng-template #emptymessage><tr><td class="muted">No files came with the lead.</td></tr></ng-template>
            </p-table>
          } @else if (folder() === 'Task files') {
            <p-table [value]="d.task_files" styleClass="p-datatable-sm">
              <ng-template #body let-f><tr><td><a [href]="f.url" target="_blank" rel="noopener">{{ f.name }}</a></td><td>{{ f.task }}</td>
                <td class="small muted">{{ f.stage }}</td><td class="small muted">{{ f.by }}</td></tr></ng-template>
              <ng-template #emptymessage><tr><td class="muted">No files on tasks yet.</td></tr></ng-template>
            </p-table>
          } @else {
            <p-table [value]="inFolder()" styleClass="p-datatable-sm" dataKey="id" [expandedRowKeys]="expanded">
              <ng-template #header><tr><th style="width: 2rem"></th><th>Document</th><th>Kind</th><th>Rev</th><th>Updated</th><th></th></tr></ng-template>
              <ng-template #body let-doc let-open="expanded">
                <tr>
                  <td><p-button [icon]="open ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" [text]="true" size="small" (onClick)="toggle(doc)" ariaLabel="Revisions" /></td>
                  <td>@if (doc.number) { <strong>{{ doc.number }}</strong> } <a [href]="doc.current.url" target="_blank" rel="noopener">{{ doc.name }}</a>
                    <div class="small muted">@if (doc.stage_name) { {{ doc.stage_name }} · } {{ doc.current.name }} · {{ doc.current.size / 1024 | number: '1.0-0' }} KB
                      @if (doc.shared) { · <span class="c-good">shared with the client</span> }</div></td>
                  <td>{{ label(doc.kind) }}</td>
                  <td><p-tag [value]="doc.current_rev" severity="info" />
                    @if (doc.kind === 'drawing') {
                      @if (d.can_write) { <p-select [options]="statusOpts" optionLabel="label" optionValue="value" [ngModel]="doc.status" (onChange)="setStatus(doc, $event.value)" size="small" appendTo="body" styleClass="status-pick" /> }
                      @else { <div class="small muted">{{ statusLabel(doc.status) }}</div> } }</td>
                  <td class="small">{{ doc.current.at | date: 'd MMM y' }}<div class="muted">{{ doc.current.by }}</div></td>
                  <td class="right nowrap">@if (d.can_write) {
                    <label class="p-button p-button-text p-button-sm upload-rev" pTooltip="Upload a new revision">
                      <i class="pi pi-upload"></i><input type="file" (change)="newRevision(doc, $event)" /></label>
                    <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="openEdit(doc)" ariaLabel="Edit" pTooltip="Edit" />
                    <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="remove(doc)" ariaLabel="Delete" pTooltip="Delete" />
                  }</td>
                </tr>
              </ng-template>
              <ng-template #expandedrow let-doc>
                <tr><td></td><td colspan="5">
                  @for (v of doc.versions.slice().reverse(); track v.rev) {
                    <div class="row-between small rev">
                      <span><a [href]="v.url" target="_blank" rel="noopener">{{ v.rev }}</a> · {{ v.at | date: 'd MMM y' }} · {{ v.by }}@if (v.note) { · {{ v.note }} }
                        @if (v.sent?.length) { · <span class="muted">sent {{ v.sent.length }}×</span> }</span>
                      @if (d.can_write && doc.versions.length > 1 && !v.sent?.length) {
                        <p-button icon="pi pi-times" [text]="true" size="small" severity="secondary" (onClick)="removeRev(doc, v)" ariaLabel="Remove revision" pTooltip="Remove this revision" /> }
                    </div>
                  }
                </td></tr>
              </ng-template>
              <ng-template #emptymessage><tr><td colspan="6" class="muted">This folder is empty.</td></tr></ng-template>
            </p-table>
          }
        </div>
      </div>
    } }

    <p-dialog header="Issue documents" [modal]="true" [(visible)]="trDlg" [style]="{ width: '36rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        <label class="field req"><span>To</span><p-multiselect [options]="trs()?.people ?? []" optionLabel="name" optionValue="contact_id" [(ngModel)]="tf.to" display="chip" fluid appendTo="body" placeholder="People on the project" /></label>
        <label class="field req"><span>Purpose</span><p-select [options]="purposeOpts()" optionLabel="label" optionValue="value" [(ngModel)]="tf.purpose" fluid appendTo="body" /></label>
        <label class="field req"><span>Documents (current revision)</span><p-multiselect [options]="docOpts()" optionLabel="label" optionValue="id" [(ngModel)]="tf.documents" [filter]="true" display="chip" fluid appendTo="body" /></label>
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="tf.note" fluid /></label>
        <label class="check"><p-checkbox [(ngModel)]="tf.email" [binary]="true" ariaLabel="Email the files" /> Email them the files</label>
        <p class="small muted m0">Issued revisions are kept for good. Issuing drawings to the client offers the stage's “Drawings issued to the client” check.</p>
        <div class="row right"><p-button label="Issue" icon="pi pi-send" [disabled]="!tf.to?.length || !tf.purpose || !tf.documents?.length" (onClick)="sendTransmittal()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Acknowledged" [modal]="true" [(visible)]="ackDlg" [style]="{ width: '26rem' }">
      <div class="stack">
        <label class="field req"><span>By</span><input pInputText [(ngModel)]="af.by" fluid /></label>
        <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="af.date" fluid /></label>
        <div class="row right"><p-button label="Save" [disabled]="!af.by?.trim()" (onClick)="saveAck()" /></div>
      </div>
    </p-dialog>

    <p-dialog [header]="f.id ? 'Edit document' : 'Add a document'" [modal]="true" [(visible)]="dlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        @if (!f.id) { <label class="field req"><span>File</span><input type="file" (change)="attach($event)" /></label> }
        <label class="field req"><span>Name</span><input pInputText [(ngModel)]="f.name" fluid /></label>
        <div class="grid2">
          <label class="field req"><span>Folder</span><p-select [options]="data()?.folders ?? []" [(ngModel)]="f.folder" fluid appendTo="body" /></label>
          <label class="field"><span>Kind</span><p-select [options]="kindOpts()" optionLabel="label" optionValue="value" [(ngModel)]="f.kind" fluid appendTo="body" /></label>
        </div>
        <div class="grid2">
          <label class="field"><span>Stage</span><p-select [options]="data()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="f.stage_id" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Room</span><input pInputText [(ngModel)]="f.room" fluid /></label>
        </div>
        @if (f.kind === 'drawing') {
          <div class="grid3">
            <label class="field req"><span>Drawing number</span><input pInputText [(ngModel)]="f.number" placeholder="A-101" fluid /></label>
            <label class="field"><span>Discipline</span><p-select [options]="disciplines" [(ngModel)]="f.discipline" [showClear]="true" fluid appendTo="body" /></label>
            <label class="field"><span>Scale</span><input pInputText [(ngModel)]="f.scale" placeholder="1:100" fluid /></label>
          </div>
        }
        @if (!f.id) { <label class="field"><span>Note</span><input pInputText [(ngModel)]="f.note" fluid /></label> }
        <label class="check"><p-checkbox [(ngModel)]="f.shared" [binary]="true" ariaLabel="Share with the client" /> Show it to the client in the portal</label>
        <div class="row right"><p-button label="Save" icon="pi pi-check" [disabled]="!f.name?.trim() || !f.folder || (!f.id && !f.file_key)" (onClick)="save()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .docs { display: grid; grid-template-columns: 14rem minmax(0, 1fr); gap: 1rem; }
    @media (max-width: 760px) { .docs { grid-template-columns: 1fr; } }
    .folders { display: flex; flex-direction: column; gap: .15rem; }
    .folder { text-align: left; background: none; border: 0; padding: .45rem .6rem; border-radius: 8px; cursor: pointer; color: inherit; font: inherit; }
    .folder.on, .folder:hover { background: var(--surface-hover, rgba(99, 102, 241, .12)); }
    .folder:focus-visible { outline: 2px solid var(--p-primary-color, #6366f1); }
    .nowrap { white-space: nowrap; }
    .upload-rev { position: relative; overflow: hidden; cursor: pointer; }
    .upload-rev input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
    .rev { padding: .25rem 0; border-bottom: 1px dashed var(--border); }
    :host ::ng-deep .status-pick { margin-top: .25rem; min-width: 9rem; }
    .cmt { border: 1px solid var(--border); border-radius: 10px; padding: .6rem .8rem; margin-bottom: .5rem; display: grid; gap: .3rem; }
  `,
})
export class ProjectDocumentsComponent implements OnInit {
  projectId = input.required<string>();
  private api = inject(Api);
  private confirm = inject(ConfirmationService);
  data = signal<any>(null);
  folder = signal('');
  expanded: Record<string, boolean> = {};
  dlg = false;
  f: any = {};
  label = label;
  views = [{ label: 'Library', value: 'library' }, { label: 'Drawing register', value: 'register' }, { label: 'Transmittals', value: 'transmittals' },
    { label: 'Comments', value: 'comments' }];
  comments = signal<any[]>([]);
  replyTo: any = null;
  replyText = '';
  view = 'library';
  reg = signal<any>(null);
  trs = signal<any>(null);
  trDlg = false; ackDlg = false;
  tf: any = {};
  af: any = {};
  private ackFor: any = null;
  disciplines = ['Architecture', 'Structure', 'MEP', 'Interior', 'Landscape', 'Other'];
  statusOpts = [{ value: 'wip', label: 'Work in progress' }, { value: 'for_comment', label: 'For comment' }, { value: 'for_approval', label: 'For approval' },
    { value: 'approved', label: 'Approved' }, { value: 'for_construction', label: 'For construction' }];
  purposeOpts = computed(() => Object.entries(this.trs()?.purposes ?? {}).map(([value, label]) => ({ value, label })));
  docOpts = computed(() => (this.data()?.documents ?? []).map((x: any) => ({ id: x.id, label: `${x.number ? x.number + ' ' : ''}${x.name} · ${x.current_rev}` })));

  allFolders = computed(() => [...(this.data()?.folders ?? []), ...(this.data()?.virtual_folders ?? [])]);
  inFolder = computed(() => (this.data()?.documents ?? []).filter((x: any) => x.folder === this.folder()));
  kindOpts = computed(() => (this.data()?.kinds ?? []).map((k: string) => ({ value: k, label: label(k) })));

  async ngOnInit() {
    await this.load();
    this.folder.set(this.data()?.folders?.[0] ?? '');
  }

  async load() {
    this.data.set(await this.api.get(`/projects/${this.projectId()}/documents`));
  }

  async loadView() {
    if (this.view === 'register') this.reg.set(await this.api.get(`/projects/${this.projectId()}/drawing-register`));
    if (this.view === 'transmittals') this.trs.set(await this.api.get(`/projects/${this.projectId()}/transmittals`));
    if (this.view === 'comments') this.comments.set(await this.api.get(`/projects/${this.projectId()}/document-comments`));
  }

  async reply(c: any) {
    await this.api.post(`/document_comments/${c.id}/reply`, { text: this.replyText }, 'Reply sent');
    this.replyTo = null;
    this.replyText = '';
    await this.loadView();
  }

  async commentStatus(c: any, status: string) {
    await this.api.put(`/document_comments/${c.id}`, { status }, 'Updated');
    await this.loadView();
  }

  async commentTask(c: any) {
    await this.api.post(`/document_comments/${c.id}/task`, {}, 'Task added to the stage');
    await this.loadView();
  }

  statusLabel(s: string) {
    return this.statusOpts.find((x) => x.value === s)?.label ?? (s === 'superseded' ? 'Superseded' : '—');
  }

  async setStatus(doc: any, status: string) {
    await this.api.put(`/documents/${doc.id}/status`, { status }, 'Status updated');
    await this.load();
  }

  async openTransmittal() {
    if (!this.trs()) await this.loadView();
    this.tf = { to: [], purpose: 'for_information', documents: [], note: '', email: true };
    this.trDlg = true;
  }

  async sendTransmittal() {
    await this.api.post(`/projects/${this.projectId()}/transmittals`, this.tf, 'Documents issued');
    this.trDlg = false;
    await this.load();
    await this.loadView();
  }

  openAck(x: any) {
    this.ackFor = x;
    this.af = { by: x.to?.[0]?.name ?? '', date: new Date().toISOString().slice(0, 10) };
    this.ackDlg = true;
  }

  async saveAck() {
    await this.api.post(`/transmittals/${this.ackFor.id}/acknowledge`, this.af, 'Recorded');
    this.ackDlg = false;
    await this.loadView();
  }

  isVirtual(f: string) {
    return (this.data()?.virtual_folders ?? []).includes(f);
  }

  count(f: string) {
    const d = this.data();
    if (f === 'From the lead') return d?.lead_files?.length || '';
    if (f === 'Task files') return d?.task_files?.length || '';
    return (d?.documents ?? []).filter((x: any) => x.folder === f).length || '';
  }

  toggle(doc: any) {
    this.expanded = { ...this.expanded, [doc.id]: !this.expanded[doc.id] };
  }

  openNew() {
    this.f = { folder: this.folder(), name: '', kind: 'other', stage_id: null, room: '', note: '', shared: false, file_key: null,
      number: '', discipline: null, scale: '' };
    this.dlg = true;
  }

  openEdit(doc: any) {
    this.f = { id: doc.id, folder: doc.folder, name: doc.name, kind: doc.kind, stage_id: doc.stage_id, room: doc.room ?? '', shared: doc.shared,
      number: doc.number ?? '', discipline: doc.discipline, scale: doc.scale ?? '' };
    this.dlg = true;
  }

  async attach(ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (!file) return;
    this.f.file_key = (await this.api.upload(file)).key;
    if (!this.f.name) this.f.name = file.name.replace(/\.[^.]+$/, '');
  }

  async save() {
    const { id, ...body } = this.f;
    if (body.kind !== 'drawing') { delete body.number; delete body.discipline; delete body.scale; }
    if (id) await this.api.put(`/documents/${id}`, body, 'Saved');
    else await this.api.post(`/projects/${this.projectId()}/documents`, body, 'Document added');
    this.dlg = false;
    if (body.folder) this.folder.set(body.folder);
    await this.load();
  }

  async newRevision(doc: any, ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (!file) return;
    const up = await this.api.upload(file);
    await this.api.post(`/documents/${doc.id}/versions`, { file_key: up.key }, 'New revision added');
    (ev.target as HTMLInputElement).value = '';
    await this.load();
  }

  removeRev(doc: any, v: any) {
    this.confirm.confirm({ header: `Remove ${v.rev} of ${doc.name}?`, icon: 'pi pi-trash', message: 'Its file is deleted.',
      accept: async () => { await this.api.del(`/documents/${doc.id}/versions/${v.rev}`, 'Revision removed'); await this.load(); } });
  }

  remove(doc: any) {
    this.confirm.confirm({ header: `Delete ${doc.name}?`, icon: 'pi pi-trash', message: 'Every revision and its file is deleted.',
      accept: async () => { await this.api.del(`/documents/${doc.id}`, 'Deleted'); await this.load(); } });
  }
}
