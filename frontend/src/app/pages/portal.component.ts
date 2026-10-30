import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AvatarModule } from 'primeng/avatar';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { TagModule } from 'primeng/tag';
import { AuthService } from '../core/auth.service';
import { ThemeService } from '../core/theme.service';

const WHAT_YOU_GET: Record<string, string[]> = {
  client: ['Project progress, schedule and photo timeline', 'Approve drawings, selections, quotes and change orders', 'View and pay invoices online', 'Messages and documents in one place'],
  vendor: ['Purchase orders sent to you', 'Update delivery dates and backorders', 'Payment status'],
  subcontractor: ['Bid invitations', 'Your work packages and progress', 'Payments and retention'],
  consultant: ['Drawings assigned to you', 'RFIs to answer'],
};

/** Landing page for external users (client, vendor, subcontractor, consultant). */
@Component({
  selector: 'app-portal',
  imports: [AvatarModule, ButtonModule, CardModule, TagModule],
  template: `
    <header class="portal-top">
      <div class="logo"><span class="mark"><i class="pi pi-building"></i></span> {{ me()?.company?.name ?? 'Portal' }}</div>
      <span class="spacer"></span>
      <p-button [icon]="theme.dark() ? 'pi pi-sun' : 'pi pi-moon'" [rounded]="true" [text]="true" severity="secondary" (onClick)="theme.toggle()" />
      <p-button label="Sign out" icon="pi pi-sign-out" [text]="true" severity="secondary" (onClick)="auth.logout()" />
    </header>
    <main class="portal-body">
      <div class="portal-hero">
        <p-avatar icon="pi pi-user" size="xlarge" shape="circle" styleClass="avatar ext" />
        <div>
          <h1>Hello, {{ auth.user()?.name }}</h1>
          <p class="muted">{{ me()?.contact?.name }} · <p-tag [value]="me()?.label ?? ''" severity="info" /></p>
        </div>
      </div>
      <p-card>
        <ng-template #title>Your {{ me()?.label?.toLowerCase() }} portal</ng-template>
        <p class="muted">Coming in the next phase:</p>
        <ul class="ticks">
          @for (x of features(); track x) { <li><i class="pi pi-check-circle"></i> {{ x }}</li> }
        </ul>
        <p class="muted small">Portal users never see costs, margins or internal company screens.</p>
      </p-card>
    </main>
  `,
})
export class PortalComponent implements OnInit {
  auth = inject(AuthService);
  theme = inject(ThemeService);
  private http = inject(HttpClient);
  me = signal<any>(null);
  features = signal<string[]>([]);

  async ngOnInit() {
    const me = await firstValueFrom(this.http.get<any>('/api/portal/me'));
    this.me.set(me);
    this.features.set(WHAT_YOU_GET[me.role] ?? []);
  }
}
