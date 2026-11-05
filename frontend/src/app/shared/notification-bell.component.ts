import { Component, OnDestroy, OnInit, inject, signal, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { BadgeModule } from 'primeng/badge';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { Popover, PopoverModule } from 'primeng/popover';
import { TableModule } from 'primeng/table';
import { Api } from '../core/api.service';

/** The bell (C+1): the signed-in user's notifications, refreshed every minute, and their preferences. */
@Component({
  selector: 'app-notification-bell',
  imports: [FormsModule, DatePipe, BadgeModule, ButtonModule, CheckboxModule, DialogModule, PopoverModule, TableModule],
  template: `
    <p-button icon="pi pi-bell" [rounded]="true" [text]="true" severity="secondary" (onClick)="toggle($event)" ariaLabel="Notifications"
      [badge]="unread() ? (unread() > 99 ? '99+' : '' + unread()) : undefined" badgeSeverity="danger" />
    <p-popover #pop styleClass="bell-pop" appendTo="body">
      <div class="row-between mb-xs">
        <strong>Notifications</strong>
        <span class="row gap">
          @if (unread()) { <p-button label="Mark all read" size="small" [text]="true" (onClick)="readAll()" /> }
          <p-button icon="pi pi-cog" size="small" [text]="true" (onClick)="openPrefs(); pop.hide()" ariaLabel="Notification settings" />
        </span>
      </div>
      <div class="bell-list">
        @for (n of items(); track n.id) {
          <button class="bell-item" [class.unread]="!n.read_at" (click)="go(n); pop.hide()">
            <strong>{{ n.title }}</strong>
            <span>{{ n.text }}</span>
            <small class="muted">{{ n.created_at | date: 'd MMM, h:mm a' }}{{ n.email === 'sent' ? ' · emailed' : '' }}</small>
          </button>
        } @empty { <p class="muted small center">Nothing yet.</p> }
      </div>
    </p-popover>

    <p-dialog header="Notification settings" [modal]="true" [(visible)]="prefsDlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '96vw' }">
      @if (!emailReady()) { <p class="muted small">Email copies start once the owner sets up email in Company settings → Sales.</p> }
      <p-table [value]="prefs()" size="small" [scrollable]="true" scrollHeight="55vh">
        <ng-template #header><tr><th>Notify me about</th><th class="center">In app</th><th class="center">Email</th></tr></ng-template>
        <ng-template #body let-e>
          <tr><td>{{ e.label }} @if (e.critical) { <small class="muted">(always on)</small> }</td>
            <td class="center"><p-checkbox [(ngModel)]="e.in_app" [binary]="true" [disabled]="e.critical" /></td>
            <td class="center"><p-checkbox [(ngModel)]="e.email" [binary]="true" /></td></tr>
        </ng-template>
      </p-table>
      <div class="row right mt"><p-button label="Save" icon="pi pi-check" (onClick)="savePrefs()" /></div>
    </p-dialog>
  `,
})
export class NotificationBellComponent implements OnInit, OnDestroy {
  private api = inject(Api);
  private router = inject(Router);
  items = signal<any[]>([]);
  unread = signal(0);
  prefs = signal<any[]>([]);
  emailReady = signal(false);
  prefsDlg = false;
  private timer: any;
  popover = viewChild.required<Popover>("pop");

  ngOnInit() {
    this.load();
    this.timer = setInterval(() => this.load(), 60000);
  }

  ngOnDestroy() {
    clearInterval(this.timer);
  }

  async load() {
    try {
      const r = await this.api.get('/notifications?limit=30');
      this.items.set(r.items);
      this.unread.set(r.unread);
    } catch {
      /* signed out or offline: try again on the next tick */
    }
  }

  toggle(ev: Event) {
    this.load();
    this.popover().toggle(ev);
  }

  async go(n: any) {
    if (!n.read_at) await this.api.post(`/notifications/${n.id}/read`);
    await this.load();
    if (n.link) this.router.navigateByUrl(n.link);
  }

  async readAll() {
    await this.api.post('/notifications/read-all');
    await this.load();
  }

  async openPrefs() {
    const p = await this.api.get('/notifications/prefs');
    this.prefs.set(p.events);
    this.emailReady.set(p.email_ready);
    this.prefsDlg = true;
  }

  async savePrefs() {
    await this.api.put('/notifications/prefs', { events: this.prefs() }, 'Notification settings saved');
    this.prefsDlg = false;
  }
}
