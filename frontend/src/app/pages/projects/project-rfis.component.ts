import { Component, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { Api } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** Phase K block 2 — RFIs (questions to the designer / architect / consultant) and submittals (shop drawings, samples). */
@Component({
  selector: 'app-project-rfis',
  imports: [FormsModule, DatePipe, ButtonModule, CheckboxModule, DialogModule, InputTextModule, MultiSelectModule, SelectModule, SelectButtonModule, TagModule],
  template: `
    <div class="row-between wrap gap mb">
      <p-selectbutton [options]="parts" [(ngModel)]="part" optionLabel="label" optionValue="value" [allowEmpty]="false" />
      @if (part === 'rfis') { <p-button label="New RFI" icon="pi pi-plus" size="small" (onClick)="openRfi()" /> }
      @else { <p-button label="New submittal" icon="pi pi-plus" size="small" (onClick)="openSub()" /> }
    </div>
    @if (part === 'rfis') {
      @for (r of rfis(); track r.id) {
        <div class="card-row" [class.late]="r.overdue">
          <div class="row-between wrap gap">
            <div><strong>{{ r.number }} · {{ r.subject }}</strong> <p-tag [value]="r.status" [severity]="r.status === 'open' ? (r.overdue ? 'danger' : 'warn') : 'success'" />
              @if (r.priority === 'high' || r.priority === 'urgent') { <p-tag [value]="r.priority" severity="danger" styleClass="ml-xs" /> }
              <div class="small muted">from {{ r.raised_by }} → {{ r.to_name }} · answer by {{ r.due_date }} @if (r.document_name) { · {{ r.document_name }} } @if (r.co_number) { · {{ r.co_number }} drafted }</div></div>
            <span class="row gap">
              @if (r.status === 'open' && (r.to_user_id === me || isManager)) { <p-button label="Answer" size="small" (onClick)="openAnswer(r)" /> }
              @if (r.status === 'answered') { <p-button label="Close" size="small" [text]="true" (onClick)="act(r, 'close')" /> <p-button label="Reopen" size="small" [text]="true" (onClick)="reopen(r)" /> }
            </span>
          </div>
          <div class="pre">{{ r.question }}</div>
          @for (f of r.files; track f.key) { <a class="small" [href]="f.url" target="_blank" rel="noopener"><i class="pi pi-paperclip"></i> {{ f.name }}</a> }
          @if (r.answer) { <div class="answer"><strong>{{ r.answer.by }}:</strong> {{ r.answer.text }}
            @if (r.answer.cost_impact || r.answer.time_impact) { <span class="small c-bad"> · {{ r.answer.cost_impact ? 'cost' : '' }} {{ r.answer.time_impact ? 'time' : '' }} impact</span> }</div> }
        </div>
      } @empty { <p class="muted">No RFIs on this project.</p> }
    } @else {
      @for (s of subs(); track s.id) {
        <div class="card-row" [class.late]="s.overdue">
          <div class="row-between wrap gap">
            <div><strong>{{ s.number }} · {{ s.title }}</strong> <span class="small muted">{{ s.kind }}</span> <p-tag [value]="decisions[s.status] || s.status" [severity]="sev(s.status)" />
              <div class="small muted">by {{ s.submitted_by }} · reviewer {{ s.reviewer_name }} · rev {{ s.current?.rev }} · review by {{ s.due_date }} @if (s.subcontract_title) { · {{ s.subcontract_title }} }</div></div>
            @if (s.status === 'submitted' && (s.reviewer_id === me || auth.user()?.role === 'owner')) { <p-button label="Review" size="small" (onClick)="openReview(s)" /> }
          </div>
          @for (v of s.revisions; track v.rev) {
            <div class="small">Rev {{ v.rev }} · {{ v.submitted_at | date: 'd MMM' }} @for (f of v.files; track f.key) { · <a [href]="f.url" target="_blank" rel="noopener">{{ f.name }}</a> }
              @if (v.decision) { → <strong>{{ decisions[v.decision] }}</strong>@if (v.review_note) { : {{ v.review_note }} } }</div>
          }
        </div>
      } @empty { <p class="muted">No submittals on this project.</p> }
    }

    <p-dialog header="New RFI" [modal]="true" [(visible)]="rDlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <label class="field req"><span>Subject</span><input pInputText [(ngModel)]="rf.subject" fluid /></label>
        <label class="field req"><span>Question</span><textarea class="p-inputtext" rows="4" [(ngModel)]="rf.question"></textarea></label>
        <div class="grid2">
          <label class="field"><span>Who answers</span><p-select [options]="answerers()" optionLabel="name" optionValue="key" [(ngModel)]="rf.to" [showClear]="true" placeholder="The architect / designer" fluid appendTo="body" /></label>
          <label class="field"><span>Priority</span><p-select [options]="['low', 'normal', 'high', 'urgent']" [(ngModel)]="rf.priority" fluid appendTo="body" /></label>
          <label class="field"><span>Answer by</span><input pInputText type="date" [(ngModel)]="rf.due_date" fluid /></label>
          <label class="field"><span>About the drawing</span><p-select [options]="docs()" optionLabel="name" optionValue="id" [(ngModel)]="rf.document_id" [showClear]="true" fluid appendTo="body" /></label>
        </div>
        <label class="field"><span>Photos / files</span><input type="file" multiple (change)="attach($event, rf.files)" /></label>
        <div class="row right"><p-button label="Send" [disabled]="!rf.subject?.trim() || !rf.question?.trim()" (onClick)="saveRfi()" /></div>
      </div>
    </p-dialog>
    <p-dialog [header]="'Answer ' + (target?.number || '')" [modal]="true" [(visible)]="aDlg" [style]="{ width: '34rem' }">
      <div class="stack">
        <p class="m0 small">{{ target?.question }}</p>
        <label class="field req"><span>Answer</span><textarea class="p-inputtext" rows="4" [(ngModel)]="af.text"></textarea></label>
        <label class="check"><p-checkbox [(ngModel)]="af.cost_impact" [binary]="true" ariaLabel="Cost impact" /> Changes the cost (makes a change request)</label>
        <label class="check"><p-checkbox [(ngModel)]="af.time_impact" [binary]="true" ariaLabel="Time impact" /> Changes the programme</label>
        <label class="field"><span>Also send the answer to</span><p-multiselect [options]="contacts()" optionLabel="name" optionValue="contact_id" [(ngModel)]="af.distribution" display="chip" fluid appendTo="body" /></label>
        <label class="field"><span>Sketch / files</span><input type="file" multiple (change)="attach($event, af.files)" /></label>
        <div class="row right"><p-button label="Send answer" [disabled]="!af.text?.trim()" (onClick)="saveAnswer()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="New submittal" [modal]="true" [(visible)]="sDlg" [style]="{ width: '32rem' }">
      <div class="stack">
        <label class="field req"><span>Title</span><input pInputText [(ngModel)]="sf.title" fluid /></label>
        <div class="grid2">
          <label class="field req"><span>Kind</span><p-select [options]="kinds" [(ngModel)]="sf.kind" fluid appendTo="body" /></label>
          <label class="field"><span>Spec section</span><input pInputText [(ngModel)]="sf.spec_section" fluid /></label>
        </div>
        <label class="field req"><span>Files</span><input type="file" multiple (change)="attach($event, sf.files)" /></label>
        <div class="row right"><p-button label="Submit" [disabled]="!sf.title?.trim() || !sf.kind || !sf.files.length" (onClick)="saveSub()" /></div>
      </div>
    </p-dialog>
    <p-dialog [header]="'Review ' + (target?.number || '')" [modal]="true" [(visible)]="vDlg" [style]="{ width: '30rem' }">
      <div class="stack">
        <label class="field req"><span>Decision</span><p-select [options]="decisionOpts" optionLabel="label" optionValue="value" [(ngModel)]="vf.decision" fluid appendTo="body" /></label>
        <label class="field" [class.req]="vf.decision !== 'approved'"><span>Comments</span><textarea class="p-inputtext" rows="3" [(ngModel)]="vf.note"></textarea></label>
        <label class="field"><span>Marked-up files</span><input type="file" multiple (change)="attach($event, vf.files)" /></label>
        <div class="row right"><p-button label="Save review" [disabled]="!vf.decision || (vf.decision !== 'approved' && !vf.note?.trim())" (onClick)="saveReview()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.card-row { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .9rem; margin-bottom: .6rem; background: var(--surface); display: grid; gap: .3rem; }
    .card-row.late { border-left: 3px solid #c0392b; } .pre { white-space: pre-wrap; } .answer { background: var(--surface-2, #f6f6f6); padding: .4rem .6rem; border-radius: 6px; }`,
})
export class ProjectRfisComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  auth = inject(AuthService);
  me = this.auth.user()?.id;
  isManager = ['owner', 'pm'].includes(this.auth.user()?.role ?? '');
  parts = [{ label: 'RFIs', value: 'rfis' }, { label: 'Submittals', value: 'subs' }];
  part = 'rfis';
  kinds = ['Shop drawing', 'Sample', 'Data sheet', 'Method statement', 'Test certificate', 'Other'];
  decisions: Record<string, string> = { submitted: 'Waiting for review', approved: 'Approved', approved_as_noted: 'Approved as noted', revise_resubmit: 'Revise and resubmit', rejected: 'Rejected' };
  decisionOpts = ['approved', 'approved_as_noted', 'revise_resubmit', 'rejected'].map((v) => ({ value: v, label: this.decisions[v] }));
  rfis = signal<any[]>([]);
  subs = signal<any[]>([]);
  answerers = signal<any[]>([]);
  contacts = signal<any[]>([]);
  docs = signal<any[]>([]);
  rDlg = false; aDlg = false; sDlg = false; vDlg = false;
  rf: any = {}; af: any = {}; sf: any = {}; vf: any = {};
  target: any = null;
  sev = (s: string) => (s === 'approved' || s === 'approved_as_noted' ? 'success' : s === 'submitted' ? 'info' : s === 'rejected' ? 'danger' : 'warn');

  async ngOnInit() {
    await this.load();
    const p = await this.api.get(`/projects/${this.projectId()}`);
    this.answerers.set(p.team.filter((m: any) => m.kind !== 'external' || ['Architect', 'Consultant', 'Structural Consultant', 'MEP Consultant', 'Interior Designer'].includes(m.project_role))
      .map((m: any) => ({ key: m.user_id ? 'u:' + m.user_id : 'c:' + m.contact_id, name: `${m.name} (${m.project_role})` })));
    this.contacts.set(p.team.filter((m: any) => m.contact_id).map((m: any) => ({ contact_id: m.contact_id, name: `${m.name} (${m.project_role})` })));
    const d = await this.api.get(`/projects/${this.projectId()}/documents`).catch(() => ({ documents: [] }));
    this.docs.set((d.documents ?? []).map((x: any) => ({ id: x.id, name: x.number ? `${x.number} ${x.name}` : x.name })));
  }

  async load() {
    const [r, s] = await Promise.all([this.api.get(`/projects/${this.projectId()}/rfis`), this.api.get(`/projects/${this.projectId()}/submittals`)]);
    this.rfis.set(r);
    this.subs.set(s);
  }

  async attach(ev: Event, into: string[]) {
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) into.push((await this.api.upload(file)).key);
  }

  openRfi() {
    this.rf = { subject: '', question: '', to: null, priority: 'normal', due_date: null, document_id: null, files: [] };
    this.rDlg = true;
  }

  async saveRfi() {
    const { to, ...body } = this.rf;
    if (to) body[to.startsWith('u:') ? 'to_user_id' : 'to_contact_id'] = to.slice(2);
    await this.api.post(`/projects/${this.projectId()}/rfis`, body, 'RFI sent');
    this.rDlg = false;
    await this.load();
  }

  openAnswer(r: any) {
    this.target = r;
    this.af = { text: '', cost_impact: false, time_impact: false, distribution: [], files: [] };
    this.aDlg = true;
  }

  async saveAnswer() {
    await this.api.post(`/rfis/${this.target.id}/answer`, this.af, 'Answer sent');
    this.aDlg = false;
    await this.load();
  }

  async act(r: any, what: string) {
    await this.api.post(`/rfis/${r.id}/${what}`, {}, 'Saved');
    await this.load();
  }

  async reopen(r: any) {
    const reason = prompt('Why is the answer not enough?');
    if (!reason?.trim()) return;
    await this.api.post(`/rfis/${r.id}/reopen`, { reason }, 'Reopened');
    await this.load();
  }

  openSub() {
    this.sf = { title: '', kind: 'Shop drawing', spec_section: '', files: [] };
    this.sDlg = true;
  }

  async saveSub() {
    await this.api.post(`/projects/${this.projectId()}/submittals`, this.sf, 'Submitted for review');
    this.sDlg = false;
    await this.load();
  }

  openReview(s: any) {
    this.target = s;
    this.vf = { decision: null, note: '', files: [] };
    this.vDlg = true;
  }

  async saveReview() {
    await this.api.post(`/submittals/${this.target.id}/review`, this.vf, 'Review saved');
    this.vDlg = false;
    await this.load();
  }
}
