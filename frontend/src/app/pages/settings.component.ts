import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';

@Component({
  selector: 'app-settings',
  imports: [FormsModule, DatePipe, ButtonModule, CardModule, InputTextModule, MessageModule, SelectButtonModule, TableModule, ToggleSwitchModule],
  template: `
    <div class="page-head">
      <div><h1>Company settings</h1><p class="muted">Modules, profile and the audit log of who changed what.</p></div>
      @if (canEdit()) { <p-button label="Save changes" icon="pi pi-check" [loading]="busy()" (onClick)="save()" /> }
    </div>
    @if (!canEdit()) { <p-message severity="info" icon="pi pi-eye" text="Read-only: only the owner can change company settings." styleClass="mb" /> }

    @if (c(); as c) {
      <div class="grid2 top">
        <p-card>
          <ng-template #title>Profile</ng-template>
          <div class="stack">
            <label class="field"><span>Company name</span><input pInputText [(ngModel)]="c.name" [disabled]="!canEdit()" fluid /></label>
            <div class="grid2">
              <label class="field"><span>City</span><input pInputText [(ngModel)]="c.city" [disabled]="!canEdit()" fluid /></label>
              <label class="field"><span>GSTIN</span><input pInputText [(ngModel)]="c.gstin" [disabled]="!canEdit()" fluid /></label>
            </div>
            <label class="check"><p-toggleswitch [(ngModel)]="c.allow_support_login" [disabled]="!canEdit()" />
              Allow BuildSuite support to sign in to help (always logged)</label>
          </div>
        </p-card>
        <p-card>
          <ng-template #title>Modules</ng-template>
          <p class="muted small">Your {{ auth.session()?.limits?.plan }} plan includes {{ auth.session()?.limits?.modules }} module(s).</p>
          <p-selectbutton [options]="modules" [(ngModel)]="c.modules" [multiple]="true" optionLabel="label" optionValue="value" [disabled]="!canEdit()" />
        </p-card>
      </div>
    }

    <p-card styleClass="mt">
      <ng-template #title>Audit log</ng-template>
      <p-table [value]="audit()" size="small" [paginator]="true" [rows]="10">
        <ng-template #header><tr><th>When</th><th>Who</th><th>Action</th><th>What</th><th>Changes</th></tr></ng-template>
        <ng-template #body let-a>
          <tr>
            <td class="nowrap"><small>{{ a.at | date: 'short' }}</small></td>
            <td>{{ a.user_name || '—' }}</td>
            <td class="cap">{{ a.action }}</td>
            <td>{{ a.collection }} @if (a.note) { <small class="muted">· {{ a.note }}</small> }</td>
            <td><small class="muted">{{ changed(a) }}</small></td>
          </tr>
        </ng-template>
      </p-table>
    </p-card>
  `,
})
export class SettingsComponent implements OnInit {
  auth = inject(AuthService);
  private http = inject(HttpClient);
  private toast = inject(MessageService);
  c = signal<any>(null);
  audit = signal<any[]>([]);
  busy = signal(false);
  canEdit = computed(() => this.auth.can('settings', 'rw'));
  modules = [
    { value: 'architecture', label: 'Architecture' },
    { value: 'construction', label: 'Construction' },
    { value: 'interior', label: 'Interior design' },
  ];

  async ngOnInit() {
    this.c.set(await firstValueFrom(this.http.get('/api/company')));
    this.audit.set(await firstValueFrom(this.http.get<any[]>('/api/audit')));
  }

  changed(a: any) {
    return a.changes ? Object.keys(a.changes).filter((k) => k !== 'password').join(', ') : '';
  }

  async save() {
    const c = this.c();
    this.busy.set(true);
    try {
      this.c.set(await firstValueFrom(this.http.put('/api/company', {
        name: c.name, city: c.city, gstin: c.gstin, modules: c.modules, allow_support_login: c.allow_support_login,
      })));
      await this.auth.refresh();
      this.audit.set(await firstValueFrom(this.http.get<any[]>('/api/audit')));
      this.toast.add({ severity: 'success', summary: 'Settings saved' });
    } catch (e) {
      this.toast.add({ severity: 'error', summary: 'Not saved', detail: errorText(e) });
    } finally {
      this.busy.set(false);
    }
  }
}
