import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { KeyValuePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../core/auth.service';
import { I18n, TPipe } from '../core/i18n';
import { OfflineStore, QueuedOp, here, newId, shrink } from '../core/offline-store';

/** Phase L block 1 — the field app: works without a signal. The day's projects are kept on the phone; the report,
 *  attendance, snags, fixes, incidents and inspections are queued and sent when the phone is online again (each
 *  operation once, even if the queue is sent twice). Big buttons, one hand, sunlight. Installable to the home screen
 *  and packaged for Android / iOS with Capacitor (see frontend/capacitor.config.json). */
@Component({
  selector: 'app-field',
  imports: [FormsModule, RouterLink, TPipe, KeyValuePipe],
  template: `
    <header class="top">
      <a routerLink="/app" class="back" aria-label="Back to the app">‹</a>
      <strong class="grow">{{ 'Field app' | t }}</strong>
      <span class="dot" [class.on]="online()">{{ (online() ? 'Online' : 'Offline') | t }}</span>
    </header>
    <section class="bar">
      <span>{{ 'Waiting to send' | t }}: <strong>{{ queued().length }}</strong>@if (failed().length) { · <span class="bad">{{ failed().length }} need attention</span> }</span>
      <button type="button" class="btn" [disabled]="!online() || syncing() || !ops().length" (click)="sync()">{{ syncing() ? 'Sending…' : ('Sync now' | t) }}</button>
    </section>
    @if (msg()) { <div class="msg">{{ msg() }}</div> }
    @if (!data()) { <p class="pad">{{ online() ? 'Loading your projects…' : 'Open this page once with a signal to keep your projects on the phone.' }}</p> }
    @else {
      <div class="pad small muted">{{ data().company }} · {{ data().user.name }} · kept {{ fetched() }}</div>
      <select class="big" [(ngModel)]="pid" aria-label="Project" (ngModelChange)="tab = 'report'">
        @for (p of data().projects; track p.id) { <option [value]="p.id">{{ p.name }}</option> }
      </select>
      @if (proj(); as p) {
        <nav class="tabs">
          @for (x of tabs; track x.v) { <button type="button" [class.active]="tab === x.v" (click)="tab = x.v">{{ x.l | t }}</button> }
        </nav>

        @if (tab === 'report') {
          <div class="card">
            @if (p.today_report) { <div class="small muted">Today's report already has {{ p.today_report.work }} work line(s) and {{ p.today_report.photos }} photo(s); yours is added to it.</div> }
            <label>{{ 'Weather' | t }} <select class="big" [(ngModel)]="rep.weather"><option value="">—</option>@for (w of data().weather; track w) { <option [value]="w">{{ w }}</option> }</select></label>
            <label>{{ 'Manpower' | t }}</label>
            @for (m of rep.manpower; track $index) {
              <div class="row"><select [(ngModel)]="m.trade" aria-label="Trade">@for (tr of data().trades; track tr) { <option [value]="tr">{{ tr }}</option> }</select>
                <input type="number" min="0" inputmode="numeric" [(ngModel)]="m.count" aria-label="Count" class="num" /></div>
            }
            <button type="button" class="link" (click)="rep.manpower.push({ trade: 'Mason', count: 1 })">+ trade</button>
            <label>{{ 'Work done' | t }}</label>
            @for (w of rep.work; track $index) {
              <select [(ngModel)]="w.stage_id" aria-label="Stage">@for (s of p.stages; track s.id) { <option [value]="s.id">{{ s.name }}</option> }</select>
              <textarea rows="2" [(ngModel)]="w.note" placeholder="What was done" aria-label="What was done"></textarea>
            }
            <button type="button" class="link" (click)="rep.work.push({ stage_id: p.stages[0]?.id, note: '' })">+ work</button>
            <label>{{ 'Photos' | t }} <input type="file" accept="image/*" capture="environment" multiple (change)="snap($event, rep.photos)" /></label>
            <div class="thumbs">@for (ph of rep.photos; track ph.blob) { <img [src]="ph.preview" alt="" /> }</div>
            <textarea rows="2" [(ngModel)]="rep.safety" [placeholder]="'Safety' | t" aria-label="Safety"></textarea>
            <button type="button" class="btn wide" [disabled]="!repReady()" (click)="queueReport(p)">{{ 'Save report' | t }}</button>
          </div>
        }

        @if (tab === 'attendance') {
          <div class="card">
            @for (x of p.people; track x.person) {
              <div class="row person"><span class="grow">{{ x.name }} <span class="small muted">{{ x.trade }}</span></span>
                @for (s of data().attendance_statuses; track s) { <button type="button" class="chip" [class.on]="att[x.person] === s" (click)="att[x.person] = s">{{ s | t }}</button> }</div>
            }
            <button type="button" class="btn wide" [disabled]="!attCount()" (click)="queueAttendance(p)">{{ 'Save attendance' | t }} ({{ attCount() }})</button>
          </div>
        }

        @if (tab === 'snags') {
          <div class="card">
            <input class="big" [(ngModel)]="sn.title" placeholder="What is wrong?" aria-label="What is wrong" />
            <input [(ngModel)]="sn.location" placeholder="Where" aria-label="Where" />
            <select [(ngModel)]="sn.priority" aria-label="Priority">@for (x of data().snag_priorities; track x) { <option [value]="x">{{ x }}</option> }</select>
            <label>{{ 'Photos' | t }} <input type="file" accept="image/*" capture="environment" multiple (change)="snap($event, sn.photos)" /></label>
            <div class="thumbs">@for (ph of sn.photos; track ph.blob) { <img [src]="ph.preview" alt="" /> }</div>
            <button type="button" class="btn wide" [disabled]="!sn.title.trim()" (click)="queueSnag(p)">{{ 'New snag' | t }}</button>
          </div>
          @for (s of p.snags; track s.id) {
            <div class="card row"><span class="grow"><strong>{{ s.number }}</strong> {{ s.title }} <span class="small muted">{{ s.location }} · {{ s.status }}</span></span>
              @if (s.status === 'open') { <button type="button" class="chip" (click)="queueFixed(p, s)">{{ 'Mark fixed' | t }}</button> }</div>
          }
        }

        @if (tab === 'safety') {
          <div class="card">
            <strong>Report an incident</strong>
            <select class="big" [(ngModel)]="inc.kind" aria-label="Kind"><option value="">What happened?</option>@for (k of data().incident_kinds | keyvalue; track k.key) { <option [value]="k.key">{{ k.value }}</option> }</select>
            <textarea rows="3" [(ngModel)]="inc.description" placeholder="Describe it" aria-label="Describe it"></textarea>
            <input [(ngModel)]="inc.person" placeholder="Who was hurt (if anyone)" aria-label="Who was hurt" />
            <input [(ngModel)]="inc.injury" placeholder="Injury" aria-label="Injury" />
            <label>{{ 'Photos' | t }} <input type="file" accept="image/*" capture="environment" multiple (change)="snap($event, inc.photos)" /></label>
            <button type="button" class="btn wide danger" [disabled]="!inc.kind || !inc.description.trim()" (click)="queueIncident(p)">Report</button>
          </div>
          <div class="card">
            <strong>Inspection</strong>
            <select class="big" [(ngModel)]="insp.template_id" (ngModelChange)="pickTemplate()" aria-label="Checklist">
              <option value="">Choose a checklist</option>@for (x of data().inspection_templates; track x.id) { <option [value]="x.id">{{ x.name }}</option> }</select>
            @for (r of insp.results; track r.item_id) {
              <div class="item"><div>{{ r.text }}</div>
                <div class="row">@for (o of ['pass', 'fail', 'na']; track o) { <button type="button" class="chip" [class.on]="r.result === o" (click)="r.result = o">{{ o }}</button> }</div>
                @if (r.result === 'fail') { <input [(ngModel)]="r.note" placeholder="What is wrong" aria-label="What is wrong" /> }</div>
            }
            @if (insp.results.length) { <button type="button" class="btn wide" [disabled]="!inspReady()" (click)="queueInspection(p)">Save inspection</button> }
          </div>
        }

        @if (tab === 'queue') {
          @for (o of ops(); track o.op_id) {
            <div class="card" [class.failed]="o.state === 'failed'">
              <div class="row"><span class="grow"><strong>{{ o.label }}</strong> <span class="small muted">{{ o.project_name }} · {{ o.made_at.slice(11, 16) }}</span></span>
                <button type="button" class="link" (click)="discard(o)">discard</button></div>
              @if (o.error) { <div class="small bad">{{ o.error }}</div> }
            </div>
          } @empty { <p class="pad muted">Nothing waiting — everything is sent.</p> }
        }
      }
    }
  `,
  styles: `:host { display: block; max-width: 640px; margin: 0 auto; min-height: 100vh; background: var(--surface, #f6f7f9); font-size: 16px; }
    .top { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: .6rem; padding: .7rem 1rem; background: #1e293b; color: #fff; }
    .back { color: #fff; font-size: 1.6rem; text-decoration: none; line-height: 1; } .grow { flex: 1; }
    .dot { font-size: .8rem; padding: .15rem .5rem; border-radius: 99px; background: #b91c1c; } .dot.on { background: #15803d; }
    .bar { display: flex; align-items: center; justify-content: space-between; gap: .5rem; padding: .6rem 1rem; background: #fff; border-bottom: 1px solid #e5e7eb; }
    .msg { margin: .5rem 1rem; padding: .5rem .7rem; background: #ecfeff; border-radius: 8px; }
    .pad { padding: .5rem 1rem; } .small { font-size: .82rem; } .muted { color: #64748b; } .bad { color: #b91c1c; }
    select, input, textarea { width: 100%; box-sizing: border-box; padding: .6rem; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 1rem; background: #fff; }
    .big { margin: .3rem 1rem; width: calc(100% - 2rem); font-size: 1.05rem; } .card .big { margin: 0; width: 100%; }
    .tabs { display: flex; overflow-x: auto; gap: .3rem; padding: .4rem 1rem; } .tabs button { flex: none; padding: .55rem .8rem; border: 0; border-radius: 99px; background: #e2e8f0; font-size: .95rem; }
    .tabs button.active { background: #1e293b; color: #fff; }
    .card { background: #fff; margin: .5rem 1rem; padding: .8rem; border-radius: 12px; display: grid; gap: .5rem; box-shadow: 0 1px 2px rgba(0,0,0,.06); }
    .card.failed { border-left: 4px solid #b91c1c; } .row { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; } .num { width: 5rem; }
    .btn { padding: .65rem 1rem; border: 0; border-radius: 10px; background: #2563eb; color: #fff; font-size: 1rem; font-weight: 600; }
    .btn:disabled { opacity: .45; } .btn.wide { width: 100%; padding: .9rem; } .btn.danger { background: #b91c1c; }
    .link { border: 0; background: none; color: #2563eb; padding: .2rem 0; text-align: left; font-size: .95rem; }
    .chip { padding: .45rem .7rem; border-radius: 99px; border: 1px solid #cbd5e1; background: #fff; font-size: .85rem; } .chip.on { background: #1e293b; color: #fff; border-color: #1e293b; }
    .person { border-bottom: 1px solid #f1f5f9; padding: .3rem 0; } .thumbs { display: flex; gap: .3rem; flex-wrap: wrap; } .thumbs img { height: 64px; border-radius: 6px; }
    .item { border-bottom: 1px solid #f1f5f9; padding: .3rem 0; display: grid; gap: .3rem; } label { font-weight: 600; font-size: .9rem; }`,
})
export class FieldAppComponent implements OnDestroy {
  private http = inject(HttpClient);
  private auth = inject(AuthService);
  i18n = inject(I18n);
  online = signal(navigator.onLine);
  syncing = signal(false);
  msg = signal('');
  data = signal<any>(null);
  ops = signal<QueuedOp[]>([]);
  queued = computed(() => this.ops().filter((o) => o.state === 'queued'));
  failed = computed(() => this.ops().filter((o) => o.state === 'failed'));
  tabs = [{ v: 'report', l: 'Daily reports' }, { v: 'attendance', l: 'Attendance' }, { v: 'snags', l: 'Snags' }, { v: 'safety', l: 'Safety' }, { v: 'queue', l: 'Waiting to send' }];
  tab = 'report';
  pid = '';
  rep: any = this.blankReport();
  att: Record<string, string> = {};
  sn: any = { title: '', location: '', priority: 'normal', photos: [] };
  inc: any = { kind: '', description: '', person: '', injury: '', photos: [] };
  insp: any = { template_id: '', results: [] };
  private onOn = () => { this.online.set(true); this.refresh(); this.sync(); };
  private onOff = () => this.online.set(false);

  proj = computed(() => this.data()?.projects.find((p: any) => p.id === this.pid) ?? null);

  async ngOnInit() {
    addEventListener('online', this.onOn);
    addEventListener('offline', this.onOff);
    try {
      const cached = await OfflineStore.get(this.key());
      if (cached) this.useData(cached);
      await this.loadOps();
    } catch { this.msg.set('This browser does not keep data offline (private window?).'); }
    if (this.online()) {
      await this.refresh();
      if (this.queued().length) await this.sync();
    }
  }

  ngOnDestroy() {
    removeEventListener('online', this.onOn);
    removeEventListener('offline', this.onOff);
  }

  private key() {
    return `bootstrap:${this.auth.user()?.id}`;
  }

  fetched() {
    const t = this.data()?.fetched_at;
    return t ? new Date(t).toLocaleString() : '';
  }

  private useData(d: any) {
    this.data.set(d);
    if (!d.projects.some((p: any) => p.id === this.pid)) this.pid = d.projects[0]?.id ?? '';
  }

  async refresh() {
    try {
      const d = await firstValueFrom(this.http.get<any>('/api/mobile/bootstrap'));
      this.useData(d);
      await OfflineStore.set(this.key(), d);
    } catch (e: any) {
      if (e?.status === 403) this.msg.set(e.error?.error || 'Your role does not use the field app.');
    }
  }

  private async loadOps() {
    this.ops.set((await OfflineStore.ops()).sort((a, b) => a.made_at.localeCompare(b.made_at)));
  }

  private blankReport() {
    return { weather: '', manpower: [] as any[], work: [] as any[], photos: [] as any[], safety: '' };
  }

  repReady() {
    return this.rep.manpower.length || this.rep.work.some((w: any) => w.note?.trim()) || this.rep.photos.length || this.rep.weather || this.rep.safety.trim();
  }

  attCount() {
    return Object.keys(this.att).length;
  }

  /** A photo taken now: shrunk, kept on the phone with where and when it was taken. */
  async snap(ev: Event, into: any[]) {
    const pos = await here();
    for (const f of Array.from((ev.target as HTMLInputElement).files ?? [])) {
      const blob = await shrink(f);
      const id = newId('ph');
      await OfflineStore.putBlob(id, blob);
      into.push({ blob: id, preview: URL.createObjectURL(blob), taken_at: new Date().toISOString(), ...(pos ?? {}) });
    }
    (ev.target as HTMLInputElement).value = '';
  }

  private async queue(kind: QueuedOp['kind'], p: any, label: string, data: any, photos: any[] = []) {
    const op: QueuedOp = { op_id: newId(), kind, project_id: p.id, project_name: p.name, label, data, blobs: photos.map((x) => x.blob),
      made_at: new Date().toISOString(), state: 'queued' };
    await OfflineStore.putOp(op);
    await this.loadOps();
    this.msg.set(this.online() ? 'Saved — sending…' : 'Saved on the phone — it will be sent when there is a signal.');
    if (this.online()) await this.sync();
  }

  async queueReport(p: any) {
    const r = this.rep;
    await this.queue('site_report', p, `Report: ${r.work.length} work, ${r.photos.length} photo(s)`, {
      date: this.data().today, weather: { kind: r.weather || null }, manpower: r.manpower.filter((m: any) => m.count > 0),
      work: r.work.filter((w: any) => w.note?.trim()), safety: r.safety || null,
      photos: r.photos.map(({ preview, ...x }: any) => ({ ...x, stage_id: r.work[0]?.stage_id })) }, r.photos);
    this.rep = this.blankReport();
  }

  async queueAttendance(p: any) {
    await this.queue('attendance', p, `Attendance: ${this.attCount()} people`, { date: this.data().today,
      rows: Object.entries(this.att).map(([person, status]) => ({ person, status })) });
    this.att = {};
  }

  async queueSnag(p: any) {
    await this.queue('snag', p, `Snag: ${this.sn.title}`, { title: this.sn.title, location: this.sn.location, priority: this.sn.priority,
      photos: this.sn.photos.map((x: any) => ({ blob: x.blob })) }, this.sn.photos);
    this.sn = { title: '', location: '', priority: 'normal', photos: [] };
  }

  async queueFixed(p: any, s: any) {
    const note = prompt('What was done?') ?? '';
    await this.queue('snag_fixed', p, `Fixed: ${s.number}`, { snag_id: s.id, note });
    s.status = 'fixed';
  }

  async queueIncident(p: any) {
    const i = this.inc;
    await this.queue('incident', p, `Incident: ${i.kind}`, { kind: i.kind, description: i.description, date: this.data().today, time: new Date().toTimeString().slice(0, 5),
      people: i.person ? [{ name: i.person, injury: i.injury }] : [], photos: i.photos.map((x: any) => ({ blob: x.blob })) }, i.photos);
    this.inc = { kind: '', description: '', person: '', injury: '', photos: [] };
  }

  pickTemplate() {
    const t = this.data().inspection_templates.find((x: any) => x.id === this.insp.template_id);
    this.insp.results = (t?.items ?? []).map((it: any) => ({ item_id: it.id, text: it.text, result: 'pass', note: '' }));
  }

  inspReady() {
    return this.insp.results.every((r: any) => r.result !== 'fail' || r.note?.trim());
  }

  async queueInspection(p: any) {
    const t = this.data().inspection_templates.find((x: any) => x.id === this.insp.template_id);
    await this.queue('inspection', p, `Inspection: ${t?.name}`, { template_id: this.insp.template_id, date: this.data().today,
      results: this.insp.results.map(({ text, ...r }: any) => r) });
    this.insp = { template_id: '', results: [] };
  }

  async discard(o: QueuedOp) {
    if (!confirm(`Discard "${o.label}"? It has not been sent.`)) return;
    for (const b of o.blobs) await OfflineStore.delBlob(b);
    await OfflineStore.delOp(o.op_id);
    await this.loadOps();
  }

  /** Upload the photos taken offline, swap them for file keys, then send the queue. */
  private async withKeys(o: QueuedOp) {
    const keys: Record<string, string> = {};
    for (const b of o.blobs) {
      const blob = await OfflineStore.blob(b);
      if (!blob) continue;
      const form = new FormData();
      form.append('file', blob, `${b}.jpg`);
      keys[b] = (await firstValueFrom(this.http.post<any>('/api/uploads', form))).key;
    }
    const data = JSON.parse(JSON.stringify(o.data));
    if (Array.isArray(data.photos)) {
      data.photos = data.photos.filter((x: any) => keys[x.blob]).map((x: any) => {
        const { blob, ...rest } = x;
        return o.kind === 'site_report' ? { ...rest, key: keys[blob] } : keys[blob];
      });
    }
    return data;
  }

  async sync() {
    if (this.syncing() || !this.online()) return;
    const todo = this.queued();
    if (!todo.length) return;
    this.syncing.set(true);
    try {
      const batch: any[] = [];
      for (const o of todo.slice(0, 50)) batch.push({ op_id: o.op_id, kind: o.kind, project_id: o.project_id, made_at: o.made_at, data: await this.withKeys(o) });
      const res = await firstValueFrom(this.http.post<any>('/api/mobile/sync', { ops: batch }));
      for (const r of res.results) {
        const o = todo.find((x) => x.op_id === r.op_id);
        if (!o) continue;
        if (r.ok) {
          for (const b of o.blobs) await OfflineStore.delBlob(b);
          await OfflineStore.delOp(o.op_id);
        } else if (r.status >= 400 && r.status < 500) {
          await OfflineStore.putOp({ ...o, state: 'failed', error: r.error });
        }
      }
      this.msg.set(`Sent ${res.applied}` + (res.failed ? `, ${res.failed} need attention (see "Waiting to send")` : '') + '.');
      await this.refresh();
    } catch {
      this.msg.set('Could not reach the server — everything stays on the phone; it will be sent later.');
    } finally {
      this.syncing.set(false);
      await this.loadOps();
    }
  }
}
