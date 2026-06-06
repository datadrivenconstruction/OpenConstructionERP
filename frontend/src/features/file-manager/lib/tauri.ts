/** Tauri-only utilities for the file manager.
 *
 * In a Tauri build we can show the OS file picker, reveal a path in the
 * native finder, or copy text to the clipboard. In a browser build these
 * fall back to no-ops (or `navigator.clipboard.writeText`).
 *
 * We dynamic-import the Tauri APIs so the web bundle never resolves them
 * at build time.
 */

// Desktop runtime detection now lives in shared/lib so non-file-manager code
// (auth bootstrap, onboarding) can reuse it without importing across feature
// boundaries. Re-export here so this module's existing consumers keep working.
import { isTauri } from '@/shared/lib/desktop';

export { isTauri };

export async function openInOSFinder(path: string): Promise<boolean> {
  if (!path) return false;
  if (isTauri) {
    try {
      // Plugin is only present in Tauri builds — we resolve it dynamically
      // through a variable so tsc doesn't try to type-check the missing
      // module, and cast the result because the web bundle has no
      // @tauri-apps/plugin-shell dep.
      const tauriPluginShell = '@tauri-apps/plugin-shell';
      const mod = (await import(/* @vite-ignore */ tauriPluginShell)) as {
        open: (target: string) => Promise<void>;
      };
      // openPath would open the file itself; we want the *containing folder*.
      // Cross-platform "reveal" needs the parent directory, so we strip the
      // trailing segment if it looks like a file.
      const isFile = /\.[a-z0-9]{1,8}$/i.test(path);
      const target = isFile ? path.replace(/[\\/][^\\/]+$/, '') : path;
      await mod.open(target);
      return true;
    } catch (err) {
      // Plugin might not be enabled in this build — fall through.
      console.warn('Tauri shell open failed:', err);
    }
  }
  return false;
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
