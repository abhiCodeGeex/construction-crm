import { Component, OnInit, inject, input, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';
import { errorText } from '../core/auth.interceptor';
import { AuthLayoutComponent } from './auth-layout.component';

/** Step 1 of forgot password (B+1): the user types their email and gets a link that works for 60 minutes, once. */
@Component({
  selector: 'app-forgot-password',
  imports: [FormsModule, RouterLink, ButtonModule, InputTextModule, MessageModule, AuthLayoutComponent],
  template: `
    <app-auth-layout>
      <h1 class="title">Forgot your password?</h1>
      @if (!sent()) {
        <p class="muted">Type the email you sign in with. We'll email you a link to choose a new password.</p>
        <form class="stack" (ngSubmit)="submit()">
          <label class="field"><span>Email</span>
            <input pInputText name="email" type="email" [(ngModel)]="email" required autocomplete="username" fluid /></label>
          @if (error()) { <p-message severity="error" [text]="error()" /> }
          <p-button type="submit" label="Email me a reset link" icon="pi pi-envelope" [loading]="busy()" [disabled]="!email.trim()" styleClass="w-full" />
        </form>
      } @else {
        <p-message severity="success" [text]="sent()" />
        <p class="muted small mt">Each link works once. Asked more than once? Any of the links works, and using one cancels the others.</p>
      }
      <div class="small mt"><a routerLink="/login">← Back to sign in</a></div>
    </app-auth-layout>
  `,
})
export class ForgotPasswordComponent implements OnInit {
  private http = inject(HttpClient);
  private route = inject(ActivatedRoute);
  email = '';
  busy = signal(false);
  error = signal('');
  sent = signal('');

  ngOnInit() {
    this.email = this.route.snapshot.queryParamMap.get('email') ?? '';
  }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      const r: any = await firstValueFrom(this.http.post('/api/auth/forgot', { email: this.email.trim() }));
      this.sent.set(r.message);
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}

/** Step 2: the link from the email. Checks the link first, then asks for the new password twice. */
@Component({
  selector: 'app-reset-password',
  imports: [FormsModule, RouterLink, ButtonModule, MessageModule, PasswordModule, AuthLayoutComponent],
  template: `
    <app-auth-layout>
      <h1 class="title">Choose a new password</h1>
      @if (state() === 'checking') {
        <p class="muted">Checking your link…</p>
      } @else if (state() === 'invalid') {
        <p-message severity="error" [text]="error()" />
        <div class="small mt"><a routerLink="/forgot">Ask for a new link</a> · <a routerLink="/login">Sign in</a></div>
      } @else if (state() === 'done') {
        <p-message severity="success" text="Your password has been changed. Sign in with the new password. Any other device that was signed in has been signed out." />
        <div class="mt"><p-button label="Go to sign in" icon="pi pi-sign-in" routerLink="/login" styleClass="w-full" /></div>
      } @else {
        <p class="muted">For <b>{{ masked() }}</b>. At least 6 characters.</p>
        <form class="stack" (ngSubmit)="submit()">
          <label class="field"><span>New password</span>
            <p-password name="pw" [(ngModel)]="pw" [toggleMask]="true" fluid autocomplete="new-password" /></label>
          <label class="field"><span>Type it again</span>
            <p-password name="pw2" [(ngModel)]="pw2" [feedback]="false" [toggleMask]="true" fluid autocomplete="new-password" /></label>
          @if (pw2 && pw !== pw2) { <small class="danger">The two passwords are not the same</small> }
          @if (error()) { <p-message severity="error" [text]="error()" /> }
          <p-button type="submit" label="Save new password" icon="pi pi-check" [loading]="busy()"
            [disabled]="pw.length < 6 || pw !== pw2" styleClass="w-full" />
        </form>
      }
    </app-auth-layout>
  `,
})
export class ResetPasswordComponent implements OnInit {
  token = input.required<string>();
  private http = inject(HttpClient);
  state = signal<'checking' | 'invalid' | 'form' | 'done'>('checking');
  masked = signal('');
  busy = signal(false);
  error = signal('');
  pw = '';
  pw2 = '';

  async ngOnInit() {
    try {
      const r: any = await firstValueFrom(this.http.get(`/api/auth/reset/${this.token()}`));
      this.masked.set(r.email);
      this.state.set('form');
    } catch (e) {
      this.error.set(errorText(e));
      this.state.set('invalid');
    }
  }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      await firstValueFrom(this.http.post(`/api/auth/reset/${this.token()}`, { password: this.pw }));
      this.state.set('done');
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
