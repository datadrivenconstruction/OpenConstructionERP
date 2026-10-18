// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cost line a row is costed on, where that came from, and a way to change
// it in place. Rows take their cost line from what they are made from (the
// bill position, the scope line, the contract line); choosing another one is
// an override and asks for a reason, which the server keeps on the row.
// Choosing "take it from the bill" puts the row back on what it inherits.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { PenLine } from 'lucide-react';

import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { costControlApi, type AssignKind, type SetVectorBody } from '@/features/cost-control/api';
import { CostLinePicker, useCostLineLabel } from './CostLinePicker';
import { OverrideReasonDialog } from './OverrideReasonDialog';
import { problemMessage } from './problemMessages';
import { problemOf } from './structureApi';

/** Where a row's cost line came from, as the server records it. */
export function costLineSourceLabel(t: TFunction, source: string | null | undefined): string {
  switch (source) {
    case 'bid_line':
      return t('costmodel.account.from_bid_line', { defaultValue: 'from the tender scope line' });
    case 'position':
      return t('costmodel.account.from_position', { defaultValue: 'from the bill position' });
    case 'contract_line':
      return t('costmodel.account.from_contract_line', { defaultValue: 'from the contract line' });
    case 'contract':
      return t('costmodel.account.from_contract', { defaultValue: 'from the contract' });
    case 'manual':
      return t('costmodel.account.from_manual', { defaultValue: 'set by hand' });
    default:
      return '';
  }
}

/** The reason kept with an override, when the row carries one. */
export function overrideReason(metadata: Record<string, unknown> | null | undefined): string {
  const raw = metadata?.cost_line_override;
  if (raw && typeof raw === 'object' && 'reason' in raw) {
    const reason = (raw as { reason?: unknown }).reason;
    return typeof reason === 'string' ? reason : '';
  }
  return '';
}

export interface AccountChooserProps {
  projectId: string;
  kind: AssignKind;
  targetId: string;
  costLineId: string | null | undefined;
  source?: string | null;
  /** The reason of a standing override, shown beside the label. */
  reason?: string;
  canEdit: boolean;
  /** False for a row with nothing to inherit: the empty choice then clears it. */
  canInherit?: boolean;
  onSaved?: () => void;
  compact?: boolean;
}

export function AccountChooser({
  projectId,
  kind,
  targetId,
  costLineId,
  source,
  reason,
  canEdit,
  canInherit = true,
  onSaved,
  compact = false,
}: AccountChooserProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const labelOf = useCostLineLabel(projectId);
  const [editing, setEditing] = useState(false);
  const [askReason, setAskReason] = useState<SetVectorBody | null>(null);

  const save = useMutation({
    mutationFn: (body: SetVectorBody) => costControlApi.setVector(projectId, body),
    onSuccess: () => {
      setAskReason(null);
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ['cost-control'] });
      onSaved?.();
    },
    onError: (err, body) => {
      const problem = problemOf(err);
      if (problem?.problem === 'override_reason_required' && !body.reason) {
        setAskReason(body);
        return;
      }
      addToast({
        type: 'error',
        title: t('costmodel.account.save_failed', { defaultValue: 'Could not change the cost line' }),
        message: problem ? problemMessage(t, problem.problem, problem.params) : getErrorMessage(err),
      });
    },
  });

  const choose = (next: string) => {
    if (next) {
      save.mutate({ kind, id: targetId, mode: 'set', cost_line_id: next });
    } else {
      save.mutate({ kind, id: targetId, mode: canInherit ? 'inherit' : 'clear' });
    }
  };

  const label = costLineId
    ? labelOf(costLineId) || t('costmodel.picker.unknown_line', { defaultValue: 'A cost line of this project' })
    : t('costmodel.account.none', { defaultValue: 'No cost line' });
  const from = costLineId ? costLineSourceLabel(t, source) : '';

  return (
    <div className={compact ? 'text-xs' : 'text-sm'} data-testid={`account-${kind}-${targetId}`}>
      {editing && canEdit ? (
        <div className="flex items-center gap-2">
          <div className="w-64 max-w-full">
            <CostLinePicker
              projectId={projectId}
              value={costLineId ?? ''}
              onChange={choose}
              allowEmpty
              emptyLabel={
                canInherit
                  ? t('costmodel.account.take_inherited', { defaultValue: 'Take it from the bill' })
                  : t('costmodel.account.clear', { defaultValue: 'No cost line' })
              }
              disabled={save.isPending}
              data-testid={`account-picker-${targetId}`}
            />
          </div>
          <button
            type="button"
            className="text-xs text-content-tertiary hover:underline"
            onClick={() => setEditing(false)}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
        </div>
      ) : (
        <span className="inline-flex flex-wrap items-center gap-1.5 text-content-tertiary">
          <span className={costLineId ? 'text-content-secondary' : 'text-amber-600'}>{label}</span>
          {from && <span>({from})</span>}
          {reason && <span className="italic" title={reason}>“{reason}”</span>}
          {canEdit && (
            <button
              type="button"
              className="inline-flex items-center gap-0.5 text-oe-blue hover:underline"
              onClick={() => setEditing(true)}
              data-testid={`account-change-${targetId}`}
            >
              <PenLine size={11} />
              {t('costmodel.account.change', { defaultValue: 'Change' })}
            </button>
          )}
        </span>
      )}
      <OverrideReasonDialog
        open={askReason !== null}
        busy={save.isPending}
        onCancel={() => setAskReason(null)}
        onConfirm={(r) => askReason && save.mutate({ ...askReason, reason: r })}
      />
    </div>
  );
}
