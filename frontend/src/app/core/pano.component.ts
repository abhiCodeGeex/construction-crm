import { Component, ElementRef, OnDestroy, effect, input, output, viewChild } from '@angular/core';

declare const pannellum: any;
let loading: Promise<void> | null = null;

/** Pannellum (MIT) from the CDN, loaded once, only when a 360° view is opened. */
function loadPannellum(): Promise<void> {
  if ((window as any).pannellum) return Promise.resolve();
  loading ??= new Promise<void>((resolve, reject) => {
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.css';
    document.head.appendChild(css);
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.js';
    s.onload = () => resolve();
    s.onerror = () => { loading = null; reject(new Error('The 360° viewer could not be loaded')); };
    document.head.appendChild(s);
  });
  return loading;
}

/** Phase J block 5 — a 360° panorama or a flat render with comment pins; a click on a free spot emits where. */
@Component({
  selector: 'app-pano',
  template: `
    @if (view().kind === '360') {
      <div #pano class="pano" role="img" [attr.aria-label]="view().title"></div>
      @if (error) { <p class="small c-bad">{{ error }}</p> }
    } @else {
      <div class="render" (click)="clickRender($event)">
        <img [src]="view().url" [alt]="view().title" />
        @for (c of view().comments; track c.id; let i = $index) {
          <span class="pin" [class.done]="c.status === 'resolved'" [style.left.%]="c.x" [style.top.%]="c.y" [title]="c.author + ': ' + c.text">{{ i + 1 }}</span>
        }
      </div>
    }
    @if (canComment()) { <p class="small muted m0">Click a spot to comment on it.</p> }
  `,
  styles: `.pano { width: 100%; height: 420px; border-radius: 8px; overflow: hidden; }
    .render { position: relative; cursor: crosshair; } .render img { width: 100%; display: block; border-radius: 8px; }
    .pin { position: absolute; transform: translate(-50%, -50%); background: var(--p-primary-color, #2563eb); color: #fff; border-radius: 50%;
      width: 1.6rem; height: 1.6rem; display: grid; place-items: center; font-size: .75rem; font-weight: 700; box-shadow: 0 0 0 2px #fff; }
    .pin.done { background: #6b7280; }`,
})
export class PanoComponent implements OnDestroy {
  view = input.required<any>();
  canComment = input(false);
  spot = output<any>();
  private el = viewChild<ElementRef<HTMLDivElement>>('pano');
  private viewer: any = null;
  private down: [number, number] | null = null;
  error = '';

  constructor() {
    effect(() => {
      const v = this.view();
      const el = this.el()?.nativeElement;
      if (v.kind === '360' && el) this.build(v, el);
    });
  }

  private async build(v: any, el: HTMLDivElement) {
    try {
      await loadPannellum();
    } catch (e: any) {
      this.error = e.message;
      return;
    }
    const keep = this.viewer ? { yaw: this.viewer.getYaw(), pitch: this.viewer.getPitch() } : { yaw: 0, pitch: 0 };
    this.viewer?.destroy();
    this.viewer = pannellum.viewer(el, {
      type: 'equirectangular', panorama: v.url, autoLoad: true, showControls: true, ...keep,
      hotSpots: (v.comments ?? []).map((c: any, i: number) => ({ pitch: c.pitch, yaw: c.yaw, type: 'info', text: `${i + 1}. ${c.author}: ${c.text}` })),
    });
    el.onmousedown = (e) => (this.down = [e.clientX, e.clientY]);
    el.onmouseup = (e) => {
      if (!this.canComment() || !this.down || Math.hypot(e.clientX - this.down[0], e.clientY - this.down[1]) > 4) return; // a drag turns the view
      if ((e.target as HTMLElement).closest('.pnlm-hotspot, .pnlm-controls')) return;
      const [pitch, yaw] = this.viewer.mouseEventToCoords(e);
      this.spot.emit({ pitch: Math.round(pitch * 100) / 100, yaw: Math.round(((yaw + 360) % 360) * 100) / 100 });
    };
  }

  clickRender(e: MouseEvent) {
    if (!this.canComment() || (e.target as HTMLElement).classList.contains('pin')) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    this.spot.emit({ x: Math.round(((e.clientX - r.left) / r.width) * 10000) / 100, y: Math.round(((e.clientY - r.top) / r.height) * 10000) / 100 });
  }

  ngOnDestroy() {
    this.viewer?.destroy();
  }
}
