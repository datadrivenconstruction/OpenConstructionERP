// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wraps one panel of a module page that a course can keep closed, e.g. the
// BOQ markups panel:
//
//   <TrainerPanelGate lockId="boq.markups_panel">
//     <MarkupPanel ... />
//   </TrainerPanelGate>
//
// It is a component, not a hook, so the host page gains no hook (and no
// hooks-above-early-return risk).
//
// Trainer off, or no enrolment: the children, unchanged, in a fragment; no
// extra DOM and no request. Lock closed: LockedPanelCard in place of the
// panel. Lock open: the children, and when the URL hash names the panel's
// anchor the gate scrolls to it once (how an Academy row deep-links into the
// panel). Locks are UI only: the panel's API stays open either way.

import { useEffect, useRef, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { LockedPanelCard } from './LockedPanelCard';
import { getLock } from './lockRegistry';
import { lockedLockIds, panelAnchorFor } from './routeMatch';
import { useTrainerMode } from './useTrainerMode';

export interface TrainerPanelGateProps {
  /** A registered lock id (`lockRegistry.ts`). */
  lockId: string;
  /** DOM id of the panel; defaults to the registry's `panelAnchor`. */
  anchorId?: string | null;
  children: ReactNode;
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

export function TrainerPanelGate({ lockId, anchorId, children }: TrainerPanelGateProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const mode = useTrainerMode();
  const anchor = anchorId ?? panelAnchorFor(lockId);
  const registered = getLock(lockId) !== null;
  const closed = mode.state === 'enrolled' && registered && lockedLockIds(mode.me).has(lockId);
  const openUnderCourse = mode.state === 'enrolled' && !closed;

  // Scroll once per navigation, never on a re-render of the same one.
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    if (!openUnderCourse || !anchor || location.hash !== `#${anchor}`) return;
    if (scrolledFor.current === location.key) return;
    // Marked inside the frame, so a StrictMode effect replay (which cancels
    // the first frame) still scrolls.
    const key = location.key;
    const frame = requestAnimationFrame(() => {
      scrolledFor.current = key;
      const el = document.getElementById(anchor);
      if (el && typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [openUnderCourse, anchor, location.hash, location.key]);

  // A badge or an unregistered id is a registry bug, not a learner state.
  if (!registered) return <>{children}</>;

  switch (mode.state) {
    case 'off':
    case 'none':
    case 'enrolled':
      return closed ? <LockedPanelCard lockId={lockId} anchorId={anchor} mode={mode} /> : <>{children}</>;
    case 'error':
      return <LockedPanelCard lockId={lockId} anchorId={anchor} mode={mode} />;
    case 'checking':
    case 'loading':
      return (
        <div
          id={anchor ?? undefined}
          role="status"
          aria-busy="true"
          className="mt-4 h-28 scroll-mt-28 rounded-xl border border-border-light bg-surface-secondary motion-safe:animate-pulse"
          data-testid="trainer-panel-pending"
        >
          <span className="sr-only">{t('trainer.state.loading', { defaultValue: 'Loading your course' })}</span>
        </div>
      );
  }
}
