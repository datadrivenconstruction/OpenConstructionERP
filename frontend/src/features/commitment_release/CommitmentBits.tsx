// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the commitment screens share: a button that says why it is
// disabled, an amount that says "unknown" instead of printing a zero, the
// colour of each state, and the box a server refusal is shown in.

import { useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button, type ButtonProps } from '@/shared/ui/Button';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getErrorMessage } from '@/shared/lib/api';

import { DISABLED_REASON, type Verdict } from './access';
import { commitmentErrorCode, commitmentErrorMessage, type ItemStatus, type ReleaseOutcome } from './api';
import { errorText, type TFn } from './labels';

/**
 * Why an action is off, in words. A code with a sentence written for the
 * button uses it; any other code reads as the refusal the server would send.
 */
export function reasonText(t: TFn, verdict: string): string {
  const own = DISABLED_REASON[verdict];
  return own ? t(own[0], { defaultValue: own[1] }) : errorText(t, verdict);
}

/**
 * A button that, when it may not be pressed, stays visible and says why.
 *
 * Hiding a control silently leaves the reader guessing whether the feature
 * exists; a disabled control with a reason tells them who can act instead.
 */
export function ReasonedButton({
  verdict,
  children,
  disabled,
  ...rest
}: ButtonProps & { verdict: Verdict; children: ReactNode }) {
  const { t } = useTranslation();
  const reasonId = useId();
  const reason = verdict ? reasonText(t, verdict) : null;
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        {...rest}
        disabled={disabled || !!verdict}
        aria-describedby={reason ? reasonId : undefined}
        title={reason ?? rest.title}
      >
        {children}
      </Button>
      {reason && (
        <span
          id={reasonId}
          data-testid="disabled-reason"
          data-reason={verdict ?? undefined}
          className="inline-flex max-w-xs items-start gap-1 text-2xs text-content-tertiary"
        >
          <Info size={11} className="mt-px shrink-0" aria-hidden />
          {reason}
        </span>
      )}
    </span>
  );
}

/**
 * An amount in its currency. A null amount is unknown and reads as such: a
 * figure that could not be worked out must not look like nothing is owed.
 */
export function Amount({
  value,
  currency,
  unknownLabel,
  className,
}: {
  value: string | null | undefined;
  currency: string;
  unknownLabel?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  if (value == null) {
    return (
      <span className="text-content-tertiary" data-testid="amount-unknown">
        {unknownLabel ?? t('commitment.unknown_amount', { defaultValue: 'Unknown' })}
      </span>
    );
  }
  return <MoneyDisplay amount={value} currency={currency} className={className} />;
}

export const ITEM_STATUS_TONE: Record<ItemStatus, BadgeVariant> = {
  planned: 'neutral',
  release_requested: 'purple',
  released: 'success',
  partially_released: 'blue',
  committed: 'success',
  closed: 'neutral',
  re_release_required: 'error',
  on_hold: 'warning',
  aborted: 'error',
  transferred: 'neutral',
};

export const OUTCOME_TONE: Record<ReleaseOutcome, BadgeVariant> = {
  pending: 'purple',
  released: 'success',
  rejected: 'error',
  withdrawn: 'neutral',
  aborted: 'error',
};

export function ToneBadge({ tone, children, testId }: { tone: BadgeVariant; children: ReactNode; testId?: string }) {
  return (
    <span data-testid={testId}>
      <Badge variant={tone} size="sm">
        {children}
      </Badge>
    </span>
  );
}

/**
 * The sentence for a failed request: the commitment refusal by its code when
 * the server named one, otherwise whatever the shared error reader makes of it.
 */
export function refusalText(t: TFn, err: unknown): string {
  const code = commitmentErrorCode(err);
  if (code) return errorText(t, code, commitmentErrorMessage(err));
  return getErrorMessage(err);
}

/** A server refusal, shown where the reader was working rather than in a toast that fades. */
export function RefusalBox({ message, children }: { message: string | null; children?: ReactNode }) {
  if (!message && !children) return null;
  return (
    <div
      role="alert"
      data-testid="refusal"
      className="rounded-md border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm"
    >
      {message && <p className="font-medium text-content-primary">{message}</p>}
      {children}
    </div>
  );
}

export const FIELD_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

/** A labelled form field: the label is a real `<label>` so a click and a screen reader both find the control. */
export function Field({
  id,
  label,
  hint,
  required,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-content-primary">
        {label}
        {required && (
          <span className="ml-1 text-xs font-normal text-semantic-error">
            {t('commitment.required', { defaultValue: 'required' })}
          </span>
        )}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-content-tertiary">{hint}</p>}
    </div>
  );
}
