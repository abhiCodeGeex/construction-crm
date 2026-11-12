import { Component, OnInit, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { Api, money } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

/** Contract billing (Phase I block 2): payment schedule or progress claims, retention held and released. */
@Component({
  selector: 'app-project-billing',
  imports: [FormsModule, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectButtonModule, TableModule],
  template: `
    @if (b(); as b) {
      <div class="billing">
        <div class="row-between wrap gap">
          <div>
            <strong>Billing:</strong> {{ b.basis === 'progress' ? 'progress claims (% complete per stage)' : 'payment schedule (milestones)' }}
            @if (b.retention_pct) { · retention {{ b.retention_pct }}% · defects period {{ b.defects_days }} days
              @if (b.handover_date) { <span class="muted small">(handover {{ b.handover_date }}, ends {{ b.defects_end }})</span> } }
          </div>
          @if (b.can_write) { <p-button label="Billing terms" icon="pi pi-sliders-h" size="small" [text]="true" (onClick)="openTerms()" /> }
        </div>
        @if (b.retention.held > 0) {
          <div class="row-between wrap gap mt-xs">
            <span class="small">Retention held {{ fmt(b.retention.held) }} · released {{ fmt(b.retention.released) }}
              @if (b.retention.draft) { · in draft {{ fmt(b.retention.draft) }} } · <strong>still held {{ fmt(b.retention.balance) }}</strong></span>
            @if (b.can_write && b.retention.balance > 0) { <p-button label="Release retention" size="small" [outlined]="true" (onClick)="openRelease()" /> }
          </div>
        }
        @if (b.basis === 'progress' && b.values) {
          <p-table [value]="b.values" styleClass="p-datatable-sm mt-xs">
            <ng-template #header><tr><th>Stage</th><th class="num">Value</th><th class="num">Claimed</th><th class="num">Progress now</th></tr></ng-template>
            <ng-template #body let-v><tr><td>{{ v.stage }}</td><td class="num">{{ fmt(v.value) }}</td>
              <td class="num">{{ v.claimed_pct }}% <span class="small muted">{{ fmt(v.claimed) }}</span></td><td class="num">{{ v.progress }}%</td></tr></ng-template>
          </p-table>
          @if (b.can_write) { <div class="row right mt-xs"><p-button label="New progress claim" icon="pi pi-plus" size="small" (onClick)="openClaim()" /></div> }
        }
      </div>
    }

    <p-dialog header="Billing terms" [modal]="true" [(visible)]="termsDlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        <p-selectbutton [options]="bases" [(ngModel)]="tf.basis" optionLabel="label" optionValue="value" [allowEmpty]="false" [disabled]="b()?.has_invoices" />
        @if (b()?.has_invoices) { <p class="small muted m0">The contract has invoices: the basis and retention % are fixed.</p> }
        <div class="grid2">
          <label class="field"><span>Retention %</span><p-inputnumber [(ngModel)]="tf.retention_pct" [min]="0" [max]="20" [maxFractionDigits]="2" [disabled]="b()?.has_invoices" fluid /></label>
          <label class="field"><span>Defects period (days)</span><p-inputnumber [(ngModel)]="tf.defects_days" [min]="0" [max]="1830" fluid /></label>
        </div>
        <label class="field"><span>Handover date</span><input pInputText type="date" [(ngModel)]="tf.handover_date" fluid />
          <small class="muted">The defects period runs from here; Accounts and the PM are reminded to release the retention when it ends.</small></label>
        <div class="row right"><p-button label="Save" icon="pi pi-check" (onClick)="saveTerms()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Progress claim" [modal]="true" [(visible)]="claimDlg" [style]="{ width: '40rem' }" [breakpoints]="{ '700px': '98vw' }">
      <div class="stack">
        <p class="small muted m0">Enter each stage's total % complete; the claim bills the increase since the last claim.</p>
        @for (r of claimRows; track r.stage_id) {
          <div class="claim-row"><span>{{ r.stage }} <span class="small muted">claimed {{ r.claimed_pct }}% · {{ fmt(r.value) }}</span></span>
            <p-inputnumber [(ngModel)]="r.pct" [min]="r.claimed_pct" [max]="100" suffix="%" [inputStyle]="{ width: '100%' }" /></div>
        }
        <div class="row-between"><strong>This claim {{ fmt(claimTotal()) }}</strong>
          <p-button label="Draft the claim" icon="pi pi-check" [disabled]="!claimTotal()" (onClick)="saveClaim()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Release retention" [modal]="true" [(visible)]="relDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <p class="m0">Held now: {{ fmt(b()?.retention?.balance) }}</p>
        <label class="field"><span>Amount</span><p-inputnumber [(ngModel)]="relAmount" [min]="0" [max]="b()?.retention?.balance" fluid /></label>
        <label class="field"><span>Description</span><input pInputText [(ngModel)]="relReason" fluid /></label>
        <div class="row right"><p-button label="Draft the release invoice" [disabled]="!relAmount" (onClick)="release()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .billing { border: 1px solid var(--border); border-radius: var(--radius); padding: .75rem 1rem; background: var(--surface); margin-bottom: 1rem; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .claim-row { display: grid; grid-template-columns: minmax(0, 1fr) 8rem; gap: .5rem; align-items: center; }
  `,
})
export class ProjectBillingComponent implements OnInit {
  contractId = input.required<string>();
  changed = output<void>();
  private api = inject(Api);
  private auth = inject(AuthService);
  b = signal<any>(null);
  termsDlg = false; claimDlg = false; relDlg = false;
  tf: any = {};
  claimRows: any[] = [];
  relAmount: number | null = null;
  relReason = 'Retention release';
  bases = [{ label: 'Payment schedule', value: 'schedule' }, { label: 'Progress claims', value: 'progress' }];

  async ngOnInit() {
    await this.load();
  }

  async load() {
    this.b.set(await this.api.get(`/contracts/${this.contractId()}/billing`));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  openTerms() {
    const b = this.b();
    this.tf = { basis: b.basis, retention_pct: b.retention_pct, defects_days: b.defects_days, handover_date: b.handover_date };
    this.termsDlg = true;
  }

  async saveTerms() {
    const body: any = { defects_days: this.tf.defects_days, handover_date: this.tf.handover_date || null };
    if (!this.b().has_invoices) Object.assign(body, { basis: this.tf.basis, retention_pct: this.tf.retention_pct });
    this.b.set(await this.api.put(`/contracts/${this.contractId()}/billing`, body, 'Billing terms saved'));
    this.termsDlg = false;
    this.changed.emit();
  }

  openClaim() {
    this.claimRows = (this.b().values ?? []).map((v: any) => ({ ...v, pct: Math.max(v.claimed_pct, v.progress) }));
    this.claimDlg = true;
  }

  claimTotal() {
    return this.claimRows.reduce((a, r) => a + (r.value * Math.max(0, (r.pct ?? 0) - r.claimed_pct)) / 100, 0);
  }

  async saveClaim() {
    const lines = this.claimRows.filter((r) => (r.pct ?? 0) > r.claimed_pct).map((r) => ({ stage_id: r.stage_id, pct: r.pct }));
    await this.api.post(`/contracts/${this.contractId()}/claims`, { lines }, 'Claim drafted');
    this.claimDlg = false;
    await this.load();
    this.changed.emit();
  }

  openRelease() {
    this.relAmount = this.b().retention.balance;
    this.relReason = 'Retention release';
    this.relDlg = true;
  }

  async release() {
    await this.api.post(`/contracts/${this.contractId()}/retention/release`, { amount: this.relAmount, reason: this.relReason }, 'Release drafted');
    this.relDlg = false;
    await this.load();
    this.changed.emit();
  }
}
