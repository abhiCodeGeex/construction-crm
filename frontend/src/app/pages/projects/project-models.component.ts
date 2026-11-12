import { Component, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { Api } from '../../core/api.service';
import { ModelViewerComponent } from '../../core/model-viewer.component';

/** Phase K block 7 — the project's 3D models: view, pin comments, before / after, share with the client. */
@Component({
  selector: 'app-project-models',
  imports: [FormsModule, DatePipe, ButtonModule, CheckboxModule, DialogModule, InputTextModule, SelectModule, TagModule, ModelViewerComponent],
  template: `
    <div class="row-between mb wrap gap">
      <span class="small muted">GLB / glTF, OBJ or IFC (from Revit, ArchiCAD, SketchUp). Click the model to pin a comment; a comment becomes a task or a change request.</span>
      <p-button label="Add a model" icon="pi pi-plus" size="small" (onClick)="open()" />
    </div>
    <div class="layout">
      <div>
        @for (m of models(); track m.id) {
          <button type="button" class="item" [class.on]="m.id === cur()?.id" (click)="pick(m)">
            <strong>{{ m.title }}</strong>
            <span class="small muted">{{ m.format.toUpperCase() }} · v{{ m.version }}@if (m.room) { · {{ m.room }} } · {{ m.open }} open @if (m.shared) { · shared }
              @if (m.superseded_by) { · <em>superseded</em> }</span>
          </button>
        } @empty { <p class="muted">No models yet.</p> }
      </div>
      @if (cur(); as m) {
        <div>
          <div class="row-between wrap gap mb"><strong>{{ m.title }}</strong>
            <span class="row gap">
              @if (prev()) { <label class="check small"><p-checkbox [(ngModel)]="compare" [binary]="true" ariaLabel="Before and after" /> Before / after (v{{ prev().version }})</label> }
              <label class="check small"><p-checkbox [ngModel]="m.shared" (ngModelChange)="share(m, $event)" [binary]="true" ariaLabel="Shared with the client" /> Shared with the client</label>
              <p-button icon="pi pi-trash" [text]="true" severity="secondary" size="small" (onClick)="remove(m)" ariaLabel="Delete model" /></span></div>
          @if (compare && prev()) {
            <div class="grid2">
              <div><div class="small muted">Before — v{{ prev().version }}</div><app-model-viewer [model]="prev()" [link]="link" /></div>
              <div><div class="small muted">After — v{{ m.version }}</div><app-model-viewer [model]="m" [link]="link" [canComment]="true" (spot)="startComment($event)" /></div>
            </div>
          } @else {
            <app-model-viewer [model]="m" [canComment]="true" (spot)="startComment($event)" />
          }
          @for (c of m.comments; track c.id; let i = $index) {
            <div class="comment" [class.done]="c.status === 'resolved'">
              <div class="row-between wrap gap"><span><strong>{{ i + 1 }}. {{ c.author }}</strong> <span class="small muted">{{ c.side }} · {{ c.at | date: 'd MMM HH:mm' }}</span></span>
                <span class="row gap">
                  @if (c.task_title) { <p-tag [value]="'Task: ' + c.task_title" severity="info" /> }
                  @if (c.co_number) { <p-tag [value]="c.co_number" severity="warn" /> }
                  @if (!c.task_id) { <p-button label="Make a task" size="small" [text]="true" (onClick)="toTask(m, c)" /> }
                  @if (!c.co_id) { <p-button label="Change request" size="small" [text]="true" (onClick)="toChange(m, c)" /> }
                  <p-button [label]="c.status === 'resolved' ? 'Reopen' : 'Resolve'" size="small" [text]="true" severity="secondary" (onClick)="resolve(m, c)" />
                </span></div>
              <div>{{ c.text }}</div>
            </div>
          }
        </div>
      }
    </div>
    <p-dialog header="Add a model" [modal]="true" [(visible)]="dlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <label class="field req"><span>Model file (GLB, glTF, OBJ, IFC — up to 100 MB)</span><input type="file" accept=".glb,.gltf,.obj,.ifc" (change)="attach($event)" /></label>
        <label class="field"><span>Title</span><input pInputText [(ngModel)]="f.title" fluid /></label>
        <label class="field"><span>Room / area</span><input pInputText [(ngModel)]="f.room" fluid /></label>
        <label class="field"><span>Replaces (for before / after)</span><p-select [options]="models()" optionLabel="title" optionValue="id" [(ngModel)]="f.previous_id" [showClear]="true" fluid appendTo="body" /></label>
        <label class="check"><p-checkbox [(ngModel)]="f.shared" [binary]="true" ariaLabel="Share with the client" /> Share with the client</label>
        @if (uploading) { <p class="small muted m0">Uploading…</p> }
        <div class="row right"><p-button label="Save" [disabled]="!f.file_key" (onClick)="save()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Comment on this point" [modal]="true" [(visible)]="cDlg" [style]="{ width: '28rem' }">
      <div class="stack"><textarea class="p-inputtext" rows="3" [(ngModel)]="text" aria-label="Comment"></textarea>
        <div class="row right"><p-button label="Add comment" [disabled]="!text.trim()" (onClick)="comment()" /></div></div>
    </p-dialog>
    <p-dialog header="Make a task" [modal]="true" [(visible)]="tDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>Stage</span><p-select [options]="stages()" optionLabel="name" optionValue="id" [(ngModel)]="tf.stage_id" fluid appendTo="body" /></label>
        <label class="field"><span>Title</span><input pInputText [(ngModel)]="tf.title" fluid /></label>
        <div class="row right"><p-button label="Make task" [disabled]="!tf.stage_id" (onClick)="saveTask()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.layout { display: grid; grid-template-columns: 16rem 1fr; gap: 1rem; } @media (max-width: 800px) { .layout { grid-template-columns: 1fr; } }
    .item { display: grid; text-align: left; width: 100%; padding: .5rem .7rem; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); margin-bottom: .4rem; cursor: pointer; }
    .item.on { border-color: var(--p-primary-color); } .comment { border-bottom: 1px solid var(--border); padding: .4rem 0; } .comment.done { opacity: .6; }`,
})
export class ProjectModelsComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  models = signal<any[]>([]);
  cur = signal<any>(null);
  stages = signal<any[]>([]);
  link = { listeners: new Set<() => void>() } as any;
  compare = false;
  dlg = false; cDlg = false; tDlg = false; uploading = false;
  f: any = {};
  tf: any = {};
  text = '';
  at: any = null;
  target: any = null;

  prev = () => this.models().find((x) => x.id === this.cur()?.previous_id) ?? null;

  async ngOnInit() {
    await this.load();
    const p = await this.api.get(`/projects/${this.projectId()}`);
    this.stages.set(p.stages.map((s: any) => ({ id: s.id, name: s.name })));
  }

  async load() {
    const rows = await this.api.get(`/projects/${this.projectId()}/models`);
    this.models.set(rows);
    const id = this.cur()?.id;
    this.cur.set(rows.find((m: any) => m.id === id) ?? rows[0] ?? null);
  }

  pick(m: any) {
    this.compare = false;
    this.link = { listeners: new Set() };
    this.cur.set(m);
  }

  open() {
    this.f = { file_key: null, title: '', room: '', previous_id: null, shared: false };
    this.dlg = true;
  }

  async attach(ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (!file) return;
    this.uploading = true;
    try {
      const up = await this.api.upload(file);
      this.f.file_key = up.key;
      this.f.title ||= file.name.replace(/\.[^.]+$/, '');
    } finally {
      this.uploading = false;
    }
  }

  async save() {
    const m = await this.api.post(`/projects/${this.projectId()}/models`, this.f, 'Model added');
    this.dlg = false;
    this.cur.set(m);
    await this.load();
  }

  async share(m: any, shared: boolean) {
    await this.api.put(`/models/${m.id}`, { shared }, shared ? 'Shared with the client' : 'No longer shared');
    await this.load();
  }

  async remove(m: any) {
    if (!confirm(`Delete ${m.title}?`)) return;
    await this.api.del(`/models/${m.id}`, 'Deleted');
    this.cur.set(null);
    await this.load();
  }

  startComment(at: any) {
    this.at = at;
    this.text = '';
    this.cDlg = true;
  }

  async comment() {
    await this.api.post(`/models/${this.cur().id}/comments`, { text: this.text, ...this.at }, 'Comment added');
    this.cDlg = false;
    await this.load();
  }

  toTask(m: any, c: any) {
    this.target = { m, c };
    this.tf = { stage_id: this.stages()[0]?.id ?? null, title: c.text.slice(0, 100) };
    this.tDlg = true;
  }

  async saveTask() {
    await this.api.post(`/models/${this.target.m.id}/comments/${this.target.c.id}/task`, this.tf, 'Task made');
    this.tDlg = false;
    await this.load();
  }

  async toChange(m: any, c: any) {
    await this.api.post(`/models/${m.id}/comments/${c.id}/change`, {}, 'Change request sent to the PM');
    await this.load();
  }

  async resolve(m: any, c: any) {
    await this.api.post(`/models/${m.id}/comments/${c.id}/resolve`, {});
    await this.load();
  }
}
