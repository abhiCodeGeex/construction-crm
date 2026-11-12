import { ProjectFieldComponent } from './project-field.component';
import { I18n, TPipe } from '../../core/i18n';
import { Component, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { ProjectSiteReportsComponent } from './project-site-reports.component';

// ---------------------------------------------------------------- attendance
@Component({
  selector: 'app-project-attendance',
  imports: [TPipe, FormsModule, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TableModule],
  template: `
    <div class="row gap wrap mb">
      <label class="field"><span>Day</span><input pInputText type="date" [(ngModel)]="day" [max]="today" (change)="load()" /></label>
      <label class="field"><span>Month summary</span><input pInputText type="month" [(ngModel)]="month" (change)="loadSummary()" /></label>
      <span class="grow"></span>
      @if (d()?.can_write) { <p-button label="Add a site worker" icon="pi pi-user-plus" size="small" [text]="true" (onClick)="wDlg = true; wf = { name: '', trade: '', phone: '', language: 'en', whatsapp: false }" /> }
    </div>
    @if (d(); as d) {
      <p-table [value]="rows" styleClass="p-datatable-sm mb">
        <ng-template #header><tr><th>Name</th><th>Trade / role</th><th>Status</th><th>In</th><th>Out</th><th>Overtime h</th></tr></ng-template>
        <ng-template #body let-r><tr>
          <td>{{ r.name }}@if (r.party) { <div class="small muted">{{ r.party }}</div> }</td><td class="small">{{ r.trade || '—' }}</td>
          <td><p-select [options]="statuses" [(ngModel)]="r.status" [disabled]="!d.can_write" [showClear]="true" placeholder="—" appendTo="body" /></td>
          <td><input pInputText type="time" [(ngModel)]="r.in" [disabled]="!d.can_write || !r.status || r.status === 'absent'" /></td>
          <td><input pInputText type="time" [(ngModel)]="r.out" [disabled]="!d.can_write || !r.status || r.status === 'absent'" /></td>
          <td><p-inputnumber [(ngModel)]="r.ot_hours" [min]="0" [max]="12" [disabled]="!d.can_write || !r.status" [inputStyle]="{ width: '4rem' }" /></td></tr></ng-template>
        <ng-template #emptymessage><tr><td colspan="6" class="muted">Nobody on the team or the worker list yet.</td></tr></ng-template>
      </p-table>
      @if (d.can_write) { <div class="row-between"><span class="small muted">{{ marked() }} marked · {{ present() }} present</span>
        <p-button [label]="'Save attendance' | t" icon="pi pi-check" (onClick)="save()" /></div> }
    }
    @if (sum(); as s) {
      <h3>{{ s.month }} · {{ s.days }} day(s) recorded</h3>
      <p-table [value]="s.rows" styleClass="p-datatable-sm">
        <ng-template #header><tr><th>Name</th><th class="num">Days</th><th class="num">Absent</th><th class="num">Overtime h</th>@if (hasCost(s)) { <th class="num">Labour cost</th> }</tr></ng-template>
        <ng-template #body let-x><tr><td>{{ x.name }} <span class="small muted">{{ x.trade }}</span></td><td class="num">{{ x.days }}</td><td class="num">{{ x.absent }}</td>
          <td class="num">{{ x.ot_hours }}</td>@if (hasCost(s)) { <td class="num">{{ x.cost !== null && x.cost !== undefined ? fmt(x.cost) : '—' }}</td> }</tr></ng-template>
        <ng-template #emptymessage><tr><td colspan="5" class="muted">No attendance this month.</td></tr></ng-template>
      </p-table>
    }
    <p-dialog header="Site worker" [modal]="true" [(visible)]="wDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>Name</span><input pInputText [(ngModel)]="wf.name" fluid /></label>
        <div class="grid2">
          <label class="field"><span>Trade</span><input pInputText [(ngModel)]="wf.trade" placeholder="Mason, carpenter…" fluid /></label>
          <label class="field"><span>Phone</span><input pInputText [(ngModel)]="wf.phone" fluid /></label>
          <label class="field"><span>Language of work messages</span>
            <select class="p-inputtext" [(ngModel)]="wf.language"><option value="en">English</option><option value="hi">हिन्दी (Hindi)</option></select></label>
          <label class="check small"><input type="checkbox" [(ngModel)]="wf.whatsapp" [disabled]="!wf.phone" /> Agreed to get work messages on WhatsApp</label>
        </div>
        @if (seesCost) { <label class="field"><span>Daily rate</span><p-inputnumber [(ngModel)]="wf.daily_rate" [min]="0" fluid /></label> }
        <div class="row right"><p-button label="Add" [disabled]="!wf.name?.trim()" (onClick)="addWorker()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.num { text-align: right; } input[type=time] { width: 7rem; }`,
})
export class ProjectAttendanceComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  private auth = inject(AuthService);
  d = signal<any>(null);
  sum = signal<any>(null);
  rows: any[] = [];
  statuses = ['present', 'half_day', 'absent', 'leave'];
  today = new Date().toISOString().slice(0, 10);
  day = this.today;
  month = this.today.slice(0, 7);
  wDlg = false;
  wf: any = {};
  seesCost = ['owner', 'pm', 'accounts'].includes(this.auth.user()?.role ?? '');

  async ngOnInit() {
    await Promise.all([this.load(), this.loadSummary()]);
  }

  async load() {
    const d = await this.api.get(`/projects/${this.projectId()}/attendance?date=${this.day}`);
    const have = Object.fromEntries((d.sheet?.rows ?? []).map((r: any) => [r.person, r]));
    this.rows = d.people.map((x: any) => ({ ...x, status: have[x.person]?.status ?? null, in: have[x.person]?.in ?? '',
      out: have[x.person]?.out ?? '', ot_hours: have[x.person]?.ot_hours ?? 0 }));
    this.d.set(d);
  }

  async loadSummary() {
    this.sum.set(await this.api.get(`/projects/${this.projectId()}/attendance/summary?month=${this.month}`));
  }

  marked = () => this.rows.filter((r) => r.status).length;
  present = () => this.rows.reduce((a, r) => a + (r.status === 'present' ? 1 : r.status === 'half_day' ? 0.5 : 0), 0);
  hasCost = (s: any) => s.rows.some((x: any) => 'cost' in x);

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  async save() {
    const rows = this.rows.filter((r) => r.status).map((r) => ({ person: r.person, status: r.status, in: r.in || null, out: r.out || null, ot_hours: r.ot_hours || 0 }));
    await this.api.put(`/projects/${this.projectId()}/attendance`, { date: this.day, rows }, 'Attendance saved');
    await Promise.all([this.load(), this.loadSummary()]);
  }

  async addWorker() {
    await this.api.post('/site-workers', this.wf, 'Worker added');
    this.wDlg = false;
    await this.load();
  }
}

// ---------------------------------------------------------------- snags
@Component({
  selector: 'app-project-snags',
  imports: [TPipe, FormsModule, DatePipe, ButtonModule, DialogModule, InputTextModule, SelectModule, SelectButtonModule, TagModule],
  template: `
    @if (d(); as d) {
      <div class="row-between wrap gap mb">
        <p-selectbutton [options]="filters" [(ngModel)]="filter" optionLabel="label" optionValue="value" [allowEmpty]="false" />
        <span class="small muted grow">{{ d.counts.open }} open · {{ d.counts.fixed }} to check · {{ d.counts.closed }} closed</span>
        @if (d.can_write) { <p-button [label]="'New snag' | t" icon="pi pi-plus" size="small" (onClick)="openNew()" /> }
      </div>
      @for (s of shown(); track s.id) {
        <div class="snag" [class.late]="s.overdue">
          <div class="row-between wrap gap">
            <div><strong>{{ s.number }} · {{ s.title }}</strong> <p-tag [value]="d.statuses[s.status]" [severity]="sev[s.status]" />
              @if (s.priority === 'high') { <p-tag value="high" severity="danger" styleClass="ml-xs" /> }
              <div class="small muted">@if (s.location) { {{ s.location }} · } @if (s.stage_name) { {{ s.stage_name }} · }
                @if (s.assignee_name) { {{ s.assignee_name }} · } @if (s.party_name) { {{ s.party_name }} · }
                @if (s.due) { due <span [class.c-bad]="s.overdue">{{ s.due | date: 'd MMM' }}</span> }</div>
              @if (s.fix_note) { <div class="small">Fix: {{ s.fix_note }} <span class="muted">({{ s.fixed_by }})</span></div> }
              @if (s.reopen_reason && s.status === 'open') { <div class="small c-warn">Reopened: {{ s.reopen_reason }}</div> }</div>
            <span class="row gap">
              @if (s.status === 'open') { <p-button [label]="'Mark fixed' | t" size="small" (onClick)="ask(s, 'fixed')" /> }
              @if (s.status === 'fixed' && d.can_write) { <p-button label="Close" size="small" (onClick)="act(s, 'close', {})" />
                <p-button label="Reopen" size="small" [text]="true" (onClick)="ask(s, 'reopen')" /> }
              @if (s.status === 'closed' && d.can_write) { <p-button label="Reopen" size="small" [text]="true" (onClick)="ask(s, 'reopen')" /> }
            </span>
          </div>
          @if (s.photos.length || s.fix_photos.length) {
            <div class="photos">@for (ph of s.photos; track ph.key) { <a [href]="ph.url" target="_blank" rel="noopener"><img [src]="ph.url" alt="Snag photo" /></a> }
              @for (ph of s.fix_photos; track ph.key) { <a [href]="ph.url" target="_blank" rel="noopener" class="fix"><img [src]="ph.url" alt="Fixed photo" /></a> }</div>
          }
        </div>
      } @empty { <p class="muted">No snags here.</p> }
    }
    <p-dialog header="New snag" [modal]="true" [(visible)]="dlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <label class="field req"><span>What is wrong</span><input pInputText [(ngModel)]="f.title" fluid /></label>
        <div class="grid2">
          <label class="field"><span>Where</span><input pInputText [(ngModel)]="f.location" placeholder="Kitchen, 2nd floor…" fluid /></label>
          <label class="field"><span>Stage</span><p-select [options]="d()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="f.stage_id" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Assign to</span><p-select [options]="d()?.team ?? []" optionLabel="name" optionValue="id" [(ngModel)]="f.assignee_id" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Due</span><input pInputText type="date" [(ngModel)]="f.due" fluid /></label>
          <label class="field"><span>Priority</span><p-select [options]="d()?.priorities ?? []" [(ngModel)]="f.priority" fluid appendTo="body" /></label>
          <label class="field"><span>Photo</span><input type="file" accept="image/*" capture="environment" multiple (change)="attach($event, f.photos)" /></label>
        </div>
        @if (f.photos?.length) { <span class="small muted">{{ f.photos.length }} photo(s)</span> }
        <div class="row right"><p-button label="Raise" [disabled]="!f.title?.trim() || busy" (onClick)="save()" /></div>
      </div>
    </p-dialog>
    <p-dialog [header]="askFor === 'fixed' ? 'Mark fixed' : 'Reopen'" [modal]="true" [(visible)]="aDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field" [class.req]="askFor === 'reopen'"><span>{{ askFor === 'fixed' ? 'What was done' : 'Why' }}</span><input pInputText [(ngModel)]="note" fluid /></label>
        @if (askFor === 'fixed') { <label class="field"><span>Photo of the fix</span><input type="file" accept="image/*" capture="environment" (change)="attach($event, fixPhotos)" /></label> }
        <div class="row right"><p-button label="Save" [disabled]="(askFor === 'reopen' && !note.trim()) || busy" (onClick)="confirmAsk()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .snag { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .9rem; margin-bottom: .6rem; background: var(--surface); }
    .snag.late { border-left: 3px solid var(--bad, #dc2626); }
    .photos { display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .4rem; }
    .photos img { width: 5rem; height: 3.8rem; object-fit: cover; border-radius: 6px; }
    .photos .fix img { outline: 2px solid var(--good, #16a34a); }
  `,
})
export class ProjectSnagsComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  d = signal<any>(null);
  sev: Record<string, 'danger' | 'warn' | 'success'> = { open: 'danger', fixed: 'warn', closed: 'success' };
  filters = [{ label: 'Not closed', value: 'live' }, { label: 'All', value: 'all' }];
  filter = 'live';
  dlg = false; aDlg = false; busy = false;
  f: any = {};
  askFor: 'fixed' | 'reopen' = 'fixed';
  note = '';
  fixPhotos: string[] = [];
  private target: any = null;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.d.set(await this.api.get(`/projects/${this.projectId()}/snags`));
  }

  shown() {
    return (this.d()?.snags ?? []).filter((s: any) => this.filter === 'all' || s.status !== 'closed');
  }

  openNew() {
    this.f = { title: '', location: '', stage_id: null, assignee_id: null, due: null, priority: 'normal', photos: [] };
    this.dlg = true;
  }

  async attach(ev: Event, into: string[]) {
    this.busy = true;
    try {
      for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) into.push((await this.api.upload(file)).key);
    } finally {
      this.busy = false;
    }
  }

  async save() {
    await this.api.post(`/projects/${this.projectId()}/snags`, this.f, 'Snag raised');
    this.dlg = false;
    await this.load();
  }

  ask(s: any, what: 'fixed' | 'reopen') {
    this.target = s;
    this.askFor = what;
    this.note = '';
    this.fixPhotos = [];
    this.aDlg = true;
  }

  async confirmAsk() {
    if (this.askFor === 'fixed') await this.act(this.target, 'fixed', { note: this.note, photos: this.fixPhotos });
    else await this.act(this.target, 'reopen', { reason: this.note });
    this.aDlg = false;
  }

  async act(s: any, what: string, body: any) {
    await this.api.post(`/snags/${s.id}/${what}`, body, 'Saved');
    await this.load();
  }
}

// ---------------------------------------------------------------- stock
@Component({
  selector: 'app-project-stock',
  imports: [TPipe, FormsModule, DatePipe, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TableModule],
  template: `
    @if (d(); as d) {
      <div class="row-between wrap gap mb">
        <span class="small muted">Received on this site (GRNs) and moved in, less what was used and moved out.</span>
        <span class="row gap">
          @if (d.can_consume && d.rows.length) { <p-button [label]="'Record use' | t" icon="pi pi-minus-circle" size="small" (onClick)="openUse()" /> }
          @if (d.can_transfer) { <p-button label="Move stock" icon="pi pi-arrow-right-arrow-left" size="small" [text]="true" (onClick)="openMove()" /> }
        </span>
      </div>
      <p-table [value]="d.rows" styleClass="p-datatable-sm mb">
        <ng-template #header><tr><th>Material</th><th class="num">Received</th><th class="num">In / out</th><th class="num">Used</th><th class="num">On site</th>@if (seesValue()) { <th class="num">Value</th> }</tr></ng-template>
        <ng-template #body let-r><tr><td>{{ r.description }}</td><td class="num">{{ r.received }}</td>
          <td class="num">+{{ r.transfer_in }} / −{{ r.transfer_out }}@if (r.adjusted) { <div class="small muted">count {{ r.adjusted > 0 ? '+' : '' }}{{ r.adjusted }}</div> }</td>
          <td class="num">{{ r.consumed }}</td><td class="num"><strong>{{ r.balance }}</strong> {{ r.unit }}</td>
          @if (seesValue()) { <td class="num">{{ fmt(r.value) }}</td> }</tr></ng-template>
        <ng-template #emptymessage><tr><td colspan="6" class="muted">Nothing received on this site yet.</td></tr></ng-template>
      </p-table>
      @if (d.moves.length) {
        <h3>Movements</h3>
        @for (m of d.moves.slice(0, 30); track m.id) {
          <div class="small">{{ m.date | date: 'd MMM' }} · {{ label[m.kind] }} {{ m.qty }} {{ m.unit }} {{ m.description }}
            @if (m.stage_name) { · {{ m.stage_name }} } @if (m.other) { · {{ m.other }} } @if (m.note) { · {{ m.note }} } <span class="muted">· {{ m.by }}</span></div>
        }
      }
    }
    <p-dialog header="Material used on site" [modal]="true" [(visible)]="useDlg" [style]="{ width: '36rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="uf.date" [max]="today" fluid /></label>
          <label class="field"><span>Stage</span><p-select [options]="d()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="uf.stage_id" [showClear]="true" fluid appendTo="body" /></label>
        </div>
        @for (r of uf.lines; track r.key) {
          <div class="use-row"><span>{{ r.description }} <span class="small muted">{{ r.balance }} {{ r.unit }} on site</span></span>
            <p-inputnumber [(ngModel)]="r.qty" [min]="0" [max]="r.balance" [maxFractionDigits]="2" [inputStyle]="{ width: '100%' }" /></div>
        }
        <div class="row right"><p-button label="Record" [disabled]="!uf.lines?.some(hasQty)" (onClick)="saveUse()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Move stock" [modal]="true" [(visible)]="mvDlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>From</span><p-select [options]="places()" optionLabel="label" optionValue="value" [(ngModel)]="mf.from" (onChange)="loadFrom()" fluid appendTo="body" /></label>
          <label class="field"><span>To</span><p-select [options]="places()" optionLabel="label" optionValue="value" [(ngModel)]="mf.to" fluid appendTo="body" /></label>
        </div>
        @for (r of mf.lines; track r.key) {
          <div class="use-row"><span>{{ r.description }} <span class="small muted">{{ r.balance }} {{ r.unit }}</span></span>
            <p-inputnumber [(ngModel)]="r.qty" [min]="0" [max]="r.balance" [maxFractionDigits]="2" [inputStyle]="{ width: '100%' }" /></div>
        } @empty { <span class="small muted">Nothing in stock there.</span> }
        <div class="row right"><p-button label="Move" [disabled]="!mf.to || mf.to === mf.from || !mf.lines?.some(hasQty)" (onClick)="saveMove()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.num { text-align: right; font-variant-numeric: tabular-nums; } .use-row { display: grid; grid-template-columns: minmax(0, 1fr) 8rem; gap: .5rem; align-items: center; }`,
})
export class ProjectStockComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  private auth = inject(AuthService);
  d = signal<any>(null);
  label: Record<string, string> = { consumed: 'Used', transfer_in: 'Moved in', transfer_out: 'Moved out', adjusted: 'Counted' };
  today = new Date().toISOString().slice(0, 10);
  useDlg = false; mvDlg = false;
  uf: any = {};
  mf: any = {};
  hasQty = (r: any) => r.qty > 0;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.d.set(await this.api.get(`/projects/${this.projectId()}/stock`));
  }

  seesValue() {
    return (this.d()?.rows ?? []).some((r: any) => 'value' in r);
  }

  places() {
    return [{ label: 'This site', value: `p:${this.projectId()}` }, ...(this.d()?.warehouses ?? []).map((w: any) => ({ label: w.name, value: `w:${w.id}` }))];
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  openUse() {
    this.uf = { date: this.today, stage_id: null, lines: this.d().rows.filter((r: any) => r.balance > 0).map((r: any) => ({ ...r, qty: null })) };
    this.useDlg = true;
  }

  async saveUse() {
    const lines = this.uf.lines.filter(this.hasQty).map((r: any) => ({ key: r.key, qty: r.qty, stage_id: this.uf.stage_id }));
    await this.api.post(`/projects/${this.projectId()}/stock/consume`, { date: this.uf.date, lines }, 'Use recorded');
    this.useDlg = false;
    await this.load();
  }

  async openMove() {
    this.mf = { from: `p:${this.projectId()}`, to: null, lines: [] };
    await this.loadFrom();
    this.mvDlg = true;
  }

  async loadFrom() {
    const rows = this.mf.from.startsWith('w:') ? (await this.api.get(`/warehouses/${this.mf.from.slice(2)}/stock`)).rows : this.d().rows;
    this.mf.lines = rows.filter((r: any) => r.balance > 0).map((r: any) => ({ ...r, qty: null }));
  }

  async saveMove() {
    await this.api.post('/stock/transfer', { from: this.mf.from, to: this.mf.to, lines: this.mf.lines.filter(this.hasQty).map((r: any) => ({ key: r.key, qty: r.qty })) }, 'Stock moved');
    this.mvDlg = false;
    await this.load();
  }
}

// ---------------------------------------------------------------- the tab (declared last: it uses the views above)
/** The project's Site tab (Phase I block 3): daily reports, attendance, snags and stock at site. */
@Component({
  selector: 'app-project-site',
  imports: [TPipe, ProjectSiteReportsComponent, FormsModule, SelectButtonModule, ButtonModule, DialogModule, InputTextModule, ProjectAttendanceComponent, ProjectSnagsComponent, ProjectStockComponent, ProjectFieldComponent],
  template: `
    <div class="row-between wrap gap mb">
      <p-selectbutton [options]="views" [(ngModel)]="view" optionLabel="label" optionValue="value" [allowEmpty]="false" />
      <p-button [label]="'Ask for a change' | t" icon="pi pi-sync" size="small" [text]="true" (onClick)="crDlg = true; cr = { title: '', description: '' }" />
    </div>
    <p-dialog header="Ask for a change" [modal]="true" [(visible)]="crDlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <label class="field req"><span>What needs to change</span><input pInputText [(ngModel)]="cr.title" fluid /></label>
        <label class="field"><span>Why / details</span><input pInputText [(ngModel)]="cr.description" fluid /></label>
        <p class="small muted m0">The PM gets it as a draft change order to price.</p>
        <div class="row right"><p-button label="Send to the PM" [disabled]="!cr.title?.trim()" (onClick)="askChange()" /></div>
      </div>
    </p-dialog>
    @switch (view) {
      @case ('attendance') { <app-project-attendance [projectId]="projectId()" /> }
      @case ('snags') { <app-project-snags [projectId]="projectId()" /> }
      @case ('stock') { <app-project-stock [projectId]="projectId()" /> }
      @case ('field') { <app-project-field [projectId]="projectId()" /> }
      @default { <app-project-site-reports [projectId]="projectId()" /> }
    }
  `,
})
export class ProjectSiteComponent {
  projectId = input.required<string>();
  private i18n = inject(I18n);
  get views() {
    return [['Daily reports', 'reports'], ['Attendance', 'attendance'], ['Snags', 'snags'], ['Stock', 'stock'], ['Workers on WhatsApp', 'field']].map(([l, v]) => ({ label: this.i18n.t(l), value: v }));
  }
  view = 'reports';
  private api = inject(Api);
  crDlg = false;
  cr: any = {};

  async askChange() {
    await this.api.post(`/projects/${this.projectId()}/change-requests`, this.cr, 'Sent to the PM');
    this.crDlg = false;
  }
}
