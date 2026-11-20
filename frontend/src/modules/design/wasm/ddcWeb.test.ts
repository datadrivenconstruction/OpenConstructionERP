// The vendored generator wasm: pinned bytes, and the worker logic run on them as the browser does.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { countByClass, createHandler, glbNodes, loadEngine, type WorkerOut } from './ddcWeb';

// Editor 2e2931493 (link/w1); README.md says how to rebuild. A new build changes this on purpose.
const VENDORED_SHA256 = '17275958771191c4f3bfa88b9c52c086d5375cb6b94062db75c68374a1b1ccbb';
const wasm = () => readFileSync(resolve(__dirname, 'ddc_web.wasm'));
const brief = () => readFileSync(resolve(__dirname, '../data/fixtures/brief.de-residential.json'), 'utf-8');

describe('ddc_web.wasm', () => {
  it('is the recorded build', () => {
    const readme = readFileSync(resolve(__dirname, 'README.md'), 'utf-8');
    const sha = createHash('sha256').update(wasm()).digest('hex');
    expect(sha).toBe(VENDORED_SHA256);
    expect(readme).toContain(VENDORED_SHA256);
  });

  it('turns the DE brief into a GLB keyed by generator keys', async () => {
    const engine = await loadEngine(wasm());
    const r = engine.gen(brief());
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const nodes = glbNodes(r.glb);
    expect(nodes.map((n) => n.key)).toContain('b1/found/raft');
    const counts = Object.fromEntries(countByClass(nodes));
    expect(counts.IfcWall).toBeGreaterThan(0);
    expect(counts.IfcFooting).toBeGreaterThan(0);
    expect(Object.values(counts).reduce((a, b) => a + b, 0)).toBe(nodes.length);
    // same brief, same bytes: the engine keeps no state between calls
    const again = engine.gen(brief());
    expect(again.ok && Buffer.from(again.glb).equals(Buffer.from(r.glb))).toBe(true);
  });

  it('answers through the worker handler, and reports a bad brief as text', async () => {
    const out: WorkerOut[] = [];
    const handle = createHandler(async () => wasm(), (m) => out.push(m));
    await handle({ type: 'gen', id: 1, brief: brief() });
    await handle({ type: 'gen', id: 2, brief: '{"schema":"nope"}' });
    expect(out[0]).toEqual({ type: 'ready' });
    const [one, two] = out.slice(1) as Extract<WorkerOut, { type: 'result' }>[];
    expect(one.id).toBe(1);
    expect(one.result.ok && glbNodes(one.result.glb).some((n) => n.key === 'b1/found/raft')).toBe(true);
    expect(two).toMatchObject({ id: 2, result: { ok: false } });
    expect(two.result.ok ? '' : two.result.error).not.toBe('');
  });

  it('says failed when the wasm cannot be loaded', async () => {
    const out: WorkerOut[] = [];
    createHandler(async () => new Uint8Array([0, 1, 2, 3]), (m) => out.push(m));
    await new Promise((r) => setTimeout(r, 50));
    expect(out[0]?.type).toBe('failed');
  });
});
