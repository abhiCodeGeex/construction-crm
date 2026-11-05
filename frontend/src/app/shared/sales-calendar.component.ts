import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { SelectButtonModule } from 'primeng/selectbutton';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';

const KIND_ICON: Record<string, string> = { visit: 'pi pi-map-marker', followup: 'pi pi-bell', bid: 'pi pi-briefcase', proposal: 'pi pi-file-edit' };

/** Calendar (C+3): site visits, follow-ups, bid due dates and proposal expiry, by month — mine or the team's. */
@Component({
  selector: 'app-sales-calendar',
  imports: [FormsModule, DatePipe, ButtonModule, SelectButtonModule],
  template: `
    <div class="row-between mb">
      <div class="row gap">
        <p-button icon="pi pi-chevron-left" [text]="true" (onClick)="shift(-1)" ariaLabel="Previous month" />
        <strong>{{ month() | date: 'MMMM y' }}</strong>
        <p-button icon="pi pi-chevron-right" [text]="true" (onClick)="shift(1)" ariaLabel="Next month" />
        <p-button label="Today" size="small" [text]="true" (onClick)="goToday()" />
      </div>
      @if (canTeam()) { <p-selectbutton [options]="scopes" [(ngModel)]="scope" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="load()" /> }
    </div>
    <div class="cal">
      @for (d of dow; track d) { <div class="cal-dow">{{ d }}</div> }
      @for (c of cells(); track c.key) {
        <div class="cal-day" [class.other]="!c.inMonth" [class.today]="c.today">
          <small class="cal-num">{{ c.date.getDate() }}</small>
          @for (e of c.events; track $index) {
            <button class="cal-ev" [class]="'k-' + e.kind" (click)="go(e)" [title]="e.title + (e.detail ? ' — ' + e.detail : '')">
              <i [class]="icon[e.kind]"></i> {{ e.at ? (e.at | date: 'HH:mm') + ' ' : '' }}{{ e.title }}</button>
          }
        </div>
      }
    </div>
    <small class="muted">Times are your local time.</small>
  `,
})
export class SalesCalendarComponent implements OnInit {
  private api = inject(Api);
  private router = inject(Router);
  auth = inject(AuthService);
  month = signal(this.first(new Date()));
  events = signal<any[]>([]);
  scope = 'mine';
  icon = KIND_ICON;
  dow = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  scopes = [{ label: 'Mine', value: 'mine' }, { label: 'Team', value: 'team' }];
  canTeam = computed(() => ['owner', 'pm'].includes(this.auth.user()?.role ?? ''));
  cells = computed(() => {
    const m = this.month();
    const start = new Date(m);
    start.setDate(1 - ((m.getDay() + 6) % 7));
    const today = this.iso(new Date());
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      const key = this.iso(d);
      return { key, date: d, inMonth: d.getMonth() === m.getMonth(), today: key === today,
        events: this.events().filter((e) => (e.at ? this.iso(new Date(e.at)) : e.date) === key) };
    });
  });

  ngOnInit() {
    this.load();
  }

  first(d: Date) {
    return new Date(d.getFullYear(), d.getMonth(), 1);
  }

  iso(d: Date) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  goToday() {
    this.month.set(this.first(new Date()));
    this.load();
  }

  shift(n: number) {
    const m = this.month();
    this.month.set(new Date(m.getFullYear(), m.getMonth() + n, 1));
    this.load();
  }

  async load() {
    const c = this.cells();
    const r = await this.api.get(`/calendar?from=${c[0].key}&to=${c[41].key}&scope=${this.scope}`);
    this.events.set(r.events);
  }

  go(e: any) {
    if (e.link) this.router.navigateByUrl(e.link);
  }
}
