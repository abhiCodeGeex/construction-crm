import { Component, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { PanoComponent } from '../../core/pano.component';

// ---------------------------------------------------------------- 360° views and renders (Phase J block 5)
@Component({
  selector: 'app-project-views',
  imports: [FormsModule, DatePipe, ButtonModule, CheckboxModule, DialogModule, InputTextModule, SelectModule, TagModule, PanoComponent],
  template: `
    <div class="row-between mb wrap gap">
      <span class="small muted">360° room views and renders. Click a spot to comment; a comment becomes a task or a change request. Shared views appear in the client portal.</span>
      <p-button label="Add a view" icon="pi pi-plus" size="small" (onClick)="open()" />
    </div>
    <div class="layout">
      <div class="list">
        @for (v of views(); track v.id) {
          <button type="button" class="vitem" [class.on]="v.id === cur()?.id" (click)="cur.set(v)">
            <strong>{{ v.title }}</strong><span class="small muted">{{ v.kind_label }}@if (v.room) { · {{ v.room }} } · {{ v.open }} open @if (v.shared) { · shared }</span>
          </button>
        } @empty { <p class="muted">No views yet.</p> }
      </div>
      @if (cur(); as v) {
        <div>
          <div class="row-between mb"><strong>{{ v.title }}</strong>
            <span class="row gap"><label class="check small"><p-checkbox [ngModel]="v.shared" (ngModelChange)="share(v, $event)" [binary]="true" ariaLabel="Shared with the client" /> Shared with the client</label>
              <p-button icon="pi pi-trash" [text]="true" severity="secondary" size="small" (onClick)="remove(v)" ariaLabel="Delete view" /></span></div>
          <app-pano [view]="v" [canComment]="true" (spot)="startComment($event)" />
          @for (c of v.comments; track c.id; let i = $index) {
            <div class="comment" [class.done]="c.status === 'resolved'">
              <div class="row-between wrap gap"><span><strong>{{ i + 1 }}. {{ c.author }}</strong> <span class="small muted">{{ c.side === 'client' ? 'client' : 'team' }} · {{ c.at | date: 'd MMM HH:mm' }}</span></span>
                <span class="row gap">
                  @if (c.task_title) { <p-tag [value]="'Task: ' + c.task_title" severity="info" /> }
                  @if (c.co_number) { <p-tag [value]="c.co_number" severity="warn" /> }
                  @if (!c.task_id) { <p-button label="Make a task" size="small" [text]="true" (onClick)="toTask(v, c)" /> }
                  @if (!c.co_id) { <p-button label="Change request" size="small" [text]="true" (onClick)="toChange(v, c)" /> }
                  <p-button [label]="c.status === 'resolved' ? 'Reopen' : 'Resolve'" size="small" [text]="true" severity="secondary" (onClick)="resolve(v, c)" />
                </span></div>
              <div>{{ c.text }}</div>
            </div>
          }
        </div>
      }
    </div>
    <p-dialog header="Add a view" [modal]="true" [(visible)]="dlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <label class="field req"><span>Kind</span><p-select [options]="kinds" optionLabel="label" optionValue="value" [(ngModel)]="f.kind" fluid appendTo="body" /></label>
        <label class="field req"><span>Title</span><input pInputText [(ngModel)]="f.title" fluid /></label>
        <label class="field"><span>Room</span><input pInputText [(ngModel)]="f.room" fluid /></label>
        <label class="field req"><span>{{ f.kind === '360' ? 'Panorama (equirectangular JPG)' : 'Render image' }}</span><input type="file" accept="image/*" (change)="attach($event)" /></label>
        <label class="check"><p-checkbox [(ngModel)]="f.shared" [binary]="true" ariaLabel="Share with the client" /> Share with the client</label>
        <div class="row right"><p-button label="Save" [disabled]="!f.title?.trim() || !f.file_key" (onClick)="save()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Comment on this spot" [modal]="true" [(visible)]="cDlg" [style]="{ width: '28rem' }">
      <div class="stack"><textarea class="p-inputtext" rows="3" [(ngModel)]="text" aria-label="Comment"></textarea>
        <div class="row right"><p-button label="Add comment" [disabled]="!text.trim()" (onClick)="comment()" /></div></div>
    </p-dialog>
    <p-dialog header="Make a task" [modal]="true" [(visible)]="tDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>Stage</span><p-select [options]="stages()" optionLabel="name" optionValue="id" [(ngModel)]="tf.stage_id" fluid appendTo="body" /></label>
        <label class="field"><span>Title</span><input pInputText [(ngModel)]="tf.title" fluid /></label>
        <label class="field"><span>Due</span><input pInputText type="date" [(ngModel)]="tf.end" fluid /></label>
        <div class="row right"><p-button label="Make task" [disabled]="!tf.stage_id" (onClick)="saveTask()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.layout { display: grid; grid-template-columns: 16rem 1fr; gap: 1rem; } @media (max-width: 800px) { .layout { grid-template-columns: 1fr; } }
    .vitem { display: grid; text-align: left; width: 100%; padding: .5rem .7rem; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); margin-bottom: .4rem; cursor: pointer; }
    .vitem.on { border-color: var(--p-primary-color); }
    .comment { border-bottom: 1px solid var(--border); padding: .4rem 0; } .comment.done { opacity: .6; }`,
})
export class ProjectViewsComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  views = signal<any[]>([]);
  cur = signal<any>(null);
  stages = signal<any[]>([]);
  kinds = [{ label: '360° view', value: '360' }, { label: 'Render', value: 'render' }];
  dlg = false; cDlg = false; tDlg = false;
  f: any = {};
  tf: any = {};
  text = '';
  at: any = null;
  target: any = null;

  async ngOnInit() {
    await this.load();
    const p = await this.api.get(`/projects/${this.projectId()}`);
    this.stages.set(p.stages.map((s: any) => ({ id: s.id, name: s.name })));
  }

  async load() {
    const rows = await this.api.get(`/projects/${this.projectId()}/views`);
    this.views.set(rows);
    const id = this.cur()?.id;
    this.cur.set(rows.find((v: any) => v.id === id) ?? rows[0] ?? null);
  }

  open() {
    this.f = { kind: '360', title: '', room: '', shared: false, file_key: null };
    this.dlg = true;
  }

  async attach(ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (file) this.f.file_key = (await this.api.upload(file)).key;
  }

  async save() {
    const v = await this.api.post(`/projects/${this.projectId()}/views`, this.f, 'View added');
    this.dlg = false;
    this.cur.set(v);
    await this.load();
  }

  async share(v: any, shared: boolean) {
    await this.api.put(`/views/${v.id}`, { shared }, shared ? 'Shared with the client' : 'No longer shared');
    await this.load();
  }

  async remove(v: any) {
    if (!confirm(`Delete ${v.title}?`)) return;
    await this.api.del(`/views/${v.id}`, 'Deleted');
    this.cur.set(null);
    await this.load();
  }

  startComment(at: any) {
    this.at = at;
    this.text = '';
    this.cDlg = true;
  }

  async comment() {
    await this.api.post(`/views/${this.cur().id}/comments`, { text: this.text, ...this.at }, 'Comment added');
    this.cDlg = false;
    await this.load();
  }

  toTask(v: any, c: any) {
    this.target = { v, c };
    this.tf = { stage_id: this.stages()[0]?.id ?? null, title: (v.room ? v.room + ': ' : '') + c.text.slice(0, 100), end: null };
    this.tDlg = true;
  }

  async saveTask() {
    const { v, c } = this.target;
    await this.api.post(`/views/${v.id}/comments/${c.id}/task`, { ...this.tf, end: this.tf.end || undefined }, 'Task made');
    this.tDlg = false;
    await this.load();
  }

  async toChange(v: any, c: any) {
    await this.api.post(`/views/${v.id}/comments/${c.id}/change`, {}, 'Change request sent to the PM');
    await this.load();
  }

  async resolve(v: any, c: any) {
    await this.api.post(`/views/${v.id}/comments/${c.id}/resolve`, {});
    await this.load();
  }
}

// ---------------------------------------------------------------- design options A / B / C (Phase J block 6)
@Component({
  selector: 'app-project-options',
  imports: [FormsModule, DatePipe, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TagModule],
  template: `
    <div class="row-between mb wrap gap">
      <span class="small muted">Two to four design options side by side for the client to approve in the portal. A linked selection records the choice; an extra price becomes a draft change order.</span>
      <p-button label="New decision" icon="pi pi-plus" size="small" (onClick)="open()" />
    </div>
    @for (d of rows(); track d.id) {
      <div class="card-row">
        <div class="row-between wrap gap">
          <div><strong>{{ d.title }}</strong>@if (d.room) { <span class="muted small"> · {{ d.room }}</span> }
            <p-tag [value]="statusLabel[d.status]" [severity]="d.status === 'approved' ? 'success' : d.status === 'changes_requested' ? 'warn' : d.status === 'sent' ? 'info' : 'secondary'" styleClass="ml-xs" />
            @if (d.selection_item) { <span class="small muted"> · selection {{ d.selection_item }}</span> }
            @if (d.co_number) { <span class="small"> · {{ d.co_number }} drafted</span> }</div>
          <span class="row gap">
            @if (d.status !== 'approved') {
              <p-button label="Edit" size="small" [text]="true" (onClick)="open(d)" />
              <p-button [label]="d.status === 'sent' ? 'Send again' : 'Send to the client'" icon="pi pi-send" size="small" (onClick)="send(d)" /> }
          </span>
        </div>
        @if (d.client_comment) { <div class="small"><strong>Client:</strong> {{ d.client_comment }}</div> }
        <div class="opts">
          @for (o of d.options; track o.id) {
            <div class="opt" [class.win]="d.approved_option_id === o.id">
              <strong>{{ o.label }}. {{ o.name }}</strong>
              @if (o.images[0]) { <img [src]="o.images[0].url" [alt]="o.name" /> }
              @if (o.description) { <span class="small">{{ o.description }}</span> }
              <span class="small">{{ o.price ? (o.price > 0 ? '+' : '') + fmt(o.price) : 'no extra cost' }}</span>
            </div>
          }
        </div>
      </div>
    } @empty { <p class="muted">No design decisions yet.</p> }
    <p-dialog [header]="f.id ? 'Edit decision' : 'New decision'" [modal]="true" [(visible)]="dlg" [style]="{ width: '44rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field req"><span>Decision</span><input pInputText [(ngModel)]="f.title" placeholder="Living room — wall finish" fluid /></label>
          <label class="field"><span>Room</span><input pInputText [(ngModel)]="f.room" fluid /></label>
          <label class="field"><span>Linked selection</span><p-select [options]="sels()" optionLabel="item" optionValue="id" [(ngModel)]="f.selection_id" [showClear]="true" fluid appendTo="body" (onChange)="f.options.forEach(clearLink)" /></label>
          <label class="field"><span>Decide by</span><input pInputText type="date" [(ngModel)]="f.due_date" fluid /></label>
        </div>
        @for (o of f.options; track $index; let i = $index) {
          <div class="optedit">
            <div class="row-between"><strong>Option {{ 'ABCD'[i] }}</strong>
              @if (f.options.length > 2) { <p-button icon="pi pi-times" [text]="true" severity="secondary" size="small" (onClick)="f.options.splice(i, 1)" ariaLabel="Remove option" /> }</div>
            <div class="grid2">
              <input pInputText [(ngModel)]="o.name" placeholder="Name" aria-label="Option name" />
              <p-inputnumber [(ngModel)]="o.price" placeholder="Extra price (0 = none, negative = cheaper)" ariaLabel="Extra price" fluid />
            </div>
            <input pInputText [(ngModel)]="o.description" placeholder="Description" aria-label="Description" />
            @if (selOptions().length) { <p-select [options]="selOptions()" optionLabel="name" optionValue="id" [(ngModel)]="o.selection_option_id" [showClear]="true" placeholder="Matches selection option…" appendTo="body" /> }
            <input type="file" accept="image/*" multiple (change)="attach($event, o)" aria-label="Images" /><span class="small muted">{{ o.images.length }} image(s)</span>
          </div>
        }
        @if (f.options.length < 4) { <p-button label="Add an option" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.options.push(blank())" /> }
        <div class="row right"><p-button label="Save" [disabled]="!f.title?.trim() || f.options.length < 2 || !allNamed()" (onClick)="save()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.card-row { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .9rem; margin-bottom: .75rem; background: var(--surface); display: grid; gap: .4rem; }
    .opts { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: .6rem; }
    .opt { display: grid; gap: .25rem; border: 1px solid var(--border); border-radius: 8px; padding: .5rem; } .opt.win { border: 2px solid var(--green, #16a34a); }
    .opt img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 6px; }
    .optedit { display: grid; gap: .4rem; border: 1px dashed var(--border); border-radius: 8px; padding: .5rem; }`,
})
export class ProjectOptionsComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  private auth = inject(AuthService);
  rows = signal<any[]>([]);
  sels = signal<any[]>([]);
  statusLabel: Record<string, string> = { draft: 'Draft', sent: 'With the client', approved: 'Approved', changes_requested: 'Changes asked' };
  dlg = false;
  f: any = { options: [] };

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.rows.set(await this.api.get(`/projects/${this.projectId()}/design-options`));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  blank = () => ({ name: '', description: '', price: 0, images: [] as string[], selection_option_id: null });
  clearLink = (o: any) => (o.selection_option_id = null);
  allNamed = () => this.f.options.every((o: any) => o.name?.trim());
  selOptions = () => this.sels().find((s) => s.id === this.f.selection_id)?.options ?? [];

  async open(d?: any) {
    const s = await this.api.get(`/projects/${this.projectId()}/selections`).catch(() => []);
    this.sels.set((Array.isArray(s) ? s : s.selections ?? []).map((x: any) => ({ id: x.id, item: x.item, options: x.options ?? [] })));
    this.f = d ? { id: d.id, title: d.title, room: d.room ?? '', selection_id: d.selection_id, due_date: d.due_date,
        options: d.options.map((o: any) => ({ id: o.id, name: o.name, description: o.description ?? '', price: o.price, images: o.images.map((i: any) => i.key), selection_option_id: o.selection_option_id })) }
      : { title: '', room: '', selection_id: null, due_date: null, options: [this.blank(), this.blank()] };
    this.dlg = true;
  }

  async attach(ev: Event, o: any) {
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) o.images.push((await this.api.upload(file)).key);
  }

  async save() {
    const { id, ...body } = this.f;
    if (id) await this.api.put(`/design-options/${id}`, body, 'Saved');
    else await this.api.post(`/projects/${this.projectId()}/design-options`, body, 'Saved');
    this.dlg = false;
    await this.load();
  }

  async send(d: any) {
    await this.api.post(`/design-options/${d.id}/send`, {}, 'Sent to the client');
    await this.load();
  }
}
