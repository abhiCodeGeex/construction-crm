import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { toDataURL } from 'qrcode';
import { ButtonModule } from 'primeng/button';
import { InputOtpModule } from 'primeng/inputotp';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';
import { AuthLayoutComponent } from '../auth/auth-layout.component';

/** Super Admin sign-in: password, then a 6-digit code from an authenticator app.
 *  First sign-in: scan the QR code (or type the key) into the app, then enter the code it shows to confirm. */
@Component({
  selector: 'app-sa-login',
  imports: [FormsModule, RouterLink, ButtonModule, InputOtpModule, InputTextModule, MessageModule, PasswordModule, AuthLayoutComponent],
  template: `
    <app-auth-layout variant="sa">
      <h1 class="title"><i class="pi pi-shield"></i> Super Admin</h1>
      @if (step() === 'password') {
        <p class="muted">Platform team only. Two-factor authentication is required.</p>
        <form class="stack" (ngSubmit)="submit()">
          <label class="field"><span>Email</span><input pInputText name="email" type="email" [(ngModel)]="email" required fluid /></label>
          <label class="field"><span>Password</span><p-password name="password" [(ngModel)]="password" [feedback]="false" [toggleMask]="true" fluid /></label>
          @if (error()) { <p-message severity="error" [text]="error()" /> }
          <p-button type="submit" label="Continue" icon="pi pi-arrow-right" iconPos="right" [loading]="busy()" styleClass="w-full" />
        </form>
      } @else {
        @if (setup(); as s) {
          <p-message severity="info" text="First sign-in: set up two-factor once. It takes a minute." />
          <ol class="steps small">
            <li>Open an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy or 1Password).</li>
            <li>Tap <b>Add</b> → <b>Scan a QR code</b> and scan this code:</li>
          </ol>
          @if (qr()) { <img class="qr" [src]="qr()" alt="QR code for your authenticator app" width="200" height="200" /> }
          <p class="small muted">Can't scan? Choose <b>Enter a setup key</b> and type: <code class="key">{{ group(s.secret) }}</code> (time-based)</p>
          <ol class="steps small" start="3"><li>Type the 6-digit code the app now shows for <b>BuildSuite</b>:</li></ol>
        } @else {
          <p class="muted">Enter the 6-digit code from your authenticator app (BuildSuite).</p>
        }
        <form class="stack" (ngSubmit)="submit()">
          <p-inputotp name="code" [(ngModel)]="code" [length]="6" [integerOnly]="true" styleClass="otp" />
          @if (error()) { <p-message severity="error" [text]="error()" /> }
          <p-button type="submit" [label]="setup() ? 'Confirm & sign in' : 'Verify & sign in'" icon="pi pi-lock-open" [loading]="busy()"
            [disabled]="(code || '').length !== 6" styleClass="w-full" />
          <p-button label="Back" [text]="true" severity="secondary" (onClick)="back()" />
        </form>
        <p class="small muted">Lost your phone? Ask the platform Owner to reset your two-factor.</p>
      }
      <div class="demo">
        <div class="demo-head"><i class="pi pi-key"></i> Demo · password <code>Admin&#64;12345</code> · the first sign-in of each account sets up its authenticator</div>
        <div class="chips">
          @for (e of demo; track e) { <button type="button" class="chip" [class.on]="email === e" (click)="fill(e)">{{ e.split('@')[0] }}</button> }
        </div>
      </div>
      <div class="small mt"><a routerLink="/login">← Company sign in</a></div>
    </app-auth-layout>
  `,
  styles: [`
    .steps { margin: .5rem 0; padding-left: 1.2rem; display: grid; gap: .3rem; }
    .qr { display: block; margin: .25rem auto .5rem; background: #fff; padding: 6px; border-radius: 8px; }
    .key { word-break: break-all; letter-spacing: .05em; }
  `],
})
export class SaLoginComponent {
  private auth = inject(AuthService);
  private router = inject(Router);
  demo = ['superadmin', 'sa-billing', 'sa-support', 'sa-sales', 'sa-viewer'].map((x) => `${x}@buildsuite.test`);
  email = '';
  password = '';
  code = '';
  step = signal<'password' | 'code'>('password');
  setup = signal<{ secret: string; otpauth: string } | null>(null);
  qr = signal('');
  busy = signal(false);
  error = signal('');

  fill(e: string) {
    this.email = e;
    this.password = 'Admin@12345';
    this.back();
  }

  back() {
    this.step.set('password');
    this.setup.set(null);
    this.qr.set('');
    this.code = '';
    this.error.set('');
  }

  /** The key in groups of four, easier to type into an app. */
  group(secret: string) {
    return secret.replace(/(.{4})/g, '$1 ').trim();
  }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      const r = await this.auth.saLogin(this.email, this.password, this.step() === 'code' ? this.code : undefined);
      if (!r.twoFactor) {
        this.router.navigateByUrl('/sa');
        return;
      }
      this.step.set('code');
      this.code = '';
      if (r.setup) {
        this.setup.set(r.setup);
        this.qr.set(await toDataURL(r.setup.otpauth, { width: 200, margin: 1 }));
      }
    } catch (e) {
      this.error.set(errorText(e));
      this.code = '';
    } finally {
      this.busy.set(false);
    }
  }
}
