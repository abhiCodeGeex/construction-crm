import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TagModule } from 'primeng/tag';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { Api, money } from '../core/api.service';
import { AuthService } from '../core/auth.service';

/** Phase L block 4 — the marketplace of supplier catalogues: browse every listed supplier's products, add one to our
 *  catalogue (linked, so a price change shows), ask for a quote; and, for a company that sells, list our products. */
@Component({
  selector: 'app-marketplace',
  imports: [FormsModule, DatePipe, ButtonModule, DialogModule, InputNumberModule, InputTextModule, SelectModule, SelectButtonModule, TagModule, ToggleSwitchModule],
  template: `
    <div class="page-head"><h2>Marketplace</h2>
      <p-selectbutton [options]="tabs" [(ngModel)]="tab" optionLabel="label" optionValue="value" [allowEmpty]="false" (onChange)="loadTab()" /></div>

    @if (tab === 'browse') {
      <div class="row gap wrap mb">
        <input pInputText [(ngModel)]="q" placeholder="Search products, brands, suppliers" (keyup.enter)="browse()" aria-label="Search" class="grow" />
        <p-select [options]="cats()" [(ngModel)]="cat" placeholder="Category" [showClear]="true" (onChange)="browse()" ariaLabel="Category" />
        <p-select [options]="sellers()" [(ngModel)]="seller" optionLabel="name" optionValue="key" placeholder="Supplier" [showClear]="true" [filter]="true" (onChange)="browse()" ariaLabel="Supplier" />
        <input pInputText [(ngModel)]="city" placeholder="City" (keyup.enter)="browse()" aria-label="City" style="width: 8rem" />
        <p-button label="Search" icon="pi pi-search" (onClick)="browse()" />
      </div>
      <div class="small muted mb">{{ total() }} product(s)</div>
      <div class="cards">
        @for (it of items(); track it.id) {
          <div class="card">
            @if (it.image_urls[0]) { <img [src]="it.image_urls[0]" [alt]="it.name" loading="lazy" /> } @else { <div class="noimg"><i class="pi pi-image"></i></div> }
            <strong>{{ it.name }}</strong>
            <div class="small muted">{{ it.brand || '' }} {{ it.sku ? '· ' + it.sku : '' }} {{ it.finish ? '· ' + it.finish : '' }}</div>
            <div><strong>{{ fmt(it.price, it.currency) }}</strong> / {{ it.unit }} @if (it.lead_days) { <span class="small muted">· {{ it.lead_days }} days</span> }</div>
            <div class="small">{{ it.seller_name }}@if (it.seller_city) { , {{ it.seller_city }} }</div>
            <div class="row gap wrap">
              @if (it.in_my_catalogue) {
                <p-tag value="In my catalogue" severity="success" />
                @if (it.price_changed) { <p-button label="Price changed — update" size="small" severity="warn" (onClick)="updatePrice(it)" /> }
              } @else if (canWrite) { <p-button label="Add to my catalogue" size="small" [outlined]="true" (onClick)="add(it)" /> }
              <p-button label="Ask for a quote" size="small" [text]="true" (onClick)="openQuote(it)" />
            </div>
          </div>
        } @empty { <p class="muted">Nothing found. Suppliers list their catalogues here; ask yours to join.</p> }
      </div>
      @if (total() > (page + 1) * 48) { <div class="row center"><p-button label="More" [text]="true" (onClick)="page = page + 1; browse(true)" /></div> }
    }

    @if (tab === 'quotes') {
      <h4>Quote requests I sent</h4>
      @for (e of sent(); track e.id) {
        <div class="line"><strong>{{ e.number }}</strong> · {{ e.qty }} {{ e.unit }} of {{ e.item_name }} from {{ e.seller_name }} · {{ e.created_at | date: 'd MMM' }}
          @if (e.reply) { → <strong>{{ fmt(e.reply.price) }}</strong> / {{ e.unit }}@if (e.reply.lead_days) { , {{ e.reply.lead_days }} days }@if (e.reply.note) { — {{ e.reply.note }} } }
          @else { <p-tag value="waiting" severity="warn" /> }</div>
      } @empty { <p class="muted small">None.</p> }
      @if (received().length) {
        <h4>Quote requests for us (we sell)</h4>
        @for (e of received(); track e.id) {
          <div class="line"><strong>{{ e.number }}</strong> · {{ e.buyer_name }} ({{ e.buyer_person }}) wants {{ e.qty }} {{ e.unit }} of {{ e.item_name }}
            @if (e.needed_by) { by {{ e.needed_by }} } @if (e.city) { · {{ e.city }} } @if (e.note) { — {{ e.note }} }
            @if (e.reply) { <p-tag [value]="'quoted ' + fmt(e.reply.price)" severity="success" /> } @else { <p-button label="Quote" size="small" (onClick)="openReply(e)" /> }</div>
        }
      }
    }

    @if (tab === 'selling') {
      @if (selling(); as s) {
        <div class="stack narrow">
          <label class="row gap"><p-toggleswitch [(ngModel)]="s.enabled" (onChange)="saveSelling()" /> Sell our products on the marketplace</label>
          <input pInputText [(ngModel)]="s.contact_email" placeholder="Email for quote requests" (blur)="saveSelling()" aria-label="Enquiry email" />
          <textarea class="p-inputtext" rows="2" [(ngModel)]="s.about" placeholder="About us (shown to buyers)" (blur)="saveSelling()" aria-label="About us"></textarea>
          <p class="small muted">Buyers see the product, your list price and your contact for quotes — never your cost, margin or clients.</p>
        </div>
        @if (s.enabled) {
          <table class="tbl"><thead><tr><th>Product</th><th>Unit</th><th>List price</th><th>Added by buyers</th><th></th></tr></thead><tbody>
            @for (p of s.products; track p.id) {
              <tr><td>{{ p.name }} <span class="small muted">{{ p.brand || '' }}</span>@if (p.hidden) { <p-tag value="hidden by the platform" severity="danger" /> }</td><td>{{ p.unit }}</td>
                <td><p-inputnumber [(ngModel)]="p.edit_price" [min]="0" [placeholder]="(p.list_price ?? p.client_price ?? '') + ''" ariaLabel="List price" inputStyleClass="w7" /></td>
                <td>{{ p.adds }}</td>
                <td class="row gap"><p-button [label]="p.listed ? 'Update' : 'List'" size="small" (onClick)="publish(p)" />
                  @if (p.listed) { <p-button label="Take off" size="small" [text]="true" (onClick)="unlist(p)" /> }</td></tr>
            } @empty { <tr><td colspan="5" class="muted">Add products to your catalogue first (Proposals → rate library, kind “product”).</td></tr> }
          </tbody></table>
        }
      }
    }

    <p-dialog [header]="'Ask for a quote — ' + (cur?.name || '')" [modal]="true" [(visible)]="qDlg" [style]="{ width: '28rem' }">
      <div class="stack"><p-inputnumber [(ngModel)]="qf.qty" [min]="0" [placeholder]="'Quantity (' + (cur?.unit || '') + ')'" ariaLabel="Quantity" />
        <input pInputText type="date" [(ngModel)]="qf.needed_by" aria-label="Needed by" />
        <input pInputText [(ngModel)]="qf.city" placeholder="Delivery city" aria-label="City" />
        <textarea class="p-inputtext" rows="2" [(ngModel)]="qf.note" placeholder="Anything else" aria-label="Note"></textarea>
        <div class="row right"><p-button label="Send" [disabled]="!qf.qty" (onClick)="sendQuote()" /></div></div>
    </p-dialog>
    <p-dialog header="Send our quote" [modal]="true" [(visible)]="rDlg" [style]="{ width: '26rem' }">
      <div class="stack"><p-inputnumber [(ngModel)]="rf.price" [min]="0" placeholder="Price per unit" ariaLabel="Price" />
        <p-inputnumber [(ngModel)]="rf.lead_days" [min]="0" placeholder="Lead time (days)" ariaLabel="Lead time" />
        <textarea class="p-inputtext" rows="2" [(ngModel)]="rf.note" placeholder="Terms, freight, validity" aria-label="Note"></textarea>
        <div class="row right"><p-button label="Send" [disabled]="!rf.price" (onClick)="sendReply()" /></div></div>
    </p-dialog>
  `,
  styles: `.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: .8rem; }
    .card { border: 1px solid var(--border); border-radius: 10px; padding: .7rem; display: grid; gap: .3rem; align-content: start; }
    .card img, .noimg { width: 100%; height: 9rem; object-fit: cover; border-radius: 8px; background: var(--surface-ground, #f1f5f9); display: grid; place-items: center; color: #94a3b8; }
    .line { padding: .4rem 0; border-bottom: 1px solid var(--border); } .narrow { max-width: 36rem; margin-bottom: 1rem; }
    .tbl { width: 100%; border-collapse: collapse; } .tbl th, .tbl td { padding: .35rem .5rem; border-bottom: 1px solid var(--border); text-align: left; }
    :host ::ng-deep .w7 { width: 7rem; }`,
})
export class MarketplaceComponent {
  private api = inject(Api);
  private auth = inject(AuthService);
  canWrite = this.auth.can('proposals', 'rw') || this.auth.can('selections', 'rw') || this.auth.can('procurement', 'rw');
  canSell = this.auth.can('settings', 'r');
  tabs = [{ label: 'Browse', value: 'browse' }, { label: 'Quotes', value: 'quotes' }, ...(this.canSell ? [{ label: 'We sell', value: 'selling' }] : [])];
  tab = inject(ActivatedRoute).snapshot.queryParamMap.get('tab') || 'browse';
  items = signal<any[]>([]);
  total = signal(0);
  cats = signal<string[]>([]);
  sellers = signal<any[]>([]);
  sent = signal<any[]>([]);
  received = signal<any[]>([]);
  selling = signal<any>(null);
  q = ''; cat: string | null = null; seller: string | null = null; city = ''; page = 0;
  cur: any = null; qDlg = false; rDlg = false;
  qf: any = {}; rf: any = {};

  async ngOnInit() {
    await this.loadTab();
  }

  fmt(v: number, cur?: string) {
    return money(v, cur || (this.auth.company() as any)?.currency || 'INR');
  }

  async loadTab() {
    if (this.tab === 'browse') await this.browse();
    if (this.tab === 'quotes') {
      const e = await this.api.get('/marketplace-enquiries');
      this.sent.set(e.sent);
      this.received.set(e.received);
    }
    if (this.tab === 'selling') this.selling.set(await this.api.get('/marketplace-selling'));
  }

  async browse(more = false) {
    if (!more) this.page = 0;
    const p = new URLSearchParams({ page: String(this.page) });
    if (this.q) p.set('q', this.q);
    if (this.cat) p.set('category', this.cat);
    if (this.seller) p.set('seller', this.seller);
    if (this.city) p.set('city', this.city);
    const r = await this.api.get(`/marketplace?${p}`);
    this.items.set(more ? [...this.items(), ...r.items] : r.items);
    this.total.set(r.total);
    this.cats.set(r.categories);
    this.sellers.set(r.sellers);
  }

  async add(it: any) {
    await this.api.post(`/marketplace/${it.id}/add`, {}, 'Added to your catalogue');
    it.in_my_catalogue = true;
  }

  async updatePrice(it: any) {
    await this.api.post(`/marketplace/${it.id}/update-price`, {}, 'Price updated');
    it.price_changed = false;
  }

  openQuote(it: any) {
    this.cur = it;
    this.qf = { qty: null, needed_by: '', city: (this.auth.company() as any)?.city || '', note: '' };
    this.qDlg = true;
  }

  async sendQuote() {
    await this.api.post(`/marketplace/${this.cur.id}/enquire`, this.qf, 'Quote request sent');
    this.qDlg = false;
  }

  openReply(e: any) {
    this.cur = e;
    this.rf = { price: null, lead_days: null, note: '' };
    this.rDlg = true;
  }

  async sendReply() {
    await this.api.post(`/marketplace-enquiries/${this.cur.id}/reply`, this.rf, 'Quote sent');
    this.rDlg = false;
    await this.loadTab();
  }

  async saveSelling() {
    const s = this.selling();
    this.selling.set(await this.api.put('/marketplace-selling', { enabled: s.enabled, contact_email: s.contact_email, about: s.about }));
  }

  async publish(p: any) {
    this.selling.set(await this.api.post(`/marketplace-selling/${p.id}`, { price: p.edit_price ?? p.list_price ?? p.client_price }, 'Listed'));
  }

  async unlist(p: any) {
    this.selling.set(await this.api.post(`/marketplace-selling/${p.id}`, { published: false }, 'Taken off'));
  }
}
