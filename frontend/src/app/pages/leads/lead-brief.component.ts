import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { TooltipModule } from 'primeng/tooltip';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** Lead steps 2 and 4 (C+2): decision-makers, ballpark, the requirement brief and the client questionnaire. */
@Component({
  selector: 'app-lead-brief',
  imports: [TooltipModule, FormsModule, DatePipe, ButtonModule, CardModule, CheckboxModule, DialogModule, InputTextModule, MessageModule, MultiSelectModule,
    SelectModule, SelectButtonModule, TagModule, TextareaModule],
  template: `
    @if (d(); as d) {
      <div class="grid2 top">
        <div class="stack">
          <p-card>
            <ng-template #title><div class="row-between"><span>Decision-makers</span>
              @if (editable()) { <p-button label="Add" icon="pi pi-plus" size="small" [text]="true" (onClick)="openPerson()" /> }</div></ng-template>
            <div class="ms-row"><i class="pi pi-user"></i><div class="grow"><strong>{{ lead().contact_name }}</strong><br /><small class="muted">Enquirer</small></div></div>
            @for (p of d.stakeholders; track p.id) {
              <div class="ms-row"><i class="pi pi-users"></i>
                <div class="grow"><strong>{{ p.name }}</strong> @if (p.main) { <p-tag value="Main decision-maker" severity="success" /> }
                  <br /><small class="muted">{{ p.role }}{{ p.phone ? ' · ' + p.phone : '' }}{{ p.email ? ' · ' + p.email : '' }}</small></div>
                @if (editable()) {
                  @if (!p.main) { <p-button label="Make main" size="small" [text]="true" (onClick)="setMain(p)" /> }
                  <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="removePerson(p)" ariaLabel="Delete" pTooltip="Delete"/> }
              </div>
            }
          </p-card>

          <p-card>
            <ng-template #title>Ballpark</ng-template>
            @if (!d.package_rates.length) { <p class="muted small">No package rates for this service yet — the owner sets them in Settings → Sales.</p> }
            @else {
              <div class="row gap wrap">
                <p-select [options]="d.package_rates" [(ngModel)]="pkg" optionLabel="name" optionValue="name" placeholder="Package" [disabled]="!editable()" />
                <p-button label="Work out" icon="pi pi-calculator" [outlined]="true" (onClick)="ballpark()" [disabled]="!pkg || !editable()" />
                <small class="muted">@for (p of d.package_rates; track p.name) { {{ p.name }} {{ fmt(p.rate) }}/{{ p.unit === 'sqft' ? 'sq ft' : 'm²' }} · }</small>
              </div>
            }
            @if (d.ballpark; as b) {
              <div class="mt-xs"><strong>{{ b.package }}: {{ fmt(b.amount) }}</strong> <small class="muted">({{ b.area }} {{ b.unit }} × {{ fmt(b.rate) }}, {{ b.by }}, {{ b.at | date: 'd MMM' }})</small></div>
              @if (b.budget_gap != null && b.budget_gap < 0) { <p-message severity="warn" text="The client's budget is short by {{ fmt(-b.budget_gap) }} for this package." styleClass="mt-xs" /> }
            }
          </p-card>

          <p-card>
            <ng-template #title>Client questionnaire</ng-template>
            @if (d.questionnaire.submitted_at) {
              <p class="small muted">Answered {{ d.questionnaire.submitted_at | date: 'd MMM y, h:mm a' }}</p>
              @for (q of d.questions; track q.id) { @if (d.questionnaire.answers?.[q.id]; as a) { <div class="small mb-xs"><strong>{{ q.label }}</strong><br />{{ a }}</div> } }
              @if (editable()) { <p-button label="Copy answers into the brief notes" icon="pi pi-copy" size="small" [text]="true" (onClick)="copyAnswers()" /> }
            } @else {
              <p class="small muted">A link the client opens to describe what they want; the answers arrive here and the salesperson is told.</p>
              @if (d.questionnaire.link) { <div class="row gap"><input aria-label="Questionnaire link" title="Questionnaire link" pInputText [value]="origin + d.questionnaire.link" readonly class="grow" />
                <p-button icon="pi pi-copy" [outlined]="true" (onClick)="copy(origin + d.questionnaire.link)" ariaLabel="Copy" pTooltip="Copy"/></div>
                <small class="muted">Created {{ d.questionnaire.sent_at | date: 'd MMM' }} by {{ d.questionnaire.sent_by }} · not answered yet</small> }
              @if (editable()) { <div class="row gap mt-xs">
                <p-button [label]="d.questionnaire.link ? 'Email the link' : 'Create link'" icon="pi pi-link" size="small" [outlined]="true" (onClick)="questionnaire(!!d.questionnaire.link)" /></div> }
            }
          </p-card>
        </div>

        <p-card>
          <ng-template #title><div class="row-between"><span>Brief @if (d.brief) { <small class="muted">v{{ d.brief.version }}</small> }</span>
            <span class="row gap">
              @if (d.brief?.complete) { <p-tag value="Complete" severity="success" /> }
              @if (d.brief?.client_confirmed; as c) { <p-tag value="Confirmed by client ({{ c.how }})" severity="info" /> }
            </span></div></ng-template>
          <div class="stack">
            <strong>Scope — rooms and the work in each</strong>
            @for (s of f.scope; track $index; let i = $index) {
              <div class="row gap">
                <input pInputText [(ngModel)]="s.room" placeholder="Room / area" [disabled]="!editable()" />
                <p-multiselect [options]="d.work_types" [(ngModel)]="s.work_types" placeholder="Work" display="chip" class="grow" [disabled]="!editable()" appendTo="body" />
                @if (editable()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="f.scope.splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/> }
              </div>
            }
            @if (editable()) { <div class="row gap"><p-button label="Add room" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.scope.push({ room: '', work_types: [] })" />
              @if (rooms().length) { <p-button label="Use measured rooms" size="small" [text]="true" (onClick)="useRooms()" /> }</div> }
            <div class="grid2">
              @for (k of textFields; track k.key) {
                <label class="field"><span>{{ k.label }}</span><textarea pTextarea rows="2" [(ngModel)]="f[k.key]" [disabled]="!editable()" fluid></textarea></label>
              }
            </div>
            <label class="check"><p-checkbox [(ngModel)]="f.complete" [binary]="true" [disabled]="!editable()" ariaLabel="The brief is complete" /> The brief is complete (estimators are told it is ready)</label>
            @if (editable()) {
              <div class="row gap right">
                @if (d.brief && !d.brief.client_confirmed) { <p-button label="Client confirmed" icon="pi pi-verified" [outlined]="true" (onClick)="confirmDlg = true" /> }
                <p-button label="Save brief" icon="pi pi-check" (onClick)="save()" />
              </div>
            }
            @if (d.versions.length > 1) {
              <details><summary class="small">Earlier versions ({{ d.versions.length - 1 }})</summary>
                @for (v of d.versions.slice(0, -1).reverse(); track v.version) {
                  <div class="small mt-xs"><strong>v{{ v.version }}</strong> — {{ v.updated_by }}, {{ v.updated_at | date: 'd MMM y' }}: {{ scopeText(v) }}{{ v.style ? ' · style ' + v.style : '' }}</div>
                }
              </details>
            }
          </div>
        </p-card>
      </div>

      <p-dialog header="Add a decision-maker" [modal]="true" [(visible)]="personDlg" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p-selectbutton [options]="modes" [(ngModel)]="pf.mode" optionLabel="label" optionValue="value" [allowEmpty]="false" />
          @if (pf.mode === 'existing') {
            <p-select [options]="contacts()" [(ngModel)]="pf.contact_id" optionLabel="name" optionValue="id" [filter]="true" placeholder="Contact" fluid appendTo="body" />
          } @else {
            <input pInputText [(ngModel)]="pf.name" placeholder="Name" fluid />
            <div class="grid2"><input pInputText [(ngModel)]="pf.phone" placeholder="Phone" /><input pInputText [(ngModel)]="pf.email" placeholder="Email" /></div>
          }
          <p-select [options]="d.stakeholder_roles" [(ngModel)]="pf.role" placeholder="Role" fluid appendTo="body" />
          <label class="check"><p-checkbox [(ngModel)]="pf.main" [binary]="true" /> Main decision-maker</label>
          <div class="row right"><p-button label="Add" (onClick)="addPerson()" [disabled]="!pf.role" /></div>
        </div>
      </p-dialog>

      <p-dialog header="How did the client confirm the brief?" [modal]="true" [(visible)]="confirmDlg" [style]="{ width: '26rem' }" [breakpoints]="{ '640px': '96vw' }">
        <div class="stack">
          <p-selectbutton [options]="hows" [(ngModel)]="how" optionLabel="label" optionValue="value" [allowEmpty]="false" />
          <div class="row right"><p-button label="Record confirmation" (onClick)="confirm()" /></div>
        </div>
      </p-dialog>
    }
  `,
})
export class LeadBriefComponent implements OnInit {
  lead = input.required<any>();
  contacts = input<any[]>([]);
  changed = output<void>();
  private api = inject(Api);
  private auth = inject(AuthService);
  private toast = inject(MessageService);
  d = signal<any>(null);
  editable = computed(() => this.lead()?.status === 'open' && this.lead()?.can_edit);
  rooms = computed(() => this.lead()?.measurements?.rooms ?? []);
  origin = location.origin;
  textFields = [{ key: 'style', label: 'Style' }, { key: 'materials', label: 'Materials / finishes' }, { key: 'brands', label: 'Brands' },
    { key: 'must_haves', label: 'Must-haves' }, { key: 'nice_to_haves', label: 'Nice-to-haves' }, { key: 'programme', label: 'Spaces / programme (architecture)' },
    { key: 'approvals_needed', label: 'Approvals needed' }, { key: 'notes', label: 'Notes' }];
  modes = [{ label: 'New person', value: 'new' }, { label: 'Existing contact', value: 'existing' }];
  hows = [{ label: 'Call', value: 'call' }, { label: 'Email', value: 'email' }, { label: 'WhatsApp', value: 'whatsapp' }, { label: 'Meeting', value: 'meeting' }];
  f: any = { scope: [] };
  pf: any = {};
  pkg: string | null = null;
  how = 'call';
  personDlg = false;
  confirmDlg = false;

  async ngOnInit() {
    await this.load();
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  async load() {
    const d = await this.api.get(`/leads/${this.lead().id}/brief`);
    this.d.set(d);
    const b = d.brief || {};
    this.f = { scope: (b.scope || []).map((s: any) => ({ ...s, work_types: [...s.work_types] })), complete: !!b.complete,
      ...Object.fromEntries(this.textFields.map((k) => [k.key, b[k.key] ?? ''])) };
    this.pkg = d.ballpark?.package ?? null;
  }

  private async done() {
    await this.load();
    this.changed.emit();
  }

  scopeText(v: any) {
    return (v.scope || []).map((s: any) => `${s.room} (${s.work_types.join(', ')})`).join('; ');
  }

  useRooms() {
    const have = new Set(this.f.scope.map((s: any) => s.room.toLowerCase()));
    for (const r of this.rooms()) if (!have.has(r.name.toLowerCase())) this.f.scope.push({ room: r.name, work_types: [] });
  }

  async save() {
    await this.api.put(`/leads/${this.lead().id}/brief`, this.f, 'Brief saved');
    await this.done();
  }

  async confirm() {
    await this.api.post(`/leads/${this.lead().id}/brief/confirm`, { how: this.how }, 'Confirmation recorded');
    this.confirmDlg = false;
    await this.done();
  }

  copyAnswers() {
    const d = this.d();
    const text = d.questions.filter((q: any) => d.questionnaire.answers?.[q.id]).map((q: any) => `${q.label}: ${d.questionnaire.answers[q.id]}`).join('\n');
    this.f.notes = [this.f.notes, text].filter(Boolean).join('\n');
  }

  async questionnaire(email: boolean) {
    const r = await this.api.post(`/leads/${this.lead().id}/questionnaire`, { email_client: email }, email ? 'Link emailed (see the timeline for the result)' : 'Link created');
    if (!email) this.copy(this.origin + r.link);
    await this.done();
  }

  copy(text: string) {
    navigator.clipboard?.writeText(text).then(() => this.toast.add({ severity: 'success', summary: 'Copied', life: 1500 }));
  }

  async ballpark() {
    await this.api.post(`/leads/${this.lead().id}/ballpark`, { package: this.pkg }, 'Ballpark worked out');
    await this.done();
  }

  openPerson() {
    this.pf = { mode: 'new', name: '', phone: '', email: '', contact_id: null, role: null, main: false };
    this.personDlg = true;
  }

  async addPerson() {
    const { mode, ...p } = this.pf;
    const body = mode === 'existing' ? { contact_id: p.contact_id, role: p.role, main: p.main } : { name: p.name, phone: p.phone, email: p.email, role: p.role, main: p.main };
    await this.api.post(`/leads/${this.lead().id}/stakeholders`, body, 'Decision-maker added');
    this.personDlg = false;
    await this.done();
  }

  async setMain(p: any) {
    await this.api.put(`/leads/${this.lead().id}/stakeholders/${p.id}`, { main: true });
    await this.done();
  }

  async removePerson(p: any) {
    await this.api.del(`/leads/${this.lead().id}/stakeholders/${p.id}`, 'Removed');
    await this.done();
  }
}
