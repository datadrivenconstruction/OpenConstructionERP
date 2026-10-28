// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the plant register screens share: a state badge, the box that
// shows why the server refused something, the lead time chip, a labelled form
// field and the footer every dialog ends with.

import { createContext, useContext, useId, type ComponentProps, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';

import { plantErrorCode, plantErrorMessage, plantViolations, type Capability, type ItemStatus, type PaperStatus, type PlantCatalogue, type PlantItem, type PlantSettings, type SlotStatus, type SpareStatus, type ItStatus } from './api';
import { errorText, leadSourceName, violationText, type LabelContext, type TFn } from './labels';
import { PROBLEM, type Problem } from './rules';

export const ITEM_STATE_TONE: Record<ItemStatus, BadgeVariant> = {
  identified: 'neutral',
  specified: 'neutral',
  enquired: 'blue',
  route_set: 'blue',
  ordered: 'purple',
  manufactured: 'purple',
  delivered: 'purple',
  installed: 'purple',
  commissioned: 'success',
  handed_over: 'success',
  cancelled: 'neutral',
};

export const SLOT_TONE: Record<SlotStatus, BadgeVariant> = {
  requested: 'blue',
  held: 'success',
  converted_to_order: 'success',
  released: 'neutral',
  expired: 'error',
};

export const PAPER_TONE: Record<PaperStatus, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'blue',
  approved: 'success',
  rejected: 'error',
};

export const SPARE_TONE: Record<SpareStatus, BadgeVariant> = {
  required: 'warning',
  specified: 'blue',
  delivered: 'purple',
  handed_over: 'success',
  waived: 'neutral',
};

export const IT_TONE: Record<ItStatus, BadgeVariant> = {
  planned: 'blue',
  provisioned: 'success',
  retired: 'neutral',
};

export interface PlantCan {
  edit: Capability;
  manage: Capability;
  /** The server has not answered yet: every write waits, switched off. */
  pending?: boolean;
}

const OPEN: Capability = { allowed: true };

/**
 * What the server lets the reader do. While the answer is on its way every
 * write is off. When it cannot be read at all nothing is held back here: the
 * server still refuses the write and its reason is shown.
 */
export function canOf(settings: PlantSettings | null | undefined, loading = false): PlantCan {
  if (loading) return { edit: OPEN, manage: OPEN, pending: true };
  return { edit: settings?.can?.edit ?? OPEN, manage: settings?.can?.manage ?? OPEN };
}

export const PlantCanContext = createContext<PlantCan>({ edit: OPEN, manage: OPEN });

export function usePlantCan(): PlantCan {
  return useContext(PlantCanContext);
}

/** The server's reason for a capability it withholds, or null when it is allowed. */
export function withheldReason(t: TFn, capability: Capability, fallback: string): string | null {
  return capability.allowed ? null : errorText(t, capability.reason ?? fallback);
}

/**
 * A button for a write. It is off while the server's answer is on its way and
 * when the server withholds the capability, with the reason as its tooltip
 * (the page states the same reason in plain sight), and it is not there at
 * all when the server says the action does not apply.
 */
export function WriteButton({
  need = 'edit',
  disabled,
  title,
  ...rest
}: ComponentProps<typeof Button> & { need?: 'edit' | 'manage' }) {
  const { t } = useTranslation();
  const can = usePlantCan();
  if (can[need].applies === false) return null;
  const reason = withheldReason(t, can[need], need === 'edit' ? 'edit_permission_required' : 'manage_required');
  return <Button {...rest} disabled={disabled || can.pending || reason !== null} title={reason ?? title} />;
}

export function ToneBadge({ tone, children, testId }: { tone: BadgeVariant; children: ReactNode; testId?: string }) {
  return (
    <span data-testid={testId}>
      <Badge variant={tone} size="sm">
        {children}
      </Badge>
    </span>
  );
}

/** The sentence for a failed request: the server's coded reason when it named one, its plain message otherwise. */
export function refusalText(t: TFn, err: unknown): string {
  const code = plantErrorCode(err);
  return code ? errorText(t, code, plantErrorMessage(err)) : getErrorMessage(err);
}

/**
 * Why the server refused. One blocker reads as a sentence; several read as
 * the list of rules, each with the server's own detail when it gave one.
 */
export function Refusal({ error, className }: { error: unknown; className?: string }) {
  const { t } = useTranslation();
  if (!error) return null;
  const violations = plantViolations(error);
  return (
    <div
      role="alert"
      data-testid="plant-refusal"
      data-code={plantErrorCode(error) ?? undefined}
      className={clsx('rounded-md border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm', className)}
    >
      <p className="font-medium text-content-primary">{refusalText(t, error)}</p>
      {violations.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-content-secondary">
          {violations.map((v, i) => (
            <li key={`${v.code}-${i}`} data-violation={v.code}>
              {violationText(t, v)}
              {v.reason && <span className="block text-xs text-content-tertiary">{v.reason}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Where an item's lead time comes from, in one chip. A dated quote says who
 * answered and when; a catalogue default says plainly that it is not market
 * evidence; no figure at all says so.
 */
export function LeadChip({
  item,
  catalogue,
  labels,
}: {
  item: PlantItem;
  catalogue: PlantCatalogue | null | undefined;
  labels: LabelContext;
}) {
  const { t } = useTranslation();
  if (item.effective_lead_weeks === null || item.lead_source === 'none') {
    return (
      <span className="text-xs text-content-tertiary" data-testid="lead-chip" data-lead="none">
        {t('plant.catalogue.source.none', { defaultValue: 'No lead time' })}
      </span>
    );
  }
  if (item.lead_source === 'catalogue_default' || !item.basis_enquiry_date) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5 text-xs" data-testid="lead-chip" data-lead="default">
        <span className="font-medium text-content-primary">
          {t('plant.item.weeks', { defaultValue: '{{weeks}} wk', weeks: item.effective_lead_weeks })}
        </span>
        <Badge variant="warning" size="sm">
          {t('plant.catalogue_default_chip', { defaultValue: 'catalogue default, not market evidence' })}
        </Badge>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs" data-testid="lead-chip" data-lead="quote">
      <span className="text-content-primary">
        {t('plant.quote_age_chip', {
          defaultValue: 'quoted {{weeks}} wk on {{date}} by {{source}}',
          weeks: item.effective_lead_weeks,
          date: fmtDate(item.basis_enquiry_date),
          source: leadSourceName(labels, catalogue, item.lead_source),
        })}
      </span>
      {item.quote_stale && (
        <Badge variant="error" size="sm">
          {t('plant.item.quote_stale', {
            defaultValue: 'quote is {{days}} days old, {{max}} allowed',
            days: item.quote_age_days ?? 0,
            max: item.quote_max_age_days,
          })}
        </Badge>
      )}
    </span>
  );
}

export const fieldClass =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

/** A labelled form control. The control is passed as a render function so it receives the label's id. */
export function Field({
  label,
  required,
  hint,
  className,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  className?: string;
  children: (id: string) => ReactNode;
}) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-content-secondary">
        {label}
        {required && (
          <span className="ml-1 font-normal text-semantic-error">
            {t('plant.common.required', { defaultValue: 'required' })}
          </span>
        )}
      </label>
      {children(id)}
      {hint && <p className="mt-1 text-2xs text-content-tertiary">{hint}</p>}
    </div>
  );
}

/**
 * Cancel and save, with what the draft is still missing beside them. The
 * problems appear once the reader has tried to save, so an empty new form
 * does not open covered in errors.
 */
export function DialogFooter({
  problems,
  showProblems,
  busy,
  submitLabel,
  onCancel,
  onSubmit,
  danger,
}: {
  problems: Problem[];
  showProblems: boolean;
  busy: boolean;
  submitLabel: string;
  onCancel: () => void;
  onSubmit: () => void;
  danger?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex w-full flex-wrap items-center justify-end gap-3">
      {showProblems && problems.length > 0 && (
        <ul className="mr-auto space-y-0.5 text-xs text-semantic-error" data-testid="dialog-problems">
          {problems.map((p) => (
            <li key={p} data-problem={p}>
              {t(PROBLEM[p][0], { defaultValue: PROBLEM[p][1] })}
            </li>
          ))}
        </ul>
      )}
      <Button variant="ghost" onClick={onCancel} disabled={busy}>
        {t('plant.common.cancel', { defaultValue: 'Cancel' })}
      </Button>
      <Button variant={danger ? 'danger' : 'primary'} loading={busy} onClick={onSubmit} data-testid="dialog-submit">
        {submitLabel}
      </Button>
    </div>
  );
}

/** A titled block of the item page, with its one action on the right. */
export function Section({
  title,
  hint,
  action,
  testId,
  children,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid={testId}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">{title}</h3>
          {hint && <p className="mt-0.5 text-xs text-content-secondary">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A label and its value, the way the item page lists facts. */
export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd className="mt-0.5 text-sm text-content-primary">{children}</dd>
    </div>
  );
}

/** A quantity as a reader writes it: whole numbers without decimals, the rest with two. */
export function fmtQuantity(value: string | number, unit?: string): string {
  const n = Number(value);
  const text = fmtNumber(value, Number.isInteger(n) ? 0 : 2);
  return unit ? `${text} ${unit}` : text;
}
