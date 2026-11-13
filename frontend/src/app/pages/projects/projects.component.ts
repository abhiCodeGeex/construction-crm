import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { IconFieldModule } from 'primeng/iconfield';
import { InputIconModule } from 'primeng/inputicon';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { ProgressBarModule } from 'primeng/progressbar';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, SERVICE_COLOR, SERVICE_LABEL, STATUS_SEVERITY, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-projects',
  imports: [FormsModule, DatePipe, ButtonModule, CardModule, DialogModule, IconFieldModule, InputIconModule, InputNumberModule, InputTextModule,
    ProgressBarModule, SelectButtonModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div><h1>Projects</h1>
        <p class="muted">{{ auth.user()?.role === 'owner' ? 'All company projects.' : 'Projects you are on.' }} Everything — people, schedule, issues — hangs off the project.</p></div>
      @if (auth.can('projects', 'rw')) { <p-button label="New project" icon="pi pi-plus" (onClick)="openNew()" /> }
    </div>
    <p-card>
      <div class="filters">
        <p-iconfield><p-inputicon class="pi pi-search" />
          <input pInputText placeholder="Search name, code, client, city" [(ngModel)]="q" (keyup.enter)="load()" /></p-iconfield>
        <p-select [options]="meta()?.statuses ?? []" [(ngModel)]="status" placeholder="Any status" [showClear]="true" (onChange)="load()" />
        <p-select [options]="serviceOptions()" [(ngModel)]="service" optionLabel="label" optionValue="value" placeholder="Any service" [showClear]="true" (onChange)="load()" />
      </div>
      <p-table [value]="rows()" [rowHover]="true" size="small" selectionMode="single" (onRowSelect)="open($event.data)" dataKey="id"
               [paginator]="rows().length > 20" [rows]="20">
        <ng-template #header>
          <tr><th>Project</th><th>Client</th><th>Services</th><th>Status</th><th style="min-width: 10rem">Progress</th><th>Health</th><th>Planned end</th>
            @if (showMoney()) { <th class="right">Value</th> }</tr>
        </ng-template>
        <ng-template #body let-p>
          <tr [pSelectableRow]="p" class="clickable">
            <td><strong>{{ p.name }}</strong><br /><small class="muted">{{ p.code }} · {{ p.site?.city || '—' }}{{ p.branch ? ' · ' + p.branch : '' }}</small></td>
            <td>{{ p.client_name || '—' }}</td>
            <td>@for (s of p.services; track s) { <span class="svc" [style.--c]="color[s]">{{ svc[s] }}</span> }</td>
            <td><p-tag [value]="label(p.status)" [severity]="sev[p.status]" />
              @if (p.late) { <p-tag value="Late" severity="danger" styleClass="ml-xs" /> }</td>
            <td><div class="prog"><p-progressbar [value]="p.progress" [showValue]="false" styleClass="thin grow" /><span>{{ p.progress }}%</span></div></td>
            <td>@if (p.health) { <span class="nowrap" [title]="p.health.late_days ? 'Forecast ' + p.health.late_days + ' working days late' : ''"><i class="health-dot" [class]="p.health.grade"></i>{{ p.health.score }} · {{ p.health.label }}</span> } @else { <span class="muted">—</span> }</td>
            <td>{{ p.planned_end ? (p.planned_end | date: 'd MMM y') : '—' }}</td>
            @if (showMoney()) { <td class="right">{{ fmt(p.value, p.currency) }}</td> }
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="8" class="center muted">No projects yet</td></tr></ng-template>
      </p-table>
    </p-card>

    <p-dialog header="New project" [modal]="true" [(visible)]="dialog" [style]="{ width: '40rem' }" [breakpoints]="{ '700px': '95vw' }">
      <form class="stack" (ngSubmit)="create()">
        <label class="field req"><span>Project name</span><input pInputText name="name" [(ngModel)]="f.name" fluid /></label>
        <div class="field"><span>Services <small class="muted">(pick several for design-and-build)</small></span>
          <p-selectbutton name="svc" [options]="serviceOptions()" [(ngModel)]="f.services" [multiple]="true" optionLabel="label" optionValue="value" /></div>
        <div class="grid2">
          <label class="field"><span>Client</span>
            <p-select name="client" [options]="clients()" [(ngModel)]="f.client_id" optionLabel="name" optionValue="id" [filter]="true" [showClear]="true" placeholder="Choose a contact" fluid appendTo="body" /></label>
          <label class="field"><span>Project type</span><p-select name="type" [options]="meta()?.types ?? []" [(ngModel)]="f.project_type" [showClear]="true" fluid appendTo="body" /></label>
        </div>
        <div class="grid3">
          <label class="field"><span>Start date</span><input pInputText type="date" name="start" [(ngModel)]="f.start" fluid /></label>
          <label class="field"><span>Branch</span><p-select name="branch" [options]="meta()?.branches ?? []" [(ngModel)]="f.branch" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Status</span><p-select name="status" [options]="['planning', 'active']" [(ngModel)]="f.status" fluid appendTo="body" /></label>
        </div>
        <div class="grid3">
          <label class="field"><span>Project value</span><p-inputnumber placeholder="Value" name="value" [(ngModel)]="f.value" mode="decimal" [min]="0" fluid /></label>
          <label class="field"><span>Currency (an overseas client)</span><p-select name="currency" [options]="currencies" [(ngModel)]="f.currency" fluid appendTo="body" /></label>
          <label class="field"><span>Area</span><p-inputnumber name="area" [(ngModel)]="f.area" [min]="0" fluid /></label>
          <label class="field"><span>Unit</span><p-selectbutton [allowEmpty]="false" name="unit" [options]="units" [(ngModel)]="f.area_unit" optionLabel="label" optionValue="value" /></label>
        </div>
        <p class="muted small">Stages, tasks timeline and milestones are created from your company's default template for each service. You are added as Project Manager.</p>
        <div class="row gap right">
          <p-button label="Cancel" severity="secondary" [text]="true" (onClick)="dialog = false" />
          <p-button type="submit" label="Create project" icon="pi pi-check" [loading]="busy()" />
        </div>
      </form>
    </p-dialog>
  `,
})
export class ProjectsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  private router = inject(Router);
  rows = signal<any[]>([]);
  meta = signal<any>(null);
  clients = signal<any[]>([]);
  busy = signal(false);
  serviceOptions = signal<{ label: string; value: string }[]>([]);
  showMoney = () => this.auth.user()?.role !== 'site';
  sev = STATUS_SEVERITY;
  svc = SERVICE_LABEL;
  color = SERVICE_COLOR;
  units = [{ label: 'sq ft', value: 'sqft' }, { label: 'm²', value: 'sqm' }];
  currencies = ['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD', 'AUD'];
  label = label;
  q = '';
  status: string | null = null;
  service: string | null = null;
  dialog = false;
  f: any = {};

  async ngOnInit() {
    const m = await this.api.get('/projects/meta');
    this.meta.set(m);
    this.serviceOptions.set(m.services.map((s: string) => ({ value: s, label: SERVICE_LABEL[s] })));
    await this.load();
  }

  fmt(v: number, cur?: string) {
    return money(v, cur || ((this.auth.company() as any)?.currency ?? 'INR'));
  }

  async load() {
    const p = new URLSearchParams();
    if (this.q) p.set('q', this.q);
    if (this.status) p.set('status', this.status);
    if (this.service) p.set('service', this.service);
    this.rows.set(await this.api.get(`/projects?${p}`));
  }

  async openNew() {
    if (this.auth.can('contacts')) this.clients.set(await this.api.get('/contacts'));
    this.f = { name: '', services: this.meta().services.slice(0, 1), client_id: null, project_type: null,
      start: new Date().toISOString().slice(0, 10), branch: this.meta().branches[0] ?? null, status: 'active', value: null, area: null, area_unit: 'sqft',
      currency: (this.auth.company() as any)?.currency ?? 'INR' };
    this.dialog = true;
  }

  async create() {
    this.busy.set(true);
    try {
      const p = await this.api.post('/projects', this.f, 'Project created');
      this.dialog = false;
      this.router.navigate(['/app/projects', p.id]);
    } finally {
      this.busy.set(false);
    }
  }

  open(p: any) {
    this.router.navigate(['/app/projects', p.id]);
  }
}
