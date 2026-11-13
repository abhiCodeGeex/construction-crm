import { Component, OnInit, computed, inject, input, signal, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, SERVICE_COLOR, SERVICE_LABEL, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { CHANNEL_ICON, CHANNEL_LABEL, FollowupDialogComponent } from '../../shared/followup-dialog.component';
import { WinLoseComponent } from './win-lose.component';
import { LeadBriefComponent } from './lead-brief.component';
import { LeadFilesComponent } from './lead-files.component';
import { LeadMoneyComponent } from './lead-money.component';
import { LeadProposalsComponent } from './lead-proposals.component';
import { LeadVisitsComponent } from './lead-visits.component';

/** Timeline filter groups (C+3). */
const GROUPS: Record<string, string[]> = {
  'Calls & messages': ['call', 'email', 'whatsapp', 'meeting', 'note', 'site_visit'],
  'Visits & site': ['visit', 'measurement', 'file'],
  'Brief & people': ['brief', 'stakeholder', 'ballpark'],
  'Money & proposals': ['estimate', 'expense', 'receipt', 'proposal', 'negotiation'],
  'Stage & status': ['created', 'stage', 'checklist', 'won', 'lost', 'reopened', 'on_hold', 'resumed', 'merged'],
  Edits: ['edit'],
};
const EVENT_ICON: Record<string, string> = {
  created: 'pi pi-plus-circle', stage: 'pi pi-arrow-right', checklist: 'pi pi-check-square', edit: 'pi pi-pencil',
  estimate: 'pi pi-calculator', expense: 'pi pi-minus-circle', receipt: 'pi pi-wallet', proposal: 'pi pi-file-edit', negotiation: 'pi pi-arrows-h', brief: 'pi pi-list-check', stakeholder: 'pi pi-users', ballpark: 'pi pi-calculator', visit: 'pi pi-map-marker', measurement: 'pi pi-arrows-h', file: 'pi pi-paperclip', won: 'pi pi-trophy', lost: 'pi pi-times-circle', reopened: 'pi pi-replay', on_hold: 'pi pi-pause', resumed: 'pi pi-play', note: 'pi pi-file',
};

@Component({
  selector: 'app-lead-detail',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, CardModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, MessageModule,
    SelectButtonModule, SelectModule, TabsModule, TagModule, TextareaModule, FollowupDialogComponent, WinLoseComponent, LeadBriefComponent, LeadFilesComponent, LeadMoneyComponent, LeadProposalsComponent, LeadVisitsComponent],
  template: `
    @if (l(); as l) {
      <div class="page-head">
        <div>
          <a routerLink="/app/leads" class="small"><i class="pi pi-arrow-left"></i> Pipeline</a>
          <h1>@if (l.temperature) { <span class="temp" [class]="l.temperature" [title]="l.temperature"></span> }{{ l.title }}</h1>
          <div class="row gap wrap">
            <span class="svc" [style.--c]="color[l.service]">{{ svc[l.service] }}</span>
            @switch (l.status) {
              @case ('won') { <p-tag value="Won" severity="success" icon="pi pi-trophy" /> @if (l.project_id) { <a [routerLink]="['/app/projects', l.project_id]">Project {{ l.project_code }} →</a> } @else { <span class="muted">project {{ l.project_code }} was deleted</span> } }
              @case ('lost') { <p-tag value="Lost" severity="danger" /> <span class="muted">{{ l.loss_reason }}{{ l.loss_note ? ' — ' + l.loss_note : '' }}{{ l.competitor ? ' · to ' + l.competitor + (l.competitor_price ? ' at ' + fmt(l.competitor_price) : '') : '' }}</span> }
              @case ('on_hold') { <p-tag value="On hold" severity="warn" icon="pi pi-pause" /> <span class="muted">until {{ l.resume_on | date: 'd MMM y' }} — {{ l.hold_reason }}</span> }
              @default { <p-tag [value]="l.stage" severity="info" />
                <span [class.c-bad]="l.over_limit" class="small">{{ l.days_in_stage }} day(s) in stage{{ l.max_days ? ' · limit ' + l.max_days : '' }}</span> }
            }
            <span class="muted"><i class="pi pi-user"></i> {{ l.owner_name || 'Unassigned' }}</span>
            <span class="score" title="Lead score (source, budget fit, temperature, last contact, response time)">Score {{ l.score }}</span>
            <span class="small muted">Value {{ fmt(l.value) }} · {{ l.probability_effective }}% · weighted {{ fmt(l.weighted_value) }}</span>
          </div>
          @if (contact(); as c) {
            <div class="row gap mt-xs small">
              @if (c.phone) { <a [href]="'tel:' + c.phone"><i class="pi pi-phone"></i> Call</a>
                <a [href]="wa(c.phone)" target="_blank" rel="noopener"><i class="pi pi-whatsapp"></i> WhatsApp</a> }
              @if (c.email) { <a [href]="'mailto:' + c.email"><i class="pi pi-envelope"></i> Email</a> }
              @if (l.best_time) { <span class="muted">best time: {{ l.best_time }}</span> }
              @if (l.preferred_language) { <span class="muted">language: {{ l.preferred_language }}</span> }
            </div>
          }
        </div>
        @if (canEdit()) {
          <div class="row gap wrap">
            @if (l.status === 'open') {
              <p-button label="On hold" icon="pi pi-pause" severity="secondary" [outlined]="true" (onClick)="openHold()" />
              <p-button label="Lost" icon="pi pi-times" severity="danger" [outlined]="true" (onClick)="wl().open('lost', l, meta())" />
              <p-button label="Won" icon="pi pi-trophy" severity="success" (onClick)="wl().open('won', l, meta())" />
            } @else if (l.status === 'lost') {
              <p-button label="Reopen" icon="pi pi-replay" [outlined]="true" (onClick)="reopen()" />
            } @else if (l.status === 'on_hold') {
              <p-button label="Resume now" icon="pi pi-play" [outlined]="true" (onClick)="resume()" />
            }
          </div>
        }
      </div>

      @if (l.status === 'open') {
        <div class="stepper">
          @for (s of l.pipeline; track s; let i = $index) {
            <button class="step" [class.done]="i < stageIndex()" [class.current]="i === stageIndex()" [disabled]="!canEdit()" (click)="move(s)">
              <span class="dot">{{ i < stageIndex() ? '✓' : i + 1 }}</span>{{ s }}</button>
          }
        </div>
        <div class="gate">
          <div class="row-between"><strong>To leave “{{ l.stage }}”</strong>
            @if (!l.missing.length) { <p-tag value="Ready for the next stage" severity="success" icon="pi pi-check" /> }
            @else { <small class="muted">{{ l.missing.length }} still to do</small> }</div>
          @for (item of l.stage_checklist; track item) {
            <label class="check-row"><p-checkbox [binary]="true" [ngModel]="ticked(item)" (ngModelChange)="tick(item, $event)" [disabled]="!canEdit()" /> {{ item }}
              @if (tickedBy(item); as t) { <small class="muted">— {{ t.by }}, {{ t.at | date: 'd MMM' }}</small> }</label>
          }
          @if (l.stage_requires.length) {
            <ul class="small">@for (r of l.stage_requires; track r) { <li [class.c-bad]="isMissing(r)" [class.muted]="!isMissing(r)">{{ isMissing(r) ? '○' : '✓' }} {{ r }}</li> }</ul>
          }
          @if (!l.stage_checklist.length && !l.stage_requires.length) { <small class="muted">No rules for this stage.</small> }
        </div>
      }

      <p-tabs [(value)]="tab" [scrollable]="true">
        <p-tablist>
          <p-tab value="overview"><i class="pi pi-id-card mr"></i>Overview</p-tab>
          <p-tab value="visits"><i class="pi pi-map-marker mr"></i>Visits & measurements</p-tab>
          <p-tab value="brief"><i class="pi pi-list-check mr"></i>Brief & decision-makers</p-tab>
          <p-tab value="money"><i class="pi pi-calculator mr"></i>Estimate & money</p-tab>
          <p-tab value="proposals"><i class="pi pi-file-edit mr"></i>Proposals & negotiation</p-tab>
          <p-tab value="files"><i class="pi pi-folder mr"></i>Files</p-tab>
          <p-tab value="timeline"><i class="pi pi-history mr"></i>Timeline ({{ l.activities.length }})</p-tab>
        </p-tablist>
        <p-tabpanels>
          <p-tabpanel value="overview">
            <div class="grid2 top">
              <div class="stack">
                @if (l.status === 'open' && canEdit()) {
                  <p-card>
                    <ng-template #title>Log a conversation</ng-template>
                    <div class="stack">
                      <p-selectbutton [allowEmpty]="false" [options]="activityTypes()" [(ngModel)]="act.type" optionLabel="label" optionValue="value" />
                      <textarea pTextarea rows="2" [(ngModel)]="act.text" placeholder="What was said? Call notes, meeting minutes, WhatsApp summary…" fluid></textarea>
                      @if (act.type === 'call') {
                        <div class="grid2">
                          <label class="field"><span>Outcome</span><p-select [options]="meta()?.call_outcomes ?? []" [(ngModel)]="act.outcome" placeholder="Choose" fluid appendTo="body" /></label>
                          <label class="field"><span>Duration (min)</span><p-inputnumber [(ngModel)]="act.duration_min" [min]="0" fluid /></label>
                        </div>
                      } @else if (act.type === 'meeting') {
                        <label class="field"><span>Outcome</span><input pInputText [(ngModel)]="act.outcome" placeholder="What was agreed" fluid /></label>
                      }
                      @if (needsNext()) {
                        <div class="grid2">
                          <label class="field"><span>Next follow-up (required)</span><input pInputText type="date" [min]="today" [(ngModel)]="act.next_due" fluid /></label>
                          <label class="field"><span>Next step</span><input pInputText [(ngModel)]="act.next_title" placeholder="e.g. Send floor plan options" fluid /></label>
                        </div>
                      }
                      <div class="row gap right">
                        <p-button label="Use template" icon="pi pi-file" [text]="true" (onClick)="openTemplates()" />
                        <p-button label="Log" icon="pi pi-send" (onClick)="logActivity()" [disabled]="!canLog()" />
                      </div>
                    </div>
                  </p-card>
                }

                <p-card>
                  <ng-template #title><div class="row-between"><span>Follow-ups</span>
                    @if (l.status === 'open' && auth.can('followups', 'rw')) { <span class="row gap"><p-button label="Draft a message" icon="pi pi-sparkles" size="small" [text]="true" (onClick)="draftDlg = true; draft = null" />
                      <p-button label="Add" icon="pi pi-plus" size="small" [text]="true" (onClick)="fd().open({ type: 'lead', id: l.id, label: l.title })" /></span> }</div></ng-template>
                  @if (draftDlg) {
                    <div class="stack draft">
                      <div class="row gap wrap">
                        <select class="p-inputtext" [(ngModel)]="dr.purpose" aria-label="Purpose"><option value="check_in">Check in</option><option value="proposal">About the proposal</option>
                          <option value="visit">Fix a site visit</option><option value="revive">Revive a quiet lead</option><option value="thanks">Thank you</option></select>
                        <select class="p-inputtext" [(ngModel)]="dr.channel" aria-label="Channel"><option value="whatsapp">WhatsApp</option><option value="email">Email</option></select>
                        <input pInputText class="grow" [(ngModel)]="dr.instruction" placeholder="Anything to add (e.g. in Hindi, mention the kitchen)" aria-label="Instruction" />
                        <p-button label="Draft" size="small" [loading]="drafting" (onClick)="makeDraft(l)" /><p-button label="Close" size="small" [text]="true" (onClick)="draftDlg = false" /></div>
                      @if (draft) {
                        @if (dr.channel === 'email') { <input pInputText [(ngModel)]="draft.subject" aria-label="Subject" /> }
                        <textarea class="p-inputtext" rows="5" [(ngModel)]="draft.body" aria-label="Message"></textarea>
                        <div class="row gap"><span class="small muted grow">{{ draft.source === 'template' ? 'Template (AI is off in Settings → AI)' : draft.source === 'sandbox' ? 'Sandbox draft' : 'Drafted by Claude' }} — read and change it before you send it.</span>
                          <p-button label="Copy" size="small" [outlined]="true" (onClick)="copyDraft()" /></div>
                      }
                    </div>
                  }
                  @if (!l.next_followup && l.status === 'open') { <p-message severity="warn" icon="pi pi-bell-slash" text="No follow-up scheduled for this lead." styleClass="mb" /> }
                  @for (f of followups(); track f.id) {
                    <div class="ms-row">
                      <i [class]="icon[f.channel] || 'pi pi-bell'" [class.c-bad]="f.overdue"></i>
                      <div class="grow"><strong [class.strike]="f.status !== 'open'">{{ f.title }}</strong>
                        <br /><small class="muted">{{ f.owner_name }} · {{ f.priority }}{{ f.outcome ? ' · ' + f.outcome : '' }}</small></div>
                      <small [class.c-bad]="f.overdue">{{ f.due | date: 'd MMM' }}</small>
                      @if (f.status === 'open') { <p-button icon="pi pi-check" [rounded]="true" [text]="true" severity="success" (onClick)="fd().openDone(f)" ariaLabel="Done" /> }
                      @else { <p-tag [value]="f.status" severity="secondary" /> }
                    </div>
                  } @empty { <p class="muted small">No follow-ups yet.</p> }
                </p-card>

                @if (l.bids?.length) {
                  <p-card>
                    <ng-template #title>Bids / tenders</ng-template>
                    @for (b of l.bids; track b.id) {
                      <div class="ms-row">
                        <i class="pi pi-briefcase"></i>
                        <div class="grow"><strong>{{ b.title }}</strong><br /><small class="muted">{{ b.reference || '' }} due {{ b.due_date | date: 'd MMM y' }}</small></div>
                        <p-tag [value]="b.decision === 'no_bid' ? 'Not bidding' : b.decision === 'pending' ? 'Awaiting decision' : b.status" [severity]="b.status === 'won' ? 'success' : b.status === 'lost' ? 'danger' : 'secondary'" />
                      </div>
                    }
                    <small class="muted">Recording a submitted bid as won or lost in the register closes this lead the same way.</small>
                  </p-card>
                }
              </div>

              <p-card>
                <ng-template #title><div class="row-between"><span>Details</span>
                  @if (l.status === 'open' && canEdit()) { <p-button label="Save" icon="pi pi-check" size="small" (onClick)="save()" /> }</div></ng-template>
                @if (form(); as f) {
                  <div class="stack">
                    <label class="field"><span>Title</span><input pInputText [(ngModel)]="f.title" [disabled]="ro()" fluid /></label>
                    <div class="field"><span>Enquirer</span>
                      <div>@if (auth.can('contacts')) { <a [routerLink]="['/app/contacts', l.contact_id]">{{ l.contact_name }}</a> } @else { {{ l.contact_name }} }</div></div>
                    <div class="grid3">
                      <div class="field"><span>Temperature</span><p-selectbutton [options]="temps" [(ngModel)]="f.temperature" optionLabel="label" optionValue="value" [disabled]="ro()" /></div>
                      <label class="field"><span title="Leave empty to use the stage default">Probability %</span><p-inputnumber [(ngModel)]="f.probability" [min]="0" [max]="100" [disabled]="ro()" fluid /></label>
                      <label class="field"><span>Expected close</span><input pInputText type="date" [(ngModel)]="f.expected_close" [disabled]="ro()" fluid /></label>
                    </div>
                    <div class="grid2">
                      <label class="field"><span>Service</span><p-select [options]="serviceOptions()" [(ngModel)]="f.service" optionLabel="label" optionValue="value" [disabled]="ro()" fluid /></label>
                      <label class="field"><span>Salesperson</span><p-select [options]="meta()?.staff ?? []" [(ngModel)]="f.owner_id" optionLabel="name" optionValue="id" [showClear]="true" [disabled]="ro()" fluid /></label>
                    </div>
                    <div class="grid2">
                      <label class="field"><span>Source</span><p-select [options]="meta()?.sources ?? []" [(ngModel)]="f.source" [disabled]="ro()" fluid /></label>
                      <label class="field"><span>Source detail</span><input pInputText [(ngModel)]="f.source_detail" [disabled]="ro()" fluid /></label>
                    </div>
                    @if (f.source === 'Referral') {
                      <label class="field"><span>Referred by</span><p-select [options]="contacts()" [(ngModel)]="f.referred_by" optionLabel="name" optionValue="id" [filter]="true" [disabled]="ro()" fluid /></label>
                    }
                    <div class="grid2">
                      <label class="field"><span>Project type</span><p-select [options]="meta()?.project_types ?? []" [(ngModel)]="f.project_type" [showClear]="true" [disabled]="ro()" fluid /></label>
                      <label class="field"><span>Timeline</span><p-select [options]="meta()?.timelines ?? []" [(ngModel)]="f.timeline" [showClear]="true" [disabled]="ro()" fluid /></label>
                    </div>
                    <label class="field"><span>Location</span><input pInputText [(ngModel)]="f.location" [disabled]="ro()" fluid /></label>
                    <div class="grid3">
                      <label class="field"><span>Budget</span><p-inputnumber [(ngModel)]="f.budget" [min]="0" [disabled]="ro()" fluid /></label>
                      <label class="field"><span>Area</span><p-inputnumber [(ngModel)]="f.area" [min]="0" [disabled]="ro()" fluid /></label>
                      <div class="field"><span>Unit</span><p-selectbutton [allowEmpty]="false" [options]="units" [(ngModel)]="f.area_unit" optionLabel="label" optionValue="value" [disabled]="ro()" /></div>
                    </div>
                    <div class="grid3">
                      <label class="field"><span>Preferred channel</span><p-select [options]="channelOptions()" [(ngModel)]="f.preferred_channel" optionLabel="label" optionValue="value" [showClear]="true" [disabled]="ro()" fluid /></label>
                      <label class="field"><span>Language</span><input pInputText [(ngModel)]="f.preferred_language" [disabled]="ro()" fluid /></label>
                      <label class="field"><span>Best time to call</span><input pInputText [(ngModel)]="f.best_time" [disabled]="ro()" fluid /></label>
                    </div>
                    <div class="grid2">
                      @if (meta()?.branches?.length) {
                        <label class="field"><span>Branch</span><p-select [options]="meta()?.branches ?? []" [(ngModel)]="f.branch" [showClear]="true" [disabled]="ro()" fluid /></label>
                      }
                      <label class="field"><span>Tags <small class="muted">(comma separated)</small></span><input pInputText [(ngModel)]="f.tags_text" [disabled]="ro()" fluid /></label>
                    </div>
                    <label class="field"><span>Notes</span><textarea pTextarea rows="3" [(ngModel)]="f.notes" [disabled]="ro()" fluid></textarea></label>
                    <small class="muted">Created {{ l.created_at | date: 'medium' }}{{ l.first_response_at ? ' · first response ' + (l.first_response_at | date: 'medium') : ' · not yet responded' }}</small>
                  </div>
                }
              </p-card>
            </div>
          </p-tabpanel>

          <p-tabpanel value="visits">@if (tab === 'visits') { <app-lead-visits [lead]="l" [staff]="meta()?.staff ?? []" (changed)="reload()" /> }</p-tabpanel>
          <p-tabpanel value="brief">@if (tab === 'brief') { <app-lead-brief [lead]="l" [contacts]="contacts()" (changed)="reload()" /> }</p-tabpanel>
          <p-tabpanel value="money">@if (tab === 'money') { <app-lead-money [lead]="l" (changed)="reload()" /> }</p-tabpanel>
          <p-tabpanel value="proposals">@if (tab === 'proposals') { <app-lead-proposals [lead]="l" (changed)="reload()" /> }</p-tabpanel>
          <p-tabpanel value="files">@if (tab === 'files') { <app-lead-files [lead]="l" (changed)="reload()" /> }</p-tabpanel>
          <p-tabpanel value="timeline">
            <div class="filters"><p-selectbutton [options]="groups" [ngModel]="group()" (onChange)="group.set($event.value ?? 'All')" [allowEmpty]="false" /></div>
            @for (a of timeline(); track a.id) {
              <div class="timeline-row"><i [class]="icon[a.type] || eventIcon[a.type] || 'pi pi-circle'"></i>
                <div class="grow"><div>{{ a.text }}</div>
                  @if (a.changes?.length) { <ul class="changes">@for (c of a.changes; track c.field) { <li><strong>{{ c.field }}</strong>: {{ c.from }} → {{ c.to }}</li> }</ul> }
                  <small class="muted">{{ chan[a.type] || label(a.type) }} · {{ a.by }} · {{ a.at | date: 'd MMM y, h:mm a' }}{{ a.outcome ? ' · ' + a.outcome : '' }}{{ a.duration_min ? ' · ' + a.duration_min + ' min' : '' }}{{ a.next_due ? ' · next ' + (a.next_due | date: 'd MMM') : '' }}</small></div></div>
            } @empty { <p class="muted small">Nothing here yet.</p> }
          </p-tabpanel>
        </p-tabpanels>
      </p-tabs>

      <p-dialog header="Use a message template" [modal]="true" [(visible)]="tplDlg" [style]="{ width: '36rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p-select [options]="templates()" [(ngModel)]="tplId" optionLabel="label" optionValue="id" placeholder="Choose template" (onChange)="render()" fluid appendTo="body" />
          @if (rendered(); as r) {
            @if (r.subject) { <strong>{{ r.subject }}</strong> }
            <textarea placeholder="The message text — edit it before you copy and send it" pTextarea rows="7" [(ngModel)]="r.text" fluid></textarea>
            @if (r.missing.length) { <p-message severity="warn" text="Fill in before sending: {{ r.missing.join(', ') }}" /> }
            <small class="muted">Sending through email / SMS / WhatsApp providers arrives in a later phase. Copy the text, send it, then log it.</small>
            <div class="row gap right">
              <p-button label="Copy" icon="pi pi-copy" [outlined]="true" (onClick)="copy(r.text)" />
              <p-button label="Log as sent" icon="pi pi-send" (onClick)="logTemplate()" />
            </div>
          }
        </div>
      </p-dialog>

      <p-dialog header="Put the lead on hold" [modal]="true" [(visible)]="holdDlg" [style]="{ width: '28rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p class="muted small">The lead leaves the active pipeline (it is not a loss) and comes back by itself on the resume date. The salesperson is told when it does.</p>
          <label class="field"><span>Why?</span><input pInputText [(ngModel)]="hf.reason" placeholder="e.g. client travelling, waiting for loan" fluid /></label>
          <label class="field"><span>Resume on</span><input pInputText type="date" [min]="tomorrow" [(ngModel)]="hf.resume_on" fluid /></label>
          <div class="row right"><p-button label="Put on hold" icon="pi pi-pause" (onClick)="hold()" [disabled]="!hf.reason?.trim() || !hf.resume_on" /></div>
        </div>
      </p-dialog>

      <p-dialog header="Move past unfinished steps?" [modal]="true" [(visible)]="ovDlg" [style]="{ width: '32rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p-message severity="warn" [text]="ovMsg" />
          @if (auth.user()?.role === 'owner') {
            <label class="field"><span>Reason for the override (logged)</span><input pInputText [(ngModel)]="ovReason" fluid /></label>
            <div class="row right"><p-button label="Move anyway" severity="warn" (onClick)="move(ovStage, ovReason)" [disabled]="!ovReason.trim()" /></div>
          } @else { <small class="muted">Finish these steps first, or ask the owner to override.</small> }
        </div>
      </p-dialog>
    }
    <app-followup-dialog (saved)="reload()" />
    <app-win-lose (done)="reload()" />
  `,
})
export class LeadDetailComponent implements OnInit {
  id = input.required<string>();
  auth = inject(AuthService);
  private api = inject(Api);
  private router = inject(Router);
  private toast = inject(MessageService);
  private confirm = inject(ConfirmationService);
  fd = viewChild.required(FollowupDialogComponent);
  wl = viewChild.required(WinLoseComponent);
  l = signal<any>(null);
  meta = signal<any>(null);
  form = signal<any>(null);
  followups = signal<any[]>([]);
  // Phase L block 3: a follow-up message drafted from the lead's facts (Claude, or a template when AI is off)
  draftDlg = false;
  drafting = false;
  draft: any = null;
  dr: any = { purpose: 'check_in', channel: 'whatsapp', instruction: '' };

  async makeDraft(l: any) {
    this.drafting = true;
    try {
      this.draft = await this.api.post(`/leads/${l.id}/ai/followup`, this.dr);
    } finally {
      this.drafting = false;
    }
  }

  copyDraft() {
    navigator.clipboard?.writeText((this.dr.channel === 'email' ? this.draft.subject + '\n\n' : '') + this.draft.body);
  }
  contacts = signal<any[]>([]);
  templates = signal<any[]>([]);
  rendered = signal<any>(null);
  canEdit = computed(() => this.auth.can('leads', 'rw'));
  ro = computed(() => !this.canEdit() || this.l()?.status !== 'open');
  stageIndex = computed(() => this.l()?.pipeline?.indexOf(this.l()?.stage) ?? 0);
  contact = computed(() => this.contacts().find((c) => c.id === this.l()?.contact_id));
  serviceOptions = computed(() => (this.meta()?.services ?? []).map((s: string) => ({ value: s, label: SERVICE_LABEL[s] })));
  activityTypes = computed(() => (this.meta()?.activity_types ?? []).map((v: string) => ({ value: v, label: CHANNEL_LABEL[v] })));
  channelOptions = computed(() => (this.meta()?.channels ?? []).map((v: string) => ({ value: v, label: CHANNEL_LABEL[v] || label(v) })));
  timeline = computed(() => {
    const all = [...(this.l()?.activities ?? [])].reverse();
    return this.group() === 'All' ? all : all.filter((a) => GROUPS[this.group()]?.includes(a.type));
  });
  svc = SERVICE_LABEL;
  color = SERVICE_COLOR;
  icon = CHANNEL_ICON;
  chan = CHANNEL_LABEL;
  eventIcon = EVENT_ICON;
  label = label;
  units = [{ label: 'sq ft', value: 'sqft' }, { label: 'm²', value: 'sqm' }];
  temps = [{ label: 'Hot', value: 'hot' }, { label: 'Warm', value: 'warm' }, { label: 'Cold', value: 'cold' }];
  groups = ['All', ...Object.keys(GROUPS)];
  group = signal('All');
  tab = 'overview';
  today = new Date().toISOString().slice(0, 10);
  tomorrow = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
  act: any = this.blankAct('call');
  tplDlg = false;
  tplId: string | null = null;
  holdDlg = false;
  hf: any = {};
  ovDlg = false;
  ovMsg = '';
  ovStage = '';
  ovReason = '';

  async ngOnInit() {
    this.meta.set(await this.api.get('/leads/meta'));
    if (this.auth.can('contacts')) this.contacts.set(await this.api.get('/contacts'));
    await this.reload();
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  /** WhatsApp needs the number with its country code; a 10-digit number is taken as Indian (+91), as the CRM's tax and currency are. */
  wa(phone: string) {
    const d = (phone || '').replace(/\D/g, '');
    return 'https://wa.me/' + (d.length === 10 ? '91' + d : d);
  }

  blankAct(type: string) {
    return { type, text: '', outcome: null as any, duration_min: null, next_due: '', next_title: '' };
  }

  needsNext() {
    return (this.act.type === 'call' || this.act.type === 'meeting') && this.act.outcome !== 'Wrong number';
  }

  canLog() {
    const a = this.act;
    if (!a.text?.trim()) return false;
    if (a.type === 'call' && !a.outcome) return false;
    if (a.type === 'meeting' && !a.outcome?.trim()) return false;
    return !this.needsNext() || !!a.next_due;
  }

  ticked(item: string) {
    return !!this.l()?.checklist?.[this.l().stage]?.[item];
  }

  tickedBy(item: string) {
    return this.l()?.checklist?.[this.l().stage]?.[item];
  }

  isMissing(req: string) {
    return (this.l()?.missing ?? []).includes(req);
  }

  async reload() {
    const l = await this.api.get(`/leads/${this.id()}`);
    this.l.set(l);
    this.form.set({ title: l.title, service: l.service, owner_id: l.owner_id, source: l.source, source_detail: l.source_detail,
      referred_by: l.referred_by, project_type: l.project_type, timeline: l.timeline, location: l.location, budget: l.budget,
      area: l.area, area_unit: l.area_unit ?? 'sqft', notes: l.notes, temperature: l.temperature ?? null, probability: l.probability ?? null,
      expected_close: l.expected_close ?? '', preferred_channel: l.preferred_channel ?? null, preferred_language: l.preferred_language ?? '',
      best_time: l.best_time ?? '', branch: l.branch ?? null, tags_text: (l.tags ?? []).join(', ') });
    const rid = l.status === 'won' && l.project_id ? l.project_id : l.id;
    if (this.auth.can('followups')) this.followups.set(await this.api.get(`/followups?related_id=${rid}`));
  }

  async save() {
    const { tags_text, ...f } = this.form();
    const body = { ...f, expected_close: f.expected_close || null, tags: (tags_text || '').split(',').map((x: string) => x.trim()).filter(Boolean) };
    await this.api.put(`/leads/${this.id()}`, body, 'Lead saved');
    await this.reload();
  }

  async tick(item: string, done: boolean) {
    await this.api.post(`/leads/${this.id()}/checklist`, { stage: this.l().stage, item, done });
    await this.reload();
  }

  async move(stage: string, override?: string) {
    if (stage === this.l().stage) return;
    try {
      await this.api.post(`/leads/${this.id()}/stage`, { stage, override_reason: override || undefined }, `Moved to ${stage}`);
      this.ovDlg = false;
    } catch (e) {
      const err = e as HttpErrorResponse;
      if (err.status === 409 && !override) {
        this.ovMsg = err.error?.error;
        this.ovStage = stage;
        this.ovReason = '';
        this.ovDlg = true;
      }
    }
    await this.reload();
  }

  async logActivity(templateId?: string) {
    const a = this.act;
    const body: any = { type: a.type, text: a.text, outcome: a.outcome || undefined, template_id: templateId };
    if (a.type === 'call' && a.duration_min) body.duration_min = a.duration_min;
    if (a.next_due) Object.assign(body, { next_due: a.next_due, next_title: a.next_title || undefined });
    await this.api.post(`/leads/${this.id()}/activities`, body, 'Logged');
    this.act = this.blankAct(a.type);
    await this.reload();
  }

  openHold() {
    this.hf = { reason: '', resume_on: '' };
    this.holdDlg = true;
  }

  async hold() {
    await this.api.post(`/leads/${this.id()}/hold`, this.hf, 'Lead on hold');
    this.holdDlg = false;
    await this.reload();
  }

  async resume() {
    await this.api.post(`/leads/${this.id()}/resume`, {}, 'Lead resumed');
    await this.reload();
  }

  reopen() {
    this.confirm.confirm({ header: 'Reopen this lead?', message: `It returns to ${this.l().lost_from_stage || 'the first stage'}.`, icon: 'pi pi-replay',
      acceptButtonProps: { label: 'Reopen' }, rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: async () => { await this.api.post(`/leads/${this.id()}/reopen`, {}, 'Lead reopened'); await this.reload(); } });
  }

  async openTemplates() {
    const t = await this.api.get('/message_templates');
    this.templates.set(t.map((x: any) => ({ ...x, label: `${CHANNEL_LABEL[x.channel]} · ${x.name}` })));
    this.tplId = null;
    this.rendered.set(null);
    this.tplDlg = true;
  }

  async render() {
    if (this.tplId) this.rendered.set(await this.api.post(`/message_templates/${this.tplId}/render`, { lead_id: this.id() }));
  }

  copy(text: string) {
    navigator.clipboard?.writeText(text).then(() => this.toast.add({ severity: 'success', summary: 'Copied', life: 1500 }));
  }

  async logTemplate() {
    const r = this.rendered();
    const ch = r.channel === 'sms' ? 'note' : r.channel;
    this.act = { ...this.blankAct(ch), text: `${r.channel.toUpperCase()} sent: ${r.text}` };
    await this.logActivity(this.tplId ?? undefined);
    this.tplDlg = false;
  }
}
