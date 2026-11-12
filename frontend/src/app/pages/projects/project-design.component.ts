import { Component, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { ProjectDocumentsComponent } from './project-documents.component';
import { ProjectOptionsComponent, ProjectViewsComponent } from './project-views.component';
import { ProjectModelsComponent } from './project-models.component';

// ---------------------------------------------------------------- authority / planning approvals
@Component({
  selector: 'app-project-permits',
  imports: [FormsModule, DatePipe, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TagModule],
  template: `
    @if (d(); as d) {
      <div class="row-between mb">
        <span class="small muted">Planning and building approvals: when they were submitted, the authority's questions, conditions and validity.</span>
        @if (d.can_write) { <p-button label="New approval" icon="pi pi-plus" size="small" (onClick)="openNew()" /> }
      </div>
      @for (x of d.permits; track x.id) {
        <div class="card-row">
          <div class="row-between wrap gap">
            <div><strong>{{ x.type }}</strong>@if (x.title) { · {{ x.title }} } <p-tag [value]="d.statuses[x.status]" [severity]="sev[x.status]" />
              @if (x.expired) { <p-tag value="expired" severity="danger" styleClass="ml-xs" /> } @else if (x.expiring) { <p-tag value="renew soon" severity="warn" styleClass="ml-xs" /> }
              <div class="small muted">@if (x.authority_name) { {{ x.authority_name }} · } @if (x.reference) { ref {{ x.reference }} · }
                @if (x.submitted_on) { submitted {{ x.submitted_on | date: 'd MMM y' }} · } @if (x.approved_on) { approved {{ x.approved_on | date: 'd MMM y' }} · }
                @if (x.valid_until) { valid until {{ x.valid_until | date: 'd MMM y' }} · } @if (x.stage_name) { {{ x.stage_name }} }
                @if (x.fee && seesMoney) { · fee {{ fmt(x.fee) }} }</div></div>
            @if (d.can_write) { <span class="row gap">
              @for (n of next[x.status]; track n) { <p-button [label]="d.statuses[n]" size="small" [text]="n !== 'approved'" (onClick)="ask(x, n)" /> }
            </span> }
          </div>
          @for (c of x.conditions; track c.id) {
            <label class="check small"><p-checkbox [ngModel]="c.met" (ngModelChange)="setCond(x, c, $event)" [binary]="true" [disabled]="!d.can_write" [ariaLabel]="c.text" />
              {{ c.text }} @if (c.met) { <span class="muted">· met {{ c.met_on | date: 'd MMM' }}</span> }</label>
          }
          @if (x.history?.length > 1) { <div class="tiny muted">@for (h of x.history; track $index) { {{ d.statuses[h.status] }}@if (h.note) { ({{ h.note }}) } @if (!$last) { → } }</div> }
          @for (f of x.documents; track f.key) { <a class="small" [href]="f.url" target="_blank" rel="noopener"><i class="pi pi-file"></i> {{ f.name }}</a> }
        </div>
      } @empty { <p class="muted">No approvals tracked yet.</p> }
    }
    <p-dialog header="New approval" [modal]="true" [(visible)]="dlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <label class="field req"><span>Type</span><p-select [options]="d()?.types ?? []" [(ngModel)]="f.type" fluid appendTo="body" /></label>
        <div class="grid2">
          <label class="field"><span>Authority</span><input pInputText [(ngModel)]="f.authority" placeholder="Municipal corporation…" fluid /></label>
          <label class="field"><span>Stage</span><p-select [options]="d()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="f.stage_id" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Fee</span><p-inputnumber [(ngModel)]="f.fee" [min]="0" fluid /></label>
          <label class="field"><span>Expected by</span><input pInputText type="date" [(ngModel)]="f.expected_by" fluid /></label>
        </div>
        <label class="field"><span>Documents</span><input type="file" multiple (change)="attach($event)" /></label>
        <div class="row right"><p-button label="Save" [disabled]="!f.type" (onClick)="save()" /></div>
      </div>
    </p-dialog>
    <p-dialog [header]="'Mark ' + (d()?.statuses?.[askTo] || '').toLowerCase()" [modal]="true" [(visible)]="aDlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="af.date" fluid /></label>
        @if (askTo === 'submitted' && !target?.reference) { <label class="field req"><span>Reference / application no.</span><input pInputText [(ngModel)]="af.reference" fluid /></label> }
        @if (askTo === 'approved') {
          <label class="field"><span>Valid until</span><input pInputText type="date" [(ngModel)]="af.valid_until" fluid /></label>
          <label class="field"><span>Conditions (one per line)</span><textarea class="p-inputtext" rows="3" [(ngModel)]="af.conditions"></textarea></label>
        }
        <label class="field" [class.req]="askTo === 'query' || askTo === 'rejected'"><span>Note</span><input pInputText [(ngModel)]="af.note" fluid /></label>
        <div class="row right"><p-button label="Save" (onClick)="saveStatus()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.card-row { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .9rem; margin-bottom: .6rem; background: var(--surface); display: grid; gap: .25rem; }
    .tiny { font-size: .72rem; }`,
})
export class ProjectPermitsComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  private auth = inject(AuthService);
  d = signal<any>(null);
  sev: Record<string, any> = { preparing: 'secondary', submitted: 'info', query: 'warn', approved: 'success', rejected: 'danger' };
  next: Record<string, string[]> = { preparing: ['submitted'], submitted: ['query', 'approved', 'rejected'], query: ['submitted', 'approved', 'rejected'], rejected: ['submitted'], approved: [] };
  seesMoney = ['owner', 'pm', 'accounts', 'designer'].includes(this.auth.user()?.role ?? '');
  dlg = false; aDlg = false;
  f: any = {};
  af: any = {};
  askTo = '';
  target: any = null;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.d.set(await this.api.get(`/projects/${this.projectId()}/permits`));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  openNew() {
    this.f = { type: null, authority: '', stage_id: null, fee: null, expected_by: null, documents: [] };
    this.dlg = true;
  }

  async attach(ev: Event) {
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) this.f.documents.push((await this.api.upload(file)).key);
  }

  async save() {
    await this.api.post(`/projects/${this.projectId()}/permits`, this.f, 'Approval added');
    this.dlg = false;
    await this.load();
  }

  ask(x: any, to: string) {
    this.target = x;
    this.askTo = to;
    this.af = { date: new Date().toISOString().slice(0, 10), reference: '', note: '', valid_until: null, conditions: '' };
    this.aDlg = true;
  }

  async saveStatus() {
    const body: any = { status: this.askTo, date: this.af.date, note: this.af.note };
    if (this.af.reference) body.reference = this.af.reference;
    if (this.askTo === 'approved') Object.assign(body, { valid_until: this.af.valid_until, conditions: this.af.conditions.split('\n').map((x: string) => x.trim()).filter(Boolean) });
    await this.api.post(`/permits/${this.target.id}/status`, body, 'Updated');
    this.aDlg = false;
    await this.load();
  }

  async setCond(x: any, c: any, met: boolean) {
    await this.api.put(`/permits/${x.id}/conditions/${c.id}`, { met });
    await this.load();
  }
}

// ---------------------------------------------------------------- mood boards
@Component({
  selector: 'app-project-boards',
  imports: [FormsModule, ButtonModule, CheckboxModule, DialogModule, InputTextModule],
  template: `
    @if (d(); as d) {
      <div class="row-between mb">
        <span class="small muted">Images per room for the client to react to. A board appears in the client portal once it is shared.</span>
        @if (d.can_write) { <p-button label="New board" icon="pi pi-plus" size="small" (onClick)="open()" /> }
      </div>
      @for (b of d.boards; track b.id) {
        <div class="board">
          <div class="row-between"><strong>{{ b.title }}@if (b.room) { <span class="muted small"> · {{ b.room }}</span> }</strong>
            <span class="row gap"><span class="small" [class.c-good]="b.shared">{{ b.shared ? 'Shared with the client' : 'Not shared' }}</span>
              @if (d.can_write) { <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="open(b)" ariaLabel="Edit board" /> }</span></div>
          <div class="grid-img">
            @for (it of b.items; track it.id) {
              <figure><img [src]="it.url" [alt]="it.note || 'Mood board image'" />
                <figcaption class="small">{{ it.note }}
                  @if (likes(it)) { <span class="c-good"> · <i class="pi pi-heart-fill"></i> {{ likes(it) }}</span> }
                  @for (r of comments(it); track $index) { <div class="small"><strong>{{ r.name }}:</strong> {{ r.comment }}</div> }</figcaption></figure>
            }
          </div>
        </div>
      } @empty { <p class="muted">No mood boards yet.</p> }
    }
    <p-dialog [header]="f.id ? 'Edit board' : 'New board'" [modal]="true" [(visible)]="dlg" [style]="{ width: '38rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field req"><span>Title</span><input pInputText [(ngModel)]="f.title" fluid /></label>
          <label class="field"><span>Room</span><input pInputText [(ngModel)]="f.room" fluid /></label>
        </div>
        <label class="field"><span>Add images</span><input type="file" accept="image/*" multiple (change)="attach($event)" /></label>
        <div class="row gap"><input pInputText [(ngModel)]="link" placeholder="…or paste an image link (https://)" class="grow" />
          <p-button label="Add link" size="small" [text]="true" [disabled]="!link.startsWith('http')" (onClick)="f.items.push({ image_url: link, note: '' }); link = ''" /></div>
        @for (it of f.items; track $index; let i = $index) {
          <div class="row gap"><img class="thumb" [src]="it.key ? '/api/files/' + it.key : it.image_url" alt="" />
            <input pInputText [(ngModel)]="it.note" placeholder="Note" class="grow" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.items.splice(i, 1)" ariaLabel="Remove image" /></div>
        }
        <label class="check"><p-checkbox [(ngModel)]="f.shared" [binary]="true" ariaLabel="Share with the client" /> Share with the client</label>
        <div class="row right"><p-button label="Save" [disabled]="!f.title?.trim() || !f.items.length" (onClick)="save()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.board { border: 1px solid var(--border); border-radius: var(--radius); padding: .7rem .9rem; margin-bottom: .75rem; background: var(--surface); }
    .grid-img { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .6rem; margin-top: .5rem; }
    figure { margin: 0; } figure img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 6px; }
    .thumb { width: 3.5rem; height: 2.6rem; object-fit: cover; border-radius: 4px; }`,
})
export class ProjectBoardsComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  d = signal<any>(null);
  dlg = false;
  f: any = { items: [] };
  link = '';

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.d.set(await this.api.get(`/projects/${this.projectId()}/boards`));
  }

  likes = (it: any) => (it.reactions ?? []).filter((r: any) => r.like).length;
  comments = (it: any) => (it.reactions ?? []).filter((r: any) => r.comment);

  open(b?: any) {
    this.f = b ? { id: b.id, title: b.title, room: b.room ?? '', shared: b.shared, items: b.items.map((i: any) => ({ id: i.id, key: i.key, image_url: i.image_url, note: i.note ?? '' })) }
      : { title: '', room: '', shared: false, items: [] };
    this.link = '';
    this.dlg = true;
  }

  async attach(ev: Event) {
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) this.f.items.push({ key: (await this.api.upload(file)).key, note: '' });
  }

  async save() {
    const { id, ...body } = this.f;
    if (id) await this.api.put(`/boards/${id}`, body, 'Board saved');
    else await this.api.post(`/projects/${this.projectId()}/boards`, body, 'Board saved');
    this.dlg = false;
    await this.load();
  }
}

// ---------------------------------------------------------------- the Documents tab (declared last: it uses the views above)
/** The project's Documents tab (Phase I block 4): the library and drawings, the approvals register and mood boards. */
@Component({
  selector: 'app-project-design',
  imports: [FormsModule, SelectButtonModule, ProjectDocumentsComponent, ProjectPermitsComponent, ProjectBoardsComponent, ProjectViewsComponent, ProjectOptionsComponent, ProjectModelsComponent],
  template: `
    <p-selectbutton class="mb block" [options]="views" [(ngModel)]="view" optionLabel="label" optionValue="value" [allowEmpty]="false" />
    @switch (view) {
      @case ('permits') { <app-project-permits [projectId]="projectId()" /> }
      @case ('boards') { <app-project-boards [projectId]="projectId()" /> }
      @case ('views') { <app-project-views [projectId]="projectId()" /> }
      @case ('options') { <app-project-options [projectId]="projectId()" /> }
      @case ('models') { <app-project-models [projectId]="projectId()" /> }
      @default { <app-project-documents [projectId]="projectId()" /> }
    }
  `,
})
export class ProjectDesignComponent {
  projectId = input.required<string>();
  views = [{ label: 'Documents & drawings', value: 'docs' }, { label: 'Approvals', value: 'permits' }, { label: 'Mood boards', value: 'boards' }, { label: '360° & renders', value: 'views' }, { label: 'Design options', value: 'options' }, { label: '3D models', value: 'models' }];
  view = 'docs';
}
