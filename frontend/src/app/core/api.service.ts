import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { MessageService } from 'primeng/api';
import { errorText } from './auth.interceptor';
import { HANDLED } from './error-handler';

/** Promise-based API helper. Mutations show a toast on failure and re-throw so callers can keep dialogs open. */
@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);
  private toast = inject(MessageService);

  get<T = any>(url: string) {
    return firstValueFrom(this.http.get<T>('/api' + url));
  }

  async send<T = any>(method: 'POST' | 'PUT' | 'DELETE', url: string, body?: unknown, okMessage?: string): Promise<T> {
    try {
      const res = await firstValueFrom(this.http.request<T>(method, '/api' + url, { body }));
      if (okMessage) this.toast.add({ severity: 'success', summary: okMessage, life: 2500 });
      return res;
    } catch (e) {
      this.toast.add({ severity: 'error', summary: 'Not saved', detail: errorText(e), life: 5000 });
      (e as any)[HANDLED] = true;
      throw e;
    }
  }

  /** Like send, but no error toast: the caller decides (e.g. ask for a delay reason on a 409, then send again). */
  raw<T = any>(method: 'post' | 'put' | 'delete', url: string, body?: unknown): Promise<T> {
    return firstValueFrom(this.http.request<T>(method.toUpperCase(), '/api' + url, { body: body ?? {} }));
  }

  toastError(e: unknown) {
    this.toast.add({ severity: 'error', summary: 'Not saved', detail: errorText(e), life: 5000 });
    (e as any)[HANDLED] = true;
  }

  post<T = any>(url: string, body?: unknown, ok?: string) {
    return this.send<T>('POST', url, body ?? {}, ok);
  }

  put<T = any>(url: string, body?: unknown, ok?: string) {
    return this.send<T>('PUT', url, body ?? {}, ok);
  }

  del<T = any>(url: string, ok?: string) {
    return this.send<T>('DELETE', url, undefined, ok);
  }

  async upload(file: File, portal = false): Promise<{ key: string; name: string; size: number; url: string }> {
    const form = new FormData();
    form.append('file', file);
    try {
      return await firstValueFrom(this.http.post<any>(portal ? '/api/portal/uploads' : '/api/uploads', form));
    } catch (e) {
      this.toast.add({ severity: 'error', summary: 'Upload failed', detail: errorText(e) });
      (e as any)[HANDLED] = true;
      throw e;
    }
  }

  /** Save an authenticated download (CSV export, import template) under `filename`. */
  async download(url: string, filename: string) {
    const blob = await firstValueFrom(this.http.get('/api' + url, { responseType: 'blob' }));
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /** Multipart POST of one file to an API endpoint (e.g. the lead import); shows errors like other writes. */
  async postFile<T = any>(url: string, file: File): Promise<T> {
    const form = new FormData();
    form.append('file', file);
    try {
      return await firstValueFrom(this.http.post<T>('/api' + url, form));
    } catch (e) {
      this.toast.add({ severity: 'error', summary: 'Not imported', detail: errorText(e), life: 5000 });
      (e as any)[HANDLED] = true;
      throw e;
    }
  }

  /** Files need the bearer token, so they are fetched and opened as a blob. */
  async openFile(url: string) {
    const blob = await firstValueFrom(this.http.get(url, { responseType: 'blob' }));
    window.open(URL.createObjectURL(blob), '_blank');
  }
}

export const SERVICE_LABEL: Record<string, string> = { architecture: 'Architecture', construction: 'Construction', interior: 'Interior design' };
export const SERVICE_COLOR: Record<string, string> = { architecture: '#6366f1', construction: '#f59e0b', interior: '#14b8a6' };
export const STATUS_SEVERITY: Record<string, 'success' | 'info' | 'warn' | 'danger' | 'secondary' | 'contrast'> = {
  planning: 'info', active: 'success', on_hold: 'warn', completed: 'contrast', cancelled: 'secondary',
  not_started: 'secondary', in_progress: 'info', done: 'success', todo: 'secondary', blocked: 'danger',
  pending: 'warn', achieved: 'success', open: 'warn', closed: 'secondary',
  expired: 'danger', expiring: 'warn', valid: 'success', no_expiry: 'secondary',
};

export function label(v?: string | null) {
  return (v ?? '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

export function money(v: number | null | undefined, currency = 'INR') {
  if (v == null) return '—';
  return new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en', { style: 'currency', currency, maximumFractionDigits: 0 }).format(v);
}
