// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SideDrawer — shared right-side slide-over panel for detail views.
//
// Why it exists: feature pages that show a master-detail flow (Property
// Dev buyers/plots, CRM opportunities/leads, BIM assets, file
// transmittals) all rolled their own inline ``fixed inset-0 z-50 flex
// justify-end`` overlay. Each implementation diverged subtly:
//
//   * Several attached an Escape handler to ``window`` (anti-pattern —
//     cannot be cleaned up reliably under React StrictMode double-mount
//     and bubbles ahead of nested modals).
//   * None used ``createPortal``, which meant a ``relative isolate``
//     ancestor (frequent on per-page wrappers) trapped the z-50 panel
//     inside a stacking context the sticky header painted over.
//   * Body scroll was not locked, so wheel events behind the open drawer
//     scrolled the page underneath.
//   * Focus trap was missing; Tab escaped into the page below and on
//     close focus was lost (poor a11y).
//   * When the underlying list refetched while a drawer was open, React
//     reconciler occasionally fired ``insertBefore`` errors because the
//     drawer's child tree referenced a detached parent node.
//
// SideDrawer fixes all of the above with a single component that mirrors
// the existing WideModal contract:
//
//   * ``createPortal`` to ``document.body`` so the drawer always paints
//     on top of every page-level stacking context.
//   * ``useFocusTrap`` (the same hook WideModal/ConfirmDialog use) — Tab
//     wraps inside the panel and focus is restored to the trigger on
//     close.
//   * Body scroll lock with cleanup that captures the previous overflow
//     value (so nested drawers don't permanently lock the page).
//   * Escape handler attached to ``document`` via ``useEffect``, NOT
//     ``window``, with capture-phase listener and proper cleanup. Honours
//     a ``busy`` flag so callers can lock close during pending mutations.
//   * Backdrop click closes by default (overridable for forms with
//     unsaved state).
//   * Right-slide animation: 250ms ``transition-transform`` driven by a
//     mount-time ``isShown`` flag so the panel starts off-screen and
//     animates in.
//   * Accessibility: ``role="dialog"``, ``aria-modal="true"``,
//     ``aria-labelledby`` auto-wired to the title heading. Initial focus
//     moves into the first focusable element inside the panel.
//   * Mobile-first: full-width on narrow screens (the configurable
//     ``widthClass`` only kicks in at the ``sm`` breakpoint and above).
//
// The component is intentionally narrower than WideModal: it only owns
// the chrome (title bar with optional action slot, scrollable body) so
// callers stay free to lay out the content however the feature requires.

import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import clsx from 'clsx';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { useTranslation } from 'react-i18next';

export interface SideDrawerProps {
  /** Controls whether the drawer is rendered. */
  open: boolean;
  /** Invoked when the user requests close (X / Escape / backdrop). */
  onClose: () => void;
  /** Title shown in the sticky header; also used for aria-labelledby. */
  title: React.ReactNode;
  /** Optional second line under the title (e.g. subtitle / status). */
  subtitle?: React.ReactNode;
  /**
   * Tailwind max-width class for the panel at >= sm breakpoint. Defaults
   * to ``max-w-xl`` which matches the BuyerDetailDrawer width pre-migration.
   * On narrower viewports the drawer is always full-width regardless of
   * this prop.
   */
  widthClass?: string;
  /** Drawer body. Caller controls layout / padding. */
  children: React.ReactNode;
  /**
   * Right-aligned slot in the header — typically Edit / Delete / Menu
   * buttons. The close (X) icon is rendered after this slot, so caller
   * actions appear first in DOM order (and Tab order).
   */
  headerActions?: React.ReactNode;
  /**
   * When ``true``, Escape and backdrop click are ignored (use this while
   * a mutation is in flight so users don't accidentally dismiss).
   */
  busy?: boolean;
  /**
   * When ``false``, clicking the backdrop does NOT call onClose (the X
   * button and Escape still do). Use for forms with unsaved state.
   */
  backdropCloses?: boolean;
  /**
   * Hide the close (X) icon. Rare; default false.
   */
  hideCloseButton?: boolean;
  /** Extra class names appended to the panel root. */
  className?: string;
  /**
   * Pre-rendered ``id`` to use for aria-labelledby. Defaults to a
   * ``useId``-generated id wired to the title heading. Provide this if
   * the caller renders its own heading inside ``children`` instead of
   * using the built-in title chrome.
   */
  'aria-labelledby'?: string;
}

/**
 * Right-side slide-over panel with portal + focus trap + scroll lock.
 *
 * Behaviour matches the WideModal contract so a11y is consistent across
 * the app: Escape closes, focus traps inside, focus returns to trigger
 * on unmount.
 */
export function SideDrawer({
  open,
  onClose,
  title,
  subtitle,
  widthClass = 'max-w-xl',
  children,
  headerActions,
  busy = false,
  backdropCloses = true,
  hideCloseButton = false,
  className,
  'aria-labelledby': ariaLabelledBy,
}: SideDrawerProps) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  const generatedHeadingId = useId();
  const headingId = ariaLabelledBy ?? generatedHeadingId;
  // ``isShown`` drives the slide-in transform. We render the panel
  // off-screen for one frame, then flip to ``translate-x-0`` so React
  // commits the initial transform before the transition kicks in.
  const [isShown, setIsShown] = useState(false);

  // Escape closes (unless busy). Listener attached to document, NOT
  // window, with capture phase so we beat any page-level keybindings.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onClose, busy]);

  // Body scroll lock — capture the previous overflow so nested drawers
  // restore the correct value (not a hard-coded empty string).
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // Two-phase mount for the slide-in animation:
  //   1. Render off-screen (isShown=false → ``translate-x-full``).
  //   2. Next animation frame, flip to on-screen so the transition runs.
  useEffect(() => {
    if (!open) {
      setIsShown(false);
      return;
    }
    const raf = requestAnimationFrame(() => setIsShown(true));
    return () => cancelAnimationFrame(raf);
  }, [open]);

  // Tab containment + restore-focus-to-trigger on close (covers Escape,
  // backdrop click, and explicit close-button paths uniformly).
  //
  // IMPORTANT: registered BEFORE the initial-focus effect so that the
  // hook captures ``document.activeElement`` (the trigger) before we
  // move focus into the panel. If the order were reversed, the trap
  // would capture the close button as the "previously focused" element
  // and on close try to restore focus to a control that has been
  // unmounted, leaving the page with no focus at all.
  useFocusTrap(panelRef, open);

  // Move initial focus into the first focusable element (matches
  // WideModal). If there is nothing focusable, focus the panel itself.
  useEffect(() => {
    if (!open) return;
    const node = panelRef.current;
    if (!node) return;
    const focusable = node.querySelector<HTMLElement>(
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    );
    (focusable ?? node).focus();
  }, [open]);

  if (!open) return null;

  const handleBackdrop = (e: React.MouseEvent) => {
    if (busy || !backdropCloses) return;
    if (e.target === e.currentTarget) onClose();
  };

  return createPortal(
    <div
      // Outer wrapper covers the viewport; backdrop click handler lives
      // here so any click NOT inside the panel collapses to close.
      onMouseDown={handleBackdrop}
      className="fixed inset-0 z-50 flex justify-end"
    >
      {/* Backdrop — separate node so we can fade it independently. */}
      <div
        aria-hidden="true"
        className={clsx(
          'absolute inset-0 bg-black/30 transition-opacity duration-200',
          isShown ? 'opacity-100' : 'opacity-0',
        )}
      />
      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        // Negative tabindex makes the panel focusable as a fallback when
        // it contains no focusable controls (Tab still wraps via the
        // focus trap, but initial focus needs *something*).
        tabIndex={-1}
        className={clsx(
          'relative h-full w-full sm:w-auto',
          // Narrow viewports → full width; sm breakpoint → caller's
          // configured width with sane fallback.
          `sm:${widthClass}`,
          widthClass, // also apply unprefixed so the panel never exceeds it
          'overflow-y-auto bg-surface-elevated shadow-xl',
          'transform transition-transform duration-250 ease-out',
          isShown ? 'translate-x-0' : 'translate-x-full',
          // Safe-area inset on the right matters on iOS notch landscape;
          // the bottom inset is reserved for body padding so the close
          // button stays reachable above the home indicator.
          'pr-[env(safe-area-inset-right,0)]',
          className,
        )}
        // Stop propagation so a click inside the panel does not bubble
        // up to the backdrop handler and close the drawer.
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Sticky header */}
        <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-border-light bg-surface-elevated px-5 py-3">
          <div className="min-w-0 flex-1">
            <h2
              id={headingId}
              className="truncate text-base font-semibold text-content-primary"
            >
              {title}
            </h2>
            {subtitle && (
              <div className="truncate text-xs text-content-tertiary">{subtitle}</div>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {headerActions}
            {!hideCloseButton && (
              <button
                type="button"
                onClick={() => !busy && onClose()}
                disabled={busy}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className={clsx(
                  'inline-flex h-7 w-7 items-center justify-center rounded',
                  'text-content-secondary hover:text-content-primary hover:bg-surface-secondary',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                  'disabled:opacity-40 disabled:pointer-events-none transition-colors',
                )}
              >
                <X size={16} />
              </button>
            )}
          </div>
        </div>
        {/* Body — caller owns padding. */}
        {children}
      </div>
    </div>,
    document.body,
  );
}
