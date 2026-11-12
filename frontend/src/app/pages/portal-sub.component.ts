import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { Api, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { ModelViewerComponent } from '../core/model-viewer.component';

/** Phase K block 1 in the portal — a subcontractor prices work packages, sees the award and the certificates. */
@Component({
  selector: 'app-portal-subcontracts',
  imports: [FormsModule, ButtonModule, DialogModule, InputNumberModule],
  template: `
    @if (rows().length) {
      <h3>Work packages</h3>
      @for (s of rows(); track s.id) {
        <div class="box">
          <div class="row-between wrap gap"><strong>{{ s.title }}</strong><span class="small">{{ s.project_name }} · {{ s.status === 'bidding' ? 'open for your price' + (s.due_date ? ' until ' + s.due_date : '') : s.awarded_to_me ? 'awarded to you' : s.status }}</span></div>
          @if (s.scope) { <div class="small">{{ s.scope }}</div> }
          @if (s.my_bid) { <div class="small">Your price: {{ fmt(s.my_bid.total) }} @if (s.my_bid.days) { · {{ s.my_bid.days }} days } </div> }
          @if (s.status === 'bidding') { <span class="row gap"><p-button [label]="s.my_bid ? 'Change my price' : 'Send my price'" size="small" (onClick)="open(s)" />
            <p-button label="Not interested" size="small" [text]="true" (onClick)="decline(s)" /></span> }
          @if (s.award) { <div class="small">Agreement {{ s.award.agreement_no }} · {{ fmt(s.award.total) }} · retention {{ s.award.retention_pct }}% @if (s.award.start) { · {{ s.award.start }} → {{ s.award.end }} }</div> }
          @for (c of s.certificates; track c.number) { <div class="small">{{ c.kind === 'release' ? 'Retention release' : 'Certificate ' + c.number }} · {{ c.date }} · {{ fmt(c.net) }} payable · paid {{ fmt(c.paid) }}</div> }
        </div>
      }
    }
    <p-dialog [header]="'Your price — ' + (cur?.title || '')" [modal]="true" [(visible)]="dlg" [style]="{ width: '34rem' }">
      <div class="stack">
        @for (l of cur?.lines ?? []; track l.id) { <div class="row gap"><span class="grow small">{{ l.description }} — {{ l.qty }} {{ l.unit }}</span>
          <p-inputnumber [(ngModel)]="rates[l.id]" [min]="0" placeholder="Rate" [ariaLabel]="'Rate for ' + l.description" /></div> }
        <p-inputnumber [(ngModel)]="days" [min]="1" placeholder="Days to complete" ariaLabel="Days" />
        <textarea class="p-inputtext" rows="2" [(ngModel)]="note" placeholder="Notes (what is included)" aria-label="Notes"></textarea>
        <div class="row right"><p-button label="Send" [disabled]="!allPriced()" (onClick)="send()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.box { border: 1px solid var(--border); border-radius: 10px; padding: .6rem .8rem; margin-bottom: .6rem; display: grid; gap: .3rem; }`,
})
export class PortalSubcontractsComponent {
  currency = input('INR');
  private api = inject(Api);
  rows = signal<any[]>([]);
  dlg = false;
  cur: any = null;
  rates: Record<string, number | null> = {};
  days: number | null = null;
  note = '';

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.rows.set(await this.api.get('/portal/subcontracts').catch(() => []));
  }

  fmt(v: number) {
    return money(v, this.currency());
  }

  allPriced = () => (this.cur?.lines ?? []).every((l: any) => this.rates[l.id] !== null && this.rates[l.id] !== undefined);

  open(s: any) {
    this.cur = s;
    this.rates = Object.fromEntries(s.lines.map((l: any) => [l.id, s.my_bid?.lines.find((x: any) => x.line_id === l.id)?.rate ?? null]));
    this.days = s.my_bid?.days ?? null;
    this.note = s.my_bid?.note ?? '';
    this.dlg = true;
  }

  async send() {
    await this.api.post(`/portal/subcontracts/${this.cur.id}/bid`, { lines: Object.entries(this.rates).map(([line_id, rate]) => ({ line_id, rate })), days: this.days, note: this.note }, 'Price sent');
    this.dlg = false;
    await this.load();
  }

  async decline(s: any) {
    await this.api.post(`/portal/subcontracts/${s.id}/decline`, {}, 'Noted');
    await this.load();
  }
}

/** Phase K blocks 2 and 7 in the portal — RFIs and submittals (subcontractors, suppliers and consultants) and the
 *  shared 3D models (everyone on the project, the client included). */
@Component({
  selector: 'app-portal-project-extras',
  imports: [FormsModule, ButtonModule, DialogModule, ModelViewerComponent],
  template: `
    @if (models().length) {
      <h4>3D models</h4>
      <div class="row gap wrap mb">@for (m of models(); track m.id) { <button type="button" class="p-button p-button-sm" [class.p-button-outlined]="cur()?.id !== m.id" (click)="cur.set(m)">{{ m.title }}</button> }</div>
      @if (cur(); as m) { <app-model-viewer [model]="m" [canComment]="true" (spot)="at = $event; text = ''; cDlg = true" />
        @for (c of m.comments; track c.id; let i = $index) { <div class="small"><strong>{{ i + 1 }}. {{ c.author }}:</strong> {{ c.text }}</div> } }
    }
    @if (isTrade) {
      <div class="row-between"><h4>Questions (RFIs)</h4><p-button label="Ask the designer" size="small" [text]="true" (onClick)="rf = { subject: '', question: '' }; rDlg = true" /></div>
      @for (r of rfis(); track r.id) {
        <div class="small box"><strong>{{ r.number }} · {{ r.subject }}</strong> — {{ r.status }}<div>{{ r.question }}</div>
          @if (r.answer) { <div><strong>{{ r.answer.by }}:</strong> {{ r.answer.text }}</div> }
          @if (r.status === 'open' && r.to_contact_id === me) { <p-button label="Answer" size="small" [text]="true" (onClick)="answer(r)" /> }</div>
      } @empty { <p class="small muted">No questions.</p> }
      <div class="row-between"><h4>Submittals</h4><p-button label="Send a submittal" size="small" [text]="true" (onClick)="sf = { title: '', kind: 'Shop drawing', files: [] }; sDlg = true" /></div>
      @for (s of subs(); track s.id) {
        <div class="small box"><strong>{{ s.number }} · {{ s.title }}</strong> ({{ s.kind }}) — rev {{ s.current?.rev }}: {{ s.status.replaceAll('_', ' ') }}
          @if (s.current?.review_note) { <div>{{ s.current.reviewed_by }}: {{ s.current.review_note }}</div> }
          @if (s.status === 'revise_resubmit') { <label class="small">Revised files <input type="file" multiple (change)="resubmit(s, $event)" /></label> }</div>
      } @empty { <p class="small muted">No submittals.</p> }
    }
    <p-dialog header="Comment on this point" [modal]="true" [(visible)]="cDlg" [style]="{ width: '26rem' }">
      <div class="stack"><textarea class="p-inputtext" rows="3" [(ngModel)]="text" aria-label="Comment"></textarea>
        <div class="row right"><p-button label="Send to the team" [disabled]="!text.trim()" (onClick)="comment()" /></div></div>
    </p-dialog>
    <p-dialog header="Ask the designer" [modal]="true" [(visible)]="rDlg" [style]="{ width: '30rem' }">
      <div class="stack"><input class="p-inputtext" [(ngModel)]="rf.subject" placeholder="Subject" aria-label="Subject" />
        <textarea class="p-inputtext" rows="4" [(ngModel)]="rf.question" placeholder="Question" aria-label="Question"></textarea>
        <div class="row right"><p-button label="Send" [disabled]="!rf.subject?.trim() || !rf.question?.trim()" (onClick)="ask()" /></div></div>
    </p-dialog>
    <p-dialog header="Send a submittal" [modal]="true" [(visible)]="sDlg" [style]="{ width: '30rem' }">
      <div class="stack"><input class="p-inputtext" [(ngModel)]="sf.title" placeholder="Title" aria-label="Title" />
        <select class="p-inputtext" [(ngModel)]="sf.kind" aria-label="Kind">@for (k of kinds; track k) { <option [value]="k">{{ k }}</option> }</select>
        <input type="file" multiple (change)="attach($event)" aria-label="Files" /><span class="small muted">{{ sf.files.length }} file(s)</span>
        <div class="row right"><p-button label="Send" [disabled]="!sf.title?.trim() || !sf.files.length" (onClick)="submit()" /></div></div>
    </p-dialog>
  `,
  styles: `.box { border: 1px solid var(--border); border-radius: 8px; padding: .4rem .6rem; margin-bottom: .4rem; }`,
})
export class PortalProjectExtrasComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  private auth = inject(AuthService);
  me = (this.auth.user() as any)?.contact_id;
  isTrade = ['subcontractor', 'consultant', 'vendor'].includes(this.auth.user()?.role ?? '');
  kinds = ['Shop drawing', 'Sample', 'Data sheet', 'Method statement', 'Test certificate', 'Other'];
  models = signal<any[]>([]);
  cur = signal<any>(null);
  rfis = signal<any[]>([]);
  subs = signal<any[]>([]);
  cDlg = false; rDlg = false; sDlg = false;
  at: any = null;
  text = '';
  rf: any = {};
  sf: any = { files: [] };

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const pid = this.projectId();
    const m = await this.api.get(`/portal/projects/${pid}/models`).catch(() => []);
    this.models.set(m);
    this.cur.set(m.find((x: any) => x.id === this.cur()?.id) ?? m[0] ?? null);
    if (this.isTrade) {
      this.rfis.set(await this.api.get(`/portal/projects/${pid}/rfis`).catch(() => []));
      this.subs.set(await this.api.get(`/portal/projects/${pid}/submittals`).catch(() => []));
    }
  }

  async comment() {
    await this.api.post(`/portal/models/${this.cur().id}/comments`, { text: this.text, ...this.at }, 'Sent to the team');
    this.cDlg = false;
    await this.load();
  }

  async ask() {
    await this.api.post(`/portal/projects/${this.projectId()}/rfis`, this.rf, 'Question sent');
    this.rDlg = false;
    await this.load();
  }

  async answer(r: any) {
    const text = prompt(r.question);
    if (!text?.trim()) return;
    await this.api.post(`/portal/rfis/${r.id}/answer`, { text }, 'Answer sent');
    await this.load();
  }

  async attach(ev: Event) {
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) this.sf.files.push((await this.api.upload(file, true)).key);
  }

  async submit() {
    await this.api.post(`/portal/projects/${this.projectId()}/submittals`, this.sf, 'Submitted for review');
    this.sDlg = false;
    await this.load();
  }

  async resubmit(s: any, ev: Event) {
    const files: string[] = [];
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) files.push((await this.api.upload(file, true)).key);
    if (!files.length) return;
    await this.api.post(`/portal/submittals/${s.id}/resubmit`, { files }, 'Revision sent');
    await this.load();
  }
}
