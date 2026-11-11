import { Component, effect, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { TextareaModule } from 'primeng/textarea';
import { Api } from '../core/api.service';

/** One portal thread between a client / consultant / contractor and the team (Phase G block 3). */
@Component({
  selector: 'app-thread',
  imports: [FormsModule, DatePipe, ButtonModule, TextareaModule],
  template: `
    <div class="msgs">
      @for (m of rows(); track m.id) {
        <div class="msg" [class.mine]="m.side === 'team'">
          <div class="small muted">{{ m.author }} · {{ m.created_at | date: 'd MMM, h:mm a' }}
            @if (m.side === 'team' && m.whatsapp) { · WhatsApp {{ m.whatsapp }} }</div>
          <div class="text">{{ m.text }}</div>
          @for (f of m.files; track f.key) { <a class="small" [href]="f.url" target="_blank" rel="noopener">{{ f.name }}</a> }
        </div>
      } @empty { <p class="muted small">No messages yet.</p> }
    </div>
    @if (canWrite()) {
      <div class="row gap compose">
        <textarea pTextarea rows="2" class="grow" [(ngModel)]="text" placeholder="Write a reply" aria-label="Reply"></textarea>
        <p-button icon="pi pi-send" [disabled]="!text.trim() || busy()" (onClick)="send()" ariaLabel="Send" />
      </div>
    }
  `,
  styles: `
    .msgs { display: flex; flex-direction: column; gap: .5rem; max-height: 26rem; overflow-y: auto; padding: .25rem; }
    .msg { max-width: 80%; border: 1px solid var(--border); border-radius: 12px; padding: .45rem .7rem; background: var(--surface); }
    .msg.mine { align-self: flex-end; background: color-mix(in srgb, var(--p-primary-color, #6366f1) 12%, var(--surface)); }
    .text { white-space: pre-wrap; }
    .compose { margin-top: .6rem; align-items: flex-end; }
  `,
})
export class ThreadComponent {
  projectId = input.required<string>();
  contactId = input.required<string>();
  canWrite = input(true);
  changed = output<void>();
  private api = inject(Api);
  rows = signal<any[]>([]);
  busy = signal(false);
  text = '';

  constructor() {
    effect(() => {
      const [p, c] = [this.projectId(), this.contactId()];
      if (p && c) this.load(p, c);
    });
  }

  async load(p = this.projectId(), c = this.contactId()) {
    this.rows.set(await this.api.get(`/projects/${p}/threads/${c}`));
    this.changed.emit();
  }

  async send() {
    this.busy.set(true);
    try {
      await this.api.post(`/projects/${this.projectId()}/threads/${this.contactId()}`, { text: this.text }, 'Sent');
      this.text = '';
      await this.load();
    } finally {
      this.busy.set(false);
    }
  }
}
