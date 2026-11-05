import { Component, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MessageService } from 'primeng/api';
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
      <div class="row gap">
        <p-button label="Export" icon="pi pi-download" [text]="true" (onClick)="exportCsv()" />
        @if (canEdit()) { <p-button label="Import" icon="pi pi-upload" [outlined]="true" (onClick)="openImport()" />
          <p-button label="New lead" icon="pi pi-plus" (onClick)="openNew()" /> }
      </div>
    </div>

    <p-tabs [(value)]="tab" [scrollable]="true">
      <p-tablist>
        <p-tab value="board"><i class="pi pi-th-large mr"></i>Pipeline</p-tab>
        <p-tab value="list"><i class="pi pi-list mr"></i>All leads</p-tab>
        <p-tab value="attention" (click)="loadAttention()"><i class="pi pi-exclamation-triangle mr"></i>Needs attention</p-tab>
        <p-tab value="bids" (click)="loadBids()"><i class="pi pi-briefcase mr"></i>Bid / tender register</p-tab>
      </p-tablist>
      <p-tabpanels>
        <!-- ============ NEEDS ATTENTION ============ -->
        <p-tabpanel value="attention">
          @if (attention(); as a) {
            <p class="muted small">{{ a.scope === 'team' ? 'The whole team' : 'Your leads' }} — everything late or waiting right now.</p>
            <div class="tpl-grid">
              @for (g of attentionGroups; track g.key) {
                <p-card>
                  <ng-template #title><div class="row-between"><span>{{ g.label }}</span><p-tag [value]="'' + (a[g.key]?.length ?? 0)" [severity]="a[g.key]?.length ? 'danger' : 'secondary'" /></div></ng-template>
                  @for (x of a[g.key]; track $index) {
                    <div class="ms-row clickable" (click)="open(x)"><div class="grow"><strong>{{ x.title }}</strong><br /><small class="muted">{{ x.why }}{{ x.owner_name ? ' · ' + x.owner_name : '' }}</small></div></div>
                  } @empty { <p class="muted small">Nothing.</p> }
                </p-card>
              }
            </div>
          }
        </p-tabpanel>
        <!-- ============ BOARD ============ -->
        <p-tabpanel value="board">
          <div class="filters">
            <p-selectbutton [allowEmpty]="false" [options]="serviceOptions()" [(ngModel)]="service" optionLabel="label" optionValue="value" (onChange)="load()" />
            <p-select [options]="ownerOptions()" [(ngModel)]="owner" optionLabel="name" optionValue="id" placeholder="All salespeople" [showClear]="true" (onChange)="load()" />
            <p-select [options]="meta()?.sources ?? []" [(ngModel)]="source" placeholder="All sources" [showClear]="true" (onChange)="load()" />
            <p-select [options]="temps" [(ngModel)]="temperature" optionLabel="label" optionValue="value" placeholder="Any temperature" [showClear]="true" (onChange)="load()" />
            <p-iconfield><p-inputicon class="pi pi-search" /><input pInputText placeholder="Search" [(ngModel)]="q" (keyup.enter)="load()" /></p-iconfield>
            <p-select [options]="views()" [(ngModel)]="view" optionLabel="name" placeholder="Saved views" [showClear]="true" (onChange)="applyView()" />
            <p-button label="Save view" icon="pi pi-bookmark" size="small" [text]="true" (onClick)="saveView()" />
          </div>
          <div class="board">
            @for (col of columns(); track col.stage) {
              <div class="col" pDroppable="lead" (onDrop)="drop(col.stage)" [class.end]="col.end">
                <div class="col-head"><strong>{{ col.stage }}</strong>
                  <span class="muted small">{{ col.items.length }} · {{ fmt(col.value) }}</span></div>
                @for (l of col.items; track l.id) {
                  <div class="lead-card" pDraggable="lead" [pDraggableDisabled]="!canEdit()" (onDragStart)="dragging = l" (onDragEnd)="dragging = null" (click)="open(l)">
                    <strong>@if (l.temperature) { <span class="temp" [class]="l.temperature" [title]="l.temperature"></span> }{{ l.title }}</strong>
                    <small class="muted">{{ l.contact_name }}{{ l.location ? ' · ' + l.location : '' }}</small>
                    <div class="row-between small mt-xs">
                      <span title="Value · probability">{{ fmt(l.value) }} · {{ l.probability_effective }}%</span>
                      <p-tag [value]="l.source" severity="secondary" />
                    </div>
                    <div class="row-between small mt-xs">
                      <span [class.c-bad]="l.over_limit" [title]="l.max_days ? 'Limit ' + l.max_days + ' days' : ''"><i class="pi pi-clock"></i> {{ l.days_in_stage }}d{{ l.over_limit ? ' — stuck' : '' }}</span>
                      <span class="score" title="Lead score">{{ l.score }}</span>
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
          @if (canEdit() && picked.length) {
            <div class="gate row gap wrap">
              <strong>{{ picked.length }} selected</strong>
              <p-select [options]="meta()?.staff ?? []" [(ngModel)]="bk.owner" optionLabel="name" optionValue="id" placeholder="Reassign to" appendTo="body" />
              <p-button label="Reassign" size="small" [outlined]="true" [disabled]="!bk.owner" (onClick)="runBulk('assign', bk.owner)" />
              <p-select [options]="allStages()" [(ngModel)]="bk.stage" placeholder="Move to stage" appendTo="body" />
              <p-button label="Move" size="small" [outlined]="true" [disabled]="!bk.stage" (onClick)="runBulk('stage', bk.stage)" />
              <p-select [options]="temps" [(ngModel)]="bk.temp" optionLabel="label" optionValue="value" placeholder="Temperature" appendTo="body" />
              <p-button label="Set" size="small" [outlined]="true" [disabled]="!bk.temp" (onClick)="runBulk('temperature', bk.temp)" />
              <input pInputText [(ngModel)]="bk.tag" placeholder="Tag" style="width: 8rem" />
              <p-button label="Add tag" size="small" [outlined]="true" [disabled]="!bk.tag?.trim()" (onClick)="runBulk('tag_add', bk.tag)" />
              <p-button label="Remove tag" size="small" [text]="true" [disabled]="!bk.tag?.trim()" (onClick)="runBulk('tag_remove', bk.tag)" />
              <p-button label="Clear" size="small" [text]="true" severity="secondary" (onClick)="picked = []" />
            </div>
          }
          <p-table [value]="all()" size="small" [rowHover]="true" [(selection)]="picked" dataKey="id" [paginator]="all().length > 20" [rows]="20">
            <ng-template #header><tr>@if (canEdit()) { <th style="width: 2.5rem"><p-tableHeaderCheckbox /></th> }<th>Lead</th><th>Service</th><th>Stage</th><th>Source</th><th>Salesperson</th><th class="right">Value</th><th class="right">Score</th><th>Close</th><th>Created</th></tr></ng-template>
            <ng-template #body let-l>
              <tr class="clickable">@if (canEdit()) { <td (click)="$event.stopPropagation()"><p-tableCheckbox [value]="l" /></td> }
                <td (click)="open(l)"><strong>@if (l.temperature) { <span class="temp" [class]="l.temperature"></span> }{{ l.title }}</strong><br /><small class="muted">{{ l.contact_name }}</small></td>
                <td><span class="svc" [style.--c]="color[l.service]">{{ svc[l.service] }}</span></td>
                <td>@if (l.status === 'open') { {{ l.stage }} <small [class.c-bad]="l.over_limit" class="muted">{{ l.days_in_stage }}d</small> }
                  @else { <p-tag [value]="label(l.status)" [severity]="l.status === 'won' ? 'success' : l.status === 'on_hold' ? 'warn' : 'danger'" /> }</td>
                <td>{{ l.source }}</td><td>{{ l.owner_name || '—' }}</td><td class="right">{{ fmt(l.value) }}</td><td class="right"><span class="score">{{ l.score }}</span></td>
                <td><small>{{ l.status === 'on_hold' ? 'resumes ' + (l.resume_on | date: 'd MMM') : (l.expected_close | date: 'd MMM y') }}</small></td><td><small>{{ l.created_at | date }}</small></td>
              </tr>
            </ng-template>
            <ng-template #emptymessage><tr><td colspan="9" class="center muted">No leads</td></tr></ng-template>
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
                <td><strong>{{ b.title }}</strong><br /><small class="muted">{{ b.reference || '' }} {{ b.client_name || '' }}{{ b.owner_name ? ' · ' + b.owner_name : '' }}
                  {{ b.site_walk_date ? ' · site walk ' + (b.site_walk_date | date: 'd MMM') : '' }}{{ b.qa_deadline ? ' · Q&A by ' + (b.qa_deadline | date: 'd MMM') : '' }}
                  {{ b.addenda?.length ? ' · ' + b.addenda.length + ' addend' + (b.addenda.length > 1 ? 'a' : 'um') : '' }}</small>
                  @for (d of b.documents ?? []; track d.key) { <br /><a class="small" href="" (click)="$event.preventDefault(); api.openFile('/api/files/' + d.key)"><i class="pi pi-paperclip"></i> {{ d.name }}</a> }
                  @if (b.lead_id) { <br /><a class="small" href="" (click)="$event.preventDefault(); open({ id: b.lead_id })"><i class="pi pi-bullseye"></i> {{ b.lead_title }}</a> }</td>
                <td [class.c-bad]="b.overdue">{{ b.due_date | date: 'mediumDate' }} @if (b.overdue) { <p-tag value="Overdue" severity="danger" /> }</td>
                <td>@switch (b.decision) { @case ('bid') { <p-tag value="Bid" severity="info" /> } @case ('no_bid') { <p-tag value="No bid" severity="secondary" /> } @default { <p-tag value="Pending" severity="warn" /> } }</td>
                <td>@if (b.decision === 'no_bid') { <span class="muted small">Not bidding — {{ b.decision_reason }}</span> }
                  @else if (b.decision === 'pending') { <span class="muted small">Awaiting decision</span> }
                  @else { <p-tag [value]="label(b.status)" [severity]="b.status === 'won' ? 'success' : b.status === 'lost' ? 'danger' : b.status === 'submitted' ? 'info' : 'secondary'" />
                    @if (b.status === 'won' && b.project_id) { <a class="small ml" href="" (click)="$event.preventDefault(); router.navigate(['/app/projects', b.project_id])">Project {{ b.project_code }} →</a> }
                    @if (b.status === 'won' && !b.project_id) { <small class="c-warn ml">no project yet</small> }
                    @if (b.status === 'lost' && b.loss_reason) { <small class="muted ml">{{ b.loss_reason }}</small> } }</td>
                <td class="right">{{ fmt(b.value) }}</td>
                <td class="right nowrap">@if (canEdit()) {
                  @if (b.status === 'submitted') {
                    <p-button label="Won" icon="pi pi-trophy" severity="success" size="small" [text]="true" (onClick)="wl().open('won', b, meta(), true, contacts())" />
                    <p-button label="Lost" icon="pi pi-times" severity="danger" size="small" [text]="true" (onClick)="wl().open('lost', b, meta(), true)" /> }
                  @if (b.status === 'won' && !b.project_id) {
                    <p-button label="Start project" icon="pi pi-building" severity="success" size="small" [text]="true" (onClick)="wl().open('won', b, meta(), true, contacts())" /> }
                  @if (b.status !== 'won' && b.status !== 'lost') { <p-button icon="pi pi-pencil" [text]="true" [rounded]="true" (onClick)="openBid(b)" />
                    <p-button icon="pi pi-file-plus" [text]="true" [rounded]="true" ariaLabel="Add addendum" (onClick)="adf = { b, note: '' }; addDlg = true" /> }
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
          <label class="field"><span>Salesperson</span><p-select name="o" [options]="ownerChoices()" [(ngModel)]="f.owner_id" optionLabel="name" optionValue="id" fluid appendTo="body" /></label>
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
        <div class="grid3">
          <label class="field"><span>Bid owner</span><p-select name="bo" [options]="meta()?.staff ?? []" [(ngModel)]="bf.owner_id" optionLabel="name" optionValue="id" fluid appendTo="body" /></label>
          <label class="field"><span>Site walk</span><input pInputText type="date" name="sw" [(ngModel)]="bf.site_walk_date" fluid /></label>
          <label class="field"><span>Q&A deadline</span><input pInputText type="date" name="qa" [(ngModel)]="bf.qa_deadline" fluid /></label>
        </div>
        <div class="field"><span>Tender documents</span>
          <div class="row gap wrap">@for (d of bf.documents ?? []; track d.key; let i = $index) { <span class="chip static">{{ d.name }} <a href="" (click)="$event.preventDefault(); bf.documents.splice(i, 1)">×</a></span> }
            <label class="p-button p-button-sm p-button-text"><i class="pi pi-upload mr"></i>Add<input type="file" hidden (change)="addBidDoc($event)" /></label></div></div>
        <label class="field"><span>Notes</span><textarea pTextarea name="nt" rows="2" [(ngModel)]="bf.notes" fluid></textarea></label>
        <div class="row gap right">
          @if (bf.id) { <p-button label="Delete" severity="danger" [text]="true" (onClick)="deleteBid()" /> }
          <p-button type="submit" label="Save" icon="pi pi-check" />
        </div>
      </form>
    </p-dialog>

    <p-dialog header="Tender addendum" [modal]="true" [(visible)]="addDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field"><span>What changed</span><input pInputText [(ngModel)]="adf.note" placeholder="e.g. revised BOQ, new due date" fluid /></label>
        <input type="file" (change)="adf.file = $any($event.target).files?.[0]" />
        <div class="row right"><p-button label="Add addendum" (onClick)="addAddendum()" [disabled]="!adf.note?.trim()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Import leads" [modal]="true" [(visible)]="impDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '96vw' }">
      <div class="stack">
        <p class="muted small">CSV or Excel (.xlsx) with a header row. Columns: name, phone, email, service, source, budget, area, location, project_type, timeline,
          notes, owner_email, temperature (title optional). Rows matching an open lead's phone or email are skipped. Without owner_email the assignment rules decide.</p>
        <div class="row gap"><p-button label="Download template" icon="pi pi-download" [text]="true" (onClick)="api.download('/leads/import/template', 'lead-import-template.csv')" />
          <input type="file" accept=".csv,.xlsx" (change)="impFile = $any($event.target).files?.[0]; impResult.set(null)" /></div>
        @if (impResult(); as r) {
          <p-message [severity]="r.failed ? 'warn' : 'success'" text="{{ r.dry_run ? 'Check' : 'Imported' }}: {{ r.ok }} ok, {{ r.failed }} with problems" />
          <p-table [value]="r.rows" size="small" [scrollable]="true" scrollHeight="40vh">
            <ng-template #body let-x><tr><td>Row {{ x.row }}</td><td>{{ x.title || '' }}</td><td [class.c-bad]="!x.ok">{{ x.ok ? (r.dry_run ? 'ready' : 'created' + (x.owner ? ' → ' + x.owner : '')) : x.error }}</td></tr></ng-template>
          </p-table>
        }
        <div class="row gap right">
          <p-button label="Check file" [outlined]="true" (onClick)="runImport(true)" [disabled]="!impFile" />
          <p-button label="Import" icon="pi pi-upload" (onClick)="runImport(false)" [disabled]="!impFile || !impResult()?.dry_run || !impResult()?.ok" />
        </div>
      </div>
    </p-dialog>

    <app-win-lose (done)="load(); tab === 'bids' && loadBids()" />
  `,
})
export class LeadsComponent implements OnInit {
  auth = inject(AuthService);
  api = inject(Api);
  private toast = inject(MessageService);
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
      return { stage, items, value: items.reduce((a, l) => a + (l.value || 0), 0), end: false };
    });
  });
  tab = 'board';
  service = '';
  owner: string | null = null;
  source: string | null = null;
  temperature: string | null = null;
  temps = [{ label: 'Hot', value: 'hot' }, { label: 'Warm', value: 'warm' }, { label: 'Cold', value: 'cold' }];
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
  statusOptions = [{ label: 'Open', value: 'open' }, { label: 'On hold', value: 'on_hold' }, { label: 'Won', value: 'won' }, { label: 'Lost', value: 'lost' }, { label: 'All', value: '' }];
  decisions = [{ label: 'Pending', value: 'pending' }, { label: 'Bid', value: 'bid' }, { label: 'No bid', value: 'no_bid' }];
  bidStatuses = [{ label: 'Preparing', value: 'preparing' }, { label: 'Submitted', value: 'submitted' }];
  label = label;
  leadOptions = signal<any[]>([]);
  attention = signal<any>(null);
  views = signal<any[]>([]);
  impResult = signal<any>(null);
  ownerChoices = computed(() => [{ id: 'auto', name: 'Auto — assignment rules' }, ...(this.meta()?.staff ?? [])]);
  allStages = computed(() => [...new Set(Object.values(this.meta()?.pipelines ?? {}).flat() as string[])]);
  attentionGroups = [{ key: 'not_contacted', label: 'Not contacted in time' }, { key: 'stuck', label: 'Stuck in a stage' },
    { key: 'overdue_followups', label: 'Overdue follow-ups' }, { key: 'missed_visits', label: 'Missed visits' }, { key: 'late_reports', label: 'Visit reports late' },
    { key: 'proposals', label: 'Proposals expiring / unanswered' }, { key: 'approvals', label: 'Approvals waiting' }, { key: 'hot_idle', label: 'Hot leads idle' },
    { key: 'unassigned', label: 'Unassigned' }];
  view: any = null;
  picked: any[] = [];
  bk: any = {};
  impDlg = false;
  impFile: File | null = null;
  addDlg = false;
  adf: any = {};
  wl = viewChild.required(WinLoseComponent);

  async ngOnInit() {
    const m = await this.api.get('/leads/meta');
    this.meta.set(m);
    this.service = m.services[0];
    this.loadViews();
    await this.load();
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  async load() {
    const p = new URLSearchParams({ service: this.service, status: 'open' });
    if (this.owner) p.set('owner_id', this.owner);
    if (this.source) p.set('source', this.source);
    if (this.temperature) p.set('temperature', this.temperature);
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
      service: this.service, decision: 'pending', status: 'preparing', decision_reason: '', lead_id: null, notes: '',
      owner_id: this.auth.user()?.id, site_walk_date: '', qa_deadline: '', documents: [] };
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
      lead_id: b.lead_id || null, notes: b.notes, decision: b.decision, decision_reason: b.decision_reason, owner_id: b.owner_id,
      site_walk_date: b.site_walk_date || null, qa_deadline: b.qa_deadline || null, documents: (b.documents ?? []).map((d: any) => d.key),
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

  async addBidDoc(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const up = await this.api.upload(file);
    this.bf.documents = [...(this.bf.documents ?? []), { key: up.key, name: up.name }];
  }

  async addAddendum() {
    const body: any = { note: this.adf.note };
    if (this.adf.file) body.file_key = (await this.api.upload(this.adf.file)).key;
    await this.api.post(`/bids/${this.adf.b.id}/addenda`, body, 'Addendum added');
    this.addDlg = false;
    await this.loadBids();
  }

  async loadAttention() {
    this.attention.set(await this.api.get('/leads/attention'));
  }

  async loadViews() {
    this.views.set(await this.api.get('/leads/views'));
  }

  applyView() {
    const f = this.view?.filters ?? {};
    if (f.service) this.service = f.service;
    this.owner = f.owner_id ?? null;
    this.source = f.source ?? null;
    this.temperature = f.temperature ?? null;
    this.q = f.q ?? '';
    this.load();
  }

  async saveView() {
    const name = prompt('Name this view (the current filters are saved)')?.trim();
    if (!name) return;
    const views = [...this.views().filter((v) => v.name !== name),
      { name, filters: { service: this.service, owner_id: this.owner, source: this.source, temperature: this.temperature, q: this.q } }];
    this.views.set(await this.api.put('/leads/views', { views }, 'View saved'));
  }

  async exportCsv() {
    await this.api.download(`/leads/export${this.tab === 'list' && this.status ? '?status=' + this.status : ''}`, 'leads.csv');
  }

  openImport() {
    this.impFile = null;
    this.impResult.set(null);
    this.impDlg = true;
  }

  async runImport(dry: boolean) {
    if (!this.impFile) return;
    this.impResult.set(await this.api.postFile(`/leads/import${dry ? '?dry_run=1' : ''}`, this.impFile));
    if (!dry) await this.load();
  }

  async runBulk(action: string, value: any) {
    const r = await this.api.post('/leads/bulk', { ids: this.picked.map((l) => l.id), action, value });
    const msg = `${r.done.length} updated` + (r.failed.length ? `, ${r.failed.length} not: ${r.failed.map((f: any) => `${f.title} — ${f.error}`).join(' | ')}` : '');
    this.toast.add({ severity: r.failed.length ? 'warn' : 'success', summary: 'Bulk update', detail: msg, life: r.failed.length ? 9000 : 3000 });
    this.picked = [];
    await this.load();
  }
}
