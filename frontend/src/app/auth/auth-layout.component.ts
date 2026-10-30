import { Component, inject, input } from '@angular/core';
import { ButtonModule } from 'primeng/button';
import { ThemeService } from '../core/theme.service';

/** Split-screen layout shared by login, signup and Super Admin login. */
@Component({
  selector: 'app-auth-layout',
  imports: [ButtonModule],
  template: `
    <div class="auth-split">
      <section class="hero" [class.sa]="variant() === 'sa'">
        <div class="logo"><span class="mark"><i class="pi pi-building"></i></span> BuildSuite</div>
        @if (variant() === 'sa') {
          <h2>Platform control centre</h2>
          <p>Companies, plans, billing and support — without ever seeing a company's private data.</p>
        } @else {
          <h2>One project. Architect, designer and contractor — together.</h2>
          <ul>
            <li><i class="pi pi-check-circle"></i> Leads to payments for all three firm types</li>
            <li><i class="pi pi-check-circle"></i> Role-based access, cost hiding and audit log</li>
            <li><i class="pi pi-check-circle"></i> Client portal and WhatsApp-first site team</li>
          </ul>
        }
        <div class="hero-foot">© BuildSuite CRM</div>
      </section>
      <section class="panel">
        <div class="panel-top">
          <p-button [icon]="theme.dark() ? 'pi pi-sun' : 'pi pi-moon'" [rounded]="true" [text]="true" severity="secondary"
                    (onClick)="theme.toggle()" ariaLabel="Toggle dark mode" />
        </div>
        <div class="panel-body"><ng-content /></div>
      </section>
    </div>
  `,
})
export class AuthLayoutComponent {
  theme = inject(ThemeService);
  variant = input<'app' | 'sa'>('app');
}
