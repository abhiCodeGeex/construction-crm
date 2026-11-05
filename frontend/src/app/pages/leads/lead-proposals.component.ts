import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { MessageService } from 'primeng/api';
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
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, CardModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, SelectButtonModule, TableModule, TagModule],
  template: `
    <div class="stack">
      @if (auth.can('proposals')) {
        <p-card>
          <ng-template #title><div class="row-between"><span>Proposals</span>
            @if (canProp()) { <p-button label="New proposal" icon="pi pi-plus" size="small" (onClick)="openNew()" /> }</div></ng-template>
          <p class="muted small">Each proposal opens in the builder. Sending gives the client a private link to view, choose options and sign; you are told when they open it.</p>
          <p-table [value]="proposals()" size="small">
            <ng-template #header><tr><th>Proposal</th><th class="right">Value</th><th>Valid until</th><th>Status</th><th></th></tr></ng-template>
            <ng-template #body let-p><tr>
              <td><a [routerLink]="['/app/proposals', p.id]"><strong>{{ p.number }}</strong> v{{ p.version }} · {{ p.title }}</a><br /><small class="muted">{{ types()[p.type] || p.type }}{{ p.estimate_number ? ' · from ' + p.estimate_number : '' }}
                @if (p.view_count) { · opened {{ p.view_count }}× }
                @if (p.file_key) { · <a href="" (click)="$event.preventDefault(); api.openFile('/api/files/' + p.file_key)">file</a> }</small></td>
              <td class="right">{{ fmt(p.value) }}</td><td><small>{{ p.valid_until | date: 'd MMM y' }}</small></td>
              <td><p-tag [value]="label(p.status)" [severity]="sev[p.status]" />
                @if (p.sent_at) { <br /><small class="muted">sent {{ p.sent_at | date: 'd MMM' }} · {{ label(p.channel) }}</small> }
                @if (p.response?.reason) { <br /><small class="muted">{{ p.response.reason }}{{ p.response.comment ? ' — ' + p.response.comment : '' }}</small> }
                @if (p.contract_id) { <br /><a class="small" [routerLink]="['/app/contracts', p.contract_id]">Contract →</a> }</td>
              <td class="right nowrap">
                <p-button icon="pi pi-pencil" [text]="true" [rounded]="true" ariaLabel="Open" [routerLink]="['/app/proposals', p.id]" />
                @if (p.link) { <p-button icon="pi pi-link" [text]="true" [rounded]="true" ariaLabel="Copy client link" (onClick)="copy(origin + p.link)" /> }
                @if (canProp()) {
                @if (p.status === 'draft') { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="del(p)" /> }
                @if (p.status === 'sent') { <p-button label="Accepted" size="small" [text]="true" severity="success" (onClick)="ac = { p, signed_by: lead().contact_name }; acDlg = true" />
                  <p-button label="Rejected" size="small" [text]="true" severity="danger" (onClick)="openReject(p)" /> }
                @if (p.status === 'revision_requested' || p.status === 'rejected' || p.status === 'expired') { <p-button label="Revise" size="small" [text]="true" (onClick)="revise(p)" /> } }</td></tr></ng-template>
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
        <p-selectbutton [options]="typeOptions()" [(ngModel)]="pf.type" optionLabel="label" optionValue="value" [allowEmpty]="false" />
        @if (pf.type === 'construction') {
          <label class="field"><span>Approved estimate</span><p-select [options]="approved()" [(ngModel)]="pf.estimate_id" optionLabel="label" optionValue="id" placeholder="Approve an estimate first (Estimate & money)" fluid appendTo="body" /></label>
        } @else if (pf.type === 'simple') {
          <label class="field"><span>Value</span><p-inputnumber [(ngModel)]="pf.value" [min]="0" fluid /></label>
        } @else {
          <label class="field"><span>Template</span><p-select [options]="templatesFor()" [(ngModel)]="pf.template_id" optionLabel="name" optionValue="id" [showClear]="true" placeholder="Start empty" fluid appendTo="body" /></label>
        }
        <div class="grid2">
          <label class="field"><span>Title</span><input pInputText [(ngModel)]="pf.title" placeholder="e.g. Interior design — 3BHK" fluid /></label>
          <label class="field"><span>Valid until</span><input pInputText type="date" [min]="tomorrow" [(ngModel)]="pf.valid_until" fluid /></label>
        </div>
        <div class="row right"><p-button label="Create and open the builder" (onClick)="create()" [disabled]="!pf.valid_until || (pf.type === 'construction' && !pf.estimate_id) || (pf.type === 'simple' && !pf.value)" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Accepted by the client" [modal]="true" [(visible)]="acDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p class="small muted">For an acceptance signed on paper or confirmed by phone. A signed copy can be attached. The contract is created with the payment schedule.</p>
        <label class="field"><span>Accepted by</span><input pInputText [(ngModel)]="ac.signed_by" fluid /></label>
        <input pInputText [(ngModel)]="ac.comment" placeholder="Note (optional)" />
        <label class="field"><span>Signed copy (optional)</span><input type="file" accept=".pdf,.png,.jpg,.jpeg" (change)="ac.file = $any($event.target).files?.[0]" /></label>
        <div class="row right"><p-button label="Record acceptance" severity="success" (onClick)="recordAccept()" [disabled]="!ac.signed_by?.trim()" /></div>
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
  types = signal<Record<string, string>>({});
  templates = signal<any[]>([]);
  defaultType = signal('fee');
  typeOptions = computed(() => Object.entries(this.types()).map(([value, label]) => ({ value, label })));
  templatesFor() {
    return this.templates().filter((x) => x.type === this.pf.type);
  }
  private router = inject(Router);
  private toast = inject(MessageService);
  origin = location.origin;
  ac: any = {};
  acDlg = false;
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
      this.types.set(r.types);
      this.templates.set(r.templates);
      this.defaultType.set(r.default_type);
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

  openNew() {
    const valid = new Date(Date.now() + 15 * 864e5).toISOString().slice(0, 10);
    const type = this.defaultType();
    this.pf = { type, estimate_id: this.approved().at(-1)?.id ?? null, value: null, title: '', valid_until: valid,
      template_id: this.templates().find((x) => x.type === type)?.id ?? null };
    this.newDlg = true;
  }

  async create() {
    const { type, estimate_id, value, template_id, title, valid_until } = this.pf;
    const body: any = { type, title: title || undefined, valid_until };
    if (type === 'construction') body.estimate_id = estimate_id;
    else if (type === 'simple') body.value = value;
    else if (template_id) body.template_id = template_id;
    const p = await this.api.post(`/leads/${this.lead().id}/proposals`, body, 'Proposal created');
    this.newDlg = false;
    this.changed.emit();
    this.router.navigate(['/app/proposals', p.id]);
  }

  async revise(p: any) {
    const valid = new Date(Date.now() + 15 * 864e5).toISOString().slice(0, 10);
    const r = await this.api.post(`/leads/${this.lead().id}/proposals`, { revision_of: p.id, valid_until: p.valid_until > valid ? p.valid_until : valid }, 'New version created');
    this.changed.emit();
    this.router.navigate(['/app/proposals', r.id]);
  }

  async recordAccept() {
    const body: any = { result: 'accepted', signed_by: this.ac.signed_by, comment: this.ac.comment };
    if (this.ac.file) body.file_key = (await this.api.upload(this.ac.file)).key;
    await this.api.post(`/proposals/${this.ac.p.id}/respond`, body, 'Accepted — contract created. You can now mark the lead as won.');
    this.acDlg = false;
    await this.done();
  }

  copy(text: string) {
    navigator.clipboard?.writeText(text).then(() => this.toast.add({ severity: 'success', summary: 'Link copied', life: 1500 }));
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
