import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { MessageModule } from 'primeng/message';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { AuthService } from '../core/auth.service';
import { NAV } from '../core/nav';

interface MatrixRole { role: string; label: string; kind: string; perms: Record<string, string>; hide_costs: boolean }
type Probe = { status: number; text: string };

/** Shows what the signed-in role can do and fires real read/write requests at every area. */
@Component({
  selector: 'app-access',
  imports: [ButtonModule, CardModule, MessageModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>My access</h1>
        <p class="muted">Each button sends a real request; the server decides — <b>200</b> allowed, <b>403</b> blocked.</p>
      </div>
      <p-button label="Test all areas" icon="pi pi-play" [loading]="running()" (onClick)="testAll()" />
    </div>
    @if (summary(); as s) { <p-message [severity]="s.bad ? 'error' : 'success'" [text]="s.text" styleClass="mb" /> }

    <p-card>
      <p-table [value]="nav" size="small" [rowHover]="true">
        <ng-template #header><tr><th>Area</th><th>Expected</th><th>Read</th><th>Write</th></tr></ng-template>
        <ng-template #body let-n>
          <tr>
            <td><i [class]="n.icon" class="mr"></i>{{ n.label }}</td>
            <td>
              @switch (auth.session()?.permissions?.[n.area]) {
                @case ('rw') { <p-tag value="read + write" severity="success" /> }
                @case ('r') { <p-tag value="read only" severity="warn" /> }
                @default { <p-tag value="no access" severity="secondary" /> }
              }
            </td>
            <td class="probe">
              <p-button label="Read" size="small" [outlined]="true" (onClick)="probe(n.area, 'GET')" />
              @if (results()[n.area + 'GET']; as r) { <p-tag [value]="'' + r.status" [severity]="r.status === 200 ? 'success' : 'danger'" /> }
            </td>
            <td class="probe">
              <p-button label="Write" size="small" [outlined]="true" (onClick)="probe(n.area, 'POST')" />
              @if (results()[n.area + 'POST']; as r) { <p-tag [value]="'' + r.status" [severity]="r.status === 200 ? 'success' : 'danger'" /> }
            </td>
          </tr>
        </ng-template>
      </p-table>
    </p-card>

    @if (sample()) {
      <p-card styleClass="mt">
        <ng-template #title>Cost hiding check</ng-template>
        <p class="muted small">Sample record returned to your role. Site staff and portal users never receive trade price, margin, budget or spent.</p>
        <pre class="code">{{ sample() }}</pre>
      </p-card>
    }

    <p-card styleClass="mt">
      <ng-template #title>Role matrix</ng-template>
      <p-table [value]="matrix()" size="small" [scrollable]="true" styleClass="matrix">
        <ng-template #header>
          <tr><th pFrozenColumn>Role</th>@for (a of areas(); track a) { <th class="center cap">{{ a.replace('_', ' ') }}</th> }</tr>
        </ng-template>
        <ng-template #body let-r>
          <tr [class.me]="r.role === auth.user()?.role">
            <td pFrozenColumn>{{ r.label }} @if (r.kind === 'external') { <small class="muted">(portal)</small> }</td>
            @for (a of areas(); track a) {
              <td class="center">
                @if (r.perms[a] === 'rw') { <i class="pi pi-pencil c-ok"></i> }
                @else if (r.perms[a] === 'r') { <i class="pi pi-eye c-warn"></i> }
                @else { <span class="muted">—</span> }
              </td>
            }
          </tr>
        </ng-template>
      </p-table>
      <p class="muted small"><i class="pi pi-pencil c-ok"></i> read + write · <i class="pi pi-eye c-warn"></i> read only · — no access. Portal roles use the portal only.</p>
    </p-card>
  `,
})
export class AccessComponent implements OnInit {
  auth = inject(AuthService);
  private http = inject(HttpClient);
  nav = NAV;
  results = signal<Record<string, Probe>>({});
  sample = signal('');
  matrix = signal<MatrixRole[]>([]);
  areas = signal<string[]>([]);
  summary = signal<{ text: string; bad: boolean } | null>(null);
  running = signal(false);

  async ngOnInit() {
    const m = await firstValueFrom(this.http.get<{ areas: string[]; roles: MatrixRole[] }>('/api/access/matrix'));
    this.areas.set(m.areas);
    this.matrix.set(m.roles);
  }

  async probe(area: string, method: 'GET' | 'POST') {
    let res: Probe;
    try {
      const url = `/api/access/probe/${area}`;
      const body = await firstValueFrom(method === 'GET' ? this.http.get<any>(url) : this.http.post<any>(url, {}));
      res = { status: 200, text: 'allowed' };
      if (method === 'GET') this.sample.set(JSON.stringify(body.sample, null, 2));
    } catch (e: any) {
      res = { status: e.status, text: e.error?.error };
    }
    this.results.update((r) => ({ ...r, [area + method]: res }));
    return res;
  }

  async testAll() {
    this.running.set(true);
    let ok = 0;
    let bad = 0;
    for (const n of this.nav) {
      for (const m of ['GET', 'POST'] as const) {
        const r = await this.probe(n.area, m);
        const expected = this.auth.can(n.area, m === 'GET' ? 'r' : 'rw') ? 200 : 403;
        r.status === expected ? ok++ : bad++;
      }
    }
    this.running.set(false);
    this.summary.set({ text: `${ok} checks matched the expected permissions${bad ? `, ${bad} did NOT` : ''}.`, bad: bad > 0 });
  }
}
