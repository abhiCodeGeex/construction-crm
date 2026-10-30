import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { InputOtpModule } from 'primeng/inputotp';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';
import { AuthLayoutComponent } from '../auth/auth-layout.component';

@Component({
  selector: 'app-sa-login',
  imports: [FormsModule, RouterLink, ButtonModule, InputOtpModule, InputTextModule, MessageModule, PasswordModule, AuthLayoutComponent],
  template: `
    <app-auth-layout variant="sa">
      <h1 class="title"><i class="pi pi-shield"></i> Super Admin</h1>
      @if (!step2()) {
        <p class="muted">Platform team only. Two-factor authentication is required.</p>
        <form class="stack" (ngSubmit)="submit()">
          <label class="field"><span>Email</span><input pInputText name="email" type="email" [(ngModel)]="email" required fluid /></label>
          <label class="field"><span>Password</span><p-password name="password" [(ngModel)]="password" [feedback]="false" [toggleMask]="true" fluid /></label>
          @if (error()) { <p-message severity="error" [text]="error()" /> }
          <p-button type="submit" label="Continue" icon="pi pi-arrow-right" iconPos="right" [loading]="busy()" styleClass="w-full" />
        </form>
      } @else {
        <p class="muted">Enter the 6-digit code from your authenticator app.</p>
        <form class="stack" (ngSubmit)="submit()">
          <p-inputotp name="code" [(ngModel)]="code" [length]="6" [integerOnly]="true" styleClass="otp" />
          @if (error()) { <p-message severity="error" [text]="error()" /> }
          <p-button type="submit" label="Verify & sign in" icon="pi pi-lock-open" [loading]="busy()" styleClass="w-full" />
          <p-button label="Back" [text]="true" severity="secondary" (onClick)="step2.set(false); code = ''" />
        </form>
      }
      <div class="demo">
        <div class="demo-head"><i class="pi pi-key"></i> Demo · password <code>Admin&#64;12345</code> · 2FA code <code>123456</code></div>
        <div class="chips">
          @for (e of demo; track e) { <button type="button" class="chip" [class.on]="email === e" (click)="fill(e)">{{ e.split('@')[0] }}</button> }
        </div>
      </div>
      <div class="small mt"><a routerLink="/login">← Company sign in</a></div>
    </app-auth-layout>
  `,
})
export class SaLoginComponent {
  private auth = inject(AuthService);
  private router = inject(Router);
  demo = ['superadmin', 'sa-billing', 'sa-support', 'sa-sales', 'sa-viewer'].map((x) => `${x}@buildsuite.test`);
  email = '';
  password = '';
  code = '';
  step2 = signal(false);
  busy = signal(false);
  error = signal('');

  fill(e: string) {
    this.email = e;
    this.password = 'Admin@12345';
    this.step2.set(false);
  }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      const r = await this.auth.saLogin(this.email, this.password, this.step2() ? this.code : undefined);
      if (r.twoFactor) this.step2.set(true);
      else this.router.navigateByUrl('/sa');
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
