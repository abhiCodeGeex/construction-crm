import { Component, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { DragDropModule } from 'primeng/dragdrop';
import { IconFieldModule } from 'primeng/iconfield';
import { InputIconModule } from 'primeng/inputicon';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { HttpErrorResponse } from '@angular/common/http';
import { Api, SERVICE_COLOR, SERVICE_LABEL, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { WinLoseComponent } from './win-lose.component';

@Component({
  selector: 'app-leads',
  imports: [FormsModule, DatePipe, ButtonModule, CardModule, CheckboxModule, DialogModule, DragDropModule, IconFieldModule, InputIconModule, InputNumberModule,
    InputTextModule, MessageModule, SelectButtonModule, SelectModule, TableModule, TabsModule, TagModule, TextareaModule, WinLoseComponent],
  template: `
    <div class="page-head">
      <div><h1>Leads & pipeline</h1><p class="muted">Every enquiry is captured once and tracked until it becomes a won project or a recorded loss.</p></div>
      @if (canEdit()) { <p-button label="New lead" icon="pi pi-plus" (onClick)="openNew()" /> }
    </div>

    <p-tabs [(value)]="tab" [scrollable]="true">
      <p-tablist>
        <p-tab value="board"><i class="pi pi-th-large mr"></i>Pipeline</p-tab>
        <p-tab value="list"><i class="pi pi-list mr"></i>All leads</p-tab>
        <p-tab value="bids" (click)="loadBids()"><i class="pi pi-briefcase mr"></i>Bid / tender register</p-tab>
      </p-tablist>
      <p-tabpanels>
        <!-- ============ BOARD ============ -->
        <p-tabpanel value="board">
          <div class="filters">
            <p-selectbutton [allowEmpty]="false" [options]="serviceOptions()" [(ngModel)]="service" optionLabel="label" optionValue="value" (onChange)="load()" />
            <p-select [options]="ownerOptions()" [(ngModel)]="owner" optionLabel="name" optionValue="id" placeholder="All salespeople" [showClear]="true" (onChange)="load()" />
            <p-select [options]="meta()?.sources ?? []" [(ngModel)]="source" placeholder="All sources" [showClear]="true" (onChange)="load()" />
            <p-iconfield><p-inputicon class="pi pi-search" /><input pInputText placeholder="Search" [(ngModel)]="q" (keyup.enter)="load()" /></p-iconfield>
          </div>
          <div class="board">
            @for (col of columns(); track col.stage) {
              <div class="col" pDroppable="lead" (onDrop)="drop(col.stage)" [class.end]="col.end">
                <div class="col-head"><strong>{{ col.stage }}</strong>
                  <span class="muted small">{{ col.items.length }} · {{ fmt(col.value) }}</span></div>
                @for (l of col.items; track l.id) {
                  <div class="lead-card" pDraggable="lead" [pDraggableDisabled]="!canEdit()" (onDragStart)="dragging = l" (onDragEnd)="dragging = null" (click)="open(l)">
                    <strong>{{ l.title }}</strong>
                    <small class="muted">{{ l.contact_name }}{{ l.location ? ' · ' + l.location : '' }}</small>
                    <div class="row-between small mt-xs">
                      <span>{{ fmt(l.budget) }}</span>
                      <p-tag [value]="l.source" severity="secondary" />
                    </div>
                    <div class="row-between small mt-xs">
                      <span class="muted"><i class="pi pi-user"></i> {{ l.owner_name || 'Unassigned' }}</span>
                      @if (l.next_followup; as nf) {
                        <span [class.c-bad]="nf.overdue"><i class="pi pi-bell"></i> {{ nf.due | date: 'd MMM' }}</span>
                      } @else { <span class="c-warn" title="No follow-up scheduled"><i class="pi pi-bell-slash"></i> none</span> }
                    </div>
                  </div>
                } @empty { <div class="muted small empty-col">No leads</div> }
              </div>
            }
            @if (canEdit()) {
              <div class="col end won" pDroppable="lead" (onDrop)="dropEnd('won')"><div class="col-head"><strong><i class="pi pi-trophy"></i> Won</strong></div>
                <div class="muted small empty-col">Drop here to convert to a project</div></div>
              <div class="col end lost" pDroppable="lead" (onDrop)="dropEnd('lost')"><div class="col-head"><strong><i class="pi pi-times-circle"></i> Lost</strong></div>
                <div class="muted small empty-col">Drop here to record a loss</div></div>
            }
          </div>
        </p-tabpanel>

        <!-- ============ LIST ============ -->
        <p-tabpanel value="list">
          <div class="filters">
            <p-selectbutton [allowEmpty]="false" [options]="statusOptions" [(ngModel)]="status" optionLabel="label" optionValue="value" (onChange)="loadAll()" />
          </div>
          <p-table [value]="all()" size="small" [rowHover]="true" selectionMode="single" (onRowSelect)="open($event.data)" [paginator]="all().length > 20" [rows]="20">
            <ng-template #header><tr><th>Lead</th><th>Service</th><th>Stage</th><th>Source</th><th>Salesperson</th><th class="right">Budget</th><th>Created</th></tr></ng-template>
            <ng-template #body let-l>
              <tr [pSelectableRow]="l" class="clickable">
                <td><strong>{{ l.title }}</strong><br /><small class="muted">{{ l.contact_name }}</small></td>
                <td><span class="svc" [style.--c]="color[l.service]">{{ svc[l.service] }}</span></td>
                <td>@if (l.status === 'open') { {{ l.stage }} } @else { <p-tag [value]="l.status" [severity]="l.status === 'won' ? 'success' : 'danger'" /> }</td>
                <td>{{ l.source }}</td><td>{{ l.owner_name || '—' }}</td><td class="right">{{ fmt(l.budget) }}</td><td><small>{{ l.created_at | date }}</small></td>
              </tr>
            </ng-template>
            <ng-template #emptymessage><tr><td colspan="7" class="center muted">No leads</td></tr></ng-template>
          </p-table>
        </p-tabpanel>

        <!-- ============ BIDS ============ -->
        <p-tabpanel value="bids">
          <div class="row-between mb">
            <div class="row gap">
              <div class="stat-card slim"><div><small>Hit rate</small><strong>{{ bids()?.hit_rate ?? '—' }}{{ bids()?.hit_rate != null ? '%' : '' }}</strong>
                <small class="muted">{{ bids()?.won ?? 0 }} won of {{ bids()?.decided ?? 0 }} decided</small></div></div>
            </div>
            @if (canEdit()) { <p-button label="New bid" icon="pi pi-plus" size="small" (onClick)="openBid()" /> }
          </div>
          <p-table [value]="bids()?.bids ?? []" size="small" [rowHover]="true">
            <ng-template #header><tr><th>Bid / tender</th><th>Due</th><th>Decision</th><th>Status</th><th class="right">Value</th><th></th></tr></ng-template>
            <ng-template #body let-b>
              <tr>
                <td><strong>{{ b.title }}</strong><br /><small class="muted">{{ b.reference || '' }} {{ b.client_name || '' }}</small>
                  @if (b.lead_id) { <br /><a class="small" href="" (click)="$event.preventDefault(); open({ id: b.lead_id })"><i class="pi pi-bullseye"></i> {{ b.lead_title }}</a> }</td>
                <td [class.c-bad]="b.overdue">{{ b.due_date | date: 'mediumDate' }} @if (b.overdue) { <p-tag value="Overdue" severity="danger" /> }</td>
                <td>@switch (b.decision) { @case ('bid') { <p-tag value="Bid" severity="info" /> } @case ('no_bid') { <p-tag value="No bid" severity="secondary" /> } @default { <p-tag value="Pending" severity="warn" /> } }</td>
                <td>@if (b.decision === 'no_bid') { <span class="muted small">Not bidding — {{ b.decision_reason }}</span> }
                  @else if (b.decision === 'pending') { <span class="muted small">Awaiting decision</span> }
                  @else { <p-tag [value]="label(b.status)" [severity]="b.status === 'won' ? 'success' : b.status === 'lost' ? 'danger' : b.status === 'submitted' ? 'info' : 'secondary'" />
                    @if (b.status === 'won' && b.project_id) { <a class="small ml" href="" (click)="$event.preventDefault(); router.navigate(['/app/projects', b.project_id])">Project {{ b.project_code }} →</a> }
                    @if (b.status === 'lost' && b.loss_reason) { <small class="muted ml">{{ b.loss_reason }}</small> } }</td>
                <td class="right">{{ fmt(b.value) }}</td>
                <td class="right nowrap">@if (canEdit()) {
                  @if (b.status === 'submitted') {
                    <p-button label="Won" icon="pi pi-trophy" severity="success" size="small" [text]="true" (onClick)="wl().open('won', b, meta(), true)" />
                    <p-button label="Lost" icon="pi pi-times" severity="danger" size="small" [text]="true" (onClick)="wl().open('lost', b, meta(), true)" /> }
                  @if (b.status !== 'won' && b.status !== 'lost') { <p-button icon="pi pi-pencil" [text]="true" [rounded]="true" (onClick)="openBid(b)" /> }
                  @else if (!(b.status === 'won' && b.project_id)) { <p-button icon="pi pi-trash" [text]="true" [rounded]="true" severity="danger" (onClick)="bf = b; deleteBid()" /> } }</td>
              </tr>
            </ng-template>
            <ng-template #emptymessage><tr><td colspan="6" class="center muted">No bids yet</td></tr></ng-template>
          </p-table>
        </p-tabpanel>
      </p-tabpanels>
    </p-tabs>

    <!-- new lead -->
    <p-dialog header="New lead" [modal]="true" [(visible)]="leadDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '96vw' }">
      <form class="stack" (ngSubmit)="create()">
        <label class="field"><span>Lead title</span><input pInputText name="t" [(ngModel)]="f.title" placeholder="e.g. Sharma duplex – new build" fluid /></label>
        <div class="field"><span>Enquirer</span>
          <p-selectbutton [allowEmpty]="false" name="ck" [options]="contactModes" [(ngModel)]="contactMode" optionLabel="label" optionValue="value" /></div>
        @if (contactMode === 'new') {
          <div class="grid3">
            <input pInputText name="cn" [(ngModel)]="f.contact_name" placeholder="Name" fluid />
            <input pInputText name="cp" [(ngModel)]="f.contact_phone" placeholder="Phone" fluid />
            <input pInputText name="ce" [(ngModel)]="f.contact_email" placeholder="Email" fluid />
          </div>
          <label class="check"><p-checkbox name="cc" [(ngModel)]="f.contact_is_company" [binary]="true" /> The enquirer is a company (not a person)</label>
        } @else {
          <p-select name="cid" [options]="contacts()" [(ngModel)]="f.contact_id" optionLabel="name" optionValue="id" [filter]="true" placeholder="Choose contact" fluid appendTo="body" />
        }
        <div class="grid3">
          <label class="field"><span>Service</span><p-select name="s" [options]="serviceOptions()" [(ngModel)]="f.service" optionLabel="label" optionValue="value" fluid appendTo="body" /></label>
          <label class="field"><span>Source</span><p-select name="src" [options]="meta()?.sources ?? []" [(ngModel)]="f.source" fluid appendTo="body" /></label>
          <label class="field"><span>Salesperson</span><p-select name="o" [options]="meta()?.staff ?? []" [(ngModel)]="f.owner_id" optionLabel="name" optionValue="id" fluid appendTo="body" /></label>
        </div>
        @if (f.source === 'Referral') {
          <label class="field"><span>Referred by</span><p-select name="rb" [options]="contacts()" [(ngModel)]="f.referred_by" optionLabel="name" optionValue="id" [filter]="true" fluid appendTo="body" /></label>
        }
        @if (f.source === 'Houzz/portals' || f.source === 'Ads') {
          <label class="field"><span>{{ f.source === 'Ads' ? 'Campaign' : 'Portal' }}</span><input pInputText name="sd" [(ngModel)]="f.source_detail" fluid /></label>
        }
        <div class="grid3">
          <label class="field"><span>Project type</span><p-select name="pt" [options]="meta()?.project_types ?? []" [(ngModel)]="f.project_type" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Timeline</span><p-select name="tl" [options]="meta()?.timelines ?? []" [(ngModel)]="f.timeline" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Budget</span><p-inputnumber name="b" [(ngModel)]="f.budget" [min]="0" fluid /></label>
        </div>
        <div class="grid3">
          <label class="field"><span>Location</span><input pInputText name="loc" [(ngModel)]="f.location" fluid /></label>
          <label class="field"><span>Area</span><p-inputnumber name="a" [(ngModel)]="f.area" [min]="0" fluid /></label>
          <div class="field"><span>Unit</span><p-selectbutton [allowEmpty]="false" name="u" [options]="units" [(ngModel)]="f.area_unit" optionLabel="label" optionValue="value" /></div>
        </div>
        <label class="field"><span>Notes</span><textarea pTextarea name="n" rows="2" [(ngModel)]="f.notes" fluid></textarea></label>
        @if (duplicate(); as dup) {
          <p-message severity="warn" icon="pi pi-copy">
            <span>An open lead already exists for this enquirer: <a href="" (click)="$event.preventDefault(); leadDlg = false; router.navigate(['/app/leads', dup.id])">{{ dup.title }}</a>.
              Save anyway only if this is a separate job.</span>
          </p-message>
        }
        <div class="row gap right">
          @if (duplicate()) { <p-button label="Save anyway" severity="warn" [outlined]="true" (onClick)="create(true)" /> }
          <p-button type="submit" label="Create lead" icon="pi pi-check" [loading]="busy()" />
        </div>
      </form>
    </p-dialog>

    <!-- bid -->
    <p-dialog [header]="bf.id ? 'Edit bid' : 'New bid'" [modal]="true" [(visible)]="bidDlg" [style]="{ width: '36rem' }">
      <form class="stack" (ngSubmit)="saveBid()">
        <label class="field"><span>Bid / tender</span><input pInputText name="t" [(ngModel)]="bf.title" fluid /></label>
        <div class="grid3">
          <label class="field"><span>Reference</span><input pInputText name="r" [(ngModel)]="bf.reference" fluid /></label>
          <label class="field"><span>Due date</span><input pInputText type="date" name="d" [(ngModel)]="bf.due_date" fluid /></label>
          <label class="field"><span>Value</span><p-inputnumber name="v" [(ngModel)]="bf.value" [min]="0" fluid /></label>
        </div>
        <div class="grid2">
          <label class="field"><span>Client</span><p-select name="c" [options]="contacts()" [(ngModel)]="bf.client_id" optionLabel="name" optionValue="id" [filter]="true" [showClear]="true" [disabled]="!!bf.lead_id" [placeholder]="bf.lead_id ? 'From the lead' : ''" fluid appendTo="body" /></label>
          <label class="field"><span>Service</span><p-select name="s" [options]="serviceOptions()" [(ngModel)]="bf.service" optionLabel="label" optionValue="value" [showClear]="true" [disabled]="!!bf.lead_id" fluid appendTo="body" /></label>
        </div>
        <label class="field"><span>Linked lead <small class="muted">(optional — the bid takes its client and service, and the lead is won or lost with the bid)</small></span>
          <p-select name="ld" [options]="leadOptions()" [(ngModel)]="bf.lead_id" (onChange)="onLead()" optionLabel="title" optionValue="id" [filter]="true" [showClear]="true" placeholder="No lead" fluid appendTo="body" /></label>
        <div class="field"><span>Bid / no-bid decision</span><p-selectbutton [allowEmpty]="false" name="dc" [options]="decisions" [(ngModel)]="bf.decision" optionLabel="label" optionValue="value" [disabled]="bf.status === 'submitted'" /></div>
        @if (bf.decision === 'no_bid') { <label class="field"><span>Why not bid?</span><input pInputText name="dr" [(ngModel)]="bf.decision_reason" fluid /></label> }
        @if (bf.decision === 'bid') { <div class="field"><span>Status</span><p-selectbutton [allowEmpty]="false" name="st" [options]="bidStatuses" [(ngModel)]="bf.status" optionLabel="label" optionValue="value" />
          <small class="muted">Once submitted, record the result with <strong>Won</strong> or <strong>Lost</strong> in the register.</small></div> }
        <label class="field"><span>Notes</span><textarea pTextarea name="nt" rows="2" [(ngModel)]="bf.notes" fluid></textarea></label>
        <div class="row gap right">
          @if (bf.id) { <p-button label="Delete" severity="danger" [text]="true" (onClick)="deleteBid()" /> }
          <p-button type="submit" label="Save" icon="pi pi-check" />
        </div>
      </form>
    </p-dialog>

    <app-win-lose (done)="load(); tab === 'bids' && loadBids()" />
  `,
})
export class LeadsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  router = inject(Router);
  meta = signal<any>(null);
  board = signal<any[]>([]);
  all = signal<any[]>([]);
  bids = signal<any>(null);
  contacts = signal<any[]>([]);
  duplicate = signal<{ id: string; title: string } | null>(null);
  busy = signal(false);
  canEdit = computed(() => this.auth.can('leads', 'rw'));
  serviceOptions = computed(() => (this.meta()?.services ?? []).map((s: string) => ({ value: s, label: SERVICE_LABEL[s] })));
  ownerOptions = computed(() => [{ id: 'none', name: 'Unassigned' }, ...(this.meta()?.staff ?? [])]);
  columns = computed(() => {
    const stages: string[] = this.meta()?.pipelines?.[this.service] ?? [];
    return stages.map((stage) => {
      const items = this.board().filter((l) => l.stage === stage);
      return { stage, items, value: items.reduce((a, l) => a + (l.budget || 0), 0), end: false };
    });
  });
  tab = 'board';
  service = '';
  owner: string | null = null;
  source: string | null = null;
  status = 'open';
  q = '';
  dragging: any = null;
  leadDlg = false;
  bidDlg = false;
  contactMode = 'new';
  f: any = {};
  bf: any = {};
  svc = SERVICE_LABEL;
  color = SERVICE_COLOR;
  units = [{ label: 'sq ft', value: 'sqft' }, { label: 'm²', value: 'sqm' }];
  contactModes = [{ label: 'New enquirer', value: 'new' }, { label: 'Existing contact', value: 'existing' }];
  statusOptions = [{ label: 'Open', value: 'open' }, { label: 'Won', value: 'won' }, { label: 'Lost', value: 'lost' }, { label: 'All', value: '' }];
  decisions = [{ label: 'Pending', value: 'pending' }, { label: 'Bid', value: 'bid' }, { label: 'No bid', value: 'no_bid' }];
  bidStatuses = [{ label: 'Preparing', value: 'preparing' }, { label: 'Submitted', value: 'submitted' }];
  label = label;
  leadOptions = signal<any[]>([]);
  wl = viewChild.required(WinLoseComponent);

  async ngOnInit() {
    const m = await this.api.get('/leads/meta');
    this.meta.set(m);
    this.service = m.services[0];
    await this.load();
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  async load() {
    const p = new URLSearchParams({ service: this.service, status: 'open' });
    if (this.owner) p.set('owner_id', this.owner);
    if (this.source) p.set('source', this.source);
    if (this.q) p.set('q', this.q);
    this.board.set(await this.api.get(`/leads?${p}`));
    await this.loadAll();
  }

  async loadAll() {
    this.all.set(await this.api.get(`/leads${this.status ? '?status=' + this.status : ''}`));
  }

  async loadBids() {
    this.bids.set(await this.api.get('/bids'));
    if (!this.contacts().length && this.auth.can('contacts')) this.contacts.set(await this.api.get('/contacts'));
  }

  open(l: any) {
    this.router.navigate(['/app/leads', l.id]);
  }

  async drop(stage: string) {
    const l = this.dragging;
    if (!l || l.stage === stage) return;
    l.stage = stage; // optimistic; reload reverts if refused
    try {
      await this.api.post(`/leads/${l.id}/stage`, { stage }, `Moved to ${stage}`);
    } finally {
      await this.load();
    }
  }

  dropEnd(kind: 'won' | 'lost') {
    if (this.dragging) this.winLose(kind, this.dragging);
  }

  winLose(kind: 'won' | 'lost', lead: any) {
    this.wl().open(kind, lead, this.meta());
  }

  async openNew() {
    if (this.auth.can('contacts') && !this.contacts().length) this.contacts.set(await this.api.get('/contacts'));
    this.duplicate.set(null);
    this.contactMode = 'new';
    this.f = { title: '', service: this.service, source: 'Walk-in', owner_id: this.auth.user()?.id, area_unit: 'sqft', budget: null, area: null,
      contact_name: '', contact_phone: '', contact_email: '', contact_id: null };
    this.leadDlg = true;
  }

  async create(force = false) {
    const body = { ...this.f, force };
    if (this.contactMode === 'new') delete body.contact_id;
    else ['contact_name', 'contact_phone', 'contact_email'].forEach((k) => delete body[k]);
    this.busy.set(true);
    try {
      const lead = await this.api.post('/leads', body, 'Lead created');
      this.leadDlg = false;
      this.router.navigate(['/app/leads', lead.id]);
    } catch (e) {
      const msg = (e as HttpErrorResponse).error?.error as string;
      if ((e as HttpErrorResponse).status === 409 && msg?.includes('|')) {
        const [title, id] = msg.split(': ').slice(1).join(': ').split('|');
        this.duplicate.set({ title, id });
      }
    } finally {
      this.busy.set(false);
    }
  }

  async openBid(b?: any) {
    if (!this.contacts().length && this.auth.can('contacts')) this.contacts.set(await this.api.get('/contacts'));
    this.bf = b ? { ...b } : { title: '', reference: '', due_date: new Date().toISOString().slice(0, 10), value: null, client_id: null,
      service: this.service, decision: 'pending', status: 'preparing', decision_reason: '', lead_id: null, notes: '' };
    const open = await this.api.get('/leads?status=open');
    if (this.bf.lead_id && !open.some((l: any) => l.id === this.bf.lead_id)) open.unshift({ id: this.bf.lead_id, title: this.bf.lead_title });
    this.leadOptions.set(open);
    this.bidDlg = true;
  }

  onLead() {
    const l = this.leadOptions().find((x) => x.id === this.bf.lead_id);
    if (l?.service) this.bf.service = l.service;
    this.bf.client_id = null;
  }

  async saveBid() {
    const b = this.bf;
    const body = { title: b.title, reference: b.reference, due_date: b.due_date, value: b.value, client_id: b.client_id, service: b.service,
      lead_id: b.lead_id || null, notes: b.notes, decision: b.decision, decision_reason: b.decision_reason,
      status: b.decision === 'bid' ? b.status : 'preparing' };
    if (b.id) await this.api.put(`/bids/${b.id}`, body, 'Bid saved');
    else await this.api.post('/bids', body, 'Bid added');
    this.bidDlg = false;
    await this.loadBids();
  }

  async deleteBid() {
    await this.api.del(`/bids/${this.bf.id}`, 'Bid deleted');
    this.bidDlg = false;
    await this.loadBids();
  }
}
