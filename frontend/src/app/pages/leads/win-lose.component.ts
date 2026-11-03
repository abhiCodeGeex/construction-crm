import { Component, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TextareaModule } from 'primeng/textarea';
import { Api } from '../../core/api.service';

/** Win (→ project with a chosen PM) or lose (reason from the company list + note). */
@Component({
  selector: 'app-win-lose',
  imports: [FormsModule, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, TextareaModule],
  template: `
    <p-dialog [header]="kind() === 'won' ? 'Mark as won' : 'Record a loss'" [modal]="true" [(visible)]="visible" [style]="{ width: '30rem' }">
      @if (kind() === 'won') {
        <form class="stack" (ngSubmit)="win()">
          <p class="muted small">A project is created for <strong>{{ lead?.contact_name }}</strong> with this lead's service, type, area, budget and referral. The salesperson joins as Sales.</p>
          <label class="field"><span>Project name</span><input pInputText name="n" [(ngModel)]="w.project_name" fluid /></label>
          <label class="field"><span>Project manager</span><p-select name="pm" [options]="pms" [(ngModel)]="w.pm_id" optionLabel="name" optionValue="id" placeholder="Choose" fluid appendTo="body" /></label>
          <div class="grid2">
            <label class="field"><span>Start date</span><input pInputText type="date" name="s" [(ngModel)]="w.start" fluid /></label>
            <label class="field"><span>Project value</span><p-inputnumber name="v" [(ngModel)]="w.value" [min]="0" fluid /></label>
          </div>
          <div class="row gap right"><p-button type="submit" label="Win & create project" icon="pi pi-trophy" severity="success" [loading]="busy()" /></div>
        </form>
      } @else {
        <form class="stack" (ngSubmit)="lose()">
          <label class="field"><span>Reason</span><p-select name="r" [options]="reasons" [(ngModel)]="l.reason" placeholder="Choose a reason" fluid appendTo="body" /></label>
          <label class="field"><span>Note</span><textarea pTextarea name="n" rows="3" [(ngModel)]="l.note" placeholder="e.g. went with a cheaper local builder" fluid></textarea></label>
          <div class="row gap right"><p-button type="submit" label="Record loss" icon="pi pi-times" severity="danger" [loading]="busy()" /></div>
        </form>
      }
    </p-dialog>
  `,
})
export class WinLoseComponent {
  private api = inject(Api);
  private router = inject(Router);
  done = output<void>();
  visible = false;
  kind = signal<'won' | 'lost'>('won');
  busy = signal(false);
  lead: any = null;
  pms: any[] = [];
  reasons: string[] = [];
  w: any = {};
  l: any = {};

  open(kind: 'won' | 'lost', lead: any, meta: any) {
    this.kind.set(kind);
    this.lead = lead;
    this.pms = meta?.project_managers ?? [];
    this.reasons = meta?.loss_reasons ?? [];
    this.w = { project_name: lead.title, pm_id: null, start: new Date().toISOString().slice(0, 10), value: lead.budget ?? null };
    this.l = { reason: null, note: '' };
    this.visible = true;
  }

  async win() {
    this.busy.set(true);
    try {
      const r = await this.api.post(`/leads/${this.lead.id}/win`, this.w, 'Won — project created');
      this.visible = false;
      this.done.emit();
      this.router.navigate(['/app/projects', r.project_id]);
    } finally {
      this.busy.set(false);
    }
  }

  async lose() {
    this.busy.set(true);
    try {
      await this.api.post(`/leads/${this.lead.id}/lose`, this.l, 'Loss recorded');
      this.visible = false;
      this.done.emit();
    } finally {
      this.busy.set(false);
    }
  }
}
