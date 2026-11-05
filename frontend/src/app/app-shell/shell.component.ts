import { Component, OnInit, computed, inject, signal } from '@angular/core';
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

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, AvatarModule, ButtonModule, MenuModule, TagModule, TooltipModule, NotificationBellComponent],
  template: `
    <div class="layout" [class.collapsed]="collapsed()">
      <aside class="sidebar">
        <div class="logo"><span class="mark"><i class="pi pi-building"></i></span><span class="txt">BuildSuite</span></div>
        <nav>
          <a routerLink="/app" [routerLinkActiveOptions]="{ exact: true }" routerLinkActive="active" pTooltip="Home" [tooltipDisabled]="!collapsed()">
            <i class="pi pi-home"></i><span class="txt">Home</span></a>
          <a routerLink="/app/access" routerLinkActive="active" pTooltip="My access" [tooltipDisabled]="!collapsed()">
            <i class="pi pi-shield"></i><span class="txt">My access</span></a>
          @for (s of sections(); track s.name) {
            <div class="nav-section txt">{{ s.name }}</div>
            @for (n of s.items; track n.area) {
              <a [routerLink]="n.path ?? '/app/m/' + n.area" routerLinkActive="active" [pTooltip]="n.label" [tooltipDisabled]="!collapsed()">
                <i [class]="n.icon"></i><span class="txt">{{ n.label }}</span>
                @if (!n.ready) { <span class="soon txt">soon</span> }
                @else if (!auth.can(n.area, 'rw')) { <span class="soon txt">view</span> }
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
          <p-menu #menu [model]="userMenu" [popup]="true" appendTo="body" />
        </header>
        <main class="content"><router-outlet /></main>
      </div>
    </div>
  `,
})
export class ShellComponent implements OnInit {
  auth = inject(AuthService);
  theme = inject(ThemeService);
  collapsed = signal(false);

  // the menu only lists areas the role can at least read
  sections = computed(() => {
    this.auth.session();
    return SECTIONS.map((name) => ({ name, items: NAV.filter((n) => n.section === name && this.auth.can(n.area)) })).filter((s) => s.items.length);
  });

  initials = computed(() => (this.auth.user()?.name ?? '?').split(/\s+/).filter((w) => /^[a-z0-9]/i.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase());

  userMenu: MenuItem[] = [
    { label: 'My access', icon: 'pi pi-shield', routerLink: '/app/access' },
    { separator: true },
    { label: 'Sign out', icon: 'pi pi-sign-out', command: () => this.auth.logout() },
  ];

  ngOnInit() {
    // pick up role / permission changes made by an admin since the last sign-in
    this.auth.refresh().catch(() => undefined);
  }
}
