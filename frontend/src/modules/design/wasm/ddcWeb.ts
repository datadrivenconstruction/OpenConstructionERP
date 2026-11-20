// Design module (ERP side of the design editor link).
/**
 * The editor's generator compiled to wasm (`ddc_web.wasm`, see README.md): brief JSON in, preview GLB out.
 * Raw ABI, no binding layer: write the brief into `ddc_alloc`, call `ddc_gen`, read `ddc_out_ptr`/`ddc_out_len`
 * (GLB on 0, error text on 1). Pure: used by the worker and by node tests alike.
 */

interface Exports {
  memory: WebAssembly.Memory;
  ddc_alloc(len: number): number;
  ddc_free(ptr: number, len: number): void;
  ddc_gen(ptr: number, len: number): number;
  ddc_out_ptr(): number;
  ddc_out_len(): number;
}

export type GenResult = { ok: true; glb: Uint8Array; ms: number } | { ok: false; error: string };

export interface PreviewEngine {
  gen(briefJson: string): GenResult;
}

export async function loadEngine(bytes: BufferSource): Promise<PreviewEngine> {
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const x = instance.exports as unknown as Exports;
  for (const f of ['ddc_alloc', 'ddc_free', 'ddc_gen', 'ddc_out_ptr', 'ddc_out_len'] as const) {
    if (typeof x[f] !== 'function') throw new Error(`ddc_web.wasm lacks ${f}`);
  }
  return {
    gen(briefJson) {
      const src = new TextEncoder().encode(briefJson);
      const p = x.ddc_alloc(src.length);
      new Uint8Array(x.memory.buffer, p, src.length).set(src);
      const t0 = performance.now();
      const code = x.ddc_gen(p, src.length);
      const ms = performance.now() - t0;
      x.ddc_free(p, src.length);
      // memory may have grown during ddc_gen: take the buffer only now, and copy out before the next call
      const out = new Uint8Array(x.memory.buffer, x.ddc_out_ptr(), x.ddc_out_len()).slice();
      return code === 0 ? { ok: true, glb: out, ms } : { ok: false, error: new TextDecoder().decode(out) };
    },
  };
}

export interface PreviewNode { key: string; ifcClass: string }

/** Element nodes of a preview GLB (node name = element key, extras carry the IFC class). */
export function glbNodes(glb: Uint8Array): PreviewNode[] {
  const dv = new DataView(glb.buffer, glb.byteOffset, glb.byteLength);
  if (glb.byteLength < 20 || dv.getUint32(0, true) !== 0x46546c67 || dv.getUint32(16, true) !== 0x4e4f534a) {
    throw new Error('not a GLB');
  }
  const n = dv.getUint32(12, true);
  const doc = JSON.parse(new TextDecoder().decode(glb.subarray(20, 20 + n))) as {
    nodes?: { name?: string; extras?: { element_key?: string; ifc_class?: string } }[];
  };
  return (doc.nodes ?? []).flatMap((nd) => {
    const key = nd.extras?.element_key ?? nd.name;
    return key ? [{ key, ifcClass: nd.extras?.ifc_class ?? 'IfcBuildingElementProxy' }] : [];
  });
}

/** Count per IFC class, largest first. */
export function countByClass(nodes: PreviewNode[]): [string, number][] {
  const m = new Map<string, number>();
  for (const nd of nodes) m.set(nd.ifcClass, (m.get(nd.ifcClass) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export type WorkerIn = { type: 'gen'; id: number; brief: string };
export type WorkerOut =
  | { type: 'ready' }
  | { type: 'failed'; error: string }
  | { type: 'result'; id: number; result: GenResult };

/** The worker's logic without the worker: load once, then answer each brief. */
export function createHandler(load: () => Promise<BufferSource>, post: (m: WorkerOut, transfer?: Transferable[]) => void) {
  const engine = load().then(loadEngine);
  engine.then(() => post({ type: 'ready' }), (e: unknown) => post({ type: 'failed', error: String(e) }));
  return async (m: WorkerIn) => {
    if (m.type !== 'gen') return;
    let result: GenResult;
    try {
      result = (await engine).gen(m.brief);
    } catch (e) {
      result = { ok: false, error: String(e) };
    }
    post({ type: 'result', id: m.id, result }, result.ok ? [result.glb.buffer as ArrayBuffer] : []);
  };
}
