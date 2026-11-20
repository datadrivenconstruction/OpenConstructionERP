import { afterEach, describe, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { BridgeFailure, connectBridge, framePort, modulePort, type HostHandlers, type Port } from './host';
import { checkMessage, type HostMsg, type OpenMsg } from './protocol';

const PID = '746402cb-14a8-430c-b3b9-9c6908fa75d7';
const RID = '9c1d2e3f-4a5b-4c6d-8e7f-0a1b2c3d4e5f';
const OPEN: OpenMsg = {
  bridge: 1, type: 'open', project: { id: PID, name: 'Wohnanlage' }, brief: null, brief_version: null,
  revision: { revision_id: RID, number: 2, status: 'published', files: [
    { path: 'model.ddc', role: 'source', url: `/api/v1/design/revisions/${RID}/files/model.ddc`, bytes: 3 }] },
  draft: null, mode: 'edit',
  locale: 'de', theme: 'light', permissions: { can_edit: true, can_accept: false }, ai: { available: false },
};
const DRAFT = { revision_id: '5b0c7e21-9d3f-4a8e-b6c1-2f4d8a9e0c13', updated_at: '2026-11-15T10:42:00Z', element_count: 214 };
const READY = { bridge: 1, type: 'ready', versions: [1], editor: { name: 'editor', version: '0.4.0' } };
const PKG = new Uint8Array([0x50, 0x4b, 0x05, 0x06, ...new Array(18).fill(0)]);
const SHA = createHash('sha256').update(PKG).digest('hex');

function memoryPort() {
  const sent: HostMsg[] = [];
  let cb: ((m: unknown) => void) | null = null;
  const port: Port = { send: (m) => sent.push(m), listen: (f) => { cb = f; return () => { cb = null; }; }, close: vi.fn() };
  return { port, sent, emit: (m: unknown) => cb?.(m) };
}

function handlers(over: Partial<HostHandlers> = {}): HostHandlers {
  return {
    open: vi.fn(async () => OPEN),
    save: vi.fn(async () => DRAFT),
    ai: vi.fn(async () => ({ status: 'declined' as const })),
    readFile: vi.fn(async () => new Uint8Array([1, 2, 3])),
    select: vi.fn(), dirty: vi.fn(), state: vi.fn(),
    ...over,
  };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => vi.useRealTimers());

describe('protocol', () => {
  it('accepts each editor message and refuses wrong direction, bad ids and non-binary packages', () => {
    expect(checkMessage(READY, 'editor')).toEqual([]);
    expect(checkMessage({ bridge: 1, type: 'save', request_id: 's1', package: PKG, package_bytes: 22, package_sha256: SHA }, 'editor')).toEqual([]);
    expect(checkMessage({ bridge: 1, type: 'select', elements: [{ element_key: 'L01/wall/1', ifc_class: 'IfcWall' }] }, 'editor')).toEqual([]);
    expect(checkMessage(OPEN, 'host')).toEqual([]);
    expect(checkMessage(OPEN, 'editor')).not.toEqual([]);
    expect(checkMessage({ ...READY, bridge: 2 }, 'editor')).not.toEqual([]);
    expect(checkMessage({ bridge: 1, type: 'save', request_id: 'a b', package: PKG, package_bytes: 22, package_sha256: SHA }, 'editor')).not.toEqual([]);
    expect(checkMessage({ bridge: 1, type: 'save', request_id: 's1', package: 42, package_bytes: 22, package_sha256: SHA }, 'editor')).not.toEqual([]);
    expect(checkMessage({ ...OPEN, token: 'ddcl_x' }, 'host')).not.toEqual([]);
    expect(checkMessage('hello', 'editor')).not.toEqual([]);
  });
});

describe('connectBridge', () => {
  it('opens the project after ready, and ignores everything before it', async () => {
    const { port, sent, emit } = memoryPort();
    const h = handlers();
    connectBridge(port, h);
    emit({ bridge: 1, type: 'select', elements: [] });
    emit(READY);
    await flush();
    expect(sent).toEqual([OPEN]);
    expect(h.select).not.toHaveBeenCalled();
    expect(h.state).toHaveBeenLastCalledWith({ status: 'open', editor: { name: 'editor', version: '0.4.0' } });
    emit({ bridge: 1, type: 'select', elements: [{ element_key: 'k1', ifc_class: 'IfcWall' }] });
    emit({ bridge: 1, type: 'dirty', dirty: true });
    expect(h.select).toHaveBeenCalledWith([{ element_key: 'k1', ifc_class: 'IfcWall' }]);
    expect(h.dirty).toHaveBeenCalledWith(true);
  });

  it('refuses an editor without a common major and opens nothing', async () => {
    const { port, sent, emit } = memoryPort();
    const h = handlers();
    connectBridge(port, h);
    emit({ ...READY, versions: [2] });
    await flush();
    expect(sent).toEqual([{ bridge: 1, type: 'refused', supported: [1] }]);
    expect(h.open).not.toHaveBeenCalled();
    expect(h.state).toHaveBeenLastCalledWith({ status: 'refused', versions: [2] });
  });

  it('fails when the editor never says ready', () => {
    vi.useFakeTimers();
    const h = handlers();
    connectBridge(memoryPort().port, h, { readyTimeoutMs: 1000 });
    vi.advanceTimersByTime(1001);
    expect(h.state).toHaveBeenLastCalledWith({ status: 'failed', reason: 'no ready message from the editor' });
  });

  it('autosaves a package whose size and hash agree as the draft', async () => {
    const { port, sent, emit } = memoryPort();
    const h = handlers();
    connectBridge(port, h);
    emit(READY);
    await flush();
    emit({ bridge: 1, type: 'save', request_id: 's1', package: PKG.buffer.slice(0), package_bytes: 22, package_sha256: SHA });
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect((h.save as ReturnType<typeof vi.fn>).mock.calls[0]![0]).toEqual(PKG);
    expect(sent[1]).toEqual({ bridge: 1, type: 'save_result', request_id: 's1', ok: true, draft: DRAFT });
    expect(checkMessage(sent[1], 'host')).toEqual([]);
  });

  it('view mode (tablet, phone, no edit right) never stores anything', async () => {
    const { port, sent, emit } = memoryPort();
    const h = handlers({ open: vi.fn(async () => ({ ...OPEN, mode: 'view' as const })) });
    connectBridge(port, h);
    emit(READY);
    await flush();
    emit({ bridge: 1, type: 'save', request_id: 's1', package: PKG, package_bytes: 22, package_sha256: SHA });
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({ ok: false, error: { code: 'no_permission' } });
    expect(h.save).not.toHaveBeenCalled();
  });

  it('reopen sends the new state after a revision was made from the draft', async () => {
    const { port, sent, emit } = memoryPort();
    let tip = OPEN;
    const h = handlers({ open: vi.fn(async () => tip) });
    const b = connectBridge(port, h);
    emit(READY);
    await flush();
    tip = { ...OPEN, revision: { ...OPEN.revision!, number: 3, status: 'shared' }, draft: null };
    await b.reopen();
    expect(sent.map((m) => m.type)).toEqual(['open', 'open']);
    expect((sent[1] as OpenMsg).revision?.number).toBe(3);
  });

  it('never uploads a package that does not match its hash; ERP refusals come back named', async () => {
    const { port, sent, emit } = memoryPort();
    const h = handlers({ save: vi.fn(async () => { throw Object.assign(new Error('Take the project lock'), { status: 409 }); }) });
    connectBridge(port, h);
    emit(READY);
    await flush();
    emit({ bridge: 1, type: 'save', request_id: 's1', package: PKG, package_bytes: 22, package_sha256: 'f'.repeat(64) });
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(h.save).not.toHaveBeenCalled();
    expect(sent[1]).toMatchObject({ ok: false, error: { code: 'integrity' } });
    emit({ bridge: 1, type: 'save', request_id: 's2', package: PKG, package_bytes: 22, package_sha256: SHA });
    await vi.waitFor(() => expect(sent).toHaveLength(3));
    expect(sent[2]).toMatchObject({ request_id: 's2', ok: false, error: { code: 'locked', status: 409 } });
    expect(checkMessage(sent[2], 'host')).toEqual([]);
  });

  it('reads only files of the open revision and the draft when there is one', async () => {
    const { port, sent, emit } = memoryPort();
    const h = handlers({ open: vi.fn(async () => ({ ...OPEN, draft: { ...DRAFT, parent_revision_id: RID } })) });
    connectBridge(port, h);
    emit(READY);
    await flush();
    emit({ bridge: 1, type: 'read_file', request_id: 'f1', path: 'model.ddc' });
    emit({ bridge: 1, type: 'read_file', request_id: 'f2', path: '../../etc/passwd' });
    emit({ bridge: 1, type: 'read_file', request_id: 'f3', path: 'draft.ddcrev' });
    await vi.waitFor(() => expect(sent).toHaveLength(4));
    const byId = Object.fromEntries(sent.slice(1).map((m) => [(m as { request_id: string }).request_id, m]));
    expect(byId.f1).toMatchObject({ ok: true, bytes: new Uint8Array([1, 2, 3]) });
    expect(byId.f2).toMatchObject({ ok: false, error: { code: 'not_found' } });
    expect(byId.f3).toMatchObject({ ok: true });
    expect(h.readFile).toHaveBeenCalledTimes(2);
  });

  it('passes AI requests to the ERP and answers with what the person confirmed', async () => {
    const { port, sent, emit } = memoryPort();
    const h = handlers({ ai: vi.fn(async () => ({ status: 'confirmed' as const, brief_version: 5, confirmed: ['/massing/floors_above'] })) });
    connectBridge(port, h);
    emit(READY);
    await flush();
    emit({ bridge: 1, type: 'ai_request', request_id: 'a1', action: 'brief_from_text', text: '4 Geschosse' });
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(h.ai).toHaveBeenCalledWith('4 Geschosse');
    expect(sent[1]).toEqual({ bridge: 1, type: 'ai_result', request_id: 'a1', status: 'confirmed', brief_version: 5,
      confirmed: ['/massing/floors_above'] });
  });

  it('maps a BridgeFailure as given and drops malformed messages', async () => {
    const { port, sent, emit } = memoryPort();
    const h = handlers({ ai: vi.fn(async () => { throw new BridgeFailure({ code: 'unavailable', message: 'no AI' }); }) });
    connectBridge(port, h);
    emit(READY);
    await flush();
    emit({ bridge: 1, type: 'ai_request', request_id: 'a1', action: 'write_prices', text: 'x' });
    emit({ bridge: 1, type: 'ai_request', request_id: 'a2', action: 'brief_from_text', text: 'x' });
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({ request_id: 'a2', status: 'failed', error: { code: 'unavailable' } });
  });
});

describe('carriers', () => {
  it('module: keeps the ready posted during mount', async () => {
    const posted: unknown[] = [];
    const mod = {
      mount: vi.fn(async (_el: HTMLElement, host: { post(m: unknown): void }) => {
        host.post(READY);
        return { post: (m: unknown) => posted.push(m), unmount: vi.fn() };
      }),
    };
    const port = await modulePort(mod, document.createElement('div'));
    const h = handlers();
    connectBridge(port, h);
    await flush();
    expect(posted).toEqual([OPEN]);
  });

  it('iframe: listens only to its own frame', () => {
    const frame = document.createElement('iframe');
    document.body.appendChild(frame);
    const port = framePort(frame);
    const got: unknown[] = [];
    port.listen((m) => got.push(m));
    window.dispatchEvent(new MessageEvent('message', { data: READY, source: window }));
    window.dispatchEvent(new MessageEvent('message', { data: READY, source: frame.contentWindow }));
    expect(got).toEqual([READY]);
    port.close();
    window.dispatchEvent(new MessageEvent('message', { data: READY, source: frame.contentWindow }));
    expect(got).toHaveLength(1);
    frame.remove();
  });
});
