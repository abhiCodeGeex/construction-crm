import { Component, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { Api } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** Phase L block 2 — safety on a project: incidents (with investigation and corrective actions), inspections from
 *  checklists (a failed item becomes a snag), toolbox talks. */
@Component({
  selector: 'app-project-safety',
  imports: [FormsModule, DatePipe, ButtonModule, DialogModule, InputTextModule, MultiSelectModule, SelectModule, SelectButtonModule, TagModule],
  template: `
    <div class="row-between wrap gap mb">
      <p-selectbutton [options]="parts" [(ngModel)]="part" optionLabel="label" optionValue="value" [allowEmpty]="false" />
      @if (canWrite()) {
        <span class="row gap">
          @if (part === 'incidents') { <p-button label="Report an incident" icon="pi pi-exclamation-triangle" size="small" severity="danger" (onClick)="openInc()" /> }
          @if (part === 'inspections') { <p-button label="New inspection" icon="pi pi-check-square" size="small" (onClick)="openInsp()" /> }
          @if (part === 'talks') { <p-button label="Record a toolbox talk" icon="pi pi-megaphone" size="small" (onClick)="openTalk()" /> }
        </span>
      }
    </div>

    @if (part === 'incidents') {
      @for (i of incidents(); track i.id) {
        <div class="box" [class.serious]="i.serious">
          <div class="row-between wrap gap">
            <div><strong>{{ i.number }} · {{ i.kind_label }}</strong> <p-tag [value]="i.severity" [severity]="sevOf(i.severity)" />
              <p-tag [value]="i.status" [severity]="i.status === 'closed' ? 'success' : 'warn'" styleClass="ml-xs" />
              <div class="small muted">{{ i.date }} {{ i.time || '' }} @if (i.location) { · {{ i.location }} } · reported by {{ i.reported_by }}
                @if (i.lost_days) { · {{ i.lost_days }} lost day(s) }</div></div>
            @if (canManage()) {
              <span class="row gap">
                @if (i.status !== 'closed') {
                  <p-button label="Investigate" size="small" [text]="true" (onClick)="openInv(i)" />
                  <p-button label="Add action" size="small" [text]="true" (onClick)="openAct(i)" />
                  <p-button label="Close" size="small" [text]="true" (onClick)="close(i)" />
                } @else { <p-button label="Reopen" size="small" [text]="true" (onClick)="reopen(i)" /> }
              </span>
            }
          </div>
          <div class="pre">{{ i.description }}</div>
          @for (x of i.people; track $index) { <div class="small">• {{ x.name }}@if (x.injury) { — {{ x.injury }} }</div> }
          @if (i.immediate_action) { <div class="small"><strong>Done at once:</strong> {{ i.immediate_action }}</div> }
          @for (ph of i.photos; track ph.key) { <a [href]="ph.url" target="_blank" rel="noopener"><img class="thumb" [src]="ph.url" [alt]="ph.name" /></a> }
          @if (i.investigation) { <div class="small"><strong>Root cause:</strong> {{ i.root_cause }} — {{ i.investigation.findings }} ({{ i.investigation.by }})</div> }
          @for (a of i.actions; track a.id) {
            <div class="row gap small action" [class.c-bad]="a.overdue">
              <i class="pi" [class.pi-check-circle]="a.done_at" [class.pi-circle]="!a.done_at"></i>
              <span class="grow">{{ a.text }} — {{ a.owner_name }}, by {{ a.due }} @if (a.done_at) { · done by {{ a.done_by }} {{ a.done_note ? '(' + a.done_note + ')' : '' }} }</span>
              @if (!a.done_at && (a.owner_id === me || canManage())) { <p-button label="Done" size="small" [text]="true" (onClick)="actionDone(i, a)" /> }
            </div>
          }
        </div>
      } @empty { <p class="muted">No incidents on this project. Report near misses too — they are how accidents are prevented.</p> }
    }

    @if (part === 'inspections') {
      @for (x of inspections(); track x.id) {
        <div class="box">
          <div class="row-between wrap gap">
            <div><strong>{{ x.number }} · {{ x.template_name }}</strong> <p-tag [value]="x.score + '%'" [severity]="x.score >= 90 ? 'success' : x.score >= 70 ? 'warn' : 'danger'" />
              <div class="small muted">{{ x.date }} · by {{ x.by }} · {{ x.passed }} passed, {{ x.failed }} failed @if (x.critical_failed) { · <span class="c-bad">{{ x.critical_failed }} critical</span> }</div></div>
          </div>
          @for (r of x.results; track r.item_id) {
            @if (r.result === 'fail') { <div class="small c-bad">✗ {{ r.text }} — {{ r.note }} @if (r.snag_number) { → snag {{ r.snag_number }} }</div> }
          }
        </div>
      } @empty { <p class="muted">No inspections yet.</p> }
    }

    @if (part === 'talks') {
      @for (x of talks(); track x.id) {
        <div class="box"><strong>{{ x.date }} · {{ x.topic }}</strong> <span class="small muted">· {{ x.count }} attended · by {{ x.by }}</span>
          <div class="small">{{ names(x.attendees) }}</div>@if (x.notes) { <div class="small pre">{{ x.notes }}</div> }</div>
      } @empty { <p class="muted">No toolbox talks recorded.</p> }
    }

    <p-dialog header="Report an incident" [modal]="true" [(visible)]="incDlg" [style]="{ width: '36rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="row gap wrap">
          <p-select [options]="meta().kinds" [(ngModel)]="inc.kind" optionLabel="label" optionValue="value" placeholder="What kind" ariaLabel="Kind" />
          <p-select [options]="meta().severities" [(ngModel)]="inc.severity" placeholder="Severity" ariaLabel="Severity" [showClear]="true" />
          <input pInputText type="date" [(ngModel)]="inc.date" [max]="today" aria-label="Date" />
          <input pInputText type="time" [(ngModel)]="inc.time" aria-label="Time" />
        </div>
        <input pInputText [(ngModel)]="inc.location" placeholder="Where (floor, room, area)" aria-label="Location" />
        <textarea class="p-inputtext" rows="3" [(ngModel)]="inc.description" placeholder="What happened" aria-label="What happened"></textarea>
        <label class="small">Who was involved</label>
        @for (x of inc.people; track $index) {
          <div class="row gap"><input pInputText class="grow" [(ngModel)]="x.name" placeholder="Name" aria-label="Name" />
            <input pInputText class="grow" [(ngModel)]="x.injury" placeholder="Injury (if any)" aria-label="Injury" />
            <p-button icon="pi pi-times" [text]="true" size="small" ariaLabel="Remove" (onClick)="inc.people.splice($index, 1)" /></div>
        }
        <div class="row gap"><p-select [options]="meta().people" [(ngModel)]="pick" optionLabel="name" placeholder="Add from the site list" ariaLabel="Person" [filter]="true" styleClass="grow" />
          <p-button label="Add" size="small" [text]="true" (onClick)="addPerson()" /></div>
        @if (inc.kind === 'lost_time') { <input pInputText type="number" min="0" [(ngModel)]="inc.lost_days" placeholder="Days lost" aria-label="Days lost" /> }
        <textarea class="p-inputtext" rows="2" [(ngModel)]="inc.immediate_action" placeholder="What was done at once" aria-label="Immediate action"></textarea>
        <input pInputText [(ngModel)]="inc.witnesses" placeholder="Witnesses" aria-label="Witnesses" />
        <label class="small">Photos <input type="file" accept="image/*" capture="environment" multiple (change)="photos($event, inc.photos)" /></label>
        <span class="small muted">{{ inc.photos.length }} photo(s)</span>
        <div class="row right"><p-button label="Report" severity="danger" [disabled]="!inc.kind || !inc.description?.trim()" (onClick)="saveInc()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Investigation" [modal]="true" [(visible)]="invDlg" [style]="{ width: '32rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <p-select [options]="meta().root_causes" [(ngModel)]="inv.root_cause" placeholder="Root cause" ariaLabel="Root cause" />
        <textarea class="p-inputtext" rows="4" [(ngModel)]="inv.findings" placeholder="What the investigation found" aria-label="Findings"></textarea>
        <input pInputText [(ngModel)]="inv.factors" placeholder="What else contributed" aria-label="Factors" />
        <div class="row right"><p-button label="Save" [disabled]="!inv.root_cause || !inv.findings?.trim()" (onClick)="saveInv()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Corrective action" [modal]="true" [(visible)]="actDlg" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <input pInputText [(ngModel)]="act.text" placeholder="What must be done" aria-label="Action" />
        <p-select [options]="meta().team" [(ngModel)]="act.owner_id" optionLabel="name" optionValue="id" placeholder="Who does it" ariaLabel="Owner" />
        <input pInputText type="date" [(ngModel)]="act.due" aria-label="Due" />
        <div class="row right"><p-button label="Add" [disabled]="!act.text?.trim() || !act.owner_id" (onClick)="saveAct()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Inspection" [modal]="true" [(visible)]="inspDlg" [style]="{ width: '40rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="row gap wrap"><p-select [options]="templates()" [(ngModel)]="insp.template" optionLabel="name" placeholder="Checklist" ariaLabel="Checklist" (onChange)="pickTemplate()" />
          <input pInputText type="date" [(ngModel)]="insp.date" [max]="today" aria-label="Date" /></div>
        @for (r of insp.results; track r.item_id) {
          <div class="item">
            <div class="row-between gap"><span>{{ r.text }} @if (r.critical) { <p-tag value="critical" severity="danger" /> }</span>
              <p-selectbutton [options]="resultOpts" [(ngModel)]="r.result" optionLabel="label" optionValue="value" [allowEmpty]="false" /></div>
            @if (r.result === 'fail') { <input pInputText class="w100" [(ngModel)]="r.note" placeholder="What is wrong" aria-label="What is wrong" /> }
          </div>
        }
        <textarea class="p-inputtext" rows="2" [(ngModel)]="insp.notes" placeholder="Notes" aria-label="Notes"></textarea>
        <div class="row right"><span class="small muted grow">Failed items become snags to fix and close.</span>
          <p-button label="Save" [disabled]="!inspReady()" (onClick)="saveInsp()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Toolbox talk" [modal]="true" [(visible)]="talkDlg" [style]="{ width: '32rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <input pInputText [(ngModel)]="talk.topic" placeholder="Topic (e.g. working at height)" aria-label="Topic" />
        <input pInputText type="date" [(ngModel)]="talk.date" [max]="today" aria-label="Date" />
        <p-multiselect [options]="meta().people" [(ngModel)]="talk.attendees" optionLabel="name" optionValue="person" placeholder="Who attended" [filter]="true" ariaLabel="Attendees" />
        <textarea class="p-inputtext" rows="2" [(ngModel)]="talk.notes" placeholder="Notes" aria-label="Notes"></textarea>
        <div class="row right"><p-button label="Save" [disabled]="!talk.topic?.trim() || !talk.attendees.length" (onClick)="saveTalk()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.box { border: 1px solid var(--border); border-radius: 10px; padding: .6rem .8rem; margin-bottom: .6rem; display: grid; gap: .3rem; }
    .box.serious { border-left: 4px solid #dc2626; } .thumb { height: 64px; border-radius: 6px; margin-right: .3rem; }
    .item { border-bottom: 1px solid var(--border); padding: .35rem 0; display: grid; gap: .3rem; } .w100 { width: 100%; } .pre { white-space: pre-wrap; }`,
})
export class ProjectSafetyComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  auth = inject(AuthService);
  me = this.auth.user()?.id;
  today = new Date().toISOString().slice(0, 10);
  parts = [{ label: 'Incidents', value: 'incidents' }, { label: 'Inspections', value: 'inspections' }, { label: 'Toolbox talks', value: 'talks' }];
  resultOpts = [{ label: 'Pass', value: 'pass' }, { label: 'Fail', value: 'fail' }, { label: 'N/A', value: 'na' }];
  part = 'incidents';
  incidents = signal<any[]>([]);
  inspections = signal<any[]>([]);
  talks = signal<any[]>([]);
  templates = signal<any[]>([]);
  meta = signal<any>({ kinds: [], severities: [], root_causes: [], people: [], team: [] });
  canWrite = signal(false);
  canManage = signal(false);
  incDlg = false; invDlg = false; actDlg = false; inspDlg = false; talkDlg = false;
  inc: any = { people: [], photos: [] };
  inv: any = {};
  act: any = {};
  insp: any = { results: [] };
  talk: any = { attendees: [] };
  pick: any = null;
  cur: any = null;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const pid = this.projectId();
    const [i, s, t] = await Promise.all([this.api.get(`/projects/${pid}/incidents`), this.api.get(`/projects/${pid}/inspections`), this.api.get(`/projects/${pid}/toolbox-talks`)]);
    this.incidents.set(i.incidents);
    this.meta.set(i);
    this.canWrite.set(i.can_write);
    this.canManage.set(i.can_manage);
    this.inspections.set(s.inspections);
    this.templates.set(s.templates);
    this.talks.set(t);
  }

  sevOf(s: string) {
    return ({ low: 'info', medium: 'warn', high: 'danger', critical: 'danger' } as any)[s] || 'secondary';
  }

  names(a: any[]) {
    return a.map((x) => x.name).join(', ');
  }

  openInc() {
    this.inc = { kind: null, severity: null, date: this.today, time: new Date().toTimeString().slice(0, 5), people: [], photos: [] };
    this.incDlg = true;
  }

  addPerson() {
    if (this.pick) this.inc.people.push({ name: this.pick.name, person: this.pick.person, injury: '' });
    this.pick = null;
  }

  async photos(ev: Event, into: string[]) {
    for (const f of Array.from((ev.target as HTMLInputElement).files ?? [])) into.push((await this.api.upload(f)).key);
  }

  async saveInc() {
    await this.api.post(`/projects/${this.projectId()}/incidents`, { ...this.inc, people: this.inc.people.filter((x: any) => x.name?.trim()) }, 'Incident reported');
    this.incDlg = false;
    await this.load();
  }

  openInv(i: any) {
    this.cur = i;
    this.inv = { root_cause: i.root_cause, findings: i.investigation?.findings || '', factors: i.factors || '' };
    this.invDlg = true;
  }

  async saveInv() {
    await this.api.post(`/incidents/${this.cur.id}/investigate`, this.inv, 'Saved');
    this.invDlg = false;
    await this.load();
  }

  openAct(i: any) {
    this.cur = i;
    this.act = { text: '', owner_id: null, due: '' };
    this.actDlg = true;
  }

  async saveAct() {
    await this.api.post(`/incidents/${this.cur.id}/actions`, this.act, 'Action added');
    this.actDlg = false;
    await this.load();
  }

  async actionDone(i: any, a: any) {
    const note = prompt('What was done?') ?? '';
    await this.api.post(`/incidents/${i.id}/actions/${a.id}/done`, { note }, 'Done');
    await this.load();
  }

  async close(i: any) {
    await this.api.post(`/incidents/${i.id}/close`, { note: prompt('Closing note (optional)') || '' }, 'Closed');
    await this.load();
  }

  async reopen(i: any) {
    const reason = prompt('Why reopen?');
    if (!reason?.trim()) return;
    await this.api.post(`/incidents/${i.id}/reopen`, { reason }, 'Reopened');
    await this.load();
  }

  openInsp() {
    this.insp = { template: this.templates()[0] ?? null, date: this.today, notes: '', results: [] };
    this.pickTemplate();
    this.inspDlg = true;
  }

  pickTemplate() {
    this.insp.results = (this.insp.template?.items ?? []).map((it: any) => ({ item_id: it.id, text: it.text, critical: it.critical, result: 'pass', note: '' }));
  }

  inspReady() {
    return this.insp.template && this.insp.results.every((r: any) => r.result !== 'fail' || r.note?.trim());
  }

  async saveInsp() {
    const x = await this.api.post(`/projects/${this.projectId()}/inspections`, { template_id: this.insp.template.id, date: this.insp.date, notes: this.insp.notes,
      results: this.insp.results.map((r: any) => ({ item_id: r.item_id, result: r.result, note: r.note })) });
    this.api.post; // keeps the toast below specific
    this.inspDlg = false;
    alert(`${x.number}: ${x.score}%` + (x.failed ? ` — ${x.failed} item(s) became snags` : ''));
    await this.load();
  }

  openTalk() {
    this.talk = { topic: '', date: this.today, attendees: [], notes: '' };
    this.talkDlg = true;
  }

  async saveTalk() {
    await this.api.post(`/projects/${this.projectId()}/toolbox-talks`, this.talk, 'Saved');
    this.talkDlg = false;
    await this.load();
  }
}
