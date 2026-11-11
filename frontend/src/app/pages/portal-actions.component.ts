import { Component, OnInit, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, money } from '../core/api.service';
import { SignaturePadComponent } from '../shared/signature-pad.component';

/** What the portal user can act on (Phase G block 1): sign off a stage, approve or reject a change order (signed),
 *  choose a selection, approve / comment on / return a drawing sent to them, acknowledge a transmittal. */
@Component({
  selector: 'app-portal-actions',
  imports: [FormsModule, DatePipe, ButtonModule, CheckboxModule, DialogModule, InputTextModule, TagModule, TextareaModule, SignaturePadComponent],
  template: `
    @if (a(); as a) {
      @if (!a.signoffs.length && !a.change_orders.length && !a.selections.length && !a.documents.length && !pendingAcks(a)) {
        <p class="muted small">Nothing is waiting for you right now.</p>
      }
      @for (s of a.signoffs; track s.stage_id) {
        <div class="act"><div><strong>Sign off: {{ s.name }}</strong><div class="small muted">The work on this stage is done and needs your approval.</div></div>
          <p-button label="Sign off" icon="pi pi-check" size="small" (onClick)="open('signoff', s)" /></div>
      }
      @for (c of a.change_orders; track c.id) {
        <div class="act col">
          <div class="row-between"><strong>Change order {{ c.number }}: {{ c.title }}</strong><span><strong>{{ fmt(c.total) }}</strong>
            @if (c.time_days) { <span class="small muted"> · {{ c.time_days > 0 ? '+' : '' }}{{ c.time_days }} working days</span> }</span></div>
          @if (c.description) { <div class="small">{{ c.description }}</div> }
          @for (l of c.lines; track $index) { <div class="small muted">{{ l.description }} · {{ l.qty }} {{ l.unit || '' }} · {{ fmt(l.price) }}</div> }
          <div class="small muted">Price {{ fmt(c.price) }} + tax {{ fmt(c.tax) }} · {{ c.stage_name }}</div>
          @for (f of c.files; track f.url) { <a class="small" [href]="f.url" target="_blank" rel="noopener">{{ f.name }}</a> }
          <div class="row gap right"><p-button label="Not now" size="small" [text]="true" severity="danger" (onClick)="open('reject', c)" />
            <p-button label="Approve and sign" icon="pi pi-pencil" size="small" (onClick)="open('co', c)" /></div>
        </div>
      }
      @for (s of a.selections; track s.id) {
        <div class="act col">
          <div class="row-between"><strong>Choose: {{ s.item }}@if (s.room) { · {{ s.room }} }</strong>
            @if (s.due_date) { <span class="small muted">by {{ s.due_date | date: 'mediumDate' }}</span> }</div>
          @if (s.allowance) { <div class="small muted">Allowance in your contract: {{ fmt(s.allowance) }}</div> }
          <div class="opts">@for (o of s.options; track o.id) {
            <button type="button" class="opt" (click)="open('choose', s, o)">
              @if (o.photo) { <img [src]="o.photo" alt="" /> }
              <strong>{{ o.name }}</strong><span class="small muted">@if (o.brand) { {{ o.brand }} · } {{ o.lead_days }} days</span>
              <span>{{ fmt(o.price) }}@if (s.allowance && o.price > s.allowance) { <span class="small c-warn"> +{{ fmt(o.price - s.allowance) }}</span> }</span>
            </button> }</div>
        </div>
      }
      @for (d of a.documents; track d.id) {
        <div class="act col">
          <div class="row-between"><span><a [href]="d.url" target="_blank" rel="noopener"><strong>@if (d.number) { {{ d.number }} } {{ d.name }}</strong></a>
            <span class="small muted"> · {{ d.rev }} · {{ d.purpose_label }} ({{ d.transmittal }})</span></span>
            @if (d.status) { <p-tag [value]="d.status" severity="info" /> }</div>
          @if (d.superseded) { <div class="small muted">A newer revision ({{ d.current_rev }}) is on its way to you.</div> }
          @for (c of d.comments; track $index) {
            <div class="small comment">“{{ c.text }}” <span class="muted">— {{ c.author }}, {{ c.at | date: 'd MMM' }}</span>
              @if (c.reply) { <div class="c-good">Reply: {{ c.reply.text }} — {{ c.reply.by }}</div> }</div>
          }
          @if (!d.superseded && (d.can_comment || d.can_approve)) {
            <div class="row gap right">
              @if (d.can_comment) {
                <p-button label="Comment" size="small" [text]="true" (onClick)="open('comment', d)" />
                <p-button label="Return with comments" size="small" [text]="true" severity="secondary" (onClick)="open('return', d)" /> }
              @if (d.can_approve) { <p-button label="Approve" icon="pi pi-check" size="small" (onClick)="open('approve', d)" /> }
            </div>
          }
        </div>
      }
      @for (t of a.transmittals; track t.id) {
        @if (!t.acknowledged) {
          <div class="act"><div><strong>{{ t.number }}</strong> <span class="small muted">{{ t.purpose }} · {{ t.at | date: 'd MMM' }}</span>
            <div class="small">{{ t.items.join(', ') }}</div></div>
            <p-button label="Received" size="small" [text]="true" (onClick)="open('ack', t)" /></div>
        }
      }
    }

    <p-dialog [header]="title()" [modal]="true" [(visible)]="dlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        @switch (mode) {
          @case ('reject') { <label class="field req"><span>Why not?</span><textarea pTextarea rows="2" [(ngModel)]="f.reason" fluid></textarea></label> }
          @case ('comment') { <label class="field req"><span>Your comment</span><textarea pTextarea rows="3" [(ngModel)]="f.text" fluid></textarea></label> }
          @case ('return') { <label class="field req"><span>What has to change</span><textarea pTextarea rows="3" [(ngModel)]="f.text" fluid></textarea></label> }
          @default {
            @if (mode === 'choose') { <p class="m0">You choose <strong>{{ target2?.name }}</strong> · {{ fmt(target2?.price) }}</p> }
            @if (mode === 'co') { <p class="m0">This adds <strong>{{ fmt(target?.total) }}</strong> to your contract. Sign below.</p> }
            <label class="field req"><span>Your full name</span><input pInputText [(ngModel)]="f.name" fluid /></label>
            @if (mode === 'co') { <app-signature-pad (signed)="f.signature = $event" /> }
            @if (mode !== 'ack') { <label class="check"><p-checkbox [(ngModel)]="f.agree" [binary]="true" ariaLabel="I confirm" /> {{ confirmText() }}</label> }
          }
        }
        <div class="row right"><p-button label="Confirm" [disabled]="!ready()" [loading]="busy()" (onClick)="submit()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .act { display: flex; justify-content: space-between; align-items: center; gap: .75rem; border: 1px solid var(--border); border-radius: 10px; padding: .7rem .85rem; margin-bottom: .6rem; }
    .act.col { flex-direction: column; align-items: stretch; gap: .35rem; }
    .opts { display: grid; grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr)); gap: .5rem; }
    .opt { display: flex; flex-direction: column; gap: .15rem; text-align: left; border: 1px solid var(--border); border-radius: 8px; padding: .5rem; background: var(--surface); color: inherit; cursor: pointer; font: inherit; }
    .opt:hover, .opt:focus-visible { border-color: var(--p-primary-color, #6366f1); outline: none; }
    .opt img { width: 100%; height: 5.5rem; object-fit: cover; border-radius: 6px; }
    .comment { border-left: 3px solid var(--border); padding-left: .5rem; }
  `,
})
export class PortalActionsComponent implements OnInit {
  projectId = input.required<string>();
  currency = input('INR');
  changed = output<void>();
  private api = inject(Api);
  a = signal<any>(null);
  busy = signal(false);
  dlg = false;
  mode = '';
  f: any = {};
  target: any = null;
  target2: any = null;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.a.set(await this.api.get(`/portal/projects/${this.projectId()}/actions`));
  }

  fmt(v: number) {
    return money(v, this.currency());
  }

  pendingAcks(a: any) {
    return a.transmittals.filter((t: any) => !t.acknowledged).length;
  }

  open(mode: string, target: any, target2?: any) {
    this.mode = mode;
    this.target = target;
    this.target2 = target2 ?? null;
    this.f = { name: '', agree: false, signature: null, reason: '', text: '' };
    this.dlg = true;
  }

  title() {
    return { signoff: 'Sign off the stage', co: 'Approve the change order', reject: 'Not this change', choose: 'Your choice', approve: 'Approve the drawing',
      comment: 'Comment', return: 'Return with comments', ack: 'Received' }[this.mode] ?? '';
  }

  confirmText() {
    return { signoff: 'I approve the work on this stage', co: 'I approve this change and its price', choose: 'This is my choice',
      approve: 'I approve this drawing' }[this.mode] ?? 'I confirm';
  }

  ready() {
    switch (this.mode) {
      case 'reject': return !!this.f.reason?.trim();
      case 'comment': case 'return': return !!this.f.text?.trim();
      case 'ack': return !!this.f.name?.trim();
      case 'co': return !!this.f.name?.trim() && this.f.agree && !!this.f.signature;
      default: return !!this.f.name?.trim() && this.f.agree;
    }
  }

  async submit() {
    const t = this.target;
    const who = { name: this.f.name, agree: this.f.agree };
    this.busy.set(true);
    try {
      switch (this.mode) {
        case 'signoff': await this.api.post(`/portal/projects/${this.projectId()}/stages/${t.stage_id}/signoff`, who, 'Signed off — thank you'); break;
        case 'co': await this.api.post(`/portal/change_orders/${t.id}/approve`, { ...who, signature: this.f.signature }, 'Approved — thank you'); break;
        case 'reject': await this.api.post(`/portal/change_orders/${t.id}/reject`, { reason: this.f.reason }, 'Sent to the team'); break;
        case 'choose': await this.api.post(`/portal/selections/${t.id}/choose`, { ...who, option_id: this.target2.id }, 'Choice saved — thank you'); break;
        case 'approve': await this.api.post(`/portal/documents/${t.id}/approve`, who, 'Approved — thank you'); break;
        case 'comment': await this.api.post(`/portal/documents/${t.id}/comments`, { text: this.f.text }, 'Comment sent'); break;
        case 'return': await this.api.post(`/portal/documents/${t.id}/return`, { comment: this.f.text }, 'Returned to the team'); break;
        case 'ack': await this.api.post(`/portal/transmittals/${t.id}/acknowledge`, { name: this.f.name }, 'Thank you'); break;
      }
      this.dlg = false;
      await this.load();
      this.changed.emit();
    } finally {
      this.busy.set(false);
    }
  }
}
