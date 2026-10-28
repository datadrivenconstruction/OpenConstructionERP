// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the delivery model screens share: a button that says why it is
// disabled, the colour of each state, the "not verified" mark a catalogue
// fact carries, a list of findings and the field wrapper of the dialogs.

import { useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info, XCircle } from 'lucide-react';
import clsx from 'clsx';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button, type ButtonProps } from '@/shared/ui/Button';

import { DISABLED_REASON, type Verdict } from './access';
import type {
  AllocationStatus,
  DecisionStatus,
  Finding,
  ModelStatus,
  OfiStatus,
  PackageEffectiveStatus,
  ReviewStatus,
} from './api';
import { errorText, findingText, type TFn } from './labels';
import { PROBLEM, type CellState } from './rules';

export const INPUT_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary disabled:opacity-60';

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
  // A reason this screen words itself, else the server's own refusal code.
  const own = verdict ? DISABLED_REASON[verdict] : undefined;
  const reason = !verdict ? null : own ? t(own[0], { defaultValue: own[1] }) : errorText(t as TFn, verdict);
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

export const MODEL_TONE: Record<ModelStatus, BadgeVariant> = {
  draft: 'neutral',
  under_evaluation: 'blue',
  proposed: 'purple',
  approved: 'success',
  binding: 'success',
  reopened: 'warning',
};

export const DECISION_TONE: Record<DecisionStatus, BadgeVariant> = {
  proposed: 'purple',
  approved: 'success',
  superseded: 'neutral',
  withdrawn: 'neutral',
  rejected: 'error',
};

export const ALLOCATION_TONE: Record<AllocationStatus, BadgeVariant> = {
  unconfirmed: 'warning',
  confirmed: 'success',
  link_missing: 'error',
};

export const CELL_TONE: Record<CellState, BadgeVariant> = {
  empty: 'error',
  default: 'neutral',
  unconfirmed: 'warning',
  confirmed: 'success',
  link_missing: 'error',
  not_applicable: 'neutral',
};

export const PACKAGE_TONE: Record<PackageEffectiveStatus, BadgeVariant> = {
  planned: 'neutral',
  in_procurement: 'blue',
  awarded: 'success',
  closed: 'neutral',
  cancelled: 'error',
};

export const OFI_TONE: Record<OfiStatus, BadgeVariant> = {
  identified: 'warning',
  route_set: 'blue',
  ordered: 'purple',
  delivered: 'success',
  handed_to_installer: 'success',
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
 * The mark a catalogue fact carries while nobody has checked it against its
 * source. It sits next to the fact itself, with the source one click away.
 */
export function ReviewMark({ status, sourceUrl }: { status: ReviewStatus | null | undefined; sourceUrl?: string | null }) {
  const { t } = useTranslation();
  if (status !== 'unconfirmed') return null;
  return (
    <span
      className="inline-flex items-center gap-1"
      data-testid="review-unconfirmed"
      title={t('delivery_model.ui.review.unconfirmed_hint', {
        defaultValue: 'Taken from a public source and not yet checked by a specialist. Check it before you rely on it.',
      })}
    >
      <Badge variant="warning" size="sm">
        {t('delivery_model.ui.review.unconfirmed', { defaultValue: 'Not verified' })}
      </Badge>
      {sourceUrl && (
        <a href={sourceUrl} target="_blank" rel="noreferrer noopener" className="text-2xs text-oe-blue-text underline">
          {t('delivery_model.ui.review.source', { defaultValue: 'Source' })}
        </a>
      )}
    </span>
  );
}

/** Findings as sentences, errors first, each with the form rule behind it when it names one. */
export function FindingList({
  findings,
  refName,
  testId = 'finding-list',
}: {
  findings: ReadonlyArray<Finding>;
  /** How to write the thing a finding points at; omitted inside a row that already names it. */
  refName?: (ref: string) => string;
  testId?: string;
}) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  const ordered = [...findings].sort((a, b) => Number(b.severity === 'error') - Number(a.severity === 'error'));
  return (
    <ul className="space-y-1" data-testid={testId}>
      {ordered.map((f, i) => {
        const { text, reason } = findingText(t as TFn, f);
        const isError = f.severity === 'error';
        return (
          <li
            key={`${f.code}-${f.ref}-${i}`}
            data-severity={f.severity}
            className={clsx('flex items-start gap-1.5 text-xs', isError ? 'text-semantic-error' : 'text-[#b45309]')}
          >
            {isError ? <XCircle size={13} className="mt-px shrink-0" aria-hidden /> : <AlertTriangle size={13} className="mt-px shrink-0" aria-hidden />}
            <span>
              {refName && f.ref && <span className="block font-medium text-content-primary">{refName(f.ref)}</span>}
              {text}
              {reason && <span className="block text-content-secondary">{reason}</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** What a draft still misses, listed under the form so the reader fixes it before sending. */
export function ProblemList({ problems, testId = 'draft-problems' }: { problems: ReadonlyArray<string>; testId?: string }) {
  const { t } = useTranslation();
  if (problems.length === 0) return null;
  return (
    <ul className="space-y-1 text-xs text-semantic-error" role="alert" data-testid={testId}>
      {problems.map((code) => {
        const own = PROBLEM[code];
        return <li key={code}>{own ? t(own[0], { defaultValue: own[1] }) : errorText(t as TFn, code)}</li>;
      })}
    </ul>
  );
}

/** The refusal the server answered with on the last attempt, shown at the top of a dialog. */
export function ServerRefusal({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      data-testid="server-refusal"
      className="rounded-md border border-semantic-error/30 bg-semantic-error-bg px-3 py-2 text-sm text-content-primary"
    >
      {message}
    </p>
  );
}

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={clsx('flex flex-col gap-1 text-sm', className)}>
      <span className="font-medium text-content-primary">{label}</span>
      {children}
      {hint && <span className="text-2xs text-content-tertiary">{hint}</span>}
    </label>
  );
}
