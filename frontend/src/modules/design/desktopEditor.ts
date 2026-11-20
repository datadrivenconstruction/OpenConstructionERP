// Design module (ERP side of the design editor link).
/**
 * The desktop shell's editor commands (`design_editor_*`). They exist only inside the desktop app; in a browser
 * `desktopEditor()` is null and the page falls back to the `.ddclink` download. The page never names a program or a
 * download address: the shell starts only the build it installed itself.
 */

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;

export type Signature =
  | { state: 'verified'; signer: string }
  | { state: 'unsigned'; reason: string }
  | { state: 'invalid'; reason: string };

export type Install =
  | { result: 'installed'; name: string; signature: Signature }
  | { result: 'needs_confirmation'; reason: string };

export type Launch = { result: 'started' } | { result: 'not_installed' } | { result: 'needs_confirmation'; reason: string };

export interface EditorStatus {
  installed: boolean;
  name: string | null;
  signature: Signature | null;
}

export interface DesktopEditor {
  status(): Promise<EditorStatus>;
  launch(linkText: string, confirmed: boolean): Promise<Launch>;
  download(confirmed: boolean): Promise<Install>;
  installLocal(path: string, confirmed: boolean): Promise<Install>;
}

function invokeOf(): Invoke | undefined {
  if (typeof window === 'undefined') return undefined;
  const tauri = (window as { __TAURI__?: Record<string, unknown> }).__TAURI__;
  const core = tauri?.core as { invoke?: Invoke } | undefined;
  return core?.invoke ?? (tauri?.invoke as Invoke | undefined);
}

/** The bridge, or null outside the desktop app. */
export function desktopEditor(): DesktopEditor | null {
  const invoke = invokeOf();
  if (!invoke) return null;
  return {
    status: () => invoke('design_editor_status') as Promise<EditorStatus>,
    launch: (link, confirmed) => invoke('design_editor_launch', { link, confirmed }) as Promise<Launch>,
    download: (confirmed) => invoke('design_editor_download', { confirmed }) as Promise<Install>,
    installLocal: (path, confirmed) => invoke('design_editor_install_local', { path, confirmed }) as Promise<Install>,
  };
}

/** Tauri rejects with the command's error string; make sure the page always gets text. */
export function errorText(e: unknown): string {
  if (typeof e === 'string') return e;
  if (e instanceof Error) return e.message;
  return String(e);
}
