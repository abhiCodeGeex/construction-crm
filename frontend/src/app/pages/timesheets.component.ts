import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Phase K block 3 — my hours, approving hours, the hours report and the resource calendar. */
@Component({
  selector: 'app-timesheets',
  imports: [FormsModule, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, SelectButtonModule, TagModule],
  template: `
    <div class="page">
      <div class="row-between wrap gap mb"><h1 class="m0">Timesheets</h1>
        <p-selectbutton [options]="parts" [(ngModel)]="part" optionLabel="label" optionValue="value" [allowEmpty]="false" (ngModelChange)="load()" /></div>
      @switch (part) {
        @case ('week') {
          @if (w(); as w) {
            <div class="row-between wrap gap mb">
              <span class="row gap"><p-button icon="pi pi-chevron-left" [text]="true" (onClick)="shift(-7)" ariaLabel="Previous week" /><strong>Week of {{ w.week }}</strong>
                <p-button icon="pi pi-chevron-right" [text]="true" (onClick)="shift(7)" ariaLabel="Next week" /></span>
              <span class="row gap"><p-button label="Log hours" icon="pi pi-plus" size="small" (onClick)="openEntry()" />
                <p-button label="Submit the week" size="small" [outlined]="true" (onClick)="submit()" /></span>
            </div>
            <div class="days">@for (d of w.days; track d) { <div class="day" [class.over]="w.totals[d] > w.capacity"><span class="small muted">{{ d.slice(5) }}</span><strong>{{ w.totals[d] }} h</strong></div> }</div>
            @for (e of w.entries; track e.id) {
              <div class="row-between card-row"><span><strong>{{ e.date }}</strong> · {{ e.project_name }}@if (e.stage_name) { · {{ e.stage_name }} } · {{ e.hours }} h
                @if (!e.billable) { <span class="small muted"> (not billable)</span> } @if (e.note) { <span class="small muted"> — {{ e.note }}</span> }
                @if (e.reason) { <div class="small c-bad">Returned: {{ e.reason }}</div> }</span>
                <span class="row gap"><p-tag [value]="e.status" [severity]="e.status === 'approved' ? 'success' : e.status === 'rejected' ? 'danger' : e.status === 'submitted' ? 'info' : 'secondary'" />
                  @if (e.status === 'draft' || e.status === 'rejected') { <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="openEntry(e)" ariaLabel="Edit" />
                    <p-button icon="pi pi-trash" [text]="true" size="small" severity="secondary" (onClick)="del(e)" ariaLabel="Delete" /> }</span></div>
            } @empty { <p class="muted">No hours this week.</p> }
          }
        }
        @case ('approve') {
          <div class="row gap mb"><p-button label="Approve selected" size="small" [disabled]="!picked.size" (onClick)="decide('approve')" />
            <p-button label="Return selected" size="small" [text]="true" severity="danger" [disabled]="!picked.size" (onClick)="decide('reject')" /></div>
          @for (e of approvals(); track e.id) {
            <label class="row gap card-row"><input type="checkbox" [checked]="picked.has(e.id)" (change)="toggle(e.id)" />
              <span class="grow"><strong>{{ e.user_name }}</strong> · {{ e.date }} · {{ e.project_name }}@if (e.stage_name) { · {{ e.stage_name }} } · {{ e.hours }} h @if (e.note) { — {{ e.note }} }</span></label>
          } @empty { <p class="muted">Nothing waiting for you.</p> }
        }
        @case ('report') {
          <div class="row gap mb"><input pInputText type="date" [(ngModel)]="from" aria-label="From" /><input pInputText type="date" [(ngModel)]="to" aria-label="To" /><p-button label="Show" size="small" (onClick)="load()" /></div>
          @if (r(); as r) {
            <h3>By person (capacity {{ r.capacity_hours }} h)</h3>
            <table class="t"><tr><th>Person</th><th>Hours</th><th>Billable</th><th>Utilisation</th></tr>
              @for (x of r.people; track x.name) { <tr><td>{{ x.name }}</td><td>{{ x.hours }}</td><td>{{ x.billable_pct ?? '—' }}%</td><td [class.c-bad]="x.utilisation > 100">{{ x.utilisation ?? '—' }}%</td></tr> }</table>
            <h3>By project</h3>
            <table class="t"><tr><th>Project</th><th>Hours</th><th>Billable</th>@if (r.projects[0]?.cost !== null) { <th>Cost</th> }<th>By stage</th></tr>
              @for (x of r.projects; track x.project_id) { <tr><td>{{ x.project }}</td><td>{{ x.hours }}</td><td>{{ x.billable }}</td>@if (x.cost !== null) { <td>{{ x.cost }}</td> }
                <td class="small">@for (s of stageList(x.stages); track s[0]) { {{ s[0] }} {{ s[1] }} h@if (!$last) { · } }</td></tr> }</table>
          }
        }
        @case ('plan') {
          @if (rc(); as rc) {
            <div class="tablewrap"><table class="t cal"><tr><th>Person</th>@for (d of rc.days; track d) { <th class="small">{{ d.slice(5) }}</th> }</tr>
              @for (p of rc.people; track p.user_id) { <tr><td>{{ p.name }}<div class="small muted">{{ p.role }}</div></td>
                @for (d of rc.days; track d) { <td [class.busy]="p.days[d].tasks.length === 1" [class.over]="p.days[d].tasks.length > 1" [title]="titles(p.days[d].tasks)">
                  @if (p.days[d].tasks.length) { {{ p.days[d].tasks.length }}t } @if (p.days[d].hours) { <div class="small">{{ p.days[d].hours }}h</div> }</td> }</tr> }</table></div>
            <p class="small muted">t = tasks assigned that day (red: more than one), h = hours logged.</p>
          }
        }
      }
    </div>
    <p-dialog [header]="ef.id ? 'Edit hours' : 'Log hours'" [modal]="true" [(visible)]="dlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <label class="field req"><span>Project</span><p-select [options]="w()?.projects ?? []" optionLabel="name" optionValue="id" [(ngModel)]="ef.project_id" fluid appendTo="body" /></label>
        <label class="field"><span>Stage</span><p-select [options]="stagesOf(ef.project_id)" optionLabel="name" optionValue="id" [(ngModel)]="ef.stage_id" [showClear]="true" fluid appendTo="body" /></label>
        <div class="grid2"><label class="field req"><span>Date</span><input pInputText type="date" [(ngModel)]="ef.date" fluid /></label>
          <label class="field req"><span>Hours</span><p-inputnumber [(ngModel)]="ef.hours" [min]="0.25" [max]="24" [step]="0.25" [maxFractionDigits]="2" fluid /></label></div>
        <label class="check"><p-checkbox [(ngModel)]="ef.billable" [binary]="true" ariaLabel="Billable" /> Billable to the client</label>
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="ef.note" fluid /></label>
        <div class="row right"><p-button label="Save" [disabled]="!ef.project_id || !ef.hours" (onClick)="saveEntry()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.days { display: grid; grid-template-columns: repeat(7, 1fr); gap: .4rem; margin-bottom: .8rem; }
    .day { border: 1px solid var(--border); border-radius: 8px; padding: .4rem; display: grid; text-align: center; } .day.over { border-color: #c0392b; }
    .card-row { border: 1px solid var(--border); border-radius: 8px; padding: .5rem .7rem; margin-bottom: .4rem; background: var(--surface); }
    .tablewrap { overflow-x: auto; } .t { width: 100%; border-collapse: collapse; font-size: .88rem; } .t td, .t th { border-bottom: 1px solid var(--border); padding: .3rem .4rem; text-align: left; }
    .cal td { text-align: center; min-width: 2.6rem; } .busy { background: rgba(37, 99, 235, .12); } .over { background: rgba(192, 57, 43, .18); }`,
})
export class TimesheetsComponent {
  private api = inject(Api);
  private auth = inject(AuthService);
  isManager = ['owner', 'pm'].includes(this.auth.user()?.role ?? '');
  parts = [{ label: 'My week', value: 'week' }, ...(this.isManager ? [{ label: 'Approve', value: 'approve' }, { label: 'Report', value: 'report' }, { label: 'Resource plan', value: 'plan' }] : [])];
  part = 'week';
  week = new Date().toISOString().slice(0, 10);
  from = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  to = new Date().toISOString().slice(0, 10);
  w = signal<any>(null);
  approvals = signal<any[]>([]);
  r = signal<any>(null);
  rc = signal<any>(null);
  picked = new Set<string>();
  dlg = false;
  ef: any = {};

  async ngOnInit() {
    const q = new URLSearchParams(location.search).get('tab');
    if (q === 'approve' && this.isManager) this.part = 'approve';
    await this.load();
  }

  async load() {
    if (this.part === 'week') this.w.set(await this.api.get(`/timesheets?week=${this.week}`));
    if (this.part === 'approve') { this.approvals.set(await this.api.get('/timesheets/approvals')); this.picked.clear(); }
    if (this.part === 'report') this.r.set(await this.api.get(`/reports/timesheets?from=${this.from}&to=${this.to}`));
    if (this.part === 'plan') this.rc.set(await this.api.get('/resources'));
  }

  async shift(days: number) {
    const d = new Date(this.w().week);
    d.setDate(d.getDate() + days);
    this.week = d.toISOString().slice(0, 10);
    await this.load();
  }

  stagesOf = (pid: string) => this.w()?.projects.find((p: any) => p.id === pid)?.stages ?? [];
  stageList = (o: Record<string, number>) => Object.entries(o);
  titles = (ts: any[]) => ts.map((t) => `${t.project}: ${t.task}`).join('\n');
  toggle = (id: string) => (this.picked.has(id) ? this.picked.delete(id) : this.picked.add(id));

  openEntry(e?: any) {
    this.ef = e ? { id: e.id, project_id: e.project_id, stage_id: e.stage_id, date: e.date, hours: e.hours, billable: e.billable, note: e.note ?? '' }
      : { project_id: this.w()?.projects[0]?.id ?? null, stage_id: null, date: new Date().toISOString().slice(0, 10), hours: null, billable: true, note: '' };
    this.dlg = true;
  }

  async saveEntry() {
    const { id, ...body } = this.ef;
    if (id) await this.api.put(`/timesheets/${id}`, body, 'Saved');
    else await this.api.post('/timesheets', body, 'Hours logged');
    this.dlg = false;
    await this.load();
  }

  async del(e: any) {
    await this.api.del(`/timesheets/${e.id}`, 'Deleted');
    await this.load();
  }

  async submit() {
    await this.api.post('/timesheets/submit', { week: this.w().week }, 'Sent for approval');
    await this.load();
  }

  async decide(decision: string) {
    const reason = decision === 'reject' ? prompt('Why are the hours returned?') : '';
    if (decision === 'reject' && !reason?.trim()) return;
    await this.api.post('/timesheets/decide', { ids: [...this.picked], decision, reason }, decision === 'approve' ? 'Approved' : 'Returned');
    await this.load();
  }
}
