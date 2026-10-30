import { Component, computed, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { ProgressBarModule } from 'primeng/progressbar';
import { AuthService } from '../core/auth.service';
import { NAV } from '../core/nav';

@Component({
  selector: 'app-home',
  imports: [RouterLink, DatePipe, ButtonModule, CardModule, ProgressBarModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Good to see you, {{ firstName() }}</h1>
        <p class="muted">{{ auth.roleLabel(auth.user()?.role) }} at {{ auth.company()?.name }}</p>
      </div>
    </div>

    <div class="stats">
      <div class="stat-card">
        <span class="stat-icon indigo"><i class="pi pi-user"></i></span>
        <div><small>Your role</small><strong>{{ auth.roleLabel(auth.user()?.role) }}</strong></div>
      </div>
      <div class="stat-card">
        <span class="stat-icon teal"><i class="pi pi-star"></i></span>
        <div><small>Plan</small><strong>{{ auth.session()?.limits?.plan }}</strong>
          <small class="muted">{{ auth.session()?.limits?.users }} users · {{ auth.session()?.limits?.modules }} module(s)</small></div>
      </div>
      <div class="stat-card">
        <span class="stat-icon amber"><i class="pi pi-calendar"></i></span>
        <div><small>Account</small><strong class="cap">{{ auth.company()?.status }}</strong>
          @if (auth.company()?.status === 'trial') { <small class="muted">Trial ends {{ auth.company()?.trial_ends | date }}</small> }</div>
      </div>
      <div class="stat-card">
        <span class="stat-icon pink"><i class="pi pi-th-large"></i></span>
        <div><small>Areas you can open</small><strong>{{ readable().length }} / {{ nav.length }}</strong>
          <p-progressbar [value]="pct()" [showValue]="false" styleClass="thin" /></div>
      </div>
    </div>

    <p-card styleClass="mt">
      <ng-template #title>What's in this build</ng-template>
      <p>This release covers <strong>authentication and role-based authorization</strong>. Business modules appear in the menu
        as <em>soon</em> placeholders, so you can verify each role's access before they are built.</p>
      <p-button label="Test my access" icon="pi pi-shield" routerLink="/app/access" />
    </p-card>

    <h3 class="mt">Your areas</h3>
    <div class="area-grid">
      @for (n of readable(); track n.area) {
        <a class="area-tile" [routerLink]="n.path ?? '/app/m/' + n.area">
          <i [class]="n.icon"></i>
          <span>{{ n.label }}</span>
          <small [class.ok]="auth.can(n.area, 'rw')">{{ auth.can(n.area, 'rw') ? 'Edit' : 'View only' }}</small>
        </a>
      }
    </div>
  `,
})
export class HomeComponent {
  auth = inject(AuthService);
  nav = NAV;
  readable = computed(() => NAV.filter((n) => this.auth.can(n.area)));
  pct = computed(() => Math.round((this.readable().length / NAV.length) * 100));
  firstName = computed(() => (this.auth.user()?.name ?? '').split(' ')[0]);
}
