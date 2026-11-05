import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ButtonModule } from 'primeng/button';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { TextareaModule } from 'primeng/textarea';
import { errorText } from '../core/auth.interceptor';

/** Public client questionnaire (C+2 step 4): one link per lead, answered once, no login. */
@Component({
  selector: 'app-public-questionnaire',
  imports: [FormsModule, ButtonModule, MessageModule, SelectModule, TextareaModule],
  template: `
    <div class="public-wrap">
      @if (info(); as i) {
        <div class="public-card">
          <div class="logo"><span class="mark"><i class="pi pi-building"></i></span> {{ i.company }}</div>
          @if (sent() || i.submitted) {
            <h2>Thank you!</h2><p class="muted">Your answers have reached the team. We will use them to prepare your proposal.</p>
          } @else {
            <h2>{{ i.project }}</h2>
            <p class="muted">Dear {{ i.name }}, a few questions so we design exactly what you have in mind. Answer what you can.</p>
            <form class="stack" (ngSubmit)="submit()">
              @for (q of i.questions; track q.id) {
                <label class="field"><span>{{ q.label }}</span>
                  @if (q.type === 'choice') { <p-select [name]="q.id" [options]="q.options" [(ngModel)]="answers[q.id]" [showClear]="true" fluid /> }
                  @else { <textarea pTextarea [name]="q.id" rows="2" [(ngModel)]="answers[q.id]" fluid></textarea> }
                </label>
              }
              @if (error()) { <p-message severity="error" [text]="error()" /> }
              <p-button type="submit" label="Send my answers" icon="pi pi-send" [loading]="busy()" />
            </form>
          }
        </div>
      } @else if (error()) {
        <div class="public-card"><h2>Not available</h2><p class="muted">{{ error() }}</p></div>
      }
    </div>
  `,
})
export class PublicQuestionnaireComponent implements OnInit {
  token = input.required<string>();
  private http = inject(HttpClient);
  info = signal<any>(null);
  sent = signal(false);
  busy = signal(false);
  error = signal('');
  answers: Record<string, string> = {};

  async ngOnInit() {
    try {
      this.info.set(await firstValueFrom(this.http.get(`/api/public/questionnaire/${this.token()}`)));
    } catch (e) {
      this.error.set(errorText(e));
    }
  }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      await firstValueFrom(this.http.post(`/api/public/questionnaire/${this.token()}`, { answers: this.answers }));
      this.sent.set(true);
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
