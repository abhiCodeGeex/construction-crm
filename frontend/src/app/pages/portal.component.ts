import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { AvatarModule } from 'primeng/avatar';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { ProgressBarModule } from 'primeng/progressbar';
import { TagModule } from 'primeng/tag';
import { Api, SERVICE_COLOR, SERVICE_LABEL, STATUS_SEVERITY, label } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { ThemeService } from '../core/theme.service';
import { ChangePasswordComponent } from '../shared/change-password.component';

/** Portal for clients, vendors, subcontractors and consultants: only projects where they are on the team (§13). */
@Component({
  selector: 'app-portal',
  imports: [DatePipe, AvatarModule, ButtonModule, CardModule, ProgressBarModule, TagModule, ChangePasswordComponent],
  template: `
    <header class="portal-top">
      <div class="logo"><span class="mark"><i class="pi pi-building"></i></span> {{ me()?.company?.name ?? 'Portal' }}</div>
      <span class="spacer"></span>
      <p-button [icon]="theme.dark() ? 'pi pi-sun' : 'pi pi-moon'" [rounded]="true" [text]="true" severity="secondary" (onClick)="theme.toggle()" />
      <p-button label="Change password" icon="pi pi-key" [text]="true" severity="secondary" (onClick)="pwd.open()" />
      <p-button label="Sign out" icon="pi pi-sign-out" [text]="true" severity="secondary" (onClick)="auth.logout()" />
    </header>
    <app-change-password #pwd />
    <main class="portal-body">
      <div class="portal-hero">
        <p-avatar icon="pi pi-user" size="xlarge" shape="circle" styleClass="avatar ext" />
        <div><h1>Hello, {{ auth.user()?.name }}</h1>
          <p class="muted">{{ me()?.contact?.name }} · <p-tag [value]="me()?.label ?? ''" severity="info" /></p></div>
      </div>

      @if (open(); as p) {
        <p-button label="All projects" icon="pi pi-arrow-left" [text]="true" (onClick)="open.set(null)" />
        <p-card>
          <ng-template #title>{{ p.name }} <small class="muted">{{ p.code }}</small></ng-template>
          <ng-template #subtitle>{{ p.site?.line1 }} {{ p.site?.city }} · <p-tag [value]="label(p.status)" [severity]="sev[p.status]" /></ng-template>
          <div class="prog mb"><p-progressbar [value]="p.progress" [showValue]="false" styleClass="grow" /><strong>{{ p.progress }}%</strong></div>
          <p class="muted small">Planned completion {{ p.planned_end | date: 'mediumDate' }}</p>
          @if (p.waiting_on_you?.length) {
            <div class="waiting-you">
              <b><i class="pi pi-hourglass"></i> Waiting on you</b>
              <p class="small muted">The work below cannot move until we hear from you.</p>
              @for (w of p.waiting_on_you; track $index) {
                <div class="ms-row"><span class="grow">{{ w.title }}{{ w.note ? ' — ' + w.note : '' }}</span><small class="muted">{{ w.days }} day(s)</small></div>
              }
            </div>
          }
          @for (s of p.stages; track s.name + s.service) {
            <div class="stage-row"><span class="svc-dot" [style.background]="color[s.service]"></span>
              <span class="grow">{{ s.name }} <small class="muted">{{ s.start | date: 'MMM d' }} – {{ s.end | date: 'MMM d' }}</small></span>
              <p-tag [value]="label(s.status)" [severity]="sev[s.status]" /><small class="w-3 right">{{ s.progress }}%</small></div>
            @for (m of s.milestones; track m.name) {
              <div class="ms-row sub"><i class="pi" [class.pi-flag-fill]="m.status === 'achieved'" [class.pi-flag]="m.status !== 'achieved'" [class.c-ok]="m.status === 'achieved'"></i>
                <span class="grow small">{{ m.name }}</span><small>{{ m.due | date: 'mediumDate' }}</small></div>
            }
          }
          <h4>Project team</h4>
          <div class="chips">@for (m of p.team; track m.name + m.project_role) { <span class="chip static">{{ m.name }} · {{ m.project_role }}</span> }</div>
        </p-card>
      } @else {
        <h3>Your projects</h3>
        <div class="tpl-grid">
          @for (p of projects(); track p.id) {
            <p-card styleClass="clickable" (click)="view(p.id)">
              <ng-template #title>{{ p.name }}</ng-template>
              <ng-template #subtitle>{{ p.city || '' }} · your role: {{ p.my_roles.join(', ') }}</ng-template>
              <div class="row gap mb">@for (s of p.services; track s) { <span class="svc" [style.--c]="color[s]">{{ svc[s] }}</span> }</div>
              <div class="prog"><p-progressbar [value]="p.progress" [showValue]="false" styleClass="thin grow" /><span>{{ p.progress }}%</span></div>
            </p-card>
          } @empty { <p class="muted">You have not been added to a project yet.</p> }
        </div>
        <p class="muted small mt">Approvals, invoices and messages arrive in a later release. You never see the firm's internal costs.</p>
      }
    </main>
  `,
})
export class PortalComponent implements OnInit {
  auth = inject(AuthService);
  theme = inject(ThemeService);
  private api = inject(Api);
  me = signal<any>(null);
  projects = signal<any[]>([]);
  open = signal<any>(null);
  sev = STATUS_SEVERITY;
  svc = SERVICE_LABEL;
  color = SERVICE_COLOR;
  label = label;

  async ngOnInit() {
    this.me.set(await this.api.get('/portal/me'));
    this.projects.set(await this.api.get('/portal/projects'));
  }

  async view(id: string) {
    this.open.set(await this.api.get(`/portal/projects/${id}`));
  }
}
