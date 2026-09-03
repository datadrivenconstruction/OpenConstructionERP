// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Escape-to-close plus focus return, for the modals added by the project-team
 * work (the availability popup and the proposal viewer).
 *
 * Focus return is the part that is usually missed: the element that opened the
 * modal is remembered on mount and re-focused on unmount, so a keyboard user
 * who closes the popup lands back on the member card they opened it from
 * rather than at the top of the document. Outside-click close stays with the
 * caller — it is one `onClick` on the backdrop and putting it here would mean
 * threading a ref for no gain.
 */

import { useEffect, useRef } from 'react';

export function useModalDismiss(open: boolean, onClose: () => void): void {
  // Kept in a ref so a caller passing an inline arrow does not re-register the
  // key listener (and, worse, re-run the focus-return effect) every render.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;

    const opener =
      typeof document !== 'undefined'
        ? (document.activeElement as HTMLElement | null)
        : null;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        closeRef.current();
      }
    };
    window.addEventListener('keydown', onKey);

    return () => {
      window.removeEventListener('keydown', onKey);
      // The opener can be gone by now (the list re-rendered, the row was
      // removed) — isConnected keeps us from focusing a detached node.
      if (opener && opener.isConnected && typeof opener.focus === 'function') {
        opener.focus();
      }
    };
  }, [open]);
}
