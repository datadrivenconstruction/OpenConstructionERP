import { useEffect } from 'react';

/** Tags where we should never intercept keyboard input. */
const INTERACTIVE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

/**
 * Listens for the "n" key press (when no input is focused) and calls the
 * provided callback.  Intended for module list pages that open a "create new"
 * form/modal when the user presses "n".
 *
 * @param onTrigger - Function to call when "n" is pressed (e.g. `() => setShowAddModal(true)`)
 * @param enabled   - Pass `false` to temporarily disable (e.g. when a modal is already open)
 */
export function useCreateShortcut(onTrigger: () => void, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;

    const handler = (e: KeyboardEvent) => {
      // Don't intercept when the user is typing in a form field.
      const el = document.activeElement;
      if (el && (INTERACTIVE_TAGS.has(el.tagName) || (el as HTMLElement).isContentEditable)) {
        return;
      }

      // Ignore events with modifier keys — those belong to the browser or OS.
      if (e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;

      if (e.key === 'n') {
        e.preventDefault();
        onTrigger();
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onTrigger, enabled]);
}
