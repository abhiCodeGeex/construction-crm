import { Component, ElementRef, output, viewChild } from '@angular/core';
import { ButtonModule } from 'primeng/button';

/** A box to sign in with a finger, pen or mouse. Emits the signature as a PNG data URL, or null when cleared. */
@Component({
  selector: 'app-signature-pad',
  imports: [ButtonModule],
  template: `
    <canvas #pad class="sig-pad" width="520" height="150" (pointerdown)="down($event)" (pointermove)="move($event)"
            (pointerup)="up()" (pointerleave)="up()" aria-label="Signature box"></canvas>
    <div class="row-between"><small class="muted">Sign inside the box</small>
      <p-button label="Clear" icon="pi pi-eraser" size="small" [text]="true" severity="secondary" (onClick)="clear()" /></div>
  `,
  styles: `.sig-pad { width: 100%; max-width: 520px; height: 150px; border: 1px dashed var(--border); border-radius: 8px; background: #fff; touch-action: none; display: block; }`,
})
export class SignaturePadComponent {
  signed = output<string | null>();
  private pad = viewChild.required<ElementRef<HTMLCanvasElement>>('pad');
  private drawing = false;

  private ctx() {
    const c = this.pad().nativeElement.getContext('2d')!;
    c.lineWidth = 2.2;
    c.lineCap = 'round';
    c.strokeStyle = '#111';
    return c;
  }

  private point(e: PointerEvent) {
    const c = this.pad().nativeElement;
    const r = c.getBoundingClientRect();
    return [(e.clientX - r.left) * (c.width / r.width), (e.clientY - r.top) * (c.height / r.height)];
  }

  down(e: PointerEvent) {
    this.drawing = true;
    const [x, y] = this.point(e);
    const c = this.ctx();
    c.beginPath();
    c.moveTo(x, y);
  }

  move(e: PointerEvent) {
    if (!this.drawing) return;
    const [x, y] = this.point(e);
    const c = this.ctx();
    c.lineTo(x, y);
    c.stroke();
  }

  up() {
    if (!this.drawing) return;
    this.drawing = false;
    this.signed.emit(this.pad().nativeElement.toDataURL('image/png'));
  }

  clear() {
    const c = this.pad().nativeElement;
    c.getContext('2d')!.clearRect(0, 0, c.width, c.height);
    this.signed.emit(null);
  }
}
