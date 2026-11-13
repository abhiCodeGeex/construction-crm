import { TPipe } from '../../core/i18n';
import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api } from '../../core/api.service';

/** Daily site reports (Phase F block 4): one per day — weather, manpower, work done, materials, photos (from the
 *  phone's camera). An issue becomes a project issue; a delay goes to the delay log (the plan is not moved). */
@Component({
  selector: 'app-project-site-reports',
  imports: [TPipe, FormsModule, DatePipe, ButtonModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TagModule, TextareaModule],
  template: `
    @if (data(); as d) {
      <div class="row-between mb">
        <span class="muted small">{{ 'One report a day. It can be changed until the end of the next day.' | t }}</span>
        @if (d.can_write && !d.has_today) { <p-button [label]="writeLabel | t" icon="pi pi-plus" size="small" (onClick)="openNew()" /> }
      </div>
      @for (r of d.reports; track r.id) {
        <div class="rep">
          <div class="row-between wrap gap">
            <div><strong>{{ r.date | date: 'EEE d MMM y' }}</strong> <span class="muted small">· {{ r.author_name }}</span>
              <div class="small">@if (r.weather?.kind) { {{ r.weather.kind }}@if (r.weather.note) { ({{ r.weather.note }}) } · } {{ r.headcount }} on site
                @for (m of r.manpower; track $index) { · {{ m.count }} {{ m.trade }}@if (m.party !== 'Own') { ({{ m.party }}) } }</div></div>
            @if (d.can_write && r.editable) { <span class="row gap">
              <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="openEdit(r)" ariaLabel="Edit" />
              <p-button label="Issue" icon="pi pi-exclamation-circle" size="small" [text]="true" (onClick)="openIssue(r)" />
              <p-button label="Delay" icon="pi pi-clock" size="small" [text]="true" (onClick)="openDelay(r)" />
              <p-button label="AI summary" icon="pi pi-sparkles" size="small" [text]="true" [loading]="aiBusy === r.id" (onClick)="summarise(r)" /></span> }
          </div>
          @if (r.ai_summary; as s) {
            <div class="ai small"><strong>AI summary</strong> <span class="muted">({{ s.source }}, {{ s.photos }} photo(s) — check before sharing)</span>
              <div>{{ s.summary }}</div>
              @for (o of s.safety_concerns; track $index) { <div class="c-bad">⚠ {{ o }}</div> }
              @if (s.client_update) { <div><span class="muted">For the client:</span> {{ s.client_update }} <a href="" (click)="$event.preventDefault(); copy(s.client_update)">copy</a></div> }
              @for (x of s.stages; track x.stage_id) { <div class="muted">{{ x.stage_name }}: now {{ x.now }}%, looks like {{ x.suggested }}% — {{ x.why }}</div> }
            </div>
          }
          @for (w of r.work; track $index) { <div class="small"><strong>{{ w.stage_name }}</strong>@if (w.task_title) { · {{ w.task_title }} }: {{ w.note }}</div> }
          @if (r.materials) { <div class="small"><span class="muted">Materials:</span> {{ r.materials }}</div> }
          @if (r.equipment) { <div class="small"><span class="muted">Equipment:</span> {{ r.equipment }}</div> }
          @if (r.visitors) { <div class="small"><span class="muted">Visitors:</span> {{ r.visitors }}</div> }
          @if (r.safety) { <div class="small c-bad"><span class="muted">Safety:</span> {{ r.safety }}</div> }
          @for (i of r.issues; track i.id) { <div class="small"><p-tag [value]="i.severity" [severity]="i.severity === 'high' ? 'danger' : 'warn'" /> {{ i.title }}</div> }
          @for (x of r.delays; track x.id) { <div class="small c-warn">Delay: {{ x.stage_name }} lost {{ x.days }} day(s) — {{ x.reason_label }}@if (x.note) { : {{ x.note }} }</div> }
          @if (r.photos.length) {
            <div class="photos">@for (ph of r.photos; track ph.key) {
              <span class="ph"><a [href]="ph.url" target="_blank" rel="noopener" [title]="photoTitle(ph)"><img [src]="ph.url" [alt]="ph.caption || 'Site photo'" />
                @if (ph.shareable) { <span class="share">client</span> }</a>
                <span class="tiny muted">@if (ph.stage_name || ph.room) { {{ ph.stage_name }}@if (ph.room) { · {{ ph.room }} } }
                  @if (ph.lat) { <a [href]="'https://www.openstreetmap.org/?mlat=' + ph.lat + '&mlon=' + ph.lng + '#map=18/' + ph.lat + '/' + ph.lng" target="_blank" rel="noopener" title="Where it was taken"><i class="pi pi-map-marker"></i></a> }</span></span> }</div>
          }
        </div>
      } @empty { <p class="muted">{{ 'No reports yet.' | t }}</p> }
    }

    <p-dialog [header]="f.id ? 'Edit site report' : 'Site report · today'" [modal]="true" [(visible)]="dlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Weather</span><p-select [options]="data()?.weather ?? []" [(ngModel)]="f.weather.kind" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Weather note</span><input pInputText [(ngModel)]="f.weather.note" fluid /></label>
        </div>
        <div class="small muted">Manpower</div>
        @for (m of f.manpower; track $index; let i = $index) {
          <div class="mp-row">
            <p-select [options]="data()?.trades ?? []" [(ngModel)]="m.trade" [editable]="true" placeholder="Trade" appendTo="body" />
            <p-inputnumber [(ngModel)]="m.count" [min]="0" [showButtons]="true" [inputStyle]="{ width: '4rem' }" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.manpower.splice(i, 1)" ariaLabel="Remove" />
          </div>
        }
        <p-button label="Add trade" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.manpower.push({ trade: '', count: 1 })" />
        <div class="small muted">Work done</div>
        @for (w of f.work; track $index; let i = $index) {
          <div class="work-row">
            <p-select [options]="data()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="w.stage_id" placeholder="Stage" appendTo="body" />
            <p-select [options]="tasksOf(w.stage_id)" optionLabel="title" optionValue="id" [(ngModel)]="w.task_id" [showClear]="true" placeholder="Task (optional)" appendTo="body" />
            <input pInputText [(ngModel)]="w.note" placeholder="What was done" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.work.splice(i, 1)" ariaLabel="Remove" />
          </div>
        }
        <p-button label="Add work" icon="pi pi-plus" size="small" [text]="true" (onClick)="f.work.push({ stage_id: null, task_id: null, note: '' })" />
        <label class="field"><span>Materials received</span><input pInputText [(ngModel)]="f.materials" fluid /></label>
        <div class="grid2">
          <label class="field"><span>Equipment</span><input pInputText [(ngModel)]="f.equipment" fluid /></label>
          <label class="field"><span>Visitors</span><input pInputText [(ngModel)]="f.visitors" fluid /></label>
        </div>
        <label class="field"><span>Safety incidents</span><input pInputText [(ngModel)]="f.safety" fluid /></label>
        <label class="field"><span>Photos</span><input type="file" accept="image/*" capture="environment" multiple (change)="addPhotos($event)" /></label>
        @for (ph of f.photos; track ph.key; let i = $index) {
          <div class="ph-row"><span class="small">{{ ph.name || 'photo' }}</span>
            <input pInputText [(ngModel)]="ph.caption" placeholder="Caption" />
            <p-select [options]="data()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="ph.stage_id" [showClear]="true" placeholder="Stage" appendTo="body" />
            <input pInputText [(ngModel)]="ph.room" placeholder="Room / area" />
            <label class="check small"><p-checkbox [(ngModel)]="ph.shareable" [binary]="true" ariaLabel="Show to the client" /> client</label>
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="f.photos.splice(i, 1)" ariaLabel="Remove photo" /></div>
        }
        <div class="row right"><p-button [label]="'Save report' | t" icon="pi pi-check" [disabled]="busy" (onClick)="save()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Issue seen on site" [modal]="true" [(visible)]="isDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>What</span><input pInputText [(ngModel)]="xf.title" fluid /></label>
        <div class="grid2">
          <label class="field"><span>Severity</span><p-select [options]="data()?.severities ?? []" [(ngModel)]="xf.severity" fluid appendTo="body" /></label>
          <label class="field"><span>Stage</span><p-select [options]="data()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="xf.stage_id" [showClear]="true" fluid appendTo="body" /></label>
        </div>
        <p class="small muted m0">It becomes a project issue; a high one holds its stage until it is closed.</p>
        <div class="row right"><p-button label="Raise" [disabled]="!xf.title?.trim()" (onClick)="saveIssue()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Work held up" [modal]="true" [(visible)]="dlDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>Stage</span><p-select [options]="data()?.stages ?? []" optionLabel="name" optionValue="id" [(ngModel)]="xf.stage_id" fluid appendTo="body" /></label>
        <div class="grid2">
          <label class="field req"><span>Why</span><p-select [options]="data()?.delay_reasons ?? []" optionLabel="label" optionValue="value" [(ngModel)]="xf.reason" fluid appendTo="body" /></label>
          <label class="field req"><span>Working days lost</span><p-inputnumber [(ngModel)]="xf.days" [min]="0.5" [maxFractionDigits]="1" fluid /></label>
        </div>
        <label class="field"><span>Note</span><input pInputText [(ngModel)]="xf.note" fluid /></label>
        <p class="small muted m0">Recorded in the delay log; the plan is not moved. The PM is asked to review it.</p>
        <div class="row right"><p-button label="Record" [disabled]="!xf.stage_id || !xf.reason || !xf.days" (onClick)="saveDelay()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.ai { background: var(--surface-ground, #f1f5f9); border-radius: 8px; padding: .5rem .7rem; margin-top: .3rem; display: grid; gap: .2rem; }

    .rep { border: 1px solid var(--border); border-radius: var(--radius); padding: .75rem 1rem; margin-bottom: .75rem; background: var(--surface); display: grid; gap: .25rem; }
    .photos { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .3rem; }
    .photos a { position: relative; }
    .photos img { width: 6rem; height: 4.5rem; object-fit: cover; border-radius: 6px; }
    .share { position: absolute; left: .2rem; bottom: .2rem; font-size: .65rem; background: rgba(0, 0, 0, .6); color: #fff; padding: 0 .3rem; border-radius: 4px; }
    .mp-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: .4rem; align-items: center; }
    .work-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 2fr) auto; gap: .4rem; align-items: center; }
    .ph-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) minmax(0, 1.2fr) minmax(0, 1fr) auto auto; gap: .4rem; align-items: center; }
    .ph { display: inline-flex; flex-direction: column; gap: .1rem; max-width: 6rem; }
    .tiny { font-size: .7rem; line-height: 1.1; }
    @media (max-width: 640px) { .work-row, .ph-row { grid-template-columns: 1fr 1fr; } }
  `,
})
export class ProjectSiteReportsComponent implements OnInit {
  writeLabel = "Write today's report";
  projectId = input.required<string>();
  private api = inject(Api);
  data = signal<any>(null);
  dlg = false; isDlg = false; dlDlg = false; busy = false;
  f: any = { weather: {}, manpower: [], work: [], photos: [] };
  xf: any = {};
  private target: any = null;
  stagesById = computed(() => Object.fromEntries((this.data()?.stages ?? []).map((s: any) => [s.id, s])));

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.data.set(await this.api.get(`/projects/${this.projectId()}/site-reports`));
  }

  tasksOf(sid: string) {
    return this.stagesById()[sid]?.tasks ?? [];
  }

  openNew() {
    this.f = { weather: { kind: null, note: '' }, manpower: [{ trade: 'Mason', count: 1 }], work: [{ stage_id: null, task_id: null, note: '' }],
      materials: '', equipment: '', visitors: '', safety: '', photos: [] };
    this.dlg = true;
  }

  openEdit(r: any) {
    this.f = { id: r.id, weather: { ...(r.weather ?? {}) }, manpower: r.manpower.map((m: any) => ({ ...m })),
      work: r.work.map((w: any) => ({ stage_id: w.stage_id, task_id: w.task_id, note: w.note })), materials: r.materials ?? '',
      equipment: r.equipment ?? '', visitors: r.visitors ?? '', safety: r.safety ?? '',
      photos: r.photos.map((p: any) => ({ key: p.key, name: p.name, caption: p.caption, shareable: p.shareable, stage_id: p.stage_id, room: p.room })) };
    this.dlg = true;
  }

  async addPhotos(ev: Event) {
    const files = Array.from((ev.target as HTMLInputElement).files ?? []);
    this.busy = true;
    try {
      const where = await this.position();  // Phase I: where the photos were taken (the phone asks once)
      const stage = this.f.work.find((w: any) => w.stage_id)?.stage_id ?? null;
      for (const file of files) {
        const up = await this.api.upload(file);
        this.f.photos.push({ key: up.key, name: up.name, caption: '', shareable: false, stage_id: stage, room: '',
          taken_at: new Date(file.lastModified || Date.now()).toISOString(), ...(where ?? {}) });
      }
    } finally {
      this.busy = false;
      (ev.target as HTMLInputElement).value = '';
    }
  }

  /** The phone's position, or null when it is refused or not available in a few seconds. */
  private position(): Promise<{ lat: number; lng: number; accuracy_m: number } | null> {
    if (!navigator.geolocation) return Promise.resolve(null);
    return new Promise((resolve) => {
      const done = setTimeout(() => resolve(null), 6000);
      navigator.geolocation.getCurrentPosition(
        (p) => { clearTimeout(done); resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy) }); },
        () => { clearTimeout(done); resolve(null); }, { enableHighAccuracy: true, timeout: 5000, maximumAge: 60000 });
    });
  }

  photoTitle(ph: any) {
    return [ph.caption, ph.taken_at ? 'taken ' + new Date(ph.taken_at).toLocaleString() : ''].filter(Boolean).join(' · ');
  }

  // Phase L block 3 — Claude reads the report's photos and notes; the PM decides what to share or change
  aiBusy: string | null = null;

  async summarise(r: any) {
    this.aiBusy = r.id;
    try {
      r.ai_summary = await this.api.post(`/site-reports/${r.id}/ai/summary`, {});
    } finally {
      this.aiBusy = null;
    }
  }

  copy(text: string) {
    navigator.clipboard?.writeText(text);
  }

  async save() {
    const { id, ...body } = this.f;
    body.manpower = body.manpower.filter((m: any) => m.trade && m.count);
    body.work = body.work.filter((w: any) => w.stage_id && w.note?.trim());
    if (id) await this.api.put(`/site-reports/${id}`, body, 'Report saved');
    else await this.api.post(`/projects/${this.projectId()}/site-reports`, body, 'Report saved');
    this.dlg = false;
    await this.load();
  }

  openIssue(r: any) {
    this.target = r;
    this.xf = { title: '', severity: 'medium', stage_id: null };
    this.isDlg = true;
  }

  async saveIssue() {
    await this.api.post(`/site-reports/${this.target.id}/issues`, this.xf, 'Issue raised');
    this.isDlg = false;
    await this.load();
  }

  openDelay(r: any) {
    this.target = r;
    this.xf = { stage_id: null, reason: 'weather', days: 1, note: '' };
    this.dlDlg = true;
  }

  async saveDelay() {
    await this.api.post(`/site-reports/${this.target.id}/delays`, this.xf, 'Delay recorded');
    this.dlDlg = false;
    await this.load();
  }
}
