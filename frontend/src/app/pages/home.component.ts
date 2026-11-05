import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { TagModule } from 'primeng/tag';
import { Api, STATUS_SEVERITY, label } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { NAV } from '../core/nav';

@Component({
  selector: 'app-home',
  imports: [RouterLink, DatePipe, ButtonModule, CardModule, TagModule],
  template: `
    <div class="page-head">
      <div><h1>Good to see you, {{ firstName() }}</h1>
        <p class="muted">{{ auth.roleLabel(auth.user()?.role) }} at {{ auth.company()?.name }} · {{ auth.session()?.limits?.plan }} plan
          @if (auth.company()?.status === 'trial') { · trial ends {{ auth.company()?.trial_ends | date }} }</p></div>
    </div>

    @if (h(); as h) {
      <div class="stats">
        @if (h.projects) {
          <a class="stat-card link-card" routerLink="/app/projects"><span class="stat-icon indigo"><i class="pi pi-building"></i></span>
            <div><small>Active projects</small><strong>{{ h.projects.active }}</strong><small class="muted">{{ h.projects.planning }} planning · {{ h.projects.on_hold }} on hold</small></div></a>
          <div class="stat-card"><span class="stat-icon teal"><i class="pi pi-check-square"></i></span>
            <div><small>My open tasks</small><strong>{{ h.my_tasks.length }}</strong><small class="muted">{{ lateTasks() }} late</small></div></div>
          <div class="stat-card"><span class="stat-icon amber"><i class="pi pi-flag"></i></span>
            <div><small>Upcoming milestones</small><strong>{{ h.milestones.length }}</strong><small class="muted">{{ lateMs() }} overdue</small></div></div>
        }
        @if (h.followups) {
          <a class="stat-card link-card" routerLink="/app/followups"><span class="stat-icon amber"><i class="pi pi-bell"></i></span>
            <div><small>My follow-ups</small><strong>{{ h.followups.today }} today</strong><small [class.c-bad]="h.followups.overdue">{{ h.followups.overdue }} overdue</small></div></a>
        }
        @if (h.leads) {
          <a class="stat-card link-card" routerLink="/app/leads"><span class="stat-icon indigo"><i class="pi pi-bullseye"></i></span>
            <div><small>Open leads</small><strong>{{ h.leads.open }}</strong><small class="muted">{{ h.leads.mine }} mine · {{ h.leads.unassigned }} unassigned</small></div></a>
        }
        @if (h.compliance_alerts !== undefined) {
          <a class="stat-card link-card" routerLink="/app/contacts"><span class="stat-icon pink"><i class="pi pi-verified"></i></span>
            <div><small>Compliance alerts</small><strong>{{ h.compliance_alerts }}</strong><small class="muted">expired or due in 30 days</small></div></a>
        }
      </div>

      @if (h.projects_at_risk?.length) {
        <p-card styleClass="mb"><ng-template #title>Projects at risk <small class="muted">· health under 75</small></ng-template>
          @for (r of h.projects_at_risk; track r.id) {
            <a class="ms-row link-row" [routerLink]="['/app/projects', r.id]">
              <i class="health-dot" [class]="r.grade"></i>
              <div class="grow"><strong>{{ r.name }}</strong><br /><small class="muted">{{ r.why }}</small></div>
              <p-tag [value]="r.score + ' · ' + r.label" [severity]="r.grade === 'red' ? 'danger' : 'warn'" /></a>
          }
        </p-card>
      }
      @if (h.projects) {
        <div class="grid2 top">
          <p-card><ng-template #title>My tasks</ng-template>
            @for (t of h.my_tasks; track t.id) {
              <a class="ms-row link-row" [routerLink]="['/app/projects', t.project_id]">
                <i class="pi pi-circle" [class.c-bad]="t.late"></i>
                <div class="grow"><strong>{{ t.title }}</strong><br /><small class="muted">{{ t.project }} · {{ t.stage }}</small></div>
                <p-tag [value]="label(t.status)" [severity]="sev[t.status]" />
                <small [class.c-bad]="t.late">{{ t.end }}</small></a>
            } @empty { <p class="muted">Nothing assigned to you.</p> }
          </p-card>
          <p-card><ng-template #title>Upcoming milestones</ng-template>
            @for (m of h.milestones; track m.id) {
              <a class="ms-row link-row" [routerLink]="['/app/projects', m.project_id]">
                <i class="pi pi-flag" [class.c-bad]="m.late"></i>
                <div class="grow"><strong>{{ m.name }}</strong><br /><small class="muted">{{ m.project }}</small></div>
                <small [class.c-bad]="m.late">{{ m.due | date: 'mediumDate' }}</small></a>
            } @empty { <p class="muted">No pending milestones.</p> }
          </p-card>
        </div>
      }
    }

    <h3 class="mt">Your areas</h3>
    <div class="area-grid">
      @for (n of readable(); track n.area) {
        <a class="area-tile" [routerLink]="n.path ?? '/app/m/' + n.area">
          <i [class]="n.icon"></i><span>{{ n.label }}</span>
          <small [class.ok]="auth.can(n.area, 'rw')">{{ n.ready ? (auth.can(n.area, 'rw') ? 'Edit' : 'View only') : 'Coming soon' }}</small>
        </a>
      }
    </div>
  `,
})
export class HomeComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  h = signal<any>(null);
  sev = STATUS_SEVERITY;
  label = label;
  readable = computed(() => NAV.filter((n) => this.auth.can(n.area)));
  firstName = computed(() => (this.auth.user()?.name ?? '').split(' ')[0]);
  lateTasks = computed(() => (this.h()?.my_tasks ?? []).filter((t: any) => t.late).length);
  lateMs = computed(() => (this.h()?.milestones ?? []).filter((m: any) => m.late).length);

  async ngOnInit() {
    this.h.set(await this.api.get('/home'));
  }
}
