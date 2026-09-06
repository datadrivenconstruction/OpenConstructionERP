// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Tauri-only utilities for the file manager.
 *
 * In a Tauri build we can show the OS file picker, reveal a path in the
 * native finder, or copy text to the clipboard. In a browser build these
 * fall back to no-ops (or `navigator.clipboard.writeText`).
 *
 * The reveal goes through the invoke bridge in shared/lib/desktop, not
 * through @tauri-apps/plugin-shell. This module used to dynamic-import that
 * package so the web bundle would never resolve it at build time, which
 * worked in the sense that the bundle stayed clean and failed in the sense
 * that the desktop build has no copy of it to resolve either.
 */

// Desktop runtime detection now lives in shared/lib so non-file-manager code
// (auth bootstrap, onboarding) can reuse it without importing across feature
// boundaries. Re-export here so this module's existing consumers keep working.
import { isTauri, revealPathInOS } from '@/shared/lib/desktop';

export { isTauri };

export async function openInOSFinder(path: string): Promise<boolean> {
  // Kept under the file manager's own name because its consumers call it, but
  // the work and the failure reporting live in shared/lib/desktop beside the
  // outbound-link opener. Both reach native commands through the same bridge,
  // and keeping one of them somewhere else is how the two drifted: this one was
  // still calling the shell plugin long after the other had written down, in
  // its own comment, why that cannot work in the built webview.
  return revealPathInOS(path);
}

export async function copyToClipboard(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // continue to fallback
  }
  // Last-ditch fallback: textarea + execCommand. Works on every browser
  // released this decade and is fine for a small file path.
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'absolute';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
