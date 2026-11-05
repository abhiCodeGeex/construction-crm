import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

const P_SEVERITY: Record<string, 'info' | 'success' | 'warn' | 'danger' | 'secondary'> = {
  draft: 'secondary', sent: 'info', accepted: 'success', rejected: 'danger', revision_requested: 'warn', expired: 'danger', superseded: 'secondary',
};

/** Lead steps 5b-6 (C+2): proposal versions and the client's answer, negotiation rounds with discount approval, competitors. */
@Component({
  selector: 'app-lead-proposals',
  imports: [FormsModule, DatePipe, ButtonModule, CardModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, SelectButtonModule, TableModule, TagModule],
  template: `
    <div class="stack">
      @if (auth.can('proposals')) {
        <p-card>
          <ng-template #title><div class="row-between"><span>Proposals</span>
            @if (canProp()) { <p-button label="New proposal" icon="pi pi-plus" size="small" (onClick)="openNew()" /> }</div></ng-template>
          <p class="muted small">The proposal document itself (builder, client link and e-signature) arrives in Phase D. Here every version is tracked: sent, accepted, rejected, expired.</p>
          <p-table [value]="proposals()" size="small">
            <ng-template #header><tr><th>Proposal</th><th class="right">Value</th><th>Valid until</th><th>Status</th><th></th></tr></ng-template>
            <ng-template #body let-p><tr>
              <td><strong>{{ p.number }}</strong> v{{ p.version }} · {{ p.title }}<br /><small class="muted">{{ p.estimate_number ? 'from ' + p.estimate_number : 'typed value' }}
                @if (p.file_key) { · <a href="" (click)="$event.preventDefault(); api.openFile('/api/files/' + p.file_key)">file</a> }</small></td>
              <td class="right">{{ fmt(p.value) }}</td><td><small>{{ p.valid_until | date: 'd MMM y' }}</small></td>
              <td><p-tag [value]="label(p.status)" [severity]="sev[p.status]" />
                @if (p.sent_at) { <br /><small class="muted">sent {{ p.sent_at | date: 'd MMM' }} · {{ label(p.channel) }}</small> }
                @if (p.response?.reason) { <br /><small class="muted">{{ p.response.reason }}{{ p.response.comment ? ' — ' + p.response.comment : '' }}</small> }</td>
              <td class="right nowrap">@if (canProp()) {
                @if (p.status === 'draft') { <p-button label="Sent" size="small" [text]="true" (onClick)="sf = { p, channel: 'email' }; sendDlg = true" />
                  <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="del(p)" /> }
                @if (p.status === 'sent') { <p-button label="Accepted" size="small" [text]="true" severity="success" (onClick)="respond(p, 'accepted')" />
                  <p-button label="Rejected" size="small" [text]="true" severity="danger" (onClick)="openReject(p)" /> }
                @if (p.status === 'revision_requested' || p.status === 'rejected' || p.status === 'expired') { <p-button label="Revise" size="small" [text]="true" (onClick)="openNew(p)" /> } }</td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="5" class="muted center">No proposal yet</td></tr></ng-template>
          </p-table>
        </p-card>
      }

      <div class="grid2 top">
        <p-card>
          <ng-template #title>Negotiation</ng-template>
          @for (r of lead().negotiation ?? []; track r.id) {
            <div class="ms-row"><i class="pi pi-arrows-h"></i>
              <div class="grow">{{ fmt(r.asked) }} → {{ fmt(r.offered) }} <strong>({{ r.discount_pct }}% off)</strong>
                <br /><small class="muted">{{ r.by }} · {{ r.at | date: 'd MMM' }}{{ r.note ? ' · ' + r.note : '' }}</small></div>
              @switch (r.approval.status) {
                @case ('pending') { <p-tag value="Needs approval" severity="warn" />
                  @if (isApprover() && editable()) { <p-button label="Approve" size="small" [text]="true" severity="success" (onClick)="decide(r, true)" />
                    <p-button label="Refuse" size="small" [text]="true" severity="danger" (onClick)="nr2 = { r, note: '' }; refDlg = true" /> } }
                @case ('approved') { <p-tag value="Approved" severity="success" /> }
                @case ('refused') { <p-tag value="Refused" severity="danger" /> }
              }
            </div>
          } @empty { <p class="muted small">No rounds yet.</p> }
          @if (editable()) {
            <div class="row gap wrap mt-xs">
              <p-inputnumber [(ngModel)]="nf.asked" [min]="0" placeholder="Our price" [inputStyle]="{ width: '8rem' }" />
              <p-inputnumber [(ngModel)]="nf.offered" [min]="0" placeholder="Client offers" [inputStyle]="{ width: '8rem' }" />
              <input pInputText [(ngModel)]="nf.note" placeholder="Note" class="grow" />
              <p-button label="Log round" (onClick)="addRound()" [disabled]="!nf.asked || !nf.offered" />
            </div>
          }
        </p-card>

        <p-card>
          <ng-template #title>Competitors</ng-template>
          @for (c of lead().competitors ?? []; track c.id) {
            <div class="ms-row"><i class="pi pi-flag"></i><div class="grow"><strong>{{ c.name }}</strong>{{ c.price ? ' · ' + fmt(c.price) : '' }}<br /><small class="muted">{{ c.notes }}</small></div>
              @if (editable()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="delComp(c)" /> }</div>
          } @empty { <p class="muted small">No competitor noted.</p> }
          @if (editable()) {
            <div class="row gap wrap mt-xs">
              <input pInputText [(ngModel)]="cf.name" placeholder="Competitor" />
              <p-inputnumber [(ngModel)]="cf.price" [min]="0" placeholder="Their price" [inputStyle]="{ width: '8rem' }" />
              <input pInputText [(ngModel)]="cf.notes" placeholder="What they offer" class="grow" />
              <p-button icon="pi pi-plus" (onClick)="addComp()" [disabled]="!cf.name?.trim()" />
            </div>
          }
        </p-card>
      </div>
    </div>

    <p-dialog header="New proposal" [modal]="true" [(visible)]="newDlg" [style]="{ width: '32rem' }">
      <div class="stack">
        <label class="field"><span>From an approved estimate</span><p-select [options]="approved()" [(ngModel)]="pf.estimate_id" optionLabel="label" optionValue="id" [showClear]="true" placeholder="— or type the value —" fluid appendTo="body" /></label>
        @if (!pf.estimate_id) { <label class="field"><span>Value</span><p-inputnumber [(ngModel)]="pf.value" [min]="0" fluid /></label> }
        <div class="grid2">
          <label class="field"><span>Title</span><input pInputText [(ngModel)]="pf.title" fluid /></label>
          <label class="field"><span>Valid until</span><input pInputText type="date" [min]="tomorrow" [(ngModel)]="pf.valid_until" fluid /></label>
        </div>
        <label class="field"><span>Proposal file (PDF) <small class="muted">optional</small></span><input type="file" accept=".pdf,.doc,.docx" (change)="pickFile($event)" /></label>
        <div class="row right"><p-button label="Save draft" (onClick)="create()" [disabled]="!pf.valid_until || (!pf.estimate_id && !pf.value)" /></div>
      </div>
    </p-dialog>

    <p-dialog header="How was it sent?" [modal]="true" [(visible)]="sendDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p-selectbutton [options]="channels" [(ngModel)]="sf.channel" optionLabel="label" optionValue="value" [allowEmpty]="false" />
        <small class="muted">Email sends it to the client (with the file) when email is set up; the result is logged.</small>
        <div class="row right"><p-button label="Mark as sent" (onClick)="send()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Client's answer" [modal]="true" [(visible)]="rejDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p-selectbutton [options]="rejOpts" [(ngModel)]="rj.result" optionLabel="label" optionValue="value" [allowEmpty]="false" />
        <p-select [options]="rejectReasons()" [(ngModel)]="rj.reason" placeholder="Reason" fluid appendTo="body" />
        <input pInputText [(ngModel)]="rj.comment" placeholder="What the client said" />
        <div class="row right"><p-button label="Save" (onClick)="respond(rj.p, rj.result, rj.reason, rj.comment)" [disabled]="!rj.reason" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Refuse the discount" [modal]="true" [(visible)]="refDlg" [style]="{ width: '26rem' }">
      <div class="stack"><input pInputText [(ngModel)]="nr2.note" placeholder="Why" />
        <div class="row right"><p-button label="Refuse" severity="danger" (onClick)="decide(nr2.r, false, nr2.note)" [disabled]="!nr2.note?.trim()" /></div></div>
    </p-dialog>
  `,
})
export class LeadProposalsComponent implements OnInit {
  lead = input.required<any>();
  changed = output<void>();
  api = inject(Api);
  auth = inject(AuthService);
  proposals = signal<any[]>([]);
  estimates = signal<any[]>([]);
  rejectReasons = signal<string[]>([]);
  managerId = signal<string | null>(null);
  editable = computed(() => this.lead()?.status === 'open' && this.lead()?.can_edit);
  canProp = computed(() => this.lead()?.status === 'open' && this.auth.can('proposals', 'rw'));
  isApprover = computed(() => this.auth.user()?.role === 'owner' || this.auth.user()?.id === this.managerId());
  approved = computed(() => this.estimates().filter((e) => e.status === 'approved').map((e) => ({ ...e, label: `${e.number} v${e.version} · ${this.fmt(e.totals.total)}` })));
  sev = P_SEVERITY;
  label = label;
  tomorrow = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
  channels = [{ label: 'Email', value: 'email' }, { label: 'WhatsApp', value: 'whatsapp' }, { label: 'In person', value: 'in_person' }, { label: 'Other', value: 'other' }];
  rejOpts = [{ label: 'Rejected', value: 'rejected' }, { label: 'Wants a revision', value: 'revision_requested' }];
  pf: any = {}; sf: any = {}; rj: any = {}; nf: any = {}; cf: any = {}; nr2: any = {};
  newDlg = false; sendDlg = false; rejDlg = false; refDlg = false;
  private file: File | null = null;

  async ngOnInit() {
    await this.load();
  }

  fmt(v: number | null | undefined) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  async load() {
    const id = this.lead().id;
    if (this.auth.can('proposals')) {
      const r = await this.api.get(`/leads/${id}/proposals`);
      this.proposals.set(r.proposals);
      this.rejectReasons.set(r.reject_reasons);
      this.estimates.set((await this.api.get(`/leads/${id}/estimates`)).estimates);
    }
    this.managerId.set((await this.api.get('/leads/meta')).sales_settings?.manager_id ?? null);
    this.nf = { asked: this.lead().value || null, offered: null, note: '' };
    this.cf = { name: '', price: null, notes: '' };
  }

  private async done() {
    this.changed.emit();
    await this.load();
  }

  openNew(from?: any) {
    const valid = new Date(Date.now() + 15 * 864e5).toISOString().slice(0, 10);
    this.pf = { estimate_id: from?.estimate_id ?? this.approved().at(-1)?.id ?? null, value: from?.value ?? null, title: '', valid_until: valid, revision_of: from?.id };
    this.file = null;
    this.newDlg = true;
  }

  pickFile(ev: Event) {
    this.file = (ev.target as HTMLInputElement).files?.[0] ?? null;
  }

  async create() {
    const body = { ...this.pf };
    if (this.file) body.file_key = (await this.api.upload(this.file)).key;
    if (body.estimate_id) delete body.value;
    await this.api.post(`/leads/${this.lead().id}/proposals`, body, 'Proposal saved');
    this.newDlg = false;
    await this.done();
  }

  async send() {
    await this.api.post(`/proposals/${this.sf.p.id}/send`, { channel: this.sf.channel }, 'Marked as sent');
    this.sendDlg = false;
    await this.done();
  }

  openReject(p: any) {
    this.rj = { p, result: 'rejected', reason: null, comment: '' };
    this.rejDlg = true;
  }

  async respond(p: any, result: string, reason?: string, comment?: string) {
    await this.api.post(`/proposals/${p.id}/respond`, { result, reason, comment }, result === 'accepted' ? 'Accepted — you can now mark the lead as won' : 'Answer recorded');
    this.rejDlg = false;
    await this.done();
  }

  async del(p: any) {
    await this.api.del(`/proposals/${p.id}`, 'Draft deleted');
    await this.done();
  }

  async addRound() {
    await this.api.post(`/leads/${this.lead().id}/negotiation`, this.nf, 'Round logged');
    await this.done();
  }

  async decide(r: any, approve: boolean, note?: string) {
    await this.api.post(`/leads/${this.lead().id}/negotiation/${r.id}/decide`, { approve, note }, approve ? 'Approved' : 'Refused');
    this.refDlg = false;
    await this.done();
  }

  async addComp() {
    await this.api.post(`/leads/${this.lead().id}/competitors`, this.cf, 'Competitor noted');
    await this.done();
  }

  async delComp(c: any) {
    await this.api.del(`/leads/${this.lead().id}/competitors/${c.id}`, 'Removed');
    await this.done();
  }
}
