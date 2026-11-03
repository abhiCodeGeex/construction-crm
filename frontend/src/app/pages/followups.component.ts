import { Component, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { CHANNEL_ICON, FollowupDialogComponent } from '../shared/followup-dialog.component';

@Component({
  selector: 'app-followups',
  imports: [FormsModule, DatePipe, RouterLink, ButtonModule, CardModule, SelectButtonModule, SelectModule, TableModule, TabsModule, TagModule,
    FollowupDialogComponent],
  template: `
    <div class="page-head">
      <div><h1>Follow-ups</h1><p class="muted">Chasing is where firms lose the most time and money. Overdue items are highlighted.</p></div>
      <div class="row gap">
        @if (meta()?.can_view_all) {
          <p-select [options]="people()" [(ngModel)]="who" optionLabel="name" optionValue="id" (onChange)="load()" />
        }
        @if (auth.can('followups', 'rw')) { <p-button label="New follow-up" icon="pi pi-plus" (onClick)="fd().open()" /> }
      </div>
    </div>

    <p-tabs value="today">
      <p-tablist><p-tab value="today"><i class="pi pi-sun mr"></i>Today</p-tab><p-tab value="all"><i class="pi pi-list mr"></i>All</p-tab></p-tablist>
      <p-tabpanels>
        <p-tabpanel value="today">
          @if (today(); as d) {
            <div class="today-grid">
              @for (b of buckets; track b.key) {
                <p-card [styleClass]="'bucket ' + b.key">
                  <ng-template #title><div class="row-between"><span><i [class]="b.icon" class="mr"></i>{{ b.label }}</span><span class="count">{{ d[b.key].length }}</span></div></ng-template>
                  @for (f of d[b.key]; track f.id) {
                    <div class="fu-row">
                      <i [class]="icon[f.channel] || 'pi pi-bell'"></i>
                      <div class="grow">
                        <strong>{{ f.title }}</strong>
                        <div class="small muted">
                          @if (f.related) { <a [routerLink]="link(f)">{{ f.related.label }}</a> · }
                          {{ f.due | date: 'd MMM' }} @if (who !== auth.user()?.id) { · {{ f.owner_name }} }
                        </div>
                      </div>
                      <p-tag [value]="f.priority" [severity]="f.priority === 'high' ? 'danger' : f.priority === 'low' ? 'secondary' : 'info'" />
                      @if (canAct(f)) { <p-button icon="pi pi-check" [rounded]="true" [text]="true" severity="success" (onClick)="fd().openDone(f)" ariaLabel="Done" />
                        <p-button icon="pi pi-pencil" [rounded]="true" [text]="true" (onClick)="fd().open(undefined, f)" ariaLabel="Edit" /> }
                    </div>
                  } @empty { <p class="muted small">{{ b.empty }}</p> }
                </p-card>
              }
            </div>
          }
        </p-tabpanel>
        <p-tabpanel value="all">
          <div class="filters"><p-selectbutton [options]="statuses" [(ngModel)]="status" optionLabel="label" optionValue="value" (onChange)="loadAll()" /></div>
          <p-table [value]="all()" size="small" [paginator]="all().length > 20" [rows]="20">
            <ng-template #header><tr><th>Follow-up</th><th>Related</th><th>Owner</th><th>Due</th><th>Priority</th><th>Status</th><th></th></tr></ng-template>
            <ng-template #body let-f>
              <tr [class.overdue-row]="f.overdue">
                <td><i [class]="icon[f.channel] || 'pi pi-bell'" class="mr muted"></i>{{ f.title }}@if (f.outcome) { <br /><small class="muted">{{ f.outcome }}</small> }</td>
                <td>@if (f.related) { <a [routerLink]="link(f)">{{ f.related.label }}</a> } @else { — }</td>
                <td>{{ f.owner_name }}</td>
                <td [class.c-bad]="f.overdue">{{ f.due | date: 'd MMM y' }}</td>
                <td><p-tag [value]="f.priority" [severity]="f.priority === 'high' ? 'danger' : f.priority === 'low' ? 'secondary' : 'info'" /></td>
                <td><p-tag [value]="f.overdue ? 'overdue' : f.status" [severity]="f.overdue ? 'danger' : f.status === 'done' ? 'success' : f.status === 'open' ? 'warn' : 'secondary'" /></td>
                <td class="right nowrap">@if (canAct(f)) {
                  @if (f.status === 'open') { <p-button icon="pi pi-check" [text]="true" [rounded]="true" severity="success" (onClick)="fd().openDone(f)" />
                    <p-button icon="pi pi-times" [text]="true" [rounded]="true" severity="secondary" (onClick)="cancel(f)" ariaLabel="Cancel" /> }
                  @else { <p-button label="Reopen" size="small" [text]="true" (onClick)="reopen(f)" /> } }</td>
              </tr>
            </ng-template>
            <ng-template #emptymessage><tr><td colspan="7" class="center muted">Nothing here</td></tr></ng-template>
          </p-table>
        </p-tabpanel>
      </p-tabpanels>
    </p-tabs>
    <app-followup-dialog (saved)="load()" />
  `,
})
export class FollowupsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  fd = viewChild.required(FollowupDialogComponent);
  meta = signal<any>(null);
  today = signal<any>(null);
  all = signal<any[]>([]);
  people = computed(() => [{ id: 'all', name: 'Everyone' }, ...(this.meta()?.staff ?? [])]);
  icon = CHANNEL_ICON;
  who = '';
  status = 'open';
  statuses = [{ label: 'Open', value: 'open' }, { label: 'Done', value: 'done' }, { label: 'Cancelled', value: 'cancelled' }, { label: 'All', value: '' }];
  buckets = [
    { key: 'overdue', label: 'Overdue', icon: 'pi pi-exclamation-triangle', empty: 'Nothing overdue — well done.' },
    { key: 'today', label: 'Due today', icon: 'pi pi-sun', empty: 'Nothing due today.' },
    { key: 'upcoming', label: 'Next 7 days', icon: 'pi pi-calendar', empty: 'Nothing scheduled this week.' },
  ];

  async ngOnInit() {
    this.meta.set(await this.api.get('/followups/meta'));
    this.who = this.auth.user()!.id;
    await this.load();
  }

  async load() {
    const q = this.who === 'all' ? '?all=1' : this.who !== this.auth.user()?.id ? `?owner_id=${this.who}` : '';
    this.today.set(await this.api.get(`/followups/today${q}`));
    await this.loadAll();
  }

  async loadAll() {
    const p = new URLSearchParams();
    if (this.status) p.set('status', this.status);
    if (this.who && this.who !== 'all' && this.meta()?.can_view_all) p.set('owner_id', this.who);
    this.all.set(await this.api.get(`/followups?${p}`));
  }

  canAct(f: any) {
    const me = this.auth.user()?.id;
    return this.auth.can('followups', 'rw') && (this.meta()?.can_view_all || f.owner_id === me || f.created_by === me);
  }

  link(f: any) {
    const r = f.related;
    return r.type === 'lead' ? ['/app/leads', r.id] : r.type === 'project' ? ['/app/projects', r.id] : ['/app/contacts', r.id];
  }

  async cancel(f: any) {
    await this.api.post(`/followups/${f.id}/cancel`, {}, 'Cancelled');
    await this.load();
  }

  async reopen(f: any) {
    await this.api.post(`/followups/${f.id}/reopen`, {}, 'Reopened');
    await this.load();
  }
}
