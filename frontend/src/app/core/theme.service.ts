import { Injectable, signal } from '@angular/core';

/** Light / dark mode, remembered per browser. */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly dark = signal(false);

  constructor() {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem('bs.theme');
    } catch {
      /* storage unavailable */
    }
    this.apply(saved ? saved === 'dark' : window.matchMedia?.('(prefers-color-scheme: dark)').matches);
  }

  toggle() {
    this.apply(!this.dark());
    try {
      localStorage.setItem('bs.theme', this.dark() ? 'dark' : 'light');
    } catch {
      /* storage unavailable */
    }
  }

  private apply(dark: boolean) {
    this.dark.set(dark);
    document.documentElement.classList.toggle('app-dark', dark);
  }
}
