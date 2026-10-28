// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the permit screens share: the colour of each state, a person
// chip, a labelled fact, and the one dialog frame every write goes through.

import { useEffect, useId, useRef, useState, type ComponentProps, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, MoreHorizontal } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtDate } from '@/shared/lib/formatters';

import type { ApplicationState, ConditionState, Outcome, PermitState, ReadinessStatus, RequirementState } from './api';
import { errorText, type TFn } from './labels';
import type { Gate } from './rules';

export const fieldClass =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary';

export const REQUIREMENT_TONE: Record<RequirementState, BadgeVariant> = {
  not_started: 'neutral',
  in_progress: 'blue',
  granted: 'success',
  partially_granted: 'warning',
  refused: 'error',
  blocked: 'warning',
  not_applicable: 'neutral',
  not_in_force: 'error',
};

export const APPLICATION_TONE: Record<ApplicationState, BadgeVariant> = {
  planned: 'neutral',
  preparing: 'blue',
  internal_review: 'purple',
  submitted: 'blue',
  validated: 'blue',
  under_review: 'purple',
  info_requested: 'warning',
  decided: 'success',
  withdrawn: 'neutral',
};

export const PERMIT_TONE: Record<PermitState, BadgeVariant> = {
  in_force: 'success',
  suspended: 'warning',
  lapsed: 'error',
  revoked: 'error',
  superseded: 'neutral',
  expired: 'neutral',
};

export const CONDITION_TONE: Record<ConditionState, BadgeVariant> = {
  open: 'blue',
  evidence_submitted: 'purple',
  discharge_applied: 'purple',
  discharged: 'success',
  in_compliance: 'success',
  breach: 'error',
  not_triggered: 'neutral',
  waived: 'neutral',
  superseded: 'neutral',
};

export const OUTCOME_TONE: Record<Outcome, BadgeVariant> = {
  granted: 'success',
  granted_with_conditions: 'success',
  partially_granted: 'warning',
  refused: 'error',
  deemed_granted: 'success',
  withdrawn: 'neutral',
};

export const READINESS_TONE: Record<ReadinessStatus, BadgeVariant> = {
  ready: 'success',
  at_risk: 'warning',
  not_ready: 'error',
  no_roadmap: 'neutral',
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

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0]!.charAt(0) + parts[parts.length - 1]!.charAt(0) : name.slice(0, 2);
  return letters.toUpperCase();
}

/** An owner shown as initials and name, or a clear "no owner" when the slot is empty. */
export function PersonChip({ name }: { name: string | null }) {
  const { t } = useTranslation();
  if (!name) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-semantic-error" data-testid="owner-missing">
        <span className="flex h-5 w-5 items-center justify-center rounded-full border border-dashed border-semantic-error/60 text-2xs">
          ?
        </span>
        {t('permits.ui.owner_missing', { defaultValue: 'No owner' })}
      </span>
    );
  }
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-content-secondary" title={name}>
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-semibold text-oe-blue-text">
        {initials(name)}
      </span>
      <span className="truncate">{name}</span>
    </span>
  );
}

/** A date for reading, or a dash when there is none. */
export function dateText(value: string | null | undefined): string {
  return value ? fmtDate(value) : '-';
}

/** One labelled value of a record. */
export function Fact({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="min-w-0" data-testid={testId}>
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd className="mt-0.5 text-sm text-content-primary">{children}</dd>
    </div>
  );
}

/** The heading of a record opened in place, with the way back to the list. */
export function PanelHeader({
  title,
  subtitle,
  badge,
  onBack,
  backLabel,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  badge?: ReactNode;
  onBack: () => void;
  backLabel: string;
  actions?: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} />} onClick={onBack} data-testid="panel-back">
        {backLabel}
      </Button>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-content-primary">{title}</h2>
            {badge}
          </div>
          {subtitle && <p className="mt-0.5 text-sm text-content-secondary">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-start gap-2">{actions}</div>}
      </div>
    </div>
  );
}

/** A refusal or a load failure said where the reader is looking. */
/** A button that follows a server flag: left out when the action does not apply, disabled with the reason when refused. */
export function GatedButton({ gate, children, ...rest }: { gate: Gate } & ComponentProps<typeof Button>) {
  const { t } = useTranslation();
  if (!gate.show) return null;
  const why = gate.reason ? errorText(t as TFn, gate.reason, null) : undefined;
  return (
    <Button {...rest} disabled={!gate.enabled || rest.disabled} title={why ?? rest.title}>
      {children}
    </Button>
  );
}

/**
 * The reason of every refused action, written out. The disabled button carries the same
 * sentence as a tooltip, which shows neither on a tablet nor on a recording.
 */
export function RefusedActions({
  items,
  testId = 'refused-actions',
}: {
  items: Array<readonly [action: string, gate: Gate] | false | null>;
  testId?: string;
}) {
  const { t } = useTranslation();
  const refused = items.filter((x): x is readonly [string, Gate] => !!x && x[1].show && !x[1].enabled && !!x[1].reason);
  if (refused.length === 0) return null;
  return (
    <ul className="space-y-0.5 text-xs text-content-secondary" data-testid={testId}>
      {refused.map(([action, g]) => (
        <li key={action}>
          {t('permits.ui.refused_line', {
            defaultValue: '{{action}}: {{reason}}',
            action,
            reason: errorText(t as TFn, g.reason ?? '', null),
          })}
        </li>
      ))}
    </ul>
  );
}

export function Refusal({ children, testId = 'refusal' }: { children: ReactNode; testId?: string }) {
  if (!children) return null;
  return (
    <p
      role="alert"
      data-testid={testId}
      className="rounded-md border border-semantic-error/30 bg-semantic-error-bg px-3 py-2 text-sm text-content-primary"
    >
      {children}
    </p>
  );
}

export function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: (id: string) => ReactNode;
}) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-content-primary">
        {label}
        {required && (
          <span className="ml-1 text-xs font-normal text-semantic-error">
            {t('permits.ui.required', { defaultValue: 'required' })}
          </span>
        )}
      </label>
      {children(id)}
      {hint && <p className="mt-1 text-xs text-content-tertiary">{hint}</p>}
    </div>
  );
}

export interface FormDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: ReactNode;
  submitLabel: string;
  busy: boolean;
  /** The server's refusal of the last attempt, as a sentence. */
  error: string | null;
  /** What the draft still lacks. Shown once the reader has tried to send it. */
  problems?: string[];
  onSubmit: () => void;
  children: ReactNode;
  testId: string;
  size?: 'md' | 'lg' | 'xl';
  danger?: boolean;
  /** Nothing can be sent from here, so only the way out is offered. */
  hideSubmit?: boolean;
}

/**
 * The frame of every write: what is being recorded, the fields, what is still
 * missing, the server's refusal, and one button that sends it.
 */
export function FormDialog({
  open,
  onClose,
  title,
  subtitle,
  submitLabel,
  busy,
  error,
  problems = [],
  onSubmit,
  children,
  testId,
  size = 'md',
  danger = false,
  hideSubmit = false,
}: FormDialogProps) {
  const { t } = useTranslation();
  const [tried, setTried] = useState(false);
  useEffect(() => {
    if (!open) setTried(false);
  }, [open]);
  const send = () => {
    setTried(true);
    if (problems.length === 0) onSubmit();
  };
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
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('permits.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {!hideSubmit && (
            <Button variant={danger ? 'danger' : 'primary'} loading={busy} onClick={send} data-testid={`${testId}-submit`}>
              {submitLabel}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        {error && <Refusal testId={`${testId}-error`}>{error}</Refusal>}
        {tried && problems.length > 0 && (
          <ul
            role="alert"
            data-testid={`${testId}-problems`}
            className="list-disc space-y-0.5 rounded-md border border-semantic-warning/40 bg-semantic-warning-bg py-2 pl-7 pr-3 text-sm text-content-primary"
          >
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        {children}
      </div>
    </WideModal>
  );
}

/* ── More actions ─────────────────────────────────────────────────────── */

export interface MoreAction {
  id: string;
  label: string;
  onClick: () => void;
  testId?: string;
  /** The server refuses the action for now; `reason` says why in a sentence. */
  disabled?: boolean;
  reason?: string;
}

/**
 * Everything a record offers besides its next step, behind one button, so a
 * screen shows a single primary action. Renders nothing without items.
 */
export function MoreActions({ items, testId }: { items: MoreAction[]; testId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  if (items.length === 0) return null;
  return (
    <div ref={box} className="relative">
      <Button
        size="sm"
        variant="secondary"
        icon={<MoreHorizontal size={14} />}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        data-testid={testId}
      >
        {t('permits.ui.more_actions', { defaultValue: 'More actions' })}
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 min-w-[14rem] rounded-md border border-border-light bg-surface-primary py-1 shadow-lg"
        >
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              className="block w-full px-3 py-1.5 text-left text-sm text-content-primary hover:bg-surface-secondary disabled:cursor-not-allowed disabled:text-content-tertiary disabled:hover:bg-transparent"
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
              data-testid={item.testId}
            >
              {item.label}
              {item.disabled && item.reason && <span className="block text-xs">{item.reason}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
