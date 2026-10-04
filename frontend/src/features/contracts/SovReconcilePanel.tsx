// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Change orders and variations approved before they reached the schedule of
// values. They moved the contract sum and no line, so the claims had nothing
// to bill the change against. The server lists them with the amount each
// would add; a person ticks the ones to post and confirms, and the apply
// posts that subset or nothing (409 when one of them is no longer on offer).
// A change order whose items name schedule lines moves those lines rather
// than adding one pooled line, so each such change lists where its money
// lands, from the same split the apply posts.
//
// A change someone already put on the schedule by hand would be billed twice
// if the reconcile added another line, so each one can be set aside as
// already on the schedule, with a reason. Set-aside changes are listed below
// the table and can be offered again.
//
// Renders nothing when there is nothing to reconcile and nothing set aside,
// which is every contract whose changes were approved after the poster existed.

import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ListPlus, Undo2 } from 'lucide-react';

import { Button } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { fmtDate } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  applySovReconcile,
  getSovReconcilePreview,
  setSovReconcileExclusion,
  type SovReconcileItem,
} from './api';

/** A change that moves existing lines, rather than adding one pooled line. */
function splitsLines(item: SovReconcileItem): boolean {
  return (item.allocation ?? []).some((row) => row.contract_line_id !== null);
}

// Where a change's money lands, as the server will post it: the lines its
// items name move by their share, the rest goes on the change's own line.
function AllocationList({ item, currency }: { item: SovReconcileItem; currency?: string }) {
  const { t } = useTranslation();
  return (
    <div className="rounded border border-border-light bg-surface-primary px-2 py-1">
      {item.allocation_method === 'pro_rata' && (
        <p className="text-content-tertiary">
          {t('contracts.sov_reconcile_split_pro_rata', {
            defaultValue:
              'Approved at a different amount than its items add up to, so each line takes its share of the approved amount.',
          })}
        </p>
      )}
      {item.allocation_method === 'itemized_with_balance' && (
        <p className="text-content-tertiary">
          {t('contracts.sov_reconcile_split_balance', {
            defaultValue:
              'Its items do not add up to the approved amount; they move their lines as priced and the difference goes on a new line.',
          })}
        </p>
      )}
      <ul className="space-y-0.5">
        {(item.allocation ?? []).map((row, index) => (
          <li
            key={row.contract_line_id ?? `new-${index}`}
            className="flex flex-wrap items-center justify-between gap-2"
          >
            <span className="min-w-0 truncate">
              {row.placement === 'new_line' ? (
                t('contracts.sov_reconcile_share_new_line', { defaultValue: 'New line for this change' })
              ) : row.placement === 'linked_line' ? (
                t('contracts.sov_reconcile_share_beside', {
                  code: row.code,
                  defaultValue: 'New line beside {{code}} (its rate is not restated)',
                })
              ) : (
                <>
                  <span className="font-mono">{row.code}</span> {row.description}
                </>
              )}
            </span>
            <span className="whitespace-nowrap">
              {row.total_before !== null && row.total_after !== null && row.placement !== 'linked_line' && (
                <>
                  <MoneyDisplay amount={row.total_before} currency={currency} /> →{' '}
                  <MoneyDisplay amount={row.total_after} currency={currency} />{' '}
                </>
              )}
              (<MoneyDisplay amount={row.delta} currency={currency} signDisplay="always" />)
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SovReconcilePanel({ contractId }: { contractId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [confirming, setConfirming] = useState(false);
  // Every change starts ticked; this holds the ones the person unticked, so
  // a change that appears on a refreshed preview is offered ticked too.
  const [unticked, setUnticked] = useState<Set<string>>(() => new Set());
  const [asideKey, setAsideKey] = useState<string | null>(null);
  const [asideReason, setAsideReason] = useState('');

  const queryKey = ['contracts', 'sov-reconcile', contractId];
  const previewQ = useQuery({
    queryKey,
    queryFn: () => getSovReconcilePreview(contractId),
  });
  const preview = previewQ.data;
  const items = preview?.items ?? [];
  const excluded = preview?.excluded ?? [];
  const ticked = items.filter((item) => !unticked.has(item.source_key));

  const refresh = () => {
    qc.invalidateQueries({ queryKey });
    qc.invalidateQueries({ queryKey: ['contracts', 'lines', contractId] });
    qc.invalidateQueries({ queryKey: ['contracts', 'sov-status', contractId] });
  };

  const applyMut = useMutation({
    mutationFn: () =>
      applySovReconcile(
        contractId,
        ticked.map((item) => item.source_key),
      ),
    onSuccess: (result) => {
      setConfirming(false);
      addToast({
        type: 'success',
        title: t('contracts.sov_reconcile_done', {
          defaultValue: 'Lines added to the schedule of values: {{lines}}',
          lines: result.posted ?? 0,
        }),
      });
      refresh();
    },
    onError: (err) => {
      setConfirming(false);
      addToast({ type: 'error', title: getErrorMessage(err) });
      // A stale preview is the usual cause: show the list as it is now.
      qc.invalidateQueries({ queryKey });
    },
  });

  const exclusionMut = useMutation({
    mutationFn: (vars: { key: string; excluded: boolean; reason?: string }) =>
      setSovReconcileExclusion(contractId, vars.key, vars.excluded, vars.reason ?? ''),
    onSuccess: (result) => {
      setAsideKey(null);
      setAsideReason('');
      qc.setQueryData(queryKey, result);
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
      qc.invalidateQueries({ queryKey });
    },
  });

  if (!preview || (items.length === 0 && excluded.length === 0)) return null;
  const currency = preview.currency || undefined;
  const adding = ticked.reduce((sum, item) => sum + Number(item.amount || 0), 0);
  const scheduledAfter = Number(preview.scheduled_total || 0) + adding;
  const toggle = (key: string) =>
    setUnticked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="mt-3 rounded-lg border border-border-light bg-semantic-warning-bg p-3 text-sm">
      {items.length > 0 && (
        <>
          <p className="font-medium text-content-primary">
            {t('contracts.sov_reconcile_title', {
              defaultValue: 'Approved changes missing from the schedule of values',
            })}
          </p>
          <p className="mt-1 text-content-secondary">
            {t('contracts.sov_reconcile_hint', {
              defaultValue:
                'These changes moved the contract sum before change orders added lines to the schedule of values, so no claim can bill them yet.',
            })}
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-content-tertiary">
                <tr>
                  {preview.can_apply && <th className="w-6 py-1" />}
                  <th className="py-1 text-start">
                    {t('contracts.code', { defaultValue: 'Code' })}
                  </th>
                  <th className="py-1 text-start">
                    {t('contracts.description', { defaultValue: 'Description' })}
                  </th>
                  <th className="py-1 text-start">
                    {t('contracts.sov_reconcile_approved_on', { defaultValue: 'Approved' })}
                  </th>
                  <th className="py-1 text-end">
                    {t('contracts.total', { defaultValue: 'Total' })}
                  </th>
                  <th className="py-1" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <Fragment key={item.source_key}>
                  <tr className="border-t border-border-light align-top">
                    {preview.can_apply && (
                      <td className="py-1">
                        <input
                          type="checkbox"
                          checked={!unticked.has(item.source_key)}
                          onChange={() => toggle(item.source_key)}
                          disabled={applyMut.isPending}
                          aria-label={t('contracts.sov_reconcile_pick_item', {
                            defaultValue: 'Add {{code}} to the schedule of values',
                            code: item.source_code,
                          })}
                          className="h-4 w-4 rounded border-border accent-oe-blue"
                        />
                      </td>
                    )}
                    <td className="py-1 font-mono">{item.source_code}</td>
                    <td className="py-1">{item.title}</td>
                    <td className="py-1">{item.approved_on ? fmtDate(item.approved_on) : '-'}</td>
                    <td className="py-1 text-end">
                      <MoneyDisplay amount={item.amount} currency={item.currency || currency} />
                    </td>
                    <td className="py-1 ps-2 text-end">
                      {asideKey === item.source_key ? (
                        <div className="flex flex-wrap items-center justify-end gap-1">
                          <input
                            type="text"
                            value={asideReason}
                            maxLength={500}
                            onChange={(e) => setAsideReason(e.target.value)}
                            placeholder={t('contracts.sov_reconcile_reason', {
                              defaultValue: 'Which line covers it (optional)',
                            })}
                            aria-label={t('contracts.sov_reconcile_reason', {
                              defaultValue: 'Which line covers it (optional)',
                            })}
                            className="h-7 min-w-0 rounded border border-border bg-surface-primary px-2 text-xs"
                          />
                          <Button
                            size="sm"
                            onClick={() =>
                              exclusionMut.mutate({
                                key: item.source_key,
                                excluded: true,
                                reason: asideReason,
                              })
                            }
                            loading={exclusionMut.isPending}
                          >
                            {t('contracts.sov_reconcile_set_aside_confirm', {
                              defaultValue: 'Set aside',
                            })}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setAsideKey(null)}
                            disabled={exclusionMut.isPending}
                          >
                            {t('common.cancel', { defaultValue: 'Cancel' })}
                          </Button>
                        </div>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          title={t('contracts.sov_reconcile_set_aside_hint', {
                            defaultValue:
                              'A line added by hand already covers this change. Set it aside so it is not added twice.',
                          })}
                          onClick={() => {
                            setAsideKey(item.source_key);
                            setAsideReason('');
                          }}
                          disabled={applyMut.isPending || exclusionMut.isPending}
                        >
                          {t('contracts.sov_reconcile_set_aside', {
                            defaultValue: 'Already on the schedule',
                          })}
                        </Button>
                      )}
                    </td>
                  </tr>
                  {splitsLines(item) && (
                    <tr data-testid={`sov-reconcile-split-${item.source_key}`}>
                      {preview.can_apply && <td />}
                      <td />
                      <td colSpan={4} className="pb-2">
                        <AllocationList item={item} currency={item.currency || currency} />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-content-secondary">
            {t('contracts.sov', { defaultValue: 'Schedule of Values' })}:{' '}
            <MoneyDisplay amount={preview.scheduled_total} currency={currency} /> →{' '}
            <MoneyDisplay amount={scheduledAfter} currency={currency} /> ·{' '}
            {t('contracts.sov_reconcile_contract_sum', { defaultValue: 'Contract sum to date' })}:{' '}
            <MoneyDisplay amount={preview.contract_sum} currency={currency} />
          </p>
          {!preview.can_apply ? (
            <p className="mt-2 text-content-tertiary">
              {t('contracts.sov_reconcile_active_only', {
                defaultValue: 'Changes are added to the schedule of values of an active contract only.',
              })}
            </p>
          ) : confirming ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-content-primary">
                {t('contracts.sov_reconcile_confirm_split', {
                  defaultValue:
                    'Post each ticked change to the schedule of values as listed: the lines it names move, the rest goes on a line of its own?',
                })}
              </span>
              <Button
                size="sm"
                onClick={() => applyMut.mutate()}
                loading={applyMut.isPending}
                disabled={ticked.length === 0}
              >
                {t('common.confirm', { defaultValue: 'Confirm' })}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setConfirming(false)}
                disabled={applyMut.isPending}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              className="mt-2"
              onClick={() => setConfirming(true)}
              disabled={ticked.length === 0}
            >
              <ListPlus size={13} className="me-1" aria-hidden />
              {t('contracts.sov_reconcile_action', { defaultValue: 'Reconcile change orders' })}
            </Button>
          )}
        </>
      )}
      {excluded.length > 0 && (
        <div className={items.length > 0 ? 'mt-3 border-t border-border-light pt-2' : ''}>
          <p className="font-medium text-content-primary">
            {t('contracts.sov_reconcile_excluded_title', {
              defaultValue: 'Set aside as already on the schedule of values',
            })}
          </p>
          <ul className="mt-1 space-y-1 text-xs">
            {excluded.map((item) => (
              <li key={item.source_key} className="flex flex-wrap items-center gap-2">
                <span className="font-mono">{item.source_code}</span>
                <span>{item.title}</span>
                <MoneyDisplay amount={item.amount} currency={item.currency || currency} />
                {item.reason && <span className="text-content-tertiary">{item.reason}</span>}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => exclusionMut.mutate({ key: item.source_key, excluded: false })}
                  disabled={exclusionMut.isPending}
                >
                  <Undo2 size={13} className="me-1" aria-hidden />
                  {t('contracts.sov_reconcile_take_back', { defaultValue: 'Offer again' })}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
