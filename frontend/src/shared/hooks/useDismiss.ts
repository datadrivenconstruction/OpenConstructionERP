// useDismiss: Escape, optional backdrop click and initial focus for hand-rolled dialogs.
//
// Spread the result on the full-screen overlay element:
//   const dismiss = useDismiss({ onClose, enabled: open });
//   <div {...dismiss} className="fixed inset-0 ...">
//
// Escape only reacts while this overlay is the topmost one (see useFocusTrap),
// so a dialog opened from a drawer closes alone. Prefer WideModal / SideDrawer
// for new dialogs; this hook exists for overlays with their own markup.

import { useEffect, useRef, type MouseEvent, type RefObject } from 'react';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';

export interface UseDismissOptions {
  onClose: () => void;
  /** False while the dialog is not shown. Default true. */
  enabled?: boolean;
  /** Close on a click on the dim area around the panel. Default false. */
  backdrop?: boolean;
  /** Block Escape and backdrop while a save or upload is in flight. */
  busy?: boolean;
}

export interface DismissProps {
  ref: RefObject<HTMLDivElement>;
  onMouseDown: (e: MouseEvent<HTMLElement>) => void;
}

const INITIAL_FOCUS =
  '[autofocus], input:not([disabled]):not([type="hidden"]), textarea:not([disabled]), select:not([disabled]), button:not([disabled]), [href]';

export function useDismiss({ onClose, enabled = true, backdrop = false, busy = false }: UseDismissOptions): DismissProps {
  const ref = useRef<HTMLDivElement>(null);
  const isTopmost = useFocusTrap(ref, enabled);
  const latest = useRef({ onClose, busy });
  latest.current = { onClose, busy };

  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented || latest.current.busy || !isTopmost()) return;
      e.preventDefault();
      latest.current.onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [enabled, isTopmost]);

  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el || el.contains(document.activeElement)) return;
    const target = el.querySelector<HTMLElement>(INITIAL_FOCUS);
    if (target) target.focus();
    else {
      el.tabIndex = -1;
      el.focus();
    }
  }, [enabled]);

  return {
    ref,
    onMouseDown: (e) => {
      if (backdrop && !latest.current.busy && e.target === e.currentTarget) latest.current.onClose();
    },
  };
}
