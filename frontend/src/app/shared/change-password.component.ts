import { Component, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';
import { AuthService } from '../core/auth.service';
import { errorText } from '../core/auth.interceptor';
import { Session } from '../core/models';

/** Change my own password (staff and portal users). Other devices are signed out; this one stays signed in. */
@Component({
  selector: 'app-change-password',
  imports: [FormsModule, ButtonModule, DialogModule, MessageModule, PasswordModule],
  template: `
    <p-dialog header="Change password" [modal]="true" [(visible)]="visible" [style]="{ width: '26rem' }" [breakpoints]="{ '640px': '96vw' }" (onHide)="reset()">
      <form class="stack" (ngSubmit)="save()">
        <label class="field"><span>Current password</span>
          <p-password name="cur" [(ngModel)]="current" [feedback]="false" [toggleMask]="true" fluid autocomplete="current-password" /></label>
        <label class="field"><span>New password <small class="muted">(at least 6 characters)</small></span>
          <p-password name="pw" [(ngModel)]="pw" [toggleMask]="true" fluid autocomplete="new-password" /></label>
        <label class="field"><span>Type the new password again</span>
          <p-password name="pw2" [(ngModel)]="pw2" [feedback]="false" [toggleMask]="true" fluid autocomplete="new-password" /></label>
        @if (pw2 && pw !== pw2) { <small class="danger">The two new passwords are not the same</small> }
        @if (error()) { <p-message severity="error" [text]="error()" /> }
        <small class="muted">Any other device signed in with your account will be signed out.</small>
        <p-button type="submit" label="Change password" icon="pi pi-check" [loading]="busy()"
          [disabled]="!current || pw.length < 6 || pw !== pw2" styleClass="w-full" />
      </form>
    </p-dialog>
  `,
})
export class ChangePasswordComponent {
  private http = inject(HttpClient);
  private auth = inject(AuthService);
  private toast = inject(MessageService);
  visible = false;
  current = '';
  pw = '';
  pw2 = '';
  busy = signal(false);
  error = signal('');

  open() {
    this.reset();
    this.visible = true;
  }

  reset() {
    this.current = this.pw = this.pw2 = '';
    this.error.set('');
  }

  async save() {
    this.busy.set(true);
    this.error.set('');
    try {
      const s = await firstValueFrom(this.http.post<Session>('/api/auth/password', { current: this.current, new: this.pw }));
      this.auth.setSession(s); // the new session: the old token no longer works
      this.visible = false;
      this.toast.add({ severity: 'success', summary: 'Password changed', detail: 'Other devices have been signed out.' });
    } catch (e) {
      this.error.set(errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
