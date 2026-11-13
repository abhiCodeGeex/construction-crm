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
              <label class="check small"><p-checkbox [(ngModel)]="showProgress" (ngModelChange)="loadProgress()" [binary]="true" ariaLabel="Colour by progress" /> Colour by site progress</label>
              <p-button [label]="linking ? 'Done linking' : 'Link parts to work'" size="small" [outlined]="!linking" (onClick)="toggleLink()" />
              @if (m.format === 'glb' || m.format === 'gltf') { <p-button [label]="m.ar_url ? 'AR link' : 'View in AR'" icon="pi pi-mobile" size="small" [text]="true" (onClick)="ar(m)" /> }
              <p-button icon="pi pi-trash" [text]="true" severity="secondary" size="small" (onClick)="remove(m)" ariaLabel="Delete model" /></span></div>
          @if (compare && prev()) {
            <div class="grid2">
              <div><div class="small muted">Before — v{{ prev().version }}</div><app-model-viewer [model]="prev()" [link]="link" /></div>
              <div><div class="small muted">After — v{{ m.version }}</div><app-model-viewer [model]="m" [link]="link" [canComment]="true" (spot)="startComment($event)" /></div>
            </div>
          } @else {
            <app-model-viewer [model]="m" [canComment]="!linking" [mode]="linking ? 'pick' : 'comment'" [progress]="showProgress || linking ? prog()?.elements ?? [] : null"
              (spot)="startComment($event)" (picked)="startLink($event)" />
          }
          @if (linking) { <p class="small muted">Click a part of the model (a wall, the wardrobe…) to say which stage or task builds it. Linked parts take the colour of that work's progress.</p> }
          @if ((showProgress || linking) && prog(); as pr) {
            <div class="legend small">@for (s of statuses; track s.k) { <span><i class="sw" [style.background]="s.c"></i>{{ s.l }} {{ pr.counts[s.k] || 0 }}</span> }
              @if (pr.done_pct !== null) { <strong>· {{ pr.done_pct }}% built</strong> }</div>
            @if (linking) { @for (x of pr.elements; track x.element) { <div class="small row gap">{{ x.label || x.element }} → {{ x.stage_name }}@if (x.task_title) { / {{ x.task_title }} } ({{ x.status.replace('_', ' ') }})
              <a href="" (click)="$event.preventDefault(); unlink(x.element)">remove</a></div> } }
          }
          @if (m.ar_url) { <div class="small">AR link (open on a phone): <a [href]="m.ar_url" target="_blank" rel="noopener">{{ origin + m.ar_url }}</a> · <a href="" (click)="$event.preventDefault(); arOff(m)">withdraw</a></div> }
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
    <p-dialog [header]="'Link ' + (lk.element || '')" [modal]="true" [(visible)]="lDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field"><span>Name it</span><input pInputText [(ngModel)]="lk.label" placeholder="e.g. Left wardrobe" fluid /></label>
        <label class="field req"><span>Stage</span><p-select [options]="fullStages()" optionLabel="name" optionValue="id" [(ngModel)]="lk.stage_id" (onChange)="lk.task_id = null" fluid appendTo="body" /></label>
        <label class="field"><span>Task (optional)</span><p-select [options]="tasksOf(lk.stage_id)" optionLabel="title" optionValue="id" [(ngModel)]="lk.task_id" [showClear]="true" fluid appendTo="body" /></label>
        <div class="row right"><p-button label="Link" [disabled]="!lk.stage_id" (onClick)="saveLink()" /></div>
      </div>
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
    .item.on { border-color: var(--p-primary-color); } .comment { border-bottom: 1px solid var(--border); padding: .4rem 0; } .comment.done { opacity: .6; }
    .legend { display: flex; gap: .8rem; flex-wrap: wrap; margin: .4rem 0; } .sw { display: inline-block; width: .7rem; height: .7rem; border-radius: 2px; margin-right: .25rem; }`,
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
  // Phase L block 5: the model linked to site progress, and AR
  origin = location.origin;
  showProgress = false;
  linking = false;
  prog = signal<any>(null);
  fullStages = signal<any[]>([]);
  lDlg = false;
  lk: any = {};
  statuses = [{ k: 'done', l: 'Done', c: '#16a34a' }, { k: 'in_progress', l: 'In progress', c: '#2563eb' }, { k: 'late', l: 'Late', c: '#dc2626' },
    { k: 'blocked', l: 'Blocked', c: '#f97316' }, { k: 'not_started', l: 'Not started', c: '#9ca3af' }];

  async loadProgress() {
    const m = this.cur();
    if (!m) return;
    const pr = await this.api.get(`/models/${m.id}/progress`);
    this.prog.set(pr);
    this.fullStages.set(pr.stages);
  }

  async toggleLink() {
    this.linking = !this.linking;
    if (this.linking) await this.loadProgress();
  }

  tasksOf(sid: string) {
    return this.fullStages().find((s) => s.id === sid)?.tasks ?? [];
  }

  startLink(ev: { element: string }) {
    const ex = (this.cur()?.links ?? []).find((x: any) => x.element === ev.element);
    this.lk = { element: ev.element, label: ex?.label ?? '', stage_id: ex?.stage_id ?? this.fullStages()[0]?.id ?? null, task_id: ex?.task_id ?? null };
    this.lDlg = true;
  }

  private linksNow() {
    return (this.cur()?.links ?? []).map((x: any) => ({ element: x.element, label: x.label, stage_id: x.stage_id, task_id: x.task_id }));
  }

  async saveLink() {
    const links = [...this.linksNow().filter((x: any) => x.element !== this.lk.element), this.lk];
    const res = await this.api.put(`/models/${this.cur().id}/links`, { links }, 'Linked');
    this.lDlg = false;
    this.cur.set(res);
    this.prog.set({ ...this.prog(), ...res });
  }

  async unlink(element: string) {
    const res = await this.api.put(`/models/${this.cur().id}/links`, { links: this.linksNow().filter((x: any) => x.element !== element) });
    this.cur.set(res);
    this.prog.set({ ...this.prog(), ...res });
  }

  async ar(m: any) {
    const res = await this.api.post(`/models/${m.id}/ar`, { scale: 'fixed' }, 'AR link ready — open it on a phone');
    this.cur.set(res);
  }

  async arOff(m: any) {
    if (!confirm('Withdraw the AR link? Anyone who has it can no longer open the model.')) return;
    this.cur.set(await this.api.post(`/models/${m.id}/ar`, { off: true }));
  }

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
    this.prog.set(null);
    if (this.showProgress || this.linking) this.loadProgress();
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
