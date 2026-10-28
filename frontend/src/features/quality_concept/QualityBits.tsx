// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the quality concept screens share: the colour of each state,
// a titled section, the list of findings, the note that carries a server
// refusal, and the dialog frame every form uses.

import { useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CircleAlert, Info } from 'lucide-react';
import clsx from 'clsx';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { WideModal, type WideModalSize } from '@/shared/ui/WideModal';

import type { Finding } from './api';
import { REVIEW_STATUS, findingText, vocab, type KeyMap, type TFn } from './labels';

export const inputCls =
  'w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary';

export const CONCEPT_TONE: Record<string, BadgeVariant> = {
  draft: 'neutral',
  in_review: 'purple',
  approved: 'success',
  binding: 'success',
  revising: 'warning',
};

export const CERTIFICATION_TONE: Record<string, BadgeVariant> = {
  planned: 'neutral',
  registered: 'blue',
  design_assessed: 'purple',
  post_construction_assessed: 'purple',
  certified: 'success',
  level_missed: 'error',
  abandoned: 'neutral',
};

export const CREDIT_TONE: Record<string, BadgeVariant> = {
  targeted: 'blue',
  evidence_submitted: 'purple',
  achieved: 'success',
  not_achieved: 'error',
  dropped: 'neutral',
};

export const PROOF_TONE: Record<string, BadgeVariant> = {
  open: 'neutral',
  partly_delivered: 'warning',
  delivered: 'blue',
  accepted: 'success',
  waived: 'purple',
};

export const STAGE_TONE: Record<string, BadgeVariant> = {
  blocked: 'neutral',
  ready: 'blue',
  in_test: 'purple',
  failed: 'error',
  passed: 'warning',
  released: 'success',
  stale: 'warning',
  not_applicable: 'neutral',
};

export const ACCEPTANCE_TONE: Record<string, BadgeVariant> = {
  planned: 'neutral',
  requested: 'blue',
  inspection_scheduled: 'purple',
  refused: 'error',
  accepted: 'success',
  accepted_with_reservations: 'warning',
  deemed_accepted: 'success',
};

export const SURVEY_TONE: Record<string, BadgeVariant> = {
  planned: 'neutral',
  invited: 'blue',
  surveyed: 'purple',
  report_issued: 'success',
  closed: 'neutral',
  access_refused: 'error',
};

export const EXPERT_TONE: Record<string, BadgeVariant> = {
  planned: 'neutral',
  commissioned: 'blue',
  reporting: 'purple',
  completed: 'success',
  cancelled: 'neutral',
};

/** A state as a coloured badge, named through its vocabulary. */
export function StateBadge({
  map,
  tones,
  code,
  testId,
}: {
  map: KeyMap;
  tones: Record<string, BadgeVariant>;
  code: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  return (
    <span data-testid={testId} data-state={code}>
      <Badge variant={tones[code] ?? 'neutral'} size="sm">
        {vocab(t as TFn, map, code)}
      </Badge>
    </span>
  );
}

/**
 * Says that a catalogue fact (a legal effect, a test frequency, a deadline)
 * has not been confirmed by a specialist yet. Shown beside the fact, so the
 * reader does not take a default for settled law.
 */
export function ReviewBadge({ status }: { status: string | null | undefined }) {
  const { t } = useTranslation();
  if (status !== 'unconfirmed') return null;
  return (
    <span data-testid="review-unconfirmed">
      <Badge variant="warning" size="sm">
        {vocab(t as TFn, REVIEW_STATUS, 'unconfirmed')}
      </Badge>
    </span>
  );
}

export function Section({
  title,
  description,
  action,
  children,
  testId,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid={testId}>
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-content-primary">{title}</h2>
          {description && <p className="mt-0.5 text-xs text-content-secondary">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A short line shown where a list is empty inside a section that has other content. */
export function Hint({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p className="flex items-start gap-1.5 text-sm text-content-tertiary" data-testid={testId}>
      <Info size={14} className="mt-0.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/** The server's reason for refusing the last action, with every finding it listed. */
export function RefusalNote({
  refusal,
  violations = [],
  refName,
}: {
  refusal: string | null;
  violations?: Finding[];
  refName?: (finding: Finding) => string;
}) {
  if (!refusal) return null;
  return (
    <div
      role="alert"
      data-testid="refusal-note"
      className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-3 py-2 text-sm text-content-primary"
    >
      <p>{refusal}</p>
      {violations.length > 0 && <FindingList findings={violations} refName={refName} className="mt-2" />}
    </div>
  );
}

/** Findings as sentences: an error stops the next step, a warning asks for a look. */
export function FindingList({
  findings,
  refName,
  className,
}: {
  findings: Finding[];
  refName?: (finding: Finding) => string;
  className?: string;
}) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  return (
    <ul className={clsx('space-y-1', className)} data-testid="finding-list">
      {findings.map((f, i) => {
        const blocking = f.severity === 'error';
        const Icon = blocking ? CircleAlert : AlertTriangle;
        return (
          <li
            key={`${f.code}:${f.ref}:${i}`}
            data-testid="finding"
            data-code={f.code}
            className="flex items-start gap-1.5 text-sm text-content-primary"
          >
            <Icon
              size={14}
              aria-hidden
              className={clsx('mt-0.5 shrink-0', blocking ? 'text-semantic-error' : 'text-semantic-warning')}
            />
            <span>{findingText(t as TFn, f.code, f.label || (refName ? refName(f) : f.ref))}</span>
          </li>
        );
      })}
    </ul>
  );
}

export interface FormDialogProps {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  onSubmit: () => void;
  submitLabel: string;
  busy: boolean;
  /** What is still missing from the form, in words. The submit button stays disabled while it is set. */
  problem?: string | null;
  refusal?: string | null;
  violations?: Finding[];
  size?: WideModalSize;
  testId?: string;
  children: ReactNode;
}

/**
 * The frame of every form: fields, the server's refusal when the last attempt
 * was turned down, and one submit button that says what is missing instead of
 * failing on click.
 */
export function FormDialog({
  open,
  title,
  subtitle,
  onClose,
  onSubmit,
  submitLabel,
  busy,
  problem = null,
  refusal = null,
  violations = [],
  size = 'md',
  testId,
  children,
}: FormDialogProps) {
  const { t } = useTranslation();
  const problemId = useId();
  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={subtitle}
      size={size}
      busy={busy}
      testId={testId}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {problem && (
            <span id={problemId} data-testid="form-problem" className="mr-auto text-xs text-content-tertiary">
              {problem}
            </span>
          )}
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('qualityConcept.common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            onClick={onSubmit}
            loading={busy}
            disabled={!!problem}
            aria-describedby={problem ? problemId : undefined}
            data-testid="form-submit"
          >
            {submitLabel}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalNote refusal={refusal} violations={violations} />
        {children}
      </div>
    </WideModal>
  );
}

/** A labelled form field. The label wraps the control, so a click on the words focuses it. */
export function Field({
  label,
  hint,
  required = false,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-content-secondary">
        {label}
        {required && <span aria-hidden> *</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-2xs text-content-tertiary">{hint}</span>}
    </label>
  );
}

/** A closed vocabulary as a select. */
export function VocabSelect({
  map,
  codes,
  value,
  onChange,
  emptyLabel,
  testId,
}: {
  map: KeyMap;
  codes: readonly string[];
  value: string;
  onChange: (code: string) => void;
  /** When given, the select offers an empty first choice with these words. */
  emptyLabel?: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  return (
    <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId}>
      {emptyLabel !== undefined && <option value="">{emptyLabel}</option>}
      {codes.map((c) => (
        <option key={c} value={c}>
          {vocab(t as TFn, map, c)}
        </option>
      ))}
    </select>
  );
}

/** A closed vocabulary where several may apply, as checkboxes. */
export function VocabChecks({
  map,
  codes,
  value,
  onChange,
}: {
  map: KeyMap;
  codes: readonly string[];
  value: string[];
  onChange: (codes: string[]) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
      {codes.map((c) => (
        <label key={c} className="inline-flex items-center gap-1.5 text-sm text-content-primary">
          <input
            type="checkbox"
            checked={value.includes(c)}
            onChange={(e) => onChange(e.target.checked ? [...value, c] : value.filter((v) => v !== c))}
          />
          {vocab(t as TFn, map, c)}
        </label>
      ))}
    </div>
  );
}
