import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { Api, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Product catalogue (Phase I block 4): the rate library's products with photos, SKU, size, finish, supplier, lead time,
 *  trade price and client price (from the markup rules unless set). *Add from a link* reads a supplier's product page. */
@Component({
  selector: 'app-products',
  imports: [FormsModule, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectModule],
  template: `
    <div class="row gap wrap mb">
      <input pInputText [(ngModel)]="q" (keyup.enter)="load()" placeholder="Search name, brand, SKU, finish, supplier" class="grow" />
      <p-select [options]="cats()" [(ngModel)]="cat" [showClear]="true" placeholder="Any category" (onChange)="load()" />
      @if (canWrite()) {
        <p-button label="Add from a link" icon="pi pi-link" size="small" [outlined]="true" (onClick)="clipDlg = true; clipUrl = ''" />
        <p-button label="New product" icon="pi pi-plus" size="small" (onClick)="open()" />
      }
    </div>
    <div class="cards">
      @for (p of rows(); track p.id) {
        <div class="prod" (click)="canWrite() && open(p)" [class.click]="canWrite()">
          <div class="img">@if (p.photo_urls?.[0] || p.image_url) { <img [src]="p.photo_urls?.[0] || p.image_url" [alt]="p.name" /> } @else { <i class="pi pi-image"></i> }</div>
          <strong>{{ p.name }}</strong>
          <span class="small muted">@if (p.brand) { {{ p.brand }} · } @if (p.sku) { {{ p.sku }} · } {{ p.category || 'Uncategorised' }}</span>
          @if (p.dimensions || p.finish) { <span class="small">{{ p.dimensions }}@if (p.dimensions && p.finish) { · } {{ p.finish }}</span> }
          <span class="small">@if (p.supplier_name) { {{ p.supplier_name }} · } @if (p.lead_days) { {{ p.lead_days }} days lead }</span>
          <span class="row-between"><strong>{{ fmt(p.price) }}<span class="small muted">/{{ p.unit }}</span></strong>
            @if (p.rate !== undefined) { <span class="small muted">trade {{ fmt(p.rate) }}</span> }</span>
        </div>
      } @empty { <p class="muted">No products yet. Add one, or add one from a supplier's web page.</p> }
    </div>

    <p-dialog header="Add from a supplier's page" [modal]="true" [(visible)]="clipDlg" [style]="{ width: '32rem' }">
      <div class="stack">
        <label class="field"><span>Product page link</span><input pInputText [(ngModel)]="clipUrl" placeholder="https://…" fluid /></label>
        <p class="small muted m0">The page's name, photo, price and brand are read for you to check before saving.</p>
        <div class="row right"><p-button label="Read the page" [disabled]="!clipUrl.startsWith('http') || busy" [loading]="busy" (onClick)="clip()" /></div>
      </div>
    </p-dialog>

    <p-dialog [header]="f.id ? 'Edit product' : 'New product'" [modal]="true" [(visible)]="dlg" [style]="{ width: '42rem' }" [breakpoints]="{ '700px': '100vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field req"><span>Name</span><input pInputText [(ngModel)]="f.name" fluid /></label>
          <label class="field"><span>Category</span><p-select [options]="cats()" [(ngModel)]="f.category" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Brand</span><input pInputText [(ngModel)]="f.brand" fluid /></label>
          <label class="field"><span>SKU / code</span><input pInputText [(ngModel)]="f.sku" fluid /></label>
          <label class="field"><span>Dimensions</span><input pInputText [(ngModel)]="f.dimensions" placeholder="W x D x H" fluid /></label>
          <label class="field"><span>Finish</span><input pInputText [(ngModel)]="f.finish" fluid /></label>
          <label class="field req"><span>Unit</span><input pInputText [(ngModel)]="f.unit" placeholder="nos, set, sq ft" fluid /></label>
          <label class="field"><span>Lead time (days)</span><p-inputnumber [(ngModel)]="f.lead_days" [min]="0" [max]="365" fluid /></label>
          <label class="field req"><span>Trade price (our cost)</span><p-inputnumber [(ngModel)]="f.rate" [min]="0" fluid /></label>
          <label class="field"><span>Client price</span><p-inputnumber [(ngModel)]="f.client_price" [min]="0" fluid placeholder="From the markup rules" /></label>
          <label class="field"><span>Supplier</span><p-select [options]="suppliers()" optionLabel="name" optionValue="id" [(ngModel)]="f.supplier_id" [filter]="true" [showClear]="true" fluid appendTo="body" /></label>
          <label class="field"><span>Supplier's page</span><input pInputText [(ngModel)]="f.url" fluid /></label>
        </div>
        <label class="field"><span>Photos</span><input type="file" accept="image/*" multiple (change)="attach($event)" /></label>
        <div class="row gap">@for (k of f.photos; track k; let i = $index) { <img class="thumb" [src]="'/api/files/' + k" alt="" (click)="f.photos.splice(i, 1)" title="Remove" /> }
          @if (f.image_url) { <img class="thumb" [src]="f.image_url" alt="" title="From the supplier's page" /> }</div>
        <div class="row right"><p-button label="Save" [disabled]="!f.name?.trim() || !f.unit?.trim() || f.rate == null" (onClick)="save()" /></div>
      </div>
    </p-dialog>
  `,
  styles: `
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: .75rem; }
    .prod { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem; background: var(--surface); display: grid; gap: .2rem; }
    .prod.click { cursor: pointer; }
    .img { aspect-ratio: 4 / 3; display: grid; place-items: center; background: var(--surface-2, rgba(0,0,0,.04)); border-radius: 6px; overflow: hidden; color: var(--muted); }
    .img img { width: 100%; height: 100%; object-fit: cover; }
    .thumb { width: 4rem; height: 3rem; object-fit: cover; border-radius: 4px; cursor: pointer; }
  `,
})
export class ProductsComponent implements OnInit {
  private api = inject(Api);
  private auth = inject(AuthService);
  rows = signal<any[]>([]);
  canWrite = signal(false);
  cats = signal<string[]>([]);
  suppliers = signal<any[]>([]);
  q = '';
  cat: string | null = null;
  dlg = false; clipDlg = false; busy = false;
  clipUrl = '';
  f: any = {};

  async ngOnInit() {
    await this.load();
    if (this.auth.can('proposals')) this.cats.set((await this.api.get('/rates?kind=product')).work_types ?? []);
    if (this.canWrite()) {
      const c = await this.api.get('/contacts');
      this.suppliers.set((Array.isArray(c) ? c : c.contacts ?? []).filter((x: any) => (x.types ?? []).includes('supplier')));
    }
  }

  async load() {
    const qs = new URLSearchParams();
    if (this.q) qs.set('q', this.q);
    if (this.cat) qs.set('category', this.cat);
    const r = await this.api.get(`/products?${qs}`);
    this.rows.set(r.products);
    this.canWrite.set(r.can_write && this.auth.can('proposals', 'rw'));
  }

  fmt(v: number) {
    return money(v, (this.auth.company() as any)?.currency ?? 'INR');
  }

  open(p?: any) {
    this.f = p ? { id: p.id, name: p.name, category: p.category, brand: p.brand, sku: p.sku, dimensions: p.dimensions, finish: p.finish, unit: p.unit,
      lead_days: p.lead_days, rate: p.rate, client_price: p.client_price, supplier_id: p.supplier_id, url: p.url, image_url: p.image_url, photos: [...(p.photos ?? [])] }
      : { name: '', category: null, unit: 'nos', rate: null, photos: [] };
    this.dlg = true;
  }

  async clip() {
    this.busy = true;
    try {
      const c = await this.api.post('/products/clip', { url: this.clipUrl });
      this.clipDlg = false;
      this.open();
      Object.assign(this.f, { name: c.name, brand: c.brand, sku: c.sku, url: c.url, image_url: c.image_url, client_price: c.price, rate: null });
    } finally {
      this.busy = false;
    }
  }

  async attach(ev: Event) {
    for (const file of Array.from((ev.target as HTMLInputElement).files ?? [])) this.f.photos.push((await this.api.upload(file)).key);
  }

  async save() {
    const { id, ...body } = this.f;
    body.kind = 'product';
    if (id) await this.api.put(`/rates/${id}`, body, 'Product saved');
    else await this.api.post('/rates', body, 'Product added');
    this.dlg = false;
    await this.load();
  }
}
