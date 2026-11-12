import { Component, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { firstValueFrom } from 'rxjs';

const STYLES = `.pub { max-width: 40rem; margin: 0 auto; padding: 1rem; font-size: 1.05rem; }
  .pub h1 { font-size: 1.35rem; margin: .2rem 0; } .muted { color: #6b7280; } .small { font-size: .85rem; }
  .box { border: 1px solid #e5e7eb; border-radius: 10px; padding: .7rem .9rem; margin: .6rem 0; background: #fff; }
  .box a { display: block; padding: .35rem 0; } img { max-width: 100%; border-radius: 8px; } table { width: 100%; border-collapse: collapse; }
  td { padding: .3rem .2rem; border-bottom: 1px solid #f1f1f1; } .err { color: #c0392b; }`;

/** Phase J block 3 — the job card a site worker opens from WhatsApp (no sign-in). */
@Component({
  selector: 'app-public-job',
  template: `
    <div class="pub">
      @if (err()) { <p class="err">{{ err() }}</p> }
      @if (d(); as d) {
        <div class="small muted">{{ d.company }} · {{ d.project_name }}</div>
        <h1>{{ d.task }}</h1>
        <div>@if (d.room) { <strong>{{ d.room }}</strong> · } @if (d.trade) { {{ d.trade }} · } {{ d.start }} → {{ d.end }}</div>
        @if (d.address) { <div class="small muted">{{ d.address }}</div> }
        @if (d.supervisor) { <div class="box">Supervisor: <strong>{{ d.supervisor.name }}</strong> @if (d.supervisor.phone) { · <a [href]="'tel:' + d.supervisor.phone" style="display:inline">{{ d.supervisor.phone }}</a> }</div> }
        @if (d.instructions) { <div class="box"><strong>Instructions</strong><div style="white-space:pre-wrap">{{ d.instructions }}</div></div> }
        @if (d.measurements.length) { <div class="box"><strong>Measurements</strong><table>@for (m of d.measurements; track $index) { <tr><td>{{ m.label }}</td><td><strong>{{ m.value }}</strong></td></tr> }</table></div> }
        @if (d.drawings.length) { <div class="box"><strong>Drawings</strong>@for (x of d.drawings; track x.id) { <a [href]="x.url" target="_blank" rel="noopener">{{ x.number || '' }} {{ x.name }} · {{ x.rev }}</a> }</div> }
        @for (p of d.photos; track p.key) { <img [src]="p.url" [alt]="p.name" /> }
      }
    </div>
  `,
  styles: STYLES,
})
export class PublicJobComponent {
  private http = inject(HttpClient);
  private route = inject(ActivatedRoute);
  d = signal<any>(null);
  err = signal('');

  async ngOnInit() {
    try {
      this.d.set(await firstValueFrom(this.http.get(`/api/public/job/${this.route.snapshot.paramMap.get('token')}`)));
    } catch {
      this.err.set('This link is not valid any more. Ask your supervisor for the new one.');
    }
  }
}

/** Phase J block 3 — the page behind a room's QR code: latest drawings, chosen finishes and the jobs (no sign-in). */
@Component({
  selector: 'app-public-room',
  template: `
    <div class="pub">
      @if (err()) { <p class="err">{{ err() }}</p> }
      @if (d(); as d) {
        <div class="small muted">{{ d.company }} · {{ d.project_name }}</div>
        <h1>{{ d.room }}</h1>
        <div class="box"><strong>Latest drawings</strong>
          @for (x of d.drawings; track x.id) { <a [href]="x.url" target="_blank" rel="noopener">{{ x.number || '' }} {{ x.name }} · {{ x.rev }} @if (x.status) { <span class="small muted">({{ x.status }})</span> }</a> }
          @empty { <div class="muted small">No drawings for this room yet.</div> }</div>
        @if (d.specs.length) { <div class="box"><strong>Finishes and fittings</strong><table>
          @for (s of d.specs; track $index) { <tr><td>{{ s.item }}</td><td>{{ s.choice || 'not chosen yet' }}@if (s.brand) { · {{ s.brand }} }@if (s.spec) { <div class="small muted">{{ s.spec }}</div> }</td></tr> }</table></div> }
        @if (d.jobs.length) { <div class="box"><strong>Jobs</strong>
          @for (j of d.jobs; track j.token) { <a [href]="'/j/' + j.token">{{ j.task }} @if (j.trade) { · {{ j.trade }} } · {{ j.status }}</a> }</div> }
      }
    </div>
  `,
  styles: STYLES,
})
export class PublicRoomComponent {
  private http = inject(HttpClient);
  private route = inject(ActivatedRoute);
  d = signal<any>(null);
  err = signal('');

  async ngOnInit() {
    try {
      this.d.set(await firstValueFrom(this.http.get(`/api/public/room/${this.route.snapshot.paramMap.get('token')}`)));
    } catch {
      this.err.set('This QR code is not valid any more.');
    }
  }
}
