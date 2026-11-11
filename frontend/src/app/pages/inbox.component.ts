import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { TagModule } from 'primeng/tag';
import { Api } from '../core/api.service';
import { ThreadComponent } from '../shared/thread.component';

/** Inbox (Phase G block 3): every portal thread of the projects you are on, unread first. */
@Component({
  selector: 'app-inbox',
  imports: [DatePipe, RouterLink, TagModule, ThreadComponent],
  template: `
    <div class="page-head"><div><h1>Inbox</h1><p class="muted">Messages from clients, consultants and contractors in the portal.</p></div></div>
    <div class="ib">
      <nav class="list">
        @for (t of threads(); track t.project_id + t.contact_id) {
          <button type="button" class="item" [class.on]="isOpen(t)" (click)="select(t)">
            <span class="row-between"><strong>{{ t.name }}</strong>@if (t.unread) { <p-tag [value]="t.unread + ''" severity="danger" /> }</span>
            <span class="small muted">{{ t.project }} · {{ t.role }}</span>
            <span class="small last">{{ t.last.author }}: {{ t.last.text }}</span>
            <span class="small muted">{{ t.last.at | date: 'd MMM, h:mm a' }}</span>
          </button>
        } @empty { <p class="muted">No messages yet.</p> }
      </nav>
      <div>@if (sel(); as s) {
          <div class="row-between mb"><strong>{{ s.name }} · <a [routerLink]="['/app/projects', s.project_id]" [queryParams]="{ tab: 'messages' }">{{ s.project }}</a></strong></div>
          <app-thread [projectId]="s.project_id" [contactId]="s.contact_id" (changed)="refresh()" />
        } @else { <p class="muted">Choose a conversation.</p> }</div>
    </div>
  `,
  styles: `
    .ib { display: grid; grid-template-columns: 20rem minmax(0, 1fr); gap: 1rem; }
    @media (max-width: 800px) { .ib { grid-template-columns: 1fr; } }
    .list { display: flex; flex-direction: column; gap: .3rem; }
    .item { display: grid; gap: .1rem; text-align: left; background: none; border: 1px solid var(--border); border-radius: 10px; padding: .55rem .7rem; cursor: pointer; color: inherit; font: inherit; }
    .item.on, .item:hover { background: var(--surface); border-color: var(--p-primary-color, #6366f1); }
    .last { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  `,
})
export class InboxComponent implements OnInit {
  project = input<string>();
  contact = input<string>();
  private api = inject(Api);
  threads = signal<any[]>([]);
  sel = signal<any>(null);

  async ngOnInit() {
    await this.refresh();
    const want = this.threads().find((t) => t.project_id === this.project() && t.contact_id === this.contact());
    this.sel.set(want ?? this.threads()[0] ?? null);
  }

  async refresh() {
    this.threads.set((await this.api.get('/inbox')).threads);
  }

  isOpen(t: any) {
    return this.sel()?.project_id === t.project_id && this.sel()?.contact_id === t.contact_id;
  }

  select(t: any) {
    this.sel.set(t);
  }
}
