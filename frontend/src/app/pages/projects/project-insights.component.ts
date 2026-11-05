import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { CardModule } from 'primeng/card';
import { ProgressBarModule } from 'primeng/progressbar';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api } from '../../core/api.service';

export const GRADE_SEVERITY: Record<string, 'success' | 'warn' | 'danger'> = { green: 'success', amber: 'warn', red: 'danger' };
const KIND_ICON: Record<string, string> = {
  task: 'pi pi-check-square', stage: 'pi pi-th-large', milestone: 'pi pi-flag', checklist: 'pi pi-list-check', signoff: 'pi pi-verified',
  schedule: 'pi pi-calendar', baseline: 'pi pi-bookmark', delay: 'pi pi-clock', team: 'pi pi-users', issue: 'pi pi-exclamation-circle',
  comment: 'pi pi-comment', file: 'pi pi-paperclip', meeting: 'pi pi-calendar-plus', edit: 'pi pi-pencil',
};

/** The project timeline (B+3): every change, newest first, with filters. */
@Component({
  selector: 'app-project-activity',
  imports: [FormsModule, DatePipe, SelectButtonModule],
  template: `
    <div class="filters mb"><p-selectbutton [options]="groups()" [ngModel]="group()" (onChange)="setGroup($event.value)" [allowEmpty]="false" /></div>
    @for (a of rows(); track a.id) {
      <div class="timeline-row"><i [class]="icon(a.kind)"></i>
        <div class="grow"><div>{{ a.text }}</div><small class="muted">{{ a.by || 'System' }} · {{ a.at | date: 'd MMM y, h:mm a' }}</small></div></div>
    } @empty { <p class="muted">Nothing here yet.</p> }
  `,
})
export class ProjectActivityComponent implements OnInit {
  projectId = input.required<string>();
  private api = inject(Api);
  rows = signal<any[]>([]);
  groups = signal<string[]>(['All']);
  group = signal('All');

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const g = this.group();
    const r = await this.api.get(`/projects/${this.projectId()}/activity${g === 'All' ? '' : '?group=' + encodeURIComponent(g)}`);
    this.rows.set(r.rows);
    this.groups.set(['All', ...r.groups]);
  }

  async setGroup(g: string) {
    this.group.set(g ?? 'All');
    await this.load();
  }

  icon(kind: string) {
    return KIND_ICON[kind] ?? 'pi pi-circle';
  }
}

/** Health, forecast, waiting on whom and delays (B+3 / B+4) for the project overview. */
@Component({
  selector: 'app-project-health',
  imports: [DatePipe, CardModule, ProgressBarModule, TableModule, TagModule],
  template: `
    @if (h(); as h) {
      <div class="grid2 top">
        <p-card>
          <ng-template #title>Project health <p-tag [value]="h.score + '/100 · ' + h.label" [severity]="sev[h.grade]" /></ng-template>
          @for (x of h.parts; track x.key) {
            <div class="hp-row"><span class="w-10">{{ x.label }}</span>
              <p-progressbar [value]="x.points / x.max * 100" [showValue]="false" styleClass="thin grow" [class.bad]="x.points < x.max / 2" />
              <b class="w-4 right">{{ x.points }}/{{ x.max }}</b></div>
            <div class="small muted mb-xs">{{ x.why }}</div>
          }
          <small class="muted">Green 75+ on track · amber 50–74 at risk · red under 50 off track. The managers are told when it turns red.</small>
        </p-card>
        <div class="stack">
          <p-card>
            <ng-template #title>Finish forecast</ng-template>
            <p [class.c-bad]="h.forecast.late_days > 0">{{ h.forecast.message }}</p>
            <div class="small">Planned finish <b>{{ h.forecast.planned_end | date: 'd MMM y' }}</b> · forecast <b>{{ h.forecast.project_forecast | date: 'd MMM y' }}</b>
              @if (h.forecast.late_days) { <p-tag [value]="h.forecast.late_days + ' working days late'" severity="danger" /> }</div>
            <small class="muted">Based on the pace each stage has kept since it started (progress per working day).</small>
          </p-card>
          <p-card>
            <ng-template #title>Waiting on whom</ng-template>
            @for (r of waiting(); track $index) {
              <div class="ms-row"><p-tag [value]="r.party_label" [severity]="r.party === 'us' ? 'secondary' : 'warn'" />
                <span class="grow">{{ r.title }}{{ r.note ? ' — ' + r.note : '' }}</span><small class="muted">{{ r.days }} day(s)</small></div>
            } @empty { <p class="muted small">Nothing is held up.</p> }
          </p-card>
          @if (delays()?.rows?.length) {
            <p-card>
              <ng-template #title>Delays since the baseline</ng-template>
              @for (x of delays().by_party; track x.party) { <div class="ms-row"><span class="grow">{{ x.label }}</span><b>{{ x.days }} working day(s)</b></div> }
              <p-table [value]="delays().rows" size="small" styleClass="mt-xs">
                <ng-template #body let-d><tr><td class="small">{{ d.title }}<br /><span class="muted">{{ d.from }} → {{ d.to }} · {{ d.reason_label }}{{ d.note ? ': ' + d.note : '' }}</span></td>
                  <td class="right small nowrap">+{{ d.days }} d</td></tr></ng-template>
              </p-table>
            </p-card>
          }
        </div>
      </div>
    }
  `,
  styles: `
    .hp-row { display: flex; align-items: center; gap: .6rem; margin-top: .5rem; }
    :host ::ng-deep .bad .p-progressbar-value { background: #ef4444; }
  `,
})
export class ProjectHealthComponent implements OnInit {
  projectId = input.required<string>();
  private api = inject(Api);
  h = signal<any>(null);
  waiting = signal<any[]>([]);
  delays = signal<any>(null);
  sev = GRADE_SEVERITY;

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const [h, w, d] = await Promise.all([this.api.get(`/projects/${this.projectId()}/health`), this.api.get(`/projects/${this.projectId()}/waiting`),
      this.api.get(`/projects/${this.projectId()}/delays`)]);
    this.h.set(h);
    this.waiting.set(w.rows);
    this.delays.set(d);
  }
}
