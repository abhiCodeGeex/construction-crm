import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { Api, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Phase K block 1 — subcontractor management: work packages, bids side by side, award, measured certificates with
 *  retention, completion rating; and the subcontractor list with ratings and compliance. */
@Component({
  selector: 'app-subcontracts',
  imports: [FormsModule, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, MultiSelectModule, SelectModule, SelectButtonModule, TagModule],
  template: `
    <div class="page">
      <div class="row-between wrap gap mb">
        <h1 class="m0">Subcontracts</h1>
        <span class="row gap"><p-selectbutton [options]="parts" [(ngModel)]="part" optionLabel="label" optionValue="value" [allowEmpty]="false" (ngModelChange)="load()" />
          <p-button label="New work package" icon="pi pi-plus" size="small" (onClick)="openNew()" /></span>
      </div>
      @if (part === 'packages') {
        <div class="layout">
          <div>
            @for (s of rows(); track s.id) {
              <button type="button" class="item" [class.on]="s.id === cur()?.id" (click)="open(s)">
                <strong>{{ s.number }} · {{ s.title }}</strong>
                <span class="small muted">{{ s.project_name }} · <span [class.c-good]="s.status === 'awarded'">{{ s.status }}</span>@if (s.award) { · {{ s.award.name }} }</span>
              </button>
            } @empty { <p class="muted">No work packages yet.</p> }
          </div>
          @if (cur(); as s) {
            <div class="stack">
              <div class="row-between wrap gap"><div><strong>{{ s.number }} · {{ s.title }}</strong> <p-tag [value]="s.status" />
                <div class="small muted">{{ s.project_name }} @if (s.trade) { · {{ s.trade }} } @if (s.due_date) { · bids by {{ s.due_date }} }</div></div>
                <span class="row gap">
                  @if (s.status === 'draft' || s.status === 'bidding') { <p-button label="Invite" icon="pi pi-send" size="small" (onClick)="inviteDlg = true; invitees = []" /> }
                  @if (s.status === 'bidding') { <p-button label="Enter a bid" size="small" [text]="true" (onClick)="openBid()" /> }
                  @if (s.status === 'awarded') {
                    <p-button label="Agreement" icon="pi pi-print" size="small" [text]="true" (onClick)="agreement(s)" />
                    <p-button label="New certificate" size="small" (onClick)="openCert()" />
                    <p-button label="Complete" size="small" [text]="true" (onClick)="doneDlg = true; rating = { quality: 4, time: 4, safety: 4, communication: 4 }" /> }
                  @if (s.status === 'draft' || s.status === 'bidding') { <p-button label="Cancel" size="small" [text]="true" severity="danger" (onClick)="cancel(s)" /> }
                </span></div>
              @if (s.scope) { <div class="small pre">{{ s.scope }}</div> }
              <div class="small">Invited: @for (b of s.bidders; track b.contact_id) { <span class="chip">{{ b.name }} · {{ b.status }}@if (b.expired_docs?.length) { <i class="pi pi-exclamation-triangle c-bad" title="Expired documents"></i> }</span> }</div>
              @if (cmp(); as c) {
                <div class="tablewrap"><table class="t">
                  <tr><th>Item</th><th>Qty</th>@if (c.estimate_total !== null) { <th>Estimate</th> }@for (b of c.bidders; track b.contact_id) { <th>{{ b.name }}</th> }</tr>
                  @for (r of c.rows; track r.line.id) {
                    <tr><td>{{ r.line.description }}</td><td>{{ r.line.qty }} {{ r.line.unit }}</td>
                      @if (c.estimate_total !== null) { <td>{{ fmt(r.est_amount) }}</td> }
                      @for (b of c.bidders; track b.contact_id) { <td [class.low]="r.bids[b.contact_id]?.lowest">@if (r.bids[b.contact_id]; as x) { {{ fmt(x.rate) }} · {{ fmt(x.amount) }} }</td> }</tr>
                  }
                  <tr class="tot"><td colspan="2">Total</td>@if (c.estimate_total !== null) { <td>{{ fmt(c.estimate_total) }}</td> }
                    @for (b of c.bidders; track b.contact_id) { <td>{{ fmt(b.total) }}@if (b.vs_estimate !== null) { <span class="small"> ({{ b.vs_estimate > 0 ? '+' : '' }}{{ b.vs_estimate }}%)</span> }
                      @if (b.days) { <div class="small muted">{{ b.days }} days</div> }@if (b.rating) { <div class="small">★ {{ b.rating.avg }} ({{ b.rating.jobs }})</div> }
                      @if (s.status === 'bidding') { <p-button label="Award" size="small" [text]="true" (onClick)="openAward(b)" /> }</td> }</tr>
                </table></div>
              }
              @if (s.award) { <div class="small">Awarded to <strong>{{ s.award.name }}</strong> — {{ fmt(s.award.total) }}, retention {{ s.award.retention_pct }}% · certified {{ fmt(s.certified) }}
                @if (s.award.reason) { · {{ s.award.reason }} }</div> }
              @for (c of certs(); track c.id) {
                <div class="cert"><div class="row-between wrap gap"><span><strong>{{ c.kind === 'release' ? 'Retention release' : 'Certificate ' + c.number }}</strong> · {{ c.date }} · <p-tag [value]="c.status" /></span>
                  <span class="row gap">
                    @if (c.status === 'draft') { <p-button label="Approve" size="small" (onClick)="certAct(c, 'approve')" /><p-button label="Delete" size="small" [text]="true" severity="danger" (onClick)="delCert(c)" /> }
                    @if (c.status === 'approved') { <p-button label="Record payment" size="small" [text]="true" (onClick)="pay(c)" /> }</span></div>
                  <div class="small">@if (c.kind === 'progress') { This period {{ fmt(c.gross_this) }} − retention {{ fmt(c.retention) }} = } <strong>{{ fmt(c.net) }}</strong> payable · paid {{ fmt(c.paid) }}</div></div>
              }
              @if (s.rating) { <div class="small">Rated ★ {{ s.rating.avg }} — quality {{ s.rating.quality }}, time {{ s.rating.time }}, safety {{ s.rating.safety }}, communication {{ s.rating.communication }}</div> }
            </div>
          }
        </div>
      } @else {
        <table class="t">
          <tr><th>Subcontractor</th><th>Rating</th><th>Invited</th><th>Awarded</th><th>Working now</th><th>Compliance</th></tr>
          @for (x of subs(); track x.id) {
            <tr><td>{{ x.name }}<div class="small muted">{{ x.phone }} {{ x.email }}</div></td><td>@if (x.rating) { ★ {{ x.rating.avg }} ({{ x.rating.jobs }}) } @else { — }</td>
              <td>{{ x.invited }}</td><td>{{ x.awarded }}</td><td>{{ x.active }}</td>
              <td>@if (x.expired_docs.length) { <span class="c-bad">Expired: {{ x.expired_docs.join(', ') }}</span> } @else { <span class="c-good">OK</span> }</td></tr>
          } @empty { <tr><td colspan="6" class="muted">Mark contacts as "subcontractor" to see them here.</td></tr> }
        </table>
      }
    </div>

    <p-dialog header="New work package" [modal]="true" [(visible)]="newDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field req"><span>Project</span><p-select [options]="projects()" optionLabel="name" optionValue="id" [(ngModel)]="nf.project_id" (onChange)="projectPicked()" [filter]="true" fluid appendTo="body" /></label>
          <label class="field req"><span>Package</span><input pInputText [(ngModel)]="nf.title" placeholder="Electrical works" fluid /></label>
          <label class="field"><span>Trade</span><input pInputText [(ngModel)]="nf.trade" fluid /></label>
          <label class="field"><span>Bids by</span><input pInputText type="date" [(ngModel)]="nf.due_date" fluid /></label>
        </div>
        <label class="field"><span>Scope</span><textarea class="p-inputtext" rows="3" [(ngModel)]="nf.scope"></textarea></label>
        @if (estLines().length) { <label class="field"><span>Take lines from the estimate</span>
          <p-multiselect [options]="estLines()" optionLabel="description" optionValue="id" [(ngModel)]="nf.est_ids" display="chip" fluid appendTo="body" (onChange)="fromEstimate()" /></label> }
        @for (l of nf.lines; track $index; let i = $index) {
          <div class="row gap"><input pInputText [(ngModel)]="l.description" placeholder="Item" class="grow" aria-label="Item" />
            <p-inputnumber [(ngModel)]="l.qty" placeholder="Qty" [min]="0" ariaLabel="Quantity" /><input pInputText [(ngModel)]="l.unit" placeholder="Unit" style="width:5rem" aria-label="Unit" />
            @if (seesCost) { <p-inputnumber [(ngModel)]="l.est_rate" placeholder="Our rate" [min]="0" ariaLabel="Estimate rate" /> }
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="nf.lines.splice(i, 1)" ariaLabel="Remove line" /></div>
        }
        <p-button label="Add a line" icon="pi pi-plus" size="small" [text]="true" (onClick)="nf.lines.push({ description: '', qty: null, unit: '' })" />
        <div class="row right"><p-button label="Save" [disabled]="!nf.project_id || !nf.title?.trim() || !nf.lines.length" (onClick)="saveNew()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Invite subcontractors" [modal]="true" [(visible)]="inviteDlg" [style]="{ width: '30rem' }">
      <div class="stack"><p-multiselect [options]="subs()" optionLabel="name" optionValue="id" [(ngModel)]="invitees" display="chip" fluid appendTo="body" ariaLabel="Subcontractors" />
        <p class="small muted m0">They get an email (and WhatsApp when they agreed) and price the lines in their portal.</p>
        <div class="row right"><p-button label="Invite" [disabled]="!invitees.length" (onClick)="invite()" /></div></div>
    </p-dialog>
    <p-dialog header="Enter a bid" [modal]="true" [(visible)]="bidDlg" [style]="{ width: '36rem' }">
      <div class="stack">
        <p-select [options]="cur()?.bidders ?? []" optionLabel="name" optionValue="contact_id" [(ngModel)]="bf.contact_id" placeholder="Subcontractor" fluid appendTo="body" ariaLabel="Subcontractor" />
        @for (l of cur()?.lines ?? []; track l.id) { <div class="row gap"><span class="grow small">{{ l.description }} ({{ l.qty }} {{ l.unit }})</span><p-inputnumber [(ngModel)]="bf.rates[l.id]" placeholder="Rate" [min]="0" [ariaLabel]="'Rate for ' + l.description" /></div> }
        <p-inputnumber [(ngModel)]="bf.days" placeholder="Days to complete" [min]="1" ariaLabel="Days" />
        <div class="row right"><p-button label="Save bid" [disabled]="!bf.contact_id" (onClick)="saveBid()" /></div>
      </div>
    </p-dialog>
    <p-dialog [header]="'Award to ' + (af.name || '')" [modal]="true" [(visible)]="awardDlg" [style]="{ width: '32rem' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Retention %</span><p-inputnumber [(ngModel)]="af.retention_pct" [min]="0" [max]="20" fluid /></label>
          <label class="field"><span>Start</span><input pInputText type="date" [(ngModel)]="af.start" fluid /></label>
          <label class="field"><span>End</span><input pInputText type="date" [(ngModel)]="af.end" fluid /></label>
        </div>
        @if (!af.lowest) { <label class="field req"><span>Why not the lowest bid?</span><input pInputText [(ngModel)]="af.reason" fluid /></label> }
        <label class="field"><span>Terms</span><textarea class="p-inputtext" rows="3" [(ngModel)]="af.terms"></textarea></label>
        @if (af.warn) { <p class="small c-bad m0">{{ af.warn }}</p><label class="check"><p-checkbox [(ngModel)]="af.accept_expired" [binary]="true" ariaLabel="Award anyway" /> Award anyway</label> }
        <div class="row right"><p-button label="Award" (onClick)="award()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Payment certificate — quantity done to date" [modal]="true" [(visible)]="certDlg" [style]="{ width: '34rem' }">
      <div class="stack">
        @for (l of cur()?.lines ?? []; track l.id) { <div class="row gap"><span class="grow small">{{ l.description }} (of {{ l.qty }} {{ l.unit }})</span><p-inputnumber [(ngModel)]="cf[l.id]" [min]="0" [maxFractionDigits]="2" [ariaLabel]="'Done to date for ' + l.description" /></div> }
        <div class="row right"><p-button label="Make certificate" (onClick)="saveCert()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Complete and rate" [modal]="true" [(visible)]="doneDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        @for (k of ['quality', 'time', 'safety', 'communication']; track k) {
          <div class="row-between"><span class="cap">{{ k }}</span><span class="row gap">@for (n of [1, 2, 3, 4, 5]; track n) {
            <button type="button" class="star" [class.on]="rating[k] >= n" (click)="rating[k] = n" [attr.aria-label]="k + ' ' + n">★</button> }</span></div>
        }
        <p class="small muted m0">The retention held is released by a release certificate to approve and pay.</p>
        <div class="row right"><p-button label="Complete" (onClick)="complete()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.layout { display: grid; grid-template-columns: 18rem 1fr; gap: 1rem; } @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
    .item { display: grid; text-align: left; width: 100%; padding: .5rem .7rem; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); margin-bottom: .4rem; cursor: pointer; }
    .item.on { border-color: var(--p-primary-color); } .chip { display: inline-block; border: 1px solid var(--border); border-radius: 99px; padding: 0 .5rem; margin: .1rem; }
    .tablewrap { overflow-x: auto; } .t { width: 100%; border-collapse: collapse; font-size: .88rem; } .t td, .t th { border-bottom: 1px solid var(--border); padding: .35rem .4rem; text-align: left; vertical-align: top; }
    .low { background: rgba(22, 163, 74, .12); } .tot td { font-weight: 600; } .cert { border: 1px solid var(--border); border-radius: 8px; padding: .5rem .7rem; }
    .pre { white-space: pre-wrap; } .star { background: none; border: 0; font-size: 1.3rem; color: #ccc; cursor: pointer; } .star.on { color: #f59e0b; } .cap { text-transform: capitalize; }`,
})
export class SubcontractsComponent {
  private api = inject(Api);
  private auth = inject(AuthService);
  seesCost = ['owner', 'pm', 'accounts', 'procurement'].includes(this.auth.user()?.role ?? '');
  parts = [{ label: 'Work packages', value: 'packages' }, { label: 'Subcontractors', value: 'subs' }];
  part = 'packages';
  rows = signal<any[]>([]);
  cur = signal<any>(null);
  cmp = signal<any>(null);
  certs = signal<any[]>([]);
  subs = signal<any[]>([]);
  projects = signal<any[]>([]);
  estLines = signal<any[]>([]);
  newDlg = false; inviteDlg = false; bidDlg = false; awardDlg = false; certDlg = false; doneDlg = false;
  nf: any = { lines: [] };
  bf: any = { rates: {} };
  af: any = {};
  cf: any = {};
  rating: any = {};
  invitees: string[] = [];

  async ngOnInit() {
    await this.load();
  }

  fmt(v: number | null) {
    return v === null || v === undefined ? '—' : money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  async load() {
    this.subs.set(await this.api.get('/subcontractors'));
    if (this.part === 'packages') {
      this.rows.set(await this.api.get('/subcontracts'));
      const id = this.cur()?.id;
      const s = this.rows().find((x) => x.id === id);
      if (s) await this.open(s);
    }
  }

  async open(s: any) {
    const full = await this.api.get(`/subcontracts/${s.id}`);
    this.cur.set(full);
    this.certs.set(full.certificates);
    this.cmp.set(full.bids.length ? await this.api.get(`/subcontracts/${s.id}/compare`) : null);
  }

  async openNew() {
    this.projects.set((await this.api.get('/projects')).filter((p: any) => ['planning', 'active', 'on_hold'].includes(p.status)));
    this.nf = { project_id: null, title: '', trade: '', due_date: null, scope: '', lines: [], est_ids: [] };
    this.estLines.set([]);
    this.newDlg = true;
  }

  async projectPicked() {
    const r = await this.api.get(`/projects/${this.nf.project_id}/estimate-lines`).catch(() => ({ lines: [] }));
    this.estLines.set(r.lines);
  }

  fromEstimate() {
    const keep = this.nf.lines.filter((l: any) => !l.estimate_line_id);
    const picked = this.estLines().filter((l) => this.nf.est_ids.includes(l.id))
      .map((l) => ({ estimate_line_id: l.id, description: l.description, qty: l.qty, unit: l.unit, est_rate: l.labour_rate ?? null }));
    this.nf.lines = [...keep, ...picked];
  }

  async saveNew() {
    const { project_id, est_ids, ...body } = this.nf;
    const s = await this.api.post(`/projects/${project_id}/subcontracts`, body, 'Work package made');
    this.newDlg = false;
    await this.load();
    await this.open(s);
  }

  async invite() {
    await this.api.post(`/subcontracts/${this.cur().id}/invite`, { contact_ids: this.invitees }, 'Invitations sent');
    this.inviteDlg = false;
    await this.load();
  }

  openBid() {
    this.bf = { contact_id: null, rates: {}, days: null };
    this.bidDlg = true;
  }

  async saveBid() {
    const lines = this.cur().lines.map((l: any) => ({ line_id: l.id, rate: this.bf.rates[l.id] }));
    await this.api.post(`/subcontracts/${this.cur().id}/bids`, { contact_id: this.bf.contact_id, lines, days: this.bf.days || null }, 'Bid saved');
    this.bidDlg = false;
    await this.load();
  }

  openAward(b: any) {
    this.af = { contact_id: b.contact_id, name: b.name, lowest: b.contact_id === this.cmp().lowest, retention_pct: 5, start: null, end: null, terms: '', reason: '', warn: '' };
    this.awardDlg = true;
  }

  async award() {
    const { name, lowest, warn, ...body } = this.af;
    try {
      await this.api.raw('post', `/subcontracts/${this.cur().id}/award`, body);
    } catch (e: any) {
      if (e?.status === 409) {
        this.af.warn = e.error?.error;
        return;
      }
      throw e;
    }
    this.awardDlg = false;
    await this.load();
  }

  agreement(s: any) {
    this.api.openFile(`/api/subcontracts/${s.id}/agreement`);
  }

  openCert() {
    const last = this.certs().filter((c) => c.kind === 'progress' && c.status !== 'draft').pop();
    this.cf = Object.fromEntries(this.cur().lines.map((l: any) => [l.id, last?.measured.find((m: any) => m.line_id === l.id)?.qty_to_date ?? 0]));
    this.certDlg = true;
  }

  async saveCert() {
    await this.api.post(`/subcontracts/${this.cur().id}/certificates`, { measured: Object.entries(this.cf).map(([line_id, qty_to_date]) => ({ line_id, qty_to_date })) }, 'Certificate made');
    this.certDlg = false;
    await this.load();
  }

  async certAct(c: any, what: string) {
    await this.api.post(`/sub-certificates/${c.id}/${what}`, {}, 'Approved — the cost is booked');
    await this.load();
  }

  async delCert(c: any) {
    await this.api.del(`/sub-certificates/${c.id}`, 'Deleted');
    await this.load();
  }

  async pay(c: any) {
    const ref = prompt('Payment reference (UTR / cheque no.)') ?? '';
    await this.api.post(`/sub-certificates/${c.id}/pay`, { ref }, 'Payment recorded');
    await this.load();
  }

  async complete() {
    await this.api.post(`/subcontracts/${this.cur().id}/complete`, { rating: this.rating }, 'Completed');
    this.doneDlg = false;
    await this.load();
  }

  async cancel(s: any) {
    if (!confirm('Cancel this package?')) return;
    await this.api.post(`/subcontracts/${s.id}/cancel`, {}, 'Cancelled');
    await this.load();
  }
}
