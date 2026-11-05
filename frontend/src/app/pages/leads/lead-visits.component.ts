import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, label } from '../../core/api.service';

const VISIT_SEVERITY: Record<string, 'info' | 'success' | 'warn' | 'danger' | 'secondary'> = {
  scheduled: 'info', confirmed: 'info', done: 'success', no_show: 'danger', cancelled: 'secondary',
};

/** Lead step 3 (C+2): site-visit appointments with report and cost, room-by-room and plot measurements. */
@Component({
  selector: 'app-lead-visits',
  imports: [FormsModule, DatePipe, DecimalPipe, ButtonModule, CardModule, CheckboxModule, DialogModule, InputNumberModule, InputTextModule,
    MultiSelectModule, SelectButtonModule, TableModule, TagModule, TextareaModule],
  template: `
    <div class="grid2 top">
      <p-card>
        <ng-template #title><div class="row-between"><span>Site visits & meetings</span>
          @if (editable()) { <p-button label="Book" icon="pi pi-calendar-plus" size="small" (onClick)="openBook()" /> }</div></ng-template>
        @for (v of visits(); track v.id) {
          <div class="gate">
            <div class="row-between">
              <strong><i [class]="v.kind === 'site_visit' ? 'pi pi-map-marker' : 'pi pi-users'"></i> {{ v.at | date: 'EEE d MMM y, h:mm a' }} · {{ v.duration_min }} min</strong>
              <span class="row gap">@if (v.missed) { <p-tag value="Missed?" severity="danger" /> } @if (v.report_late) { <p-tag value="Report late" severity="warn" /> }
                <p-tag [value]="label(v.status)" [severity]="sev[v.status]" /></span>
            </div>
            <small class="muted">{{ v.address }} · {{ staffNames(v) }}{{ v.notes ? ' · ' + v.notes : '' }}</small>
            @if (v.report) {
              <div class="small mt-xs"><strong>Found:</strong> {{ v.report.findings }}
                @if (v.report.risks) { <br /><strong>Risks:</strong> {{ v.report.risks }} }
                @if (v.report.recommendations) { <br /><strong>Recommend:</strong> {{ v.report.recommendations }} }
                @if (v.cost?.total) { <br /><strong>Cost:</strong> {{ v.cost.total | number: '1.0-0' }} }</div>
              @if (v.site_checklist?.length) {
                <ul class="changes">@for (c of v.site_checklist; track c.item) { <li>{{ c.item }}: <strong>{{ c.value === 'na' ? 'n/a' : c.value }}</strong>{{ c.note ? ' — ' + c.note : '' }}</li> }</ul>
              }
            }
            @if (editable()) {
              <div class="row gap wrap mt-xs">
                @if (v.status === 'scheduled') { <p-button label="Client confirmed" size="small" [text]="true" (onClick)="setStatus(v, 'confirmed')" /> }
                @if (v.status === 'scheduled' || v.status === 'confirmed') {
                  <p-button label="Done" icon="pi pi-check" size="small" [text]="true" severity="success" (onClick)="setStatus(v, 'done')" />
                  <p-button label="Reschedule" size="small" [text]="true" (onClick)="openReschedule(v)" />
                  <p-button label="No-show" size="small" [text]="true" severity="danger" (onClick)="openReason(v, 'no_show')" />
                  <p-button label="Cancel" size="small" [text]="true" severity="secondary" (onClick)="openReason(v, 'cancelled')" /> }
                @if (v.status === 'done') { <p-button [label]="v.report ? 'Edit report' : 'Write report'" icon="pi pi-file-edit" size="small" [text]="true" (onClick)="openReport(v)" /> }
              </div>
            }
          </div>
        } @empty { <p class="muted small">No visit booked yet. A site visit is booked here so the team is reminded and the report is kept.</p> }
      </p-card>

      <p-card>
        <ng-template #title><div class="row-between"><span>Measurements</span>
          @if (editable()) { <p-button label="Add room" icon="pi pi-plus" size="small" (onClick)="openRoom()" /> }</div></ng-template>
        @if (m(); as m) {
          <div class="row gap mb-xs"><small class="muted">Unit</small>
            <p-selectbutton [options]="unitOpts" [ngModel]="m.unit" (ngModelChange)="setUnit($event)" optionLabel="label" optionValue="value" [allowEmpty]="false" [disabled]="!editable() || m.rooms.length > 0" /></div>
          <p-table [value]="m.rooms" size="small">
            <ng-template #header><tr><th>Room</th><th class="right">L × W × H</th><th class="right">Floor</th><th class="right">Net wall</th><th></th></tr></ng-template>
            <ng-template #body let-r><tr>
              <td><strong>{{ r.name }}</strong>@if (r.openings?.length) { <br /><small class="muted">{{ r.openings.length }} opening(s) · {{ r.openings_area }} {{ r.area_unit }}</small> }</td>
              <td class="right">{{ r.length }} × {{ r.width }}{{ r.height ? ' × ' + r.height : '' }}</td>
              <td class="right">{{ r.floor_area }}</td><td class="right">{{ r.height ? r.net_wall_area : '—' }}</td>
              <td class="right nowrap">@if (editable()) { <p-button icon="pi pi-pencil" [text]="true" size="small" (onClick)="openRoom(r)" />
                <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="deleteRoom(r)" /> }</td></tr></ng-template>
            <ng-template #footer><tr><td>Total</td><td></td><td class="right">{{ m.totals.floor_area }}</td><td class="right">{{ m.totals.net_wall_area }}</td><td></td></tr></ng-template>
            <ng-template #emptymessage><tr><td colspan="5" class="muted center">No rooms measured</td></tr></ng-template>
          </p-table>
          <h4>Plot / site</h4>
          <div class="grid3">
            @for (f of plotFields; track f.key) {
              <label class="field"><span>{{ f.label }}</span><p-inputnumber [(ngModel)]="plot[f.key]" [min]="0" [disabled]="!editable()" fluid /></label>
            }
            <label class="field"><span>Soil</span><input pInputText [(ngModel)]="plot.soil" [disabled]="!editable()" fluid /></label>
            <label class="field"><span>Access</span><input pInputText [(ngModel)]="plot.access" [disabled]="!editable()" fluid /></label>
            <label class="field"><span>Notes</span><input pInputText [(ngModel)]="plot.notes" [disabled]="!editable()" fluid /></label>
          </div>
          @if (editable()) { <div class="row right mt-xs"><p-button label="Save plot" icon="pi pi-check" size="small" [outlined]="true" (onClick)="savePlot()" /></div> }
          @if (m.updated_by) { <small class="muted">Last measured by {{ m.updated_by }}, {{ m.updated_at | date: 'd MMM y' }}</small> }
        }
      </p-card>
    </div>

    <p-dialog header="Book a visit" [modal]="true" [(visible)]="bookDlg" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        <p-selectbutton [options]="kinds" [(ngModel)]="bf.kind" optionLabel="label" optionValue="value" [allowEmpty]="false" />
        <div class="grid2">
          <label class="field"><span>Date & time</span><input pInputText type="datetime-local" [(ngModel)]="bf.at" fluid /></label>
          <label class="field"><span>Duration (min)</span><p-inputnumber [(ngModel)]="bf.duration_min" [min]="15" fluid /></label>
        </div>
        <label class="field"><span>Who goes</span><p-multiselect [options]="staff()" [(ngModel)]="bf.staff_ids" optionLabel="name" optionValue="id" display="chip" fluid appendTo="body" /></label>
        <label class="field"><span>Address</span><input pInputText [(ngModel)]="bf.address" fluid /></label>
        <label class="field"><span>Notes</span><input pInputText [(ngModel)]="bf.notes" fluid /></label>
        <label class="check"><p-checkbox [(ngModel)]="bf.email_client" [binary]="true" /> Email the client a confirmation (when email is set up)</label>
        <div class="row right"><p-button label="Book" icon="pi pi-check" (onClick)="book()" [disabled]="!bf.at || !bf.staff_ids?.length" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Reschedule" [modal]="true" [(visible)]="reDlg" [style]="{ width: '28rem' }">
      <div class="stack">
        <label class="field"><span>New date & time</span><input pInputText type="datetime-local" [(ngModel)]="rf.at" fluid /></label>
        <label class="field"><span>Reason</span><input pInputText [(ngModel)]="rf.reason" fluid /></label>
        <label class="check"><p-checkbox [(ngModel)]="rf.email_client" [binary]="true" /> Email the client the new time</label>
        <div class="row right"><p-button label="Reschedule" (onClick)="reschedule()" [disabled]="!rf.at || !rf.reason?.trim()" /></div>
      </div>
    </p-dialog>

    <p-dialog [header]="rsn.status === 'no_show' ? 'Client did not show' : 'Cancel the visit'" [modal]="true" [(visible)]="reasonDlg" [style]="{ width: '26rem' }">
      <div class="stack">
        <label class="field"><span>Reason</span><input pInputText [(ngModel)]="rsn.reason" fluid /></label>
        <div class="row right"><p-button label="Save" (onClick)="setStatus(rsn.visit, rsn.status, rsn.reason)" [disabled]="!rsn.reason?.trim()" /></div>
      </div>
    </p-dialog>

    <p-dialog header="Visit report" [modal]="true" [(visible)]="repDlg" [style]="{ width: '44rem' }" [breakpoints]="{ '760px': '96vw' }">
      <div class="stack">
        <label class="field"><span>What we found (required)</span><textarea pTextarea rows="3" [(ngModel)]="rp.findings" fluid></textarea></label>
        <div class="grid2">
          <label class="field"><span>Risks</span><textarea pTextarea rows="2" [(ngModel)]="rp.risks" fluid></textarea></label>
          <label class="field"><span>Recommendations</span><textarea pTextarea rows="2" [(ngModel)]="rp.recommendations" fluid></textarea></label>
        </div>
        <strong>Site condition checklist</strong>
        @for (c of rp.site_checklist; track c.item) {
          <div class="row gap wrap"><span class="grow">{{ c.item }}</span>
            <p-selectbutton [options]="yn" [(ngModel)]="c.value" optionLabel="label" optionValue="value" />
            <input pInputText [(ngModel)]="c.note" placeholder="note" /></div>
        }
        <strong>What the visit cost</strong>
        <div class="grid3">
          <label class="field"><span>Travel</span><p-inputnumber [(ngModel)]="rp.cost.travel" [min]="0" fluid /></label>
          <label class="field"><span>Staff hours</span><p-inputnumber [(ngModel)]="rp.cost.staff_hours" [min]="0" [maxFractionDigits]="1" fluid /></label>
          <label class="field"><span>Rate per hour</span><p-inputnumber [(ngModel)]="rp.cost.hourly_rate" [min]="0" fluid /></label>
          <label class="field"><span>Other</span><p-inputnumber [(ngModel)]="rp.cost.other" [min]="0" fluid /></label>
        </div>
        <div class="row right"><p-button label="Save report" icon="pi pi-check" (onClick)="saveReport()" [disabled]="!rp.findings?.trim()" /></div>
      </div>
    </p-dialog>

    <p-dialog [header]="rm.id ? 'Edit room' : 'Measure a room'" [modal]="true" [(visible)]="roomDlg" [style]="{ width: '36rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        <label class="field"><span>Room</span><input pInputText [(ngModel)]="rm.name" placeholder="Living, Kitchen, Bedroom 1…" fluid /></label>
        <div class="grid3">
          <label class="field"><span>Length ({{ m()?.unit }})</span><p-inputnumber [(ngModel)]="rm.length" [min]="0" [maxFractionDigits]="2" fluid /></label>
          <label class="field"><span>Width ({{ m()?.unit }})</span><p-inputnumber [(ngModel)]="rm.width" [min]="0" [maxFractionDigits]="2" fluid /></label>
          <label class="field"><span>Height ({{ m()?.unit }})</span><p-inputnumber [(ngModel)]="rm.height" [min]="0" [maxFractionDigits]="2" fluid /></label>
        </div>
        <div class="row-between"><strong>Doors & windows</strong><p-button label="Add" icon="pi pi-plus" size="small" [text]="true" (onClick)="rm.openings.push({ kind: 'window', width: null, height: null, count: 1 })" /></div>
        @for (o of rm.openings; track $index; let i = $index) {
          <div class="row gap">
            <p-selectbutton [options]="openingKinds" [(ngModel)]="o.kind" optionLabel="label" optionValue="value" [allowEmpty]="false" />
            <p-inputnumber [(ngModel)]="o.width" placeholder="W" [min]="0" [maxFractionDigits]="2" [inputStyle]="{ width: '4.5rem' }" />
            <p-inputnumber [(ngModel)]="o.height" placeholder="H" [min]="0" [maxFractionDigits]="2" [inputStyle]="{ width: '4.5rem' }" />
            <p-inputnumber [(ngModel)]="o.count" [min]="1" [inputStyle]="{ width: '3.5rem' }" />
            <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="rm.openings.splice(i, 1)" />
          </div>
        }
        <label class="field"><span>Notes</span><input pInputText [(ngModel)]="rm.notes" fluid /></label>
        <div class="row right"><p-button label="Save room" icon="pi pi-check" (onClick)="saveRoom()" [disabled]="!rm.name?.trim() || !rm.length || !rm.width" /></div>
      </div>
    </p-dialog>
  `,
})
export class LeadVisitsComponent implements OnInit {
  lead = input.required<any>();
  staff = input<any[]>([]);
  changed = output<void>();
  private api = inject(Api);
  visits = signal<any[]>([]);
  m = signal<any>(null);
  checklist = signal<string[]>([]);
  editable = computed(() => this.lead()?.status === 'open' && this.lead()?.can_edit);
  sev = VISIT_SEVERITY;
  label = label;
  kinds = [{ label: 'Site visit', value: 'site_visit' }, { label: 'Meeting', value: 'meeting' }];
  unitOpts = [{ label: 'feet', value: 'ft' }, { label: 'metres', value: 'm' }];
  yn = [{ label: 'Yes', value: 'yes' }, { label: 'No', value: 'no' }, { label: 'n/a', value: 'na' }];
  openingKinds = [{ label: 'Door', value: 'door' }, { label: 'Window', value: 'window' }, { label: 'Opening', value: 'opening' }];
  plotFields = [{ key: 'area', label: 'Plot area' }, { key: 'frontage', label: 'Frontage' }, { key: 'depth', label: 'Depth' },
    { key: 'setback_front', label: 'Front setback' }, { key: 'setback_rear', label: 'Rear setback' }, { key: 'setback_sides', label: 'Side setbacks' },
    { key: 'floors', label: 'Floors allowed' }];
  plot: any = {};
  bookDlg = false; reDlg = false; reasonDlg = false; repDlg = false; roomDlg = false;
  bf: any = {}; rf: any = {}; rsn: any = {}; rp: any = { cost: {}, site_checklist: [] }; rm: any = { openings: [] };

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const id = this.lead().id;
    const v = await this.api.get(`/leads/${id}/visits`);
    this.visits.set(v.visits);
    this.checklist.set(v.site_checklist);
    const m = await this.api.get(`/leads/${id}/measurements`);
    this.m.set(m);
    this.plot = { ...(m.plot || {}) };
  }

  private async done() {
    await this.load();
    this.changed.emit();
  }

  staffNames(v: any) {
    return v.staff.map((s: any) => s.name).join(', ');
  }

  /** datetime-local is the user's own time; the API stores UTC. */
  private iso(local: string) {
    return new Date(local).toISOString();
  }

  private local(d: Date) {
    const p = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  openBook() {
    const t = new Date(Date.now() + 864e5);
    t.setHours(11, 0, 0, 0);
    this.bf = { kind: 'site_visit', at: this.local(t), duration_min: 60, staff_ids: this.lead().owner_id ? [this.lead().owner_id] : [],
      address: this.lead().location || '', notes: '', email_client: false };
    this.bookDlg = true;
  }

  async book() {
    await this.api.post(`/leads/${this.lead().id}/visits`, { ...this.bf, at: this.iso(this.bf.at) }, 'Visit booked');
    this.bookDlg = false;
    await this.done();
  }

  openReschedule(v: any) {
    this.rf = { visit: v, at: this.local(new Date(v.at)), reason: '', email_client: false };
    this.reDlg = true;
  }

  async reschedule() {
    await this.api.post(`/visits/${this.rf.visit.id}/reschedule`, { at: this.iso(this.rf.at), reason: this.rf.reason, email_client: this.rf.email_client }, 'Visit rescheduled');
    this.reDlg = false;
    await this.done();
  }

  openReason(v: any, status: string) {
    this.rsn = { visit: v, status, reason: '' };
    this.reasonDlg = true;
  }

  async setStatus(v: any, status: string, reason?: string) {
    await this.api.post(`/visits/${v.id}/status`, { status, reason }, `Visit ${label(status).toLowerCase()}`);
    this.reasonDlg = false;
    await this.done();
    if (status === 'done') this.openReport(this.visits().find((x) => x.id === v.id));
  }

  openReport(v: any) {
    const prev = Object.fromEntries((v.site_checklist ?? []).map((c: any) => [c.item, c]));
    this.rp = { visit: v, findings: v.report?.findings ?? '', risks: v.report?.risks ?? '', recommendations: v.report?.recommendations ?? '',
      cost: { travel: null, staff_hours: null, hourly_rate: null, other: null, ...(v.cost || {}) },
      site_checklist: this.checklist().map((item) => ({ item, value: prev[item]?.value ?? 'na', note: prev[item]?.note ?? '' })) };
    this.repDlg = true;
  }

  async saveReport() {
    const { visit, ...body } = this.rp;
    await this.api.put(`/visits/${visit.id}/report`, body, 'Report saved');
    this.repDlg = false;
    await this.done();
  }

  async setUnit(unit: string) {
    await this.api.put(`/leads/${this.lead().id}/measurements/unit`, { unit });
    await this.done();
  }

  openRoom(r?: any) {
    this.rm = r ? { ...r, openings: (r.openings ?? []).map((o: any) => ({ ...o })) } : { name: '', length: null, width: null, height: null, openings: [], notes: '' };
    this.roomDlg = true;
  }

  async saveRoom() {
    const { id, name, length, width, height, notes } = this.rm;
    const body = { name, length, width, height, notes, openings: this.rm.openings.filter((o: any) => o.width && o.height) };
    if (id) await this.api.put(`/leads/${this.lead().id}/rooms/${id}`, body, 'Room saved');
    else await this.api.post(`/leads/${this.lead().id}/rooms`, body, 'Room measured');
    this.roomDlg = false;
    await this.done();
  }

  async deleteRoom(r: any) {
    await this.api.del(`/leads/${this.lead().id}/rooms/${r.id}`, 'Room removed');
    await this.done();
  }

  async savePlot() {
    await this.api.put(`/leads/${this.lead().id}/plot`, this.plot, 'Plot saved');
    await this.done();
  }
}
