import { I18n, TPipe } from '../core/i18n';
import { FormsModule } from '@angular/forms';
import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { AvatarModule } from 'primeng/avatar';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { ProgressBarModule } from 'primeng/progressbar';
import { TagModule } from 'primeng/tag';
import { Api, SERVICE_COLOR, SERVICE_LABEL, STATUS_SEVERITY, label, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { ThemeService } from '../core/theme.service';
import { ChangePasswordComponent } from '../shared/change-password.component';
import { PortalActionsComponent } from './portal-actions.component';
import { PortalInvoicesComponent } from './portal-invoices.component';
import { PortalSupplierComponent } from './portal-supplier.component';
import { PortalMessagesComponent } from './portal-messages.component';

/** Portal for clients, vendors, subcontractors and consultants: only projects where they are on the team (§13). */
@Component({
  selector: 'app-portal',
  imports: [TPipe, DatePipe, FormsModule, AvatarModule, ButtonModule, CardModule, ProgressBarModule, TagModule, ChangePasswordComponent, PortalActionsComponent, PortalInvoicesComponent, PortalSupplierComponent, PortalMessagesComponent],
  template: `
    <header class="portal-top">
      <div class="logo"><span class="mark"><i class="pi pi-building"></i></span> {{ me()?.company?.name ?? 'Portal' }}</div>
      <span class="spacer"></span>
      <p-button [icon]="theme.dark() ? 'pi pi-sun' : 'pi pi-moon'" [rounded]="true" [text]="true" severity="secondary" (onClick)="theme.toggle()" />
      <p-button label="Change password" icon="pi pi-key" [text]="true" severity="secondary" (onClick)="pwd.open()" />
      <p-button label="Sign out" icon="pi pi-sign-out" [text]="true" severity="secondary" (onClick)="auth.logout()" />
    </header>
    <app-change-password #pwd />
        <button type="button" class="p-button p-button-text p-button-sm" (click)="i18n.set(i18n.lang() === 'hi' ? 'en' : 'hi')">{{ i18n.lang() === 'hi' ? 'English' : 'हिन्दी' }}</button>
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
              <p class="small muted m0">Act on them below.</p>
            </div>
          }
          <h4>For you to act on</h4>
          <app-portal-actions [projectId]="p.id" [currency]="me()?.company?.currency ?? 'INR'" (changed)="view(p.id)" />
          @for (s of p.stages; track s.name + s.service) {
            <div class="stage-row"><span class="svc-dot" [style.background]="color[s.service]"></span>
              <span class="grow">{{ s.name }} <small class="muted">{{ s.start | date: 'MMM d' }} – {{ s.end | date: 'MMM d' }}</small></span>
              <p-tag [value]="label(s.status)" [severity]="sev[s.status]" /><small class="w-3 right">{{ s.progress }}%</small></div>
            @for (m of s.milestones; track m.name) {
              <div class="ms-row sub"><i class="pi" [class.pi-flag-fill]="m.status === 'achieved'" [class.pi-flag]="m.status !== 'achieved'" [class.c-ok]="m.status === 'achieved'"></i>
                <span class="grow small">{{ m.name }}</span><small>{{ m.due | date: 'mediumDate' }}</small></div>
            }
          }
          @if (p.my_role === 'Client') { <app-portal-invoices [projectId]="p.id" [currency]="me()?.company?.currency ?? 'INR'" /> }
          @if (docs().length) {
            <h4>Documents and drawings</h4>
            @for (d of docs(); track d.url) { <div class="ms-row"><i class="pi pi-file"></i><a class="grow small" [href]="d.url" target="_blank" rel="noopener">@if (d.number) { {{ d.number }} } {{ d.name }}</a><small class="muted">{{ d.rev }} · {{ d.date | date: 'mediumDate' }}</small></div> }
          }
          @if (sels().length) {
            <h4>Your selections</h4>
            @for (s of sels(); track s.item + s.room) {
              <div class="ms-row"><span class="grow small"><strong>{{ s.item }}</strong>@if (s.room) { · {{ s.room }} }
                @if (s.chosen) { — you chose {{ s.chosen }} } @else if (s.due_date) { — please choose by {{ s.due_date | date: 'mediumDate' }} }</span>
                <small class="muted">{{ label(s.status) }}</small></div>
              @if (!s.chosen) { <div class="opts small muted">@for (o of s.options; track o.name) { <span>{{ o.name }}@if (o.brand) { ({{ o.brand }}) } · {{ money(o.price) }}</span> }</div> }
            }
          }
          @if (boards().length) {
            <h4>{{ 'Mood boards' | t }}</h4>
            @for (b of boards(); track b.id) {
              <div class="small"><strong>{{ b.title }}</strong>@if (b.room) { · {{ b.room }} }</div>
              <div class="mb-grid">@for (it of b.items; track it.id) {
                <figure><img [src]="it.url" [alt]="it.note || 'Mood board image'" />
                  <figcaption class="small">{{ it.note }}
                    <button type="button" class="like" [class.on]="it.liked" (click)="react(b, it, { like: !it.liked })" [attr.aria-label]="it.liked ? 'Unlike' : 'Like'"><i class="pi" [class.pi-heart-fill]="it.liked" [class.pi-heart]="!it.liked"></i></button>
                    @for (c of it.comments; track $index) { <div><strong>{{ c.name }}:</strong> {{ c.comment }}</div> }
                    <input class="p-inputtext p-inputtext-sm" placeholder="Comment…" (keyup.enter)="comment(b, it, $event)" /></figcaption></figure>
              }</div>
            }
          }
          @if (photos().length) {
            <h4>{{ 'Site photos' | t }}</h4>
            @for (grp of photoDays(); track grp.date) {
              <div class="small muted">{{ grp.date | date: 'EEE d MMM y' }}</div>
              <div class="photos">@for (ph of grp.photos; track ph.url) { <a [href]="ph.url" target="_blank" rel="noopener" [title]="ph.caption || ph.date">
                <img [src]="ph.url" [alt]="ph.caption || 'Site photo'" />@if (ph.stage || ph.room) { <span class="tag">{{ ph.stage }}@if (ph.room) { · {{ ph.room }} }</span> }</a> }</div>
            }
          }
          @if (isClient()) {
            <div class="row-between mt"><h4 class="m0">{{ 'Your change requests' | t }}</h4>
              <button type="button" class="p-button p-button-sm p-button-text" (click)="crOpen = !crOpen">{{ (crOpen ? 'Close' : 'Ask for a change') | t }}</button></div>
            @if (crOpen) {
              <div class="stack mb">
                <input class="p-inputtext" [(ngModel)]="cr.title" placeholder="What would you like changed?" />
                <textarea class="p-inputtext" rows="2" [(ngModel)]="cr.description" placeholder="Details (optional)"></textarea>
                <div><button type="button" class="p-button p-button-sm" [disabled]="!cr.title.trim()" (click)="askChange(p.id)">{{ 'Send to the team' | t }}</button></div>
              </div>
            }
            @for (r of requests(); track r.id) { <div class="small">{{ r.number }} · {{ r.title }} — <strong>{{ r.state }}</strong>@if (r.total) { · {{ money(r.total) }} }</div> }
            @empty { @if (!crOpen) { <div class="small muted">None yet.</div> } }
          }
          <app-portal-messages [projectId]="p.id" />
          <h4>{{ 'Project team' | t }}</h4>
          <div class="chips">@for (m of p.team; track m.name + m.project_role) { <span class="chip static">{{ m.name }} · {{ m.project_role }}</span> }</div>
        </p-card>
      } @else {
        <h3>{{ 'Your projects' | t }}</h3>
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
        @if (proposals().length) {
          <h3>{{ 'Proposals for you' | t }}</h3>
          @for (x of proposals(); track x.number + x.version) {
            <div class="row-between small mb-xs"><span>{{ x.number }} · {{ x.title }} — {{ money(x.value) }} <span class="muted">({{ label(x.status) }}@if (x.valid_until) { , valid until {{ x.valid_until | date: 'mediumDate' }} })</span></span>
              @if (x.link) { <a [href]="x.link" target="_blank" rel="noopener">{{ (x.status === 'accepted' ? 'View' : 'Open and answer') | t }}</a> }</div>
          }
        }
        <app-portal-supplier [currency]="me()?.company?.currency ?? 'INR'" />
        <p class="muted small mt">{{ "You never see the firm's internal costs." | t }}</p>
      }
    </main>
  `,
  styles: `
    .photos { display: flex; flex-wrap: wrap; gap: .4rem; }
    .photos img { width: 7rem; height: 5rem; object-fit: cover; border-radius: 6px; }
    .photos a { position: relative; display: inline-block; }
    .photos .tag { position: absolute; left: .2rem; bottom: .2rem; font-size: .65rem; background: rgba(0,0,0,.6); color: #fff; padding: 0 .3rem; border-radius: 4px; }
    .mb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: .6rem; margin: .3rem 0 .8rem; }
    .mb-grid figure { margin: 0; } .mb-grid img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 6px; }
    .like { background: none; border: 0; cursor: pointer; color: var(--muted); } .like.on { color: #e11d48; }
    .opts { display: flex; flex-wrap: wrap; gap: .3rem .9rem; padding: 0 0 .4rem 1.2rem; }
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
  docs = signal<any[]>([]);
  sels = signal<any[]>([]);
  photos = signal<any[]>([]);
  boards = signal<any[]>([]);  // Phase I: mood boards shared with the client
  i18n = inject(I18n);
  requests = signal<any[]>([]);
  proposals = signal<any[]>([]);
  crOpen = false;
  cr = { title: '', description: '' };

  isClient() {
    const role = this.me()?.user?.role ?? this.me()?.role;
    return (this.open()?.my_roles ?? []).includes('Client') || role === 'client';
  }

  async askChange(pid: string) {
    await this.api.post(`/portal/projects/${pid}/change-requests`, this.cr, 'Sent to the team');
    this.cr = { title: '', description: '' };
    this.crOpen = false;
    this.requests.set(await this.api.get(`/portal/projects/${pid}/change-requests`));
  }

  photoDays() {
    const days: Record<string, any[]> = {};
    for (const ph of this.photos()) (days[ph.date] ??= []).push(ph);
    return Object.entries(days).map(([date, photos]) => ({ date, photos }));
  }

  async react(b: any, it: any, body: any) {
    const upd = await this.api.post(`/portal/boards/${b.id}/react`, { item_id: it.id, ...body });
    this.boards.set(this.boards().map((x) => (x.id === b.id ? upd : x)));
  }

  async comment(b: any, it: any, ev: Event) {
    const el = ev.target as HTMLInputElement;
    if (!el.value.trim()) return;
    await this.react(b, it, { comment: el.value.trim() });
    el.value = '';
  }

  money(v: number) {
    return money(v, this.me()?.company?.currency ?? 'INR');
  }

  async ngOnInit() {
    this.me.set(await this.api.get('/portal/me'));
    this.i18n.adopt(this.me()?.user?.language ?? (this.auth.user() as any)?.language);
    this.projects.set(await this.api.get('/portal/projects'));
    this.proposals.set(await this.api.get('/portal/proposals'));
  }

  async view(id: string) {
    this.open.set(await this.api.get(`/portal/projects/${id}`));
    const [d, s, ph] = await Promise.all([this.api.get(`/portal/projects/${id}/documents`), this.api.get(`/portal/projects/${id}/selections`),
      this.api.get(`/portal/projects/${id}/photos`)]);
    this.docs.set(d);
    this.sels.set(s);
    this.photos.set(ph.photos);
    this.boards.set(await this.api.get(`/portal/projects/${id}/boards`));
    this.requests.set(await this.api.get(`/portal/projects/${id}/change-requests`));
  }
}
