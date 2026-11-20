// Design module (ERP side of the design editor link).
/**
 * ERP side of `ddc-web-bridge/1`: two carriers (JS module mounted on an element, sandboxed iframe) behind one Port,
 * and the host that answers the editor. Free of React and of ERP calls: the page passes the handlers.
 */
import {
  BRIDGE_VERSION, DRAFT_FILE, checkMessage, sha256Hex, toBytes,
  type BridgeError, type EditorMsg, type ErrorCode, type HostMsg, type DraftRef, type OpenMsg, type SelectedElement,
} from './protocol';

export interface Port {
  send(msg: HostMsg, transfer?: Transferable[]): void;
  listen(cb: (msg: unknown) => void): () => void;
  close(): void;
}

/** What a bundle entry `*.js` exports. */
export interface EditorModule {
  mount(element: HTMLElement, host: { post(msg: unknown, transfer?: Transferable[]): void }): Promise<{
    post(msg: unknown, transfer?: Transferable[]): void;
    unmount(): void;
  }>;
}

/** Messages the editor posts before the host listens (its `ready` during mount) are kept, not lost. */
function inbox() {
  const early: unknown[] = [];
  let sink: ((m: unknown) => void) | null = null;
  return {
    push: (m: unknown) => (sink ? sink(m) : early.push(m)),
    listen(cb: (m: unknown) => void) {
      sink = cb;
      for (const m of early.splice(0)) cb(m);
      return () => { sink = null; };
    },
  };
}

export async function modulePort(mod: EditorModule, element: HTMLElement): Promise<Port> {
  if (typeof mod?.mount !== 'function') throw new Error('editor bundle has no mount()');
  const box = inbox();
  const handle = await mod.mount(element, { post: (m) => box.push(m) });
  return {
    send: (m, transfer) => handle.post(m, transfer),
    listen: box.listen,
    close: () => handle.unmount(),
  };
}

/**
 * The frame is sandboxed without same-origin, so its origin is opaque ("null") and replies go to '*'; what makes a
 * message the editor's is that it comes from this frame's window.
 */
export function framePort(frame: HTMLIFrameElement, win: Window = window): Port {
  const box = inbox();
  const onMessage = (e: MessageEvent) => {
    if (e.source && e.source === frame.contentWindow) box.push(e.data);
  };
  win.addEventListener('message', onMessage);
  return {
    send: (m, transfer) => frame.contentWindow?.postMessage(m, '*', transfer ?? []),
    listen: box.listen,
    close: () => win.removeEventListener('message', onMessage),
  };
}

export class BridgeFailure extends Error {
  constructor(public readonly error: BridgeError) {
    super(error.message);
  }
}

export interface HostHandlers {
  open(): Promise<OpenMsg>;
  /** Autosave: store the package as the person's draft. */
  save(bytes: Uint8Array): Promise<DraftRef>;
  ai(text: string): Promise<Omit<Extract<HostMsg, { type: 'ai_result' }>, 'bridge' | 'type' | 'request_id'>>;
  readFile(path: string): Promise<Uint8Array>;
  select(elements: SelectedElement[]): void;
  dirty(dirty: boolean): void;
  state(state: BridgeState): void;
}

export type BridgeState =
  | { status: 'connecting' }
  | { status: 'open'; editor: { name: string; version: string } }
  | { status: 'refused'; versions: number[] }
  | { status: 'failed'; reason: string };

/** ERP errors as the bridge names them; anything without an HTTP status is the network. */
export function bridgeError(err: unknown): BridgeError {
  if (err instanceof BridgeFailure) return err.error;
  const status = typeof (err as { status?: unknown })?.status === 'number' ? (err as { status: number }).status : 0;
  const message = err instanceof Error ? err.message : String(err);
  const code: ErrorCode = status === 0 ? 'network'
    : status === 409 ? 'locked'
      : status === 401 || status === 403 ? 'no_permission'
        : status === 413 ? 'too_large'
          : status === 422 || status === 400 ? 'rejected'
            : status === 426 ? 'version'
              : status === 404 ? 'not_found'
                : status === 503 ? 'unavailable' : 'other';
  return { code, ...(status ? { status } : {}), message: message.slice(0, 4000) };
}

export interface BridgeHost {
  /** Send open again: a revision was made from the draft, or the chain tip moved. */
  reopen(): Promise<void>;
  /** Highlight elements the person picked in an ERP list. */
  select(elements: SelectedElement[]): void;
  settings(locale: string, theme: 'light' | 'dark'): void;
  close(): void;
}

export function connectBridge(port: Port, h: HostHandlers, opts: { readyTimeoutMs?: number } = {}): BridgeHost {
  let open = false;
  let opened: OpenMsg | null = null;
  let closed = false;
  let saving = false;
  const send = (m: HostMsg, transfer?: Transferable[]) => { if (!closed) port.send(m, transfer); };
  h.state({ status: 'connecting' });
  const timer = setTimeout(() => {
    if (!open && !closed) h.state({ status: 'failed', reason: 'no ready message from the editor' });
  }, opts.readyTimeoutMs ?? 30_000);

  const onReady = async (m: Extract<EditorMsg, { type: 'ready' }>) => {
    clearTimeout(timer);
    if (!m.versions.includes(BRIDGE_VERSION)) {
      send({ bridge: 1, type: 'refused', supported: [BRIDGE_VERSION] });
      h.state({ status: 'refused', versions: m.versions });
      return;
    }
    try {
      opened = await h.open();
      send(opened);
      open = true;
      h.state({ status: 'open', editor: m.editor });
    } catch (e) {
      h.state({ status: 'failed', reason: e instanceof Error ? e.message : String(e) });
    }
  };

  const onSave = async (m: Extract<EditorMsg, { type: 'save' }>) => {
    const reply = (r: { ok: true; draft: DraftRef } | { ok: false; error: BridgeError }) =>
      send({ bridge: 1, type: 'save_result', request_id: m.request_id, ...r });
    if (opened?.mode !== 'edit') return reply({ ok: false, error: { code: 'no_permission', message: 'view only here' } });
    if (saving) return reply({ ok: false, error: { code: 'other', message: 'a save is already running' } });
    saving = true;
    try {
      const bytes = toBytes(m.package);
      if (bytes.byteLength !== m.package_bytes || (await sha256Hex(bytes)) !== m.package_sha256) {
        return reply({ ok: false, error: { code: 'integrity', message: 'package size or SHA-256 does not match' } });
      }
      reply({ ok: true, draft: await h.save(bytes) });
    } catch (e) {
      reply({ ok: false, error: bridgeError(e) });
    } finally {
      saving = false;
    }
  };

  const onAi = async (m: Extract<EditorMsg, { type: 'ai_request' }>) => {
    try {
      send({ bridge: 1, type: 'ai_result', request_id: m.request_id, ...(await h.ai(m.text)) });
    } catch (e) {
      send({ bridge: 1, type: 'ai_result', request_id: m.request_id, status: 'failed', error: bridgeError(e) });
    }
  };

  const onRead = async (m: Extract<EditorMsg, { type: 'read_file' }>) => {
    try {
      const listed = opened?.revision?.files.some((f) => f.path === m.path) || (m.path === DRAFT_FILE && opened?.draft);
      if (!listed) {
        throw new BridgeFailure({ code: 'not_found', message: `not a file of the open revision: ${m.path}` });
      }
      const bytes = await h.readFile(m.path);
      const copy = bytes.slice();
      send({ bridge: 1, type: 'file', request_id: m.request_id, ok: true, bytes: copy }, [copy.buffer]);
    } catch (e) {
      send({ bridge: 1, type: 'file', request_id: m.request_id, ok: false, error: bridgeError(e) });
    }
  };

  const stop = port.listen((raw) => {
    if (closed || checkMessage(raw, 'editor').length) return; // not ours or malformed: never acted on
    const m = raw as EditorMsg;
    if (m.type === 'ready') { void onReady(m); return; }
    if (!open) return;
    if (m.type === 'save') void onSave(m);
    else if (m.type === 'ai_request') void onAi(m);
    else if (m.type === 'read_file') void onRead(m);
    else if (m.type === 'select') h.select(m.elements);
    else if (m.type === 'dirty') h.dirty(m.dirty);
  });

  return {
    reopen: async () => {
      if (!open) return;
      opened = await h.open();
      send(opened);
    },
    select: (elements) => { if (open) send({ bridge: 1, type: 'select', elements }); },
    settings: (locale, theme) => { if (open) send({ bridge: 1, type: 'settings', locale, theme }); },
    close() {
      closed = true;
      clearTimeout(timer);
      stop();
      port.close();
    },
  };
}
