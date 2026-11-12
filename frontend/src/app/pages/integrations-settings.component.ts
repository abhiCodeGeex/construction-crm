import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Phase K — Company settings → Integrations: hourly rates (timesheets), accounting (Tally, Zoho Books, QuickBooks,
 *  Xero), the WhatsApp assistant and the phone system. */
@Component({
  selector: 'app-integrations-settings',
  imports: [FormsModule, ButtonModule, InputNumberModule, InputTextModule, SelectModule, SelectButtonModule, ToggleSwitchModule],
  template: `
    <p-selectbutton class="mb block" [options]="parts" [(ngModel)]="part" optionLabel="label" optionValue="value" [allowEmpty]="false" (ngModelChange)="load()" />
    <div class="stack narrow">
      @switch (part) {
        @case ('rates') { @if (ts(); as ts) {
          <label class="field"><span>Working hours per day (for utilisation)</span><p-inputnumber [(ngModel)]="ts.capacity_hours" [min]="1" [max]="16" /></label>
          <table class="t"><tr><th>Person</th><th>Hourly cost</th><th>Bill rate (hourly fees)</th></tr>
            @for (p of ts.people; track p.id) { <tr><td>{{ p.name }} <span class="small muted">{{ p.role }}</span></td>
              <td><p-inputnumber [(ngModel)]="p.cost" [min]="0" [ariaLabel]="'Cost for ' + p.name" /></td><td><p-inputnumber [(ngModel)]="p.bill" [min]="0" [ariaLabel]="'Bill rate for ' + p.name" /></td></tr> }</table>
          <div class="row right"><p-button label="Save" (onClick)="saveRates()" /></div> } }
        @case ('books') { @if (acc(); as a) {
          <label class="field"><span>Accounting</span><p-select [options]="providerOpts(a.providers)" optionLabel="label" optionValue="value" [(ngModel)]="a.provider" appendTo="body" /></label>
          @if (['zoho', 'quickbooks', 'xero'].includes(a.provider)) {
            <p class="small muted m0">From the provider's developer console: create an app, authorise it once, and paste the refresh token here.</p>
            <div class="grid2"><label class="field"><span>Client id</span><input pInputText [(ngModel)]="a.client_id" /></label>
              <label class="field"><span>Client secret {{ a.client_secret_set ? '(saved)' : '' }}</span><input pInputText type="password" [(ngModel)]="secret" /></label>
              <label class="field"><span>Refresh token {{ a.refresh_token_set ? '(saved)' : '' }}</span><input pInputText type="password" [(ngModel)]="refresh" /></label>
              <label class="field"><span>{{ a.provider === 'zoho' ? 'Organisation id' : a.provider === 'quickbooks' ? 'Company (realm) id' : 'Tenant id' }}</span><input pInputText [(ngModel)]="a.org_id" /></label>
              @if (a.provider === 'zoho') { <label class="field"><span>Zoho data centre</span><p-select [options]="['in', 'com', 'eu', 'com.au']" [(ngModel)]="a.region" appendTo="body" /></label> }</div>
            <label class="check"><p-toggleswitch [(ngModel)]="a.auto_sync" ariaLabel="Daily sync" /> Sync every night</label>
          }
          <details><summary class="small">Ledger names (to match your books)</summary>
            <div class="grid2">@for (k of ledgerKeys(a.ledgers); track k) { <label class="field"><span>{{ k }}</span><input pInputText [(ngModel)]="a.ledgers[k]" /></label> }</div></details>
          <div class="row right"><p-button label="Save" (onClick)="saveAcc()" /></div>
          <div class="row gap wrap"><input pInputText type="date" [(ngModel)]="from" aria-label="From" /><input pInputText type="date" [(ngModel)]="to" aria-label="To" />
            <p-button label="Download Tally XML" icon="pi pi-download" size="small" [outlined]="true" (onClick)="tally()" />
            @if (['zoho', 'quickbooks', 'xero', 'sandbox'].includes(a.provider)) { <p-button label="Sync now" icon="pi pi-sync" size="small" (onClick)="sync()" /> }</div>
          <p class="small m0">Synced {{ a.status.synced }} · failed {{ a.status.failed }} · exported to Tally {{ a.status.exported }}</p>
          @for (l of log(); track l.id) { @if (l.status === 'failed') { <div class="small c-bad">{{ l.kind }} {{ l.number }}: {{ l.error }}</div> } }
        } }
        @case ('assistant') { @if (ast(); as s) {
          <label class="field"><span>WhatsApp assistant</span><p-select [options]="[{ l: 'Off', v: 'off' }, { l: 'Answers from FAQs and project facts', v: 'faq' }, { l: 'Claude (AI) — uses your Anthropic API key', v: 'claude' }]"
            optionLabel="l" optionValue="v" [(ngModel)]="s.mode" appendTo="body" /></label>
          @if (s.mode === 'claude') { <div class="grid2"><label class="field"><span>Anthropic API key {{ s.api_key_set ? '(saved)' : '' }}</span><input pInputText type="password" [(ngModel)]="key" /></label>
            <label class="field"><span>Model</span><input pInputText [(ngModel)]="s.model" /></label></div>
            <p class="small muted m0">The client's question and their project's facts (progress, milestones, amount due — never internal costs) are sent to Anthropic to write the answer.</p> }
          <label class="field"><span>Reply when a person must take over</span><input pInputText [(ngModel)]="s.handoff_text" /></label>
          <span class="small">Frequently asked questions</span>
          @for (f of s.faqs; track $index; let i = $index) { <div class="row gap"><input pInputText [(ngModel)]="f.q" placeholder="Question" class="grow" aria-label="Question" />
            <input pInputText [(ngModel)]="f.a" placeholder="Answer" class="grow" aria-label="Answer" /><p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="s.faqs.splice(i, 1)" ariaLabel="Remove" /></div> }
          <p-button label="Add a question" icon="pi pi-plus" size="small" [text]="true" (onClick)="s.faqs.push({ q: '', a: '' })" />
          <div class="row right"><p-button label="Save" (onClick)="saveAs()" /></div>
          <div class="row gap"><input pInputText [(ngModel)]="tryText" placeholder="Try a question, e.g. how much is due?" class="grow" aria-label="Question to try" />
            <p-select [options]="clients()" optionLabel="name" optionValue="id" [(ngModel)]="tryContact" placeholder="As client" [filter]="true" appendTo="body" ariaLabel="Client" />
            <p-button label="Ask" size="small" [disabled]="!tryText.trim() || !tryContact" (onClick)="tryIt()" /></div>
          @if (tried(); as t) { <div class="small">{{ t.handoff ? 'Hands over to the team' : 'Answers' }} ({{ t.how }}): {{ t.answer || '—' }}</div> }
        } }
        @case ('phone') { @if (ph(); as p) {
          <label class="field"><span>Phone system</span><p-select [options]="['off', 'twilio', 'exotel', 'sandbox']" [(ngModel)]="p.provider" appendTo="body" /></label>
          <label class="field"><span>Greeting</span><input pInputText [(ngModel)]="p.greeting" placeholder="Thank you for calling …" /></label>
          <span class="small">Menu</span>
          @for (m of p.menu; track $index; let i = $index) { <div class="row gap"><span>Press</span><input pInputText [(ngModel)]="m.digit" style="width:3rem" aria-label="Digit" />
            <input pInputText [(ngModel)]="m.label" class="grow" aria-label="Label" /><p-select [options]="roles" [(ngModel)]="m.role" appendTo="body" ariaLabel="Role" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="p.menu.splice(i, 1)" ariaLabel="Remove" /></div> }
          <p-button label="Add an option" icon="pi pi-plus" size="small" [text]="true" (onClick)="p.menu.push({ digit: '', label: '', role: 'pm' })" />
          <label class="check"><p-toggleswitch [(ngModel)]="p.record" ariaLabel="Record calls" /> Record calls</label>
          <div class="row right"><p-button label="Save" (onClick)="savePhone()" /></div>
          @if (p.webhook_incoming) { <p class="small m0">Incoming-call webhook: <code>{{ origin }}{{ p.webhook_incoming }}</code><br />Exotel connect applet URL: <code>{{ origin }}{{ p.exotel_dial_url }}</code></p> }
          <p class="small muted m0">Calls are put through to the person in that role on the caller's own project, and logged; staff need a mobile number on their profile.</p>
        } }
      }
    </div>
  `,
  styles: `.narrow { max-width: 50rem; } .t { width: 100%; border-collapse: collapse; } .t td, .t th { border-bottom: 1px solid var(--border); padding: .3rem; text-align: left; }
    code { word-break: break-all; }`,
})
export class IntegrationsSettingsComponent {
  private api = inject(Api);
  private auth = inject(AuthService);
  role = this.auth.user()?.role;
  parts = [{ label: 'Hourly rates', value: 'rates' }, { label: 'Accounting', value: 'books' }, { label: 'WhatsApp assistant', value: 'assistant' }, { label: 'Phone', value: 'phone' }];
  part = 'rates';
  roles = ['owner', 'pm', 'sales', 'accounts', 'designer', 'site', 'procurement'];
  ts = signal<any>(null); acc = signal<any>(null); ast = signal<any>(null); ph = signal<any>(null);
  log = signal<any[]>([]); clients = signal<any[]>([]); tried = signal<any>(null);
  secret = ''; refresh = ''; key = ''; tryText = ''; tryContact: string | null = null;
  from = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  to = new Date().toISOString().slice(0, 10);
  origin = location.origin;

  providerOpts = (p: Record<string, string>) => Object.entries(p).map(([value, label]) => ({ value, label }));
  ledgerKeys = (l: Record<string, string>) => Object.keys(l);

  async ngOnInit() {
    await this.load();
  }

  async load() {
    if (this.part === 'rates') this.ts.set(await this.api.get('/settings/timesheets'));
    if (this.part === 'books') {
      this.acc.set(await this.api.get('/settings/accounting'));
      this.log.set(await this.api.get('/accounting/log?status=failed'));
    }
    if (this.part === 'assistant') {
      this.ast.set(await this.api.get('/settings/assistant'));
      const c = await this.api.get('/contacts');
      this.clients.set((Array.isArray(c) ? c : c.items ?? []).filter((x: any) => (x.types ?? []).includes('client')));
    }
    if (this.part === 'phone') this.ph.set(await this.api.get('/settings/phone'));
  }

  async saveRates() {
    const ts = this.ts();
    await this.api.put('/settings/timesheets', { capacity_hours: ts.capacity_hours, rates: Object.fromEntries(ts.people.map((p: any) => [p.id, { cost: p.cost, bill: p.bill }])) }, 'Saved');
  }

  async saveAcc() {
    const a = this.acc();
    this.acc.set(await this.api.put('/settings/accounting', { provider: a.provider, ledgers: a.ledgers, client_id: a.client_id, org_id: a.org_id, region: a.region,
      auto_sync: a.auto_sync, client_secret: this.secret || undefined, refresh_token: this.refresh || undefined }, 'Saved'));
    this.secret = this.refresh = '';
  }

  tally() {
    this.api.download(`/accounting/tally.xml?from=${this.from}&to=${this.to}`, `tally-${this.from}-to-${this.to}.xml`);
  }

  async sync() {
    const r = await this.api.post('/accounting/sync', { from: this.from, to: this.to }, 'Sync finished');
    alert(`Sent ${r.sent}, failed ${r.failed}, already there ${r.already}`);
    await this.load();
  }

  async saveAs() {
    const s = this.ast();
    this.ast.set(await this.api.put('/settings/assistant', { mode: s.mode, model: s.model, handoff_text: s.handoff_text, faqs: s.faqs, api_key: this.key || undefined }, 'Saved'));
    this.key = '';
  }

  async tryIt() {
    this.tried.set(await this.api.post('/assistant/try', { contact_id: this.tryContact, text: this.tryText }));
  }

  async savePhone() {
    const p = this.ph();
    this.ph.set(await this.api.put('/settings/phone', { provider: p.provider, greeting: p.greeting, menu: p.menu, record: p.record }, 'Saved'));
  }
}
