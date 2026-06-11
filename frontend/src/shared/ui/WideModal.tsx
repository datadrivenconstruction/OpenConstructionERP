// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// WideModal — shared modal component for forms with many fields.
//
// Why it exists: a recurring complaint across the recently-added
// modules (Service / Resources / Procurement / Portal / Schedule
// Advanced / HSE Advanced / BI Dashboards / ...) was that create/edit
// modals were uniformly clamped at ~max-w-lg (32rem). Forms with 6-12
// fields were squeezing labels onto a single column, leaving 2/3 of the
// viewport empty, and forcing users to scroll. The result was UX that
// looked unfinished and made multi-field inputs hard to scan.
//
// WideModal fixes that with:
//   * size variants `sm / md / lg / xl / 2xl / full` mapped to
//     `max-w-md … max-w-7xl`, so a contract form can comfortably show
//     two- or three-column grids while a confirmation can stay compact.
//   * a `<WideModalSection>` helper that renders a heading + grid wrapper
//     so callers do not need to know which Tailwind classes form a
//     `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` layout.
//   * built-in Escape + backdrop-click handling, body-scroll lock and
//     focus trap (same pattern as ConfirmDialog) so callers do not
//     have to re-implement the dialog plumbing.
//   * a sticky footer slot so primary/secondary CTAs never scroll out
//     of view when the form gets long.
//
// Accessibility: role="dialog", aria-modal, aria-labelledby pointed at
// the heading. Initial focus is moved into the first focusable form
// element; Escape and backdrop click both call onClose.

import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  type ReactElement,
} from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';

export type WideModalSize = 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'full';

const SIZE_CLASSES: Record<WideModalSize, string> = {
  sm: 'max-w-md',
  md: 'max-w-2xl',
  lg: 'max-w-3xl',
  xl: 'max-w-5xl',
  '2xl': 'max-w-6xl',
  full: 'max-w-[min(1280px,calc(100vw-2rem))]',
};

export interface WideModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Optional descriptive subtitle rendered under the title. */
  subtitle?: React.ReactNode;
  /** Maximum width preset — defaults to `lg` (~768px). */
  size?: WideModalSize;
  /** Form body. Use <WideModalSection> for grouped fields. */
  children: React.ReactNode;
  /** Sticky footer — typically a pair of buttons (Cancel / Submit). */
  footer?: React.ReactNode;
  /**
   * Lock close-on-backdrop / Escape (e.g. while a submit is in flight
   * so users do not accidentally dismiss a pending request).
   */
  busy?: boolean;
  /** Hide the close (X) icon — rare; default false. */
  hideCloseButton?: boolean;
  /** Extra class names appended to the panel root. */
  className?: string;
}

export function WideModal({
  open,
  onClose,
  title,
  subtitle,
  size = 'lg',
  children,
  footer,
  busy = false,
  hideCloseButton = false,
  className,
}: WideModalProps) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  const headingId = useId();
  const subtitleId = useId();

  // Escape closes the modal (unless busy).
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

  // Lock body scroll while open; restore previous overflow on unmount.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // Move initial focus into the first focusable element inside the
  // panel — typically the first <input>. This matches modal a11y
  // expectations and saves callers one useRef + autoFocus dance.
  useEffect(() => {
    if (!open) return;
    const node = panelRef.current;
    if (!node) return;
    const focusable = node.querySelector<HTMLElement>(
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])',
    );
    focusable?.focus();
  }, [open]);

  // Trap Tab inside the panel and restore focus to the triggering
  // element when the modal closes (covers Escape, backdrop click and
  // explicit close-button). The earlier source comment claimed a trap
  // existed but the implementation was missing — Round 2 Wave D audit.
  useFocusTrap(panelRef, open);

  if (!open) return null;

  const handleBackdrop = (e: React.MouseEvent) => {
    if (busy) return;
    if (e.target === e.currentTarget) onClose();
  };

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={headingId}
      aria-describedby={subtitle ? subtitleId : undefined}
      onMouseDown={handleBackdrop}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 backdrop-blur-sm py-8 px-4"
    >
      <div
        ref={panelRef}
        className={clsx(
          'relative w-full mx-auto my-auto',
          SIZE_CLASSES[size],
          'rounded-2xl border border-border-light shadow-2xl',
          'bg-surface-elevated',
          'animate-scale-in',
          'flex flex-col max-h-[calc(100vh-4rem)]',
          className,
        )}
        // Stop propagation so click inside the panel does not bubble up
        // to the backdrop close handler.
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-border-light/60">
          <div className="min-w-0">
            <h2
              id={headingId}
              className="text-lg font-semibold text-content-primary truncate"
            >
              {title}
            </h2>
            {subtitle && (
              <p
                id={subtitleId}
                className="mt-1 text-sm text-content-secondary leading-relaxed"
              >
                {subtitle}
              </p>
            )}
          </div>
          {!hideCloseButton && (
            <button
              type="button"
              onClick={() => !busy && onClose()}
              disabled={busy}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className={clsx(
                'shrink-0 -mt-1 -mr-1 inline-flex h-8 w-8 items-center justify-center rounded-lg',
                'text-content-secondary hover:text-content-primary',
                'hover:bg-surface-secondary',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                'disabled:opacity-40 disabled:pointer-events-none transition-colors',
              )}
            >
              <X size={18} />
            </button>
          )}
        </header>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>

        {/* Sticky footer */}
        {footer && (
          <footer className="shrink-0 px-6 py-4 border-t border-border-light/60 bg-surface-primary/30 rounded-b-2xl flex items-center justify-end gap-2">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

// ── Section helper ──────────────────────────────────────────────────
//
// Renders a labelled group of form fields inside a responsive grid.
// Most callers want `columns={2}` for desktop with single-column fall
// back on mobile; pass `columns={3}` for very dense layouts (e.g.
// procurement line items).

export interface WideModalSectionProps {
  /** Section heading (rendered as <h3>). */
  title?: string;
  /** Optional helper copy under the heading. */
  description?: string;
  /** Grid columns at >= sm breakpoint. */
  columns?: 1 | 2 | 3;
  children: React.ReactNode;
  className?: string;
}

const COLUMN_CLASSES: Record<1 | 2 | 3, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 sm:grid-cols-2',
  3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
};

export function WideModalSection({
  title,
  description,
  columns = 2,
  children,
  className,
}: WideModalSectionProps) {
  return (
    <section className={clsx('mb-6 last:mb-0', className)}>
      {title && (
        <h3 className="text-sm font-semibold text-content-primary mb-1">
          {title}
        </h3>
      )}
      {description && (
        <p className="text-xs text-content-secondary mb-3 leading-relaxed">
          {description}
        </p>
      )}
      <div className={clsx('grid gap-4', COLUMN_CLASSES[columns])}>
        {children}
      </div>
    </section>
  );
}

// ── Field wrapper ───────────────────────────────────────────────────
//
// Most form fields share the same structure: <label> + <input/select>
// + optional hint + optional error. <WideModalField> abstracts that so
// callers do not re-implement the same JSX in every modal.

export interface WideModalFieldProps {
  /** Field label. Omit for label-less fields such as inline info/hint rows. */
  label?: string;
  /** Visible "*" + aria-required on the label. */
  required?: boolean;
  /** Lighter helper text below the input. */
  hint?: string;
  /** Validation error text — overrides hint when set. */
  error?: string;
  /** Span across multiple grid columns (1-3). */
  span?: 1 | 2 | 3;
  children: React.ReactNode;
  className?: string;
  /** Optional htmlFor target — wire to the wrapped input id. */
  htmlFor?: string;
}

const SPAN_CLASSES: Record<1 | 2 | 3, string> = {
  1: 'sm:col-span-1',
  2: 'sm:col-span-2',
  3: 'sm:col-span-2 lg:col-span-3',
};

export function WideModalField({
  label,
  required = false,
  hint,
  error,
  span = 1,
  children,
  className,
  htmlFor,
}: WideModalFieldProps) {
  // A11y: when `required` is set we want the inner form control to also
  // expose aria-required to assistive tech (a screen reader only reads
  // the wrapper's "*" if it can associate it with the field — which the
  // visual asterisk alone does not do, per WCAG 3.3.2). We clone the
  // first valid React-element child and inject aria-required="true" so
  // every call site picks this up automatically, without a per-form
  // change. If the child is a Fragment, plain text, or already declares
  // aria-required, we leave it untouched.
  const enhancedChildren = required
    ? Children.map(children, (child, idx) => {
        if (idx !== 0) return child;
        if (!isValidElement(child)) return child;
        const existing = (child.props as Record<string, unknown>)[
          'aria-required'
        ];
        if (existing !== undefined) return child;
        return cloneElement(child as ReactElement<Record<string, unknown>>, {
          'aria-required': true,
        });
      })
    : children;

  return (
    <div className={clsx('flex flex-col', SPAN_CLASSES[span], className)}>
      {label && (
        <label
          htmlFor={htmlFor}
          className="text-xs font-medium text-content-primary mb-1.5 flex items-center gap-1"
        >
          {label}
          {required && (
            <span aria-hidden="true" className="text-semantic-error">
              *
            </span>
          )}
        </label>
      )}
      {enhancedChildren}
      {error ? (
        <p className="mt-1 text-xs text-semantic-error">{error}</p>
      ) : hint ? (
        <p className="mt-1 text-xs text-content-secondary">{hint}</p>
      ) : null}
    </div>
  );
}
