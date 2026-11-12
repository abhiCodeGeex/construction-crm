import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AvatarModule } from 'primeng/avatar';
import { ButtonModule } from 'primeng/button';
import { MenuModule } from 'primeng/menu';
import { TagModule } from 'primeng/tag';
import { TooltipModule } from 'primeng/tooltip';
import { MenuItem } from 'primeng/api';
import { AuthService } from '../core/auth.service';
import { NAV, SECTIONS } from '../core/nav';
import { ThemeService } from '../core/theme.service';
import { NotificationBellComponent } from '../shared/notification-bell.component';
import { ChangePasswordComponent } from '../shared/change-password.component';
import { DialogModule } from 'primeng/dialog';
import { I18n, TPipe } from '../core/i18n';

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, AvatarModule, ButtonModule, MenuModule, TagModule, TooltipModule, NotificationBellComponent, ChangePasswordComponent, DialogModule, TPipe],
  styles: `.banner { display: flex; gap: .5rem; align-items: center; padding: .5rem 1.25rem; background: var(--surface); border-bottom: 1px solid var(--border); font-size: .9rem; }
    .banner.warn { background: rgba(217, 119, 6, .12); } .banner .link { margin-left: auto; background: none; border: 0; cursor: pointer; color: inherit; text-decoration: underline; }`,
  template: `
    <div class="layout" [class.collapsed]="collapsed()">
      <aside class="sidebar">
        <div class="logo"><span class="mark"><i class="pi pi-building"></i></span><span class="txt">BuildSuite</span></div>
        <nav>
          <a routerLink="/app" [routerLinkActiveOptions]="{ exact: true }" routerLinkActive="active" pTooltip="Home" [tooltipDisabled]="!collapsed()">
            <i class="pi pi-home"></i><span class="txt">{{ 'Home' | t }}</span></a>
          <a routerLink="/app/access" routerLinkActive="active" pTooltip="My access" [tooltipDisabled]="!collapsed()">
            <i class="pi pi-shield"></i><span class="txt">{{ 'My access' | t }}</span></a>
          @for (s of sections(); track s.name) {
            <div class="nav-section txt">{{ s.name | t }}</div>
            @for (n of s.items; track n.area) {
              <a [routerLink]="n.path ?? '/app/m/' + n.area" routerLinkActive="active" [pTooltip]="n.label" [tooltipDisabled]="!collapsed()">
                <i [class]="n.icon"></i><span class="txt">{{ n.label | t }}</span>
                @if (!n.ready) { <span class="soon txt">{{ 'soon' | t }}</span> }
                @else if (!auth.can(n.area, 'rw')) { <span class="soon txt">{{ 'view' | t }}</span> }
              </a>
            }
          }
        </nav>
      </aside>

      <div class="main">
        <header class="topbar">
          <p-button icon="pi pi-bars" [text]="true" severity="secondary" (onClick)="collapsed.set(!collapsed())" ariaLabel="Toggle menu" />
          <div class="company-name">{{ auth.company()?.name }}</div>
          <p-tag [value]="auth.company()?.status ?? ''" [severity]="auth.company()?.status === 'active' ? 'success' : 'info'" />
          <span class="spacer"></span>
          <app-notification-bell />
          <p-button [icon]="theme.dark() ? 'pi pi-sun' : 'pi pi-moon'" [rounded]="true" [text]="true" severity="secondary" (onClick)="theme.toggle()" ariaLabel="Theme" />
          <button class="who" (click)="menu.toggle($event)">
            <p-avatar [label]="initials()" shape="circle" styleClass="avatar" />
            <span class="who-text">
              <strong>{{ auth.user()?.name }}</strong>
              <small>{{ auth.roleLabel(auth.user()?.role) }}</small>
            </span>
            <i class="pi pi-angle-down"></i>
          </button>
          <p-menu #menu [model]="userMenu()" [popup]="true" appendTo="body" />
          <p-dialog [header]="'Calendar feed' | t" [modal]="true" [(visible)]="calDlg" [style]="{ width: '34rem' }">
            <div class="stack">
              <p class="small m0">Subscribe to this link in Google Calendar (Other calendars → From URL) or Outlook (Add calendar → Subscribe from web): your tasks, milestones, follow-ups, site visits and meetings. Keep it private — anyone with the link sees these events.</p>
              <input class="p-inputtext" [value]="calUrl()" readonly (focus)="$any($event.target).select()" />
              <div class="row gap right"><p-button label="Copy" size="small" (onClick)="copyCal()" /><p-button label="Make a new link" size="small" [text]="true" severity="secondary" (onClick)="resetCal()" /></div>
            </div>
          </p-dialog>
          <app-change-password />
        </header>
        @if (support()) { <div class="banner warn"><i class="pi pi-shield"></i> Platform support session — every action is logged in your audit log. It ends within an hour.
          <button type="button" class="link" (click)="auth.logout()">End it now</button></div> }
        @for (a of news(); track a.id) { <div class="banner"><i class="pi pi-megaphone"></i> <strong>{{ a.title }}</strong> {{ a.body }}
          <button type="button" class="link" (click)="dismiss(a.id)" aria-label="Dismiss">✕</button></div> }
        <main class="content"><router-outlet /></main>
      </div>
    </div>
  `,
})
export class ShellComponent implements OnInit {
  auth = inject(AuthService);
  theme = inject(ThemeService);
  collapsed = signal(false);
  pwd = viewChild.required(ChangePasswordComponent);

  // the menu only lists areas the role can at least read
  sections = computed(() => {
    this.auth.session();
    return SECTIONS.map((name) => ({ name, items: NAV.filter((n) => n.section === name && this.auth.can(n.area)) })).filter((s) => s.items.length);
  });

  initials = computed(() => (this.auth.user()?.name ?? '?').split(/\s+/).filter((w) => /^[a-z0-9]/i.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase());

  i18n = inject(I18n);
  calDlg = false;
  calUrl = signal('');
  userMenu = computed<MenuItem[]>(() => {
    const t = (x: string) => this.i18n.t(x);
    return [
      { label: t('My access'), icon: 'pi pi-shield', routerLink: '/app/access' },
      { label: t('Change password'), icon: 'pi pi-key', command: () => this.pwd().open() },
      { label: t('Calendar feed'), icon: 'pi pi-calendar', command: () => this.openCal() },
      { label: `${t('Language')}: ${this.i18n.lang() === 'hi' ? 'हिन्दी → English' : 'English → हिन्दी'}`, icon: 'pi pi-language',
        command: () => this.i18n.set(this.i18n.lang() === 'hi' ? 'en' : 'hi') },
      { separator: true },
      { label: t('Sign out'), icon: 'pi pi-sign-out', command: () => this.auth.logout() },
    ];
  });

  async openCal() {
    const r = await firstValueFrom(this.http.get<{ url: string }>('/api/calendar/link'));
    this.calUrl.set(location.origin + r.url);
    this.calDlg = true;
  }

  async resetCal() {
    const r = await firstValueFrom(this.http.post<{ url: string }>('/api/calendar/link/reset', {}));
    this.calUrl.set(location.origin + r.url);
  }

  copyCal() {
    navigator.clipboard?.writeText(this.calUrl()).catch(() => undefined);
  }

  private http = inject(HttpClient);
  news = signal<any[]>([]);
  support = computed(() => {
    try {
      return !!JSON.parse(atob((this.auth.session()?.token ?? '').split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).support_session;
    } catch {
      return false;
    }
  });

  ngOnInit() {
    // pick up role / permission changes made by an admin since the last sign-in
    this.auth.refresh().then(() => this.i18n.adopt((this.auth.user() as any)?.language)).catch(() => undefined);
    // Phase I: platform announcements not dismissed in this browser
    firstValueFrom(this.http.get<any[]>('/api/announcements')).then((rows) => {
      let seen: string[] = [];
      try { seen = JSON.parse(localStorage.getItem('bs.news.seen') ?? '[]'); } catch { seen = []; }
      this.news.set(rows.filter((r) => !seen.includes(r.id)).slice(0, 2));
    }).catch(() => undefined);
  }

  dismiss(id: string) {
    try {
      const seen = JSON.parse(localStorage.getItem('bs.news.seen') ?? '[]');
      localStorage.setItem('bs.news.seen', JSON.stringify([...seen, id].slice(-50)));
    } catch { /* private window */ }
    this.news.set(this.news().filter((n) => n.id !== id));
  }
}
