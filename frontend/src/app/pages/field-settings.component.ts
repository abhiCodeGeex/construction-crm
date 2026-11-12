import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { Api } from '../core/api.service';

/** Phase J — Company settings → Field & WhatsApp: the morning work message, the PM digest, the trade order, routing
 *  rules and urgent words, and the inbound email address for the shared inbox. */
@Component({
  selector: 'app-field-settings',
  imports: [FormsModule, ButtonModule, InputNumberModule, InputTextModule, SelectModule, ToggleSwitchModule],
  template: `
    @if (s(); as s) {
      <div class="stack narrow">
        <h3 class="m0">Site workers on WhatsApp</h3>
        <div class="grid2">
          <label class="check"><p-toggleswitch [(ngModel)]="s.morning_on" ariaLabel="Morning work message" /> Morning work message to site workers</label>
          <label class="field"><span>At</span><input pInputText type="time" [(ngModel)]="s.morning_time" /></label>
          <label class="check"><p-toggleswitch [(ngModel)]="s.digest_on" ariaLabel="PM digest" /> Morning digest to Owners and PMs</label>
          <label class="field"><span>At</span><input pInputText type="time" [(ngModel)]="s.digest_time" /></label>
          <label class="field"><span>Time zone (minutes from UTC; India = 330)</span><p-inputnumber [(ngModel)]="s.utc_offset" [min]="-720" [max]="840" fluid /></label>
          <label class="field"><span>Escalate urgent messages to the Owner after (minutes)</span><p-inputnumber [(ngModel)]="s.escalate_minutes" [min]="5" [max]="1440" fluid /></label>
        </div>
        <label class="field"><span>Trade order (one per line) — when a trade finishes a room, the next one is told it is ready</span>
          <textarea class="p-inputtext" rows="5" [(ngModel)]="trades"></textarea></label>
        <h3 class="m0">Who gets which message</h3>
        <p class="small muted m0">WhatsApp and email messages from clients and workers go to the person in this role on the project (with the PM).</p>
        @for (t of topicKeys(); track t) {
          <div class="row gap"><span class="grow">{{ topicLabel[t] || t }}</span>
            <p-select [options]="roles()" [(ngModel)]="routing[t]" appendTo="body" [ariaLabel]="'Role for ' + t" /></div>
        }
        <label class="field"><span>Extra urgent words (comma separated; built in: {{ s.urgent_defaults.join(', ') }})</span><input pInputText [(ngModel)]="urgent" fluid /></label>
        <div class="row right"><p-button label="Save" (onClick)="save()" /></div>

        <h3 class="m0">Email into the shared inbox</h3>
        <p class="small muted m0">Point your mail provider's inbound parse (SendGrid, Mailgun, Postmark) or a forwarding rule at this address. An email from a known contact lands in their project thread; replies from the inbox go back by email.</p>
        @if (mail(); as m) {
          @if (m.enabled) { <code class="url">{{ origin }}{{ m.webhook_url }}</code>
            <div class="row gap"><p-button label="New address" size="small" [text]="true" (onClick)="setMail(true)" /><p-button label="Turn off" size="small" [text]="true" severity="danger" (onClick)="setMail(false)" />
              @if (m.unmatched) { <span class="small">{{ m.unmatched }} email(s) from unknown senders in the inbox</span> }</div> }
          @else { <p-button label="Make an inbound address" size="small" (onClick)="setMail(true)" /> }
        }
      </div>
    }
  `,
  styles: `.narrow { max-width: 46rem; } .url { display: block; word-break: break-all; padding: .5rem; background: var(--surface-2, #f5f5f5); border-radius: 6px; }`,
})
export class FieldSettingsComponent {
  private api = inject(Api);
  s = signal<any>(null);
  mail = signal<any>(null);
  roles = signal<string[]>([]);
  routing: Record<string, string> = {};
  trades = '';
  urgent = '';
  origin = location.origin;
  topicLabel: Record<string, string> = { material_needed: 'Material needed', payment: 'Payment', need_clarification: 'Questions from site', design: 'Design / drawings', general: 'Everything else' };
  topicKeys = () => Object.keys(this.s()?.routing_defaults ?? {});

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const s = await this.api.get('/settings/field');
    this.s.set(s);
    this.roles.set(s.roles);
    this.routing = { ...s.routing_defaults, ...s.routing };
    this.trades = s.trade_sequence.join('\n');
    this.urgent = s.urgent_words.join(', ');
    this.mail.set(await this.api.get('/settings/inbound-email').catch(() => null));
  }

  async save() {
    const s = this.s();
    const changed = Object.fromEntries(Object.entries(this.routing).filter(([k, v]) => s.routing_defaults[k] !== v));
    await this.api.put('/settings/field', {
      morning_on: s.morning_on, morning_time: s.morning_time, digest_on: s.digest_on, digest_time: s.digest_time, utc_offset: s.utc_offset,
      escalate_minutes: s.escalate_minutes, routing: changed,
      trade_sequence: this.trades.split('\n').map((x) => x.trim()).filter(Boolean),
      urgent_words: this.urgent.split(',').map((x) => x.trim()).filter(Boolean),
    }, 'Saved');
    await this.load();
  }

  async setMail(enabled: boolean) {
    this.mail.set(await this.api.post('/settings/inbound-email', { enabled }, enabled ? 'Inbound address made' : 'Turned off'));
  }
}
