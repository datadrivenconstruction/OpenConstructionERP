// Design module (ERP side of the design editor link).
/**
 * The browser editor inside the ERP: which payload this ERP has (the editor bundle `ddc-web-editor/1`, or the
 * generator already in the module), and loading it in the background for people who said yes to the design offer.
 * Nothing is fetched without that yes; the choice can be changed on the editor page.
 */
import { useSyncExternalStore } from 'react';
import { BRIDGE_VERSION, bundleBytes, checkBundle, sha256Hex, type EditorBundle } from '../bridge/protocol';

export const CONSENT_KEY = 'oe_design_web_editor';
export const CACHE_NAME = 'oe-design-editor-v1';
/** Size of wasm/ddc_web.wasm (checked by webEditor.test.ts against the file). */
export const ENGINE_BYTES = 635_678;

export type Consent = 'yes' | 'no' | null;

export function readConsent(): Consent {
  try {
    const v = localStorage.getItem(CONSENT_KEY);
    return v === 'yes' || v === 'no' ? v : null;
  } catch {
    return null;
  }
}

export function writeConsent(c: 'yes' | 'no'): void {
  try { localStorage.setItem(CONSENT_KEY, c); } catch { /* private mode: asked again next time */ }
}

export interface Asset { url: string; bytes: number; sha256?: string }
export type Payload =
  | { kind: 'editor'; version: string; entryUrl: string; assets: Asset[]; bundle: EditorBundle }
  | { kind: 'engine'; version: string; assets: Asset[] };

/** Where the editor bundle manifest lives: https, or a path on this ERP. Anything else is ignored. */
export function bundleUrl(env: Record<string, string | undefined>, origin: string): string | null {
  const raw = (env.VITE_DESIGN_WEB_EDITOR_URL ?? '').trim();
  if (!raw) return null;
  try {
    const url = new URL(raw, origin);
    if (url.protocol === 'https:' || url.origin === origin) return url.href;
  } catch { /* not a URL */ }
  return null;
}

export function enginePayload(engineUrl: string, origin: string): Payload {
  return { kind: 'engine', version: 'ddc_web', assets: [{ url: new URL(engineUrl, origin).href, bytes: ENGINE_BYTES }] };
}

/**
 * The editor when this ERP publishes a bundle that speaks our bridge major, else the module's generator.
 * A missing, malformed or incompatible manifest falls back quietly (the reason is returned for the page).
 */
export async function findPayload(opts: {
  env: Record<string, string | undefined>; origin: string; engineUrl: string; fetchFn?: typeof fetch;
}): Promise<Payload & { fallback?: string }> {
  const engine = enginePayload(opts.engineUrl, opts.origin);
  const at = bundleUrl(opts.env, opts.origin);
  if (!at) return engine;
  try {
    const r = await (opts.fetchFn ?? fetch)(at, { credentials: 'omit' });
    if (!r.ok) return { ...engine, fallback: `HTTP ${r.status}` };
    const doc: unknown = await r.json();
    const errors = checkBundle(doc);
    if (errors.length) return { ...engine, fallback: `manifest: ${errors[0]!.pointer} ${errors[0]!.code}` };
    const b = doc as EditorBundle;
    if (!b.bridge.includes(BRIDGE_VERSION)) return { ...engine, fallback: `bridge ${b.bridge.join(',')}` };
    return {
      kind: 'editor', version: b.version, bundle: b, entryUrl: new URL(b.entry, at).href,
      assets: b.files.map((f) => ({ url: new URL(f.path, at).href, bytes: f.bytes, sha256: f.sha256 })),
    };
  } catch (e) {
    return { ...engine, fallback: e instanceof Error ? e.message : String(e) };
  }
}

export function payloadBytes(p: Payload): number {
  return p.kind === 'editor' ? bundleBytes(p.bundle) : p.assets.reduce((s, a) => s + a.bytes, 0);
}

/* ── Background load ─────────────────────────────────────────────────── */

export type LoadState =
  | { status: 'off' }
  | { status: 'waiting'; total: number }
  | { status: 'loading'; done: number; total: number }
  | { status: 'ready'; total: number; cached: boolean }
  | { status: 'failed'; reason: string };

let state: LoadState = { status: 'off' };
const listeners = new Set<() => void>();
const set = (s: LoadState) => { state = s; listeners.forEach((l) => l()); };
export const loadState = () => state;
export function useLoadState(): LoadState {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, loadState, loadState);
}

async function readAll(r: Response, onChunk: (n: number) => void): Promise<Uint8Array> {
  if (!r.body) {
    const b = new Uint8Array(await r.arrayBuffer());
    onChunk(b.byteLength);
    return b;
  }
  const reader = r.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    size += value.byteLength;
    onChunk(value.byteLength);
  }
  const out = new Uint8Array(size);
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.byteLength; }
  return out;
}

/** Fetch every asset not yet in the cache, check its hash, keep it. Progress counts cached bytes as done. */
export async function prefetch(p: Payload, opts: {
  fetchFn?: typeof fetch; caches?: CacheStorage | null; onProgress?: (done: number, total: number) => void;
} = {}): Promise<{ cached: boolean }> {
  const total = payloadBytes(p);
  const store = opts.caches === undefined ? (typeof caches === 'undefined' ? null : caches) : opts.caches;
  const cache = store ? await store.open(CACHE_NAME) : null;
  let done = 0;
  let allCached = true;
  for (const a of p.assets) {
    if (cache && (await cache.match(a.url))) {
      done += a.bytes;
      opts.onProgress?.(done, total);
      continue;
    }
    allCached = false;
    const r = await (opts.fetchFn ?? fetch)(a.url, { credentials: 'omit' });
    if (!r.ok) throw new Error(`${a.url}: HTTP ${r.status}`);
    const bytes = await readAll(r, (n) => { done += n; opts.onProgress?.(Math.min(done, total), total); });
    if (a.sha256 && (await sha256Hex(bytes)) !== a.sha256) throw new Error(`${a.url}: SHA-256 does not match the manifest`);
    await cache?.put(a.url, new Response(bytes as BodyInit, { headers: { 'Content-Type': r.headers.get('Content-Type') ?? 'application/octet-stream' } }));
  }
  return { cached: allCached };
}

type Idle = (cb: () => void) => void;
const idle: Idle = (cb) => {
  const ric = (globalThis as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback;
  if (ric) ric(cb, { timeout: 10_000 });
  else setTimeout(cb, 2_000);
};

let running: Promise<void> | null = null;

/**
 * Load the payload in idle time when, and only when, the person said yes. Safe to call often: one run at a time,
 * and a finished run is not repeated in the same page.
 */
export function scheduleBackgroundLoad(opts: {
  payload: () => Promise<Payload>; consent?: Consent; idle?: Idle; fetchFn?: typeof fetch; caches?: CacheStorage | null;
}): Promise<void> | null {
  if ((opts.consent ?? readConsent()) !== 'yes') return null;
  if (running) return running;
  if (state.status === 'ready') return Promise.resolve();
  running = new Promise<void>((resolve) => {
    (opts.idle ?? idle)(() => {
      void (async () => {
        try {
          const p = await opts.payload();
          const total = payloadBytes(p);
          set({ status: 'waiting', total });
          const r = await prefetch(p, {
            fetchFn: opts.fetchFn, caches: opts.caches,
            onProgress: (done, t) => set({ status: 'loading', done, total: t }),
          });
          set({ status: 'ready', total, cached: r.cached });
        } catch (e) {
          set({ status: 'failed', reason: e instanceof Error ? e.message : String(e) });
        } finally {
          running = null;
          resolve();
        }
      })();
    });
  });
  return running;
}

/** Switched off: stop showing progress; what is cached stays until the browser clears it. */
export function stopBackgroundLoad(): void {
  set({ status: 'off' });
}

/** Test hook. */
export function resetLoadState(): void {
  running = null;
  set({ status: 'off' });
}

export function megabytes(bytes: number): string {
  return (bytes / 1_048_576).toFixed(1);
}
