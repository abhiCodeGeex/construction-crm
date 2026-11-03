import { Component, computed, input, output } from '@angular/core';
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
  milestones?: { id: string; name: string; due: string; status: string }[];
}

const DAY = 86400000;
const ROW = 30;
const LABEL_W = 240;

/** Gantt timeline (§4): stage and task bars, milestone diamonds, finish-to-start dependency arrows, today line. */
@Component({
  selector: 'app-gantt',
  template: `
    @if (layout(); as L) {
      <div class="gantt-wrap">
        <svg [attr.width]="L.width" [attr.height]="L.height" class="gantt">
          <!-- month grid -->
          @for (m of L.months; track m.x) {
            <line [attr.x1]="m.x" [attr.x2]="m.x" y1="0" [attr.y2]="L.height" class="grid" />
            <text [attr.x]="m.x + 4" y="14" class="month">{{ m.label }}</text>
          }
          @if (L.todayX !== null) {
            <line [attr.x1]="L.todayX" [attr.x2]="L.todayX" y1="20" [attr.y2]="L.height" class="today" />
            <text [attr.x]="L.todayX + 3" y="30" class="today-label">Today</text>
          }
          <!-- rows -->
          @for (r of L.rows; track r.id; let i = $index) {
            <g [attr.transform]="'translate(0,' + (40 + i * rowH) + ')'" (click)="select.emit(r)" class="row" [class.stage]="r.kind === 'stage'">
              <rect x="0" y="0" [attr.width]="L.width" [attr.height]="rowH" [class.zebra]="i % 2 === 0" class="row-bg" />
              <text [attr.x]="r.kind === 'stage' ? 8 : 22" [attr.y]="rowH / 2 + 4" class="label">{{ trim(r.label) }}</text>
              @if (r.x !== null) {
                <rect [attr.x]="r.x" [attr.y]="r.kind === 'stage' ? 7 : 9" [attr.width]="r.w" [attr.height]="r.kind === 'stage' ? 16 : 12" rx="4"
                      [attr.fill]="color(r.service)" [attr.opacity]="r.kind === 'stage' ? 0.28 : 0.35" />
                <rect [attr.x]="r.x" [attr.y]="r.kind === 'stage' ? 7 : 9" [attr.width]="r.w * r.progress / 100" [attr.height]="r.kind === 'stage' ? 16 : 12" rx="4"
                      [attr.fill]="color(r.service)" />
                @if (r.conflict) { <rect [attr.x]="r.x" y="8" [attr.width]="r.w" height="14" rx="4" class="conflict" /> }
              }
              @for (m of r.ms; track m.id) {
                <g [attr.transform]="'translate(' + m.x + ',' + rowH / 2 + ')'">
                  <rect x="-6" y="-6" width="12" height="12" transform="rotate(45)" [class.achieved]="m.status === 'achieved'" class="diamond" />
                  <title>{{ m.name }} · {{ m.due }}</title>
                </g>
              }
              <title>{{ r.label }} · {{ r.start }} → {{ r.end }} · {{ r.progress }}%</title>
            </g>
          }
          <!-- dependency arrows -->
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
        @for (s of services(); track s) { <span><i class="dot" [style.background]="color(s)"></i>{{ s }}</span> }
        <span><i class="diamond-key"></i>Milestone</span>
        <span><i class="line-key"></i>Dependency</span>
        <span><i class="conflict-key"></i>Starts before its predecessor ends</span>
      </div>
    } @else {
      <p class="muted">Add dates to stages and tasks to see the timeline.</p>
    }
  `,
  styles: `
    .gantt-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
    .gantt { display: block; font-family: inherit; }
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
    .conflict { fill: none; stroke: #ef4444; stroke-width: 2; stroke-dasharray: 3 2; }
    .legend { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: .6rem; }
    .legend span { display: inline-flex; align-items: center; gap: .35rem; text-transform: capitalize; }
    .dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
    .diamond-key { width: 9px; height: 9px; background: #f59e0b; transform: rotate(45deg); display: inline-block; }
    .line-key { width: 16px; height: 2px; background: var(--muted); display: inline-block; }
    .conflict-key { width: 16px; height: 10px; border: 2px dashed #ef4444; border-radius: 3px; display: inline-block; }
  `,
})
export class GanttComponent {
  stages = input<any[]>([]);
  select = output<Row>();
  rowH = ROW;
  services = computed(() => [...new Set(this.stages().map((s) => s.service))]);

  color(s: string) {
    return SERVICE_COLOR[s] ?? '#64748b';
  }

  trim(s: string) {
    return s.length > 30 ? s.slice(0, 29) + '…' : s;
  }

  layout = computed(() => {
    const rows: Row[] = [];
    for (const s of this.stages()) {
      rows.push({ kind: 'stage', id: s.id, label: s.name, start: s.start, end: s.end, progress: s.progress ?? 0, service: s.service,
        status: s.status, milestones: s.milestones });
      for (const t of s.tasks ?? []) {
        rows.push({ kind: 'task', id: t.id, label: t.title, start: t.start, end: t.end, progress: t.progress ?? 0, service: s.service,
          status: t.status, conflict: t.conflict, depends_on: t.depends_on });
      }
    }
    const dates = rows.flatMap((r) => [r.start, r.end, ...(r.milestones ?? []).map((m) => m.due)]).filter(Boolean) as string[];
    if (!dates.length) return null;
    const t0 = Date.parse(dates.reduce((a, b) => (a < b ? a : b))) - 3 * DAY;
    const t1 = Date.parse(dates.reduce((a, b) => (a > b ? a : b))) + 7 * DAY;
    const days = Math.round((t1 - t0) / DAY);
    const pxDay = Math.max(4, Math.min(28, 900 / days));
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
        const mid = Math.max(fx + 8, Math.min(tx - 8, fx + 8));
        arrows.push({ key: dep + r.id, d: `M${fx},${fy} H${mid} V${ty} H${tx - 2}`, bad: !!r.conflict });
      }
    });
    return { rows: placed, months, todayX, width, height: 40 + rows.length * ROW + 6, arrows };
  });
}
