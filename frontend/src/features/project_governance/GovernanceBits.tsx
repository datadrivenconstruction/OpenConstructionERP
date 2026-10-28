// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the governance screens share: a button that says why it is
// disabled, a person chip with initials, and the colour of each state.

import { useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button, type ButtonProps } from '@/shared/ui/Button';

import { DISABLED_REASON, type Verdict } from './access';
import { ERROR_TEXT } from './labels';
import type { CheckStatus, ConditionStatus, DocumentStatus, GateStatus, Outcome } from './api';

/** The sentence for a verdict, and the server code when nobody translated it. */
function useVerdictReason(verdict: Verdict): {
  reason: readonly [string, string] | null;
  server: string | null;
  serverKnown: boolean;
} {
  const { i18n } = useTranslation();
  const server = verdict && typeof verdict === 'object' ? verdict.server : null;
  // A server code resolves through governance.errors.<code>; a code nobody
  // translated reads as neutral, with the code beside it for support.
  const serverKey = server ? ['governance', 'errors', server].join('.') : null;
  const serverKnown =
    !!server && (server in ERROR_TEXT || (typeof i18n?.exists === 'function' && !!serverKey && i18n.exists(serverKey)));
  const reason: readonly [string, string] | null =
    verdict === null
      ? null
      : typeof verdict === 'string'
        ? DISABLED_REASON[verdict]
        : serverKnown && serverKey
          ? [serverKey, ERROR_TEXT[server as string] ?? '']
          : ['governance.project.disabled.unavailable', 'This decision is not available right now.'];
  return { reason, server, serverKnown };
}

/** Why a control is refused, as the line under it. Renders nothing for an allowed verdict. */
export function VerdictReason({ verdict, id }: { verdict: Verdict; id?: string }) {
  const { t } = useTranslation();
  const { reason, server, serverKnown } = useVerdictReason(verdict);
  if (!reason) return null;
  return (
    <span
      id={id}
      data-testid="disabled-reason"
      data-reason={typeof verdict === 'string' ? verdict : server ? `server:${server}` : undefined}
      className="inline-flex max-w-xs items-start gap-1 text-2xs text-content-tertiary"
    >
      <Info size={11} className="mt-px shrink-0" aria-hidden />
      {t(reason[0], { defaultValue: reason[1] })}
      {server && !serverKnown && (
        <span className="ml-1 font-mono text-content-quaternary" data-testid="disabled-reason-code">
          ({server})
        </span>
      )}
    </span>
  );
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
  const { reason } = useVerdictReason(verdict);
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        {...rest}
        disabled={disabled || !!verdict}
        aria-describedby={reason ? reasonId : undefined}
        title={reason ? t(reason[0], { defaultValue: reason[1] }) : rest.title}
      >
        {children}
      </Button>
      <VerdictReason verdict={verdict} id={reasonId} />
    </span>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0]!.charAt(0) + parts[parts.length - 1]!.charAt(0) : name.slice(0, 2);
  return letters.toUpperCase();
}

/** An owner shown as initials and name, or a clear "no owner" when the slot is empty. */
export function PersonChip({ name, compact = false }: { name: string | null; compact?: boolean }) {
  const { t } = useTranslation();
  if (!name) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-semantic-error" data-testid="owner-missing">
        <span className="flex h-5 w-5 items-center justify-center rounded-full border border-dashed border-semantic-error/60 text-2xs">
          ?
        </span>
        {!compact && t('governance.project.owner_missing', { defaultValue: 'No owner' })}
      </span>
    );
  }
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-content-secondary" title={name}>
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-semibold text-oe-blue-text">
        {initials(name)}
      </span>
      {!compact && <span className="truncate">{name}</span>}
    </span>
  );
}

export const GATE_STATUS_TONE: Record<GateStatus, BadgeVariant> = {
  not_started: 'neutral',
  in_preparation: 'blue',
  in_review: 'purple',
  on_hold: 'warning',
  decided: 'success',
};

export const OUTCOME_TONE: Record<Outcome, BadgeVariant> = {
  go: 'success',
  go_with_conditions: 'warning',
  hold: 'warning',
  recycle: 'purple',
  stop: 'error',
};

export const CHECK_TONE: Record<CheckStatus, BadgeVariant> = {
  not_assessed: 'neutral',
  ready: 'success',
  ready_with_risks: 'warning',
  not_ready: 'error',
  not_applicable: 'neutral',
};

export const DOCUMENT_TONE: Record<DocumentStatus, BadgeVariant> = {
  draft: 'neutral',
  in_review: 'blue',
  approved_at_gate: 'purple',
  binding: 'success',
  superseded: 'neutral',
};

export const CONDITION_TONE: Record<ConditionStatus, BadgeVariant> = {
  open: 'blue',
  overdue: 'error',
  cleared: 'success',
  waived: 'neutral',
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
