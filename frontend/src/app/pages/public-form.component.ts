import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { TextareaModule } from 'primeng/textarea';
import { errorText } from '../core/auth.interceptor';

/** Public enquiry form (§2 source "Website form"). Each company gets its own link; no login. */
@Component({
  selector: 'app-public-form',
  imports: [FormsModule, ButtonModule, InputTextModule, MessageModule, SelectModule, TextareaModule],
  template: `
    <div class="public-wrap">
      @if (info(); as i) {
        <div class="public-card">
          <div class="logo"><span class="mark"><i class="pi pi-building"></i></span> {{ i.company }}</div>
          @if (sent()) {
            <h2>Thank you!</h2><p class="muted">We have received your enquiry and will contact you shortly.</p>
          } @else {
            <h2>Tell us about your project</h2>
            <form class="stack" (ngSubmit)="submit()">
              <label class="field"><span>Your name</span><input pInputText name="n" [(ngModel)]="f.name" fluid /></label>
              <div class="grid2">
                <label class="field"><span>Phone</span><input pInputText name="p" [(ngModel)]="f.phone" fluid /></label>
                <label class="field"><span>Email</span><input pInputText name="e" type="email" [(ngModel)]="f.email" fluid /></label>
              </div>
              <div class="grid2">
                <label class="field"><span>Service</span><p-select name="s" [options]="i.services" [(ngModel)]="f.service" fluid /></label>
                <label class="field"><span>Project type</span><p-select name="t" [options]="i.project_types" [(ngModel)]="f.project_type" [showClear]="true" fluid /></label>
              </div>
              <div class="grid2">
                <label class="field"><span>Location</span><input pInputText name="l" [(ngModel)]="f.location" fluid /></label>
                <label class="field"><span>When do you want to start?</span><p-select name="tl" [options]="i.timelines" [(ngModel)]="f.timeline" [showClear]="true" fluid /></label>
              </div>
              <label class="field"><span>Message</span><textarea pTextarea name="m" rows="3" [(ngModel)]="f.message" fluid></textarea></label>
              <input type="text" name="website" [(ngModel)]="f.website" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true" />
              @if (error()) { <p-message severity="error" [text]="error()" /> }
              <p-button type="submit" label="Send enquiry" icon="pi pi-send" [loading]="busy()" styleClass="w-full" />
            </form>
          }
        </div>
      } @else if (error()) {
        <div class="public-card"><h2>Form unavailable</h2><p class="muted">{{ error() }}</p></div>
      }
    </div>
  `,
})
export class PublicFormComponent implements OnInit {
  key = input.required<string>();
  private http = inject(HttpClient);
  info = signal<any>(null);
  sent = signal(false);
  busy = signal(false);
  error = signal('');
  f: any = { name: '', phone: '', email: '', service: null, project_type: null, location: '', timeline: null, message: '', website: '' };

  async ngOnInit() {
    try {
      const i = await firstValueFrom(this.http.get<any>(`/api/public/lead-form/${this.key()}`));
      this.f.service = i.services[0];
      this.info.set(i);
    } catch (e) {
      this.error.set(errorText(e));
    }
  }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      await firstValueFrom(this.http.post(`/api/public/lead-form/${this.key()}`, this.f));
      this.sent.set(true);
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
