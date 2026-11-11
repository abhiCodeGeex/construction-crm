import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { TagModule } from 'primeng/tag';
import { Api } from '../../core/api.service';
import { ThreadComponent } from '../../shared/thread.component';

/** The project's portal threads (Phase G block 3): one per client / consultant / contractor on the team. */
@Component({
  selector: 'app-project-messages',
  imports: [DatePipe, TagModule, ThreadComponent],
  template: `
    <div class="pm">
      <nav class="people">
        @for (t of threads(); track t.contact_id) {
          <button type="button" class="person" [class.on]="open() === t.contact_id" (click)="open.set(t.contact_id)">
            <span><strong>{{ t.name }}</strong> <span class="small muted">{{ t.role }}</span>@if (!t.portal) { <span class="small muted"> · no portal login</span> }</span>
            @if (t.unread) { <p-tag [value]="t.unread + ''" severity="danger" /> }
            @if (t.last) { <span class="small muted last">{{ t.last.author }}: {{ t.last.text }} · {{ t.last.at | date: 'd MMM' }}</span> }
          </button>
        } @empty { <p class="muted small">No clients, consultants or contractors on the team yet.</p> }
      </nav>
      <div>@if (open()) { <app-thread [projectId]="projectId()" [contactId]="open()!" (changed)="reload()" /> }
        @else { <p class="muted">Choose a person to read and answer their messages.</p> }</div>
    </div>
  `,
  styles: `
    .pm { display: grid; grid-template-columns: 17rem minmax(0, 1fr); gap: 1rem; }
    @media (max-width: 760px) { .pm { grid-template-columns: 1fr; } }
    .people { display: flex; flex-direction: column; gap: .25rem; }
    .person { display: grid; gap: .1rem; text-align: left; background: none; border: 1px solid transparent; border-radius: 10px; padding: .5rem .6rem; cursor: pointer; color: inherit; font: inherit; }
    .person.on, .person:hover { border-color: var(--border); background: var(--surface); }
    .last { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  `,
})
export class ProjectMessagesComponent implements OnInit {
  projectId = input.required<string>();
  private api = inject(Api);
  threads = signal<any[]>([]);
  open = signal<string | null>(null);

  async ngOnInit() {
    await this.reload();
    const first = this.threads().find((t) => t.unread) ?? this.threads().find((t) => t.last);
    if (first) this.open.set(first.contact_id);
  }

  async reload() {
    this.threads.set(await this.api.get(`/projects/${this.projectId()}/threads`));
  }
}
