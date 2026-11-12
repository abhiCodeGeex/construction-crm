import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Phase J block 4 — the PM's one morning screen (done yesterday, late, stuck, budget warnings) and, for the Owner
 *  and PMs, who writes in most and about what. */
@Component({
  selector: 'app-digest',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, SelectButtonModule, TagModule],
  template: `
    <div class="page">
      <div class="row-between wrap gap mb">
        <h1 class="m0">Morning digest</h1>
        <span class="row gap">
          @if (canReport) { <p-selectbutton [options]="parts" [(ngModel)]="part" optionLabel="label" optionValue="value" [allowEmpty]="false" (ngModelChange)="load()" /> }
          <p-button [label]="wa() ? 'Digest on WhatsApp: on' : 'Get it on WhatsApp'" icon="pi pi-whatsapp" size="small" [text]="true" (onClick)="toggleWa()" />
        </span>
      </div>
      @if (part === 'digest' && d(); as d) {
        <div class="kpis mb">
          <div class="kpi"><span class="n">{{ d.totals.done }}</span><span class="small muted">done since yesterday</span></div>
          <div class="kpi" [class.bad]="d.totals.late"><span class="n">{{ d.totals.late }}</span><span class="small muted">late tasks</span></div>
          <div class="kpi" [class.bad]="d.totals.stuck"><span class="n">{{ d.totals.stuck }}</span><span class="small muted">stuck</span></div>
          <div class="kpi" [class.warn]="d.totals.budget"><span class="n">{{ d.totals.budget }}</span><span class="small muted">budget warnings</span></div>
        </div>
        @for (p of d.projects; track p.project_id) {
          <div class="card-row">
            <div class="row-between"><a [routerLink]="['/app/projects', p.project_id]"><strong>{{ p.project }}</strong></a>
              @if (!p.site_report) { <p-tag value="no site report yesterday" severity="warn" /> }</div>
            @if (p.late.length) { <div><span class="lbl c-bad">Late</span> @for (x of p.late; track $index) { <span class="chip">{{ x.task }} · {{ x.days }} d @if (x.assignee) { · {{ x.assignee }} }</span> }</div> }
            @if (p.stuck.length) { <div><span class="lbl c-bad">Stuck</span> @for (x of p.stuck; track $index) { <span class="chip">{{ x.what }} — {{ x.why }}</span> }</div> }
            @if (p.budget.length) { <div><span class="lbl">Budget</span> @for (x of p.budget; track $index) { <span class="chip" [class.red]="x.level === 'red'">{{ x.stage }} {{ x.pct }}%</span> }</div> }
            @if (p.done.length) { <div class="small muted"><span class="lbl">Done</span> {{ p.done.join(' · ') }}</div> }
            @if (!p.late.length && !p.stuck.length && !p.budget.length && !p.done.length) { <span class="small muted">Nothing to flag.</span> }
          </div>
        } @empty { <p class="muted">No live projects you are on.</p> }
      }
      @if (part === 'messages' && r(); as r) {
        <div class="row gap mb"><p-selectbutton [options]="dayOpts" [(ngModel)]="days" optionLabel="label" optionValue="value" [allowEmpty]="false" (ngModelChange)="load()" /></div>
        <div class="kpis mb">
          <div class="kpi"><span class="n">{{ r.messages }}</span><span class="small muted">messages in</span></div>
          <div class="kpi"><span class="n">{{ r.first_reply_minutes ?? '—' }}</span><span class="small muted">median first reply (min)</span></div>
          <div class="kpi" [class.bad]="r.unanswered"><span class="n">{{ r.unanswered }}</span><span class="small muted">unread by the team</span></div>
        </div>
        <div class="grid2">
          <div><h3>About what</h3>@for (x of r.topics; track x[0]) { <div class="row-between small"><span>{{ topic(x[0]) }}</span><strong>{{ x[1] }}</strong></div> }</div>
          <div><h3>By channel</h3>@for (x of r.channels; track x[0]) { <div class="row-between small"><span>{{ x[0] }}</span><strong>{{ x[1] }}</strong></div> }
            @if (r.calls.length) { <h3>Calls logged on leads</h3>@for (x of r.calls; track x[0]) { <div class="row-between small"><span>{{ x[0] }}</span><strong>{{ x[1] }}</strong></div> } }</div>
        </div>
        <h3>Who writes most</h3>
        @for (x of r.people; track $index) {
          <div class="card-row"><div class="row-between"><strong>{{ x.name }}</strong><span class="small">{{ x.count }} · {{ x.kind }} @if (x.urgent) { · <span class="c-bad">{{ x.urgent }} urgent</span> }</span></div>
            <div class="small muted">@for (t of x.topics; track t[0]) { {{ topic(t[0]) }} {{ t[1] }}@if (!$last) { · } } · last {{ x.last | date: 'd MMM HH:mm' }}</div></div>
        } @empty { <p class="muted">No messages in this period.</p> }
      }
    </div>
  `,
  styles: `.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .6rem; }
    .kpi { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .8rem; background: var(--surface); display: grid; }
    .kpi .n { font-size: 1.6rem; font-weight: 700; } .kpi.bad .n { color: var(--red, #c0392b); } .kpi.warn .n { color: #b7791f; }
    .card-row { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .9rem; margin-bottom: .6rem; background: var(--surface); display: grid; gap: .3rem; }
    .chip { display: inline-block; border: 1px solid var(--border); border-radius: 99px; padding: .05rem .55rem; margin: .1rem .2rem; font-size: .8rem; } .chip.red { border-color: #c0392b; }
    .lbl { font-size: .72rem; text-transform: uppercase; letter-spacing: .04em; margin-right: .3rem; }`,
})
export class DigestComponent {
  private api = inject(Api);
  private auth = inject(AuthService);
  canReport = ['owner', 'pm'].includes(this.auth.user()?.role ?? '');
  parts = [{ label: 'Digest', value: 'digest' }, { label: 'Message report', value: 'messages' }];
  part = 'digest';
  dayOpts = [{ label: '7 days', value: 7 }, { label: '30 days', value: 30 }, { label: '90 days', value: 90 }];
  days = 30;
  d = signal<any>(null);
  r = signal<any>(null);
  wa = signal(false);
  topics: Record<string, string> = { material_needed: 'Material', payment: 'Payment', design: 'Design', need_clarification: 'Questions', work_done: 'Work done', general: 'General' };
  topic = (k: string) => this.topics[k] ?? k;

  async ngOnInit() {
    this.wa.set(!!(this.auth.user() as any)?.whatsapp_opt_in);
    await this.load();
  }

  async load() {
    if (this.part === 'digest') this.d.set(await this.api.get('/digest'));
    else this.r.set(await this.api.get(`/reports/messages?days=${this.days}`));
  }

  async toggleWa() {
    const r = await this.api.put('/me/whatsapp', { opt_in: !this.wa() }, this.wa() ? 'WhatsApp digest off' : 'You will get the digest on WhatsApp');
    this.wa.set(r.opt_in);
  }
}
