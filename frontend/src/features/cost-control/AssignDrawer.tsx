// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Money that sits on no cost line, line by line, and one way to fix it: pick
// the cost line it belongs to. Lines are grouped by their contract or order,
// and a whole contract can go to one cost line in one step, which is the usual
// case for a trade package. Each choice is saved at once; the report refreshes
// and the line leaves this list.
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2 } from 'lucide-react';

import { Button, Skeleton } from '@/shared/ui';
import { SideDrawer } from '@/shared/ui/SideDrawer';
import { SearchableSelect, type SearchableSelectOption } from '@/shared/ui/SearchableSelect';
import { sumMoneyStrings } from '@/shared/lib/exactDecimal';
import { fmtCurrency } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { OverrideReasonDialog } from '@/features/costmodel/OverrideReasonDialog';
import { problemMessage } from '@/features/costmodel/problemMessages';
import { problemOf } from '@/features/costmodel/structureApi';
import { costControlApi, type AssignBody, type UnassignedItem } from './api';

interface Group {
  id: string;
  label: string;
  items: UnassignedItem[];
}

export interface AssignDrawerProps {
  open: boolean;
  projectId: string;
  currency: string;
  canEdit: boolean;
  onClose: () => void;
  onOpen5d: () => void;
}

export function AssignDrawer({ open, projectId, currency, canEdit, onClose, onOpen5d }: AssignDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const list = useQuery({
    queryKey: ['cost-control', 'unassigned', projectId],
    queryFn: () => costControlApi.unassigned(projectId),
    enabled: open,
  });
  // The choices are the project's cost lines, whichever axis the page shows.
  const byLine = useQuery({
    queryKey: ['cost-control', 'report', projectId, 'cost_line'],
    queryFn: () => costControlApi.report(projectId, 'cost_line'),
    enabled: open,
  });
  const costLines = useMemo(() => (byLine.data?.rows ?? []).filter((r) => r.kind === 'cost_line'), [byLine.data]);

  // A line that inherits another cost line asks why before it moves.
  const [askReason, setAskReason] = useState<AssignBody | null>(null);
  const assign = useMutation({
    mutationFn: (body: AssignBody) => costControlApi.assign(projectId, body),
    onSuccess: () => {
      setAskReason(null);
      queryClient.invalidateQueries({ queryKey: ['cost-control'] });
      addToast({
        type: 'success',
        title: t('cost_control.assign_saved', { defaultValue: 'Put on the cost line' }),
      });
    },
    onError: (e, body) => {
      const problem = problemOf(e);
      if (problem?.problem === 'override_reason_required' && !body.reason) {
        setAskReason(body);
        return;
      }
      addToast({
        type: 'error',
        title: t('cost_control.assign_failed', { defaultValue: 'Could not put it on the cost line' }),
        message: problem ? problemMessage(t, problem.problem, problem.params) : getErrorMessage(e),
      });
    },
  });

  const options = useMemo<SearchableSelectOption[]>(
    () =>
      costLines.map((l) => ({
        value: l.key,
        label: `${l.code} ${l.description}`.trim(),
        keywords: `${l.code} ${l.description}`,
      })),
    [costLines],
  );

  const groups = useMemo<Group[]>(() => {
    const map = new Map<string, Group>();
    for (const item of list.data?.items ?? []) {
      let group = map.get(item.group_id);
      if (!group) {
        const label =
          item.kind === 'po_item'
            ? t('cost_control.assign_group_order', { defaultValue: 'Order {{code}}', code: item.group_code })
            : `${item.group_code} ${item.group_title}`.trim();
        group = { id: item.group_id, label, items: [] };
        map.set(item.group_id, group);
      }
      group.items.push(item);
    }
    return [...map.values()];
  }, [list.data, t]);

  const put = (costLineId: string, items: UnassignedItem[]) => {
    if (!costLineId || items.length === 0) return;
    assign.mutate({ cost_line_id: costLineId, items: items.map((i) => ({ kind: i.kind, id: i.id })) });
  };

  const placeholder = t('cost_control.assign_pick', { defaultValue: 'Choose a cost line' });

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title={t('cost_control.assign_title', { defaultValue: 'Put the money on cost lines' })}
      widthClass="w-full max-w-2xl"
    >
      {/* The explanation is a full sentence; the drawer subtitle is one truncated line. */}
      <p className="mb-4 text-sm text-content-secondary">
        {t('cost_control.assign_subtitle', {
          defaultValue:
            'These contract and order lines are on no cost line yet, so the forecast cannot place them. Choose where each belongs.',
        })}
      </p>
      {list.isLoading || byLine.isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : list.error ? (
        <p className="text-sm text-semantic-error">{getErrorMessage(list.error)}</p>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-10 text-center">
          <CheckCircle2 size={28} className="text-semantic-success" />
          <p className="text-sm text-content-secondary">
            {t('cost_control.assign_done', { defaultValue: 'Every line is on a cost line.' })}
          </p>
        </div>
      ) : costLines.length === 0 ? (
        <div className="space-y-3 rounded-xl border border-border-light p-4">
          <p className="text-sm text-content-secondary">
            {t('cost_control.assign_no_lines', {
              defaultValue:
                'The project has no cost lines to choose from yet. Create them from the bill of quantities on the 5D cost model page.',
            })}
          </p>
          <Button variant="secondary" size="sm" onClick={onOpen5d}>
            {t('cost_control.go_5d', { defaultValue: 'Open the 5D cost model' })}
          </Button>
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map((group) => (
            <section key={group.id} className="rounded-xl border border-border-light">
              <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light bg-surface-secondary/40 px-4 py-2.5">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-content-primary">{group.label}</div>
                  <div className="text-xs text-content-tertiary tabular-nums">
                    {fmtCurrency(
                      sumMoneyStrings(group.items.map((i) => i.amount)),
                      currency,
                    )}
                  </div>
                </div>
                {canEdit && group.items.length > 1 && (
                  <div className="w-64 max-w-full">
                    <SearchableSelect
                      value=""
                      onChange={(v) => put(v, group.items)}
                      options={options}
                      placeholder={t('cost_control.assign_all', { defaultValue: 'All lines to...' })}
                      disabled={assign.isPending}
                      data-testid={`assign-all-${group.id}`}
                    />
                  </div>
                )}
              </header>
              <ul className="divide-y divide-border-light">
                {group.items.map((item) => (
                  <li key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-content-primary">
                        {item.code && <span className="mr-2 font-mono text-xs text-content-tertiary">{item.code}</span>}
                        {item.description || '-'}
                      </div>
                    </div>
                    <span className="shrink-0 text-sm tabular-nums text-content-secondary">
                      {fmtCurrency(item.amount, currency)}
                    </span>
                    {canEdit && (
                      <div className="w-56 max-w-full">
                        <SearchableSelect
                          value=""
                          onChange={(v) => put(v, [item])}
                          options={options}
                          placeholder={placeholder}
                          disabled={assign.isPending}
                          data-testid={`assign-${item.id}`}
                        />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <OverrideReasonDialog
        open={askReason !== null}
        busy={assign.isPending}
        onCancel={() => setAskReason(null)}
        onConfirm={(reason) => askReason && assign.mutate({ ...askReason, reason })}
      />
    </SideDrawer>
  );
}
