// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the stakeholder screens share: a button that follows a server
// capability flag and says why it is off, the box a refused write is shown
// in, a tick list, and the colour of each state.

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Info } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button, type ButtonProps } from '@/shared/ui/Button';
import { getErrorMessage } from '@/shared/lib/api';

import {
  stakeholderErrorCode,
  stakeholderErrorMessage,
  stakeholderViolations,
  type CommitmentStatus,
  type EventStatus,
  type PlanStatus,
  type StakeholderStatus,
} from './api';
import { errorText, humanizeCode, type KeyText, type TFn } from './labels';

export const FIELD_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

/** Which server flag a button follows, and the sentence shown when the flag is off. */
export type Capability = 'edit' | 'organisation';

export const CAPABILITY_REASON: Record<Capability, KeyText> = {
  edit: [
    'stakeholders.ui.disabled.edit',
    'Your role can view stakeholders but not change them. An editor or manager can.',
  ],
  organisation: [
    'stakeholders.ui.disabled.organisation',
    'Only a project manager can change the organisation and the mandates.',
  ],
};

/**
 * A button that follows a capability flag the server sent. When the flag is
 * off it stays visible and says who can act instead, so the reader does not
 * have to guess whether the feature exists.
 */
export function GatedButton({
  allowed,
  capability,
  children,
  disabled,
  ...rest
}: ButtonProps & { allowed: boolean; capability: Capability; children: ReactNode }) {
  const { t } = useTranslation();
  const reasonId = useId();
  const reason = CAPABILITY_REASON[capability];
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        {...rest}
        disabled={disabled || !allowed}
        aria-describedby={allowed ? undefined : reasonId}
        title={allowed ? rest.title : t(reason[0], { defaultValue: reason[1] })}
      >
        {children}
      </Button>
      {!allowed && (
        <span
          id={reasonId}
          data-testid="disabled-reason"
          data-reason={capability}
          className="inline-flex max-w-xs items-start gap-1 text-2xs text-content-tertiary"
        >
          <Info size={11} className="mt-px shrink-0" aria-hidden />
          {t(reason[0], { defaultValue: reason[1] })}
        </span>
      )}
    </span>
  );
}

/** What a refused write said: the server's sentence and every blocker it listed. */
export interface Refusal {
  code: string | null;
  message: string;
  violations: Array<Record<string, unknown>>;
}

export function refusalOf(err: unknown, t: TFn): Refusal {
  const code = stakeholderErrorCode(err);
  const server = stakeholderErrorMessage(err);
  return {
    code,
    message: code ? errorText(t, code, server) : getErrorMessage(err),
    violations: stakeholderViolations(err),
  };
}

/** One blocker of a refused write, in words: the decision type, dimension or person it names. */
function violationText(v: Record<string, unknown>): string {
  return ['decision_type', 'dimension', 'scope', 'code']
    .map((k) => v[k])
    .filter((x): x is string => typeof x === 'string' && x.length > 0)
    .map(humanizeCode)
    .join(' / ');
}

/** The server's reason for refusing a write, shown where the reader pressed the button. */
export function RefusalBox({ refusal }: { refusal: Refusal | null }) {
  if (!refusal) return null;
  const lines = refusal.violations.map(violationText).filter(Boolean);
  return (
    <div
      role="alert"
      data-testid="refusal"
      data-code={refusal.code ?? undefined}
      className="rounded-md border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm text-content-primary"
    >
      <p>{refusal.message}</p>
      {lines.length > 0 && (
        <ul className="ml-4 mt-1 list-disc text-xs text-content-secondary">
          {lines.map((line, i) => (
            <li key={`${line}-${i}`}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * A write whose refusal is kept for the dialog to show. `run` resolves the
 * mutation; `refusal` is what the server said the last time it refused.
 */
export function useWrite<TInput, TResult>(fn: (input: TInput) => Promise<TResult>, onDone: (result: TResult) => void) {
  const { t } = useTranslation();
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const mutation = useMutation({
    mutationFn: fn,
    onMutate: () => setRefusal(null),
    onSuccess: onDone,
    onError: (err) => setRefusal(refusalOf(err, t as TFn)),
  });
  return { run: mutation.mutate, busy: mutation.isPending, refusal, clear: () => setRefusal(null) };
}

export interface TickOption {
  id: string;
  label: string;
}

/** A list of ticks for choosing several of a short list (audience, attendees). */
export function TickList({
  options,
  value,
  onChange,
  label,
  emptyText,
  testId,
}: {
  options: TickOption[];
  value: string[];
  onChange: (next: string[]) => void;
  label: string;
  emptyText: string;
  testId?: string;
}) {
  if (options.length === 0) return <p className="text-xs text-content-tertiary">{emptyText}</p>;
  return (
    <div
      role="group"
      aria-label={label}
      data-testid={testId}
      className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-border-light bg-surface-elevated p-2"
    >
      {options.map((o) => (
        <label key={o.id} className="flex items-center gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            checked={value.includes(o.id)}
            onChange={() => onChange(value.includes(o.id) ? value.filter((x) => x !== o.id) : [...value, o.id])}
          />
          <span className="truncate">{o.label}</span>
        </label>
      ))}
    </div>
  );
}

/**
 * One record of another register, or none. A link that is stored but no
 * longer offered (the other list is longer than one page, or its module is
 * off) stays selected under a neutral name, so saving never drops it.
 */
export function LinkSelect({
  id,
  value,
  onChange,
  options,
  emptyText,
  disabled = false,
}: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  options: TickOption[];
  /** Said under the field when there is nothing to pick, with the reason. */
  emptyText: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const listed = options.some((o) => o.id === value);
  return (
    <>
      <select id={id} className={FIELD_CLASS} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t('stakeholders.ui.link.none', { defaultValue: 'None' })}</option>
        {value && !listed && (
          <option value={value}>{t('stakeholders.ui.link.kept', { defaultValue: 'Linked record (kept as it is)' })}</option>
        )}
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
      {options.length === 0 && <p className="mt-1 text-xs text-content-tertiary">{emptyText}</p>}
    </>
  );
}

export const STAKEHOLDER_TONE: Record<StakeholderStatus, BadgeVariant> = {
  active: 'success',
  dormant: 'neutral',
  archived: 'neutral',
};

export const COMMITMENT_TONE: Record<CommitmentStatus, BadgeVariant> = {
  proposed: 'neutral',
  agreed: 'blue',
  in_progress: 'purple',
  fulfilled: 'success',
  verified: 'success',
  withdrawn: 'neutral',
  breached: 'error',
};

export const PLAN_TONE: Record<PlanStatus, BadgeVariant> = {
  planned: 'neutral',
  active: 'success',
  paused: 'warning',
  completed: 'blue',
  cancelled: 'neutral',
};

export const EVENT_TONE: Record<EventStatus, BadgeVariant> = {
  planned: 'blue',
  held: 'success',
  cancelled: 'neutral',
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

/** The look of the one row a link pointed at. */
export const FOCUS_CLASS = 'ring-2 ring-oe-blue ring-offset-1';

/**
 * The row a notification linked to: the ref goes on that row, which is
 * scrolled into view once it is on screen.
 */
export function useFocusRow<T extends HTMLElement>(id: string | null | undefined, present: boolean) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const node = ref.current;
    if (id && present && node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [id, present]);
  return ref;
}

/** A section heading with the one action that belongs to it on the right. */
export function SectionHead({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-content-primary">{title}</h2>
        {hint && <p className="text-xs text-content-secondary">{hint}</p>}
      </div>
      {action}
    </div>
  );
}
