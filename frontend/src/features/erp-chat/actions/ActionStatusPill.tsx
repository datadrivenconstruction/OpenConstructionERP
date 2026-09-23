// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The state of a proposal in one word or two. The word carries the meaning;
 * the colour only repeats it, so the pill reads the same without colour.
 */
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Loader2 } from 'lucide-react';
import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import type { ActionOp, ActionStatus } from './types';

export interface ActionStatusPillProps {
  status: ActionStatus;
  /** A request in flight on this action; replaces the status with a busy word. */
  busyOp?: ActionOp | null;
  className?: string;
}

const VARIANT: Record<ActionStatus, BadgeVariant> = {
  proposed: 'blue',
  applied: 'success',
  rejected: 'neutral',
  reverted: 'purple',
  failed: 'error',
};

/** The status word, also used by the Changes filters and screen-reader text. */
export function statusLabel(status: ActionStatus, t: TFunction): string {
  switch (status) {
    case 'proposed':
      return String(t('erp_chat.action.status.proposed', { defaultValue: 'Waiting for review' }));
    case 'applied':
      return String(t('erp_chat.action.status.applied', { defaultValue: 'Applied' }));
    case 'rejected':
      return String(t('erp_chat.action.status.rejected', { defaultValue: 'Rejected' }));
    case 'reverted':
      return String(t('erp_chat.action.status.reverted', { defaultValue: 'Undone' }));
    case 'failed':
      return String(t('erp_chat.action.status.failed', { defaultValue: 'Failed' }));
    default:
      return String(status);
  }
}

/** The busy word for a request in flight. */
export function busyLabel(op: ActionOp, t: TFunction): string {
  switch (op) {
    case 'apply':
      return String(t('erp_chat.action.busy.apply', { defaultValue: 'Applying…' }));
    case 'reject':
      return String(t('erp_chat.action.busy.reject', { defaultValue: 'Rejecting…' }));
    case 'save':
      return String(t('erp_chat.action.busy.save', { defaultValue: 'Saving…' }));
    case 'revert':
      return String(t('erp_chat.action.busy.revert', { defaultValue: 'Undoing…' }));
    default:
      return '';
  }
}

export function ActionStatusPill({ status, busyOp, className }: ActionStatusPillProps) {
  const { t } = useTranslation();
  if (busyOp) {
    return (
      <Badge variant="blue" size="sm" className={className}>
        <span className="inline-flex items-center gap-1" data-testid="action-status-pill" data-status="busy">
          <Loader2 size={11} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {busyLabel(busyOp, t)}
        </span>
      </Badge>
    );
  }
  return (
    <Badge variant={VARIANT[status] ?? 'neutral'} size="sm" dot className={className}>
      <span data-testid="action-status-pill" data-status={status}>
        {statusLabel(status, t)}
      </span>
    </Badge>
  );
}
