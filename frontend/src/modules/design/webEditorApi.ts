// Design module (ERP side of the design editor link).
/** The full browser editor this server fetches on request from the release feed (backend web_release_api). */
import { apiDelete, apiGet, apiPost } from '@/shared/lib/api';

export type BridgeProblem = 'erp_too_old' | 'editor_too_old' | null;

export interface WebEditorStatus {
  host_bridge: number[];
  installed: {
    version: string; bridge: number[]; bytes: number; installed_at: string | null;
    manifest_url: string; problem: BridgeProblem;
  } | null;
  feed: {
    state: 'available' | 'absent' | 'unreachable' | 'invalid' | 'off';
    version?: string; bytes?: number; bridge?: number[]; published_at?: string | null; problem?: BridgeProblem;
  };
  signing: { key: boolean; error: string | null };
  install: { state: 'idle' | 'downloading' | 'verifying' | 'unpacking' | 'failed'; version: string | null;
    done: number; total: number; error: string | null };
  update_available: boolean;
  can_install: boolean;
  can_remove: boolean;
  is_admin?: boolean;
}

export const WEB_EDITOR_KEY = ['design-web-editor'] as const;

export const fetchWebEditorStatus = () => apiGet<WebEditorStatus>('/v1/design/web-editor');
export const startWebEditorInstall = () => apiPost<WebEditorStatus>('/v1/design/web-editor/install', {});
export const removeWebEditor = () => apiDelete('/v1/design/web-editor');

/** The installed bundle's manifest URL when it speaks our bridge, else null (engine mode). */
export async function installedManifestUrl(): Promise<string | null> {
  const s = await fetchWebEditorStatus();
  return s.installed && !s.installed.problem ? s.installed.manifest_url : null;
}

export const busy = (s: WebEditorStatus | undefined) =>
  !!s && ['downloading', 'verifying', 'unpacking'].includes(s.install.state);

/** i18n key of a refusal or failure code from the server; unknown codes get the generic sentence. */
const KNOWN = new Set(['no_key', 'key_invalid', 'erp_too_old', 'editor_too_old', 'integrity', 'too_large',
  'download_failed', 'bundle_invalid', 'already_installed', 'no_permission', 'busy']);
const FEED = new Set(['absent', 'unreachable', 'invalid', 'off']);
export function problemKey(code: string | null | undefined): string {
  const c = code ?? '';
  if (c.startsWith('feed_') && FEED.has(c.slice(5))) return `design.web_editor.feed.${c.slice(5)}`;
  if (c.startsWith('signature_')) return 'design.web_editor.problem.signature';
  return `design.web_editor.problem.${KNOWN.has(c) ? c : 'other'}`;
}

/** After a yes to the offer: fetch the full editor onto this server when the person may and it is not there yet. */
export async function installIfOffered(): Promise<boolean> {
  try {
    const s = await fetchWebEditorStatus();
    const offered = s.can_install && s.feed.state === 'available' && !s.feed.problem && !s.installed && !busy(s);
    if (!offered) return false;
    await startWebEditorInstall();
    return true;
  } catch {
    return false; // the engine keeps working; the editor page shows why
  }
}
