import { Component, computed, inject, input, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';

const PALETTE = ['#2563eb', '#14b8a6', '#f59e0b', '#ef4444', '#8b5cf6', '#22c55e', '#ec4899', '#64748b'];

/** A result as a number, bars, a line, a pie or a table — plain SVG, no chart library. */
@Component({
  selector: 'app-report-chart',
  imports: [DecimalPipe],
  template: `
    @let r = result();
    @if (!r.rows.length) { <p class="muted small">No records match.</p> }
    @else if (chart() === 'kpi') {
      <div class="kpi">{{ r.totals[m()] ?? r.rows[0][m()] | number: '1.0-2' }}</div><div class="small muted">{{ mLabel() }} · {{ r.matched }} record(s)</div>
    } @else if (chart() === 'bar') {
      <div class="bars">@for (row of top(); track $index) {
        <div class="bar-row"><span class="lbl" [title]="row.keys.join(' · ')">{{ row.keys.join(' · ') }}</span>
          <span class="track"><span class="fill" [style.width.%]="pct(row[m()])"></span></span><span class="val">{{ row[m()] | number: '1.0-0' }}</span></div>
      }</div>
    } @else if (chart() === 'line') {
      <svg viewBox="0 0 300 120" class="svg" role="img" [attr.aria-label]="mLabel() + ' over time'">
        <polyline [attr.points]="linePoints()" fill="none" stroke="#2563eb" stroke-width="2" />
        @for (p of dots(); track $index) { <circle [attr.cx]="p.x" [attr.cy]="p.y" r="2.5" fill="#2563eb"><title>{{ p.label }}: {{ p.v }}</title></circle> }
      </svg>
      <div class="row-between small muted"><span>{{ r.rows[0].keys[0] }}</span><span>{{ r.rows[r.rows.length - 1].keys[0] }}</span></div>
    } @else if (chart() === 'pie') {
      <div class="row gap wrap"><svg viewBox="-1.1 -1.1 2.2 2.2" class="pie" role="img" [attr.aria-label]="mLabel()">
          @for (s of slices(); track $index) { <path [attr.d]="s.d" [attr.fill]="s.c"><title>{{ s.label }}: {{ s.v }}</title></path> }</svg>
        <div class="legend">@for (s of slices(); track $index) { <div class="small"><span class="sw" [style.background]="s.c"></span>{{ s.label }} — {{ s.v | number: '1.0-0' }}</div> }</div></div>
    } @else {
      <div class="tbl"><table><thead><tr>@for (c of r.columns; track c.key) { <th [class.num]="c.measure">{{ c.label }}</th> }</tr></thead>
        <tbody>@for (row of r.rows; track $index) { <tr>@for (k of row.keys.slice(0, r.spec.group_by.length); track $index) { <td>{{ k }}</td> }
          @for (mm of r.spec.measures; track mm) { <td class="num">{{ row[mm] | number: '1.0-2' }}</td> }</tr> }</tbody>
        @if (r.spec.group_by.length) { <tfoot><tr><td [attr.colspan]="r.spec.group_by.length"><strong>Total</strong></td>@for (mm of r.spec.measures; track mm) { <td class="num"><strong>{{ r.totals[mm] ?? '' | number: '1.0-2' }}</strong></td> }</tr></tfoot> }
      </table></div>
      @if (r.more) { <div class="small muted">and {{ r.more }} more row(s)</div> }
    }
  `,
  styles: `.kpi { font-size: 2.2rem; font-weight: 700; } .bars { display: grid; gap: .3rem; } .bar-row { display: grid; grid-template-columns: 9rem 1fr 4.5rem; gap: .4rem; align-items: center; font-size: .85rem; }
    .lbl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .track { background: var(--surface-ground, #eef2f7); border-radius: 4px; height: .8rem; }
    .fill { display: block; height: 100%; background: #2563eb; border-radius: 4px; } .val { text-align: right; } .svg { width: 100%; height: 140px; }
    .pie { width: 140px; height: 140px; } .sw { display: inline-block; width: .7rem; height: .7rem; border-radius: 2px; margin-right: .3rem; }
    .tbl { overflow-x: auto; } table { border-collapse: collapse; width: 100%; font-size: .88rem; } th, td { padding: .3rem .5rem; border-bottom: 1px solid var(--border); text-align: left; } .num { text-align: right; }`,
})
export class ReportChartComponent {
  result = input.required<any>();
  chart = input<string>('table');
  m = computed(() => this.result().spec.measures[0]);
  mLabel = computed(() => this.result().columns.find((c: any) => c.key === this.m())?.label ?? '');
  top = computed(() => this.result().rows.slice(0, 15));
  max = computed(() => Math.max(1, ...this.top().map((r: any) => Math.abs(r[this.m()]))));

  pct(v: number) {
    return (100 * Math.abs(v)) / this.max();
  }

  dots() {
    const rows = this.result().rows;
    const vals = rows.map((r: any) => r[this.m()]);
    const hi = Math.max(1, ...vals), n = Math.max(1, rows.length - 1);
    return rows.map((r: any, i: number) => ({ x: 6 + (288 * i) / n, y: 112 - (100 * r[this.m()]) / hi, v: r[this.m()], label: r.keys.join(' · ') }));
  }

  linePoints() {
    return this.dots().map((p: any) => `${p.x},${p.y}`).join(' ');
  }

  slices() {
    const rows = this.top().filter((r: any) => r[this.m()] > 0);
    const total = rows.reduce((s: number, r: any) => s + r[this.m()], 0) || 1;
    let a = -Math.PI / 2;
    return rows.map((r: any, i: number) => {
      const da = (2 * Math.PI * r[this.m()]) / total;
      const [x1, y1, x2, y2] = [Math.cos(a), Math.sin(a), Math.cos(a + da), Math.sin(a + da)];
      const d = rows.length === 1 ? 'M -1 0 A 1 1 0 1 1 1 0 A 1 1 0 1 1 -1 0 Z' : `M 0 0 L ${x1} ${y1} A 1 1 0 ${da > Math.PI ? 1 : 0} 1 ${x2} ${y2} Z`;
      a += da;
      return { d, c: PALETTE[i % PALETTE.length], v: r[this.m()], label: r.keys.join(' · ') };
    });
  }
}

/** Phase L block 6 — the report builder: dataset, group by, measures, filters, range → table / chart, CSV, save, email. */
@Component({
  selector: 'app-report-builder',
  imports: [FormsModule, ButtonModule, DialogModule, InputTextModule, MultiSelectModule, SelectModule, SelectButtonModule, TagModule, ReportChartComponent],
  template: `
    <div class="page-head"><h2>Report builder</h2>
      <span class="row gap"><p-select [options]="saved()" [(ngModel)]="openId" optionLabel="name" optionValue="id" placeholder="Open a saved report" [showClear]="true" (onChange)="openSaved()" ariaLabel="Saved reports" /></span></div>
    <div class="grid">
      <div class="panel stack">
        <label class="small">Data <p-select [options]="meta().datasets" [(ngModel)]="spec.dataset" optionLabel="label" optionValue="key" (onChange)="reset()" styleClass="w100" ariaLabel="Dataset" /></label>
        @if (ds(); as d) {
          <label class="small">Group by <p-multiselect [options]="d.dims" [(ngModel)]="spec.group_by" optionLabel="label" optionValue="key" [selectionLimit]="2" placeholder="(no grouping)" styleClass="w100" ariaLabel="Group by" /></label>
          <label class="small">Show <p-multiselect [options]="d.measures" [(ngModel)]="spec.measures" optionLabel="label" optionValue="key" [selectionLimit]="4" styleClass="w100" ariaLabel="Measures" /></label>
          <label class="small">Period <p-select [options]="periods" [(ngModel)]="period" optionLabel="label" optionValue="value" styleClass="w100" ariaLabel="Period" /></label>
          @if (period === 'custom') { <div class="row gap"><input pInputText type="date" [(ngModel)]="spec.range.from" aria-label="From" /><input pInputText type="date" [(ngModel)]="spec.range.to" aria-label="To" /></div> }
          <label class="small">Filter on <p-select [options]="d.dims" [(ngModel)]="fDim" optionLabel="label" optionValue="key" placeholder="field" [showClear]="true" (onChange)="loadValues()" styleClass="w100" ariaLabel="Filter field" /></label>
          @if (fDim) { <p-multiselect [options]="values()" [(ngModel)]="spec.filters[fDim]" placeholder="values" [filter]="true" styleClass="w100" ariaLabel="Filter values" /> }
          @for (f of filterList(); track f.k) { <div class="small"><p-tag [value]="f.label + ': ' + f.v.join(', ')" /> <a href="" (click)="$event.preventDefault(); clearFilter(f.k)">×</a></div> }
          <label class="small">Chart <p-selectbutton [options]="charts" [(ngModel)]="spec.chart" optionLabel="label" optionValue="value" [allowEmpty]="false" ariaLabel="Chart" /></label>
          <div class="row gap wrap"><p-button label="Run" icon="pi pi-play" (onClick)="run()" /><p-button label="CSV" icon="pi pi-download" [outlined]="true" [disabled]="!res()" (onClick)="csv()" />
            <p-button label="Save" icon="pi pi-save" [text]="true" [disabled]="!res()" (onClick)="saveDlg = true" /></div>
        }
      </div>
      <div class="panel">
        @if (res(); as r) {
          <div class="small muted mb">{{ r.matched }} record(s){{ r.from ? ' · ' + r.from + ' to ' + r.to : '' }}@if (money()) { · amounts in {{ r.currency }} }</div>
          <app-report-chart [result]="r" [chart]="spec.chart" />
        } @else { <p class="muted">Choose the data and what to show, then Run.</p> }
      </div>
    </div>
    <p-dialog header="Save report" [modal]="true" [(visible)]="saveDlg" [style]="{ width: '30rem' }">
      <div class="stack"><input pInputText [(ngModel)]="sv.name" placeholder="Name" aria-label="Name" />
        @if (canShare) { <label class="small"><input type="checkbox" [(ngModel)]="sv.shared" /> Share with the company</label> }
        <label class="small">Email it <select class="p-inputtext" [(ngModel)]="sv.every" aria-label="Email it"><option value="">never</option><option value="week">every Monday</option><option value="month">on the 1st</option></select></label>
        @if (sv.every) { <p-multiselect [options]="users()" [(ngModel)]="sv.to" optionLabel="name" optionValue="id" placeholder="To" ariaLabel="Recipients" /> }
        <div class="row right"><p-button label="Save" [disabled]="!sv.name.trim() || (sv.every && !sv.to.length)" (onClick)="save()" /></div></div>
    </p-dialog>
  `,
  styles: `.grid { display: grid; grid-template-columns: minmax(16rem, 22rem) 1fr; gap: 1rem; } @media (max-width: 800px) { .grid { grid-template-columns: 1fr; } }
    .panel { border: 1px solid var(--border); border-radius: 10px; padding: .8rem; } :host ::ng-deep .w100 { width: 100%; }`,
})
export class ReportBuilderComponent {
  private api = inject(Api);
  private http = inject(HttpClient);
  private auth = inject(AuthService);
  canShare = ['owner', 'pm'].includes(this.auth.user()?.role ?? '');
  meta = signal<any>({ datasets: [] });
  saved = signal<any[]>([]);
  users = signal<any[]>([]);
  values = signal<string[]>([]);
  res = signal<any>(null);
  spec: any = { dataset: 'leads', group_by: [], measures: ['count'], filters: {}, range: {}, chart: 'bar' };
  period = 'last_90';
  periods = [{ label: 'Last 30 days', value: 'last_30' }, { label: 'Last 90 days', value: 'last_90' }, { label: 'Last 12 months', value: 'last_365' },
    { label: 'All time', value: 'all' }, { label: 'Between dates…', value: 'custom' }];
  charts = [{ label: 'Table', value: 'table' }, { label: 'Bar', value: 'bar' }, { label: 'Line', value: 'line' }, { label: 'Pie', value: 'pie' }, { label: 'Number', value: 'kpi' }];
  fDim: string | null = null;
  openId: string | null = null;
  saveDlg = false;
  sv: any = { name: '', shared: false, every: '', to: [] };

  ds = computed(() => this.meta().datasets.find((d: any) => d.key === this.spec.dataset));

  async ngOnInit() {
    this.meta.set(await this.api.get('/report-builder'));
    if (!this.ds()) this.spec.dataset = this.meta().datasets[0]?.key;
    this.saved.set(await this.api.get('/saved-reports'));
    this.users.set((await this.api.get('/users').catch(() => [])).filter((u: any) => u.kind === 'staff' && u.active !== false));
  }

  money() {
    return ['invoices', 'payments', 'costs', 'projects'].includes(this.spec.dataset);
  }

  reset() {
    this.spec = { ...this.spec, group_by: [], measures: ['count'], filters: {} };
    this.fDim = null;
    this.res.set(null);
  }

  filterList() {
    const d = this.ds();
    return Object.entries(this.spec.filters).filter(([, v]: any) => v?.length).map(([k, v]: any) => ({ k, v, label: d?.dims.find((x: any) => x.key === k)?.label ?? k }));
  }

  clearFilter(k: string) {
    delete this.spec.filters[k];
  }

  async loadValues() {
    if (!this.fDim) return;
    this.values.set(await this.api.get(`/report-builder/values?dataset=${this.spec.dataset}&dim=${this.fDim}`));
  }

  body() {
    const range: any = {};
    if (this.period.startsWith('last_')) range.last_days = +this.period.slice(5);
    if (this.period === 'custom') Object.assign(range, { from: this.spec.range.from, to: this.spec.range.to });
    return { ...this.spec, measures: this.spec.measures.length ? this.spec.measures : ['count'], range };
  }

  async run() {
    this.res.set(await this.api.post('/report-builder/run', this.body()));
  }

  async csv() {
    const text = await firstValueFrom(this.http.post('/api/report-builder/csv', this.body(), { responseType: 'text' }));
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
    a.download = `${this.spec.dataset}-report.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async save() {
    await this.api.post('/saved-reports', { name: this.sv.name, shared: this.sv.shared, spec: this.body(),
      schedule: this.sv.every ? { every: this.sv.every, to: this.sv.to } : null }, 'Report saved');
    this.saveDlg = false;
    this.saved.set(await this.api.get('/saved-reports'));
  }

  async openSaved() {
    const r = this.saved().find((x) => x.id === this.openId);
    if (!r) return;
    if (!r.can_run) return alert('Your role cannot see this report\'s data.');
    this.spec = { ...r.spec, filters: { ...r.spec.filters }, range: { ...r.spec.range } };
    this.period = r.spec.range?.last_days ? `last_${r.spec.range.last_days}` : r.spec.range?.from ? 'custom' : 'all';
    if (!this.periods.some((p) => p.value === this.period)) this.periods = [...this.periods, { label: `Last ${r.spec.range.last_days} days`, value: this.period }];
    await this.run();
  }
}

/** Phase L block 6 — my dashboards (and the company's shared ones): widgets from saved or inline reports. */
@Component({
  selector: 'app-dashboards',
  imports: [FormsModule, ButtonModule, DialogModule, InputTextModule, SelectModule, ReportChartComponent],
  template: `
    <div class="page-head"><h2>Dashboards</h2>
      <span class="row gap">
        <p-select [options]="list()" [(ngModel)]="curId" optionLabel="name" optionValue="id" placeholder="Choose" (onChange)="load()" ariaLabel="Dashboard" />
        <p-button label="New" icon="pi pi-plus" size="small" [outlined]="true" (onClick)="create()" />
        @if (cur()?.dashboard?.mine || (cur()?.dashboard?.shared && isOwner)) { <p-button label="Add widget" icon="pi pi-plus" size="small" (onClick)="wDlg = true" /> }
      </span></div>
    @if (cur(); as c) {
      <div class="board">
        @for (w of c.widgets; track w.id) {
          <div class="widget" [style.grid-column]="'span ' + w.width">
            <div class="row-between"><strong>{{ w.title }}</strong>
              @if (c.dashboard.mine) { <a href="" class="small" (click)="$event.preventDefault(); remove(w.id)">remove</a> }</div>
            @if (w.error) { <p class="small muted">{{ w.error }}</p> } @else { <app-report-chart [result]="w.result" [chart]="w.chart" /> }
          </div>
        } @empty { <p class="muted">No widgets yet — add a saved report or a quick one.</p> }
      </div>
    } @else { <p class="muted">Make a dashboard of the numbers you check every day.</p> }
    <p-dialog header="Add a widget" [modal]="true" [(visible)]="wDlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <input pInputText [(ngModel)]="w.title" placeholder="Title (optional)" aria-label="Title" />
        <p-select [options]="reports()" [(ngModel)]="w.report_id" optionLabel="name" optionValue="id" placeholder="A saved report" [showClear]="true" ariaLabel="Saved report" />
        <span class="small muted">or a quick one:</span>
        <p-select [options]="quick" [(ngModel)]="w.quick" optionLabel="label" placeholder="Quick report" [showClear]="true" ariaLabel="Quick report" />
        <div class="row gap"><select class="p-inputtext" [(ngModel)]="w.chart" aria-label="Chart"><option value="kpi">Number</option><option value="bar">Bar</option><option value="line">Line</option><option value="pie">Pie</option><option value="table">Table</option></select>
          <select class="p-inputtext" [(ngModel)]="w.width" aria-label="Width"><option [ngValue]="1">narrow</option><option [ngValue]="2">wide</option><option [ngValue]="3">full</option></select></div>
        <div class="row right"><p-button label="Add" [disabled]="!w.report_id && !w.quick" (onClick)="addWidget()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.board { display: grid; grid-template-columns: repeat(3, 1fr); gap: .8rem; } @media (max-width: 800px) { .board { grid-template-columns: 1fr; } .widget { grid-column: auto !important; } }
    .widget { border: 1px solid var(--border); border-radius: 10px; padding: .8rem; display: grid; gap: .4rem; align-content: start; }`,
})
export class DashboardsComponent {
  private api = inject(Api);
  private auth = inject(AuthService);
  isOwner = this.auth.user()?.role === 'owner';
  list = signal<any[]>([]);
  reports = signal<any[]>([]);
  cur = signal<any>(null);
  curId: string | null = null;
  wDlg = false;
  w: any = { chart: 'kpi', width: 1 };
  quick = [
    { label: 'Open leads', spec: { dataset: 'leads', measures: ['count'], filters: { status: ['open'] } }, chart: 'kpi' },
    { label: 'Leads by stage', spec: { dataset: 'leads', group_by: ['stage'], measures: ['count'], filters: { status: ['open'] } }, chart: 'bar' },
    { label: 'New leads per month', spec: { dataset: 'leads', group_by: ['month'], measures: ['count'], range: { last_days: 365 } }, chart: 'line' },
    { label: 'Invoices outstanding', spec: { dataset: 'invoices', measures: ['due'] }, chart: 'kpi' },
    { label: 'Invoiced per month', spec: { dataset: 'invoices', group_by: ['month'], measures: ['total'], range: { last_days: 365 } }, chart: 'line' },
    { label: 'Costs by head', spec: { dataset: 'costs', group_by: ['category'], measures: ['amount'], range: { last_days: 90 } }, chart: 'pie' },
    { label: 'Projects by status', spec: { dataset: 'projects', group_by: ['status'], measures: ['count'] }, chart: 'pie' },
    { label: 'Safety incidents by kind', spec: { dataset: 'incidents', group_by: ['kind'], measures: ['count'], range: { last_days: 365 } }, chart: 'bar' },
    { label: 'Overdue follow-ups', spec: { dataset: 'followups', group_by: ['owner'], measures: ['overdue'] }, chart: 'bar' },
  ];

  async ngOnInit() {
    await this.refresh();
    this.curId = this.list()[0]?.id ?? null;
    await this.load();
  }

  async refresh() {
    this.list.set(await this.api.get('/dashboards'));
    this.reports.set((await this.api.get('/saved-reports')).filter((r: any) => r.can_run));
  }

  async load() {
    this.cur.set(this.curId ? await this.api.get(`/dashboards/${this.curId}/data`) : null);
  }

  async create() {
    const name = prompt('Dashboard name', 'My dashboard');
    if (!name) return;
    const d = await this.api.post('/dashboards', { name, widgets: [] });
    await this.refresh();
    this.curId = d.id;
    await this.load();
  }

  widgetsNow() {
    return this.cur().dashboard.widgets.map((x: any) => ({ id: x.id, title: x.title, chart: x.chart, width: x.width, report_id: x.report_id, spec: x.spec }));
  }

  async addWidget() {
    const nw: any = { title: this.w.title || this.w.quick?.label || null, chart: this.w.chart, width: this.w.width };
    if (this.w.report_id) nw.report_id = this.w.report_id;
    else nw.spec = this.w.quick.spec;
    await this.api.put(`/dashboards/${this.curId}`, { widgets: [...this.widgetsNow(), nw] });
    this.wDlg = false;
    this.w = { chart: 'kpi', width: 1 };
    await this.load();
  }

  async remove(id: string) {
    await this.api.put(`/dashboards/${this.curId}`, { widgets: this.widgetsNow().filter((x: any) => x.id !== id) });
    await this.load();
  }
}

/** Phase L block 2 — the company's safety report. */
@Component({
  selector: 'app-safety-report',
  imports: [DecimalPipe],
  template: `
    <div class="page-head"><h2>Safety</h2><span class="small muted">last 12 months · incidents are reported in each project's Safety tab or the field app</span></div>
    @if (r(); as r) {
      <div class="tiles">
        <div class="tile"><div class="n">{{ r.incidents }}</div><div class="small">incidents</div></div>
        <div class="tile"><div class="n c-bad">{{ r.serious }}</div><div class="small">serious</div></div>
        <div class="tile"><div class="n">{{ r.lost_days }}</div><div class="small">days lost</div></div>
        <div class="tile"><div class="n">{{ r.overdue_actions.length }}</div><div class="small">actions overdue</div></div>
        <div class="tile"><div class="n">{{ r.avg_score === null ? '—' : (r.avg_score | number: '1.0-1') + '%' }}</div><div class="small">inspection score ({{ r.inspections }})</div></div>
        <div class="tile"><div class="n">{{ r.talks }}</div><div class="small">toolbox talks</div></div>
      </div>
      <div class="cols">
        <div><h4>Days without a lost-time injury</h4>@for (x of r.days_without_lti; track x.project_id) { <div class="small">{{ x.project }} — <strong>{{ x.days }}</strong> days <span class="muted">(since {{ x.since }})</span></div> }</div>
        <div><h4>By kind</h4>@for (x of r.by_kind; track x.kind) { <div class="small">{{ x.label }} — {{ x.count }}</div> } @empty { <p class="small muted">No incidents.</p> }</div>
        <div><h4>Items that fail most</h4>@for (x of r.top_fails; track $index) { <div class="small">{{ x.item }} <span class="muted">({{ x.checklist }})</span> — {{ x.count }}</div> } @empty { <p class="small muted">Nothing failed.</p> }</div>
        <div><h4>Overdue actions</h4>@for (a of r.overdue_actions; track a.id) { <div class="small c-bad">{{ a.incident }} · {{ a.project_name }}: {{ a.text }} — {{ a.owner_name }}, due {{ a.due }}</div> } @empty { <p class="small muted">None.</p> }</div>
      </div>
    }
  `,
  styles: `.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr)); gap: .6rem; margin-bottom: 1rem; }
    .tile { border: 1px solid var(--border); border-radius: 10px; padding: .7rem; } .n { font-size: 1.6rem; font-weight: 700; }
    .cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 1rem; }`,
})
export class SafetyReportComponent {
  private api = inject(Api);
  r = signal<any>(null);

  async ngOnInit() {
    this.r.set(await this.api.get('/reports/safety'));
  }
}
