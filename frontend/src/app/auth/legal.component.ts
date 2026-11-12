import { Component, OnInit, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthLayoutComponent } from './auth-layout.component';

/** Phase I: the platform's terms of service and privacy policy (Super Admin → Platform settings), public. */
@Component({
  selector: 'app-legal',
  imports: [RouterLink, AuthLayoutComponent],
  template: `
    <app-auth-layout>
      <h1 class="title">{{ kind() === 'privacy' ? 'Privacy policy' : 'Terms of service' }}</h1>
      @if (text()) { <div class="legal">{{ text() }}</div> } @else { <p class="muted">Not published yet.</p> }
      <p class="small"><a routerLink="/login">Back to sign in</a></p>
    </app-auth-layout>
  `,
  styles: `.legal { white-space: pre-wrap; line-height: 1.55; max-height: 60vh; overflow: auto; }`,
})
export class LegalComponent implements OnInit {
  kind = input<string>('terms');
  text = signal('');

  async ngOnInit() {
    try {
      const r = await (await fetch(`/api/public/legal/${this.kind() === 'privacy' ? 'privacy' : 'terms'}`)).json();
      this.text.set(r.text || '');
    } catch {
      this.text.set('');
    }
  }
}
