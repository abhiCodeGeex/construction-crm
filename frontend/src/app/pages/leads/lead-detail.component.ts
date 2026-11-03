import { Component, OnInit, computed, inject, input, signal, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, SERVICE_COLOR, SERVICE_LABEL, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { CHANNEL_ICON, CHANNEL_LABEL, FollowupDialogComponent } from '../../shared/followup-dialog.component';
import { WinLoseComponent } from './win-lose.component';

@Component({
  selector: 'app-lead-detail',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, CardModule, DialogModule, InputNumberModule, InputTextModule, MessageModule,
    SelectButtonModule, SelectModule, TagModule, TextareaModule, FollowupDialogComponent, WinLoseComponent],
  template: `
    @if (l(); as l) {
      <div class="page-head">
        <div>
          <a routerLink="/app/leads" class="small"><i class="pi pi-arrow-left"></i> Pipeline</a>
          <h1>{{ l.title }}</h1>
          <div class="row gap">
            <span class="svc" [style.--c]="color[l.service]">{{ svc[l.service] }}</span>
            @switch (l.status) {
              @case ('won') { <p-tag value="Won" severity="success" icon="pi pi-trophy" /> <a [routerLink]="['/app/projects', l.project_id]">Project {{ l.project_code }} →</a> }
              @case ('lost') { <p-tag value="Lost" severity="danger" /> <span class="muted">{{ l.loss_reason }}{{ l.loss_note ? ' — ' + l.loss_note : '' }}</span> }
              @default { <p-tag [value]="l.stage" severity="info" /> }
            }
            <span class="muted"><i class="pi pi-user"></i> {{ l.owner_name || 'Unassigned' }}</span>
          </div>
        </div>
        @if (canEdit()) {
          <div class="row gap">
            @if (l.status === 'open') {
              <p-button label="Lost" icon="pi pi-times" severity="danger" [outlined]="true" (onClick)="wl().open('lost', l, meta())" />
              <p-button label="Won" icon="pi pi-trophy" severity="success" (onClick)="wl().open('won', l, meta())" />
            } @else if (l.status === 'lost') {
              <p-button label="Reopen" icon="pi pi-replay" [outlined]="true" (onClick)="reopen()" />
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
      }

      <div class="grid2 top">
        <div class="stack">
          <p-card>
            <ng-template #title><div class="row-between"><span>Follow-ups</span>
              @if (l.status === 'open' && auth.can('followups', 'rw')) { <p-button label="Add" icon="pi pi-plus" size="small" [text]="true" (onClick)="fd().open({ type: 'lead', id: l.id, label: l.title })" /> }</div></ng-template>
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

          <p-card>
            <ng-template #title>Activity log</ng-template>
            @if (l.status === 'open' && canEdit()) {
              <div class="stack mb">
                <p-selectbutton [options]="activityTypes()" [(ngModel)]="act.type" optionLabel="label" optionValue="value" />
                <textarea pTextarea rows="2" [(ngModel)]="act.text" placeholder="What happened? Call notes, meeting minutes, WhatsApp summary…" fluid></textarea>
                <div class="row gap">
                  <input pInputText [(ngModel)]="act.outcome" placeholder="Outcome (optional)" class="grow" />
                  <p-button label="Use template" icon="pi pi-file" [text]="true" (onClick)="openTemplates()" />
                  <p-button label="Log" icon="pi pi-send" (onClick)="logActivity()" [disabled]="!act.text?.trim()" />
                </div>
              </div>
            }
            @for (a of activities(); track a.id) {
              <div class="timeline-row"><i [class]="icon[a.type] || 'pi pi-circle'"></i>
                <div class="grow"><div>{{ a.text }}</div>
                  <small class="muted">{{ label[a.type] || a.type }} · {{ a.by }} · {{ a.at | date: 'd MMM, h:mm a' }}{{ a.outcome ? ' · ' + a.outcome : '' }}</small></div></div>
            } @empty { <p class="muted small">Nothing logged yet.</p> }
          </p-card>
        </div>

        <p-card>
          <ng-template #title><div class="row-between"><span>Details</span>
            @if (l.status === 'open' && canEdit()) { <p-button label="Save" icon="pi pi-check" size="small" (onClick)="save()" /> }</div></ng-template>
          @if (form(); as f) {
            <div class="stack">
              <label class="field"><span>Title</span><input pInputText [(ngModel)]="f.title" [disabled]="ro()" fluid /></label>
              <div class="field"><span>Enquirer</span>
                <div>@if (auth.can('contacts')) { <a [routerLink]="['/app/contacts', l.contact_id]">{{ l.contact_name }}</a> } @else { {{ l.contact_name }} }</div></div>
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
                <div class="field"><span>Unit</span><p-selectbutton [options]="units" [(ngModel)]="f.area_unit" optionLabel="label" optionValue="value" [disabled]="ro()" /></div>
              </div>
              <label class="field"><span>Notes</span><textarea pTextarea rows="3" [(ngModel)]="f.notes" [disabled]="ro()" fluid></textarea></label>
              <small class="muted">Created {{ l.created_at | date: 'medium' }}{{ l.first_response_at ? ' · first response ' + (l.first_response_at | date: 'medium') : ' · not yet responded' }}</small>
            </div>
          }
        </p-card>
      </div>

      <p-dialog header="Use a message template" [modal]="true" [(visible)]="tplDlg" [style]="{ width: '36rem' }">
        <div class="stack">
          <p-select [options]="templates()" [(ngModel)]="tplId" optionLabel="label" optionValue="id" placeholder="Choose template" (onChange)="render()" fluid appendTo="body" />
          @if (rendered(); as r) {
            @if (r.subject) { <strong>{{ r.subject }}</strong> }
            <textarea pTextarea rows="7" [(ngModel)]="r.text" fluid></textarea>
            @if (r.missing.length) { <p-message severity="warn" text="Fill in before sending: {{ r.missing.join(', ') }}" /> }
            <small class="muted">Sending through email / SMS / WhatsApp providers arrives in a later phase. Copy the text, send it, then log it.</small>
            <div class="row gap right">
              <p-button label="Copy" icon="pi pi-copy" [outlined]="true" (onClick)="copy(r.text)" />
              <p-button label="Log as sent" icon="pi pi-send" (onClick)="logTemplate()" />
            </div>
          }
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
  contacts = signal<any[]>([]);
  templates = signal<any[]>([]);
  rendered = signal<any>(null);
  canEdit = computed(() => this.auth.can('leads', 'rw'));
  ro = computed(() => !this.canEdit() || this.l()?.status !== 'open');
  stageIndex = computed(() => this.l()?.pipeline?.indexOf(this.l()?.stage) ?? 0);
  activities = computed(() => [...(this.l()?.activities ?? [])].reverse());
  serviceOptions = computed(() => (this.meta()?.services ?? []).map((s: string) => ({ value: s, label: SERVICE_LABEL[s] })));
  activityTypes = computed(() => (this.meta()?.activity_types ?? []).map((v: string) => ({ value: v, label: CHANNEL_LABEL[v] })));
  svc = SERVICE_LABEL;
  color = SERVICE_COLOR;
  icon = CHANNEL_ICON;
  label = CHANNEL_LABEL;
  units = [{ label: 'sq ft', value: 'sqft' }, { label: 'm²', value: 'sqm' }];
  act: any = { type: 'call', text: '', outcome: '' };
  tplDlg = false;
  tplId: string | null = null;

  async ngOnInit() {
    this.meta.set(await this.api.get('/leads/meta'));
    if (this.auth.can('contacts')) this.contacts.set(await this.api.get('/contacts'));
    await this.reload();
  }

  async reload() {
    const l = await this.api.get(`/leads/${this.id()}`);
    this.l.set(l);
    this.form.set({ title: l.title, service: l.service, owner_id: l.owner_id, source: l.source, source_detail: l.source_detail,
      referred_by: l.referred_by, project_type: l.project_type, timeline: l.timeline, location: l.location, budget: l.budget,
      area: l.area, area_unit: l.area_unit ?? 'sqft', notes: l.notes });
    const rid = l.status === 'won' ? l.project_id : l.id;
    if (this.auth.can('followups')) this.followups.set(await this.api.get(`/followups?related_id=${rid}`));
  }

  async save() {
    await this.api.put(`/leads/${this.id()}`, this.form(), 'Lead saved');
    await this.reload();
  }

  async move(stage: string) {
    if (stage === this.l().stage) return;
    await this.api.post(`/leads/${this.id()}/stage`, { stage }, `Moved to ${stage}`);
    await this.reload();
  }

  async logActivity(templateId?: string) {
    await this.api.post(`/leads/${this.id()}/activities`, { ...this.act, template_id: templateId }, 'Logged');
    this.act = { type: this.act.type, text: '', outcome: '' };
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
    this.act = { type: ch, text: `${r.channel.toUpperCase()} sent: ${r.text}`, outcome: '' };
    await this.logActivity(this.tplId ?? undefined);
    this.tplDlg = false;
  }
}
