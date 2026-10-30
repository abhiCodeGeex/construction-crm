import { HttpClient } from '@angular/common/http';
import { Component, computed, inject, input, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { TagModule } from 'primeng/tag';
import { AuthService } from '../core/auth.service';
import { NAV } from '../core/nav';

/** Placeholder for a module that is not built yet: shows the role's access and lets you try it. */
@Component({
  selector: 'app-area',
  imports: [ButtonModule, CardModule, TagModule],
  template: `
    <div class="page-head">
      <div><h1><i [class]="item()?.icon" class="mr"></i>{{ item()?.label }}</h1>
        <p class="muted">Planned for a later phase — use this page to verify access for your role.</p></div>
      @if (auth.can(area(), 'rw')) { <p-tag value="read + write" severity="success" icon="pi pi-pencil" /> }
      @else { <p-tag value="read only" severity="warn" icon="pi pi-eye" /> }
    </div>
    <div class="empty-state">
      <i [class]="item()?.icon"></i>
      <h3>{{ item()?.label }} is coming soon</h3>
      <div class="row gap center-x">
        <p-button label="Try reading" icon="pi pi-eye" [outlined]="true" (onClick)="probe('GET')" />
        <p-button label="Try saving" icon="pi pi-save" [disabled]="!auth.can(area(), 'rw')" (onClick)="probe('POST')" />
        <p-button label="Force a save request" icon="pi pi-bolt" severity="secondary" [text]="true" (onClick)="probe('POST')" />
      </div>
      @if (result()) { <pre class="code left">{{ result() }}</pre> }
    </div>
  `,
})
export class AreaComponent {
  auth = inject(AuthService);
  private http = inject(HttpClient);
  area = input.required<string>();
  item = computed(() => NAV.find((n) => n.area === this.area()));
  result = signal('');

  async probe(method: 'GET' | 'POST') {
    const url = `/api/access/probe/${this.area()}`;
    try {
      const r = await firstValueFrom(method === 'GET' ? this.http.get(url) : this.http.post(url, {}));
      this.result.set(`${method} → 200 OK\n` + JSON.stringify(r, null, 2));
    } catch (e: any) {
      this.result.set(`${method} → ${e.status} ${e.error?.error ?? ''}`);
    }
  }
}

@Component({
  selector: 'app-forbidden',
  imports: [ButtonModule],
  template: `
    <div class="empty-state">
      <i class="pi pi-lock c-bad"></i>
      <h3>No access</h3>
      <p class="muted">Your role ({{ auth.roleLabel(auth.user()?.role) }}) cannot open {{ area ? '“' + area.replace('_', ' ') + '”' : 'this page' }}.</p>
      <p-button label="Back to home" icon="pi pi-home" (onClick)="router.navigateByUrl('/app')" />
    </div>
  `,
})
export class ForbiddenComponent {
  auth = inject(AuthService);
  area = inject(ActivatedRoute).snapshot.queryParamMap.get('area');
  router = inject(Router);
}
