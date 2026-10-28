// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ApprovalTargetBadge — compact, row-level approval indicator (feature 06).
//
// Drops into a submittal / RFI list row and surfaces whether a routed
// approval workflow is running (or terminally decided) for that target,
// without the caller having to know anything about the approval engine.
// It renders nothing when no instance exists, so rows without a workflow
// stay clean. The query is keyed per target and shares the same cache as
// ApprovalInstanceCard, so opening a row's detail does not refetch.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Clock } from 'lucide-react';

import { Badge } from '@/shared/ui';
import { approvalRoutesKeys, listInstances } from './api';
import { InstanceStatusBadge } from './ApprovalInstanceCard';

export interface ApprovalTargetBadgeProps {
  /** Target kind discriminator — e.g. "submittal", "rfi". */
  targetKind: string;
  /** UUID of the specific target row. */
  targetId: string;
  /** When true, only render while a workflow is actively pending (the
   *  common list use). When false, also show a terminal (approved /
   *  rejected) badge. Default: true. */
  pendingOnly?: boolean;
  className?: string;
}

export function ApprovalTargetBadge({
  targetKind,
  targetId,
  pendingOnly = true,
  className,
}: ApprovalTargetBadgeProps) {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: approvalRoutesKeys.instances(targetKind, targetId),
    queryFn: () => listInstances({ targetKind, targetId }),
    enabled: Boolean(targetKind && targetId),
    staleTime: 30_000,
  });
  const instances = data ?? [];
  const active = instances.find((i) => i.status === 'pending');

  if (active) {
    return (
      <Badge variant="blue" size="sm" className={className}>
        <Clock size={11} className="mr-1" />
        {t('approvalRoutes.pending_step_n', {
          defaultValue: 'Approval · step {{n}}',
          n: active.current_step_ordinal,
        })}
      </Badge>
    );
  }

  if (pendingOnly || instances.length === 0) return null;

  // Latest terminal instance (the list is newest-first from the engine).
  const latest = instances[0];
  if (!latest) return null;
  return <InstanceStatusBadge status={latest.status} />;
}
