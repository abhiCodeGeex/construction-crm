import { Component, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Phase K blocks 4 and 6 — automatic follow-up sequences, and the call log (IVR and calls logged by hand). */
@Component({
  selector: 'app-automation',
  imports: [FormsModule, DatePipe, DecimalPipe, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, SelectButtonModule, TagModule, ToggleSwitchModule],
  template: `
    <div class="page">
      <div class="row-between wrap gap mb"><h1 class="m0">Automation & calls</h1>
        <p-selectbutton [options]="parts" [(ngModel)]="part" optionLabel="label" optionValue="value" [allowEmpty]="false" (ngModelChange)="load()" /></div>
      @if (part === 'seq' && d(); as d) {
        <div class="row-between wrap gap mb"><span class="small muted">A sequence starts for each new matching record and stops when the client replies or the record moves on (accepted, paid, won…).</span>
          @if (canEdit) { <span class="row gap"><p-select [options]="d.presets" optionLabel="name" [(ngModel)]="preset" placeholder="Start from a preset" appendTo="body" (onChange)="open(preset)" />
            <p-button label="New sequence" icon="pi pi-plus" size="small" (onClick)="open()" /></span> }</div>
        @for (s of d.sequences; track s.id) {
          <div class="card-row">
            <div class="row-between wrap gap"><span><strong>{{ s.name }}</strong> · {{ d.triggers[s.trigger] }} <p-tag [value]="s.active ? 'on' : 'off'" [severity]="s.active ? 'success' : 'secondary'" />
              <span class="small muted"> · {{ s.running }} running, {{ s.finished }} finished</span></span>
              @if (canEdit) { <span class="row gap"><p-button label="Runs" size="small" [text]="true" (onClick)="showRuns(s)" /><p-button label="Edit" size="small" [text]="true" (onClick)="open(s)" />
                <p-button icon="pi pi-trash" size="small" [text]="true" severity="secondary" (onClick)="del(s)" ariaLabel="Delete sequence" /></span> }</div>
            <div class="small">@for (st of s.steps; track $index) { <span class="chip">+{{ st.wait_days }}d · {{ st.action === 'message' ? st.template : st.action === 'task' ? 'task: ' + st.title : 'notify ' + st.role }}</span> }</div>
          </div>
        } @empty { <p class="muted">No sequences yet — start from a preset.</p> }
      }
      @if (part === 'calls') {
        <div class="row gap mb"><p-button label="Log a call" icon="pi pi-phone" size="small" (onClick)="callDlg = true; cf = { contact_id: null, direction: 'out', duration: null, note: '' }" /></div>
        <table class="t"><tr><th>When</th><th>Who</th><th>Direction</th><th>Option</th><th>Taken by</th><th>Status</th><th>Duration</th></tr>
          @for (c of calls(); track c.id) {
            <tr><td>{{ c.created_at | date: 'd MMM HH:mm' }}</td><td>{{ c.contact_name || c.from }}</td><td>{{ c.direction === 'in' ? 'In' : 'Out' }}</td><td>{{ c.option || '—' }}</td>
              <td>{{ c.routed_name || '—' }}</td><td><p-tag [value]="c.status" [severity]="c.status === 'missed' ? 'danger' : 'success'" /></td>
              <td>{{ c.duration ? (c.duration / 60 | number: '1.0-1') + ' min' : '—' }} @if (c.recording_url) { <a [href]="c.recording_url" target="_blank" rel="noopener">recording</a> }</td></tr>
          } @empty { <tr><td colspan="7" class="muted">No calls yet.</td></tr> }
        </table>
      }
    </div>
    <p-dialog [header]="f.id ? 'Edit sequence' : 'New sequence'" [modal]="true" [(visible)]="dlg" [style]="{ width: '44rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="grid2"><label class="field req"><span>Name</span><input pInputText [(ngModel)]="f.name" fluid /></label>
          <label class="field req"><span>Starts when</span><p-select [options]="triggerOpts()" optionLabel="label" optionValue="value" [(ngModel)]="f.trigger" fluid appendTo="body" /></label>
          @if (f.trigger === 'lead_cold') { <label class="field"><span>Cold after (days without activity)</span><p-inputnumber [(ngModel)]="f.cold_days" [min]="3" fluid /></label> }</div>
        <div class="row gap wrap"><label class="check"><p-toggleswitch [(ngModel)]="f.active" ariaLabel="On" /> On</label>
          <label class="check"><p-checkbox [(ngModel)]="f.stop_on_reply" [binary]="true" ariaLabel="Stop on reply" /> Stop when the client replies</label>
          <label class="check"><p-checkbox [(ngModel)]="f.stop_on_change" [binary]="true" ariaLabel="Stop on change" /> Stop when the record moves on</label></div>
        @for (st of f.steps; track $index; let i = $index) {
          <div class="step"><span class="small">Step {{ i + 1 }} — wait</span><p-inputnumber [(ngModel)]="st.wait_days" [min]="0" [max]="400" ariaLabel="Days to wait" /><span class="small">days, then</span>
            <p-select [options]="actions" [(ngModel)]="st.action" appendTo="body" ariaLabel="Action" />
            @switch (st.action) {
              @case ('message') { <p-select [options]="d()?.templates ?? []" optionLabel="name" optionValue="name" [(ngModel)]="st.template" placeholder="Template" appendTo="body" ariaLabel="Template" /> }
              @case ('task') { <input pInputText [(ngModel)]="st.title" [placeholder]="taskHint" class="grow" aria-label="Task title" /> }
              @default { <p-select [options]="roles" [(ngModel)]="st.role" appendTo="body" ariaLabel="Who" /><input pInputText [(ngModel)]="st.text" placeholder="Notification" class="grow" aria-label="Notification" /> }
            }
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.steps.splice(i, 1)" ariaLabel="Remove step" /></div>
        }
        <p-button label="Add a step" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.steps.push({ wait_days: 1, action: 'task', title: '' })" />
        <p class="small muted m0">{{ mergeHelp }}</p>
        <div class="row right"><p-button label="Save" [disabled]="!f.name?.trim() || !f.trigger || !f.steps.length" (onClick)="save()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Runs" [modal]="true" [(visible)]="runsDlg" [style]="{ width: '40rem' }">
      @for (r of runs(); track r.id) {
        <div class="card-row"><div class="row-between"><span><strong>{{ r.label }}</strong> · step {{ r.step }} · <p-tag [value]="r.status" /> @if (r.reason) { <span class="small muted">{{ r.reason }}</span> }</span>
          @if (r.status === 'running') { <p-button label="Stop" size="small" [text]="true" (onClick)="stopRun(r)" /> }</div>
          <div class="small muted">@for (l of r.log; track $index) { step {{ l.step }}: {{ l.result }}@if (!$last) { · } } @if (r.next_at) { · next {{ r.next_at | date: 'd MMM' }} }</div></div>
      } @empty { <p class="muted">No runs yet.</p> }
    </p-dialog>
    <p-dialog header="Log a call" [modal]="true" [(visible)]="callDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>Contact</span><p-select [options]="contacts()" optionLabel="name" optionValue="id" [(ngModel)]="cf.contact_id" [filter]="true" fluid appendTo="body" /></label>
        <div class="grid2"><label class="field"><span>Direction</span><p-select [options]="[{ l: 'Outgoing', v: 'out' }, { l: 'Incoming', v: 'in' }]" optionLabel="l" optionValue="v" [(ngModel)]="cf.direction" fluid appendTo="body" /></label>
          <label class="field"><span>Minutes</span><p-inputnumber [(ngModel)]="cf.minutes" [min]="0" fluid /></label></div>
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="cf.note" fluid /></label>
        <div class="row right"><p-button label="Save" [disabled]="!cf.contact_id" (onClick)="saveCall()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.card-row { border: 1px solid var(--border); border-radius: 8px; padding: .5rem .7rem; margin-bottom: .5rem; background: var(--surface); display: grid; gap: .25rem; }
    .chip { display: inline-block; border: 1px solid var(--border); border-radius: 99px; padding: 0 .5rem; margin: .1rem; }
    .step { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; border: 1px dashed var(--border); border-radius: 8px; padding: .4rem; }
    .t { width: 100%; border-collapse: collapse; font-size: .88rem; } .t td, .t th { border-bottom: 1px solid var(--border); padding: .35rem .4rem; text-align: left; }`,
})
export class AutomationComponent {
  private api = inject(Api);
  private auth = inject(AuthService);
  canEdit = ['owner', 'pm'].includes(this.auth.user()?.role ?? '') || !!(this.auth.user() as any)?.is_sales_manager;
  parts = [{ label: 'Follow-up sequences', value: 'seq' }, { label: 'Calls', value: 'calls' }];
  part = 'seq';
  actions = ['message', 'task', 'notify'];
  roles = ['record_owner', 'owner', 'pm', 'sales', 'accounts', 'designer', 'site', 'procurement'];
  d = signal<any>(null);
  runs = signal<any[]>([]);
  calls = signal<any[]>([]);
  contacts = signal<any[]>([]);
  dlg = false; runsDlg = false; callDlg = false;
  f: any = { steps: [] };
  cf: any = {};
  preset: any = null;
  taskHint = 'Task, e.g. Call {{client}}';
  mergeHelp = 'Merge fields: {{client}}, {{project}}, {{company}}, {{salesperson}}.';

  triggerOpts = () => Object.entries(this.d()?.triggers ?? {}).map(([value, label]) => ({ value, label }));

  async ngOnInit() {
    await this.load();
  }

  async load() {
    if (this.part === 'seq') this.d.set(await this.api.get('/sequences'));
    else {
      this.calls.set(await this.api.get('/calls'));
      this.contacts.set(await this.api.get('/contacts').then((r: any) => (Array.isArray(r) ? r : r.items ?? [])));
    }
  }

  open(s?: any) {
    this.f = s ? { id: s.id, name: s.name, trigger: s.trigger, cold_days: s.cold_days ?? 14, active: s.active ?? true, stop_on_reply: s.stop_on_reply ?? true,
        stop_on_change: s.stop_on_change ?? true, steps: s.steps.map((x: any) => ({ ...x })) }
      : { name: '', trigger: 'lead_new', cold_days: 14, active: true, stop_on_reply: true, stop_on_change: true, steps: [{ wait_days: 1, action: 'task', title: '' }] };
    this.preset = null;
    this.dlg = true;
  }

  async save() {
    const { id, ...body } = this.f;
    if (id) await this.api.put(`/sequences/${id}`, body, 'Saved');
    else await this.api.post('/sequences', body, 'Sequence on');
    this.dlg = false;
    await this.load();
  }

  async del(s: any) {
    if (!confirm(`Delete ${s.name}? Running follow-ups stop.`)) return;
    await this.api.del(`/sequences/${s.id}`, 'Deleted');
    await this.load();
  }

  async showRuns(s: any) {
    this.runs.set(await this.api.get(`/sequences/runs?sequence_id=${s.id}`));
    this.runsDlg = true;
  }

  async stopRun(r: any) {
    await this.api.post(`/sequences/runs/${r.id}/stop`, {}, 'Stopped');
    this.runs.set(await this.api.get(`/sequences/runs?sequence_id=${r.sequence_id}`));
  }

  async saveCall() {
    const { minutes, ...body } = this.cf;
    await this.api.post('/calls', { ...body, duration: minutes ? Math.round(minutes * 60) : null }, 'Call logged');
    this.callDlg = false;
    await this.load();
  }
}
