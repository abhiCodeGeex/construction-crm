import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { PasswordModule } from 'primeng/password';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';
import { AuthLayoutComponent } from './auth-layout.component';

@Component({
  selector: 'app-signup',
  imports: [FormsModule, RouterLink, ButtonModule, InputTextModule, PasswordModule, MessageModule, SelectButtonModule, AuthLayoutComponent],
  template: `
    <app-auth-layout>
      <h1 class="title">Start your 14-day free trial</h1>
      <p class="muted">No card needed. Your company type switches the right modules on.</p>
      <form class="stack" (ngSubmit)="submit()">
        <label class="field"><span>Company name</span><input pInputText name="company" [(ngModel)]="f.company_name" required fluid /></label>
        <div class="field">
          <span>What does your company do?</span>
          <p-selectbutton name="types" [options]="types" [(ngModel)]="f.company_types" [multiple]="true" optionLabel="label" optionValue="value" />
        </div>
        <div class="field">
          <span>Plan</span>
          <div class="plans">
            @for (p of plans; track p.code) {
              <button type="button" class="plan" [class.on]="f.plan_code === p.code" (click)="f.plan_code = p.code">
                <strong>{{ p.name }}</strong><span class="price">{{ p.price }}<small>/mo</small></span><small class="muted">{{ p.note }}</small>
              </button>
            }
          </div>
        </div>
        <div class="grid2">
          <label class="field"><span>Your name</span><input pInputText name="name" [(ngModel)]="f.name" required fluid /></label>
          <label class="field"><span>City</span><input pInputText name="city" [(ngModel)]="f.city" fluid /></label>
        </div>
        <label class="field"><span>Work email</span><input pInputText name="email" type="email" [(ngModel)]="f.email" required fluid /></label>
        <label class="field"><span>Password</span><p-password name="password" [(ngModel)]="f.password" [toggleMask]="true" fluid /></label>
        @if (error()) { <p-message severity="error" [text]="error()" /> }
        <p-button type="submit" label="Create account" icon="pi pi-arrow-right" iconPos="right" [loading]="busy()" styleClass="w-full" />
        <div class="small"><a routerLink="/login">Already have an account? Sign in</a></div>
      </form>
    </app-auth-layout>
  `,
})
export class SignupComponent {
  private auth = inject(AuthService);
  private router = inject(Router);
  types = [
    { value: 'architect', label: 'Architecture' },
    { value: 'contractor', label: 'Construction' },
    { value: 'interior', label: 'Interior design' },
  ];
  plans = [
    { code: 'basic', name: 'Basic', price: '₹3,500', note: '5 users · 1 module' },
    { code: 'pro', name: 'Pro', price: '₹8,500', note: '15 users · all modules' },
    { code: 'enterprise', name: 'Enterprise', price: '₹12,500', note: '50 users · custom' },
  ];
  f = { company_name: '', company_types: ['contractor'] as string[], plan_code: 'pro', name: '', city: '', email: '', password: '' };
  busy = signal(false);
  error = signal('');

  async submit() {
    if (!this.f.company_types?.length) return this.error.set('Pick at least one company type');
    if (this.f.password.length < 6) return this.error.set('Password must be at least 6 characters');
    this.busy.set(true);
    this.error.set('');
    try {
      await this.auth.signup(this.f);
      this.router.navigateByUrl('/app');
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
