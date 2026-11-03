import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';
import { Api, SERVICE_LABEL } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { CHANNEL_LABEL } from '../shared/followup-dialog.component';

/** Settings → Sales: pipelines per service, loss reasons, website form, message templates. */
@Component({
  selector: 'app-sales-settings',
  imports: [FormsModule, ButtonModule, CardModule, DialogModule, InputTextModule, SelectModule, TableModule, TagModule, TextareaModule],
  template: `
    @if (meta(); as m) {
      <div class="tpl-grid">
        @for (svc of m.services; track svc) {
          <p-card><ng-template #title>{{ label[svc] }} pipeline</ng-template>
            <ol class="pipe-edit">
              @for (st of draft[svc]; track $index; let i = $index; let last = $last) {
                <li><input pInputText [(ngModel)]="draft[svc][i]" [disabled]="!canEdit()" />
                  @if (canEdit()) {
                    <p-button icon="pi pi-arrow-up" [text]="true" size="small" [disabled]="i === 0" (onClick)="swap(svc, i, i - 1)" />
                    <p-button icon="pi pi-arrow-down" [text]="true" size="small" [disabled]="last" (onClick)="swap(svc, i, i + 1)" />
                    <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="draft[svc].splice(i, 1)" /> }</li>
              }
              <li class="muted"><i class="pi pi-trophy"></i> Won · <i class="pi pi-times-circle"></i> Lost <small>(fixed)</small></li>
            </ol>
            @if (canEdit()) { <p-button label="Add stage" icon="pi pi-plus" size="small" [text]="true" (onClick)="draft[svc].push('')" /> }
          </p-card>
        }
        <p-card><ng-template #title>Loss reasons</ng-template>
          @for (r of reasons; track $index; let i = $index) {
            <div class="row gap mb-xs"><input pInputText [(ngModel)]="reasons[i]" [disabled]="!canEdit()" class="grow" />
              @if (canEdit()) { <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="reasons.splice(i, 1)" /> }</div>
          }
          @if (canEdit()) { <p-button label="Add reason" icon="pi pi-plus" size="small" [text]="true" (onClick)="reasons.push('')" /> }
        </p-card>
      </div>
      @if (canEdit()) { <div class="row right mt"><p-button label="Save pipelines & reasons" icon="pi pi-check" (onClick)="savePipelines()" /></div> }

      @if (m.form_key) {
        <p-card styleClass="mt"><ng-template #title>Website enquiry form</ng-template>
          <p class="muted">Enquiries from this form arrive as <strong>Website form</strong> leads (unassigned). Repeat enquiries from the same phone or email are added to the open lead instead of creating a duplicate.</p>
          <div class="row gap"><input pInputText [value]="formUrl()" readonly class="grow" />
            <p-button label="Copy link" icon="pi pi-copy" [outlined]="true" (onClick)="copy(formUrl())" />
            <a [href]="formUrl()" target="_blank" rel="noopener"><p-button label="Open" icon="pi pi-external-link" [text]="true" /></a></div>
          <label class="field mt"><span>Embed on your website</span><textarea pTextarea rows="3" [value]="embed()" readonly fluid></textarea></label>
          @if (canEdit()) { <p-button label="Regenerate link" icon="pi pi-refresh" severity="warn" [text]="true" (onClick)="rotate()" /><small class="muted">The old link stops working.</small> }
        </p-card>
      }

      <p-card styleClass="mt">
        <ng-template #title><div class="row-between"><span>Message templates</span>
          @if (canEdit()) { <p-button label="New template" icon="pi pi-plus" size="small" (onClick)="editTpl()" /> }</div></ng-template>
        <p class="muted small">Merge fields: @for (f of mergeFields; track f) { <code>{{ mf(f) }}</code> } </p>
        <p-table [value]="templates()" size="small">
          <ng-template #header><tr><th>Name</th><th>Channel</th><th>Text</th><th></th></tr></ng-template>
          <ng-template #body let-t><tr><td><strong>{{ t.name }}</strong></td><td><p-tag [value]="chan[t.channel]" severity="secondary" /></td>
            <td><small class="muted pre">{{ t.body.length > 140 ? t.body.slice(0, 140) + '…' : t.body }}</small></td>
            <td class="right nowrap">@if (canEdit()) { <p-button icon="pi pi-pencil" [text]="true" (onClick)="editTpl(t)" />
              <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="deleteTpl(t)" /> }</td></tr></ng-template>
        </p-table>
      </p-card>
    }

    <p-dialog [header]="tf.id ? 'Edit template' : 'New template'" [modal]="true" [(visible)]="tplDlg" [style]="{ width: '36rem' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Name</span><input pInputText [(ngModel)]="tf.name" fluid /></label>
          <label class="field"><span>Channel</span><p-select [options]="channels" [(ngModel)]="tf.channel" optionLabel="label" optionValue="value" fluid appendTo="body" /></label>
        </div>
        @if (tf.channel === 'email') { <label class="field"><span>Subject</span><input pInputText [(ngModel)]="tf.subject" fluid /></label> }
        <label class="field"><span>Text</span><textarea pTextarea rows="7" [(ngModel)]="tf.body" fluid></textarea>
          <small class="muted">{{ tf.body?.length || 0 }} characters{{ tf.channel === 'sms' ? ' (max 480)' : '' }}</small></label>
        <div class="chips">@for (f of mergeFields; track f) { <button type="button" class="chip" (click)="insert(f)">+ {{ f }}</button> }</div>
        <div class="row gap right"><p-button label="Save" icon="pi pi-check" (onClick)="saveTpl()" /></div>
      </div>
    </p-dialog>
  `,
})
export class SalesSettingsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  private toast = inject(MessageService);
  meta = signal<any>(null);
  templates = signal<any[]>([]);
  canEdit = computed(() => this.auth.can('settings', 'rw'));
  formUrl = computed(() => `${location.origin}/f/${this.meta()?.form_key}`);
  embed = computed(() => `<iframe src="${this.formUrl()}" width="100%" height="760" style="border:0" title="Enquiry form"></iframe>`);
  label = SERVICE_LABEL;
  chan = CHANNEL_LABEL;
  channels = [{ value: 'email', label: 'Email' }, { value: 'sms', label: 'SMS' }, { value: 'whatsapp', label: 'WhatsApp' }];
  mergeFields = ['client', 'name', 'project', 'amount', 'company', 'date', 'salesperson'];
  draft: Record<string, string[]> = {};
  reasons: string[] = [];
  tplDlg = false;
  tf: any = {};

  async ngOnInit() {
    await this.load();
  }

  async load() {
    const m = await this.api.get('/leads/meta');
    this.meta.set(m);
    this.draft = Object.fromEntries(m.services.map((s: string) => [s, [...m.pipelines[s]]]));
    this.reasons = [...m.loss_reasons];
    this.templates.set(await this.api.get('/message_templates'));
  }

  mf(f: string) {
    return '{' + '{' + f + '}' + '}';
  }

  insert(f: string) {
    this.tf.body = (this.tf.body || '') + this.mf(f);
  }

  swap(svc: string, i: number, j: number) {
    const a = this.draft[svc];
    [a[i], a[j]] = [a[j], a[i]];
  }

  async savePipelines() {
    await this.api.put('/leads/pipelines', { pipelines: this.draft, loss_reasons: this.reasons }, 'Pipelines saved');
    await this.load();
  }

  async rotate() {
    await this.api.post('/leads/form-key', {}, 'New link created');
    await this.load();
  }

  copy(text: string) {
    navigator.clipboard?.writeText(text).then(() => this.toast.add({ severity: 'success', summary: 'Copied', life: 1500 }));
  }

  editTpl(t?: any) {
    this.tf = t ? { ...t } : { name: '', channel: 'whatsapp', subject: '', body: '' };
    this.tplDlg = true;
  }

  async saveTpl() {
    const body = { name: this.tf.name, channel: this.tf.channel, subject: this.tf.subject, body: this.tf.body };
    if (this.tf.id) await this.api.put(`/message_templates/${this.tf.id}`, body, 'Template saved');
    else await this.api.post('/message_templates', body, 'Template created');
    this.tplDlg = false;
    await this.load();
  }

  async deleteTpl(t: any) {
    await this.api.del(`/message_templates/${t.id}`, 'Template deleted');
    await this.load();
  }
}
