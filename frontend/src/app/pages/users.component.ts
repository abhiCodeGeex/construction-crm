import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ConfirmationService, MessageService } from 'primeng/api';
import { AvatarModule } from 'primeng/avatar';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { IconFieldModule } from 'primeng/iconfield';
import { InputIconModule } from 'primeng/inputicon';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';
import { ProgressBarModule } from 'primeng/progressbar';
import { SelectModule } from 'primeng/select';
import { Table, TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';
import { User } from '../core/models';

interface Summary { limits: { plan: string; users: number | null }; usage: { users: number; free_users: number } }

@Component({
  selector: 'app-users',
  imports: [FormsModule, DatePipe, AvatarModule, ButtonModule, CardModule, CheckboxModule, DialogModule, IconFieldModule, InputIconModule,
    InputTextModule, MessageModule, PasswordModule, ProgressBarModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div>
        <h1>Users & roles</h1>
        <p class="muted">Staff are counted against your plan; portal users and WhatsApp-only site workers are free.</p>
      </div>
      @if (canEdit()) { <p-button label="Add user" icon="pi pi-plus" (onClick)="openNew()" /> }
    </div>

    @if (summary(); as s) {
      <div class="stats">
        <div class="stat-card">
          <span class="stat-icon indigo"><i class="pi pi-users"></i></span>
          <div class="grow"><small>Paid users ({{ s.limits.plan }})</small><strong>{{ s.usage.users }} / {{ s.limits.users ?? '∞' }}</strong>
            <p-progressbar [value]="s.limits.users ? (s.usage.users / s.limits.users) * 100 : 0" [showValue]="false" styleClass="thin" /></div>
        </div>
        <div class="stat-card">
          <span class="stat-icon teal"><i class="pi pi-globe"></i></span>
          <div><small>Free users</small><strong>{{ s.usage.free_users }}</strong><small class="muted">portal + WhatsApp-only</small></div>
        </div>
      </div>
    }
    @if (!canEdit()) { <p-message severity="info" icon="pi pi-eye" text="Read-only: your role can view users but not change them." styleClass="mb" /> }

    <p-card>
      <p-table #dt [value]="users()" [rowHover]="true" [paginator]="users().length > 15" [rows]="15" dataKey="id"
               [globalFilterFields]="['name', 'email', 'role']" size="small">
        <ng-template #caption>
          <div class="row-between">
            <p-iconfield>
              <p-inputicon class="pi pi-search" />
              <input pInputText placeholder="Search users" (input)="dt.filterGlobal($any($event.target).value, 'contains')" />
            </p-iconfield>
          </div>
        </ng-template>
        <ng-template #header>
          <tr>
            <th pSortableColumn="name">Name <p-sortIcon field="name" /></th>
            <th pSortableColumn="role">Role <p-sortIcon field="role" /></th>
            <th>Type</th><th>Status</th><th pSortableColumn="last_login">Last login <p-sortIcon field="last_login" /></th><th></th>
          </tr>
        </ng-template>
        <ng-template #body let-u>
          <tr [class.inactive]="u.active === false">
            <td>
              <div class="person">
                <p-avatar [label]="initials(u.name)" shape="circle" [styleClass]="u.kind === 'external' ? 'avatar ext' : 'avatar'" />
                <div><strong>{{ u.name }}</strong> @if (u.id === auth.user()?.id) { <small class="muted">(you)</small> }<br /><small class="muted">{{ u.email }}</small></div>
              </div>
            </td>
            <td>{{ auth.roleLabel(u.role) }}</td>
            <td><p-tag [value]="u.kind === 'external' ? 'Portal' : u.whatsapp_only ? 'WhatsApp only' : 'Staff'"
                       [severity]="u.kind === 'external' ? 'info' : 'secondary'" /></td>
            <td><p-tag [value]="u.active === false ? 'Inactive' : 'Active'" [severity]="u.active === false ? 'danger' : 'success'" /></td>
            <td><small>{{ u.last_login ? (u.last_login | date: 'short') : '—' }}</small></td>
            <td class="right nowrap">
              @if (canEdit()) {
                <p-button icon="pi pi-pencil" [rounded]="true" [text]="true" (onClick)="edit(u)" ariaLabel="Edit" />
                @if (u.id !== auth.user()?.id) {
                  <p-button [icon]="u.active === false ? 'pi pi-check-circle' : 'pi pi-ban'" [rounded]="true" [text]="true"
                            [severity]="u.active === false ? 'success' : 'danger'" (onClick)="toggle(u)"
                            [ariaLabel]="u.active === false ? 'Activate' : 'Deactivate'" />
                }
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="6" class="center muted">No users found</td></tr></ng-template>
      </p-table>
    </p-card>

    <p-dialog [header]="form()?.id ? 'Edit user' : 'Add user'" [modal]="true" [(visible)]="dialog" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '95vw' }">
      @if (form(); as f) {
        <form class="stack" (ngSubmit)="save()">
          <div class="grid2">
            <label class="field"><span>Name</span><input pInputText name="name" [(ngModel)]="f.name" required fluid /></label>
            <label class="field"><span>Phone</span><input pInputText name="phone" [(ngModel)]="f.phone" fluid /></label>
          </div>
          <label class="field"><span>Email</span><input pInputText name="email" type="email" [(ngModel)]="f.email" [disabled]="!!f.id" required fluid /></label>
          <label class="field"><span>Role</span>
            <p-select name="role" [(ngModel)]="f.role" [options]="roleOptions(f)" optionLabel="label" optionValue="value"
                      optionDisabled="disabled" [group]="true" fluid appendTo="body" />
          </label>
          @if (isExternalRole(f.role) && !f.id) {
            <label class="field"><span>Organisation</span><input pInputText name="org" [(ngModel)]="f.org" placeholder="e.g. client's company" fluid /></label>
          }
          <label class="field"><span>{{ f.id ? 'New password (optional)' : 'Password' }}</span>
            <p-password name="password" [(ngModel)]="f.password" [toggleMask]="true" [feedback]="false" fluid appendTo="body" />
            @if (!f.id || f.password) { <small class="hint" [class.ok]="(f.password ?? '').length >= 6"><i class="pi" [class.pi-check-circle]="(f.password ?? '').length >= 6" [class.pi-info-circle]="(f.password ?? '').length < 6"></i> At least 6 characters</small> }</label>
          @if (f.role === 'site' && !f.id) {
            <label class="check"><p-checkbox name="wa" [(ngModel)]="f.whatsapp_only" [binary]="true" /> WhatsApp-only site worker (free, not counted)</label>
          }
          @if (error()) { <p-message severity="error" [text]="error()" /> }
          <div class="row gap right">
            <p-button label="Cancel" severity="secondary" [text]="true" (onClick)="dialog = false" />
            <p-button type="submit" label="Save" icon="pi pi-check" [loading]="busy()" />
          </div>
        </form>
      }
    </p-dialog>

    <p-dialog header="Hand over open work" [modal]="true" [(visible)]="handDlg" [style]="{ width: '30rem' }" [breakpoints]="{ '640px': '95vw' }">
      @if (hand(); as h) {
        <div class="stack">
          <p>{{ h.user.name }} still has <strong>{{ h.work.leads }}</strong> open lead(s), <strong>{{ h.work.followups }}</strong> open follow-up(s),
            <strong>{{ h.work.tasks }}</strong> open task(s) and <strong>{{ h.work.visits }}</strong> upcoming visit(s). Choose who takes them over before deactivating.</p>
          <label class="field"><span>Hand over to</span>
            <p-select [options]="handTargets()" [(ngModel)]="h.to" optionLabel="name" optionValue="id" placeholder="Choose a colleague" fluid appendTo="body" /></label>
          <small class="muted">Leads and follow-ups move to this person. Tasks move to them on projects where they are on the team; elsewhere the task is left unassigned for the PM to reassign.</small>
          <div class="row gap right">
            <p-button label="Cancel" severity="secondary" [text]="true" (onClick)="handDlg = false" />
            <p-button label="Hand over & deactivate" icon="pi pi-ban" severity="danger" [disabled]="!h.to" [loading]="busy()" (onClick)="deactivate(h.user, h.to)" />
          </div>
        </div>
      }
    </p-dialog>
  `,
})
export class UsersComponent implements OnInit {
  auth = inject(AuthService);
  private http = inject(HttpClient);
  private toast = inject(MessageService);
  private confirm = inject(ConfirmationService);
  users = signal<User[]>([]);
  summary = signal<Summary | null>(null);
  form = signal<any>(null);
  dialog = false;
  error = signal('');
  busy = signal(false);
  canEdit = computed(() => this.auth.can('users', 'rw'));
  hand = signal<any>(null);
  handDlg = false;
  handTargets = computed(() => this.users().filter((x) => x.kind === 'staff' && x.active !== false && x.id !== this.hand()?.user.id));

  ngOnInit() {
    this.load();
  }

  initials(name: string) {
    return name.split(/\s+/).filter((w) => /^[a-z0-9]/i.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  }

  isExternalRole(r: string) {
    return (this.auth.session()?.roles.external ?? []).includes(r);
  }

  roleOptions(f: any) {
    const roles = this.auth.session()?.roles;
    const isOwner = this.auth.user()?.role === 'owner';
    const opt = (r: string) => ({ label: this.auth.roleLabel(r), value: r, disabled: r === 'owner' && !isOwner });
    const groups = [];
    if (!f.id || f.kind === 'staff') groups.push({ label: 'Staff (counted)', items: (roles?.internal ?? []).map(opt) });
    if (!f.id || f.kind === 'external') groups.push({ label: 'Portal (free)', items: (roles?.external ?? []).map(opt) });
    return groups;
  }

  async load() {
    try {
      this.users.set(await firstValueFrom(this.http.get<User[]>('/api/users')));
      this.summary.set(await firstValueFrom(this.http.get<Summary>('/api/users/summary')));
    } catch (e) {
      this.toast.add({ severity: 'error', summary: 'Could not load users', detail: errorText(e) });
    }
  }

  openNew() {
    this.error.set('');
    this.form.set({ name: '', email: '', role: 'pm', phone: '', password: '', org: '', whatsapp_only: false });
    this.dialog = true;
  }

  edit(u: User) {
    this.error.set('');
    this.form.set({ ...u, password: '' });
    this.dialog = true;
  }

  async save() {
    const f = this.form();
    this.busy.set(true);
    this.error.set('');
    try {
      if (f.id) {
        const body: any = { name: f.name, phone: f.phone, role: f.role };
        if (f.password) body.password = f.password;
        await firstValueFrom(this.http.put(`/api/users/${f.id}`, body));
      } else {
        await firstValueFrom(this.http.post('/api/users', f));
      }
      this.dialog = false;
      this.toast.add({ severity: 'success', summary: f.id ? 'User updated' : 'User added', detail: f.name });
      await this.load();
      if (f.id === this.auth.user()?.id) await this.auth.refresh();
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }

  async toggle(u: User) {
    const activate = u.active === false;
    if (!activate && u.kind === 'staff') {
      try {
        const work = await firstValueFrom(this.http.get<any>(`/api/users/${u.id}/open-work`));
        if (work.leads || work.followups || work.tasks || work.visits) {
          this.hand.set({ user: u, work, to: null });
          this.handDlg = true;
          return;
        }
      } catch (e) {
        this.toast.add({ severity: 'error', summary: 'Could not check open work', detail: errorText(e) });
        return;
      }
    }
    this.confirm.confirm({
      header: activate ? 'Activate user' : 'Deactivate user',
      message: activate ? `Let ${u.name} sign in again?` : `${u.name} will be signed out immediately and cannot sign in.`,
      icon: activate ? 'pi pi-check-circle' : 'pi pi-exclamation-triangle',
      acceptButtonProps: { label: activate ? 'Activate' : 'Deactivate', severity: activate ? 'success' : 'danger' },
      rejectButtonProps: { label: 'Cancel', severity: 'secondary', text: true },
      accept: async () => {
        try {
          await firstValueFrom(this.http.put(`/api/users/${u.id}`, { active: activate }));
          this.toast.add({ severity: 'success', summary: activate ? 'User activated' : 'User deactivated', detail: u.name });
          await this.load();
        } catch (e) {
          this.toast.add({ severity: 'error', summary: 'Not changed', detail: errorText(e) });
        }
      },
    });
  }

  async deactivate(u: User, to: string) {
    this.busy.set(true);
    try {
      await firstValueFrom(this.http.put(`/api/users/${u.id}`, { active: false, handover_to: to }));
      this.handDlg = false;
      this.toast.add({ severity: 'success', summary: 'User deactivated', detail: `Open work handed over` });
      await this.load();
    } catch (e) {
      this.toast.add({ severity: 'error', summary: 'Not changed', detail: errorText(e) });
    } finally {
      this.busy.set(false);
    }
  }
}
