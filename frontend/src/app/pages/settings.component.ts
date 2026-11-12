import { IntegrationsSettingsComponent } from './integrations-settings.component';
import { FieldSettingsComponent } from './field-settings.component';
import { SubscriptionComponent } from './subscription.component';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { TooltipModule } from 'primeng/tooltip';
import { CardModule } from 'primeng/card';
import { CheckboxModule } from 'primeng/checkbox';
import { TextareaModule } from 'primeng/textarea';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { Api, SERVICE_LABEL } from '../core/api.service';
import { SalesSettingsComponent } from './sales-settings.component';
import { ProposalSettingsComponent } from './proposal-settings.component';
import { AuthService } from '../core/auth.service';

/** GST state codes (Phase I): the company's state decides CGST + SGST or IGST on invoices. */
const STATE_NAMES: Record<string, string> = {
  '01': 'Jammu and Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh', '05': 'Uttarakhand', '06': 'Haryana', '07': 'Delhi',
  '08': 'Rajasthan', '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim', '12': 'Arunachal Pradesh', '13': 'Nagaland', '14': 'Manipur',
  '15': 'Mizoram', '16': 'Tripura', '17': 'Meghalaya', '18': 'Assam', '19': 'West Bengal', '20': 'Jharkhand', '21': 'Odisha',
  '22': 'Chhattisgarh', '23': 'Madhya Pradesh', '24': 'Gujarat', '26': 'Dadra and Nagar Haveli and Daman and Diu', '27': 'Maharashtra',
  '29': 'Karnataka', '30': 'Goa', '31': 'Lakshadweep', '32': 'Kerala', '33': 'Tamil Nadu', '34': 'Puducherry',
  '35': 'Andaman and Nicobar Islands', '36': 'Telangana', '37': 'Andhra Pradesh', '38': 'Ladakh', '97': 'Other Territory',
};

@Component({
  selector: 'app-settings',
  imports: [IntegrationsSettingsComponent, FieldSettingsComponent, SubscriptionComponent, TooltipModule, FormsModule, DatePipe, ButtonModule, CardModule, CheckboxModule, TextareaModule, DialogModule, InputNumberModule, InputTextModule, MessageModule, SelectButtonModule,
    SelectModule, TableModule, TabsModule, TagModule, ToggleSwitchModule, SalesSettingsComponent, ProposalSettingsComponent],
  template: `
    <div class="page-head"><div><h1>Company settings</h1><p class="muted">Company setup, stage templates, role permissions and the audit log.</p></div></div>
    @if (!canEdit()) { <p-message severity="info" icon="pi pi-eye" text="Read-only: only the owner can change company settings." styleClass="mb" /> }

    <p-tabs [value]="startTab" [scrollable]="true">
      <p-tablist>
        <p-tab value="company"><i class="pi pi-building mr"></i>Company</p-tab>
        <p-tab value="setup"><i class="pi pi-sitemap mr"></i>Branches, tax & numbering</p-tab>
        <p-tab value="templates"><i class="pi pi-list mr"></i>Stage templates</p-tab>
        <p-tab value="sales"><i class="pi pi-bullseye mr"></i>Sales & templates</p-tab>
        <p-tab value="proposals"><i class="pi pi-file-edit mr"></i>Proposals & branding</p-tab>
        <p-tab value="roles"><i class="pi pi-shield mr"></i>Roles & permissions</p-tab>
        <p-tab value="audit"><i class="pi pi-history mr"></i>Audit log</p-tab>
        <p-tab value="field"><i class="pi pi-whatsapp mr"></i>Field & WhatsApp</p-tab>
        <p-tab value="integrations"><i class="pi pi-link mr"></i>Integrations</p-tab>
        <p-tab value="subscription"><i class="pi pi-credit-card mr"></i>Subscription & support</p-tab>
      </p-tablist>
      <p-tabpanels>
        <!-- company -->
        <p-tabpanel value="company">
          @if (c(); as c) {
            <div class="grid2 top">
              <p-card><ng-template #title>Profile</ng-template>
                <div class="stack">
                  <label class="field"><span>Company name</span><input pInputText [(ngModel)]="c.name" [disabled]="!canEdit()" fluid /></label>
                  <div class="grid2">
                    <label class="field"><span>City</span><input pInputText [(ngModel)]="c.city" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>GSTIN</span><input pInputText [(ngModel)]="c.gstin" [disabled]="!canEdit()" fluid /></label>
                  </div>
                  <label class="check"><p-toggleswitch [(ngModel)]="c.allow_support_login" [disabled]="!canEdit()" /> Allow BuildSuite support to sign in to help (always logged)</label>
                </div>
              </p-card>
              <p-card><ng-template #title>Modules</ng-template>
                <p class="muted small">Your {{ auth.session()?.limits?.plan }} plan includes {{ auth.session()?.limits?.modules }} module(s). Projects can only use enabled modules.</p>
                <p-selectbutton [options]="modules" [(ngModel)]="c.modules" [multiple]="true" optionLabel="label" optionValue="value" [disabled]="!canEdit()" />
              </p-card>
            </div>
            @if (canEdit()) { <div class="row right mt"><p-button label="Save" icon="pi pi-check" (onClick)="saveCompany()" /></div> }
          }
        </p-tabpanel>

        <!-- setup -->
        <p-tabpanel value="setup">
          @if (c(); as c) {
            <div class="grid2 top">
              <p-card><ng-template #title>Branches / offices</ng-template>
                <p-table [value]="setup.branches" size="small">
                  <ng-template #header><tr><th>Name</th><th>City</th><th>GSTIN</th><th></th></tr></ng-template>
                  <ng-template #body let-b let-i="rowIndex">
                    <tr><td><input placeholder="Branch name" pInputText [(ngModel)]="b.name" [disabled]="!canEdit()" /></td><td><input placeholder="City" pInputText [(ngModel)]="b.city" [disabled]="!canEdit()" /></td>
                      <td><input placeholder="GSTIN" pInputText [(ngModel)]="b.gstin" [disabled]="!canEdit()" /></td>
                      <td>@if (canEdit()) { <p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="setup.branches.splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/> }</td></tr>
                  </ng-template>
                  <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No branches yet — add your head office.</td></tr></ng-template>
      </p-table>
                @if (canEdit()) { <p-button label="Add branch" icon="pi pi-plus" size="small" [text]="true" (onClick)="setup.branches.push({ name: '', city: '' })" /> }
              </p-card>
              <p-card><ng-template #title>Currency, tax & numbering</ng-template>
                <div class="stack">
                  <div class="grid3">
                    <label class="field"><span>Currency</span><p-select [options]="currencies" [(ngModel)]="setup.currency" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Tax label</span><input pInputText [(ngModel)]="setup.tax_label" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Tax rate %</span><p-inputnumber [(ngModel)]="setup.tax_rate" [min]="0" [max]="100" [maxFractionDigits]="2" [disabled]="!canEdit()" fluid /></label>
                  </div>
                  <div class="grid2">
                    <label class="field"><span>Tax on invoices</span><p-select [options]="taxModes" optionLabel="label" optionValue="value" [(ngModel)]="setup.tax_mode" [disabled]="!canEdit()" fluid />
                      <small class="muted">GST: same state as the client → CGST + SGST, another state → IGST (from the client's GSTIN or state).</small></label>
                    <label class="field"><span>Company state</span><p-select [options]="states" [(ngModel)]="setup.state" [filter]="true" [showClear]="true" [disabled]="!canEdit()" fluid placeholder="From the GSTIN if set" /></label>
                  </div>
                  <label class="field"><span>Project number format</span>
                    <input pInputText [(ngModel)]="setup.prj" (ngModelChange)="preview()" [disabled]="!canEdit()" fluid />
                    <small class="muted">Use <code>{{ '{' }}n{{ '}' }}</code> (or <code>{{ '{' }}n:04d{{ '}' }}</code> for padding) and optional <code>{{ '{' }}year{{ '}' }}</code>. Next number: <strong>{{ nextNo() }}</strong></small></label>
                  <div class="grid2">
                    <label class="field"><span>Invoice number format</span><input pInputText [(ngModel)]="setup.inv" [disabled]="!canEdit()" fluid /></label>
                    <label class="field"><span>Credit note number format</span><input pInputText [(ngModel)]="setup.crn" [disabled]="!canEdit()" fluid /></label>
                  </div>
                </div>
              </p-card>
              <p-card><ng-template #title>Working days & holidays</ng-template>
                <div class="stack">
                  <small class="muted">Used for task lags, moving dependent tasks, delay days and the finish forecast — a Sunday or a holiday never counts as a day of work.</small>
                  <div class="row gap wrap">
                    @for (d of cal.weekdays; track $index; let i = $index) {
                      <label class="check"><p-checkbox [binary]="true" [ngModel]="cal.working_days.includes(i)" (onChange)="toggleDay(i, $event.checked)" [disabled]="!canEdit()" /> {{ d }}</label>
                    }
                  </div>
                  @for (h of cal.holidays; track $index; let i = $index) {
                    <div class="row gap"><input aria-label="Holiday date" title="Holiday date" pInputText type="date" [(ngModel)]="h.date" [disabled]="!canEdit()" />
                      <input pInputText [(ngModel)]="h.name" placeholder="Holiday name" class="grow" [disabled]="!canEdit()" />
                      @if (canEdit()) { <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="cal.holidays.splice(i, 1)" ariaLabel="Remove" pTooltip="Remove"/> }</div>
                  }
                  @if (canEdit()) {
                    <div class="row-between"><p-button label="Add holiday" icon="pi pi-plus" size="small" [text]="true" (onClick)="cal.holidays.push({ date: '', name: '' })" />
                      <p-button label="Save calendar" icon="pi pi-check" size="small" (onClick)="saveCalendar()" /></div>
                  }
                </div>
              </p-card>
            </div>
            @if (canEdit()) { <div class="row right mt"><p-button label="Save setup" icon="pi pi-check" (onClick)="saveSetup()" /></div> }
          }
          <p-card header="Document folders" styleClass="mt">
            <div class="stack">
              <small class="muted">Comma-separated. New projects and existing ones show these folders; “From the lead” and “Task files” are added automatically.</small>
              @for (k of folderKeys; track k.key) {
                <label class="field"><span>{{ k.label }}</span><input pInputText [(ngModel)]="folders[k.key]" [disabled]="!canEdit()" fluid /></label>
              }
            </div>
            @if (canEdit()) { <div class="row right"><p-button label="Save folders" icon="pi pi-check" size="small" (onClick)="saveFolders()" /></div> }
          </p-card>
          <p-card header="Online payments" styleClass="mt">
            <div class="stack">
              <small class="muted">Clients pay invoices from the portal or the invoice email. A payment becomes a receipt only when the provider confirms it.</small>
              <div class="grid2">
                <label class="field"><span>Provider</span><p-select [options]="payProviders()" optionLabel="label" optionValue="value" [(ngModel)]="pay.provider" [showClear]="true" placeholder="Off" [disabled]="!canEdit()" fluid appendTo="body" /></label>
                <label class="field"><span>Mode</span><p-select [options]="['test', 'live']" [(ngModel)]="pay.mode" [disabled]="!canEdit()" fluid appendTo="body" /></label>
              </div>
              @if (pay.provider === 'razorpay') {
                <div class="grid2">
                  <label class="field"><span>Key id</span><input pInputText [(ngModel)]="pay.key_id" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>Key secret</span><input pInputText type="password" [(ngModel)]="pay.key_secret" [placeholder]="pay.key_secret_set ? 'saved — type to replace' : ''" [disabled]="!canEdit()" fluid /></label>
                </div>
              }
              @if (pay.provider) {
                <label class="field"><span>Webhook secret</span><input pInputText type="password" [(ngModel)]="pay.webhook_secret" [placeholder]="pay.webhook_secret_set ? 'saved — type to replace' : ''" [disabled]="!canEdit()" fluid />
                  <small class="muted">Webhook address for the provider: <code>{{ origin }}{{ pay.webhook_url }}</code>@if (pay.provider === 'sandbox') { — sandbox moves no real money }</small></label>
              }
              <small [class.c-good]="pay.enabled" [class.muted]="!pay.enabled">{{ pay.enabled ? 'Online payments are on.' : 'Online payments are off.' }}</small>
            </div>
            @if (canEdit()) { <div class="row right"><p-button label="Save" icon="pi pi-check" size="small" (onClick)="savePay()" /></div> }
          </p-card>
          <p-card header="WhatsApp" styleClass="mt">
            <div class="stack">
              <small class="muted">Replies, transmittals, invoices and reminders also go by WhatsApp to contacts who opted in. Not set up: messages are only logged.</small>
              <label class="field"><span>Provider</span><p-select [options]="waProviders()" optionLabel="label" optionValue="value" [(ngModel)]="wa.provider" [showClear]="true" placeholder="Off (log only)" [disabled]="!canEdit()" fluid appendTo="body" /></label>
              @if (wa.provider === 'whatsapp_cloud') {
                <div class="grid2">
                  <label class="field"><span>Phone number id</span><input pInputText [(ngModel)]="wa.phone_number_id" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>Access token</span><input pInputText type="password" [(ngModel)]="wa.access_token" [placeholder]="wa.access_token_set ? 'saved — type to replace' : ''" [disabled]="!canEdit()" fluid /></label>
                </div>
              }
              @if (wa.provider) {
                <div class="grid2">
                  <label class="field"><span>App secret (webhook signature)</span><input pInputText type="password" [(ngModel)]="wa.app_secret" [placeholder]="wa.app_secret_set ? 'saved — type to replace' : ''" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>Verify token</span><input pInputText [(ngModel)]="wa.verify_token" [disabled]="!canEdit()" fluid /></label>
                </div>
                <small class="muted">Webhook address: <code>{{ origin }}{{ wa.webhook_url }}</code></small>
              }
              <small [class.c-good]="wa.ready" [class.muted]="!wa.ready">{{ wa.ready ? 'WhatsApp sending is on.' : 'WhatsApp is off: messages are logged, not sent.' }}</small>
            </div>
            @if (canEdit()) { <div class="row right"><p-button label="Save" icon="pi pi-check" size="small" (onClick)="saveWa()" /></div> }
          </p-card>
          <p-card header="SMS" styleClass="mt">
            <div class="stack">
              <small class="muted">SMS templates go out through your provider on DLT-registered templates (TRAI). Not set up: they are only logged.</small>
              <label class="field"><span>Provider</span><p-select [options]="smsProviders()" optionLabel="label" optionValue="value" [(ngModel)]="sms.provider" [showClear]="true" placeholder="Off (log only)" [disabled]="!canEdit()" fluid appendTo="body" /></label>
              @if (sms.provider === 'msg91') {
                <div class="grid2">
                  <label class="field"><span>Sender id (header)</span><input pInputText [(ngModel)]="sms.sender_id" maxlength="6" [disabled]="!canEdit()" fluid /></label>
                  <label class="field"><span>DLT entity id</span><input pInputText [(ngModel)]="sms.dlt_entity_id" [disabled]="!canEdit()" fluid /></label>
                </div>
                <label class="field"><span>Auth key</span><input pInputText type="password" [(ngModel)]="sms.auth_key" [placeholder]="sms.auth_key_set ? 'saved — type to replace' : ''" [disabled]="!canEdit()" fluid /></label>
              }
              <small [class.c-good]="sms.ready" [class.muted]="!sms.ready">{{ sms.ready ? 'SMS sending is on.' : 'SMS is off: messages are logged, not sent.' }}</small>
              @if (canEdit()) { <div class="row right"><p-button label="Save" icon="pi pi-check" size="small" (onClick)="saveSms()" /></div> }
            </div>
          </p-card>
          <p-card header="Daily site reports" styleClass="mt">
            <label class="field"><span>Cut-off time</span><input pInputText type="time" [(ngModel)]="site.cutoff" [disabled]="!canEdit()" />
              <small class="muted">No report by this time on a working day: the site supervisor is reminded; still none the next day: the PM.</small></label>
            @if (canEdit()) { <div class="row right"><p-button label="Save" icon="pi pi-check" size="small" (onClick)="saveSite()" /></div> }
          </p-card>
          <p-card header="Warehouses" styleClass="mt">
            <p class="small muted mt0">Goods can be received into a company warehouse instead of the site, then moved to projects (Project → Site → Stock).</p>
            @for (w of stores; track $index; let i = $index) {
              <div class="row gap mb-xs"><input pInputText [(ngModel)]="w.name" placeholder="Name" [disabled]="!canEdit()" />
                <input pInputText [(ngModel)]="w.address" placeholder="Address" [disabled]="!canEdit()" class="grow" />
                @if (canEdit()) { <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="stores.splice(i, 1)" ariaLabel="Remove warehouse" /> }</div>
            }
            @if (canEdit()) { <div class="row-between"><p-button label="Add warehouse" icon="pi pi-plus" size="small" [text]="true" (onClick)="stores.push({ name: '', address: '' })" />
              <p-button label="Save" icon="pi pi-check" size="small" (onClick)="saveStores()" /></div> }
          </p-card>
          @if (mk) {
          <p-card header="Product markup" styleClass="mt">
            <p class="small muted mt0">Added to a product's trade price to give the client's price: the client's own rule wins, then the category's, then the default.</p>
            <label class="field"><span>Default markup %</span><p-inputnumber [(ngModel)]="mk.default_pct" [min]="0" [max]="500" [disabled]="!canEdit()" /></label>
            <div class="grid3 mt-xs">
              @for (c of mkCats; track c) { <label class="field"><span>{{ c }} %</span><p-inputnumber [(ngModel)]="mk.by_category[c]" [min]="0" [max]="500" [disabled]="!canEdit()" placeholder="default" fluid /></label> }
            </div>
            <div class="small muted mt">Client rules</div>
            @for (r of mkClients; track $index; let i = $index) {
              <div class="row gap mb-xs"><p-select [options]="clientList" optionLabel="name" optionValue="id" [(ngModel)]="r.id" [filter]="true" [disabled]="!canEdit()" placeholder="Client" class="grow" />
                <p-inputnumber [(ngModel)]="r.pct" [min]="0" [max]="500" suffix="%" [disabled]="!canEdit()" />
                @if (canEdit()) { <p-button icon="pi pi-times" [text]="true" severity="secondary" (onClick)="mkClients.splice(i, 1)" ariaLabel="Remove rule" /> }</div>
            }
            @if (canEdit()) { <div class="row-between"><p-button label="Add a client rule" icon="pi pi-plus" size="small" [text]="true" (onClick)="addClientRule()" />
              <p-button label="Save" icon="pi pi-check" size="small" (onClick)="saveMarkup()" /></div> }
          </p-card>
          }
          <p-card header="Costs" styleClass="mt">
            <div class="grid2">
              <label class="field"><span>Site expense limit</span><p-inputnumber [(ngModel)]="fin.site_expense_limit" [min]="0" [disabled]="!canEdit()" fluid />
                <small class="muted">The most a Site Supervisor can log in one expense; each waits for the PM's approval.</small></label>
              <label class="field"><span>Overspend markup %</span><p-inputnumber [(ngModel)]="fin.overspend_markup_pct" [min]="0" [max]="100" [disabled]="!canEdit()" fluid />
                <small class="muted">Added when a client change takes a stage over budget and the client is charged for it.</small></label>
              <label class="field"><span>Purchase order approval limit</span><p-inputnumber [(ngModel)]="fin.po_approval_limit" [min]="0" [disabled]="!canEdit()" fluid />
                <small class="muted">A PO above this (before tax) waits for an Owner; within it and the budget, it is approved on submit.</small></label>
              <label class="field"><span>Over-delivery allowed %</span><p-inputnumber [(ngModel)]="fin.over_receipt_pct" [min]="0" [max]="100" [disabled]="!canEdit()" fluid />
                <small class="muted">How much more than ordered the site can receive on a PO line.</small></label>
              <label class="field"><span>Bill rate tolerance %</span><p-inputnumber [(ngModel)]="fin.match_rate_tolerance_pct" [min]="0" [max]="100" [minFractionDigits]="0" [maxFractionDigits]="2" [disabled]="!canEdit()" fluid />
                <small class="muted">A supplier bill's rate may differ this much from the PO before it goes on hold.</small></label>
              <label class="field"><span>Bill amount tolerance</span><p-inputnumber [(ngModel)]="fin.match_amount_tolerance" [min]="0" [disabled]="!canEdit()" fluid />
                <small class="muted">Rounding allowed on a bill's total against PO and receipts.</small></label>
              <label class="field"><span>Selection deposit %</span><p-inputnumber [(ngModel)]="fin.selection_deposit_pct" [min]="1" [max]="100" [disabled]="!canEdit()" fluid />
                <small class="muted">Asked from the client before a chosen product is ordered.</small></label>
              <label class="check"><p-checkbox [(ngModel)]="fin.require_selection_deposit" [binary]="true" [disabled]="!canEdit()" ariaLabel="Require the deposit" />
                Do not order a selection until its deposit is paid</label>
              <label class="field"><span>Client invoice reminders (days)</span><input pInputText [(ngModel)]="reminderText" [disabled]="!canEdit()" fluid placeholder="-3, 1, 7, 14" />
                <small class="muted">Days from the due date the client is reminded (minus = before it). The last one, 14+ days late, is the final reminder.</small></label>
            </div>
            @if (canEdit()) { <div class="row right"><p-button label="Save" icon="pi pi-check" size="small" (onClick)="saveFinance()" /></div> }
          </p-card>
        </p-tabpanel>

        <!-- templates -->
        <p-tabpanel value="templates">
          <div class="row-between mb">
            <span class="muted">New projects use the default template of each service. Durations set the default stage length.</span>
            @if (canEdit()) {
              <div class="row gap">
                @for (pr of presets(); track pr.key) { <p-button [label]="'Add ' + pr.name" icon="pi pi-plus" size="small" [outlined]="true" [disabled]="hasTemplate(pr.name)" (onClick)="addPreset(pr.key)" /> }
                <p-button label="New template" icon="pi pi-plus" size="small" (onClick)="editTemplate()" />
              </div>
            }
          </div>
          <div class="tpl-grid">
            @for (t of templates(); track t.id) {
              <p-card>
                <ng-template #title><div class="row-between"><span>{{ t.name }}</span>
                  @if (t.is_default) { <p-tag value="Default" severity="success" /> }</div></ng-template>
                <ng-template #subtitle>{{ svc[t.service] }} · {{ t.stages.length }} stages · {{ total(t) }} days</ng-template>
                <ol class="tpl-stages">@for (s of t.stages; track s.name) { <li>{{ s.name }} <small class="muted">{{ s.duration_days }} d{{ s.checklist?.length ? ' · ' + s.checklist.length + ' closing checks' : '' }}{{ s.client_signoff ? ' · client sign-off' : '' }}</small></li> }</ol>
                @if (canEdit()) {
                  <div class="row gap">
                    <p-button label="Edit" icon="pi pi-pencil" size="small" [text]="true" (onClick)="editTemplate(t)" />
                    @if (!t.is_default) {
                      <p-button label="Make default" icon="pi pi-star" size="small" [text]="true" (onClick)="makeDefault(t)" />
                      <p-button label="Delete" icon="pi pi-trash" size="small" severity="danger" [text]="true" (onClick)="deleteTemplate(t)" />
                    }
                  </div>
                }
              </p-card>
            }
          </div>
        </p-tabpanel>

        <p-tabpanel value="sales"><app-sales-settings /></p-tabpanel>
        <p-tabpanel value="proposals"><app-proposal-settings /></p-tabpanel>

        <!-- roles -->
        <p-tabpanel value="roles">
          <p class="muted">Adjust what each staff role can do. Defaults come from the product; your changes are stored separately and can be reset. The Owner always has full access.</p>
          @if (roles(); as r) {
            <div class="scroll-x">
              <p-table [value]="r.roles" size="small" styleClass="matrix">
                <ng-template #header><tr><th>Role</th>@for (a of r.areas; track a) { <th class="center cap">{{ a.replace('_', ' ') }}</th> }<th></th></tr></ng-template>
                <ng-template #body let-row>
                  <tr>
                    <td><strong>{{ row.label }}</strong> @if (hasOverrides(row)) { <p-tag value="custom" severity="warn" /> }</td>
                    @for (a of r.areas; track a) {
                      <td class="center">
                        @if (row.locked || !canEdit()) {
                          <span [class]="cellClass(row.effective[a])">{{ cell(row.effective[a]) }}</span>
                        } @else {
                          <button class="perm" [class]="cellClass(row.draft[a])" [class.changed]="(row.draft[a] || '') !== (row.defaults[a] || '')"
                                  (click)="cycle(row, a)" [title]="'Click to change · default: ' + cell(row.defaults[a])">{{ cell(row.draft[a]) }}</button>
                        }
                      </td>
                    }
                    <td class="nowrap">@if (!row.locked && canEdit()) {
                      <p-button label="Save" size="small" [text]="true" [disabled]="!dirty(row)" (onClick)="saveRole(row)" />
                      <p-button label="Reset" size="small" [text]="true" severity="secondary" [disabled]="!hasOverrides(row)" (onClick)="resetRole(row)" /> }</td>
                  </tr>
                </ng-template>
              </p-table>
            </div>
            <p class="muted small">✏️ read + write · 👁 read · — none. Changed cells are outlined. Changes apply to users on their next request.</p>
          }
        </p-tabpanel>

        <!-- audit -->
        <p-tabpanel value="field"><app-field-settings /></p-tabpanel>
        <p-tabpanel value="integrations"><app-integrations-settings /></p-tabpanel>
        <p-tabpanel value="subscription"><app-subscription /></p-tabpanel>
        <p-tabpanel value="audit">
          <p-table [value]="audit()" size="small" [paginator]="true" [rows]="15">
            <ng-template #header><tr><th>When</th><th>Who</th><th>Action</th><th>What</th><th>Changes</th></tr></ng-template>
            <ng-template #body let-a>
              <tr><td class="nowrap"><small>{{ a.at | date: 'short' }}</small></td><td>{{ a.user_name || '—' }}</td><td class="cap">{{ a.action }}</td>
                <td>{{ a.collection }} @if (a.note) { <small class="muted">· {{ a.note }}</small> }</td><td><small class="muted">{{ changed(a) }}</small></td></tr>
            </ng-template>
            <ng-template #emptymessage><tr><td colspan="20" class="muted center small">No changes recorded yet.</td></tr></ng-template>
      </p-table>
        </p-tabpanel>
      </p-tabpanels>
    </p-tabs>

    <p-dialog [header]="tf.id ? 'Edit template' : 'New template'" [modal]="true" [(visible)]="tplDlg" [style]="{ width: '36rem' }" [breakpoints]="{ '640px': '96vw' }">
      <div class="stack">
        <div class="grid2">
          <label class="field"><span>Name</span><input pInputText [(ngModel)]="tf.name" fluid /></label>
          <label class="field"><span>Service</span><p-select [options]="modules" [(ngModel)]="tf.service" optionLabel="label" optionValue="value" fluid appendTo="body" /></label>
        </div>
        <p-table [value]="tf.stages" size="small">
          <ng-template #header><tr><th>#</th><th>Stage <small class="muted">· closing checklist, one per line</small></th><th>Days</th><th></th></tr></ng-template>
          <ng-template #body let-s let-i="rowIndex">
            <tr><td>{{ i + 1 }}</td><td><input placeholder="Stage name" pInputText [(ngModel)]="s.name" fluid />
              <textarea pTextarea rows="2" [ngModel]="(s.checklist ?? []).join('\n')" (ngModelChange)="s.checklist = splitLines($event)" placeholder="Checks before this stage can close" class="mt-xs" fluid></textarea>
              <label class="check small"><p-checkbox [binary]="true" [(ngModel)]="s.client_signoff" /> Needs the client's sign-off</label></td>
              <td><p-inputnumber placeholder="Days" [(ngModel)]="s.duration_days" [min]="1" [max]="3650" [showButtons]="false" inputStyleClass="w-5" /></td>
              <td class="nowrap"><p-button icon="pi pi-arrow-up" [text]="true" size="small" [disabled]="i === 0" (onClick)="swap(i, i - 1)" ariaLabel="Move up" pTooltip="Move up"/>
                <p-button icon="pi pi-arrow-down" [text]="true" size="small" [disabled]="i === tf.stages.length - 1" (onClick)="swap(i, i + 1)" ariaLabel="Move down" pTooltip="Move down"/>
                <p-button icon="pi pi-trash" [text]="true" size="small" severity="danger" (onClick)="tf.stages.splice(i, 1)" ariaLabel="Delete" pTooltip="Delete"/></td></tr>
          </ng-template>
        </p-table>
        <p-button label="Add stage" icon="pi pi-plus" size="small" [text]="true" (onClick)="tf.stages.push({ name: '', duration_days: 14, checklist: [], client_signoff: false })" />
        <label class="check"><p-toggleswitch [(ngModel)]="tf.is_default" /> Default for this service</label>
        <div class="row gap right"><p-button label="Save template" icon="pi pi-check" (onClick)="saveTemplate()" /></div>
      </div>
    </p-dialog>
  `,
})
export class SettingsComponent implements OnInit {
  auth = inject(AuthService);
  private api = inject(Api);
  c = signal<any>(null);
  audit = signal<any[]>([]);
  templates = signal<any[]>([]);
  presets = signal<any[]>([]);
  roles = signal<any>(null);
  nextNo = signal('');
  canEdit = computed(() => this.auth.can('settings', 'rw'));
  svc = SERVICE_LABEL;
  modules = Object.entries(SERVICE_LABEL).map(([value, label]) => ({ value, label }));
  currencies = ['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD', 'AUD'];
  setup: any = { branches: [] };
  cal: any = { weekdays: [], working_days: [], holidays: [] };
  fin: any = {};
  folders: Record<string, string> = {};
  site: any = { cutoff: '19:00' };
  pay: any = {};
  wa: any = {};
  origin = window.location.origin;
  folderKeys = [{ key: 'all', label: 'Every project' }, { key: 'architecture', label: 'Architecture' }, { key: 'construction', label: 'Construction' },
    { key: 'interior', label: 'Interior design' }];
  tplDlg = false;
  tf: any = { stages: [] };

  async ngOnInit() {
    await Promise.all([this.loadCompany(), this.loadTemplates(), this.loadRoles(), this.loadAudit(), this.loadCalendar(), this.loadFinance(), this.loadFolders(), this.loadSite(), this.loadPay(), this.loadWa()]);
  }

  async loadCalendar() {
    const c = await this.api.get('/settings/calendar');
    this.cal = { weekdays: c.weekdays, working_days: [...c.working_days], holidays: c.holidays.map((h: any) => ({ ...h })) };
  }

  toggleDay(i: number, on: boolean) {
    this.cal.working_days = on ? [...new Set([...this.cal.working_days, i])].sort() : this.cal.working_days.filter((d: number) => d !== i);
  }

  waProviders() {
    return Object.entries(this.wa.providers ?? {}).map(([value, label]) => ({ value, label }));
  }

  async loadWa() {
    try {
      this.wa = await this.api.get('/settings/messaging');
    this.loadSms();
    } catch {
      this.wa = {};
    }
  }

  async saveWa() {
    const { provider, phone_number_id, access_token, app_secret, verify_token } = this.wa;
    this.wa = await this.api.put('/settings/messaging', { provider: provider || null, phone_number_id, access_token, app_secret, verify_token }, 'Saved');
  }

  payProviders() {
    return Object.entries(this.pay.providers ?? {}).map(([value, label]) => ({ value, label }));
  }

  async loadPay() {
    try {
      this.pay = await this.api.get('/settings/payments');
    } catch {
      this.pay = {};
    }
  }

  async savePay() {
    const { provider, mode, key_id, key_secret, webhook_secret } = this.pay;
    this.pay = await this.api.put('/settings/payments', { provider: provider || null, mode, key_id, key_secret, webhook_secret }, 'Saved');
  }

  async loadSite() {
    this.site = await this.api.get('/settings/site');
  }

  async saveSite() {
    this.site = await this.api.put('/settings/site', { cutoff: this.site.cutoff }, 'Saved');
  }

  async loadFolders() {
    const f = await this.api.get('/settings/document-folders');
    this.folders = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, (v as string[]).join(', ')]));
  }

  async saveFolders() {
    const body = Object.fromEntries(Object.entries(this.folders).map(([k, v]) => [k, v.split(',').map((x) => x.trim()).filter(Boolean)]));
    await this.api.put('/settings/document-folders', body, 'Folders saved');
    await this.loadFolders();
  }

  mk: any = null;
  mkCats: string[] = [];
  mkClients: any[] = [];
  clientList: any[] = [];

  async loadMarkup() {
    try {
      const m = await this.api.get('/settings/markup');
      this.mkCats = (await this.api.get('/rates?kind=product')).work_types ?? [];
      this.mkClients = Object.entries(m.by_client ?? {}).map(([id, pct]) => ({ id, pct }));
      const c = await this.api.get('/contacts');
      this.clientList = (Array.isArray(c) ? c : c.contacts ?? []).filter((x: any) => (x.types ?? []).includes('client')).map((x: any) => ({ id: x.id, name: x.name }));
      this.mk = { ...m, by_category: { ...(m.by_category ?? {}) } };
    } catch {
      this.mk = null;  // roles that do not see costs
    }
  }

  addClientRule() {
    this.mkClients.push({ id: null, pct: this.mk.default_pct });
  }

  async saveMarkup() {
    const by_category = Object.fromEntries(Object.entries(this.mk.by_category).filter(([, v]) => v !== null && v !== undefined && v !== ''));
    const by_client = Object.fromEntries(this.mkClients.filter((r) => r.id && r.pct !== null).map((r) => [r.id, r.pct]));
    await this.api.put('/settings/markup', { default_pct: this.mk.default_pct, by_category, by_client }, 'Markup saved');
    await this.loadMarkup();
  }

  stores: any[] = [];

  async loadStores() {
    this.stores = (await this.api.get('/settings/warehouses')).map((w: any) => ({ ...w }));
  }

  async saveStores() {
    this.stores = await this.api.put('/settings/warehouses', { warehouses: this.stores.filter((w) => w.name?.trim()) }, 'Warehouses saved');
  }

  async loadFinance() {
    this.fin = await this.api.get('/finance/settings');
    this.loadStores();
    this.loadMarkup();
    this.reminderText = (this.fin.client_reminder_days ?? []).join(', ');
  }

  async saveFinance() {
    this.fin = await this.api.put('/finance/settings', { site_expense_limit: this.fin.site_expense_limit, overspend_markup_pct: this.fin.overspend_markup_pct,
      po_approval_limit: this.fin.po_approval_limit, over_receipt_pct: this.fin.over_receipt_pct,
      match_rate_tolerance_pct: this.fin.match_rate_tolerance_pct, match_amount_tolerance: this.fin.match_amount_tolerance,
      selection_deposit_pct: this.fin.selection_deposit_pct, require_selection_deposit: !!this.fin.require_selection_deposit,
      client_reminder_days: this.reminderText.split(/[,\s]+/).filter(Boolean).map((x) => parseInt(x, 10)).filter((x) => !isNaN(x)) }, 'Saved');
    this.reminderText = (this.fin.client_reminder_days ?? []).join(', ');
  }

  reminderText = '';
  startTab = ['subscription', 'support'].includes(new URLSearchParams(location.search).get('tab') ?? '') ? 'subscription' : 'company';
  taxModes = [{ label: 'One tax rate', value: 'single' }, { label: 'GST (CGST + SGST / IGST)', value: 'gst' }];
  states = Object.values(STATE_NAMES).sort();

  sms: any = {};

  smsProviders() {
    return Object.entries(this.sms.providers ?? {}).map(([value, label]) => ({ value, label }));
  }

  async loadSms() {
    try { this.sms = await this.api.get('/settings/sms'); } catch { this.sms = {}; }
  }

  async saveSms() {
    const { provider, sender_id, dlt_entity_id, auth_key } = this.sms;
    this.sms = await this.api.put('/settings/sms', { provider: provider || null, sender_id, dlt_entity_id, ...(auth_key ? { auth_key } : {}) }, 'Saved');
  }

  async saveCalendar() {
    await this.api.put('/settings/calendar', { working_days: this.cal.working_days, holidays: this.cal.holidays.filter((h: any) => h.date || h.name) },
      'Working days saved');
    await this.loadCalendar();
  }

  splitLines(v: string) {
    return v.split('\n').map((x) => x.trim()).filter(Boolean);
  }

  async loadCompany() {
    const c = await this.api.get('/company');
    this.c.set(c);
    this.setup = { branches: (c.branches ?? []).map((b: any) => ({ ...b })), currency: c.currency ?? 'INR', tax_label: c.tax_label ?? 'GST',
      tax_rate: c.tax_rate ?? 18, prj: c.numbering?.PRJ ?? 'PRJ-{n:04d}', tax_mode: c.tax_mode ?? 'single', state: c.state ? STATE_NAMES[c.state] : null,
      inv: c.numbering?.INV ?? 'INV-{n:04d}', crn: c.numbering?.CRN ?? 'CRN-{n:04d}' };
    this.preview();
  }

  async loadTemplates() {
    const r = await this.api.get('/stage_templates');
    this.templates.set(r.templates);
    this.presets.set(r.presets);
  }

  async loadRoles() {
    const r = await this.api.get('/roles');
    r.roles.forEach((row: any) => (row.draft = { ...row.effective }));
    this.roles.set(r);
  }

  async loadAudit() {
    this.audit.set(await this.api.get('/audit'));
  }

  changed(a: any) {
    return a.changes ? Object.keys(a.changes).filter((k) => k !== 'password').join(', ') : '';
  }

  async saveCompany() {
    const c = this.c();
    await this.api.put('/company', { name: c.name, city: c.city, gstin: c.gstin, modules: c.modules, allow_support_login: c.allow_support_login }, 'Settings saved');
    await this.auth.refresh();
    await Promise.all([this.loadCompany(), this.loadAudit()]);
  }

  async preview() {
    try {
      this.nextNo.set((await this.api.get(`/company/numbering/preview?format=${encodeURIComponent(this.setup.prj)}`)).next);
    } catch {
      this.nextNo.set('invalid format');
    }
  }

  async saveSetup() {
    await this.api.put('/company/setup', { branches: this.setup.branches, currency: this.setup.currency, tax_label: this.setup.tax_label,
      tax_rate: this.setup.tax_rate, tax_mode: this.setup.tax_mode, state: this.setup.state,
      numbering: { PRJ: this.setup.prj, INV: this.setup.inv, CRN: this.setup.crn } }, 'Setup saved');
    await this.auth.refresh();
    await Promise.all([this.loadCompany(), this.loadAudit()]);
  }

  // templates
  total(t: any) {
    return t.stages.reduce((a: number, s: any) => a + s.duration_days, 0);
  }

  hasTemplate(name: string) {
    return this.templates().some((t) => t.name === name);
  }

  async addPreset(key: string) {
    await this.api.post('/stage_templates', { preset: key }, 'Template added');
    await this.loadTemplates();
  }

  editTemplate(t?: any) {
    this.tf = t ? { id: t.id, name: t.name, service: t.service, is_default: t.is_default, stages: t.stages.map((s: any) => ({ ...s })) }
      : { name: '', service: 'architecture', is_default: false, stages: [{ name: '', duration_days: 14, checklist: [], client_signoff: true }] };
    this.tplDlg = true;
  }

  swap(i: number, j: number) {
    const s = this.tf.stages;
    [s[i], s[j]] = [s[j], s[i]];
  }

  async saveTemplate() {
    const body = { name: this.tf.name, service: this.tf.service, stages: this.tf.stages, is_default: this.tf.is_default };
    if (this.tf.id) await this.api.put(`/stage_templates/${this.tf.id}`, body, 'Template saved');
    else await this.api.post('/stage_templates', body, 'Template created');
    this.tplDlg = false;
    await this.loadTemplates();
  }

  async makeDefault(t: any) {
    await this.api.put(`/stage_templates/${t.id}`, { is_default: true }, `${t.name} is now the default`);
    await this.loadTemplates();
  }

  async deleteTemplate(t: any) {
    await this.api.del(`/stage_templates/${t.id}`, 'Template deleted');
    await this.loadTemplates();
  }

  // roles
  cell(v?: string) {
    return v === 'rw' ? '✏️' : v === 'r' ? '👁' : '—';
  }

  cellClass(v?: string) {
    return 'perm-cell ' + (v === 'rw' ? 'c-ok' : v === 'r' ? 'c-warn' : 'muted');
  }

  cycle(row: any, area: string) {
    const order = ['', 'r', 'rw'];
    row.draft[area] = order[(order.indexOf(row.draft[area] ?? '') + 1) % 3];
    this.roles.set({ ...this.roles() });
  }

  dirty(row: any) {
    return this.roles().areas.some((a: string) => (row.draft[a] ?? '') !== (row.effective[a] ?? ''));
  }

  hasOverrides(row: any) {
    return Object.keys(row.overrides ?? {}).length > 0;
  }

  async saveRole(row: any) {
    const perms: any = {};
    for (const a of this.roles().areas) perms[a] = row.draft[a] ?? '';
    await this.api.put(`/roles/${row.role}`, { perms }, `${row.label} permissions saved`);
    await Promise.all([this.loadRoles(), this.loadAudit()]);
  }

  async resetRole(row: any) {
    await this.api.put(`/roles/${row.role}`, { perms: {} }, `${row.label} reset to default`);
    await Promise.all([this.loadRoles(), this.loadAudit()]);
  }
}
