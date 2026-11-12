import { Component, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { MessageService } from 'primeng/api';
import { Api } from '../../core/api.service';

/** Phase J blocks 1-3 — WhatsApp for site workers on a project: job cards, what workers sent (material, work done,
 *  questions), rooms with their QR code, and today's morning messages. */
@Component({
  selector: 'app-project-field',
  imports: [FormsModule, DatePipe, ButtonModule, DialogModule, InputTextModule, MultiSelectModule, SelectButtonModule, TagModule],
  template: `
    <p-selectbutton class="mb block" [options]="parts" [(ngModel)]="part" optionLabel="label" optionValue="value" [allowEmpty]="false" (ngModelChange)="load()" />
    @switch (part) {
      @case ('updates') {
        <div class="row gap mb wrap">
          <p-selectbutton [options]="filters" [(ngModel)]="filter" optionLabel="label" optionValue="value" [allowEmpty]="false" (ngModelChange)="load()" />
          <span class="small muted">Workers answer the morning message with a button, text, a voice note or a photo.</span>
        </div>
        @for (u of updates(); track u.id) {
          <div class="card-row" [class.urgent]="u.urgent && !u.acknowledged_at">
            <div class="row-between wrap gap">
              <div><strong>{{ u.worker_name }}</strong> · <p-tag [value]="kinds[u.kind] || u.kind" [severity]="u.kind === 'done' ? 'success' : u.kind === 'help' ? 'info' : u.kind === 'material' ? 'warn' : 'secondary'" />
                <p-tag [value]="u.status" severity="secondary" styleClass="ml-xs" />
                @if (u.urgent) { <p-tag value="URGENT" severity="danger" styleClass="ml-xs" /> } @if (u.escalated) { <span class="small c-bad"> escalated to the Owner</span> }
                <div class="small muted">{{ u.created_at | date: 'd MMM, HH:mm' }} @if (u.task_title) { · {{ u.task_title }} } @if (u.pr_number) { · {{ u.pr_number }} }</div></div>
              <span class="row gap">
                @if (u.kind === 'done' && u.status === 'pending') {
                  <p-button label="Approve" icon="pi pi-check" size="small" (onClick)="act(u, 'approve')" />
                  <p-button label="Send back" size="small" [text]="true" (onClick)="ask(u, 'reject')" /> }
                @if ((u.kind === 'help' || u.kind === 'other') && u.status === 'open') { <p-button label="Answer" icon="pi pi-reply" size="small" (onClick)="ask(u, 'answer')" /> }
                @if (u.urgent && !u.acknowledged_at) { <p-button label="I'm on it" size="small" severity="danger" [outlined]="true" (onClick)="act(u, 'ack')" /> }
                @if (u.status === 'open') { <p-button label="Close" size="small" [text]="true" severity="secondary" (onClick)="act(u, 'close')" /> }
              </span>
            </div>
            @if (u.text) { <div class="pre">{{ u.text }}</div> }
            @for (m of u.media; track $index) {
              @if (m.url && m.type === 'voice') { <audio controls [src]="m.url"></audio> }
              @else if (m.url) { <a [href]="m.url" target="_blank" rel="noopener" class="small"><i class="pi pi-image"></i> {{ m.type }}</a> }
              @else { <span class="small muted"><i class="pi pi-microphone"></i> {{ m.type }} on WhatsApp (media {{ m.media_id }})</span> }
            }
            @if (u.answer) { <div class="small"><strong>{{ u.answered_by }}:</strong> {{ u.answer }}</div> }
            @if (u.reason) { <div class="small c-bad">Sent back: {{ u.reason }}</div> }
          </div>
        } @empty { <p class="muted">Nothing from the workers here.</p> }
      }
      @case ('cards') {
        <p class="small muted">A job card per task: the room, the trade, the workers, drawings, measurements and photos. Workers open it from the link in their WhatsApp without signing in.</p>
        @for (t of tasks(); track t.id) {
          <div class="card-row">
            <div class="row-between wrap gap">
              <div><strong>{{ t.title }}</strong> <span class="small muted">{{ t.start }} → {{ t.end }} · {{ t.status }}</span>
                @if (card(t.id); as c) { <div class="small">@if (c.room) { {{ c.room }} · } @if (c.trade) { {{ c.trade }} · } {{ names(c.workers) || 'no workers yet' }}
                  @if (c.drawings.length) { · {{ c.drawings.length }} drawing(s) }</div> }</div>
              <span class="row gap">
                <p-button label="Job card" icon="pi pi-id-card" size="small" [text]="true" (onClick)="openCard(t)" />
                @if (card(t.id)?.worker_ids?.length) { <p-button label="Send on WhatsApp" icon="pi pi-whatsapp" size="small" [text]="true" (onClick)="sendCard(t)" /> }
              </span>
            </div>
          </div>
        } @empty { <p class="muted">Add tasks on the Stages & tasks tab first.</p> }
      }
      @case ('rooms') {
        <p class="small muted">Stick the QR code in the room: scanning it opens the room's latest drawings, the chosen finishes and the jobs — no sign-in.</p>
        <div class="row gap mb"><input pInputText [(ngModel)]="newRoom" placeholder="Room name (e.g. Kitchen)" /><p-button label="Make QR code" size="small" [disabled]="!newRoom.trim()" (onClick)="makeQr(newRoom); newRoom = ''" /></div>
        <div class="qr-grid">
          @for (r of rooms(); track r.room) {
            <div class="card-row qr">
              <strong>{{ r.room }}</strong>
              <span class="small muted">{{ r.drawings }} drawing(s) · {{ r.specs }} finish(es) · {{ r.jobs }} job(s)</span>
              @if (r.link) { <img [src]="'/api/qr.svg?data=' + enc(r.link)" [alt]="'QR code for ' + r.room" />
                <a class="small" [href]="r.link" target="_blank" rel="noopener">Open the room page</a>
                <p-button label="Print" icon="pi pi-print" size="small" [text]="true" (onClick)="print(r)" /> }
              @else { <p-button label="Make QR code" size="small" (onClick)="makeQr(r.room)" /> }
            </div>
          } @empty { <p class="muted">Rooms appear here from job cards, documents and selections.</p> }
        </div>
      }
      @case ('morning') {
        <div class="row-between wrap gap mb"><span class="small muted">Today's work message to each worker (sent automatically at the time set in Company settings → Field & WhatsApp).</span>
          <p-button label="Send now" icon="pi pi-send" size="small" [disabled]="!morning().length" (onClick)="sendMorning()" /></div>
        @for (m of morning(); track m.worker_id) {
          <div class="card-row"><div class="row-between"><strong>{{ m.worker }}</strong>
            <span class="small" [class.c-bad]="!m.whatsapp">{{ m.whatsapp ? 'WhatsApp' : 'no WhatsApp opt-in — not sent' }} · {{ m.language === 'hi' ? 'Hindi' : 'English' }}</span></div>
            <div class="pre small">{{ m.text }}</div></div>
        } @empty { <p class="muted">No worker has a job card with work today.</p> }
      }
    }

    <p-dialog [header]="'Job card — ' + (cf.task || '')" [modal]="true" [(visible)]="cDlg" [style]="{ width: '40rem' }" [breakpoints]="{ '640px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Room</span><input pInputText [(ngModel)]="cf.room" fluid /></label>
          <label class="field"><span>Trade</span><input pInputText [(ngModel)]="cf.trade" placeholder="Plumbing, tiling…" fluid /></label>
        </div>
        <label class="field"><span>Workers</span><p-multiselect [options]="workers()" optionLabel="name" optionValue="id" [(ngModel)]="cf.worker_ids" display="chip" fluid appendTo="body" /></label>
        <label class="field"><span>Drawings</span><p-multiselect [options]="docs()" optionLabel="name" optionValue="id" [(ngModel)]="cf.document_ids" display="chip" fluid appendTo="body" /></label>
        <span class="small">Measurements</span>
        @for (m of cf.measurements; track $index; let i = $index) {
          <div class="row gap"><input pInputText [(ngModel)]="m.label" placeholder="What" class="grow" /><input pInputText [(ngModel)]="m.value" placeholder="Size" />
            <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="cf.measurements.splice(i, 1)" ariaLabel="Remove measurement" /></div>
        }
        <p-button label="Add a measurement" icon="pi pi-plus" size="small" [text]="true" (onClick)="cf.measurements.push({ label: '', value: '' })" />
        <label class="field"><span>Instructions</span><textarea class="p-inputtext" rows="3" [(ngModel)]="cf.instructions"></textarea></label>
        <label class="field"><span>Reference photos</span><input type="file" accept="image/*" multiple (change)="attach($event)" /></label>
        <div class="small muted">{{ cf.photos.length }} photo(s)</div>
        @if (cf.link) { <a class="small" [href]="cf.link" target="_blank" rel="noopener">Public link the worker opens</a> }
        <div class="row right"><p-button label="Save" (onClick)="saveCard()" /></div>
      </div>
    </p-dialog>
    <p-dialog [header]="askKind === 'answer' ? 'Answer the worker' : 'Send the work back'" [modal]="true" [(visible)]="aDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field req"><span>{{ askKind === 'answer' ? 'Answer (sent on WhatsApp)' : 'What is still to do' }}</span><textarea class="p-inputtext" rows="3" [(ngModel)]="answer"></textarea></label>
        <div class="row right"><p-button label="Send" [disabled]="!answer.trim()" (onClick)="sendAnswer()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `.card-row { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .9rem; margin-bottom: .6rem; background: var(--surface); display: grid; gap: .3rem; }
    .card-row.urgent { border-color: var(--red, #c0392b); }
    .pre { white-space: pre-wrap; } .qr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: .6rem; }
    .qr img { width: 160px; height: 160px; } audio { max-width: 100%; }`,
})
export class ProjectFieldComponent {
  projectId = input.required<string>();
  private api = inject(Api);
  private toast = inject(MessageService);
  info = (detail: string) => this.toast.add({ severity: 'info', summary: detail, life: 4000 });
  parts = [{ label: 'From workers', value: 'updates' }, { label: 'Job cards', value: 'cards' }, { label: 'Rooms & QR', value: 'rooms' }, { label: 'Morning message', value: 'morning' }];
  part = 'updates';
  filters = [{ label: 'Open', value: 'awaiting,open,pending' }, { label: 'All', value: '' }];
  filter = 'awaiting,open,pending';
  kinds: Record<string, string> = { material: 'Material needed', done: 'Work done', help: 'Need help', other: 'Message' };
  updates = signal<any[]>([]);
  tasks = signal<any[]>([]);
  cards = signal<any[]>([]);
  rooms = signal<any[]>([]);
  morning = signal<any[]>([]);
  workers = signal<any[]>([]);
  docs = signal<any[]>([]);
  cDlg = false; aDlg = false;
  cf: any = { measurements: [], photos: [] };
  target: any = null;
  askKind = '';
  answer = '';
  newRoom = '';
  enc = encodeURIComponent;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const pid = this.projectId();
    if (this.part === 'updates') this.updates.set(await this.api.get(`/field-updates?project_id=${pid}${this.filter ? '&status=' + this.filter : ''}`));
    if (this.part === 'cards') {
      const [p, cards] = await Promise.all([this.api.get(`/projects/${pid}`), this.api.get(`/projects/${pid}/job-cards`)]);
      this.tasks.set(p.stages.flatMap((s: any) => s.tasks ?? []));
      this.cards.set(cards);
    }
    if (this.part === 'rooms') this.rooms.set(await this.api.get(`/projects/${pid}/rooms`));
    if (this.part === 'morning') this.morning.set(await this.api.get(`/worker-messages/preview`).then((r: any[]) => r));
  }

  card = (tid: string) => this.cards().find((c) => c.task_id === tid);
  names = (ws: any[]) => (ws ?? []).map((w) => w.name).join(', ');

  async openCard(t: any) {
    const pid = this.projectId();
    const [c, ws, docs] = await Promise.all([this.api.get(`/projects/${pid}/tasks/${t.id}/job`), this.api.get('/site-workers'), this.api.get(`/projects/${pid}/documents`).catch(() => [])]);
    this.workers.set(ws.filter((w: any) => w.active !== false));
    this.docs.set((Array.isArray(docs) ? docs : docs.documents ?? []).map((d: any) => ({ id: d.id, name: d.number ? `${d.number} ${d.name}` : d.name })));
    this.cf = { task_id: t.id, task: t.title, room: c.room ?? '', trade: c.trade ?? '', worker_ids: c.worker_ids, document_ids: c.document_ids,
      measurements: c.measurements.map((m: any) => ({ ...m })), instructions: c.instructions ?? '', photos: c.photos.map((p: any) => p.key), link: c.link };
    this.cDlg = true;
  }

  async attach(ev: Event) {
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) this.cf.photos.push((await this.api.upload(file)).key);
  }

  async saveCard() {
    const { task_id, task, link, ...body } = this.cf;
    body.measurements = body.measurements.filter((m: any) => m.label?.trim());
    await this.api.put(`/projects/${this.projectId()}/tasks/${task_id}/job`, body, 'Job card saved');
    this.cDlg = false;
    await this.load();
  }

  async sendCard(t: any) {
    const r: any[] = await this.api.post(`/projects/${this.projectId()}/tasks/${t.id}/job/send`, {});
    const bad = r.filter((x) => x.status !== 'sent');
    this.info(bad.length ? `Not sent to ${bad.map((x) => `${x.worker} (${x.error || x.status})`).join(', ')}` : 'Sent on WhatsApp');
  }

  async act(u: any, what: string) {
    await this.api.post(`/field-updates/${u.id}/${what}`, {}, what === 'approve' ? 'Approved — the task is done' : 'Saved');
    await this.load();
  }

  ask(u: any, kind: string) {
    this.target = u;
    this.askKind = kind;
    this.answer = '';
    this.aDlg = true;
  }

  async sendAnswer() {
    const body = this.askKind === 'answer' ? { text: this.answer } : { reason: this.answer };
    await this.api.post(`/field-updates/${this.target.id}/${this.askKind}`, body, 'Sent to the worker');
    this.aDlg = false;
    await this.load();
  }

  async makeQr(room: string) {
    await this.api.post(`/projects/${this.projectId()}/rooms/qr`, { room: room.trim() });
    await this.load();
  }

  print(r: any) {
    const w = window.open('', '_blank', 'width=420,height=560');
    if (!w) return;
    w.document.write(`<html><head><title>${r.room}</title></head><body style="font-family:sans-serif;text-align:center">
      <h2>${r.room.replace(/</g, '&lt;')}</h2><img src="${location.origin}/api/qr.svg?data=${encodeURIComponent(r.link)}" style="width:320px" />
      <p>Scan for the latest drawings and finishes</p><script>window.onload = () => window.print()<\/script></body></html>`);
    w.document.close();
  }

  async sendMorning() {
    const r: any[] = await this.api.post('/worker-messages/send', {});
    const sent = r.filter((x) => x.status === 'sent').length;
    this.info(`${sent} of ${r.length} sent on WhatsApp`);
    await this.load();
  }
}
