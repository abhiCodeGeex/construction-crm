import { Component, OnInit, computed, inject, input, signal, viewChild } from '@angular/core';
import { CHANNEL_ICON, FollowupDialogComponent } from '../../shared/followup-dialog.component';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ConfirmationService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { KnobModule } from 'primeng/knob';
import { MessageModule } from 'primeng/message';
import { MultiSelectModule } from 'primeng/multiselect';
import { ProgressBarModule } from 'primeng/progressbar';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { SliderModule } from 'primeng/slider';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { TooltipModule } from 'primeng/tooltip';
import { Api, SERVICE_COLOR, SERVICE_LABEL, STATUS_SEVERITY, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { GanttComponent } from '../../shared/gantt.component';
import { MapPickerComponent } from '../../shared/map-picker.component';
import { PRIORITY_SEVERITY, TaskPanelComponent } from './task-panel.component';
import { ProjectMeetingsComponent } from './project-meetings.component';
import { ProjectActivityComponent, ProjectHealthComponent } from './project-insights.component';

const DESIGN = ['architecture', 'interior'];

@Component({
  selector: 'app-project-detail',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, CardModule, DialogModule, InputNumberModule, InputTextModule, KnobModule,
    MessageModule, MultiSelectModule, ProgressBarModule, SelectButtonModule, SelectModule, SliderModule, TableModule, TabsModule,
    TagModule, TextareaModule, TooltipModule, GanttComponent, MapPickerComponent, FollowupDialogComponent, CheckboxModule,
    TaskPanelComponent, ProjectMeetingsComponent, ProjectActivityComponent, ProjectHealthComponent],
  template: `
    @if (p(); as p) {
      <div class="page-head">
        <div>
          <a routerLink="/app/projects" class="small"><i class="pi pi-arrow-left"></i> Projects</a>
          <h1>{{ p.name }}</h1>
          <div class="row gap">
            <span class="muted">{{ p.code }}</span>
            <p-tag [value]="label(p.status)" [severity]="sev[p.status]" />
            @for (s of p.services; track s) { <span class="svc" [style.--c]="color[s]">{{ svc[s] }}</span> }
            @if (p.lead_id && auth.can('leads')) { <a class="small" [routerLink]="['/app/leads', p.lead_id]"><i class="pi pi-bullseye"></i> From lead</a> }
            @else if (p.bid_id && auth.can('leads')) { <a class="small" routerLink="/app/leads"><i class="pi pi-briefcase"></i> From a won bid</a> }
            @if (p.client_name) { <span class="muted"><i class="pi pi-user"></i> {{ p.client_name }}</span> }
            <p-tag [value]="p.my_access === 'edit' ? 'You can edit' : (p.can_edit_design ? 'You can edit design stages' : 'View only')"
                   [severity]="p.my_access === 'edit' ? 'success' : 'secondary'" [icon]="p.my_access === 'edit' ? 'pi pi-pencil' : 'pi pi-eye'" />
          </div>
        </div>
        @if (auth.user()?.role === 'owner') { <p-button label="Delete project" icon="pi pi-trash" severity="danger" [text]="true" (onClick)="removeProject()" /> }
      </div>

      <p-tabs [(value)]="tab" [scrollable]="true">
        <p-tablist>
          <p-tab value="overview"><i class="pi pi-chart-pie mr"></i>Overview</p-tab>
          <p-tab value="schedule"><i class="pi pi-list-check mr"></i>Stages & tasks</p-tab>
          <p-tab value="gantt"><i class="pi pi-chart-bar mr"></i>Timeline</p-tab>
          <p-tab value="team"><i class="pi pi-users mr"></i>Team ({{ p.team.length }})</p-tab>
          <p-tab value="issues"><i class="pi pi-exclamation-circle mr"></i>Issues ({{ dash()?.open_issues ?? 0 }})</p-tab>
          <p-tab value="details"><i class="pi pi-map-marker mr"></i>Details & site</p-tab>
          <p-tab value="meetings"><i class="pi pi-calendar-plus mr"></i>Meetings</p-tab>
          <p-tab value="followups"><i class="pi pi-bell mr"></i>Follow-ups</p-tab>
          <p-tab value="activity"><i class="pi pi-list mr"></i>Activity</p-tab>
          <p-tab value="history"><i class="pi pi-history mr"></i>Audit log</p-tab>
          @if (handover()) { <p-tab value="lead"><i class="pi pi-bullseye mr"></i>From the lead</p-tab> }
          @if (contract()) { <p-tab value="contract"><i class="pi pi-verified mr"></i>Contract</p-tab> }
        </p-tablist>
        <p-tabpanels>
          <!-- ================= OVERVIEW ================= -->
          <p-tabpanel value="overview">
            @if (dash(); as d) {
              <div class="stats">
                <div class="stat-card"><p-knob [ngModel]="d.progress" [readonly]="true" [size]="64" valueTemplate="{value}%" />
                  <div><small>Progress</small><strong>{{ d.progress }}%</strong><small class="muted">weighted by stage duration</small></div></div>
                @if (d.budget) {
                  <div class="stat-card"><span class="stat-icon teal"><i class="pi pi-wallet"></i></span>
                    <div class="grow"><small>Budget vs actual</small><strong>{{ fmt(d.budget.actual) }} / {{ fmt(d.budget.budget) }}</strong>
                      <p-progressbar [value]="d.budget.budget ? (d.budget.actual / d.budget.budget) * 100 : 0" [showValue]="false" styleClass="thin" />
                      <small class="muted">Actual costs are recorded in the Finance phase</small></div></div>
                }
                <div class="stat-card"><span class="stat-icon amber"><i class="pi pi-exclamation-circle"></i></span>
                  <div><small>Open issues</small><strong>{{ d.open_issues }}</strong></div></div>
                <div class="stat-card"><span class="stat-icon indigo"><i class="pi pi-check-square"></i></span>
                  <div><small>Tasks</small><strong>{{ d.tasks.done }} / {{ d.tasks.total }} done</strong>
                    <small class="muted">{{ d.tasks.late }} late · {{ d.tasks.blocked }} blocked · {{ d.tasks.conflicts }} date conflicts</small></div></div>
              </div>
              @if (tab === 'overview') { <app-project-health #health [projectId]="p.id" /> }
              <div class="grid2 top mt">
                <p-card>
                  <ng-template #title>Next milestones</ng-template>
                  @for (m of d.next_milestones; track m.id) {
                    <div class="ms-row"><i class="pi pi-flag" [class.c-bad]="m.late"></i>
                      <div class="grow"><strong>{{ m.name }}</strong><br /><small class="muted">{{ m.stage }}</small></div>
                      <span [class.c-bad]="m.late">{{ m.due | date: 'mediumDate' }}</span>
                      @if (m.late) { <p-tag value="Late" severity="danger" /> }</div>
                  } @empty { <p class="muted">No pending milestones</p> }
                </p-card>
                <p-card>
                  <ng-template #title>Stages</ng-template>
                  @for (s of d.stages; track s.id) {
                    <div class="stage-row"><span class="svc-dot" [style.background]="color[s.service]"></span>
                      <span class="grow">{{ s.name }}</span>
                      <p-progressbar [value]="s.progress" [showValue]="false" styleClass="thin w-8" /><small>{{ s.progress }}%</small></div>
                  }
                </p-card>
              </div>
              @if (d.issues.length) {
                <p-card styleClass="mt"><ng-template #title>Latest open issues</ng-template>
                  @for (i of d.issues; track i.id) { <div class="ms-row"><p-tag [value]="i.severity" [severity]="i.severity === 'high' ? 'danger' : i.severity === 'medium' ? 'warn' : 'secondary'" />
                    <span class="grow">{{ i.title }}</span><small class="muted">{{ i.owner_name || '' }}</small></div> }
                </p-card>
              }
            }
          </p-tabpanel>

          <!-- ================= SCHEDULE ================= -->
          <p-tabpanel value="schedule">
            <div class="row-between mb">
              <span class="muted small">Stage progress = tasks done ÷ tasks. A stage closes through its “complete” milestone once its tasks are done,
                its closing checklist is ticked and (where needed) the client has signed off.
                @if (p.baseline) { <br /><i class="pi pi-bookmark"></i> Baseline set {{ p.baseline.at | date: 'd MMM y' }} by {{ p.baseline.by }}{{ p.baseline.note ? ' (' + p.baseline.note + ')' : '' }} ·
                  <b [class.c-bad]="p.baseline.slip_days > 0">{{ p.baseline.slip_days > 0 ? p.baseline.slip_days + ' working days behind the baseline' : 'on the baseline' }}</b>.
                  Moving a date later now asks why. }
                @else { <br />No baseline yet: once the plan is agreed, set a baseline to track every delay and its reason. }</span>
              <div class="row gap">
                @if (p.my_access === 'edit') { <p-button [label]="p.baseline ? 'New baseline' : 'Set baseline'" icon="pi pi-bookmark" size="small" [outlined]="true" (onClick)="openBaseline()" /> }
                @if (anyStageEdit()) { <p-button label="Add stage" icon="pi pi-plus" size="small" (onClick)="openStage()" /> }
              </div>
            </div>
            @for (s of p.stages; track s.id; let first = $first; let last = $last) {
              <div class="stage-card" [style.--c]="color[s.service]">
                <div class="stage-head">
                  <div class="grow">
                    <strong>{{ s.name }}</strong> <span class="svc small" [style.--c]="color[s.service]">{{ svc[s.service] }}</span>
                    <p-tag [value]="label(s.status)" [severity]="sev[s.status]" styleClass="ml-xs" />
                    <div class="small muted">{{ s.start }} → {{ s.end }}
                      @if (s.budget !== undefined && !hideMoney()) { · Budget {{ fmt(s.budget) }} }</div>
                  </div>
                  <div class="prog w-12"><p-progressbar [value]="s.progress" [showValue]="false" styleClass="thin grow" /><span>{{ s.progress }}%</span></div>
                  @if (canEditStage(s)) {
                    <p-button icon="pi pi-pencil" [text]="true" [rounded]="true" pTooltip="Edit stage" (onClick)="openStage(s)" />
                    @if (p.my_access === 'edit') {
                      <p-button icon="pi pi-arrow-up" [text]="true" [rounded]="true" [disabled]="first" (onClick)="move(s, -1)" />
                      <p-button icon="pi pi-arrow-down" [text]="true" [rounded]="true" [disabled]="last" (onClick)="move(s, 1)" />
                    }
                    <p-button [icon]="s.status === 'on_hold' ? 'pi pi-play' : 'pi pi-pause'" [text]="true" [rounded]="true"
                              [pTooltip]="s.status === 'on_hold' ? 'Resume' : 'Put on hold'" (onClick)="hold(s)" />
                    <p-button icon="pi pi-trash" severity="danger" [text]="true" [rounded]="true" (onClick)="deleteStage(s)" />
                  }
                </div>
                <p-table [value]="s.tasks" size="small" styleClass="tasks">
                  <ng-template #header><tr><th>Task</th><th>Assignee</th><th>Dates</th><th>Depends on</th><th style="width: 10rem">Status</th><th></th></tr></ng-template>
                  <ng-template #body let-t>
                    <tr>
                      <td><a href="" (click)="$event.preventDefault(); panel().open(t.id)" class="task-link">{{ t.title }}</a>
                        @if (t.conflict) { <i class="pi pi-exclamation-triangle c-bad" pTooltip="Its dates break a dependency"></i> }
                        <div class="task-badges">
                          @if (t.priority && t.priority !== 'normal') { <p-tag [value]="t.priority" [severity]="prio[t.priority]" /> }
                          @if (t.checklist?.length) { <small><i class="pi pi-list-check"></i> {{ doneItems(t) }}/{{ t.checklist.length }}</small> }
                          @if (t.comment_count) { <small><i class="pi pi-comment"></i> {{ t.comment_count }}</small> }
                          @if (t.files?.length) { <small><i class="pi pi-paperclip"></i> {{ t.files.length }}</small> }
                          @if (t.baseline?.slip_days > 0) { <small class="c-bad"><i class="pi pi-clock"></i> +{{ t.baseline.slip_days }} d</small> }
                          @if (t.status === 'blocked' && t.waiting_on) { <small class="c-warn"><i class="pi pi-hourglass"></i> {{ partyLabel(t.waiting_on.party) }}</small> }
                        </div></td>
                      <td>{{ t.assignee_name || '—' }} @if (t.assignee_id === auth.user()?.id) { <p-tag value="you" severity="info" /> }</td>
                      <td class="nowrap"><small>{{ t.start }} → {{ t.end }}</small></td>
                      <td><small>{{ depNames(t) }}</small></td>
                      <td>
                        @if (canEditStage(s) || t.assignee_id === auth.user()?.id) {
                          <p-select [options]="taskStatuses" [ngModel]="t.status" (onChange)="$event.value === 'blocked' ? openWaiting(t) : setTaskStatus(t, $event.value)" size="small" appendTo="body" />
                        } @else { <p-tag [value]="label(t.status)" [severity]="sev[t.status]" /> }
                      </td>
                      <td class="right nowrap">@if (canEditStage(s)) {
                        <p-button icon="pi pi-pencil" [text]="true" [rounded]="true" size="small" (onClick)="openTask(s, t)" />
                        <p-button icon="pi pi-trash" [text]="true" [rounded]="true" size="small" severity="danger" (onClick)="deleteTask(t)" /> }</td>
                    </tr>
                  </ng-template>
                  <ng-template #emptymessage><tr><td colspan="6" class="muted small">No tasks. Progress for this stage is set manually.</td></tr></ng-template>
                </p-table>
                <div class="ms-list">
                  @for (m of s.milestones; track m.id) {
                    <span class="ms-chip" [class.done]="m.status === 'achieved'">
                      <i class="pi" [class.pi-flag-fill]="m.status === 'achieved'" [class.pi-flag]="m.status !== 'achieved'"></i>
                      {{ m.name }} · {{ m.due }}
                      @if (canEditStage(s)) {
                        <button class="link" (click)="m.gate && m.status !== 'achieved' ? closeStage(s) : toggleMilestone(m)">{{ m.status === 'achieved' ? (m.gate ? 'reopen stage' : 'undo') : (m.gate ? 'close stage' : 'mark achieved') }}</button>
                        <button class="link" (click)="openMilestone(s, m)">edit</button>
                        <button class="link c-bad" (click)="deleteMilestone(m)">×</button>
                      }
                    </span>
                  }
                  @if (canEditStage(s)) {
                    <p-button label="Task" icon="pi pi-plus" size="small" [text]="true" (onClick)="openTask(s)" />
                    <p-button label="Milestone" icon="pi pi-flag" size="small" [text]="true" (onClick)="openMilestone(s)" />
                  }
                </div>
                <div class="gate" [class.closed]="s.gate?.closed">
                  <div class="row-between">
                    <b><i class="pi" [class.pi-lock]="s.gate?.closed" [class.pi-sign-out]="!s.gate?.closed"></i> {{ s.gate?.closed ? 'Stage closed' : 'Closing this stage' }}</b>
                    @if (s.gate?.milestone_id && !s.gate.closed && canEditStage(s)) {
                      <p-button label="Close stage" icon="pi pi-check-circle" size="small" [severity]="s.gate.missing.length ? 'secondary' : 'success'" (onClick)="closeStage(s)" />
                    }
                  </div>
                  @for (c of s.checklist; track c.id) {
                    <div class="check-row"><p-checkbox [binary]="true" [ngModel]="c.done" (onChange)="tickStage(s, c, $event.checked)" [disabled]="!canEditStage(s) || s.gate?.closed" />
                      <span class="grow" [class.strike]="c.done">{{ c.text }} @if (c.done_by) { <small class="muted">· {{ c.done_by }}</small> }</span>
                      @if (canEditStage(s) && !s.gate?.closed) { <p-button icon="pi pi-times" [text]="true" size="small" severity="secondary" (onClick)="removeStageItem(s, c)" /> }</div>
                  }
                  @if (canEditStage(s) && !s.gate?.closed) {
                    <form class="row gap mt-xs" (ngSubmit)="addStageItem(s)"><input pInputText [name]="'gi' + s.id" [(ngModel)]="stageItem[s.id]" placeholder="Add a closing check" class="grow" />
                      <p-button type="submit" icon="pi pi-plus" size="small" [text]="true" [disabled]="!stageItem[s.id]?.trim()" /></form>
                  }
                  <div class="small mt-xs">
                    @if (s.signoff) {
                      <i class="pi pi-verified c-good"></i> Client sign-off: <b>{{ s.signoff.name }}</b> · {{ s.signoff.method }} · {{ s.signoff.date | date: 'd MMM y' }}{{ s.signoff.note ? ' — ' + s.signoff.note : '' }}
                      <span class="muted">(recorded by {{ s.signoff.recorded_by }})</span>
                      @if (canEditStage(s) && !s.gate?.closed) { <button class="link c-bad" (click)="removeSignoff(s)">remove</button> }
                    } @else if (s.client_signoff_required) {
                      <i class="pi pi-user"></i> Needs the client's sign-off.
                      @if (canEditStage(s) && !s.gate?.closed) { <button class="link" (click)="openSignoff(s)">Record sign-off</button> }
                    } @else { <span class="muted">No client sign-off needed for this stage.</span> }
                    @if (p.my_access === 'edit' && !s.gate?.closed) {
                      <button class="link" (click)="toggleSignoffRule(s)">{{ s.client_signoff_required ? 'not needed' : 'require sign-off' }}</button> }
                  </div>
                  @if (!s.gate?.closed && s.gate?.missing?.length) {
                    <div class="small c-warn mt-xs">Still open: {{ s.gate.missing.join(' · ') }}</div>
                  } @else if (!s.gate?.closed && s.gate?.milestone_id) { <div class="small c-good mt-xs">Ready to close.</div> }
                </div>
              </div>
            }
          </p-tabpanel>

          <!-- ================= GANTT ================= -->
          <p-tabpanel value="gantt">
            <app-gantt [stages]="p.stages" [editableStages]="editableStageIds()" (select)="ganttSelect($event)" (moved)="ganttMoved($event)" />
          </p-tabpanel>

          <!-- ================= TEAM ================= -->
          <p-tabpanel value="team">
            <div class="row-between mb">
              <span class="muted">Internal staff and external parties with their role on this project. Edit access lets a member change this project (within their company role).</span>
              @if (p.my_access === 'edit') { <p-button label="Add member" icon="pi pi-user-plus" size="small" (onClick)="openMember()" /> }
            </div>
            <p-table [value]="p.team" size="small">
              <ng-template #header><tr><th>Name</th><th>Type</th><th>Project role</th><th>Access</th><th></th></tr></ng-template>
              <ng-template #body let-m>
                <tr>
                  <td>@if (m.contact_id && auth.can('contacts')) { <a [routerLink]="['/app/contacts', m.contact_id]">{{ m.name }}</a> } @else { {{ m.name }} }
                    @if (m.user_id === auth.user()?.id) { <small class="muted">(you)</small> }</td>
                  <td><p-tag [value]="m.kind === 'staff' ? 'Staff' : 'External'" [severity]="m.kind === 'staff' ? 'secondary' : 'info'" /></td>
                  <td>
                    @if (p.my_access === 'edit' && m.project_role !== 'Client') {
                      <p-select [options]="roleOptions()" [ngModel]="m.project_role" (onChange)="updateMember(m, { project_role: $event.value })" size="small" appendTo="body" />
                    } @else { {{ m.project_role }} }
                  </td>
                  <td>
                    @if (p.my_access === 'edit' && m.kind === 'staff') {
                      <p-selectbutton [allowEmpty]="false" [options]="accessOptions" [ngModel]="m.access" (onChange)="updateMember(m, { access: $event.value })" optionLabel="label" optionValue="value" size="small" />
                    } @else { <p-tag [value]="m.access" severity="secondary" /> }
                  </td>
                  <td class="right">@if (p.my_access === 'edit' && m.project_role !== 'Client') {
                    <p-button icon="pi pi-times" [text]="true" [rounded]="true" severity="danger" (onClick)="removeMember(m)" /> }</td>
                </tr>
              </ng-template>
            </p-table>
            <p class="muted small mt">The client is set on Details and joins the team automatically. External parties see this project in their portal (view only).</p>
          </p-tabpanel>

          <!-- ================= ISSUES ================= -->
          <p-tabpanel value="issues">
            <div class="row-between mb">
              <p-selectbutton [allowEmpty]="false" [options]="issueFilter" [(ngModel)]="issueStatus" optionLabel="label" optionValue="value" (onChange)="loadIssues()" />
              <p-button label="Raise issue" icon="pi pi-plus" size="small" (onClick)="openIssue()" />
            </div>
            <p-table [value]="issues()" size="small">
              <ng-template #header><tr><th>Issue</th><th>Severity</th><th>Owner</th><th>Due</th><th>Waiting on</th><th>Status</th><th></th></tr></ng-template>
              <ng-template #body let-i>
                <tr>
                  <td><strong>{{ i.title }}</strong><br /><small class="muted">{{ i.description }}{{ i.stage_id ? ' · ' + stageLabel(i.stage_id) : '' }} · raised by {{ i.raised_by }}</small></td>
                  <td><p-tag [value]="i.severity" [severity]="i.severity === 'high' ? 'danger' : i.severity === 'medium' ? 'warn' : 'secondary'" /></td>
                  <td>{{ i.owner_name || '—' }}</td><td>{{ i.due || '—' }}</td>
                  <td>@if (i.status === 'open' && (p.my_access === 'edit' || i.created_by === auth.user()?.id)) {
                    <p-select [options]="partyOpts()" [ngModel]="i.waiting_on?.party ?? null" (onChange)="setIssueWaiting(i, $event.value)" optionLabel="label" optionValue="value" placeholder="—" [showClear]="true" size="small" appendTo="body" />
                  } @else { {{ i.waiting_on ? partyLabel(i.waiting_on.party) : '—' }} }</td>
                  <td><p-tag [value]="i.status" [severity]="sev[i.status]" /></td>
                  <td class="right">@if (p.my_access === 'edit' || i.created_by === auth.user()?.id) {
                    <p-button [label]="i.status === 'open' ? 'Close' : 'Reopen'" size="small" [text]="true" (onClick)="toggleIssue(i)" /> }</td>
                </tr>
              </ng-template>
              <ng-template #emptymessage><tr><td colspan="7" class="center muted">No issues</td></tr></ng-template>
            </p-table>
          </p-tabpanel>

          <!-- ================= DETAILS ================= -->
          <p-tabpanel value="details">
            @if (form(); as f) {
              <div class="grid2 top">
                <div class="stack">
                  <label class="field"><span>Project name</span><input pInputText [(ngModel)]="f.name" [disabled]="!canEdit()" fluid /></label>
                  <div class="field"><span>Services</span>
                    <p-selectbutton [options]="serviceOptions()" [(ngModel)]="f.services" [multiple]="true" optionLabel="label" optionValue="value" [disabled]="!canEdit()" />
                    <small class="muted">Adding a service appends its template stages. Services cannot be removed.</small></div>
                  <div class="grid2">
                    <label class="field"><span>Client</span><p-select [options]="contacts()" [(ngModel)]="f.client_id" optionLabel="name" optionValue="id" [filter]="true" [showClear]="true" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Referred by</span><p-select [options]="contacts()" [(ngModel)]="f.referred_by" optionLabel="name" optionValue="id" [filter]="true" [showClear]="true" [disabled]="!canEdit()" fluid /></label>
                  </div>
                  <div class="grid3">
                    <label class="field"><span>Status</span><p-select [options]="meta()?.statuses ?? []" [(ngModel)]="f.status" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Type</span><p-select [options]="meta()?.types ?? []" [(ngModel)]="f.project_type" [showClear]="true" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Branch</span><p-select [options]="meta()?.branches ?? []" [(ngModel)]="f.branch" [showClear]="true" [disabled]="!canEdit()" fluid /></label>
                  </div>
                  <div class="grid3">
                    <label class="field"><span>Start</span><input pInputText type="date" [(ngModel)]="f.start" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Target end</span><input pInputText type="date" [(ngModel)]="f.target_end" [disabled]="!canEdit()" fluid /></label>
                    <div class="field"><span>Planned end</span><input pInputText [value]="p.planned_end || '—'" disabled fluid /></div>
                  </div>
                  <div class="grid3">
                    @if (!hideMoney()) { <label class="field"><span>Project value</span><p-inputnumber [(ngModel)]="f.value" [min]="0" [disabled]="!canEdit()" fluid /></label> }
                    <label class="field"><span>Area</span><p-inputnumber [(ngModel)]="f.area" [min]="0" [disabled]="!canEdit()" fluid /></label>
                    <div class="field"><span>Unit</span><p-selectbutton [allowEmpty]="false" [options]="units" [(ngModel)]="f.area_unit" optionLabel="label" optionValue="value" [disabled]="!canEdit()" /></div>
                  </div>
                  <label class="field"><span>Description</span><textarea pTextarea rows="3" [(ngModel)]="f.description" [disabled]="!canEdit()" fluid></textarea></label>
                </div>
                <div class="stack">
                  <label class="field"><span>Site address</span><input pInputText [(ngModel)]="f.site.line1" placeholder="Street" [disabled]="!canEdit()" fluid /></label>
                  <input pInputText [(ngModel)]="f.site.line2" placeholder="Area / landmark" [disabled]="!canEdit()" fluid />
                  <div class="grid3">
                    <input pInputText [(ngModel)]="f.site.city" placeholder="City" [disabled]="!canEdit()" fluid />
                    <input pInputText [(ngModel)]="f.site.state" placeholder="State" [disabled]="!canEdit()" fluid />
                    <input pInputText [(ngModel)]="f.site.pincode" placeholder="PIN" [disabled]="!canEdit()" fluid />
                  </div>
                  <app-map-picker [lat]="f.site.lat" [lng]="f.site.lng" [editable]="canEdit()" (picked)="f.site.lat = $event.lat; f.site.lng = $event.lng" />
                  @if (f.site.lat != null) {
                    <small class="muted">Pin: {{ f.site.lat }}, {{ f.site.lng }} · <a [href]="'https://www.openstreetmap.org/?mlat=' + f.site.lat + '&mlon=' + f.site.lng + '#map=17/' + f.site.lat + '/' + f.site.lng" target="_blank" rel="noopener">Open in maps</a>
                      @if (canEdit()) { · <a href="" (click)="$event.preventDefault(); f.site.lat = null; f.site.lng = null">remove pin</a> }</small>
                  }
                </div>
              </div>
              @if (canEdit()) { <div class="row right mt"><p-button label="Save details" icon="pi pi-check" [loading]="busy()" (onClick)="saveDetails()" /></div> }
            }
          </p-tabpanel>

          <p-tabpanel value="meetings">@if (tab === 'meetings') { <app-project-meetings [project]="p" [contacts]="contacts()" (changed)="reload()" /> }</p-tabpanel>
          <p-tabpanel value="activity">@if (tab === 'activity') { <app-project-activity [projectId]="p.id" /> }</p-tabpanel>
          <p-tabpanel value="followups">
            @if (auth.can('followups', 'rw')) { <div class="row right mb"><p-button label="Add follow-up" icon="pi pi-plus" size="small" (onClick)="fd().open({ type: 'project', id: p.id, label: p.name })" /></div> }
            @for (r of timeline(); track $index) {
              <div class="timeline-row"><i [class]="r.kind === 'followup' ? 'pi pi-bell' : (chIcon[r.type] || 'pi pi-circle')" [class.c-bad]="r.kind === 'followup' && r.status === 'open' && r.due < todayIso"></i>
                <div class="grow"><div>{{ r.title }} @if (r.kind === 'followup') { <p-tag [value]="r.status" [severity]="r.status === 'done' ? 'success' : r.status === 'open' ? 'warn' : 'secondary'" /> }</div>
                  <small class="muted">{{ r.kind === 'followup' ? 'Follow-up · due ' + r.due : r.lead }} · {{ r.owner }} · {{ r.at | date: 'd MMM y' }}{{ r.outcome ? ' · ' + r.outcome : '' }}</small></div></div>
            } @empty { <p class="muted">No follow-ups or activity yet.</p> }
          </p-tabpanel>

          <!-- ================= HISTORY ================= -->
          <p-tabpanel value="history">
            <p-table [value]="history()" size="small" [paginator]="history().length > 15" [rows]="15">
              <ng-template #header><tr><th>When</th><th>Who</th><th>What</th></tr></ng-template>
              <ng-template #body let-h><tr><td class="nowrap"><small>{{ h.at | date: 'short' }}</small></td><td>{{ h.by || '—' }}</td>
                <td class="cap">{{ h.action }} @if (h.fields.length) { <small class="muted">· {{ h.fields.join(', ') }}</small> }</td></tr></ng-template>
            </p-table>
          </p-tabpanel>

          <!-- ================= CONTRACT (Phase D: payment schedule follows the milestones) ================= -->
          @if (contract(); as c) {
            <p-tabpanel value="contract">
              <div class="row-between mb"><div><strong>Contract {{ c.number }}</strong> · {{ fmt(c.value) }} · signed {{ c.signed_at | date: 'd MMM y' }} by {{ c.acceptance?.name }}</div>
                <a [routerLink]="['/app/contracts', c.id]">Open / print →</a></div>
              <p-table [value]="c.payment_schedule" size="small">
                <ng-template #header><tr><th>Payment</th><th>When</th><th class="right">%</th><th class="right">Amount</th><th>Now</th></tr></ng-template>
                <ng-template #body let-r><tr><td>{{ r.name }}</td>
                  <td class="small">{{ r.trigger === 'signing' ? 'On signing' : r.trigger === 'date' ? (r.date | date: 'd MMM y') : (r.milestone?.name || r.stage + ' complete') }}
                    @if (r.milestone?.due) { <span class="muted"> · planned {{ r.milestone.due | date: 'd MMM y' }}</span> }</td>
                  <td class="right">{{ r.pct }}</td><td class="right">{{ fmt(r.amount) }}</td>
                  <td><p-tag [value]="label(r.state)" [severity]="r.state === 'due' ? 'warn' : 'secondary'" /></td></tr></ng-template>
              </p-table>
              <small class="muted">A stage payment becomes due when its milestone is marked achieved. Invoicing arrives with Finance (Phase E).</small>
            </p-tabpanel>
          }

          <!-- ================= FROM THE LEAD (C+2.7: nothing is retyped) ================= -->
          @if (handover(); as h) {
            <p-tabpanel value="lead">
              <div class="grid2 top">
                <div class="stack">
                  @if (h.brief) {
                    <p-card><ng-template #title>Brief v{{ h.brief.version }} @if (h.brief.client_confirmed) { <small class="muted">· confirmed by the client ({{ h.brief.client_confirmed.how }})</small> }</ng-template>
                      @for (s of h.brief.scope; track $index) { <div class="small"><strong>{{ s.room }}</strong>: {{ s.work_types.join(', ') }}</div> }
                      @for (k of briefKeys; track k.key) { @if (h.brief[k.key]) { <div class="small mt-xs"><strong>{{ k.label }}:</strong> {{ h.brief[k.key] }}</div> } }
                    </p-card>
                  }
                  @if (h.stakeholders?.length) {
                    <p-card><ng-template #title>Decision-makers</ng-template>
                      @for (s of h.stakeholders; track s.id) { <div class="small">{{ s.name }} — {{ s.role }}{{ s.main ? ' (main)' : '' }}{{ s.phone ? ' · ' + s.phone : '' }}</div> }
                    </p-card>
                  }
                  @if (h.visits?.length) {
                    <p-card><ng-template #title>Site visit reports</ng-template>
                      @for (v of h.visits; track $index) { @if (v.report) { <div class="small mb-xs"><strong>{{ v.at | date: 'd MMM y' }}:</strong> {{ v.report.findings }}{{ v.report.risks ? ' · Risks: ' + v.report.risks : '' }}</div> } }
                    </p-card>
                  }
                </div>
                <div class="stack">
                  @if (h.measurements?.rooms?.length) {
                    <p-card><ng-template #title>Measurements ({{ h.measurements.unit }})</ng-template>
                      @for (r of h.measurements.rooms; track r.id) { <div class="small">{{ r.name }}: {{ r.length }} × {{ r.width }}{{ r.height ? ' × ' + r.height : '' }}</div> }
                    </p-card>
                  }
                  @if (h.accepted_proposal; as a) {
                    <p-card><ng-template #title>Accepted proposal</ng-template>
                      <div class="small"><strong>{{ a.number }}</strong> {{ a.title }}{{ a.value != null ? ' · ' + fmt(a.value) : '' }}</div>
                      @if (a.file_key) { <a class="small" href="" (click)="$event.preventDefault(); api.openFile('/api/files/' + a.file_key)">Open the proposal file</a> }
                    </p-card>
                  }
                  @if (h.receipts?.length) {
                    <p-card><ng-template #title>Advances received</ng-template>
                      @for (r of h.receipts; track r.id) { <div class="small" [class.strike]="r.status === 'void'">{{ r.number }} · {{ r.kind }} · {{ fmt(r.amount) }} · {{ r.mode }} · {{ r.date | date: 'd MMM y' }}</div> }
                    </p-card>
                  }
                  @if (h.files?.length) {
                    <p-card><ng-template #title>Files from the lead</ng-template>
                      @for (f of h.files; track f.id) { <div class="small"><a href="" (click)="$event.preventDefault(); api.openFile(f.url)">{{ f.name }}</a> <span class="muted">· {{ f.folder }}{{ f.room ? ' · ' + f.room : '' }}</span></div> }
                    </p-card>
                  }
                </div>
              </div>
            </p-tabpanel>
          }
        </p-tabpanels>
      </p-tabs>

      <!-- ================= DIALOGS ================= -->
      <p-dialog [header]="sf.id ? 'Edit stage' : 'Add stage'" [modal]="true" [(visible)]="stageDlg" [style]="{ width: '32rem' }">
        <form class="stack" (ngSubmit)="saveStage()">
          <label class="field"><span>Name</span><input pInputText name="n" [(ngModel)]="sf.name" fluid /></label>
          @if (!sf.id) { <label class="field"><span>Service</span><p-select name="s" [options]="stageServiceOptions()" [(ngModel)]="sf.service" optionLabel="label" optionValue="value" fluid appendTo="body" /></label> }
          <div class="grid2">
            <label class="field"><span>Start</span><input pInputText type="date" name="st" [(ngModel)]="sf.start" fluid /></label>
            <label class="field"><span>End</span><input pInputText type="date" name="en" [(ngModel)]="sf.end" fluid /></label>
          </div>
          @if (p.my_access === 'edit' && !hideMoney()) { <label class="field"><span>Budget</span><p-inputnumber name="b" [(ngModel)]="sf.budget" [min]="0" fluid /></label> }
          @if (sf.id && !sf.hasTasks) { <div class="field"><span>Progress {{ sf.progress }}%</span><p-slider name="pr" [(ngModel)]="sf.progress" [step]="5" /></div> }
          <div class="row gap right"><p-button type="submit" label="Save" icon="pi pi-check" /></div>
        </form>
      </p-dialog>

      <p-dialog [header]="tf.id ? 'Edit task' : 'Add task'" [modal]="true" [(visible)]="taskDlg" [style]="{ width: '34rem' }">
        <form class="stack" (ngSubmit)="saveTask()">
          <label class="field"><span>Task</span><input pInputText name="t" [(ngModel)]="tf.title" fluid /></label>
          <div class="grid2">
            <label class="field"><span>Start</span><input pInputText type="date" name="st" [(ngModel)]="tf.start" fluid /></label>
            <label class="field"><span>End</span><input pInputText type="date" name="en" [(ngModel)]="tf.end" fluid /></label>
          </div>
          <label class="field"><span>Assignee <small class="muted">(project team staff)</small></span>
            <p-select name="a" [options]="staffOnTeam()" [(ngModel)]="tf.assignee_id" optionLabel="name" optionValue="user_id" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Priority</span><p-selectbutton name="pr" [options]="priorities" [(ngModel)]="tf.priority" [allowEmpty]="false" /></label>
          <div class="field"><span>Depends on <small class="muted">· lag in working days</small></span>
            @for (l of tf.links; track $index; let i = $index) {
              <div class="dep-row">
                <p-select [name]="'lt' + i" [options]="depOptions()" [(ngModel)]="l.task_id" optionLabel="label" optionValue="id" [filter]="true" placeholder="Task" appendTo="body" />
                <p-select [name]="'ly' + i" [options]="linkTypes" [(ngModel)]="l.type" optionLabel="label" optionValue="value" appendTo="body" />
                <p-inputnumber [name]="'lg' + i" [(ngModel)]="l.lag" [min]="-60" [max]="365" [showButtons]="false" inputStyleClass="w-4" pTooltip="Lag (working days)" />
                <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="tf.links.splice(i, 1)" />
              </div>
            }
            <p-button label="Add dependency" icon="pi pi-plus" size="small" [text]="true" (onClick)="tf.links.push({ task_id: null, type: 'FS', lag: 0 })" />
            <small class="muted">Finish → start: starts after the other finishes. Start → start: starts once the other starts. Finish → finish: finishes once the other finishes.</small></div>
          <label class="field"><span>Notes</span><textarea pTextarea name="no" rows="2" [(ngModel)]="tf.notes" fluid></textarea></label>
          <div class="row gap right"><p-button type="submit" label="Save" icon="pi pi-check" /></div>
        </form>
      </p-dialog>

      <p-dialog [header]="mf.id ? 'Edit milestone' : 'Add milestone'" [modal]="true" [(visible)]="msDlg" [style]="{ width: '26rem' }">
        <form class="stack" (ngSubmit)="saveMilestone()">
          <label class="field"><span>Milestone</span><input pInputText name="n" [(ngModel)]="mf.name" fluid /></label>
          <label class="field"><span>Due</span><input pInputText type="date" name="d" [(ngModel)]="mf.due" fluid /></label>
          <div class="row gap right"><p-button type="submit" label="Save" icon="pi pi-check" /></div>
        </form>
      </p-dialog>

      <p-dialog header="Add team member" [modal]="true" [(visible)]="memberDlg" [style]="{ width: '30rem' }">
        <form class="stack" (ngSubmit)="addMember()">
          <p-selectbutton [allowEmpty]="false" name="k" [options]="memberKinds" [(ngModel)]="nm.kind" optionLabel="label" optionValue="value" />
          @if (nm.kind === 'staff') {
            <label class="field"><span>Staff member</span><p-select name="u" [options]="staffNotOnTeam()" [(ngModel)]="nm.user_id" optionLabel="label" optionValue="id" [filter]="true" fluid appendTo="body" /></label>
            <div class="field"><span>Access on this project</span><p-selectbutton [allowEmpty]="false" name="ac" [options]="accessOptions" [(ngModel)]="nm.access" optionLabel="label" optionValue="value" /></div>
          } @else {
            <label class="field"><span>Contact</span><p-select name="c" [options]="contacts()" [(ngModel)]="nm.contact_id" optionLabel="name" optionValue="id" [filter]="true" fluid appendTo="body" /></label>
          }
          <label class="field"><span>Role on this project</span><p-select name="r" [options]="roleOptions()" [(ngModel)]="nm.project_role" [filter]="true" fluid appendTo="body" /></label>
          <div class="row gap right"><p-button type="submit" label="Add" icon="pi pi-check" /></div>
        </form>
      </p-dialog>

      <p-dialog header="Raise issue" [modal]="true" [(visible)]="issueDlg" [style]="{ width: '30rem' }">
        <form class="stack" (ngSubmit)="saveIssue()">
          <label class="field"><span>Issue</span><input pInputText name="t" [(ngModel)]="isf.title" fluid /></label>
          <label class="field"><span>Details</span><textarea pTextarea name="d" rows="3" [(ngModel)]="isf.description" fluid></textarea></label>
          <div class="grid3">
            <label class="field"><span>Severity</span><p-select name="s" [options]="['low', 'medium', 'high']" [(ngModel)]="isf.severity" fluid appendTo="body" /></label>
            <label class="field"><span>Owner</span><p-select name="o" [options]="staffOnTeam()" [(ngModel)]="isf.owner_id" optionLabel="name" optionValue="user_id" [showClear]="true" fluid appendTo="body" /></label>
            <label class="field"><span>Due</span><input pInputText type="date" name="du" [(ngModel)]="isf.due" fluid /></label>
          </div>
          <label class="field"><span>Stage <small class="muted">(a high issue on a stage stops it from closing)</small></span>
            <p-select name="st" [options]="p.stages" [(ngModel)]="isf.stage_id" optionLabel="name" optionValue="id" [showClear]="true" placeholder="Whole project" fluid appendTo="body" /></label>
          <div class="row gap right"><p-button type="submit" label="Raise" icon="pi pi-check" /></div>
        </form>
      </p-dialog>
    }
    @if (p(); as p) {
      <app-task-panel [project]="p" [parties]="partyOpts()" (changed)="panelChanged($event)" />

      <p-dialog header="Why is it later?" [modal]="true" [(visible)]="delayDlg" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p class="small">{{ delayMsg }}</p>
          <label class="field"><span>Reason</span><p-select [options]="delayReasons()" [(ngModel)]="dl.reason" optionLabel="label" optionValue="value" fluid appendTo="body" /></label>
          <label class="field"><span>Note <small class="muted">(optional)</small></span><input pInputText [(ngModel)]="dl.note" fluid /></label>
          <small class="muted">The plan has a baseline, so every date moved later is kept as a delay with who caused it.</small>
          <div class="row gap right"><p-button label="Cancel" [text]="true" severity="secondary" (onClick)="delayDlg = false; reload()" />
            <p-button label="Save" icon="pi pi-check" [disabled]="!dl.reason" (onClick)="delayOk()" /></div>
        </div>
      </p-dialog>

      <p-dialog header="Blocked — waiting on whom?" [modal]="true" [(visible)]="waitDlg" [style]="{ width: '28rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <label class="field"><span>Waiting on</span><p-select [options]="partyOpts()" [(ngModel)]="wf.party" optionLabel="label" optionValue="value" fluid appendTo="body" /></label>
          <label class="field"><span>Who exactly <small class="muted">(optional contact)</small></span>
            <p-select [options]="contacts()" [(ngModel)]="wf.contact_id" optionLabel="name" optionValue="id" [filter]="true" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>What for</span><input pInputText [(ngModel)]="wf.note" placeholder="e.g. tile selection, drawing approval" fluid /></label>
          <div class="row gap right"><p-button label="Cancel" [text]="true" severity="secondary" (onClick)="waitDlg = false; reload()" />
            <p-button label="Mark blocked" icon="pi pi-check" [disabled]="!wf.party" (onClick)="saveWaiting()" /></div>
        </div>
      </p-dialog>

      <p-dialog header="Record client sign-off" [modal]="true" [(visible)]="signDlg" [style]="{ width: '28rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <label class="field"><span>Signed off by</span><input pInputText [(ngModel)]="so.name" fluid /></label>
          <div class="grid2">
            <label class="field"><span>How</span><p-select [options]="signoffMethods" [(ngModel)]="so.method" fluid appendTo="body" /></label>
            <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="so.date" fluid /></label>
          </div>
          <label class="field"><span>Note</span><input pInputText [(ngModel)]="so.note" placeholder="e.g. approved on site walk-through" fluid /></label>
          <div class="row gap right"><p-button label="Save" icon="pi pi-check" [disabled]="!so.name || !so.method" (onClick)="saveSignoff()" /></div>
        </div>
      </p-dialog>

      <p-dialog header="Close the stage anyway?" [modal]="true" [(visible)]="overDlg" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p class="small">{{ overStage?.name }} is not ready:</p>
          <ul class="small">@for (m of overStage?.gate?.missing ?? []; track $index) { <li>{{ m }}</li> }</ul>
          @if (auth.user()?.role === 'owner') {
            <label class="field"><span>Reason (kept on the timeline)</span><input pInputText [(ngModel)]="overReason" fluid /></label>
            <div class="row gap right"><p-button label="Cancel" [text]="true" severity="secondary" (onClick)="overDlg = false" />
              <p-button label="Close anyway" icon="pi pi-exclamation-triangle" severity="warn" [disabled]="!overReason.trim()" (onClick)="override()" /></div>
          } @else { <p class="small muted">Finish these first. Only the Owner can close a stage that is not ready.</p> }
        </div>
      </p-dialog>

      <p-dialog header="Set the baseline" [modal]="true" [(visible)]="blDlg" [style]="{ width: '28rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p class="small">Today's dates become the agreed plan. From then on every task and stage shows how far it is from this plan, and moving a date later asks for a reason.</p>
          <label class="field"><span>Note</span><input pInputText [(ngModel)]="blNote" placeholder="e.g. plan agreed with the client" fluid /></label>
          <div class="row gap right"><p-button label="Set baseline" icon="pi pi-bookmark" (onClick)="saveBaseline()" /></div>
        </div>
      </p-dialog>

      <p-dialog header="Move the tasks that depend on it?" [modal]="true" [(visible)]="shiftDlg" [style]="{ width: '28rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p class="small">{{ shiftMsg }}</p>
          <div class="row gap right">
            <p-button label="Only this task" [text]="true" (onClick)="doMove(false)" />
            <p-button label="Move them too" icon="pi pi-arrows-h" (onClick)="doMove(true)" /></div>
        </div>
      </p-dialog>
    }
    <app-followup-dialog (saved)="loadTimeline()" />
  `,
})
export class ProjectDetailComponent implements OnInit {
  fd = viewChild.required(FollowupDialogComponent);
  timeline = signal<any[]>([]);
  chIcon = CHANNEL_ICON;
  todayIso = new Date().toISOString().slice(0, 10);

  async loadTimeline() {
    this.timeline.set(await this.api.get(`/projects/${this.id()}/followups`));
  }

  id = input.required<string>();
  auth = inject(AuthService);
  api = inject(Api);
  private router = inject(Router);
  private confirm = inject(ConfirmationService);

  p = signal<any>(null);
  dash = signal<any>(null);
  meta = signal<any>(null);
  issues = signal<any[]>([]);
  history = signal<any[]>([]);
  handover = signal<any>(null);
  contract = signal<any>(null);
  briefKeys = [{ key: "style", label: "Style" }, { key: "materials", label: "Materials" }, { key: "brands", label: "Brands" }, { key: "must_haves", label: "Must-haves" },
    { key: "nice_to_haves", label: "Nice-to-haves" }, { key: "programme", label: "Spaces" }, { key: "approvals_needed", label: "Approvals" }, { key: "notes", label: "Notes" }];
  contacts = signal<any[]>([]);
  staff = signal<any[]>([]);
  form = signal<any>(null);
  busy = signal(false);
  tab = 'overview';

  sev = STATUS_SEVERITY;
  svc = SERVICE_LABEL;
  color = SERVICE_COLOR;
  label = label;
  units = [{ label: 'sq ft', value: 'sqft' }, { label: 'm²', value: 'sqm' }];
  accessOptions = [{ label: 'Edit', value: 'edit' }, { label: 'View', value: 'view' }];
  memberKinds = [{ label: 'Staff', value: 'staff' }, { label: 'External party', value: 'external' }];
  issueFilter = [{ label: 'Open', value: 'open' }, { label: 'Closed', value: 'closed' }, { label: 'All', value: '' }];
  taskStatuses = [{ label: 'To do', value: 'todo' }, { label: 'In progress', value: 'in_progress' }, { label: 'Blocked', value: 'blocked' }, { label: 'Done', value: 'done' }];
  issueStatus = 'open';
  prio = PRIORITY_SEVERITY;
  priorities = [{ label: 'Low', value: 'low' }, { label: 'Normal', value: 'normal' }, { label: 'High', value: 'high' }, { label: 'Urgent', value: 'urgent' }];
  linkTypes = [{ label: 'Finish → start', value: 'FS' }, { label: 'Start → start', value: 'SS' }, { label: 'Finish → finish', value: 'FF' }];
  signoffMethods = ['In person', 'Email', 'WhatsApp', 'Phone', 'Signed document'];
  planMeta = signal<any>(null);
  panel = viewChild.required(TaskPanelComponent);
  health = viewChild<ProjectHealthComponent>('health');
  stageItem: Record<string, string | undefined> = {};
  delayDlg = false; waitDlg = false; signDlg = false; overDlg = false; blDlg = false; shiftDlg = false;
  delayMsg = ''; shiftMsg = ''; overReason = ''; blNote = '';
  dl: any = {}; wf: any = {}; so: any = {};
  overStage: any = null;
  private signStage: any = null;
  private waitTask: any = null;
  private pending: { url: string; body: any; method: 'put' } | null = null;
  private moveReq: any = null;
  partyOpts = computed(() => this.planMeta()?.waiting_parties ?? []);
  delayReasons = computed(() => this.planMeta()?.delay_reasons ?? []);
  editableStageIds = computed(() => (this.p()?.stages ?? []).filter((s: any) => this.canEditStage(s)).map((s: any) => s.id));

  canEdit = computed(() => this.p()?.my_access === 'edit');
  hideMoney = computed(() => this.p() && this.p().value === undefined);
  anyStageEdit = computed(() => this.canEdit() || this.p()?.can_edit_design);
  serviceOptions = computed(() => (this.meta()?.services ?? []).map((s: string) => ({ value: s, label: SERVICE_LABEL[s] })));
  stageServiceOptions = computed(() => (this.p()?.services ?? []).filter((s: string) => this.canEdit() || DESIGN.includes(s))
    .map((s: string) => ({ value: s, label: SERVICE_LABEL[s] })));
  roleOptions = computed(() => (this.meta()?.project_roles ?? []).filter((r: string) => r !== 'Client'));
  staffOnTeam = computed(() => (this.p()?.team ?? []).filter((m: any) => m.user_id));
  staffNotOnTeam = computed(() => this.staff().filter((s) => !this.staffOnTeam().some((m: any) => m.user_id === s.id))
    .map((s) => ({ ...s, label: `${s.name} · ${this.auth.roleLabel(s.role)}` })));
  allTasks = computed(() => (this.p()?.stages ?? []).flatMap((s: any) => (s.tasks ?? []).map((t: any) => ({ ...t, stage: s.name }))));
  depOptions = computed(() => this.allTasks().filter((t: any) => t.id !== this.tf.id).map((t: any) => ({ id: t.id, label: `${t.title} (${t.stage})` })));

  stageDlg = false; taskDlg = false; msDlg = false; memberDlg = false; issueDlg = false;
  sf: any = {}; tf: any = {}; mf: any = {}; nm: any = {}; isf: any = {};
  private taskStage: any = null;
  private msStage: any = null;

  async ngOnInit() {
    this.meta.set(await this.api.get('/projects/meta'));
    this.planMeta.set(await this.api.get('/projects/plan_meta'));
    await this.reload();
    if (this.auth.can('contacts')) this.contacts.set(await this.api.get('/contacts'));
    this.staff.set(await this.api.get('/directory/staff'));
  }

  async reload(p?: any) {
    this.setProject(p ?? (await this.api.get(`/projects/${this.id()}`)));
    this.dash.set(await this.api.get(`/projects/${this.id()}/dashboard`));
    this.history.set(await this.api.get(`/projects/${this.id()}/history`));
    this.handover.set(await this.api.get(`/projects/${this.id()}/handover`));
    this.contract.set(await this.api.get(`/projects/${this.id()}/contract`));
    if (this.auth.can('followups')) await this.loadTimeline();
    await this.loadIssues();
    await this.health()?.load();
  }

  private setProject(p: any) {
    this.p.set(p);
    this.form.set({ name: p.name, services: [...p.services], client_id: p.client_id ?? null, referred_by: p.referred_by ?? null,
      status: p.status, project_type: p.project_type ?? null, branch: p.branch ?? null, start: p.start, target_end: p.target_end ?? null,
      value: p.value ?? null, area: p.area ?? null, area_unit: p.area_unit ?? 'sqft', description: p.description ?? '',
      site: { line1: '', line2: '', city: '', state: '', pincode: '', country: 'India', lat: null, lng: null, ...(p.site ?? {}) } });
  }

  private async apply(promise: Promise<any>) {
    const p = await promise;
    await this.reload(p);
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  canEditStage(s: any) {
    return this.canEdit() || (this.p()?.can_edit_design && DESIGN.includes(s.service));
  }

  depNames(t: any) {
    const all = this.allTasks();
    return (t.depends_on ?? []).map((id: string) => all.find((x: any) => x.id === id)?.title).filter(Boolean).join(', ') || '—';
  }

  // ---------- stages ----------
  openStage(s?: any) {
    const svc = this.stageServiceOptions()[0]?.value;
    this.sf = s ? { id: s.id, name: s.name, start: s.start, end: s.end, budget: s.budget ?? 0, progress: s.progress, hasTasks: s.tasks.length > 0 }
      : { name: '', service: svc, start: this.p().start, end: this.p().start, budget: 0 };
    this.stageDlg = true;
  }

  async saveStage() {
    const body: any = { name: this.sf.name, start: this.sf.start, end: this.sf.end };
    if (this.canEdit() && !this.hideMoney()) body.budget = this.sf.budget ?? 0;
    if (this.sf.id && !this.sf.hasTasks) body.progress = this.sf.progress;
    if (!this.sf.id) body.service = this.sf.service;
    this.stageDlg = false;
    if (this.sf.id) await this.putWithReason(`/projects/${this.id()}/stages/${this.sf.id}`, body);
    else await this.apply(this.api.post(`/projects/${this.id()}/stages`, body, 'Stage added'));
  }

  hold(s: any) {
    this.apply(this.api.put(`/projects/${this.id()}/stages/${s.id}`, { status: s.status === 'on_hold' ? 'active' : 'on_hold' }));
  }

  move(s: any, dir: number) {
    const ids = this.p().stages.map((x: any) => x.id);
    const i = ids.indexOf(s.id);
    [ids[i], ids[i + dir]] = [ids[i + dir], ids[i]];
    this.apply(this.api.post(`/projects/${this.id()}/stages/reorder`, { order: ids }));
  }

  deleteStage(s: any) {
    this.confirm.confirm({ header: `Delete ${s.name}?`, message: 'Its tasks and milestones are deleted too.', icon: 'pi pi-trash',
      acceptButtonProps: { label: 'Delete', severity: 'danger' }, rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: () => this.apply(this.api.del(`/projects/${this.id()}/stages/${s.id}`, 'Stage deleted')) });
  }

  // ---------- tasks ----------
  openTask(s: any, t?: any) {
    this.taskStage = s;
    this.tf = t ? { id: t.id, title: t.title, start: t.start, end: t.end, assignee_id: t.assignee_id, notes: t.notes ?? '', priority: t.priority ?? 'normal',
        links: (t.links ?? (t.depends_on ?? []).map((x: string) => ({ task_id: x, type: 'FS', lag: 0 }))).map((l: any) => ({ ...l })) }
      : { title: '', start: s.start, end: s.end, assignee_id: null, notes: '', priority: 'normal', links: [] };
    this.taskDlg = true;
  }

  async saveTask() {
    const body = { title: this.tf.title, start: this.tf.start, end: this.tf.end, assignee_id: this.tf.assignee_id, notes: this.tf.notes,
      priority: this.tf.priority, links: this.tf.links.filter((l: any) => l.task_id).map((l: any) => ({ ...l, lag: l.lag ?? 0 })) };
    this.taskDlg = false;
    if (this.tf.id) await this.putWithReason(`/projects/${this.id()}/tasks/${this.tf.id}`, body);
    else await this.apply(this.api.post(`/projects/${this.id()}/stages/${this.taskStage.id}/tasks`, body, 'Task added'));
  }

  async setTaskStatus(t: any, status: string) {
    try {
      await this.apply(this.api.put(`/projects/${this.id()}/tasks/${t.id}`, { status }));
    } catch {
      await this.reload(); // revert the dropdown when the server refuses (e.g. waiting on a predecessor)
    }
  }

  deleteTask(t: any) {
    this.apply(this.api.del(`/projects/${this.id()}/tasks/${t.id}`, 'Task deleted'));
  }

  ganttSelect(r: any) {
    const stage = this.p().stages.find((s: any) => s.id === r.id || s.tasks.some((t: any) => t.id === r.id));
    if (!stage || !this.canEditStage(stage)) return;
    if (r.kind === 'stage') this.openStage(stage);
    else this.openTask(stage, stage.tasks.find((t: any) => t.id === r.id));
  }

  // ---------- milestones ----------
  openMilestone(s: any, m?: any) {
    this.msStage = s;
    this.mf = m ? { id: m.id, name: m.name, due: m.due } : { name: '', due: s.end };
    this.msDlg = true;
  }

  async saveMilestone() {
    const body = { name: this.mf.name, due: this.mf.due };
    this.msDlg = false;
    if (this.mf.id) await this.putWithReason(`/projects/${this.id()}/milestones/${this.mf.id}`, body);
    else await this.apply(this.api.post(`/projects/${this.id()}/stages/${this.msStage.id}/milestones`, body, 'Milestone added'));
  }

  toggleMilestone(m: any) {
    this.apply(this.api.put(`/projects/${this.id()}/milestones/${m.id}`, { status: m.status === 'achieved' ? 'pending' : 'achieved' }));
  }

  deleteMilestone(m: any) {
    this.apply(this.api.del(`/projects/${this.id()}/milestones/${m.id}`, 'Milestone deleted'));
  }

  // ---------- team ----------
  openMember() {
    this.nm = { kind: 'staff', user_id: null, contact_id: null, project_role: null, access: 'view' };
    this.memberDlg = true;
  }

  async addMember() {
    const body = this.nm.kind === 'staff' ? { user_id: this.nm.user_id, project_role: this.nm.project_role, access: this.nm.access }
      : { contact_id: this.nm.contact_id, project_role: this.nm.project_role };
    await this.apply(this.api.post(`/projects/${this.id()}/team`, body, 'Member added'));
    this.memberDlg = false;
  }

  async updateMember(m: any, change: any) {
    try {
      await this.apply(this.api.put(`/projects/${this.id()}/team/${m.id}`, change, 'Updated'));
    } catch {
      await this.reload();
    }
  }

  removeMember(m: any) {
    this.confirm.confirm({ header: `Remove ${m.name}?`, message: 'Their open tasks on this project become unassigned.', icon: 'pi pi-user-minus',
      acceptButtonProps: { label: 'Remove', severity: 'danger' }, rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: () => this.apply(this.api.del(`/projects/${this.id()}/team/${m.id}`, 'Member removed')) });
  }

  // ---------- issues ----------
  async loadIssues() {
    this.issues.set(await this.api.get(`/projects/${this.id()}/issues${this.issueStatus ? '?status=' + this.issueStatus : ''}`));
  }

  openIssue() {
    this.isf = { title: '', description: '', severity: 'medium', owner_id: null, due: null, stage_id: null };
    this.issueDlg = true;
  }

  async saveIssue() {
    await this.api.post(`/projects/${this.id()}/issues`, this.isf, 'Issue raised');
    this.issueDlg = false;
    await this.reload();
  }

  async toggleIssue(i: any) {
    await this.api.put(`/projects/${this.id()}/issues/${i.id}`, { status: i.status === 'open' ? 'closed' : 'open' });
    await this.reload();
  }

  // ---------- B+2: stage closing, task panel ----------
  doneItems(t: any) {
    return (t.checklist ?? []).filter((c: any) => c.done).length;
  }

  partyLabel(v: string) {
    return this.partyOpts().find((x: any) => x.value === v)?.label ?? v;
  }

  stageLabel(id: string) {
    return this.p()?.stages.find((s: any) => s.id === id)?.name ?? '';
  }

  async panelChanged(p: any) {
    await this.reload(p ?? undefined);
  }

  async tickStage(s: any, c: any, done: boolean) {
    await this.apply(this.api.put(`/projects/${this.id()}/stages/${s.id}/checklist/${c.id}`, { done }));
  }

  async addStageItem(s: any) {
    const text = (this.stageItem[s.id] ?? '').trim();
    if (!text) return;
    await this.apply(this.api.post(`/projects/${this.id()}/stages/${s.id}/checklist`, { text }));
    this.stageItem[s.id] = '';
  }

  async removeStageItem(s: any, c: any) {
    await this.apply(this.api.del(`/projects/${this.id()}/stages/${s.id}/checklist/${c.id}`));
  }

  closeStage(s: any) {
    if (s.gate?.missing?.length) {
      this.overStage = s;
      this.overReason = '';
      this.overDlg = true;
      return;
    }
    this.apply(this.api.put(`/projects/${this.id()}/milestones/${s.gate.milestone_id}`, { status: 'achieved' }, `${s.name} closed`));
  }

  async override() {
    const s = this.overStage;
    this.overDlg = false;
    await this.apply(this.api.put(`/projects/${this.id()}/milestones/${s.gate.milestone_id}`, { status: 'achieved', override_reason: this.overReason.trim() },
      `${s.name} closed by the Owner`));
  }

  openSignoff(s: any) {
    this.signStage = s;
    this.so = { name: this.p()?.client_name ?? '', method: 'In person', date: new Date().toISOString().slice(0, 10), note: '' };
    this.signDlg = true;
  }

  async saveSignoff() {
    this.signDlg = false;
    await this.apply(this.api.post(`/projects/${this.id()}/stages/${this.signStage.id}/signoff`, this.so, 'Client sign-off recorded'));
  }

  removeSignoff(s: any) {
    this.apply(this.api.del(`/projects/${this.id()}/stages/${s.id}/signoff`, 'Sign-off removed'));
  }

  toggleSignoffRule(s: any) {
    this.apply(this.api.put(`/projects/${this.id()}/stages/${s.id}`, { client_signoff_required: !s.client_signoff_required }));
  }

  // ---------- B+3: baseline, delays, Gantt drag ----------
  openBaseline() {
    this.blNote = '';
    this.blDlg = true;
  }

  async saveBaseline() {
    this.blDlg = false;
    await this.apply(this.api.post(`/projects/${this.id()}/baseline`, { note: this.blNote }, 'Baseline set'));
  }

  /** PUT that may need a delay reason (the plan has a baseline and a date moves later): ask, then send again. */
  async putWithReason(url: string, body: any) {
    try {
      await this.reload(await this.api.raw('put', url, body));
    } catch (e: any) {
      const msg = e?.error?.error ?? '';
      if (e?.status === 409 && msg.includes('delay reason')) {
        this.pending = { url, body, method: 'put' };
        this.delayMsg = msg.replace(': choose why (delay reason), because the plan has a baseline', '.');
        this.dl = { reason: null, note: '' };
        this.delayDlg = true;
      } else {
        this.api.toastError(e);
        await this.reload();
      }
    }
  }

  async delayOk() {
    const p = this.pending!;
    this.delayDlg = false;
    await this.apply(this.api.put(p.url, { ...p.body, delay_reason: this.dl.reason, delay_note: this.dl.note }, 'Saved — delay recorded'));
  }

  ganttMoved(e: { id: string; start: string; end: string }) {
    const deps = this.allTasks().filter((t: any) => (t.depends_on ?? []).includes(e.id));
    this.moveReq = e;
    if (deps.length) {
      this.shiftMsg = `${deps.length} task(s) depend on it (${deps.slice(0, 3).map((t: any) => t.title).join(', ')}${deps.length > 3 ? '…' : ''}). Move them by the same number of working days?`;
      this.shiftDlg = true;
    } else this.doMove(false);
  }

  async doMove(shift: boolean) {
    this.shiftDlg = false;
    const e = this.moveReq;
    await this.putWithReason(`/projects/${this.id()}/tasks/${e.id}`, { start: e.start, end: e.end, shift_dependents: shift });
  }

  // ---------- B+4: waiting on whom ----------
  openWaiting(t: any) {
    this.waitTask = t;
    this.wf = { party: t.waiting_on?.party ?? null, contact_id: t.waiting_on?.contact_id ?? null, note: t.waiting_on?.note ?? '' };
    this.waitDlg = true;
  }

  async saveWaiting() {
    this.waitDlg = false;
    try {
      await this.apply(this.api.put(`/projects/${this.id()}/tasks/${this.waitTask.id}`, { status: 'blocked', waiting_on: this.wf }, 'Marked blocked'));
    } catch {
      await this.reload();
    }
  }

  async setIssueWaiting(i: any, party: string | null) {
    await this.api.put(`/projects/${this.id()}/issues/${i.id}`, { waiting_on: party ? { party } : null });
    await this.reload();
  }

  // ---------- details ----------
  async saveDetails() {
    const f = { ...this.form() };
    if (this.hideMoney()) delete f.value;
    this.busy.set(true);
    try {
      await this.apply(this.api.put(`/projects/${this.id()}`, f, 'Project saved'));
    } finally {
      this.busy.set(false);
    }
  }

  removeProject() {
    this.confirm.confirm({ header: 'Delete this project?', message: 'Stages, tasks, milestones, team and issues are deleted. This cannot be undone.',
      icon: 'pi pi-exclamation-triangle', acceptButtonProps: { label: 'Delete project', severity: 'danger' },
      rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: async () => {
        await this.api.del(`/projects/${this.id()}`, 'Project deleted');
        this.router.navigateByUrl('/app/projects');
      } });
  }
}
