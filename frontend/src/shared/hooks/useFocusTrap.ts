// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// useFocusTrap — keyboard focus containment for modal dialogs.
//
// Why it exists: dialogs (ConfirmDialog, WideModal, slide-overs) MUST
// prevent Tab / Shift+Tab from escaping the modal back into the page
// underneath. They MUST also restore focus to the element that opened
// them on close so keyboard users do not lose their place. Before this
// hook each dialog rolled its own (incomplete) handling and several
// had no trap at all — flagged in the Round 2 Wave D a11y audit.
//
// Usage:
//   const ref = useRef<HTMLDivElement>(null);
//   useFocusTrap(ref, isOpen);
//   return <div ref={ref}>…</div>;
//
// Behaviour:
//   * On mount (when `active` is true) the hook records the currently
//     focused element so it can be restored on cleanup.
//   * Intercepts Tab / Shift+Tab keydowns and wraps focus inside the
//     container — last → first on Tab, first → last on Shift+Tab.
//   * When the container unmounts (or `active` flips to false) the
//     previously focused element regains focus, regardless of whether
//     the dialog closed via Escape, backdrop click, or explicit button.

import { useEffect, type RefObject } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function getFocusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter((el) => {
      // Filter out elements that are hidden via CSS / aria-hidden.
      if (el.hasAttribute('disabled')) return false;
      if (el.getAttribute('aria-hidden') === 'true') return false;
      // offsetParent === null catches display:none + hidden ancestors.
      // Tabindex="-1" was already excluded by the selector.
      return el.offsetParent !== null || el === document.activeElement;
    });
}

export function useFocusTrap(
  ref: RefObject<HTMLElement>,
  active: boolean,
): void {
  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;

    // Capture the trigger element so we can restore focus on close.
    const previouslyFocused = document.activeElement as HTMLElement | null;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const focusable = getFocusable(container);
      if (focusable.length === 0) {
        // Nothing to focus inside; keep focus on the container itself
        // so Tab cannot escape.
        e.preventDefault();
        container.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      const current = document.activeElement as HTMLElement | null;

      if (e.shiftKey) {
        // Shift+Tab: wrap from first → last.
        if (current === first || !container.contains(current)) {
          e.preventDefault();
          last.focus();
        }
      } else {
        // Tab: wrap from last → first.
        if (current === last || !container.contains(current)) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown, true);

    return () => {
      document.removeEventListener('keydown', handleKeyDown, true);
      // Restore focus to whatever opened the dialog. Guard against the
      // trigger having been removed from the DOM in the meantime
      // (rare, but happens when the dialog deletes its own host row).
      if (previouslyFocused && document.contains(previouslyFocused)) {
        try {
          previouslyFocused.focus();
        } catch {
          // Some elements (e.g. detached SVG) throw on .focus() — swallow.
        }
      }
    };
  }, [ref, active]);
}
