// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// useTabKeyboardNav — small helper that returns an onKeyDown handler
// implementing the WAI-ARIA "tabs" keyboard pattern (ArrowLeft / Right
// / Up / Down + Home / End) for tab strips that aren't using the shared
// <TabBar> component yet (vertical sidebars, custom-styled strips, etc.)
//
// Use the <TabBar> component when you can — it bakes in the keyboard
// pattern. Reach for this hook only when the strip needs to keep its
// existing markup (e.g. SettingsPage's dual mobile/desktop layout).

import { useCallback, type KeyboardEvent } from 'react';

export interface UseTabKeyboardNavOptions<TId extends string> {
  ids: readonly TId[];
  activeId: TId;
  onChange: (next: TId) => void;
  /** "horizontal" (default) uses ArrowLeft/Right; "vertical" uses Up/Down.
   *  "both" accepts either pair. */
  orientation?: 'horizontal' | 'vertical' | 'both';
  /** Disabled tab ids — these are skipped during navigation. */
  disabledIds?: readonly TId[];
}

export function useTabKeyboardNav<TId extends string>({
  ids,
  activeId,
  onChange,
  orientation = 'horizontal',
  disabledIds,
}: UseTabKeyboardNavOptions<TId>) {
  return useCallback(
    (e: KeyboardEvent<HTMLElement>) => {
      const enabled = ids.filter(
        (id) => !disabledIds || !disabledIds.includes(id),
      );
      if (enabled.length === 0) return;
      const idx = enabled.indexOf(activeId);
      const safe = idx === -1 ? 0 : idx;
      let next: number | null = null;
      const k = e.key;
      const horiz = orientation === 'horizontal' || orientation === 'both';
      const vert = orientation === 'vertical' || orientation === 'both';
      if ((horiz && k === 'ArrowLeft') || (vert && k === 'ArrowUp')) {
        next = (safe - 1 + enabled.length) % enabled.length;
      } else if ((horiz && k === 'ArrowRight') || (vert && k === 'ArrowDown')) {
        next = (safe + 1) % enabled.length;
      } else if (k === 'Home') {
        next = 0;
      } else if (k === 'End') {
        next = enabled.length - 1;
      } else {
        return;
      }
      if (next === null) return;
      e.preventDefault();
      e.stopPropagation();
      const target = enabled[next];
      if (target !== undefined) onChange(target);
    },
    [activeId, disabledIds, ids, onChange, orientation],
  );
}
