import { Component, inject, input, model, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TextareaModule } from 'primeng/textarea';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';

export const CHANNEL_LABEL: Record<string, string> = { call: 'Call', email: 'Email', whatsapp: 'WhatsApp', sms: 'SMS', meeting: 'Meeting',
  site_visit: 'Site visit', other: 'Other', note: 'Note' };
export const CHANNEL_ICON: Record<string, string> = { call: 'pi pi-phone', email: 'pi pi-envelope', whatsapp: 'pi pi-whatsapp', sms: 'pi pi-mobile',
  meeting: 'pi pi-users', site_visit: 'pi pi-map-marker', other: 'pi pi-circle', note: 'pi pi-pencil', stage: 'pi pi-arrow-right',
  won: 'pi pi-trophy', lost: 'pi pi-times-circle', reopened: 'pi pi-replay' };

/** New / edit follow-up (§16: owner, due date, priority), and "mark done" with outcome + optional next follow-up. */
@Component({
  selector: 'app-followup-dialog',
  imports: [FormsModule, ButtonModule, DialogModule, InputTextModule, SelectButtonModule, SelectModule, TextareaModule],
  template: `
    <p-dialog [header]="mode() === 'done' ? 'Complete follow-up' : f.id ? 'Edit follow-up' : 'New follow-up'" [modal]="true"
              [(visible)]="visible" [style]="{ width: '32rem' }" [breakpoints]="{ '640px': '95vw' }">
      @if (mode() === 'done') {
        <form class="stack" (ngSubmit)="complete()">
          <p class="muted">{{ f.title }}</p>
          <label class="field"><span>Outcome — what happened?</span><textarea pTextarea name="o" rows="3" [(ngModel)]="d.outcome" fluid></textarea></label>
          <div class="grid2">
            <label class="field"><span>Next follow-up on <small class="muted">(optional)</small></span><input pInputText type="date" name="nd" [(ngModel)]="d.next_due" fluid /></label>
            <label class="field"><span>Next note</span><input pInputText name="nn" [(ngModel)]="d.next_notes" fluid /></label>
          </div>
          <div class="row gap right"><p-button type="submit" label="Mark done" icon="pi pi-check" [loading]="busy()" /></div>
        </form>
      } @else {
        <form class="stack" (ngSubmit)="save()">
          <label class="field"><span>Follow-up</span><input pInputText name="t" [(ngModel)]="f.title" placeholder="e.g. Call to confirm site visit" fluid /></label>
          <div class="grid2">
            <label class="field"><span>Due date</span><input pInputText type="date" name="due" [(ngModel)]="f.due" fluid /></label>
            <label class="field"><span>Channel</span><p-select name="c" [options]="channels" [(ngModel)]="f.channel" optionLabel="label" optionValue="value" [showClear]="true" fluid appendTo="body" /></label>
          </div>
          <div class="field"><span>Priority</span><p-selectbutton name="p" [options]="priorities" [(ngModel)]="f.priority" optionLabel="label" optionValue="value" /></div>
          <label class="field"><span>Owner</span><p-select name="o" [options]="staff()" [(ngModel)]="f.owner_id" optionLabel="name" optionValue="id" [filter]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Notes</span><textarea pTextarea name="n" rows="2" [(ngModel)]="f.notes" fluid></textarea></label>
          @if (f.related?.label) { <small class="muted"><i class="pi pi-link"></i> {{ f.related.type }}: {{ f.related.label }}</small> }
          <div class="row gap right"><p-button type="submit" label="Save" icon="pi pi-check" [loading]="busy()" /></div>
        </form>
      }
    </p-dialog>
  `,
})
export class FollowupDialogComponent {
  private api = inject(Api);
  private auth = inject(AuthService);
  visible = false;
  mode = signal<'edit' | 'done'>('edit');
  busy = signal(false);
  staff = signal<any[]>([]);
  saved = output<void>();
  f: any = {};
  d: any = {};
  channels = Object.entries(CHANNEL_LABEL).filter(([k]) => k !== 'note').map(([value, label]) => ({ value, label }));
  priorities = [{ label: 'Low', value: 'low' }, { label: 'Normal', value: 'normal' }, { label: 'High', value: 'high' }];

  private async loadStaff() {
    if (!this.staff().length) this.staff.set((await this.api.get('/followups/meta')).staff);
  }

  async open(related?: { type: string; id: string; label?: string }, existing?: any) {
    await this.loadStaff();
    this.mode.set('edit');
    this.f = existing ? { ...existing } : { title: '', due: new Date().toISOString().slice(0, 10), channel: 'call', priority: 'normal',
      owner_id: this.auth.user()?.id, notes: '', related: related ?? null };
    this.visible = true;
  }

  openDone(f: any) {
    this.mode.set('done');
    this.f = f;
    this.d = { outcome: '', next_due: null, next_notes: '' };
    this.visible = true;
  }

  async save() {
    this.busy.set(true);
    try {
      const body = { title: this.f.title, due: this.f.due, channel: this.f.channel, priority: this.f.priority, owner_id: this.f.owner_id,
        notes: this.f.notes, ...(this.f.id ? {} : { related: this.f.related?.id ? { type: this.f.related.type, id: this.f.related.id } : null }) };
      if (this.f.id) await this.api.put(`/followups/${this.f.id}`, body, 'Follow-up saved');
      else await this.api.post('/followups', body, 'Follow-up added');
      this.visible = false;
      this.saved.emit();
    } finally {
      this.busy.set(false);
    }
  }

  async complete() {
    this.busy.set(true);
    try {
      await this.api.post(`/followups/${this.f.id}/done`, this.d, 'Follow-up completed');
      this.visible = false;
      this.saved.emit();
    } finally {
      this.busy.set(false);
    }
  }
}
