/** Phase L block 1 — the phone's own store for the field app (IndexedDB): the day's data (bootstrap), the queue of
 *  what was recorded offline, and the photos taken offline (as blobs until they are uploaded). */
const DB_NAME = 'bs-field';
const VERSION = 1;

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
      if (!db.objectStoreNames.contains('ops')) db.createObjectStore('ops', { keyPath: 'op_id' });
      if (!db.objectStoreNames.contains('blobs')) db.createObjectStore('blobs');
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T> {
  const db = await open();
  return new Promise<T>((resolve, reject) => {
    const t = db.transaction(store, mode);
    const s = t.objectStore(store);
    const req = fn(s);
    t.oncomplete = () => resolve(req ? (req as IDBRequest<T>).result : (undefined as T));
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

export interface QueuedOp {
  op_id: string;
  kind: 'site_report' | 'attendance' | 'snag' | 'snag_fixed' | 'incident' | 'inspection';
  project_id?: string;
  project_name?: string;
  label: string;
  data: any;
  /** photos taken offline: blob ids, swapped for file keys when uploaded */
  blobs: string[];
  made_at: string;
  state: 'queued' | 'failed';
  error?: string;
}

export const OfflineStore = {
  get: <T = any>(key: string) => tx<T>('kv', 'readonly', (s) => s.get(key)),
  set: (key: string, v: any) => tx('kv', 'readwrite', (s) => s.put(v, key)),
  ops: () => tx<QueuedOp[]>('ops', 'readonly', (s) => s.getAll()),
  putOp: (op: QueuedOp) => tx('ops', 'readwrite', (s) => s.put(op)),
  delOp: (id: string) => tx('ops', 'readwrite', (s) => s.delete(id)),
  putBlob: (id: string, b: Blob) => tx('blobs', 'readwrite', (s) => s.put(b, id)),
  blob: (id: string) => tx<Blob | undefined>('blobs', 'readonly', (s) => s.get(id)),
  delBlob: (id: string) => tx('blobs', 'readwrite', (s) => s.delete(id)),
};

export function newId(prefix = 'op') {
  const r = crypto.getRandomValues(new Uint8Array(10));
  return `${prefix}-${Date.now().toString(36)}-${Array.from(r, (b) => b.toString(16).padStart(2, '0')).join('')}`;
}

/** Where the phone is (for photo tags); resolves null quickly when there is no fix or no permission. */
export function here(): Promise<{ lat: number; lng: number; accuracy_m: number } | null> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    const done = setTimeout(() => resolve(null), 6000);
    navigator.geolocation.getCurrentPosition(
      (p) => { clearTimeout(done); resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy) }); },
      () => { clearTimeout(done); resolve(null); },
      { enableHighAccuracy: true, timeout: 5000, maximumAge: 60000 });
  });
}

/** A phone photo shrunk to at most 1600 px (a site photo does not need 12 MP, and a weak signal thanks you). */
export async function shrink(file: File, max = 1600): Promise<Blob> {
  if (!file.type.startsWith('image/')) return file;
  try {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const c = document.createElement('canvas');
    c.width = Math.round(bmp.width * k);
    c.height = Math.round(bmp.height * k);
    c.getContext('2d')!.drawImage(bmp, 0, 0, c.width, c.height);
    return await new Promise<Blob>((res) => c.toBlob((b) => res(b ?? file), 'image/jpeg', 0.82));
  } catch {
    return file;
  }
}
