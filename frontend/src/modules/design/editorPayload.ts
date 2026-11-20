// Design module (ERP side of the design editor link).
/** This ERP's payload for the editor page and the background load (data/webEditor.ts), resolved once per page. */
import wasmUrl from './wasm/ddc_web.wasm?url';
import { findPayload, scheduleBackgroundLoad, type Consent, type Payload } from './data/webEditor';
import { installedManifestUrl } from './webEditorApi';

let found: Promise<Payload & { fallback?: string }> | null = null;

export function currentPayload(): Promise<Payload & { fallback?: string }> {
  found ??= findPayload({
    env: import.meta.env as Record<string, string | undefined>,
    origin: window.location.origin,
    engineUrl: wasmUrl,
    installedUrl: installedManifestUrl,
  });
  return found;
}

/** After an install, update or removal on this server the next page asks again. */
export function forgetPayload(): void {
  found = null;
}

/** Called after the person says yes, on the editor page, and at start-up; does nothing without that yes. */
export function startBackgroundLoad(consent?: Consent): Promise<void> | null {
  return scheduleBackgroundLoad({ payload: currentPayload, consent });
}
