import { HttpClient } from '@angular/common/http';
import { AfterViewChecked, Component, ElementRef, OnInit, computed, inject, input, signal, viewChild } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { TextareaModule } from 'primeng/textarea';
import { errorText } from '../../core/auth.interceptor';
import { money } from '../../core/api.service';

/** The client's proposal (§5): branded, optional items to tick, e-signature, decline / ask for changes, print.
 *  /p/:token is public; /app/proposals/:id/preview shows staff the same page without counting a view. */
@Component({
  selector: 'app-proposal-view',
  imports: [FormsModule, DatePipe, DecimalPipe, ButtonModule, CheckboxModule, InputTextModule, MessageModule, SelectModule, TextareaModule],
  template: `
    <div class="doc-wrap">
      @if (v(); as v) {
        <article class="doc" [style.--brand]="v.company.primary">
          <header class="doc-head">
            <div>@if (v.company.logo_url) { <img [src]="v.company.logo_url" alt="" class="doc-logo" /> } @else { <strong class="doc-co">{{ v.company.name }}</strong> }</div>
            <div class="right small">
              <strong>{{ v.company.name }}</strong><br />{{ v.company.address }}<br />{{ v.company.phone }} {{ v.company.email }}<br />{{ v.company.website }}
              @if (v.company.gstin) { <br />GSTIN {{ v.company.gstin }} }
            </div>
          </header>
          <h1 class="doc-title">{{ v.title }}</h1>
          <div class="row-between small doc-meta">
            <span>{{ v.type_label }} {{ v.number }} · version {{ v.version }}<br />For <strong>{{ v.client }}</strong> — {{ v.project }}</span>
            <span class="right">Valid until <strong>{{ v.valid_until | date: 'd MMM y' }}</strong>
              @if (preview()) { <br /><span class="tag-preview">Staff preview</span> }</span>
          </div>
          @if (v.intro) { <p class="pre">{{ v.intro }}</p> }
          @if (v.scope_text) { <h3>Scope of work</h3><p class="pre">{{ v.scope_text }}</p> }

          <h3>Price</h3>
          <table class="doc-table">
            <thead><tr><th>Item</th><th class="right">Qty</th><th class="right">Rate</th><th class="right">Amount</th></tr></thead>
            <tbody>
              @for (i of v.items; track i.id) {
                <tr [class.opt]="i.optional">
                  <td>@if (i.optional) { <label class="check">@if (canSign()) { <p-checkbox [binary]="true" [(ngModel)]="pick[i.id]" (ngModelChange)="recalc()" /> }
                      @else { <span>{{ i.selected ? '☑' : '☐' }}</span> } <span>Optional — {{ i.description }}</span></label> }
                    @else { {{ i.section ? i.section + ' · ' : '' }}{{ i.description }} }</td>
                  <td class="right nowrap">{{ i.qty | number: '1.0-2' }} {{ i.unit || '' }}</td><td class="right">{{ fmt(i.rate) }}</td><td class="right">{{ fmt(i.amount) }}</td>
                </tr>
              }
            </tbody>
          </table>
          <table class="doc-totals">
            <tr><td>Subtotal</td><td class="right">{{ fmt(t().subtotal) }}</td></tr>
            @if (t().discount) { <tr><td>Discount ({{ v.discount_pct }}%)</td><td class="right">− {{ fmt(t().discount) }}</td></tr> }
            @if (v.tax_pct) { <tr><td>{{ v.company.tax_label }} ({{ v.tax_pct }}%)</td><td class="right">{{ fmt(t().tax) }}</td></tr> }
            <tr class="grand"><td>Total</td><td class="right">{{ fmt(t().total) }}</td></tr>
          </table>

          @if (v.payment_schedule.length) {
            <h3>Payment schedule</h3>
            <table class="doc-table">
              @for (r of v.payment_schedule; track r.id) {
                <tr><td>{{ r.name }}</td><td class="muted small">{{ when(r) }}</td><td class="right">{{ r.pct }}%</td><td class="right">{{ fmt(t().total * r.pct / 100) }}</td></tr>
              }
            </table>
          }
          @if (v.terms) { <h3>Terms</h3><p class="pre small">{{ v.terms }}</p> }
          @if (v.has_file && token()) { <p><a [href]="'/api/public/proposals/' + token() + '/file'">Download the attached document</a></p> }

          @if (v.acceptance; as a) {
            <section class="doc-sign">
              <h3>Accepted</h3>
              @if (a.signature) { <img [src]="a.signature" alt="Signature" class="sig-img" /> }
              <div>{{ a.name }} · {{ a.at | date: 'd MMM y, h:mm a' }} · {{ a.method }}</div>
              @if (v.contract_number) { <div class="small muted">Contract {{ v.contract_number }}</div> }
            </section>
          } @else if (v.status === 'rejected' || v.status === 'revision_requested') {
            <p-message severity="info" text="{{ v.status === 'rejected' ? 'Declined' : 'Changes requested' }}: {{ v.response?.reason }}{{ v.response?.comment ? ' — ' + v.response.comment : '' }}. We will be in touch." />
          } @else if (v.expired || v.status === 'expired') {
            <p-message severity="warn" text="This proposal has expired. Please ask us for an updated one." />
          } @else if (canSign()) {
            <section class="doc-sign no-print">
              @if (!declining) {
                <h3>Accept this proposal</h3>
                <label class="field"><span>Your full name</span><input pInputText [(ngModel)]="name" fluid /></label>
                <div class="field"><span>Sign here</span>
                  <canvas #pad class="sig-pad" width="520" height="160" (pointerdown)="down($event)" (pointermove)="move($event)" (pointerup)="up()" (pointerleave)="up()"></canvas>
                  <a href="" class="small" (click)="$event.preventDefault(); clear()">Clear</a></div>
                <label class="check"><p-checkbox [binary]="true" [(ngModel)]="agree" /> I accept this proposal, its total of <strong>{{ fmt(t().total) }}</strong>, the payment schedule and the terms.</label>
                @if (error()) { <p-message severity="error" [text]="error()" /> }
                <div class="row gap"><p-button label="Accept and sign" icon="pi pi-check" (onClick)="accept()" [loading]="busy()" [disabled]="!name.trim() || !agree || !signed" />
                  <p-button label="Decline or ask for changes" [text]="true" severity="secondary" (onClick)="declining = true" /></div>
              } @else {
                <h3>Decline or ask for changes</h3>
                <label class="check"><p-checkbox [binary]="true" [(ngModel)]="revision" /> I would like a revised proposal</label>
                <p-select [options]="reasons" [(ngModel)]="reason" placeholder="Main reason" fluid />
                <textarea pTextarea rows="3" [(ngModel)]="comment" placeholder="Tell us more (optional)" fluid></textarea>
                @if (error()) { <p-message severity="error" [text]="error()" /> }
                <div class="row gap"><p-button label="Send" (onClick)="decline()" [disabled]="!reason" [loading]="busy()" /><p-button label="Back" [text]="true" (onClick)="declining = false" /></div>
              }
            </section>
          }
          <footer class="doc-foot small muted">{{ v.company.footer }}</footer>
          <div class="row right no-print"><p-button label="Print / save as PDF" icon="pi pi-print" [text]="true" (onClick)="print()" /></div>
        </article>
      } @else if (error()) {
        <div class="public-card"><h2>Not available</h2><p class="muted">{{ error() }}</p></div>
      }
    </div>
  `,
})
export class ProposalViewComponent implements OnInit, AfterViewChecked {
  token = input<string>('');
  id = input<string>('');
  private http = inject(HttpClient);
  pad = viewChild<ElementRef<HTMLCanvasElement>>('pad');
  v = signal<any>(null);
  error = signal('');
  busy = signal(false);
  t = signal<any>({ subtotal: 0, discount: 0, tax: 0, total: 0 });
  preview = computed(() => !this.token());
  canSign = computed(() => !!this.token() && this.v()?.status === 'sent' && !this.v()?.expired);
  pick: Record<string, boolean> = {};
  name = '';
  agree = false;
  signed = false;
  declining = false;
  revision = true;
  reason: string | null = null;
  comment = '';
  reasons = ['Price', 'Scope', 'Timing', 'Chose a competitor', 'Other'];
  private drawing = false;
  private ctx: CanvasRenderingContext2D | null = null;

  async ngOnInit() {
    try {
      const url = this.token() ? `/api/public/proposals/${this.token()}` : `/api/proposals/${this.id()}/preview`;
      this.set(await firstValueFrom(this.http.get(url)));
    } catch (e) {
      this.error.set(errorText(e));
    }
  }

  ngAfterViewChecked() {
    const c = this.pad()?.nativeElement;
    if (c && !this.ctx) {
      this.ctx = c.getContext('2d');
      this.ctx!.lineWidth = 2.2;
      this.ctx!.lineCap = 'round';
      this.ctx!.strokeStyle = '#111';
    }
    if (!c) this.ctx = null;
  }

  private set(v: any) {
    this.v.set(v);
    this.pick = Object.fromEntries(v.items.filter((i: any) => i.optional).map((i: any) => [i.id, !!i.selected]));
    this.recalc();
  }

  fmt(x: number | null | undefined) {
    return money(x, this.v()?.company?.currency ?? 'INR');
  }

  when(r: any) {
    return r.trigger === 'signing' ? 'on signing' : r.trigger === 'date' ? `on ${r.date}` : `when ${r.stage} is complete`;
  }

  /** Same arithmetic as the server: required + chosen options -> discount -> tax. */
  recalc() {
    const v = this.v();
    if (!v) return;
    if (!v.items.length) {
      this.t.set(v.totals);
      return;
    }
    const sub = v.items.filter((i: any) => !i.optional || (this.canSign() ? this.pick[i.id] : i.selected)).reduce((a: number, i: any) => a + i.amount, 0);
    const discount = sub * v.discount_pct / 100;
    const tax = (sub - discount) * v.tax_pct / 100;
    this.t.set({ subtotal: sub, discount, tax, total: sub - discount + tax });
  }

  private point(e: PointerEvent) {
    const c = this.pad()!.nativeElement;
    const r = c.getBoundingClientRect();
    return [(e.clientX - r.left) * (c.width / r.width), (e.clientY - r.top) * (c.height / r.height)];
  }

  down(e: PointerEvent) {
    if (!this.ctx) return;
    this.drawing = true;
    const [x, y] = this.point(e);
    this.ctx.beginPath();
    this.ctx.moveTo(x, y);
  }

  move(e: PointerEvent) {
    if (!this.drawing || !this.ctx) return;
    const [x, y] = this.point(e);
    this.ctx.lineTo(x, y);
    this.ctx.stroke();
    this.signed = true;
  }

  up() {
    this.drawing = false;
  }

  clear() {
    const c = this.pad()?.nativeElement;
    if (c && this.ctx) this.ctx.clearRect(0, 0, c.width, c.height);
    this.signed = false;
  }

  async accept() {
    this.busy.set(true);
    this.error.set('');
    try {
      const selected = Object.entries(this.pick).filter(([, on]) => on).map(([id]) => id);
      this.set(await firstValueFrom(this.http.post(`/api/public/proposals/${this.token()}/accept`,
        { name: this.name, agree: this.agree, signature: this.pad()!.nativeElement.toDataURL('image/png'), selected })));
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }

  async decline() {
    this.busy.set(true);
    this.error.set('');
    try {
      this.set(await firstValueFrom(this.http.post(`/api/public/proposals/${this.token()}/decline`, { revision: this.revision, reason: this.reason, comment: this.comment })));
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }

  print() {
    window.print();
  }
}
