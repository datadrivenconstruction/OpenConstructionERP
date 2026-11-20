// Design module (ERP side of the design editor link).
/**
 * `ddc-web-bridge/1` (contract/README.md §11): the messages between this page and the browser editor. Every message
 * from the editor is checked against the contract schema before the host acts on it.
 */
import rawSchema from '../data/web-bridge.schema.json';
import rawEditorSchema from '../data/web-editor.schema.json';
import { validate, type Schema, type SchemaError } from '../data/schemaCheck';

export const BRIDGE_VERSION = 1;
const SCHEMA = rawSchema as unknown as { $defs: Record<string, Schema> };

export type Binary = ArrayBuffer | Uint8Array | string;
export type ErrorCode = 'locked' | 'no_permission' | 'rejected' | 'too_large' | 'integrity' | 'network' | 'version'
  | 'unavailable' | 'declined' | 'not_found' | 'other';
export interface BridgeError { code: ErrorCode; status?: number; message: string }
export interface SelectedElement { element_key: string; ifc_class?: string; type_key?: string }
export interface RevisionFile { path: string; role: string; url: string; bytes: number }
export interface RevisionRef { revision_id: string; number: number; status: 'shared' | 'published' }
export interface DraftRef { revision_id: string; updated_at: string; element_count: number }
export const DRAFT_FILE = 'draft.ddcrev';

export interface OpenMsg {
  bridge: 1; type: 'open';
  project: { id: string; name: string };
  brief: Record<string, unknown> | null;
  brief_version: number | null;
  revision: (RevisionRef & { files: RevisionFile[] }) | null;
  draft: (DraftRef & { parent_revision_id: string | null }) | null;
  mode: 'edit' | 'view';
  locale: string;
  theme: 'light' | 'dark';
  permissions: { can_edit: boolean; can_accept: boolean };
  ai: { available: boolean };
}

export type EditorMsg =
  | { bridge: 1; type: 'ready'; versions: number[]; editor: { name: string; version: string } }
  | { bridge: 1; type: 'dirty'; dirty: boolean }
  | { bridge: 1; type: 'save'; request_id: string; package: Binary; package_bytes: number; package_sha256: string }
  | { bridge: 1; type: 'ai_request'; request_id: string; action: 'brief_from_text'; text: string }
  | { bridge: 1; type: 'read_file'; request_id: string; path: string }
  | { bridge: 1; type: 'select'; elements: SelectedElement[] };

export type HostMsg =
  | OpenMsg
  | { bridge: 1; type: 'refused'; supported: number[] }
  | { bridge: 1; type: 'settings'; locale: string; theme: 'light' | 'dark' }
  | { bridge: 1; type: 'save_result'; request_id: string; ok: boolean; draft?: DraftRef; error?: BridgeError }
  | { bridge: 1; type: 'ai_result'; request_id: string; status: 'confirmed' | 'declined' | 'unavailable' | 'failed';
      brief_version?: number; brief?: Record<string, unknown>; confirmed?: string[]; error?: BridgeError }
  | { bridge: 1; type: 'file'; request_id: string; ok: boolean; bytes?: Binary; error?: BridgeError }
  | { bridge: 1; type: 'select'; elements: SelectedElement[] };

const FROM_EDITOR = new Set(['ready', 'dirty', 'save', 'ai_request', 'read_file', 'select']);
const FROM_HOST = new Set(['open', 'refused', 'settings', 'save_result', 'ai_result', 'file', 'select']);
const BINARY = new Set(['package', 'bytes']);

/** Binary members are not JSON: check them here, then the rest against the schema with a placeholder. */
function jsonShape(msg: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(msg)) out[k] = BINARY.has(k) && isBinary(v) ? '' : v;
  return out;
}

export function isBinary(v: unknown): v is Binary {
  return v instanceof ArrayBuffer || v instanceof Uint8Array || typeof v === 'string';
}

/** Schema problems of a message of one direction; [] = valid. */
export function checkMessage(msg: unknown, from: 'editor' | 'host'): SchemaError[] {
  if (typeof msg !== 'object' || msg === null || Array.isArray(msg)) return [{ pointer: '', code: 'type', param: 'object' }];
  const m = msg as Record<string, unknown>;
  const allowed = from === 'editor' ? FROM_EDITOR : FROM_HOST;
  if (typeof m.type !== 'string' || !allowed.has(m.type)) return [{ pointer: '/type', code: 'enum', param: [...allowed].join(', ') }];
  for (const k of BINARY) if (k in m && !isBinary(m[k])) return [{ pointer: `/${k}`, code: 'type', param: 'binary' }];
  return validate(jsonShape(m), { $defs: SCHEMA.$defs, $ref: `#/$defs/${m.type}` });
}

export function isEditorMsg(msg: unknown): msg is EditorMsg {
  return checkMessage(msg, 'editor').length === 0;
}

/** Bytes of a binary field (base64 when a JSON carrier was used). */
export function toBytes(b: Binary): Uint8Array {
  if (b instanceof Uint8Array) return b;
  if (b instanceof ArrayBuffer) return new Uint8Array(b);
  const raw = atob(b);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes as BufferSource);
  return [...new Uint8Array(digest)].map((x) => x.toString(16).padStart(2, '0')).join('');
}

/* ── Bundle manifest ddc-web-editor/1 ─────────────────────────────────── */

export interface EditorBundle {
  schema: 'ddc-web-editor/1';
  version: string;
  bridge: number[];
  entry: string;
  files: { path: string; bytes: number; sha256: string }[];
}

export function checkBundle(doc: unknown): SchemaError[] {
  return validate(doc, rawEditorSchema as unknown as Schema);
}

export function bundleBytes(b: EditorBundle): number {
  return b.files.reduce((s, f) => s + f.bytes, 0);
}
