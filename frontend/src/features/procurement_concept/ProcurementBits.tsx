// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the procurement screens share: a button that says why it is
// disabled, the colour of each state, a list of rule findings, the box that
// shows a refusal in full, and a labelled form field.

import { useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info, XCircle } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button, type ButtonProps } from '@/shared/ui/Button';
import { formatCurrency } from '@/shared/lib/money';

import {
  procurementErrorCode,
  procurementErrorMessage,
  procurementViolations,
  type ConceptState,
  type Finding,
  type FrameworkState,
  type PackageState,
  type ThresholdStatus,
} from './api';
import { errorText, findingText, type TFn } from './labels';
import type { Verdict } from './rules';
import { getErrorMessage } from '@/shared/lib/api';

export const FIELD_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-60';

/**
 * A button that, when it may not be pressed, stays visible and says why.
 *
 * Hiding a control silently leaves the reader guessing whether the feature
 * exists; a disabled control with the server's reason tells them who can act.
 */
export function ReasonedButton({
  verdict,
  children,
  disabled,
  quiet = false,
  ...rest
}: ButtonProps & {
  verdict: Verdict;
  children: ReactNode;
  /** In a table row the reason goes to the tooltip and to screen readers; the screen states it once above the table. */
  quiet?: boolean;
}) {
  const { t } = useTranslation();
  const reasonId = useId();
  const reason = verdict ? errorText(t as TFn, verdict) : null;
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
          className={quiet ? 'sr-only' : 'inline-flex max-w-xs items-start gap-1 text-2xs text-content-tertiary'}
        >
          <Info size={11} className="mt-px shrink-0" aria-hidden />
          {reason}
        </span>
      )}
    </span>
  );
}

export const CONCEPT_TONE: Record<ConceptState, BadgeVariant> = {
  draft: 'neutral',
  in_review: 'blue',
  approved: 'success',
  binding: 'success',
  reopened: 'warning',
};

export const PACKAGE_TONE: Record<PackageState, BadgeVariant> = {
  planned: 'neutral',
  procedure_set: 'blue',
  shortlisted: 'purple',
  in_tender: 'warning',
  awarded: 'success',
  cancelled: 'neutral',
  on_hold: 'warning',
};

export const FRAMEWORK_TONE: Record<FrameworkState, BadgeVariant> = {
  draft: 'neutral',
  active: 'success',
  exhausted: 'warning',
  expired: 'neutral',
  terminated: 'error',
};

export const THRESHOLD_TONE: Record<ThresholdStatus, BadgeVariant> = {
  above: 'purple',
  below: 'success',
  unconfirmed: 'warning',
  unresolved: 'error',
  unavailable: 'error',
  not_applicable: 'neutral',
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

/** An amount with its currency, or a dash when there is none. */
export function Money({ value, currency }: { value: string | null | undefined; currency?: string | null }) {
  if (value === null || value === undefined || value === '') return <span className="text-content-tertiary">-</span>;
  return <span className="tabular-nums">{formatCurrency(value, currency)}</span>;
}

/** Rule findings as a list: what blocks approval first and in red, warnings after. */
export function FindingList({
  findings,
  refLabel,
  testId = 'finding-list',
}: {
  findings: Finding[];
  /** Turns a finding's `ref` (a package code, a candidate id) into words. */
  refLabel?: (ref: string) => string;
  testId?: string;
}) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  const ordered = [...findings].sort((a, b) => Number(b.blocks_approval) - Number(a.blocks_approval));
  return (
    <ul className="space-y-1" data-testid={testId}>
      {ordered.map((f, i) => (
        <li
          key={`${f.code}-${f.ref}-${i}`}
          data-finding={f.code}
          data-blocking={f.blocks_approval ? 'yes' : 'no'}
          className="flex items-start gap-2 text-sm"
        >
          {f.blocks_approval ? (
            <XCircle size={14} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
          ) : (
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          )}
          <span className="text-content-primary">
            {findingText(t as TFn, f)}
            {f.ref && f.ref !== 'profile' && (
              <span className="ml-1.5 text-xs text-content-tertiary">{refLabel ? refLabel(f.ref) : f.ref}</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** A refused request shown in place: the server's sentence and every finding it listed. */
export function RefusalBox({ error, refLabel }: { error: unknown; refLabel?: (ref: string) => string }) {
  const { t } = useTranslation();
  if (!error) return null;
  const code = procurementErrorCode(error);
  const text = code ? errorText(t as TFn, code, procurementErrorMessage(error)) : getErrorMessage(error);
  const violations = procurementViolations(error);
  return (
    <div
      role="alert"
      data-testid="refusal-box"
      data-code={code ?? undefined}
      className="rounded-md border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm"
    >
      <p className="font-medium text-content-primary">{text}</p>
      {violations.length > 0 && (
        <div className="mt-2">
          <FindingList findings={violations} refLabel={refLabel} testId="refusal-violations" />
        </div>
      )}
    </div>
  );
}

/** A labelled form control. The label is a real <label>, so a click and a screen reader both find the field. */
export function Field({
  label,
  htmlFor,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-content-secondary">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-2xs text-content-tertiary">{hint}</p>}
    </div>
  );
}

/** What a form still misses, listed beside the save button. */
export function ProblemList({ problems }: { problems: Array<readonly [string, string]> }) {
  const { t } = useTranslation();
  if (problems.length === 0) return null;
  return (
    <ul className="mr-auto space-y-0.5 text-xs text-semantic-error" data-testid="form-problems">
      {problems.map(([key, english]) => (
        <li key={key} data-problem={key}>
          {t(key, { defaultValue: english })}
        </li>
      ))}
    </ul>
  );
}
