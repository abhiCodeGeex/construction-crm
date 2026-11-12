import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ConfirmationService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { TooltipModule } from 'primeng/tooltip';
import { Api, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

export const SEL_SEV: Record<string, 'secondary' | 'info' | 'success' | 'warn'> = {
  open: 'secondary', options_sent: 'warn', chosen: 'info', confirmed: 'info', ordered: 'info', delivered: 'info', installed: 'success',
};
const NEXT: Record<string, string> = { chosen: 'confirmed', confirmed: 'ordered', ordered: 'installed', delivered: 'installed' };

/** Selections on a project (Phase F block 3): each item with its allowance and options side by side; send the options,
 *  record the client's choice, then confirm -> order -> install. Over the allowance -> a change order. */
@Component({
  selector: 'app-project-selections',
  imports: [FormsModule, DatePipe, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TagModule, TooltipModule],
  template: `
    @if (data(); as d) {
      <div class="row-between mb wrap gap">
        <span class="small">Allowances <strong>{{ fmt(d.summary.allowance) }}</strong> · chosen <strong>{{ fmt(d.summary.chosen) }}</strong> ·
          difference <strong [class.c-bad]="d.summary.difference > 0" [class.c-good]="d.summary.difference < 0">{{ fmt(d.summary.difference) }}</strong>
          @if (d.summary.waiting) { · <span class="c-bad">{{ d.summary.waiting }} waiting on the client</span> }</span>
        <span class="row gap">
          @if (d.can_order_cost) { <p-button label="Margin" icon="pi pi-percentage" size="small" [text]="true" (onClick)="openMargin()" /> }
          @if (d.can_write) { <p-button label="Add item" icon="pi pi-plus" size="small" (onClick)="openNew()" /> }
        </span>
      </div>
      @for (s of d.selections; track s.id) {
        <div class="sel">
          <div class="row-between wrap gap">
            <div><strong>{{ s.item }}</strong> <span class="muted small">@if (s.room) { {{ s.room }} · } {{ s.stage_name }}</span>
              <div class="small">Allowance {{ fmt(s.allowance) }}
                @if (s.chosen) { · chosen {{ s.chosen.name }} {{ fmt(s.chosen.price) }} · <span [class.c-bad]="s.difference > 0" [class.c-good]="s.difference < 0">{{ s.difference > 0 ? '+' : '' }}{{ fmt(s.difference) }}</span> }
                @if (s.due_date && !s.chosen) { · choose by <span [class.c-bad]="s.overdue">{{ s.due_date | date: 'd MMM y' }}</span> }
                @if (s.co_number) { · change order {{ s.co_number }} }
                @if (s.deposit) { · deposit {{ s.deposit.number || 'draft' }} <span [class.c-good]="s.deposit.status === 'paid'" [class.c-warn]="s.deposit.status !== 'paid'">{{ s.deposit.status }}</span> }</div>
              @if (s.choice) { <div class="small muted">Chosen by {{ s.choice.name }} ({{ s.choice.method }}) {{ s.choice.date | date: 'd MMM' }}</div> }</div>
            <span class="row gap"><p-tag [value]="d.statuses[s.status]" [severity]="sev[s.status]" />
              @if (d.can_write) {
                @if (s.status === 'open' || s.status === 'options_sent') {
                  <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="openEdit(s)" ariaLabel="Edit" pTooltip="Edit" />
                  @if (s.options.length) { <p-button [label]="s.status === 'open' ? 'Send options' : 'Send again'" size="small" [text]="true" (onClick)="send(s)" /> }
                }
                @if ((s.status === 'chosen' || s.status === 'confirmed') && s.difference && !s.co_id) { <p-button [label]="s.difference > 0 ? 'Change order' : 'Credit the client'" size="small" [text]="true" (onClick)="toCo(s)" /> }
                @if ((s.status === 'chosen' || s.status === 'confirmed') && d.can_order_cost && !s.deposit && s.chosen?.price) { <p-button label="Ask for deposit" size="small" [text]="true" (onClick)="askDeposit(s)" /> }
                @if (s.status === 'ordered' || s.status === 'delivered') { <p-button label="Installation checklist" icon="pi pi-check-square" size="small" (onClick)="openInstall(s)" /> }
                @else if (NEXT[s.status]) { <p-button [label]="'Mark ' + d.statuses[NEXT[s.status]].toLowerCase()" size="small" (onClick)="advance(s)" /> }
                @if (s.status === 'chosen' || s.status === 'confirmed') { <p-button label="Reopen" size="small" [text]="true" severity="secondary" (onClick)="askReopen(s)" /> }
              }</span>
          </div>
          @if (s.options.length) {
            <div class="opts">
              @for (o of s.options; track o.id) {
                <div class="opt" [class.picked]="o.id === s.chosen_option_id">
                  @if (o.file_key) { <img [src]="'/api/files/' + o.file_key" alt="" /> }
                  <strong>{{ o.name }}</strong>
                  <div class="small muted">@if (o.brand) { {{ o.brand }} · } {{ o.qty }} {{ o.unit || '' }} · {{ o.lead_days }} days lead</div>
                  <div>{{ fmt(o.price) }}@if (o.cost !== undefined) { <span class="small muted"> · cost {{ fmt(o.cost) }}</span> }</div>
                  @if (o.supplier_name) { <div class="small muted">{{ o.supplier_name }}</div> }
                  @if (d.can_write && (s.status === 'open' || s.status === 'options_sent')) { <p-button label="Client chose this" size="small" [text]="true" (onClick)="openChoice(s, o)" /> }
                </div>
              }
            </div>
          }
        </div>
      } @empty { <p class="muted">No selections yet. Add the finishes and fittings the client needs to choose.</p> }
    }

    <p-dialog [header]="f.id ? 'Edit selection' : 'Add a selection'" [modal]="true" [(visible)]="dlg" [style]="{ width: '52rem' }" [breakpoints]="{ '840px': '98vw' }">
      <div class="stack">
        <div class="grid3">
          <label class="field req"><span>Item</span><input pInputText [(ngModel)]="f.item" placeholder="Kitchen countertop" fluid /></label>
          <label class="field"><span>Room</span><input pInputText [(ngModel)]="f.room" fluid /></label>
          <label class="field req"><span>Stage</span><p-select [options]="data()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="f.stage_id" fluid appendTo="body" /></label>
        </div>
        <div class="grid2">
          <label class="field"><span>Allowance (client price)</span><p-inputnumber [(ngModel)]="f.allowance" [min]="0" fluid /></label>
          <label class="field"><span>Choose by</span><input pInputText type="date" [(ngModel)]="f.due_date" fluid /><small class="muted">Empty: stage start minus the longest lead time</small></label>
        </div>
        <div class="small muted">Options</div>
        @for (o of f.options; track $index; let i = $index) {
          <div class="opt-row">
            <input pInputText placeholder="Option" [(ngModel)]="o.name" />
            <input pInputText placeholder="Brand" [(ngModel)]="o.brand" />
            <p-inputnumber placeholder="Qty" [(ngModel)]="o.qty" [min]="0" [maxFractionDigits]="2" [inputStyle]="{ width: '100%' }" />
            <p-inputnumber placeholder="Cost / unit" [(ngModel)]="o.unit_cost" [min]="0" [inputStyle]="{ width: '100%' }" />
            <p-inputnumber placeholder="Price / unit" [(ngModel)]="o.unit_price" [min]="0" [inputStyle]="{ width: '100%' }" />
            <p-inputnumber placeholder="Lead days" [(ngModel)]="o.lead_days" [min]="0" [max]="365" [inputStyle]="{ width: '100%' }" />
            <label class="p-button p-button-text p-button-sm file-pick" pTooltip="Photo"><i class="pi" [class.pi-image]="!o.file_key" [class.pi-check]="o.file_key"></i>
              <input type="file" accept="image/*" (change)="photo(o, $event)" /></label>
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.options.splice(i, 1)" ariaLabel="Remove option" />
          </div>
        }
        <p-button label="Add option" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.options.push({ name: '', qty: 1, unit_cost: null, unit_price: null, lead_days: 0 })" />
        <div class="row right"><p-button label="Save" icon="pi pi-check" [disabled]="!f.item?.trim() || !f.stage_id" (onClick)="save()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Client's choice" [modal]="true" [(visible)]="chDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p class="m0"><strong>{{ choiceOpt?.name }}</strong> · {{ fmt(choiceOpt?.price) }}</p>
        <label class="field req"><span>Who chose</span><input pInputText [(ngModel)]="cf.name" fluid /></label>
        <div class="grid2">
          <label class="field req"><span>How</span><p-select [options]="data()?.methods ?? []" [(ngModel)]="cf.method" fluid appendTo="body" /></label>
          <label class="field"><span>Date</span><input pInputText type="date" [(ngModel)]="cf.date" fluid /></label>
        </div>
        <div class="row right"><p-button label="Record" [disabled]="!cf.name?.trim() || !cf.method" (onClick)="saveChoice()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Reopen the choice" [modal]="true" [(visible)]="roDlg" [style]="{ width: '26rem' }">
      <div class="stack">
        <label class="field req"><span>Why</span><input pInputText [(ngModel)]="reason" fluid /></label>
        <div class="row right"><p-button label="Reopen" [disabled]="!reason.trim()" (onClick)="reopen()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Installation checklist" [modal]="true" [(visible)]="instDlg" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        @for (c of inst.checks; track c.text) { <label class="check"><p-checkbox [(ngModel)]="c.done" [binary]="true" [ariaLabel]="c.text" /> {{ c.text }}</label> }
        <label class="field"><span>Photos of the installed item</span><input type="file" accept="image/*" capture="environment" multiple (change)="instPhoto($event)" />
          @if (inst.photos.length) { <small class="muted">{{ inst.photos.length }} photo(s)</small> }</label>
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="inst.note" fluid /></label>
        <div class="row right"><p-button [label]="allTicked() ? 'Mark installed' : 'Save progress'" icon="pi pi-check" (onClick)="saveInstall()" /></div>
      </div>
    </p-dialog>
    <p-dialog header="Selection margin" [modal]="true" [(visible)]="marginDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '100vw' }">
      @if (margin(); as m) {
        <div class="stack">
          @for (r of m.rooms; track r.room) {
            <div><strong>{{ r.room }}</strong> <span class="small muted">cost {{ fmt(r.cost) }} · price {{ fmt(r.price) }} · margin {{ fmt(r.margin) }}@if (r.margin_pct !== null) { ({{ r.margin_pct }}%) }</span>
              @for (x of r.items; track x.item) { <div class="small">{{ x.item }}: {{ x.option }} — {{ fmt(x.cost) }} → {{ fmt(x.price) }}, <span [class.c-bad]="x.margin < 0">{{ fmt(x.margin) }}</span></div> }</div>
          } @empty { <p class="muted">No choices made yet.</p> }
          <div class="row-between"><strong>Project</strong><strong>{{ fmt(m.total.price) }} · margin {{ fmt(m.total.margin) }}@if (m.total.margin_pct !== null) { ({{ m.total.margin_pct }}%) }</strong></div>
        </div>
      }
    </p-dialog>
  `,
  styles: `
    .sel { border: 1px solid var(--border); border-radius: var(--radius); padding: .8rem 1rem; margin-bottom: .75rem; background: var(--surface); }
    .opts { display: grid; grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr)); gap: .6rem; margin-top: .6rem; }
    .opt { border: 1px solid var(--border); border-radius: 10px; padding: .55rem .65rem; }
    .opt.picked { border-color: var(--p-primary-color, #6366f1); box-shadow: 0 0 0 1px var(--p-primary-color, #6366f1); }
    .opt img { width: 100%; height: 6.5rem; object-fit: cover; border-radius: 6px; margin-bottom: .35rem; }
    .opt-row { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1.2fr) 4.5rem 6.5rem 6.5rem 5rem auto auto; gap: .35rem; align-items: center; }
    @media (max-width: 760px) { .opt-row { grid-template-columns: 1fr 1fr; } }
    .file-pick { position: relative; overflow: hidden; cursor: pointer; }
    .file-pick input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  `,
})
export class ProjectSelectionsComponent implements OnInit {
  projectId = input.required<string>();
  private api = inject(Api);
  private auth = inject(AuthService);
  private confirm = inject(ConfirmationService);
  data = signal<any>(null);
  sev = SEL_SEV;
  NEXT = NEXT;
  dlg = false; chDlg = false; roDlg = false;
  f: any = { options: [] };
  cf: any = {};
  choiceOpt: any = null;
  reason = '';
  private pending: any = null;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.data.set(await this.api.get(`/projects/${this.projectId()}/selections`));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  openNew() {
    this.f = { item: '', room: '', stage_id: null, allowance: 0, due_date: '', options: [{ name: '', qty: 1, unit_cost: null, unit_price: null, lead_days: 0 }] };
    this.dlg = true;
  }

  openEdit(s: any) {
    this.f = { id: s.id, item: s.item, room: s.room ?? '', stage_id: s.stage_id, allowance: s.allowance, due_date: s.due_date ?? '',
      options: s.options.map((o: any) => ({ id: o.id, name: o.name, brand: o.brand, qty: o.qty, unit: o.unit, unit_cost: o.unit_cost,
        unit_price: o.unit_price, lead_days: o.lead_days, supplier_id: o.supplier_id, rate_id: o.rate_id, file_key: o.file_key })) };
    this.dlg = true;
  }

  async photo(o: any, ev: Event) {
    const file = (ev.target as HTMLInputElement).files?.[0];
    if (file) o.file_key = (await this.api.upload(file)).key;
  }

  async save() {
    const { id, ...body } = this.f;
    body.options = body.options.filter((o: any) => o.name?.trim());
    body.due_date = body.due_date || null;
    if (id) await this.api.put(`/selections/${id}`, body, 'Saved');
    else await this.api.post(`/projects/${this.projectId()}/selections`, body, 'Selection added');
    this.dlg = false;
    await this.load();
  }

  async send(s: any) {
    await this.api.post(`/selections/${s.id}/send`, {}, 'Options sent to the client');
    await this.load();
  }

  openChoice(s: any, o: any) {
    this.pending = s;
    this.choiceOpt = o;
    this.cf = { option_id: o.id, name: '', method: 'In person', date: new Date().toISOString().slice(0, 10) };
    this.chDlg = true;
  }

  async saveChoice() {
    await this.api.post(`/selections/${this.pending.id}/choice`, this.cf, 'Choice recorded');
    this.chDlg = false;
    await this.load();
  }

  advance(s: any) {
    const next = NEXT[s.status];
    const go = async () => { await this.api.post(`/selections/${s.id}/status`, { status: next }, 'Updated'); await this.load(); };
    if (next === 'ordered') {
      const noDeposit = s.deposit?.status !== 'paid';
      this.confirm.confirm({ header: `Order ${s.item}?`, icon: 'pi pi-shopping-cart', accept: go,
        message: "It goes on the supplier's draft purchase order (or a purchase request when it has no supplier)."
          + (noDeposit ? " The client's deposit for it is not paid yet." : '') });
    } else go();
  }

  // Phase I: installation checklist (all ticked -> installed)
  instDlg = false;
  allTicked = () => this.inst.checks.length && this.inst.checks.every((c: any) => c.done);
  inst: any = { checks: [], photos: [] };
  private instSel: any = null;

  async openInstall(s: any) {
    this.instSel = s;
    const texts: string[] = s.installation?.checks?.map((c: any) => c.text) ?? await this.api.get('/install-checks');
    const done = Object.fromEntries((s.installation?.checks ?? []).map((c: any) => [c.text, c.done]));
    this.inst = { checks: texts.map((text) => ({ text, done: !!done[text] })), photos: (s.installation?.photos ?? []).map((p: any) => p.key),
      note: s.installation?.note ?? '' };
    this.instDlg = true;
  }

  async instPhoto(ev: Event) {
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) this.inst.photos.push((await this.api.upload(file)).key);
  }

  async saveInstall() {
    const r = await this.api.post(`/selections/${this.instSel.id}/install`, this.inst, 'Saved');
    this.instDlg = false;
    if (r.status === 'installed') this.confirm.confirm({ header: `${r.item} installed`, icon: 'pi pi-check', message: 'Every check is ticked.', acceptLabel: 'OK', rejectVisible: false });
    await this.load();
  }

  // Phase I: selection margin by room
  marginDlg = false;
  margin = signal<any>(null);

  async openMargin() {
    this.margin.set(await this.api.get(`/projects/${this.projectId()}/selections/margin`));
    this.marginDlg = true;
  }

  async askDeposit(s: any) {
    const inv = await this.api.post(`/selections/${s.id}/deposit`, {}, 'Deposit invoice drafted');
    this.confirm.confirm({ header: 'Deposit invoice drafted', icon: 'pi pi-check', acceptLabel: 'OK', rejectVisible: false,
      message: `${this.fmt(inv.total)} — send it to the client from the Money tab.` });
    await this.load();
  }

  async toCo(s: any) {
    const r = await this.api.post(`/selections/${s.id}/change-order`, {}, 'Change order drafted');
    this.confirm.confirm({ header: `${r.change_order.number} drafted`, icon: 'pi pi-check', message: 'Price and send it from the Change orders tab.',
      acceptLabel: 'OK', rejectVisible: false });
    await this.load();
  }

  askReopen(s: any) {
    this.pending = s;
    this.reason = '';
    this.roDlg = true;
  }

  async reopen() {
    await this.api.post(`/selections/${this.pending.id}/reopen`, { reason: this.reason }, 'Reopened');
    this.roDlg = false;
    await this.load();
  }
}
