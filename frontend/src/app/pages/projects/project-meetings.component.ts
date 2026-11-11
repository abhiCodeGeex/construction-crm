import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ConfirmationService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { TooltipModule } from 'primeng/tooltip';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** Meetings and minutes (B+4). Plan it -> attendees are told and reminded 2 hours before. After the meeting write
 *  the minutes -> Publish: each action becomes a task (owner, stage, due date) and the minutes are emailed. */
@Component({
  selector: 'app-project-meetings',
  imports: [TooltipModule, FormsModule, DatePipe, ButtonModule, CardModule, DialogModule, InputTextModule, MultiSelectModule, SelectModule, TagModule, TextareaModule],
  template: `
    <div class="row-between mb">
      <span class="muted small">Plan a meeting → attendees are told (and reminded 2 hours before). Afterwards write the minutes and publish: every action becomes a task and the minutes are emailed to every attendee.</span>
      @if (canEdit()) { <p-button label="Plan a meeting" icon="pi pi-calendar-plus" size="small" (onClick)="openNew()" /> }
    </div>
    @for (m of meetings(); track m.id) {
      <p-card styleClass="mb">
        <div class="row-between">
          <div><strong>{{ m.title }}</strong> <p-tag [value]="m.status === 'published' ? 'Minutes published' : 'Planned'" [severity]="m.status === 'published' ? 'success' : 'info'" />
            <div class="small muted">{{ m.at | date: 'EEE d MMM y, h:mm a' }}{{ m.place ? ' · ' + m.place : '' }}</div>
            <div class="small">With: {{ attendees(m) || '—' }}</div></div>
          <div class="row gap">
            @if (canEdit() && m.status !== 'published') {
              <p-button label="Edit" icon="pi pi-calendar" size="small" [text]="true" (onClick)="openEdit(m)" />
              <p-button label="Minutes" icon="pi pi-pencil" size="small" [text]="true" (onClick)="openMinutes(m)" />
              <p-button label="Publish" icon="pi pi-send" size="small" (onClick)="publish(m)" />
            }
            @if (canEdit() && (m.status !== 'published' || isOwner())) { <p-button icon="pi pi-trash" size="small" [text]="true" severity="danger" (onClick)="remove(m)" ariaLabel="Delete" pTooltip="Delete"/> }
          </div>
        </div>
        @if (m.agenda) { <div class="small mt-xs"><b>Agenda:</b> <span class="pre">{{ m.agenda }}</span></div> }
        @if (m.notes) { <div class="small mt-xs"><b>Notes:</b> <span class="pre">{{ m.notes }}</span></div> }
        @if (m.decisions?.length) { <div class="small mt-xs"><b>Decisions</b>@for (x of m.decisions; track $index) { <div>• {{ x }}</div> }</div> }
        @if (m.actions?.length) {
          <div class="small mt-xs"><b>Actions</b>
            @for (a of m.actions; track a.id) { <div>• {{ a.text }} — {{ owner(a.owner_id) }} · {{ stageName(a.stage_id) }} · by {{ a.due ? (a.due | date: 'd MMM y') : '—' }} @if (a.task_id) { <p-tag value="task created" severity="success" /> }</div> }</div>
        }
        @if (m.status === 'published') {
          <div class="small muted mt-xs">Published {{ m.published_at | date: 'd MMM y, h:mm a' }} by {{ m.published_by }} ·
            emailed: @for (e of emailed(m); track e.to) { <span [class.c-bad]="e.result !== 'sent'">{{ e.to }} ({{ e.result }}) </span> } @empty { nobody had an email address }</div>
        }
      </p-card>
    } @empty { <p class="muted">No meetings yet.</p> }

    <p-dialog [header]="f.id ? 'Edit meeting' : 'Plan a meeting'" [modal]="true" [(visible)]="planDlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '96vw' }">
      <form class="stack" (ngSubmit)="savePlan()">
        <label class="field req"><span>Title</span><input pInputText name="t" [(ngModel)]="f.title" fluid /></label>
        <div class="grid2">
          <label class="field req"><span>Date and time</span><input pInputText type="datetime-local" name="a" [(ngModel)]="f.at" fluid /></label>
          <label class="field"><span>Place or link</span><input pInputText name="pl" [(ngModel)]="f.place" fluid /></label>
        </div>
        <label class="field"><span>Our team</span><p-multiselect name="s" [options]="staff()" [(ngModel)]="f.staff" optionLabel="name" optionValue="user_id" display="chip" fluid appendTo="body" /></label>
        <label class="field"><span>Client, consultants, vendors <small class="muted">(contacts)</small></span>
          <p-multiselect name="c" [options]="contacts()" [(ngModel)]="f.contacts" optionLabel="name" optionValue="id" [filter]="true" display="chip" fluid appendTo="body" /></label>
        <label class="field"><span>Agenda</span><textarea pTextarea name="ag" rows="3" [(ngModel)]="f.agenda" fluid></textarea></label>
        <div class="row right"><p-button type="submit" label="Save" icon="pi pi-check" [disabled]="!f.title || !f.at" /></div>
      </form>
    </p-dialog>

    <p-dialog header="Minutes" [modal]="true" [(visible)]="minDlg" [style]="{ width: '46rem' }" [breakpoints]="{ '760px': '98vw' }">
      <div class="stack">
        <label class="field"><span>Notes — what was discussed</span><textarea pTextarea rows="4" [(ngModel)]="mf.notes" fluid></textarea></label>
        <div class="field"><span>Decisions</span>
          @for (x of mf.decisions; track $index; let i = $index) {
            <div class="row gap mb-xs"><input placeholder="Decision" pInputText [(ngModel)]="mf.decisions[i]" class="grow" /><p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="mf.decisions.splice(i, 1)" ariaLabel="Remove" pTooltip="Remove"/></div>
          }
          <p-button label="Add decision" icon="pi pi-plus" size="small" [text]="true" (onClick)="mf.decisions.push('')" /></div>
        <div class="field"><span>Actions <small class="muted">— each becomes a task on publish (owner, stage and due date needed)</small></span>
          @for (a of mf.actions; track a.id; let i = $index) {
            <div class="action-row">
              <input pInputText [(ngModel)]="a.text" placeholder="What needs doing" class="grow" />
              <p-select [options]="staff()" [(ngModel)]="a.owner_id" optionLabel="name" optionValue="user_id" placeholder="Owner" appendTo="body" />
              <p-select [options]="stageOpts()" [(ngModel)]="a.stage_id" optionLabel="name" optionValue="id" placeholder="Stage" appendTo="body" />
              <input aria-label="Due date" title="Due date" pInputText type="date" [(ngModel)]="a.due" />
              <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="mf.actions.splice(i, 1)" ariaLabel="Remove" pTooltip="Remove"/>
            </div>
          }
          <p-button label="Add action" icon="pi pi-plus" size="small" [text]="true" (onClick)="addAction()" /></div>
        <div class="row gap right"><p-button label="Save minutes" icon="pi pi-check" (onClick)="saveMinutes()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .pre { white-space: pre-wrap; }
    .action-row { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr) 9.5rem auto; gap: .4rem; margin-bottom: .4rem; align-items: center; }
    @media (max-width: 760px) { .action-row { grid-template-columns: 1fr 1fr; } }
  `,
})
export class ProjectMeetingsComponent implements OnInit {
  project = input.required<any>();
  contacts = input<any[]>([]);
  changed = output<void>();
  private api = inject(Api);
  private confirm = inject(ConfirmationService);
  private auth = inject(AuthService);
  meetings = signal<any[]>([]);
  planDlg = false;
  minDlg = false;
  f: any = {};
  mf: any = { decisions: [], actions: [] };
  private editing: any = null;

  canEdit = computed(() => this.project()?.my_access === 'edit');
  staff = computed(() => (this.project()?.team ?? []).filter((m: any) => m.user_id));
  stageOpts = computed(() => (this.project()?.stages ?? []).map((s: any) => ({ id: s.id, name: s.name })));

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.meetings.set(await this.api.get(`/projects/${this.project().id}/meetings`));
  }

  isOwner() {
    return this.auth.user()?.role === 'owner'; // published minutes: only the Owner may delete them
  }

  attendees(m: any) {
    return [...m.staff.map((s: any) => s.name), ...m.contacts.map((c: any) => c.name)].join(', ');
  }

  owner(id: string) {
    return this.staff().find((m: any) => m.user_id === id)?.name ?? 'no owner';
  }

  stageName(id: string) {
    return this.stageOpts().find((s: any) => s.id === id)?.name ?? 'no stage';
  }

  emailed(m: any) {
    return Object.entries(m.emailed ?? {}).map(([to, result]) => ({ to, result }));
  }

  openNew() {
    const d = new Date(Date.now() + 86400000);
    d.setHours(10, 0, 0, 0);
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    this.f = { title: '', at: local, place: '', staff: [], contacts: [], agenda: '' };
    this.planDlg = true;
  }

  openEdit(m: any) {
    const d = new Date(m.at);
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    this.f = { id: m.id, title: m.title, at: local, place: m.place ?? '', agenda: m.agenda ?? '',
      staff: (m.staff ?? []).map((s: any) => s.user_id), contacts: (m.contacts ?? []).map((c: any) => c.contact_id) };
    this.planDlg = true;
  }

  async savePlan() {
    // the browser's local time goes to the server in UTC (shown back in local time)
    const { id, ...body } = this.f;
    body.at = new Date(this.f.at).toISOString();
    if (id) await this.api.put(`/projects/${this.project().id}/meetings/${id}`, body, 'Meeting updated');
    else await this.api.post(`/projects/${this.project().id}/meetings`, body, 'Meeting planned — attendees told');
    this.planDlg = false;
    await this.load();
    this.changed.emit();
  }

  openMinutes(m: any) {
    this.editing = m;
    this.mf = { notes: m.notes ?? '', decisions: [...(m.decisions ?? [])], actions: (m.actions ?? []).map((a: any) => ({ ...a })) };
    this.minDlg = true;
  }

  addAction() {
    this.mf.actions.push({ id: Math.random().toString(36).slice(2, 12), text: '', owner_id: null, stage_id: null, due: null });
  }

  async saveMinutes() {
    await this.api.put(`/projects/${this.project().id}/meetings/${this.editing.id}`, {
      notes: this.mf.notes, decisions: this.mf.decisions.filter((x: string) => x.trim()),
      actions: this.mf.actions.filter((a: any) => a.text?.trim()) }, 'Minutes saved');
    this.minDlg = false;
    await this.load();
  }

  publish(m: any) {
    this.confirm.confirm({ header: 'Publish the minutes?', icon: 'pi pi-send',
      message: `${m.actions?.length ?? 0} action(s) become tasks and the minutes are emailed to every attendee with an email address. Published minutes cannot be changed.`,
      acceptButtonProps: { label: 'Publish' }, rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: async () => {
        await this.api.post(`/projects/${this.project().id}/meetings/${m.id}/publish`, {}, 'Minutes published');
        await this.load();
        this.changed.emit();
      } });
  }

  remove(m: any) {
    this.confirm.confirm({ header: `Delete ${m.title}?`, icon: 'pi pi-trash', message: 'Tasks already created from it stay.',
      acceptButtonProps: { label: 'Delete', severity: 'danger' }, rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: async () => {
        await this.api.del(`/projects/${this.project().id}/meetings/${m.id}`, 'Meeting deleted');
        await this.load();
      } });
  }
}
