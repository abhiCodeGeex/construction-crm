import { Component, OnInit, computed, inject, input, signal, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { CHANNEL_ICON, FollowupDialogComponent } from '../../shared/followup-dialog.component';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ConfirmationService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { MultiSelectModule } from 'primeng/multiselect';
import { PasswordModule } from 'primeng/password';
import { RatingModule } from 'primeng/rating';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { TooltipModule } from 'primeng/tooltip';
import { Api, STATUS_SEVERITY, label, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { TYPE_LABEL } from './contacts.component';

const PORTAL_ROLE: Record<string, string> = { client: 'client', developer: 'client', supplier: 'vendor', subcontractor: 'subcontractor',
  consultant: 'consultant', architect: 'consultant', contractor: 'subcontractor', authority: 'consultant' };

@Component({
  selector: 'app-contact-detail',
  imports: [FormsModule, RouterLink, ButtonModule, CardModule, DialogModule, InputNumberModule, InputTextModule, MessageModule,
    MultiSelectModule, PasswordModule, RatingModule, SelectModule, TableModule, TabsModule, TagModule, TextareaModule, TooltipModule, FollowupDialogComponent, DatePipe],
  template: `
    @if (c(); as c) {
      <div class="page-head">
        <div>
          <a routerLink="/app/contacts" class="small"><i class="pi pi-arrow-left"></i> Contacts</a>
          <h1><i [class]="c.kind === 'person' ? 'pi pi-user' : 'pi pi-building'" class="mr muted"></i>{{ c.name }}</h1>
          <div class="row gap">
            @for (t of c.types; track t) { <p-tag [value]="typeLabel[t]" severity="secondary" /> }
            @if (c.compliance_alert) { <p-tag [value]="c.compliance_alert === 'expired' ? 'Compliance expired' : 'Compliance expiring'" [severity]="sev[c.compliance_alert]" icon="pi pi-exclamation-triangle" /> }
            @if (c.org_name) { <span class="muted">{{ c.designation }} at <a [routerLink]="['/app/contacts', c.org_id]">{{ c.org_name }}</a></span> }
            @if (c.whatsapp_opt_in) { <p-tag value="WhatsApp: opted in" severity="success" icon="pi pi-whatsapp" [pTooltip]="'Since ' + (c.whatsapp_opt_in.at | date: 'd MMM y') + ' · ' + c.whatsapp_opt_in.how" /> }
            @else if (c.whatsapp_opt_out) { <p-tag value="WhatsApp: opted out" severity="secondary" /> }
          </div>
        </div>
        <div class="row gap">
          @if (canEdit()) {
            @if (!h()?.portal_user && auth.can('users', 'rw')) { <p-button label="Portal access" icon="pi pi-globe" [outlined]="true" (onClick)="openInvite()" /> }
            @if (c.phone) {
              @if (c.whatsapp_opt_in) {
                <p-button label="WhatsApp" icon="pi pi-whatsapp" [outlined]="true" (onClick)="openWa()" />
                <p-button label="Opt out" size="small" [text]="true" severity="secondary" (onClick)="setOpt(false)" />
              } @else { <p-button label="WhatsApp opt-in" icon="pi pi-whatsapp" [text]="true" (onClick)="optDlg = true" /> }
            }
            <p-button label="Delete" icon="pi pi-trash" severity="danger" [text]="true" (onClick)="remove()" />
            <p-button label="Save" icon="pi pi-check" [loading]="busy()" (onClick)="save()" />
          }
        </div>
      </div>
      @if (h()?.portal_user; as pu) { <p-message severity="info" icon="pi pi-globe" styleClass="mb" text="Portal login: {{ pu.email }} ({{ pu.role }}){{ pu.active === false ? ' — inactive' : '' }}" /> }

      <p-tabs value="details" [scrollable]="true">
        <p-tablist>
          <p-tab value="details"><i class="pi pi-id-card mr"></i>Details</p-tab>
          <p-tab value="finance"><i class="pi pi-wallet mr"></i>Tax & bank</p-tab>
          <p-tab value="compliance"><i class="pi pi-verified mr"></i>Compliance ({{ c.compliance?.length || 0 }})</p-tab>
          <p-tab value="projects"><i class="pi pi-building mr"></i>Projects together ({{ h()?.projects?.length || 0 }})</p-tab>
          <p-tab value="activity" (click)="loadTimeline()"><i class="pi pi-clock mr"></i>Activity</p-tab>
          <p-tab value="relations"><i class="pi pi-share-alt mr"></i>Relationships</p-tab>
        </p-tablist>
        <p-tabpanels>
          <p-tabpanel value="details">
            <div class="grid2 top">
              <div class="stack">
                <label class="field"><span>Name</span><input pInputText [(ngModel)]="c.name" [disabled]="!canEdit()" fluid /></label>
                <label class="field"><span>Types</span>
                  <p-multiselect [options]="typeOptions" [(ngModel)]="c.types" optionLabel="label" optionValue="value" display="chip" [disabled]="!canEdit()" fluid /></label>
                @if (c.kind === 'person') {
                  <div class="grid2">
                    <label class="field"><span>Company</span><p-select [options]="companies()" [(ngModel)]="c.org_id" optionLabel="name" optionValue="id"
                                                                    [filter]="true" [showClear]="true" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Designation</span><input pInputText [(ngModel)]="c.designation" [disabled]="!canEdit()" fluid /></label>
                  </div>
                }
                <div class="grid2">
                  <label class="field"><span>Trade category</span><input pInputText [(ngModel)]="c.trade_category" placeholder="e.g. Electrical, Tiles" [disabled]="!canEdit()" fluid /></label>
                  <div class="field"><span>Rating</span><p-rating [(ngModel)]="c.rating" [readonly]="!canEdit()" /></div>
                </div>
                <label class="field"><span>Notes</span><textarea pTextarea rows="4" [(ngModel)]="c.notes" [disabled]="!canEdit()" fluid></textarea></label>
              </div>
              <div class="stack">
                <div class="grid2">
                  <label class="field"><span>Phone</span><input pInputText [(ngModel)]="c.phone" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>Alternate phone</span><input pInputText [(ngModel)]="c.alt_phone" [disabled]="!canEdit()" fluid /></label>
                </div>
                <div class="grid2">
                  <label class="field"><span>Email</span><input pInputText [(ngModel)]="c.email" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>Website</span><input pInputText [(ngModel)]="c.website" [disabled]="!canEdit()" fluid /></label>
                </div>
                <label class="field"><span>Address</span><input pInputText [(ngModel)]="c.address" [disabled]="!canEdit()" fluid /></label>
                <div class="grid3">
                  <label class="field"><span>City</span><input pInputText [(ngModel)]="c.city" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>State</span><input pInputText [(ngModel)]="c.state" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>PIN code</span><input pInputText [(ngModel)]="c.pincode" [disabled]="!canEdit()" fluid /></label>
                </div>
                <label class="field"><span>Referred by</span><p-select [options]="others()" [(ngModel)]="c.referred_by" optionLabel="name" optionValue="id"
                                                                  [filter]="true" [showClear]="true" [disabled]="!canEdit()" fluid /></label>
              </div>
            </div>
          </p-tabpanel>

          <p-tabpanel value="finance">
            <div class="grid2 top">
              <p-card>
                <ng-template #title>Tax & trade account</ng-template>
                <div class="stack">
                  <div class="grid2">
                    <label class="field"><span>GSTIN</span><input pInputText [(ngModel)]="c.gstin" placeholder="29ABCDE1234F1Z5" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>PAN</span><input pInputText [(ngModel)]="c.pan" placeholder="ABCDE1234F" [disabled]="!canEdit()" fluid /></label>
                  </div>
                  <div class="grid2">
                    <label class="field"><span>Trade account no.</span><input pInputText [(ngModel)]="c.trade_account_no" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Trade discount %</span><p-inputnumber [(ngModel)]="c.discount_pct" [min]="0" [max]="100" [maxFractionDigits]="2" suffix="%" [disabled]="!canEdit()" fluid /></label>
                  </div>
                </div>
              </p-card>
              <p-card>
                <ng-template #title>Bank details <small class="muted">(for vendor payments)</small></ng-template>
                @if (c.bank?.masked) {
                  <p-message severity="secondary" icon="pi pi-lock" text="Bank details are visible only to roles that manage finance or procurement." styleClass="mb" />
                }
                <div class="stack">
                  <label class="field"><span>Account name</span><input pInputText [(ngModel)]="bank().account_name" [disabled]="!canEditBank()" fluid /></label>
                  <div class="grid2">
                    <label class="field"><span>Account number</span><input pInputText [(ngModel)]="bank().account_no" [disabled]="!canEditBank()" fluid /></label>
                    <label class="field"><span>IFSC</span><input pInputText [(ngModel)]="bank().ifsc" [placeholder]="c.bank?.masked ? '' : 'HDFC0001234'" [disabled]="!canEditBank()" fluid /></label>
                  </div>
                  <div class="grid2">
                    <label class="field"><span>Bank</span><input pInputText [(ngModel)]="bank().bank_name" [disabled]="!canEditBank()" fluid /></label>
                    <label class="field"><span>Branch</span><input pInputText [(ngModel)]="bank().branch" [disabled]="!canEditBank()" fluid /></label>
                  </div>
                </div>
              </p-card>
            </div>
          </p-tabpanel>

          <p-tabpanel value="compliance">
            <div class="row-between mb">
              <span class="muted">Insurance, licences and certificates. Alerts start {{ warnDays }} days before expiry.</span>
              @if (canEdit()) { <p-button label="Add document" icon="pi pi-plus" size="small" (onClick)="addDoc()" /> }
            </div>
            <p-table [value]="c.compliance" size="small">
              <ng-template #header><tr><th>Type</th><th>Name</th><th>Number</th><th>Issuer</th><th>Issued</th><th>Expiry</th><th>Status</th><th>File</th><th></th></tr></ng-template>
              <ng-template #body let-d let-i="rowIndex">
                <tr>
                  <td><p-select placeholder="Type" [options]="complianceTypes" [(ngModel)]="d.type" [disabled]="!canEdit()" appendTo="body" /></td>
                  <td><input placeholder="Document name" pInputText [(ngModel)]="d.name" [disabled]="!canEdit()" /></td>
                  <td><input placeholder="Number" pInputText [(ngModel)]="d.number" [disabled]="!canEdit()" class="w-8" /></td>
                  <td><input placeholder="Issued by" pInputText [(ngModel)]="d.issuer" [disabled]="!canEdit()" class="w-8" /></td>
                  <td><input aria-label="Issue date" title="Issue date" pInputText type="date" [(ngModel)]="d.issue_date" [disabled]="!canEdit()" /></td>
                  <td><input aria-label="Expiry date" title="Expiry date" pInputText type="date" [(ngModel)]="d.expiry" [disabled]="!canEdit()" /></td>
                  <td>@if (d.status) { <p-tag [value]="label(d.status)" [severity]="sev[d.status]" /> }</td>
                  <td class="nowrap">
                    @if (d.file) { <p-button icon="pi pi-file" [text]="true" [rounded]="true" (onClick)="api.openFile(d.file.url)" [pTooltip]="d.file.name" /> }
                    @if (canEdit()) {
                      <label class="upload-btn"><i class="pi pi-upload"></i><input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx" (change)="attach(d, $event)" hidden /></label>
                    }
                  </td>
                  <td>@if (canEdit()) { <p-button icon="pi pi-trash" severity="danger" [text]="true" [rounded]="true" (onClick)="c.compliance.splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/> }</td>
                </tr>
              </ng-template>
              <ng-template #emptymessage><tr><td colspan="9" class="center muted">No compliance documents</td></tr></ng-template>
            </p-table>
            @if (canEdit()) { <p class="muted small">Remember to Save after editing documents.</p> }
          </p-tabpanel>

          <p-tabpanel value="projects">
            <p-table [value]="h()?.projects ?? []" size="small">
              <ng-template #header><tr><th>Project</th><th>Role(s) on this project</th><th>Status</th><th>Start</th><th class="right">Value</th></tr></ng-template>
              <ng-template #body let-p>
                <tr>
                  <td><a [routerLink]="['/app/projects', p.id]"><strong>{{ p.name }}</strong></a> <small class="muted">{{ p.code }}</small></td>
                  <td>@for (r of p.roles; track r) { <p-tag [value]="r" severity="info" styleClass="mr-xs" /> }</td>
                  <td><p-tag [value]="label(p.status)" [severity]="sev[p.status]" /></td>
                  <td>{{ p.start | date: 'd MMM y' }}</td>
                  <td class="right">{{ fmt(p.value) }}</td>
                </tr>
              </ng-template>
              <ng-template #emptymessage><tr><td colspan="5" class="center muted">Not on any project yet</td></tr></ng-template>
            </p-table>
          </p-tabpanel>

          <p-tabpanel value="activity">
            @if (auth.can('followups', 'rw')) { <div class="row right mb"><p-button label="Add follow-up" icon="pi pi-plus" size="small" (onClick)="fd().open({ type: 'contact', id: c.id, label: c.name })" /></div> }
            @for (r of timeline(); track $index) {
              <div class="timeline-row"><i [class]="r.kind === 'followup' ? 'pi pi-bell' : (chIcon[r.type] || 'pi pi-circle')" [class.c-bad]="r.kind === 'followup' && r.status === 'open' && r.due < todayIso"></i>
                <div class="grow"><div>{{ r.title }} @if (r.kind === 'followup') { <p-tag [value]="r.status" [severity]="r.status === 'done' ? 'success' : r.status === 'open' ? 'warn' : 'secondary'" /> }</div>
                  <small class="muted">{{ r.kind === 'followup' ? 'Follow-up · due ' + r.due : r.lead }} · {{ r.owner }} · {{ r.at | date: 'd MMM y' }}{{ r.outcome ? ' · ' + r.outcome : '' }}</small></div></div>
            } @empty { <p class="muted">No follow-ups or activity yet.</p> }
          </p-tabpanel>

          <p-tabpanel value="relations">
            <div class="grid2 top">
              <p-card>
                <ng-template #title>Referral history</ng-template>
                <p>Referred by: @if (h()?.referred_by; as r) { <a [routerLink]="['/app/contacts', r.id]">{{ r.name }}</a> } @else { <span class="muted">—</span> }</p>
                <h4>Contacts they referred</h4>
                @for (r of h()?.referred_contacts ?? []; track r.id) { <div><a [routerLink]="['/app/contacts', r.id]">{{ r.name }}</a></div> }
                @empty { <p class="muted small">None</p> }
                <h4>Projects they referred</h4>
                @for (p of h()?.referred_projects ?? []; track p.id) {
                  <div class="row-between"><a [routerLink]="['/app/projects', p.id]">{{ p.name }}</a><span>{{ fmt(p.value) }}</span></div>
                } @empty { <p class="muted small">None</p> }
                @if (h()?.referred_value) { <p class="mt"><strong>Total value referred: {{ fmt(h().referred_value) }}</strong></p> }
              </p-card>
              @if (c.kind === 'company') {
                <p-card>
                  <ng-template #title>People at {{ c.name }}</ng-template>
                  @for (p of h()?.people ?? []; track p.id) {
                    <div class="person-row"><a [routerLink]="['/app/contacts', p.id]"><strong>{{ p.name }}</strong></a>
                      <small class="muted">{{ p.designation }} {{ p.phone }} {{ p.email }}</small></div>
                  } @empty { <p class="muted small">No people linked. Create a person contact and choose this company.</p> }
                </p-card>
              }
            </div>
          </p-tabpanel>
        </p-tabpanels>
      </p-tabs>
    }

    <p-dialog header="WhatsApp opt-in" [modal]="true" [(visible)]="optDlg" [style]="{ width: '26rem' }">
      <div class="stack">
        <p class="m0 small">Only contacts who agreed get WhatsApp messages. How did they agree?</p>
        <p-select [options]="optHows" [(ngModel)]="optHow" fluid appendTo="body" />
        <div class="row right"><p-button label="Record opt-in" (onClick)="setOpt(true)" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Send on WhatsApp" [modal]="true" [(visible)]="waDlg" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        <p-select [options]="templates()" optionLabel="name" optionValue="id" [(ngModel)]="waTpl" (onChange)="previewWa()" placeholder="Choose a WhatsApp template" fluid appendTo="body" />
        <textarea pTextarea rows="4" [(ngModel)]="waText" fluid aria-label="Message"></textarea>
        <div class="row right"><p-button label="Send" icon="pi pi-send" [disabled]="!waTpl || !waText.trim() || waText.includes('{{')" (onClick)="sendWa()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Give portal access" [modal]="true" [(visible)]="invite" [style]="{ width: '28rem' }" [breakpoints]="{ '640px': '96vw' }">
      <form class="stack" (ngSubmit)="sendInvite()">
        <p class="muted small">Portal users are free and only see projects where this contact is on the team.</p>
        <label class="field"><span>Portal role</span><p-select name="role" [options]="portalRoles" [(ngModel)]="inv.role" fluid appendTo="body" /></label>
        <label class="field"><span>Person's name</span><input pInputText name="n" [(ngModel)]="inv.name" fluid /></label>
        <label class="field"><span>Login email</span><input pInputText name="e" [(ngModel)]="inv.email" fluid /></label>
        <label class="field"><span>Temporary password</span><p-password name="p" [(ngModel)]="inv.password" [toggleMask]="true" [feedback]="false" fluid appendTo="body" />
          <small class="hint" [class.ok]="(inv.password ?? '').length >= 6"><i class="pi" [class.pi-check-circle]="(inv.password ?? '').length >= 6" [class.pi-info-circle]="(inv.password ?? '').length < 6"></i> At least 6 characters</small></label>
        <div class="row gap right"><p-button type="submit" label="Create login" icon="pi pi-check" /></div>
      </form>
    </p-dialog>
    <app-followup-dialog (saved)="loadTimeline()" />
  `,
})
export class ContactDetailComponent implements OnInit {
  fd = viewChild.required(FollowupDialogComponent);
  timeline = signal<any[]>([]);
  chIcon = CHANNEL_ICON;
  todayIso = new Date().toISOString().slice(0, 10);

  async loadTimeline() {
    this.timeline.set(await this.api.get(`/contacts/${this.id()}/timeline`));
  }

  id = input.required<string>();
  auth = inject(AuthService);
  api = inject(Api);
  private router = inject(Router);
  private confirm = inject(ConfirmationService);
  c = signal<any>(null);
  h = signal<any>(null);
  all = signal<any[]>([]);
  busy = signal(false);
  companies = computed(() => this.all().filter((x) => x.kind === 'company' && x.id !== this.id()));
  others = computed(() => this.all().filter((x) => x.id !== this.id()));
  bank = computed(() => this.c()?.bank ?? {});
  canEdit = computed(() => this.auth.can('contacts', 'rw'));
  canEditBank = computed(() => this.canEdit() && (this.auth.can('finance', 'rw') || this.auth.can('procurement', 'rw')));
  typeLabel = TYPE_LABEL;
  typeOptions = Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }));
  complianceTypes = ['insurance', 'licence', 'certificate', 'other'];
  portalRoles = ['client', 'vendor', 'subcontractor', 'consultant'];
  sev = STATUS_SEVERITY;
  warnDays = 30;
  label = label;
  invite = false;
  inv: any = {};

  optDlg = false;
  waDlg = false;
  optHow = 'Verbal';
  optHows = ['Verbal', 'Written', 'WhatsApp message', 'Portal tick'];
  templates = signal<any[]>([]);
  waTpl: string | null = null;
  waText = '';

  async setOpt(on: boolean) {
    await this.api.put(`/contacts/${this.id()}/whatsapp`, on ? { opt_in: true, how: this.optHow } : { opt_in: false }, on ? 'Opted in' : 'Opted out');
    this.optDlg = false;
    await this.load();
  }

  async openWa() {
    this.templates.set((await this.api.get('/message_templates')).filter((x: any) => x.channel === 'whatsapp'));
    this.waTpl = null;
    this.waText = '';
    this.waDlg = true;
  }

  async previewWa() {
    if (this.waTpl) this.waText = (await this.api.post(`/message_templates/${this.waTpl}/render`, { contact_id: this.id() })).text;
  }

  async sendWa() {
    const m = await this.api.post(`/message_templates/${this.waTpl}/send`, { contact_id: this.id(), text: this.waText });
    this.waDlg = false;
    this.toast(m.status);
  }

  private toast(status: string) {
    this.confirm.confirm({ header: status === 'sent' ? 'Sent on WhatsApp' : status === 'logged' ? 'Logged (WhatsApp is not set up)' : 'Not sent',
      icon: 'pi pi-whatsapp', message: status === 'failed' ? 'Check the number and the opt-in.' : '', acceptLabel: 'OK', rejectVisible: false });
  }

  async ngOnInit() {
    await this.load();
    this.all.set(await this.api.get('/contacts'));
  }

  async load() {
    const c = await this.api.get(`/contacts/${this.id()}`);
    c.bank = c.bank ?? {};
    c.compliance = c.compliance ?? [];
    this.c.set(c);
    this.h.set(await this.api.get(`/contacts/${this.id()}/history`));
    if (this.auth.can('followups')) await this.loadTimeline();
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  addDoc() {
    this.c().compliance.push({ type: 'insurance', name: '', number: '', issuer: '', issue_date: null, expiry: null });
  }

  async attach(d: any, ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (file) d.file = await this.api.upload(file);
  }

  async save() {
    const c = { ...this.c() };
    if (!this.canEditBank()) delete c.bank;
    this.busy.set(true);
    try {
      await this.api.put(`/contacts/${this.id()}`, c, 'Contact saved');
      await this.load();
    } finally {
      this.busy.set(false);
    }
  }

  remove() {
    this.confirm.confirm({
      header: 'Delete contact?', message: `${this.c().name} will be removed. Contacts on projects cannot be deleted.`, icon: 'pi pi-trash',
      acceptButtonProps: { label: 'Delete', severity: 'danger' }, rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: async () => {
        await this.api.del(`/contacts/${this.id()}`, 'Contact deleted');
        this.router.navigateByUrl('/app/contacts');
      },
    });
  }

  openInvite() {
    const c = this.c();
    this.inv = { role: PORTAL_ROLE[c.types?.[0]] ?? 'client', name: c.name, email: c.email ?? '', password: '', contact_id: c.id };
    this.invite = true;
  }

  async sendInvite() {
    await this.api.post('/users', this.inv, 'Portal login created');
    this.invite = false;
    await this.load();
  }
}
