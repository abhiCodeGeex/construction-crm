/* Phase L block 1 — the service worker that lets the field app open without a signal.
 * - the app shell (index.html) is fetched from the network first and kept, so an update is picked up when online;
 * - the hashed JS / CSS / fonts / icons are kept once fetched (a new build has new names);
 * - the API is never cached here (the field app keeps its own data in IndexedDB) — offline API calls simply fail.
 */
const SHELL = 'bs-shell-v1';
const ASSETS = 'bs-assets-v1';

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['/', '/index.html', '/manifest.webmanifest', '/icon.svg']).catch(() => null)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, ASSETS].includes(k)).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  if (req.mode === 'navigate') {  // any app route: network first, the kept shell when offline
    e.respondWith(fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(SHELL).then((c) => c.put('/index.html', copy));
      return res;
    }).catch(() => caches.match('/index.html')));
    return;
  }
  if (/\.(js|css|woff2?|ttf|svg|png|ico|webmanifest)$/.test(url.pathname)) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(ASSETS).then((c) => c.put(req, copy));
      }
      return res;
    })));
  }
});
