import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Settings → Subscription and Support (Phase I block 6): the company's plan, usage, invoices, plan change, coupon,
 *  cancel, data export; support tickets for everyone. */
@Component({
  selector: 'app-subscription',
  imports: [DatePipe, FormsModule, ButtonModule, CardModule, InputTextModule, SelectButtonModule, SelectModule, TagModule, TextareaModule],
  template: `
    @if (isOwner) {
      @if (s(); as s) {
        <div class="grid2 top">
          <p-card header="Your plan">
            <div><strong>{{ s.plan?.name }}</strong> · {{ s.billing_cycle }} · <p-tag [value]="s.status" /></div>
            @if (s.status === 'trial' && s.trial_ends) { <div class="small">Free trial until {{ s.trial_ends | date: 'mediumDate' }}</div> }
            @if (s.next_renewal) { <div class="small">Renews {{ s.next_renewal | date: 'mediumDate' }}</div> }
            @if (s.coupon?.months_left) { <div class="small c-good">Coupon {{ s.coupon.code }}: {{ s.coupon.percent }}% off for {{ s.coupon.months_left }} more invoice(s)</div> }
            <div class="small mt-xs">Users {{ s.usage.users }}@if (s.limits.users) { / {{ s.limits.users }} } · active projects {{ s.usage.projects }}@if (s.limits.projects) { / {{ s.limits.projects }} }
              · storage {{ gb(s.usage.storage_bytes) }} / {{ s.limits.storage_gb }} GB · WhatsApp {{ s.usage.whatsapp_messages }}@if (s.limits.whatsapp) { / {{ s.limits.whatsapp }} }</div>
            @for (n of s.near_limit; track n.what) { <div class="small c-warn">Close to your {{ n.what.replace('_', ' ') }} limit ({{ n.used }} of {{ n.limit }})</div> }
            <div class="small muted mt-xs">Site workers on WhatsApp and portal users (clients, suppliers, subcontractors) are free.</div>
          </p-card>
          <p-card header="Change plan">
            <div class="stack">
              <p-select [options]="s.plans" optionLabel="name" optionValue="code" [(ngModel)]="planCode" fluid />
              <p-selectbutton [options]="cycles" [(ngModel)]="cycle" optionLabel="label" optionValue="value" [allowEmpty]="false" />
              @if (pick(); as p) { <div class="small">{{ inr(cycle === 'yearly' ? p.price_yearly : p.price_monthly) }} + 18% GST {{ cycle === 'yearly' ? 'a year (2 months free)' : 'a month' }}
                · {{ p.max_users ?? 'unlimited' }} users · {{ p.max_projects ?? 'unlimited' }} projects · {{ p.max_modules === 3 || !p.max_modules ? 'all modules' : p.max_modules + ' module' }}</div> }
              <input pInputText [(ngModel)]="coupon" placeholder="Coupon code (optional)" />
              <div class="row right"><p-button label="Change" [disabled]="!planCode" (onClick)="change()" /></div>
              <p class="small muted m0">The change starts now; the unused part of your current plan is credited on the new invoice.</p>
            </div>
          </p-card>
        </div>
        <p-card header="Add-ons" styleClass="mt">
          <div class="row gap wrap">
            <label class="field"><span>Extra users ({{ inr(s.addon_prices.extra_user) }}/user/month)</span><input pInputText type="number" min="0" [(ngModel)]="add.extra_users" /></label>
            <label class="field"><span>Extra storage, GB ({{ inr(s.addon_prices.storage_100gb) }}/100 GB/month)</span><input pInputText type="number" min="0" step="100" [(ngModel)]="add.extra_storage_gb" /></label>
            <label class="field"><span>Extra WhatsApp messages ({{ inr(s.addon_prices.whatsapp_1000) }}/1,000/month)</span><input pInputText type="number" min="0" step="1000" [(ngModel)]="add.extra_whatsapp" /></label>
          </div>
          <div class="row-between"><span class="small muted">Billed with your next invoice, plus GST.</span><p-button label="Save add-ons" size="small" (onClick)="saveAddons()" /></div>
        </p-card>
        <p-card header="Automatic payment" styleClass="mt">
          @if (ap(); as a) {
            @if (a.autopay?.status === 'active') {
              <div class="row-between wrap gap"><span class="small c-good"><i class="pi pi-check-circle"></i> Invoices are charged automatically to your {{ a.autopay.method === 'upi' ? 'UPI' : 'card' }} ({{ a.gateway }}).
                @if (a.autopay.last_error) { <span class="c-bad"> Last try failed: {{ a.autopay.last_error }}</span> }</span>
                <p-button label="Turn off" size="small" [text]="true" severity="danger" (onClick)="cancelAutopay()" /></div>
            } @else {
              @if (a.autopay?.status === 'pending') { <p class="small m0">Waiting for the gateway to confirm the mandate.</p> }
              <div class="row gap wrap"><p-selectbutton [options]="apMethods" [(ngModel)]="apMethod" optionLabel="label" optionValue="value" [allowEmpty]="false" />
                <p-button label="Set up autopay" icon="pi pi-credit-card" size="small" (onClick)="setupAutopay()" /></div>
              <p class="small muted m0">Each invoice is charged when it is issued; a failed charge is tried again on the next two days, and you are emailed each time.</p>
            }
          }
        </p-card>
        <p-card header="Invoices" styleClass="mt">
          @for (i of s.invoices; track i.id) {
            <div class="row-between small"><span>{{ i.number }} · {{ i.created_at | date: 'mediumDate' }} · {{ i.period || i.type }}</span>
              <span>{{ inr(i.total) }} <p-tag [value]="i.status" [severity]="i.status === 'paid' ? 'success' : i.status === 'overdue' ? 'danger' : 'info'" />
                @if (i.status === 'due' || i.status === 'overdue') { <p-button label="Pay now" size="small" [text]="true" (onClick)="pay(i)" /> }</span></div>
          } @empty { <span class="muted small">No invoices yet.</span> }
        </p-card>
        <div class="grid2 top mt">
          <p-card header="Your data">
            <p class="small m0">Your data belongs to you. Ask for a full export and the platform team sends it to you.</p>
            @if (s.export_requested) { <p class="small c-good">Export requested {{ s.export_requested | date: 'medium' }}.</p> }
            @else { <p-button label="Ask for an export" size="small" [outlined]="true" (onClick)="exportData()" /> }
          </p-card>
          <p-card header="Cancel">
            <p class="small m0">Your account turns read-only; nothing is deleted, and you can come back or ask for your data.</p>
            <input pInputText [(ngModel)]="why" placeholder="Why are you leaving?" class="mt-xs" />
            <p-button label="Cancel the subscription" size="small" severity="danger" [text]="true" [disabled]="!why.trim()" (onClick)="cancel()" />
          </p-card>
        </div>
      }
    }
    <p-card header="Support" styleClass="mt">
      <div class="stack mb">
        <input pInputText [(ngModel)]="t.subject" placeholder="What is it about?" />
        <textarea pTextarea rows="3" [(ngModel)]="t.text" placeholder="Describe the problem"></textarea>
        <div class="row right"><p-button label="Send to support" size="small" [disabled]="!t.subject.trim() || !t.text.trim()" (onClick)="raise()" /></div>
      </div>
      @for (k of tickets(); track k.id) {
        <div class="ticket"><div class="row-between"><strong>{{ k.subject }}</strong><p-tag [value]="k.status" /></div>
          @for (r of k.replies; track $index) { <div class="small" [class.c-good]="r.side === 'support'"><strong>{{ r.side === 'support' ? 'Support · ' + r.by : r.by }}</strong> {{ r.at | date: 'short' }}: {{ r.text }}</div> }
          @if (k.status !== 'closed') { <div class="row gap mt-xs"><input pInputText [(ngModel)]="drafts[k.id]" placeholder="Reply" class="grow" />
            <p-button label="Send" size="small" [disabled]="!drafts[k.id]?.trim()" (onClick)="reply(k)" /></div> }
        </div>
      }
    </p-card>
  `,
  styles: `.ticket { border-top: 1px solid var(--border); padding: .5rem 0; }`,
})
export class SubscriptionComponent implements OnInit {
  private api = inject(Api);
  private auth = inject(AuthService);
  s = signal<any>(null);
  tickets = signal<any[]>([]);
  isOwner = this.auth.user()?.role === 'owner';
  planCode: string | null = null;
  cycle = 'monthly';
  cycles = [{ label: 'Monthly', value: 'monthly' }, { label: 'Yearly', value: 'yearly' }];
  coupon = '';
  why = '';
  t = { subject: '', text: '' };
  drafts: Record<string, string> = {};

  async ngOnInit() {
    if (this.isOwner) await this.load();
    this.tickets.set(await this.api.get('/support/tickets'));
  }

  async load() {
    const s = await this.api.get('/billing/subscription');
    this.s.set(s);
    this.planCode = s.plan?.code ?? null;
    this.cycle = s.billing_cycle ?? 'monthly';
    this.add = { extra_users: s.addons?.extra_users ?? 0, extra_storage_gb: s.addons?.extra_storage_gb ?? 0, extra_whatsapp: s.addons?.extra_whatsapp ?? 0 };
    this.ap.set(await this.api.get('/billing/autopay'));
  }

  // Phase J block 7: the subscription charged automatically
  ap = signal<any>(null);
  apMethod = 'card';
  apMethods = [{ label: 'Card', value: 'card' }, { label: 'UPI autopay', value: 'upi' }];

  async setupAutopay() {
    const r = await this.api.post('/billing/autopay', { method: this.apMethod });
    if (r.autopay.checkout?.order_id || r.autopay.checkout?.client_secret) {
      alert('Complete the authorisation in the payment window; autopay turns on when the gateway confirms it.');
    }
    await this.load();
  }

  async cancelAutopay() {
    if (!confirm('Turn off automatic payment? Invoices will then need paying by hand.')) return;
    await this.api.del('/billing/autopay', 'Autopay turned off');
    await this.load();
  }

  pick() {
    return (this.s()?.plans ?? []).find((p: any) => p.code === this.planCode);
  }

  inr(v: number) {
    return '₹' + Math.round(v ?? 0).toLocaleString('en-IN');
  }

  gb(b: number) {
    return (b / 1073741824).toFixed(2);
  }

  add: any = {};

  async saveAddons() {
    await this.api.post('/billing/addons', { extra_users: +this.add.extra_users || 0, extra_storage_gb: +this.add.extra_storage_gb || 0,
      extra_whatsapp: +this.add.extra_whatsapp || 0 }, 'Add-ons saved');
    await this.load();
  }

  async change() {
    await this.api.post('/billing/change', { plan_code: this.planCode, billing_cycle: this.cycle, ...(this.coupon ? { coupon: this.coupon } : {}) }, 'Plan changed');
    this.coupon = '';
    await this.load();
  }

  async pay(i: any) {
    await this.api.post(`/billing/invoices/${i.id}/pay`, {}, 'Paid — thank you');
    await this.load();
  }

  async exportData() {
    await this.api.post('/billing/export', {}, 'Export requested');
    await this.load();
  }

  async cancel() {
    await this.api.post('/billing/cancel', { reason: this.why }, 'Subscription cancelled');
    await this.load();
  }

  async raise() {
    await this.api.post('/support/tickets', this.t, 'Sent to support');
    this.t = { subject: '', text: '' };
    this.tickets.set(await this.api.get('/support/tickets'));
  }

  async reply(k: any) {
    await this.api.post(`/support/tickets/${k.id}/reply`, { text: this.drafts[k.id] }, 'Sent');
    this.drafts[k.id] = '';
    this.tickets.set(await this.api.get('/support/tickets'));
  }
}
