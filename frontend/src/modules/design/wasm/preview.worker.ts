// Design module (ERP side of the design editor link).
// Web Worker: runs the wasm generator off the main thread. The first message names the wasm URL.
import { createHandler, type WorkerIn, type WorkerOut } from './ddcWeb';

const scope = self as unknown as {
  postMessage(m: WorkerOut, transfer?: Transferable[]): void;
  onmessage: ((e: MessageEvent<WorkerIn | { type: 'init'; url: string }>) => void) | null;
};
let handle: ((m: WorkerIn) => Promise<void>) | null = null;
scope.onmessage = (e) => {
  const m = e.data;
  if (m.type === 'init') {
    handle ??= createHandler(async () => {
      // A background load (data/webEditor.ts) may already hold it; the cache name is CACHE_NAME there.
      const hit = typeof caches === 'undefined' ? undefined
        : await caches.open('oe-design-editor-v1').then((c) => c.match(m.url)).catch(() => undefined);
      const r = hit ?? await fetch(m.url);
      if (!r.ok) throw new Error(`ddc_web.wasm: HTTP ${r.status}`);
      return r.arrayBuffer();
    }, (out, transfer) => scope.postMessage(out, transfer ?? []));
  } else if (handle) {
    void handle(m);
  }
};
