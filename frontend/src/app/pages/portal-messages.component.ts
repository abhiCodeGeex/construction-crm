import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { TextareaModule } from 'primeng/textarea';
import { Api } from '../core/api.service';

/** The portal user's private thread with the team on this project (Phase G block 3), and WhatsApp opt-in (block 4). */
@Component({
  selector: 'app-portal-messages',
  imports: [FormsModule, DatePipe, ButtonModule, CheckboxModule, TextareaModule],
  template: `
    <h4>Messages with the team</h4>
    <div class="msgs">
      @for (m of rows(); track m.id) {
        <div class="msg" [class.mine]="m.side === 'contact'"><div class="small muted">{{ m.author }} · {{ m.created_at | date: 'd MMM, h:mm a' }}</div>
          <div class="text">{{ m.text }}</div></div>
      } @empty { <p class="muted small">Ask the team anything about the project here.</p> }
    </div>
    <div class="row gap compose">
      <textarea pTextarea rows="2" class="grow" [(ngModel)]="text" placeholder="Write to the team" aria-label="Message to the team"></textarea>
      <p-button icon="pi pi-send" [disabled]="!text.trim() || busy()" (onClick)="send()" ariaLabel="Send" />
    </div>
    @if (wa()?.available) {
      <label class="check small mt">
        <p-checkbox [ngModel]="wa().opt_in" [binary]="true" [disabled]="!wa().has_phone" (onChange)="optIn($event.checked)" ariaLabel="WhatsApp updates" />
        Send me updates and replies on WhatsApp @if (!wa().has_phone) { <span class="muted">(ask the team to add your mobile number)</span> }
      </label>
    }
  `,
  styles: `
    .msgs { display: flex; flex-direction: column; gap: .45rem; max-height: 22rem; overflow-y: auto; }
    .msg { max-width: 85%; border: 1px solid var(--border); border-radius: 12px; padding: .4rem .65rem; }
    .msg.mine { align-self: flex-end; background: color-mix(in srgb, var(--p-primary-color, #6366f1) 12%, transparent); }
    .text { white-space: pre-wrap; }
    .compose { margin-top: .5rem; align-items: flex-end; }
  `,
})
export class PortalMessagesComponent implements OnInit {
  projectId = input.required<string>();
  private api = inject(Api);
  rows = signal<any[]>([]);
  wa = signal<any>(null);
  busy = signal(false);
  text = '';

  async ngOnInit() {
    await this.load();
    this.wa.set(await this.api.get('/portal/whatsapp'));
  }

  async load() {
    this.rows.set(await this.api.get(`/portal/projects/${this.projectId()}/messages`));
  }

  async send() {
    this.busy.set(true);
    try {
      await this.api.post(`/portal/projects/${this.projectId()}/messages`, { text: this.text }, 'Sent to the team');
      this.text = '';
      await this.load();
    } finally {
      this.busy.set(false);
    }
  }

  async optIn(on: boolean) {
    await this.api.put('/portal/whatsapp', { opt_in: on }, on ? 'WhatsApp updates on' : 'WhatsApp updates off');
    this.wa.set(await this.api.get('/portal/whatsapp'));
  }
}
