// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Small controls shared by the proposal card, the Changes rows and the review
 * tray: a compact button with a real busy state, and the confirmation dialog.
 *
 * The button is local rather than the shared `Button` for one reason: a busy
 * shared Button replaces its label with a bare spinner and fades to 40 %,
 * which on a card that is writing to the project reads as "disabled" rather
 * than "working on it". This one keeps its words ("Applying…") and full
 * contrast while it blocks further clicks.
 *
 * The dialog is the shared `ConfirmDialog`, portalled to `document.body`: the
 * dock may be a transformed, fixed element, and a fixed dialog inside a
 * transformed ancestor would be pinned to the dock instead of the viewport.
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import clsx from 'clsx';
import { Loader2 } from 'lucide-react';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';

type Tone = 'primary' | 'secondary' | 'ghost';

export interface ActionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: Tone;
  /** Shows a spinner and `busyLabel`, blocks clicks, keeps full contrast. */
  busy?: boolean;
  busyLabel?: string;
  icon?: ReactNode;
}

const TONES: Record<Tone, string> = {
  primary: 'bg-oe-blue text-content-inverse hover:bg-oe-blue-hover active:bg-oe-blue-active shadow-xs',
  secondary:
    'border border-[var(--act-border)] bg-[var(--act-bg)] text-[var(--act-text)] hover:bg-[var(--act-surface)]',
  ghost: 'text-[var(--act-text-2)] hover:bg-[var(--act-surface)] hover:text-[var(--act-text)]',
};

export const ActionButton = forwardRef<HTMLButtonElement, ActionButtonProps>(function ActionButton(
  { tone = 'secondary', busy = false, busyLabel, icon, disabled, className, children, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={clsx(
        'inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-md px-2.5',
        'text-xs font-medium whitespace-nowrap select-none transition-colors duration-150',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--act-bg)]',
        TONES[tone],
        busy ? 'cursor-progress' : 'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...rest}
    >
      {busy ? (
        <Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
      ) : (
        icon && (
          <span className="inline-flex shrink-0" aria-hidden="true">
            {icon}
          </span>
        )
      )}
      <span>{busy && busyLabel ? busyLabel : children}</span>
    </button>
  );
});

export interface ActionConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** The shared confirmation dialog, rendered over the whole viewport. */
export function ActionConfirmDialog({ open, ...props }: ActionConfirmDialogProps) {
  if (!open || typeof document === 'undefined') return null;
  return createPortal(<ConfirmDialog open variant="warning" {...props} />, document.body);
}
