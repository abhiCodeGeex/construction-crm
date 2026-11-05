import { Component, computed, input, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { SERVICE_COLOR } from '../core/api.service';

interface Row {
  kind: 'stage' | 'task';
  id: string;
  label: string;
  start: string | null;
  end: string | null;
  progress: number;
  service: string;
  status: string;
  conflict?: boolean;
  depends_on?: string[];
  baseline?: { start: string; end: string; slip_days: number } | null;
  editable?: boolean;
  milestones?: { id: string; name: string; due: string; status: string }[];
}

const DAY = 86400000;
const ROW = 30;
const LABEL_W = 240;

function addDays(day: string, n: number) {
  const d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Gantt timeline (§4, B+3): stage and task bars, milestone diamonds, dependency arrows, today line, the baseline
 *  (grey line under each bar) and drag to edit: drag a task bar to move it, drag its right edge to change its end. */
@Component({
  selector: 'app-gantt',
  imports: [DatePipe],
  template: `
    @if (layout(); as L) {
      <div class="gantt-wrap">
        <svg [attr.width]="L.width" [attr.height]="L.height" class="gantt" [class.dragging]="drag()"
             (pointermove)="onMove($event)" (pointerup)="onUp()" (pointerleave)="onUp()">
          @for (m of L.months; track m.x) {
            <line [attr.x1]="m.x" [attr.x2]="m.x" y1="0" [attr.y2]="L.height" class="grid" />
            <text [attr.x]="m.x + 4" y="14" class="month">{{ m.label }}</text>
          }
          @if (L.todayX !== null) {
            <line [attr.x1]="L.todayX" [attr.x2]="L.todayX" y1="20" [attr.y2]="L.height" class="today" />
            <text [attr.x]="L.todayX + 3" y="30" class="today-label">Today</text>
          }
          @for (r of L.rows; track r.id; let i = $index) {
            <g [attr.transform]="'translate(0,' + (40 + i * rowH) + ')'" (click)="clicked(r)" class="row" [class.stage]="r.kind === 'stage'">
              <rect x="0" y="0" [attr.width]="L.width" [attr.height]="rowH" [class.zebra]="i % 2 === 0" class="row-bg" />
              <text [attr.x]="r.kind === 'stage' ? 8 : 22" [attr.y]="rowH / 2 + 4" class="label">{{ trim(r.label) }}</text>
              @if (r.bx !== null) {
                <rect [attr.x]="r.bx" [attr.y]="rowH - 5" [attr.width]="r.bw" height="3" rx="1.5" class="baseline"><title>Baseline {{ r.baseline?.start | date: 'd MMM' }} → {{ r.baseline?.end | date: 'd MMM y' }}</title></rect>
              }
              @if (r.x !== null) {
                <g [class.draggable]="r.editable">
                  <rect [attr.x]="bx(r)" [attr.y]="r.kind === 'stage' ? 7 : 9" [attr.width]="bw(r)" [attr.height]="r.kind === 'stage' ? 16 : 12" rx="4"
                        [attr.fill]="color(r.service)" [attr.opacity]="r.kind === 'stage' ? 0.28 : 0.35" (pointerdown)="onDown($event, r, 'move')" />
                  <rect [attr.x]="bx(r)" [attr.y]="r.kind === 'stage' ? 7 : 9" [attr.width]="bw(r) * r.progress / 100" [attr.height]="r.kind === 'stage' ? 16 : 12" rx="4"
                        [attr.fill]="color(r.service)" (pointerdown)="onDown($event, r, 'move')" />
                  @if (r.conflict) { <rect [attr.x]="bx(r)" y="8" [attr.width]="bw(r)" height="14" rx="4" class="conflict" /> }
                  @if (r.editable) {
                    <rect [attr.x]="bx(r) + bw(r) - 6" y="7" width="8" height="16" class="handle" (pointerdown)="onDown($event, r, 'end')"><title>Drag to change the end date</title></rect>
                  }
                </g>
                @if (drag()?.id === r.id && drag()!.delta) { <text [attr.x]="bx(r) + bw(r) + 6" [attr.y]="rowH / 2 + 4" class="drag-label">{{ preview(r) }}</text> }
              }
              @for (m of r.ms; track m.id) {
                <g [attr.transform]="'translate(' + m.x + ',' + rowH / 2 + ')'">
                  <rect x="-6" y="-6" width="12" height="12" transform="rotate(45)" [class.achieved]="m.status === 'achieved'" class="diamond" />
                  <title>{{ m.name }} · {{ m.due | date: 'd MMM y' }}</title>
                </g>
              }
              <title>{{ r.label }} · {{ r.start | date: 'd MMM' }} → {{ r.end | date: 'd MMM y' }} · {{ r.progress }}%{{ r.baseline?.slip_days ? ' · ' + (r.baseline!.slip_days > 0 ? '+' : '') + r.baseline!.slip_days + ' working days vs baseline' : '' }}</title>
            </g>
          }
          @for (a of L.arrows; track a.key) {
            <path [attr.d]="a.d" class="arrow" [class.bad]="a.bad" marker-end="url(#arrowhead)" />
          }
          <defs>
            <marker id="arrowhead" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" class="arrow-head" />
            </marker>
          </defs>
        </svg>
      </div>
      <div class="legend small muted">
        @for (s of services(); track s) { <span class="cap"><i class="dot" [style.background]="color(s)"></i>{{ s }}</span> }
        <span><i class="diamond-key"></i>Milestone</span>
        <span><i class="line-key"></i>Dependency</span>
        <span><i class="conflict-key"></i>Breaks a dependency</span>
        <span><i class="baseline-key"></i>Baseline (agreed plan)</span>
        @if (editable()) { <span><i class="pi pi-arrows-h"></i> Drag a task to move it · drag its right edge to change the end date</span> }
      </div>
    } @else {
      <p class="muted">Add dates to stages and tasks to see the timeline.</p>
    }
  `,
  styles: `
    .gantt-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
    .gantt { display: block; font-family: inherit; touch-action: pan-y; }
    .grid { stroke: var(--border); }
    .month { fill: var(--muted); font-size: 11px; }
    .today { stroke: #ef4444; stroke-dasharray: 4 3; }
    .today-label { fill: #ef4444; font-size: 10px; }
    .row { cursor: pointer; }
    .row-bg { fill: transparent; }
    .row-bg.zebra { fill: color-mix(in srgb, var(--text) 3%, transparent); }
    .row:hover .row-bg { fill: color-mix(in srgb, var(--brand) 8%, transparent); }
    .label { fill: var(--text); font-size: 12px; }
    .row.stage .label { font-weight: 600; }
    .diamond { fill: #f59e0b; stroke: var(--surface); stroke-width: 1.5; }
    .diamond.achieved { fill: #16a34a; }
    .arrow { fill: none; stroke: var(--muted); stroke-width: 1.3; }
    .arrow.bad { stroke: #ef4444; }
    .arrow-head { fill: var(--muted); }
    .conflict { fill: none; stroke: #ef4444; stroke-width: 2; stroke-dasharray: 3 2; pointer-events: none; }
    .baseline { fill: var(--muted); opacity: .55; }
    .draggable rect { cursor: grab; }
    .gantt.dragging, .gantt.dragging .draggable rect { cursor: grabbing; user-select: none; }
    .handle { fill: transparent; cursor: ew-resize !important; }
    .draggable:hover .handle { fill: color-mix(in srgb, var(--text) 25%, transparent); }
    .drag-label { fill: var(--brand); font-size: 11px; font-weight: 600; }
    .legend { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: .6rem; }
    .legend span { display: inline-flex; align-items: center; gap: .35rem; }
    .legend span.cap { text-transform: capitalize; }
    .dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
    .diamond-key { width: 9px; height: 9px; background: #f59e0b; transform: rotate(45deg); display: inline-block; }
    .line-key { width: 16px; height: 2px; background: var(--muted); display: inline-block; }
    .conflict-key { width: 16px; height: 10px; border: 2px dashed #ef4444; border-radius: 3px; display: inline-block; }
    .baseline-key { width: 16px; height: 3px; background: var(--muted); opacity: .55; display: inline-block; }
  `,
})
export class GanttComponent {
  stages = input<any[]>([]);
  /** stage ids whose tasks the current user may move by dragging */
  editableStages = input<string[]>([]);
  editable = computed(() => this.editableStages().length > 0);
  select = output<Row>();
  /** a task bar was dragged: its new dates (the parent saves them and asks for a delay reason when needed) */
  moved = output<{ id: string; start: string; end: string; mode: 'move' | 'end' }>();
  drag = signal<{ id: string; mode: 'move' | 'end'; x0: number; delta: number } | null>(null);
  rowH = ROW;
  private pxDay = 10;
  private dragged = false;
  services = computed(() => [...new Set(this.stages().map((s) => s.service))]);

  color(s: string) {
    return SERVICE_COLOR[s] ?? '#64748b';
  }

  trim(s: string) {
    return s.length > 30 ? s.slice(0, 29) + '…' : s;
  }

  layout = computed(() => {
    const rows: Row[] = [];
    const editable = this.editableStages();
    for (const s of this.stages()) {
      rows.push({ kind: 'stage', id: s.id, label: s.name, start: s.start, end: s.end, progress: s.progress ?? 0, service: s.service,
        status: s.status, milestones: s.milestones, baseline: s.baseline ?? null });
      for (const t of s.tasks ?? []) {
        rows.push({ kind: 'task', id: t.id, label: t.title, start: t.start, end: t.end, progress: t.progress ?? 0, service: s.service,
          status: t.status, conflict: t.conflict, depends_on: t.depends_on, baseline: t.baseline ?? null,
          editable: editable.includes(s.id) && t.status !== 'done' });
      }
    }
    const dates = rows.flatMap((r) => [r.start, r.end, r.baseline?.start, r.baseline?.end, ...(r.milestones ?? []).map((m) => m.due)])
      .filter(Boolean) as string[];
    if (!dates.length) return null;
    const t0 = Date.parse(dates.reduce((a, b) => (a < b ? a : b))) - 3 * DAY;
    const t1 = Date.parse(dates.reduce((a, b) => (a > b ? a : b))) + 7 * DAY;
    const days = Math.round((t1 - t0) / DAY);
    const pxDay = Math.max(4, Math.min(28, 900 / days));
    this.pxDay = pxDay;
    const x = (d: string) => LABEL_W + ((Date.parse(d) - t0) / DAY) * pxDay;
    const width = LABEL_W + days * pxDay + 20;
    const months: { x: number; label: string }[] = [];
    const m = new Date(t0);
    m.setUTCDate(1);
    while (m.getTime() <= t1) {
      const mx = LABEL_W + ((m.getTime() - t0) / DAY) * pxDay;
      if (mx >= LABEL_W) months.push({ x: mx, label: m.toLocaleString('en', { month: 'short', year: '2-digit', timeZone: 'UTC' }) });
      m.setUTCMonth(m.getUTCMonth() + 1);
    }
    const today = new Date().toISOString().slice(0, 10);
    const todayX = Date.parse(today) >= t0 && Date.parse(today) <= t1 ? x(today) : null;
    const placed = rows.map((r) => ({
      ...r,
      x: r.start && r.end ? x(r.start) : null,
      w: r.start && r.end ? Math.max(pxDay, x(r.end) - x(r.start) + pxDay) : 0,
      bx: r.baseline?.start && r.baseline?.end ? x(r.baseline.start) : null,
      bw: r.baseline?.start && r.baseline?.end ? Math.max(pxDay, x(r.baseline.end) - x(r.baseline.start) + pxDay) : 0,
      ms: (r.milestones ?? []).filter((mm) => mm.due).map((mm) => ({ ...mm, x: x(mm.due) + pxDay / 2 })),
    }));
    const index = new Map(placed.map((r, i) => [r.id, i]));
    const arrows: { key: string; d: string; bad: boolean }[] = [];
    placed.forEach((r, i) => {
      for (const dep of r.depends_on ?? []) {
        const j = index.get(dep);
        if (j === undefined || placed[j].x === null || r.x === null) continue;
        const from = placed[j];
        const fx = from.x! + from.w;
        const fy = 40 + j * ROW + ROW / 2;
        const tx = r.x!;
        const ty = 40 + i * ROW + ROW / 2;
        const mid = fx + 8;
        arrows.push({ key: dep + r.id, d: `M${fx},${fy} H${mid} V${ty} H${tx - 2}`, bad: !!r.conflict });
      }
    });
    return { rows: placed, months, todayX, width, height: 40 + rows.length * ROW + 6, arrows };
  });

  // ---------- drag to edit ----------
  bx(r: any) {
    const d = this.drag();
    return r.x + (d && d.id === r.id && d.mode === 'move' ? d.delta * this.pxDay : 0);
  }

  bw(r: any) {
    const d = this.drag();
    return Math.max(this.pxDay, r.w + (d && d.id === r.id && d.mode === 'end' ? d.delta * this.pxDay : 0));
  }

  onDown(ev: PointerEvent, r: any, mode: 'move' | 'end') {
    if (!r.editable || r.kind !== 'task') return;
    ev.stopPropagation();
    ev.preventDefault();
    this.dragged = false;
    this.drag.set({ id: r.id, mode, x0: ev.clientX, delta: 0 });
  }

  onMove(ev: PointerEvent) {
    const d = this.drag();
    if (!d) return;
    const delta = Math.round((ev.clientX - d.x0) / this.pxDay);
    if (delta !== d.delta) {
      this.dragged = true;
      this.drag.set({ ...d, delta });
    }
  }

  onUp() {
    const d = this.drag();
    if (!d) return;
    this.drag.set(null);
    if (!d.delta) return;
    const r = this.layout()!.rows.find((x) => x.id === d.id)!;
    const start = d.mode === 'move' ? addDays(r.start!, d.delta) : r.start!;
    let end = addDays(r.end!, d.delta);
    if (end < start) end = start;
    this.moved.emit({ id: d.id, start, end, mode: d.mode });
  }

  clicked(r: any) {
    if (this.dragged) {
      this.dragged = false; // the end of a drag is not a click
      return;
    }
    this.select.emit(r);
  }

  preview(r: any) {
    const d = this.drag()!;
    const start = d.mode === 'move' ? addDays(r.start, d.delta) : r.start;
    let end = addDays(r.end, d.delta);
    if (end < start) end = start;
    return `${start} → ${end}`;
  }
}
