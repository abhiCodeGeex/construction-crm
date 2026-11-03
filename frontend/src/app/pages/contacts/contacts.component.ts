import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { IconFieldModule } from 'primeng/iconfield';
import { InputIconModule } from 'primeng/inputicon';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { RatingModule } from 'primeng/rating';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { Api, label } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

export const TYPE_LABEL: Record<string, string> = {
  client: 'Client', developer: 'Developer', architect: 'Architect', contractor: 'Contractor', subcontractor: 'Subcontractor',
  supplier: 'Supplier', consultant: 'Consultant', authority: 'Authority / Inspector',
};

@Component({
  selector: 'app-contacts',
  imports: [FormsModule, ButtonModule, CardModule, DialogModule, IconFieldModule, InputIconModule, InputTextModule, MultiSelectModule,
    RatingModule, SelectButtonModule, SelectModule, TableModule, TagModule],
  template: `
    <div class="page-head">
      <div><h1>Contacts</h1><p class="muted">Companies and people. Their role is set on each project, so the same firm can be a client on one job and a partner on another.</p></div>
      @if (auth.can('contacts', 'rw')) { <p-button label="New contact" icon="pi pi-plus" (onClick)="openNew()" /> }
    </div>

    @if (alerts().length) {
      <div class="alert-strip">
        <i class="pi pi-exclamation-triangle"></i>
        <strong>{{ alerts().length }} compliance document(s) need attention</strong>
        <span class="muted">
          @for (a of alerts().slice(0, 3); track a.document + a.contact_id) {
            · {{ a.contact }} — {{ a.document }} ({{ a.status === 'expired' ? 'expired ' + -a.days + ' d ago' : 'expires in ' + a.days + ' d' }})
          }
        </span>
        <p-button label="Show" size="small" [text]="true" (onClick)="alertOnly = true; load()" />
      </div>
    }

    <p-card>
      <div class="filters">
        <p-iconfield>
          <p-inputicon class="pi pi-search" />
          <input pInputText placeholder="Search name, email, phone, trade, city" [(ngModel)]="q" (keyup.enter)="load()" />
        </p-iconfield>
        <p-select [options]="typeOptions" [(ngModel)]="type" placeholder="All types" [showClear]="true" (onChange)="load()" />
        <p-selectbutton [options]="kindOptions" [(ngModel)]="kind" optionLabel="label" optionValue="value" (onChange)="load()" />
        <p-button [label]="alertOnly ? 'Showing alerts' : 'Compliance alerts'" icon="pi pi-filter" [outlined]="!alertOnly" severity="warn"
                  (onClick)="alertOnly = !alertOnly; load()" />
      </div>
      <p-table [value]="rows()" [rowHover]="true" [paginator]="rows().length > 20" [rows]="20" size="small" selectionMode="single"
               (onRowSelect)="open($event.data)" dataKey="id">
        <ng-template #header>
          <tr><th pSortableColumn="name">Name <p-sortIcon field="name" /></th><th>Types</th><th>Trade</th><th>Phone / email</th>
            <th pSortableColumn="rating">Rating <p-sortIcon field="rating" /></th><th>Compliance</th></tr>
        </ng-template>
        <ng-template #body let-c>
          <tr [pSelectableRow]="c" class="clickable">
            <td>
              <i [class]="c.kind === 'person' ? 'pi pi-user' : 'pi pi-building'" class="mr muted"></i><strong>{{ c.name }}</strong>
              @if (c.org_name) { <br /><small class="muted">{{ c.designation ? c.designation + ', ' : '' }}{{ c.org_name }}</small> }
            </td>
            <td>@for (t of c.types; track t) { <p-tag [value]="typeLabel[t]" severity="secondary" styleClass="mr-xs" /> }</td>
            <td>{{ c.trade_category || '—' }}</td>
            <td><small>{{ c.phone || '' }}<br />{{ c.email || '' }}</small></td>
            <td>@if (c.rating) { <p-rating [ngModel]="c.rating" [readonly]="true" /> } @else { <span class="muted">—</span> }</td>
            <td>
              @if (c.compliance_alert === 'expired') { <p-tag value="Expired" severity="danger" icon="pi pi-times-circle" /> }
              @else if (c.compliance_alert === 'expiring') { <p-tag value="Expiring" severity="warn" icon="pi pi-clock" /> }
              @else if (c.compliance?.length) { <p-tag value="OK" severity="success" /> }
              @else { <span class="muted">—</span> }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage><tr><td colspan="6" class="center muted">No contacts found</td></tr></ng-template>
      </p-table>
    </p-card>

    <p-dialog header="New contact" [modal]="true" [(visible)]="dialog" [style]="{ width: '34rem' }" [breakpoints]="{ '640px': '95vw' }">
      <form class="stack" (ngSubmit)="create()">
        <p-selectbutton name="kind" [options]="newKindOptions" [(ngModel)]="f.kind" optionLabel="label" optionValue="value" />
        <label class="field"><span>{{ f.kind === 'person' ? 'Full name' : 'Company name' }}</span><input pInputText name="name" [(ngModel)]="f.name" fluid /></label>
        @if (f.kind === 'person') {
          <div class="grid2">
            <label class="field"><span>Company</span>
              <p-select name="org" [options]="companies()" [(ngModel)]="f.org_id" optionLabel="name" optionValue="id" [filter]="true" [showClear]="true" fluid appendTo="body" /></label>
            <label class="field"><span>Designation</span><input pInputText name="des" [(ngModel)]="f.designation" fluid /></label>
          </div>
        }
        <label class="field"><span>Types</span>
          <p-multiselect name="types" [options]="typeOptions" [(ngModel)]="f.types" optionLabel="label" optionValue="value" display="chip" fluid appendTo="body" /></label>
        <div class="grid2">
          <label class="field"><span>Phone</span><input pInputText name="phone" [(ngModel)]="f.phone" fluid /></label>
          <label class="field"><span>Email</span><input pInputText name="email" [(ngModel)]="f.email" fluid /></label>
        </div>
        <div class="row gap right">
          <p-button label="Cancel" severity="secondary" [text]="true" (onClick)="dialog = false" />
          <p-button type="submit" label="Create & open" icon="pi pi-arrow-right" iconPos="right" [loading]="busy()" />
        </div>
      </form>
    </p-dialog>
  `,
})
export class ContactsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  private router = inject(Router);
  rows = signal<any[]>([]);
  alerts = signal<any[]>([]);
  all = signal<any[]>([]);
  companies = computed(() => this.all().filter((c) => c.kind === 'company'));
  busy = signal(false);
  typeLabel = TYPE_LABEL;
  typeOptions = Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }));
  kindOptions = [{ label: 'All', value: '' }, { label: 'Companies', value: 'company' }, { label: 'People', value: 'person' }];
  newKindOptions = this.kindOptions.slice(1);
  q = '';
  type: string | null = null;
  kind = '';
  alertOnly = false;
  dialog = false;
  f: any = {};
  label = label;

  async ngOnInit() {
    await this.load();
    this.alerts.set(await this.api.get('/compliance/alerts'));
  }

  async load() {
    const p = new URLSearchParams();
    if (this.q) p.set('q', this.q);
    if (this.type) p.set('type', this.type);
    if (this.kind) p.set('kind', this.kind);
    if (this.alertOnly) p.set('alert', '1');
    this.rows.set(await this.api.get(`/contacts?${p}`));
  }

  async openNew() {
    this.all.set(await this.api.get('/contacts'));
    this.f = { kind: 'company', name: '', types: [], phone: '', email: '', org_id: null, designation: '' };
    this.dialog = true;
  }

  async create() {
    this.busy.set(true);
    try {
      const c = await this.api.post('/contacts', this.f, 'Contact created');
      this.dialog = false;
      this.router.navigate(['/app/contacts', c.id]);
    } finally {
      this.busy.set(false);
    }
  }

  open(c: any) {
    this.router.navigate(['/app/contacts', c.id]);
  }
}
