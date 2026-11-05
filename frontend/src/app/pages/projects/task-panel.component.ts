import { Component, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { TooltipModule } from 'primeng/tooltip';
import { CheckboxModule } from 'primeng/checkbox';
import { DrawerModule } from 'primeng/drawer';
import { InputTextModule } from 'primeng/inputtext';
import { MenuModule } from 'primeng/menu';
import { ProgressBarModule } from 'primeng/progressbar';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { MenuItem } from 'primeng/api';
import { Api, STATUS_SEVERITY, label } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

export const PRIORITY_SEVERITY: Record<string, 'secondary' | 'info' | 'warn' | 'danger'> = {
  low: 'secondary', normal: 'info', high: 'warn', urgent: 'danger',
};

/** One task in depth (B+2): checklist, files and photos, comments with @mentions, who it is waiting on. */
@Component({
  selector: 'app-task-panel',
  imports: [TooltipModule, FormsModule, DatePipe, ButtonModule, CheckboxModule, DrawerModule, InputTextModule, MenuModule, ProgressBarModule, TagModule, TextareaModule],
  template: `
    <p-drawer [(visible)]="visible" position="right" [style]="{ width: '34rem' }" styleClass="task-drawer" (onHide)="closed.emit()">
      <ng-template #header><strong>{{ task()?.title }}</strong></ng-template>
      @if (task(); as t) {
        <div class="stack">
          <div class="row gap wrap">
            <p-tag [value]="statusText[t.status] ?? t.status" [severity]="sev[t.status]" />
            <p-tag [value]="'Priority: ' + t.priority" [severity]="prio[t.priority]" />
            <span class="small muted">{{ stageName() }} · {{ t.start | date: 'd MMM' }} → {{ t.end | date: 'd MMM y' }}</span>
            @if (t.baseline?.slip_days) { <p-tag [value]="(t.baseline.slip_days > 0 ? '+' : '') + t.baseline.slip_days + ' d vs baseline'" [severity]="t.baseline.slip_days > 0 ? 'danger' : 'success'" /> }
          </div>
          <div class="small">Assigned to <b>{{ t.assignee_name || 'nobody' }}</b></div>
          @if (t.status === 'blocked' && t.waiting_on) {
            <div class="waiting"><i class="pi pi-hourglass"></i> Waiting on <b>{{ partyLabel(t.waiting_on.party) }}</b>{{ t.waiting_on.contact_name ? ' (' + t.waiting_on.contact_name + ')' : '' }}
              since {{ t.waiting_on.since | date: 'd MMM' }}{{ t.waiting_on.note ? ' — ' + t.waiting_on.note : '' }}</div>
          }
          @if (t.notes) { <p class="small muted pre">{{ t.notes }}</p> }

          <!-- checklist -->
          <section>
            <div class="row-between"><b>Checklist</b>
              @if (t.checklist.length) { <small class="muted">{{ doneCount() }} / {{ t.checklist.length }} done</small> }</div>
            @if (t.checklist.length) { <p-progressbar [value]="doneCount() / t.checklist.length * 100" [showValue]="false" styleClass="thin mt-xs" /> }
            @for (c of t.checklist; track c.id) {
              <div class="check-row">
                <p-checkbox [binary]="true" [ngModel]="c.done" (onChange)="tick(c, $event.checked)" [disabled]="!canWork()" />
                <span class="grow" [class.strike]="c.done">{{ c.text }} @if (c.done && c.done_by) { <small class="muted">· {{ c.done_by }}</small> }</span>
                @if (canWork()) { <p-button icon="pi pi-times" [text]="true" size="small" severity="secondary" (onClick)="removeItem(c)" ariaLabel="Remove" pTooltip="Remove"/> }
              </div>
            } @empty { <p class="small muted">No checklist. Break the task into steps; it can be marked done once every step is ticked.</p> }
            @if (canWork()) {
              <form class="row gap mt-xs" (ngSubmit)="addItem()"><input pInputText name="ni" [(ngModel)]="newItem" placeholder="Add a step" class="grow" />
                <p-button type="submit" icon="pi pi-plus" [disabled]="!newItem.trim()" ariaLabel="Add" pTooltip="Add"/></form>
            }
          </section>

          <!-- files -->
          <section>
            <div class="row-between"><b>Files & photos</b>
              @if (canWork()) { <label class="p-button p-button-sm p-button-text"><i class="pi pi-upload mr"></i>Add
                <input type="file" hidden (change)="upload($event)" accept=".pdf,.png,.jpg,.jpeg,.webp,.heic,.doc,.docx,.xlsx,.xls,.csv,.dwg,.dxf,.mp4,.mov" /></label> }</div>
            @for (f of t.files; track f.id) {
              <div class="file-row"><i class="pi" [class.pi-image]="isImage(f.name)" [class.pi-file]="!isImage(f.name)"></i>
                <a href="" class="grow" (click)="$event.preventDefault(); api.openFile('/api/files/' + f.key)">{{ f.name }}</a>
                <small class="muted">{{ f.caption ? f.caption + ' · ' : '' }}{{ f.by }} · {{ f.at | date: 'd MMM' }}</small>
                @if (f.by_id === auth.user()?.id || canEdit()) { <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="removeFile(f)" ariaLabel="Delete" pTooltip="Delete"/> }
              </div>
            } @empty { <p class="small muted">No files yet — drawings, site photos, delivery notes.</p> }
          </section>

          <!-- comments -->
          <section>
            <b>Comments</b>
            @for (c of comments(); track c.id) {
              <div class="comment"><div class="row-between"><small><b>{{ c.by }}</b> · {{ c.at | date: 'd MMM, h:mm a' }}</small>
                @if (c.by_id === auth.user()?.id || auth.user()?.role === 'owner') { <p-button icon="pi pi-trash" [text]="true" size="small" severity="secondary" (onClick)="removeComment(c)" ariaLabel="Delete" pTooltip="Delete"/> }</div>
                <div class="pre" [innerHTML]="highlight(c.text)"></div></div>
            } @empty { <p class="small muted">No comments yet.</p> }
            <div class="stack mt-xs">
              <textarea pTextarea rows="3" [(ngModel)]="newComment" placeholder="Write a comment. Use @ to mention someone on the team." fluid></textarea>
              <div class="row-between">
                <p-button label="@ Mention" icon="pi pi-at" [text]="true" size="small" (onClick)="menu.toggle($event)" />
                <p-menu #menu [model]="mentionMenu()" [popup]="true" appendTo="body" />
                <p-button label="Comment" icon="pi pi-send" size="small" [disabled]="!newComment.trim()" (onClick)="addComment()" />
              </div>
              <small class="muted">People you mention are notified; the person the task is assigned to is told about every comment.</small>
            </div>
          </section>
        </div>
      }
    </p-drawer>
  `,
  styles: `
    section { border-top: 1px solid var(--border); padding-top: .75rem; }
    .check-row, .file-row { display: flex; align-items: center; gap: .5rem; padding: .25rem 0; }
    .strike { text-decoration: line-through; color: var(--muted); }
    .comment { background: color-mix(in srgb, var(--text) 4%, transparent); border-radius: 8px; padding: .5rem .65rem; margin-top: .5rem; }
    .pre { white-space: pre-wrap; }
    .waiting { background: color-mix(in srgb, #f59e0b 12%, transparent); border-radius: 8px; padding: .45rem .65rem; font-size: .9rem; }
    :host ::ng-deep .mention { color: var(--brand); font-weight: 600; }
  `,
})
export class TaskPanelComponent {
  project = input.required<any>();
  parties = input<{ value: string; label: string }[]>([]);
  /** the server's updated project after a change */
  changed = output<any>();
  closed = output<void>();
  api = inject(Api);
  auth = inject(AuthService);
  visible = false;
  taskId = signal<string | null>(null);
  comments = signal<any[]>([]);
  newItem = '';
  newComment = '';
  sev = STATUS_SEVERITY;
  prio = PRIORITY_SEVERITY;
  label = label;
  statusText: Record<string, string | undefined> = { todo: 'To do', in_progress: 'In progress', blocked: 'Blocked', done: 'Done' };

  stage = computed(() => (this.project()?.stages ?? []).find((s: any) => (s.tasks ?? []).some((t: any) => t.id === this.taskId())));
  task = computed(() => this.stage()?.tasks.find((t: any) => t.id === this.taskId()) ?? null);
  stageName = computed(() => this.stage()?.name ?? '');
  doneCount = computed(() => (this.task()?.checklist ?? []).filter((c: any) => c.done).length);
  canEdit = computed(() => {
    const p = this.project();
    const s = this.stage();
    return p?.my_access === 'edit' || (p?.can_edit_design && ['architecture', 'interior'].includes(s?.service));
  });
  canWork = computed(() => this.canEdit() || this.task()?.assignee_id === this.auth.user()?.id);
  mentionMenu = computed<MenuItem[]>(() => (this.project()?.team ?? []).filter((m: any) => m.user_id && m.user_id !== this.auth.user()?.id)
    .map((m: any) => ({ label: `${m.name} · ${m.project_role}`, command: () => (this.newComment = `${this.newComment}${this.newComment && !this.newComment.endsWith(' ') ? ' ' : ''}@${m.name} `) })));

  async open(taskId: string) {
    this.taskId.set(taskId);
    this.newItem = '';
    this.newComment = '';
    this.visible = true;
    await this.loadComments();
  }

  private base() {
    return `/projects/${this.project().id}`;
  }

  async loadComments() {
    this.comments.set(await this.api.get(`${this.base()}/tasks/${this.taskId()}/comments`));
  }

  partyLabel(v: string) {
    return this.parties().find((p) => p.value === v)?.label ?? v;
  }

  isImage(name: string) {
    return /\.(png|jpe?g|webp|heic)$/i.test(name);
  }

  /** @Name of a team member in bold (text is escaped first). */
  highlight(text: string) {
    let out = text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
    for (const m of this.project()?.team ?? []) {
      if (!m.user_id) continue;
      const safe = m.name.replace(/[&<>"]/g, (c: string) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
      out = out.split(`@${safe}`).join(`<span class="mention">@${safe}</span>`);
    }
    return out;
  }

  async tick(c: any, done: boolean) {
    this.changed.emit(await this.api.put(`${this.base()}/tasks/${this.taskId()}/checklist/${c.id}`, { done }));
  }

  async addItem() {
    if (!this.newItem.trim()) return;
    this.changed.emit(await this.api.post(`${this.base()}/tasks/${this.taskId()}/checklist`, { text: this.newItem.trim() }));
    this.newItem = '';
  }

  async removeItem(c: any) {
    this.changed.emit(await this.api.del(`${this.base()}/tasks/${this.taskId()}/checklist/${c.id}`));
  }

  async upload(ev: Event) {
    const inp = ev.target as HTMLInputElement;
    const file = inp.files?.[0];
    inp.value = '';
    if (!file) return;
    const up = await this.api.upload(file);
    this.changed.emit(await this.api.post(`${this.base()}/tasks/${this.taskId()}/files`, { key: up.key }, 'File added'));
  }

  async removeFile(f: any) {
    this.changed.emit(await this.api.del(`${this.base()}/tasks/${this.taskId()}/files/${f.id}`, 'File removed'));
  }

  async addComment() {
    await this.api.post(`${this.base()}/tasks/${this.taskId()}/comments`, { text: this.newComment.trim() });
    this.newComment = '';
    await this.loadComments();
    this.changed.emit(null);
  }

  async removeComment(c: any) {
    await this.api.del(`${this.base()}/comments/${c.id}`);
    await this.loadComments();
    this.changed.emit(null);
  }
}
