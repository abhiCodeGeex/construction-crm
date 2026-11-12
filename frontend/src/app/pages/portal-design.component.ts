import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { Api, money } from '../core/api.service';
import { PanoComponent } from '../core/pano.component';
import { TPipe } from '../core/i18n';

/** Phase J blocks 5-6 in the client portal — design options to approve, and 360° views / renders to comment on. */
@Component({
  selector: 'app-portal-design',
  imports: [FormsModule, ButtonModule, DialogModule, PanoComponent, TPipe],
  template: `
    @if (options().length) {
      <h4>{{ 'Design options' | t }}</h4>
      @for (d of options(); track d.id) {
        <div class="dec">
          <div class="row-between wrap gap"><strong>{{ d.title }}@if (d.room) { <span class="small muted"> · {{ d.room }}</span> }</strong>
            <span class="small">@switch (d.status) { @case ('approved') { {{ 'You approved' | t }} {{ d.approved_label }} } @case ('changes_requested') { {{ 'You asked for changes' | t }} } @default { @if (d.due_date) { {{ 'Please decide by' | t }} {{ d.due_date }} } } }</span></div>
          <div class="opts">
            @for (o of d.options; track o.id) {
              <div class="opt" [class.win]="d.approved_option_id === o.id">
                <strong>{{ o.label }}. {{ o.name }}</strong>
                @for (im of o.images; track im.key) { <img [src]="im.url" [alt]="o.name" /> }
                @if (o.description) { <span class="small">{{ o.description }}</span> }
                <span class="small">{{ o.price ? (o.price > 0 ? '+' : '') + fmt(o.price) : ('No extra cost' | t) }}</span>
                @if (d.status === 'sent' && isClient()) { <p-button [label]="('Choose' | t) + ' ' + o.label" size="small" (onClick)="ask(d, o)" /> }
              </div>
            }
          </div>
          @if (d.status === 'sent' && isClient()) { <button type="button" class="p-button p-button-text p-button-sm" (click)="changes(d)">{{ 'Ask for changes' | t }}</button> }
        </div>
      }
    }
    @if (views().length) {
      <h4>{{ '360° views and renders' | t }}</h4>
      <div class="row gap wrap mb">@for (v of views(); track v.id) {
        <button type="button" class="p-button p-button-sm" [class.p-button-outlined]="cur()?.id !== v.id" (click)="cur.set(v)">{{ v.title }}</button> }</div>
      @if (cur(); as v) {
        <app-pano [view]="v" [canComment]="true" (spot)="spot($event)" />
        @for (c of v.comments; track c.id; let i = $index) { <div class="small"><strong>{{ i + 1 }}. {{ c.author }}:</strong> {{ c.text }}</div> }
      }
    }
    <p-dialog [header]="'Approve option' | t" [modal]="true" [(visible)]="aDlg" [style]="{ width: '26rem' }">
      <div class="stack"><p class="m0">{{ pick?.o?.label }}. {{ pick?.o?.name }}</p>
        @if (pick?.o?.price) { <p class="small m0">{{ 'This adds' | t }} {{ fmt(pick.o.price) }} {{ '— the team will send a change order.' | t }}</p> }
        <textarea class="p-inputtext" rows="2" [(ngModel)]="note" [placeholder]="'Comment (optional)' | t" aria-label="Comment"></textarea>
        <div class="row right"><p-button [label]="'Approve' | t" (onClick)="approve()" /></div></div>
    </p-dialog>
    <p-dialog [header]="'Your comment' | t" [modal]="true" [(visible)]="cDlg" [style]="{ width: '26rem' }">
      <div class="stack"><textarea class="p-inputtext" rows="3" [(ngModel)]="note" aria-label="Comment"></textarea>
        <div class="row right"><p-button [label]="'Send to the team' | t" [disabled]="!note.trim()" (onClick)="sendComment()" /></div></div>
    </p-dialog>
  `,
  styles: `.dec { border: 1px solid var(--border); border-radius: 10px; padding: .6rem .8rem; margin-bottom: .7rem; display: grid; gap: .4rem; }
    .opts { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: .6rem; }
    .opt { display: grid; gap: .3rem; border: 1px solid var(--border); border-radius: 8px; padding: .5rem; } .opt.win { border: 2px solid #16a34a; }
    .opt img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 6px; }`,
})
export class PortalDesignComponent {
  projectId = input.required<string>();
  isClient = input(false);
  currency = input('INR');
  private api = inject(Api);
  options = signal<any[]>([]);
  views = signal<any[]>([]);
  cur = signal<any>(null);
  aDlg = false; cDlg = false;
  pick: any = null;
  at: any = null;
  note = '';

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const pid = this.projectId();
    const [o, v] = await Promise.all([this.api.get(`/portal/projects/${pid}/design-options`), this.api.get(`/portal/projects/${pid}/views`)]);
    this.options.set(o);
    this.views.set(v);
    const id = this.cur()?.id;
    this.cur.set(v.find((x: any) => x.id === id) ?? v[0] ?? null);
  }

  fmt(v: number) {
    return money(v, this.currency());
  }

  ask(d: any, o: any) {
    this.pick = { d, o };
    this.note = '';
    this.aDlg = true;
  }

  async approve() {
    await this.api.post(`/portal/design-options/${this.pick.d.id}/approve`, { option_id: this.pick.o.id, comment: this.note }, 'Thank you — the team is told');
    this.aDlg = false;
    await this.load();
  }

  async changes(d: any) {
    const comment = prompt('What would you like changed?');
    if (!comment?.trim()) return;
    await this.api.post(`/portal/design-options/${d.id}/changes`, { comment }, 'Sent to the team');
    await this.load();
  }

  spot(at: any) {
    this.at = at;
    this.note = '';
    this.cDlg = true;
  }

  async sendComment() {
    await this.api.post(`/portal/views/${this.cur().id}/comments`, { text: this.note, ...this.at }, 'Sent to the team');
    this.cDlg = false;
    await this.load();
  }
}
