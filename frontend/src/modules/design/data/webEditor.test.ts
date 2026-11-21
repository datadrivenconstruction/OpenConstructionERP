import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { statSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  CONSENT_KEY, ENGINE_BYTES, bundleUrl, findPayload, loadState, payloadBytes, prefetch, readConsent, resetLoadState,
  scheduleBackgroundLoad, writeConsent, type Payload,
} from './webEditor';

const ORIGIN = 'https://erp.example.com';
const bytes = (n: number) => new Uint8Array(n).fill(7);
const sha = (b: Uint8Array) => createHash('sha256').update(b).digest('hex');

/** A Cache Storage stand-in: one map per name. */
function memoryCaches() {
  const stores = new Map<string, Map<string, Response>>();
  const api = {
    open: async (name: string) => {
      if (!stores.has(name)) stores.set(name, new Map());
      const m = stores.get(name)!;
      return { match: async (u: string) => m.get(u)?.clone(), put: async (u: string, r: Response) => { m.set(u, r); } };
    },
  };
  return { caches: api as unknown as CacheStorage, stores };
}

const engine = (): Payload => ({ kind: 'engine', version: 'ddc_web', assets: [{ url: `${ORIGIN}/assets/ddc_web.wasm`, bytes: 1000 }] });
const fetchOf = (body: Uint8Array) => vi.fn(async () => new Response(body as BodyInit, { status: 200 }));
const now = (cb: () => void) => cb();

beforeEach(() => {
  localStorage.clear();
  resetLoadState();
});

describe('consent', () => {
  it('is yes, no or not asked', () => {
    expect(readConsent()).toBeNull();
    writeConsent('no');
    expect(localStorage.getItem(CONSENT_KEY)).toBe('no');
    writeConsent('yes');
    expect(readConsent()).toBe('yes');
    localStorage.setItem(CONSENT_KEY, 'maybe');
    expect(readConsent()).toBeNull();
  });
});

describe('background load', () => {
  it('downloads nothing for a person who said no or was never asked', async () => {
    const f = fetchOf(bytes(1000));
    const payload = vi.fn(async () => engine());
    expect(scheduleBackgroundLoad({ payload, consent: 'no', idle: now, fetchFn: f, caches: null })).toBeNull();
    expect(scheduleBackgroundLoad({ payload, idle: now, fetchFn: f, caches: null })).toBeNull();
    expect(payload).not.toHaveBeenCalled();
    expect(f).not.toHaveBeenCalled();
    expect(loadState()).toEqual({ status: 'off' });
  });

  it('after yes: waits for idle time, reports progress, keeps the files in the cache', async () => {
    writeConsent('yes');
    const { caches, stores } = memoryCaches();
    const f = fetchOf(bytes(1000));
    let later: (() => void) | null = null;
    const run = scheduleBackgroundLoad({ payload: async () => engine(), idle: (cb) => { later = cb; }, fetchFn: f, caches });
    expect(f).not.toHaveBeenCalled(); // nothing until the browser is idle
    later!();
    await run;
    expect(f).toHaveBeenCalledTimes(1);
    expect(loadState()).toEqual({ status: 'ready', total: 1000, cached: false });
    expect(stores.get('oe-design-editor-v1')!.has(`${ORIGIN}/assets/ddc_web.wasm`)).toBe(true);
  });

  it('a cached payload is not fetched again', async () => {
    const { caches } = memoryCaches();
    const f = fetchOf(bytes(1000));
    await prefetch(engine(), { fetchFn: f, caches });
    const progress: number[] = [];
    const r = await prefetch(engine(), { fetchFn: f, caches, onProgress: (d) => progress.push(d) });
    expect(f).toHaveBeenCalledTimes(1);
    expect(r.cached).toBe(true);
    expect(progress).toEqual([1000]);
  });

  it('refuses a file whose hash is not the manifest hash, and caches nothing', async () => {
    writeConsent('yes');
    const { caches, stores } = memoryCaches();
    const p: Payload = { ...engine(), assets: [{ url: `${ORIGIN}/e.wasm`, bytes: 10, sha256: sha(bytes(9)) }] };
    await scheduleBackgroundLoad({ payload: async () => p, idle: now, fetchFn: fetchOf(bytes(10)), caches });
    expect(loadState()).toMatchObject({ status: 'failed' });
    expect(stores.get('oe-design-editor-v1')!.size).toBe(0);
  });
});

describe('payload', () => {
  it('ENGINE_BYTES is the size of the vendored generator', () => {
    expect(statSync(resolve(__dirname, '../wasm/ddc_web.wasm')).size).toBe(ENGINE_BYTES);
  });

  it('takes the bundle address only over https or from this ERP', () => {
    expect(bundleUrl({}, ORIGIN)).toBeNull();
    expect(bundleUrl({ VITE_DESIGN_WEB_EDITOR_URL: 'http://cdn.example.com/m.json' }, ORIGIN)).toBeNull();
    expect(bundleUrl({ VITE_DESIGN_WEB_EDITOR_URL: '/design-editor/m.json' }, ORIGIN)).toBe(`${ORIGIN}/design-editor/m.json`);
    expect(bundleUrl({ VITE_DESIGN_WEB_EDITOR_URL: 'https://cdn.example.com/m.json' }, ORIGIN)).toBe('https://cdn.example.com/m.json');
  });

  const manifest = (over: object = {}) => ({
    schema: 'ddc-web-editor/1', version: '0.4.0', bridge: [1], entry: 'ddc-editor.js',
    files: [{ path: 'ddc-editor.js', bytes: 10, sha256: 'a'.repeat(64) }, { path: 'pkg/ed.wasm', bytes: 90, sha256: 'b'.repeat(64) }],
    ...over,
  });
  const env = { VITE_DESIGN_WEB_EDITOR_URL: '/design-editor/ddc-web-editor.json' };
  const json = (doc: unknown) => vi.fn(async () => new Response(JSON.stringify(doc), { status: 200 }));

  it('without a bundle: the generator in the module', async () => {
    const p = await findPayload({ env: {}, origin: ORIGIN, engineUrl: '/assets/ddc_web.wasm' });
    expect(p).toEqual({ kind: 'engine', version: 'ddc_web', assets: [{ url: `${ORIGIN}/assets/ddc_web.wasm`, bytes: ENGINE_BYTES }] });
  });

  it('with a valid bundle: its files beside the manifest', async () => {
    const p = await findPayload({ env, origin: ORIGIN, engineUrl: '/w.wasm', fetchFn: json(manifest()) });
    expect(p.kind).toBe('editor');
    if (p.kind !== 'editor') return;
    expect(p.entryUrl).toBe(`${ORIGIN}/design-editor/ddc-editor.js`);
    expect(p.assets.map((a) => a.url)).toEqual([`${ORIGIN}/design-editor/ddc-editor.js`, `${ORIGIN}/design-editor/pkg/ed.wasm`]);
  });

  it('without a build-time URL: the bundle this server installed from the release feed', async () => {
    const installedUrl = async () => '/api/v1/design/web-editor/files/0.10.0/manifest.json';
    const p = await findPayload({ env: {}, origin: ORIGIN, engineUrl: '/w.wasm', fetchFn: json(manifest()), installedUrl });
    expect(p.kind).toBe('editor');
    if (p.kind !== 'editor') return;
    expect(p.entryUrl).toBe(`${ORIGIN}/api/v1/design/web-editor/files/0.10.0/ddc-editor.js`);
  });

  it('stays on the engine when nothing is installed or the status call fails', async () => {
    for (const installedUrl of [async () => null, async () => { throw new Error('offline'); }]) {
      const p = await findPayload({ env: {}, origin: ORIGIN, engineUrl: '/w.wasm', installedUrl });
      expect(p.kind).toBe('engine');
    }
  });

  it('leaves on-demand files (locale catalogs, script fonts) to the page: not prefetched, not counted', async () => {
    const m = manifest();
    m.files.push({ path: 'i18n/de.json', bytes: 700, sha256: 'c'.repeat(64), load: 'on_demand' } as (typeof m.files)[number]);
    const p = await findPayload({ env, origin: ORIGIN, engineUrl: '/w.wasm', fetchFn: json(m) });
    if (p.kind !== 'editor') throw new Error(p.kind);
    expect(p.assets.map((a) => a.url)).not.toContain(`${ORIGIN}/design-editor/i18n/de.json`);
    expect(payloadBytes(p)).toBe(100);
  });

  it('falls back to the generator on another bridge major, a bad manifest or an HTML page', async () => {
    for (const fetchFn of [
      json(manifest({ bridge: [2] })),
      json(manifest({ entry: '../x.js' })),
      vi.fn(async () => new Response('<!doctype html><html></html>', { status: 200 })),
      vi.fn(async () => new Response('', { status: 404 })),
    ]) {
      const p = await findPayload({ env, origin: ORIGIN, engineUrl: '/w.wasm', fetchFn });
      expect(p.kind).toBe('engine');
      expect(p.fallback).toBeTruthy();
    }
  });
});
