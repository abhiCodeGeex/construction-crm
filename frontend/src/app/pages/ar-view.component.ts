import { CUSTOM_ELEMENTS_SCHEMA, Component, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { firstValueFrom } from 'rxjs';

/** Native dynamic import (kept out of the bundler). */
const load = (spec: string): Promise<any> => (new Function('s', 'return import(s)') as any)(spec);

/** Phase L block 5 — a 3D model on a phone, in AR: Android (Scene Viewer / WebXR) and iPhone (Quick Look) place it in the
 *  room at real size. Opened from the link the design team shares; no sign-in (the link carries a token). */
@Component({
  selector: 'app-ar-view',
  schemas: [CUSTOM_ELEMENTS_SCHEMA],
  template: `
    @if (err()) { <p class="pad">{{ err() }}</p> }
    @if (!err() && model(); as m) {
      <header class="pad"><strong>{{ m.title }}</strong><div class="small">{{ m.project }}@if (m.room) { · {{ m.room }} } · {{ m.company }}</div></header>
      <model-viewer [attr.src]="m.src" ar ar-modes="webxr scene-viewer quick-look" [attr.ar-scale]="m.scale" camera-controls touch-action="pan-y"
        shadow-intensity="1" [attr.alt]="m.title" style="width: 100%; height: calc(100vh - 9rem); background: #eef2f7">
        <button slot="ar-button" class="ar">View in your room</button>
      </model-viewer>
      <p class="pad small">Tap <strong>View in your room</strong>, point the phone at the floor and move it slowly until the model appears.
        It is shown at real size; pinch to look around. Needs ARCore (Android) or ARKit (iPhone).</p>
    }
    @if (!err() && !model()) { <p class="pad">Loading…</p> }
  `,
  styles: `:host { display: block; font-family: system-ui, sans-serif; } .pad { padding: .7rem 1rem; } .small { font-size: .85rem; color: #475569; }
    .ar { position: absolute; bottom: 1rem; left: 50%; transform: translateX(-50%); padding: .8rem 1.4rem; border: 0; border-radius: 99px;
      background: #2563eb; color: #fff; font-size: 1rem; font-weight: 600; box-shadow: 0 4px 12px rgba(0,0,0,.2); }`,
})
export class ArViewComponent {
  private http = inject(HttpClient);
  private token = inject(ActivatedRoute).snapshot.paramMap.get('token') ?? '';
  model = signal<any>(null);
  err = signal('');

  async ngOnInit() {
    try {
      await load('https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js');
      this.model.set(await firstValueFrom(this.http.get(`/api/public/ar/${this.token}`)));
    } catch (e: any) {
      this.err.set(e?.status === 404 ? 'This AR link was withdrawn. Ask the design team for a new one.' : 'The AR viewer could not be loaded.');
    }
  }
}
