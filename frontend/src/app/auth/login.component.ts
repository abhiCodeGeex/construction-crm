import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { PasswordModule } from 'primeng/password';
import { MessageModule } from 'primeng/message';
import { IconFieldModule } from 'primeng/iconfield';
import { InputIconModule } from 'primeng/inputicon';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';
import { AuthLayoutComponent } from './auth-layout.component';

const DEMO = [
  { group: 'Staff · Skyline Design & Build (Pro)', emails: ['owner', 'sales', 'pm', 'designer', 'estimator', 'site', 'procurement', 'accounts'].map((r) => `${r}@skyline.test`) },
  { group: 'Portal · Skyline', emails: ['client', 'subcontractor', 'vendor', 'consultant'].map((r) => `${r}@skyline.test`) },
  { group: 'Second tenant · Nest Interiors (Basic)', emails: ['owner@nest.test', 'designer@nest.test'] },
];

@Component({
  selector: 'app-login',
  imports: [FormsModule, RouterLink, ButtonModule, InputTextModule, PasswordModule, MessageModule, IconFieldModule, InputIconModule, AuthLayoutComponent],
  template: `
    <app-auth-layout>
      <h1 class="title">Welcome back</h1>
      <p class="muted">Staff and portal users (clients, vendors, subcontractors, consultants) sign in here.</p>
      @if (auth.signedOutReason()) { <p-message severity="info" [text]="auth.signedOutReason()" styleClass="mb" /> }
      <form class="stack" (ngSubmit)="submit()">
        <label class="field">
          <span>Email</span>
          <p-iconfield>
            <p-inputicon class="pi pi-envelope" />
            <input pInputText name="email" type="email" [(ngModel)]="email" required autocomplete="username" fluid />
          </p-iconfield>
        </label>
        <label class="field">
          <span>Password</span>
          <p-password name="password" [(ngModel)]="password" [feedback]="false" [toggleMask]="true" fluid autocomplete="current-password" />
        </label>
        <div class="right small"><a routerLink="/forgot" [queryParams]="email ? { email } : {}">Forgot password?</a></div>
        @if (error()) { <p-message severity="error" [text]="error()" /> }
        <p-button type="submit" label="Sign in" icon="pi pi-sign-in" [loading]="busy()" styleClass="w-full" />
        <div class="row-between small">
          <a routerLink="/signup">Create a company account</a>
          <a routerLink="/sa/login"><i class="pi pi-shield"></i> Super Admin</a>
        </div>
      </form>

      <div class="demo">
        <div class="demo-head"><i class="pi pi-key"></i> Demo accounts <span class="muted">· password <code>Demo&#64;123</code></span></div>
        @for (g of demo; track g.group) {
          <div class="demo-group">{{ g.group }}</div>
          <div class="chips">
            @for (e of g.emails; track e) {
              <button type="button" class="chip" [class.on]="email === e" (click)="fill(e)">{{ e.split('@')[0] }}</button>
            }
          </div>
        }
      </div>
    </app-auth-layout>
  `,
})
export class LoginComponent {
  auth = inject(AuthService);
  private router = inject(Router);
  demo = DEMO;
  email = '';
  password = '';
  busy = signal(false);
  error = signal('');

  constructor() {
    // Phase I: a platform support session opened by the Super Admin (with the company's permission)
    const support = new URLSearchParams(location.search).get('support');
    if (support) {
      this.auth.setSession({ token: support } as any);
      this.auth.refresh().then(() => this.router.navigateByUrl('/app')).catch(() => { this.auth.setSession(null); this.error.set('The support session has ended.'); });
    }
  }

  fill(email: string) {
    this.email = email;
    this.password = 'Demo@123';
  }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    this.auth.signedOutReason.set('');
    try {
      const s = await this.auth.login(this.email, this.password);
      this.router.navigateByUrl(this.auth.homeFor(s));
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
