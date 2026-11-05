import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { Level, SaSession, Session } from './models';

const KEY = 'bs.session';
const SA_KEY = 'bs.sa';

function load<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function save(key: string, value: unknown) {
  try {
    if (value) localStorage.setItem(key, JSON.stringify(value));
    else localStorage.removeItem(key);
  } catch {
    /* storage unavailable: session lives in memory only */
  }
}

/** Company users (staff + portal) and Super Admin sessions are kept separate so one never leaks into the other. */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  readonly session = signal<Session | null>(load<Session>(KEY));
  readonly sa = signal<SaSession | null>(load<SaSession>(SA_KEY));
  /** Why the last session ended (e.g. the password was changed elsewhere); shown once on the sign-in page. */
  readonly signedOutReason = signal('');

  readonly user = computed(() => this.session()?.user ?? null);
  readonly company = computed(() => this.session()?.company ?? null);
  readonly isStaff = computed(() => this.user()?.kind === 'staff');
  readonly isExternal = computed(() => this.user()?.kind === 'external');

  roleLabel(role?: string) {
    return (role && this.session()?.roles.labels[role]) || role || '';
  }

  /** can('users') = read, can('users', 'rw') = write */
  can(area: string, level: Level = 'r'): boolean {
    const have = this.session()?.permissions?.[area];
    if (!have) return false;
    return level === 'r' ? have.includes('r') : have.includes('w');
  }

  saCan(area: string, level: Level = 'r'): boolean {
    const have = this.sa()?.permissions?.[area];
    if (!have) return false;
    return level === 'r' ? have.includes('r') : have.includes('w');
  }

  async login(email: string, password: string) {
    const s = await firstValueFrom(this.http.post<Session>('/api/auth/login', { email, password }));
    this.setSession(s);
    return s;
  }

  async signup(data: Record<string, unknown>) {
    const s = await firstValueFrom(this.http.post<Session>('/api/auth/signup', data));
    this.setSession(s);
    return s;
  }

  /** Re-reads role, permissions and company from the server (a role change applies immediately). */
  async refresh() {
    if (!this.session()) return;
    const me = await firstValueFrom(this.http.get<Omit<Session, 'token'>>('/api/auth/me'));
    this.setSession({ ...me, token: this.session()!.token });
  }

  setSession(s: Session | null) {
    this.session.set(s);
    save(KEY, s);
  }

  homeFor(s = this.session()) {
    return s?.user.kind === 'external' ? '/portal' : '/app';
  }

  logout(redirect = true) {
    this.setSession(null);
    if (redirect) this.router.navigateByUrl('/login');
  }

  // ---------- Super Admin ----------
  async saLogin(email: string, password: string, code?: string) {
    const res = await firstValueFrom(
      this.http.post<SaSession & { two_factor_required?: boolean; two_factor_setup?: boolean; secret?: string; otpauth?: string }>(
        '/api/sa/login', { email, password, code }),
    );
    // first sign-in: set up an authenticator app (secret + QR link), then confirm with its code
    if (res.two_factor_setup) return { twoFactor: true, setup: { secret: res.secret!, otpauth: res.otpauth! } };
    if (res.two_factor_required) return { twoFactor: true, setup: null };
    this.sa.set(res);
    save(SA_KEY, res);
    return { twoFactor: false, setup: null };
  }

  saLogout(redirect = true) {
    this.sa.set(null);
    save(SA_KEY, null);
    if (redirect) this.router.navigateByUrl('/sa/login');
  }
}
