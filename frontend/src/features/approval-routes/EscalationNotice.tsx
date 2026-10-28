// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// EscalationNotice — live SLA-escalation banner for a running approval (#17).
//
// Reads GET /approval-routes/instances/{id}/escalation and surfaces how the
// current step is tracking against its SLA: nothing while on time or when the
// step carries no SLA clock, a warning chip once the step is overdue inside its
// grace window, and a louder "escalates to the next approver" line once the
// breach has aged past the grace window. The background monitor is what
// actually nudges the next authority; this banner just reflects that standing
// so an approver sees it in the card without waiting for a notification.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ArrowUpCircle } from 'lucide-react';
import clsx from 'clsx';

import { Badge } from '@/shared/ui';
import { approvalRoutesKeys, getInstanceEscalation } from './api';
import type { EscalationSeverity } from './types';

const SEVERITY_VARIANT: Record<EscalationSeverity, 'neutral' | 'warning' | 'error'> = {
  on_time: 'neutral',
  late: 'warning',
  breached: 'warning',
  critical: 'error',
};

const SEVERITY_LABEL: Record<EscalationSeverity, string> = {
  on_time: 'On time',
  late: 'Running late',
  breached: 'SLA breached',
  critical: 'Critically overdue',
};

export interface EscalationNoticeProps {
  instanceId: string;
  className?: string;
}

export function EscalationNotice({ instanceId, className }: EscalationNoticeProps) {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: approvalRoutesKeys.escalation(instanceId),
    queryFn: () => getInstanceEscalation(instanceId),
    enabled: Boolean(instanceId),
    staleTime: 30_000,
    retry: false,
  });

  // Stay invisible until there is a live SLA clock and the step has slipped.
  // No SLA, on time, or a verdict that has not loaded yet -> render nothing.
  if (!data || !data.has_sla || data.severity === 'on_time') return null;

  const variant = SEVERITY_VARIANT[data.severity] ?? 'warning';
  const overdue = Math.max(0, Math.round(data.hours_overdue));
  const critical = data.severity === 'critical';

  let line: string;
  if (data.should_escalate && data.next_target) {
    line = t('approvalRoutes.escalation_due', {
      defaultValue:
        'Past the grace window - escalating to the next approver (level {{level}}).',
      level: data.level,
    });
  } else if (data.reason === 'chain_exhausted') {
    line = t('approvalRoutes.escalation_exhausted', {
      defaultValue: 'Overdue with no further approver to escalate to.',
    });
  } else {
    line = t('approvalRoutes.escalation_within_window', {
      defaultValue: 'Overdue, still inside the escalation grace window.',
    });
  }

  return (
    <div
      data-testid="escalation-notice"
      className={clsx(
        'mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border px-2.5 py-1.5',
        critical
          ? 'border-semantic-error-bg bg-semantic-error-bg'
          : 'border-border-light bg-surface-secondary',
        className,
      )}
    >
      {critical ? (
        <ArrowUpCircle className="h-4 w-4 shrink-0 text-semantic-error" aria-hidden />
      ) : (
        <AlertTriangle className="h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
      )}
      <Badge variant={variant} size="sm">
        {t(`approvalRoutes.severity_${data.severity}`, {
          defaultValue: SEVERITY_LABEL[data.severity],
        })}
      </Badge>
      <span className="text-2xs text-content-secondary">{line}</span>
      {overdue > 0 && (
        <span className="ml-auto text-2xs font-medium tabular-nums text-content-tertiary">
          {t('approvalRoutes.escalation_overdue_short', {
            defaultValue: '{{hours}}h overdue',
            hours: overdue,
          })}
        </span>
      )}
    </div>
  );
}

export default EscalationNotice;
