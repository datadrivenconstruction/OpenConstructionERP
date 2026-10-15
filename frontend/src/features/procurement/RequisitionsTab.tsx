// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RequisitionsTab - the project's material requisitions inside Procurement.
//
// A requisition is a request for material, not an order. The list shows each
// one with its status and how much of what was requested has been ordered and
// received. Opening one shows its lines with the BOQ positions they came from;
// a draft can be edited (header, quantities, explicit line merge) and
// submitted, a submitted one withdrawn back to draft, and either cancelled.
// Submitting never approves: with no approval configured it waits in
// "submitted", and the requisition rules run first.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ClipboardList, Loader2, GitMerge, Send, Undo2, Ban, Trash2 } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable, WideModal, type BadgeVariant } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { QuantityDisplay } from '@/shared/ui/QuantityDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  REQUISITION_STATUSES,
  cancelRequisition,
  getRequisition,
  lineToInput,
  listRequisitions,
  mergeRequisitionLines,
  parseRequisitionRuleErrors,
  submitRequisition,
  updateRequisition,
  withdrawRequisition,
  type Requisition,
  type RequisitionLineIn,
  type RequisitionRuleError,
  type RequisitionStatus,
} from './requisitionsApi';

const fieldCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const STATUS_VARIANT: Record<RequisitionStatus, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'warning',
  approved: 'blue',
  ordered: 'purple',
  received: 'success',
  consumed: 'success',
  rejected: 'error',
  cancelled: 'error',
};

const STATUS_DEFAULT: Record<RequisitionStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  approved: 'Approved',
  ordered: 'Ordered',
  received: 'Received',
  consumed: 'Consumed',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
};

/**
 * The one unit every line of a requisition shares, or null when they differ.
 * Header totals are only shown under a shared unit: summing tonnes and cubic
 * metres gives a number that means nothing.
 */
function sharedUnit(req: Requisition): string | null {
  const units = new Set(req.items.map((i) => (i.unit ?? '').trim()));
  if (units.size !== 1) return null;
  return [...units][0] ?? null;
}

function HeaderQuantity({ req, value }: { req: Requisition; value: string | undefined }) {
  const unit = sharedUnit(req);
  if (unit === null) return <>-</>;
  return <QuantityDisplay value={value ?? '0'} unit={unit} precision={2} />;
}

function StatusBadge({ status }: { status: RequisitionStatus }) {
  const { t } = useTranslation();
  return (
    <Badge variant={STATUS_VARIANT[status] ?? 'neutral'} size="sm">
      {t(`procurement.requisitions.status.${status}`, { defaultValue: STATUS_DEFAULT[status] ?? status })}
    </Badge>
  );
}

interface RequisitionsTabProps {
  projectId: string;
  /** `?requisition=<id>` opens that requisition on arrival (the buy-list hand-off). */
  focusRequisitionId?: string | null;
}

export function RequisitionsTab({ projectId, focusRequisitionId }: RequisitionsTabProps) {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<RequisitionStatus | ''>('');
  const [openId, setOpenId] = useState<string | null>(focusRequisitionId ?? null);

  useEffect(() => {
    if (focusRequisitionId) setOpenId(focusRequisitionId);
  }, [focusRequisitionId]);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['procurement-requisitions', projectId, statusFilter],
    queryFn: () => listRequisitions(projectId, statusFilter),
  });

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-content-secondary">
          {t('procurement.requisitions.intro', {
            defaultValue:
              'Requests for material, raised from the buy-list or by hand. A request is not an order: purchasing takes it from here.',
          })}
        </p>
        <label className="flex items-center gap-2 text-xs text-content-secondary">
          {t('procurement.requisitions.filter_status', { defaultValue: 'Status' })}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as RequisitionStatus | '')}
            className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-sm"
          >
            <option value="">{t('procurement.requisitions.filter_all', { defaultValue: 'All' })}</option>
            {REQUISITION_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`procurement.requisitions.status.${s}`, { defaultValue: STATUS_DEFAULT[s] })}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isError ? (
        <Card padding="sm">
          <div className="flex items-center justify-between gap-2 text-sm text-semantic-error">
            {t('procurement.requisitions.load_error', { defaultValue: 'Could not load the requisitions.' })}
            <Button size="sm" variant="secondary" onClick={() => refetch()}>
              {t('common.retry', { defaultValue: 'Retry' })}
            </Button>
          </div>
        </Card>
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="h-6 w-6" />}
          title={t('procurement.requisitions.empty_title', { defaultValue: 'No requisitions yet' })}
          description={t('procurement.requisitions.empty_description', {
            defaultValue: 'Open the material buy-list in Resource Summary, select materials and create a requisition.',
          })}
        />
      ) : (
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_number', { defaultValue: 'Number' })}</th>
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_title', { defaultValue: 'Title' })}</th>
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_status', { defaultValue: 'Status' })}</th>
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_needed_by', { defaultValue: 'Needed by' })}</th>
                  <th className="px-4 py-2 text-right font-medium">{t('procurement.requisitions.col_lines', { defaultValue: 'Lines' })}</th>
                  <th className="px-4 py-2 text-right font-medium">{t('procurement.requisitions.col_requested', { defaultValue: 'Requested' })}</th>
                  <th className="px-4 py-2 text-right font-medium">{t('procurement.requisitions.col_ordered', { defaultValue: 'Ordered' })}</th>
                  <th className="px-4 py-2 text-right font-medium">{t('procurement.requisitions.col_received', { defaultValue: 'Received' })}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr
                    key={r.id}
                    className="cursor-pointer border-b border-border-light/60 last:border-0 hover:bg-surface-secondary"
                    onClick={() => setOpenId(r.id)}
                  >
                    <td className="px-4 py-2 font-mono text-xs text-content-primary">
                      <button type="button" className="text-oe-blue hover:underline" onClick={() => setOpenId(r.id)}>
                        {r.req_number ?? r.id.slice(0, 8)}
                      </button>
                    </td>
                    <td className="px-4 py-2 text-content-primary">{r.title || '-'}</td>
                    <td className="px-4 py-2"><StatusBadge status={r.status} /></td>
                    <td className="px-4 py-2 text-content-secondary">
                      {r.required_date ? <DateDisplay value={r.required_date} /> : '-'}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{r.items.length}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <HeaderQuantity req={r} value={r.reconciliation.requested} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <HeaderQuantity req={r} value={r.reconciliation.ordered} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <HeaderQuantity req={r} value={r.reconciliation.received} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.total > data.items.length && (
            <p className="px-4 py-2 text-xs text-content-tertiary">
              {t('procurement.requisitions.truncated', {
                defaultValue: 'Showing the newest {{shown}} of {{total}} requisitions.',
                shown: data.items.length,
                total: data.total,
              })}
            </p>
          )}
        </Card>
      )}

      <RequisitionDetailModal projectId={projectId} requisitionId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

/* ── Detail / edit ──────────────────────────────────────────────────────── */

interface DetailProps {
  projectId: string;
  requisitionId: string | null;
  onClose: () => void;
}

function RequisitionDetailModal({ projectId, requisitionId, onClose }: DetailProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: req, isLoading } = useQuery({
    queryKey: ['procurement-requisition', requisitionId],
    queryFn: () => getRequisition(requisitionId!),
    enabled: !!requisitionId,
  });

  const [title, setTitle] = useState('');
  const [neededBy, setNeededBy] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<RequisitionLineIn[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [dirty, setDirty] = useState(false);
  const [ruleErrors, setRuleErrors] = useState<RequisitionRuleError[]>([]);

  useEffect(() => {
    if (!req) return;
    setTitle(req.title ?? '');
    setNeededBy(req.required_date ?? '');
    setNotes(req.notes ?? '');
    setLines(req.items.map(lineToInput));
    setSelected([]);
    setDirty(false);
  }, [req]);

  useEffect(() => {
    setRuleErrors([]);
  }, [requisitionId]);

  const isDraft = req?.status === 'draft';

  const onDone = (updated: Requisition) => {
    queryClient.setQueryData(['procurement-requisition', updated.id], updated);
    queryClient.invalidateQueries({ queryKey: ['procurement-requisitions', projectId] });
  };
  const onFail = (e: unknown) => {
    const errors = parseRequisitionRuleErrors(e);
    setRuleErrors(errors);
    if (!errors.length) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    }
  };

  const save = useMutation({
    mutationFn: () =>
      updateRequisition(requisitionId!, {
        title: title.trim() || null,
        required_date: neededBy || null,
        notes: notes.trim() || null,
        items: lines,
      }),
    onSuccess: (updated) => {
      onDone(updated);
      setRuleErrors([]);
      addToast({ type: 'success', title: t('procurement.requisitions.saved', { defaultValue: 'Draft saved' }) });
    },
    onError: onFail,
  });

  const submit = useMutation({
    mutationFn: async () => {
      if (dirty) await save.mutateAsync();
      return submitRequisition(requisitionId!);
    },
    onSuccess: (updated) => {
      onDone(updated);
      setRuleErrors([]);
      addToast({
        type: 'success',
        title: t('procurement.requisitions.submitted_toast', {
          defaultValue: 'Requisition submitted. It now waits for purchasing; it has not been approved.',
        }),
      });
    },
    onError: onFail,
  });

  const withdraw = useMutation({
    mutationFn: () => withdrawRequisition(requisitionId!),
    onSuccess: onDone,
    onError: onFail,
  });

  const cancel = useMutation({
    mutationFn: () => cancelRequisition(requisitionId!),
    onSuccess: onDone,
    onError: onFail,
  });

  const busy = save.isPending || submit.isPending || withdraw.isPending || cancel.isPending;

  const editLine = (index: number, patch: Partial<RequisitionLineIn>) => {
    setLines((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)));
    setDirty(true);
  };
  const removeLine = (index: number) => {
    setLines((prev) => prev.filter((_, i) => i !== index));
    setSelected([]);
    setDirty(true);
  };
  const mergeSelected = () => {
    const merged = mergeRequisitionLines(lines, selected);
    if (merged === null) {
      addToast({
        type: 'error',
        title: t('procurement.requisitions.merge_unit_mismatch', {
          defaultValue: 'Only lines in the same unit can be merged.',
        }),
      });
      return;
    }
    setLines(merged);
    setSelected([]);
    setDirty(true);
  };

  const storedLines = useMemo(() => req?.items ?? [], [req]);

  return (
    <WideModal
      open={requisitionId !== null}
      onClose={onClose}
      busy={busy}
      size="2xl"
      title={
        req
          ? t('procurement.requisitions.detail_title', {
              defaultValue: 'Requisition {{number}}',
              number: req.req_number ?? '',
            })
          : t('procurement.requisitions.loading', { defaultValue: 'Loading requisition' })
      }
      footer={
        req && (
          <>
            {(req.status === 'draft' || req.status === 'submitted' || req.status === 'approved') && (
              <Button variant="danger" icon={<Ban size={14} />} onClick={() => cancel.mutate()} disabled={busy}>
                {t('procurement.requisitions.cancel', { defaultValue: 'Cancel requisition' })}
              </Button>
            )}
            {req.status === 'submitted' && (
              <Button variant="secondary" icon={<Undo2 size={14} />} onClick={() => withdraw.mutate()} disabled={busy}>
                {t('procurement.requisitions.withdraw', { defaultValue: 'Withdraw to draft' })}
              </Button>
            )}
            {isDraft && (
              <>
                <Button variant="secondary" onClick={() => save.mutate()} disabled={busy || !dirty}>
                  {t('procurement.requisitions.save', { defaultValue: 'Save draft' })}
                </Button>
                <Button icon={<Send size={14} />} onClick={() => submit.mutate()} disabled={busy || lines.length === 0}>
                  {submit.isPending && <Loader2 size={14} className="mr-1 animate-spin" />}
                  {t('procurement.requisitions.submit', { defaultValue: 'Submit' })}
                </Button>
              </>
            )}
          </>
        )
      }
    >
      {isLoading || !req ? (
        <Loader2 size={18} className="animate-spin text-content-tertiary" />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <StatusBadge status={req.status} />
            {sharedUnit(req) !== null && (
            <span className="text-content-tertiary">
              {t('procurement.requisitions.progress', {
                defaultValue: 'Requested {{requested}}, ordered {{ordered}}, received {{received}}, outstanding {{outstanding}}',
                requested: req.reconciliation.requested ?? '0',
                ordered: req.reconciliation.ordered ?? '0',
                received: req.reconciliation.received ?? '0',
                outstanding: req.reconciliation.outstanding ?? '0',
              })}{' '}
              {sharedUnit(req)}
            </span>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs font-medium text-content-secondary">
              {t('procurement.requisitions.field_title', { defaultValue: 'Title' })}
              <input
                className={`${fieldCls} mt-1`}
                value={title}
                maxLength={500}
                disabled={!isDraft}
                onChange={(e) => {
                  setTitle(e.target.value);
                  setDirty(true);
                }}
              />
            </label>
            <label className="block text-xs font-medium text-content-secondary">
              {t('procurement.requisitions.field_needed_by', { defaultValue: 'Needed on site by' })}
              <input
                type="date"
                className={`${fieldCls} mt-1`}
                value={neededBy}
                disabled={!isDraft}
                onChange={(e) => {
                  setNeededBy(e.target.value);
                  setDirty(true);
                }}
              />
            </label>
            <label className="block text-xs font-medium text-content-secondary sm:col-span-2">
              {t('procurement.requisitions.field_notes', { defaultValue: 'Notes' })}
              <textarea
                className="mt-1 min-h-[3.5rem] w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm"
                value={notes}
                maxLength={5000}
                disabled={!isDraft}
                onChange={(e) => {
                  setNotes(e.target.value);
                  setDirty(true);
                }}
              />
            </label>
          </div>

          {ruleErrors.length > 0 && (
            <div role="alert" className="rounded-lg border border-semantic-error/40 bg-semantic-error/5 p-3 text-sm">
              <p className="mb-1 font-medium text-semantic-error">
                {t('procurement.requisitions.rules_failed', {
                  defaultValue: 'Fix these before submitting:',
                })}
              </p>
              <ul className="list-disc space-y-1 pl-5 text-content-secondary">
                {ruleErrors.map((e, i) => (
                  <li key={`${e.rule_id}-${i}`}>
                    {e.message}
                    {e.suggestion ? <span className="text-content-tertiary"> - {e.suggestion}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-content-primary">
                {t('procurement.requisitions.lines', { defaultValue: 'Lines' })}
              </h4>
              {isDraft && (
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<GitMerge size={14} />}
                  onClick={mergeSelected}
                  disabled={selected.length < 2}
                  title={t('procurement.requisitions.merge_hint', {
                    defaultValue: 'Combine the selected lines into one. Do this only when they are the same material.',
                  })}
                >
                  {t('procurement.requisitions.merge', { defaultValue: 'Merge selected' })}
                </Button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[40rem] text-sm">
                <thead>
                  <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                    {isDraft && <th className="w-8 py-1.5" />}
                    <th className="py-1.5 pr-3 font-medium">{t('procurement.requisitions.col_material', { defaultValue: 'Material' })}</th>
                    <th className="py-1.5 pr-3 font-medium">{t('procurement.requisitions.col_unit', { defaultValue: 'Unit' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_requested', { defaultValue: 'Requested' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_ordered', { defaultValue: 'Ordered' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_received', { defaultValue: 'Received' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_outstanding', { defaultValue: 'Outstanding' })}</th>
                    <th className="py-1.5 pr-3 font-medium">{t('procurement.requisitions.col_sources', { defaultValue: 'From the BOQ' })}</th>
                    {isDraft && <th className="w-8 py-1.5" />}
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line, index) => {
                    // Progress figures belong to the stored line; an unsaved
                    // edit (merge, removal) has none yet.
                    const stored = !dirty ? storedLines[index] : undefined;
                    return (
                      <tr key={index} className="border-b border-border-light/60 align-top last:border-0">
                        {isDraft && (
                          <td className="py-1.5">
                            <input
                              type="checkbox"
                              aria-label={t('procurement.requisitions.select_line', { defaultValue: 'Select line' })}
                              checked={selected.includes(index)}
                              onChange={(e) =>
                                setSelected((prev) => (e.target.checked ? [...prev, index] : prev.filter((i) => i !== index)))
                              }
                            />
                          </td>
                        )}
                        <td className="py-1.5 pr-3">
                          {isDraft ? (
                            <input
                              className={fieldCls}
                              value={line.description}
                              maxLength={500}
                              onChange={(e) => editLine(index, { description: e.target.value })}
                            />
                          ) : (
                            line.description
                          )}
                        </td>
                        <td className="py-1.5 pr-3 text-content-secondary">{line.unit || '-'}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">
                          {isDraft ? (
                            <input
                              className={`${fieldCls} w-28 text-right`}
                              inputMode="decimal"
                              value={line.quantity_requested}
                              onChange={(e) => editLine(index, { quantity_requested: e.target.value.trim() })}
                            />
                          ) : (
                            <QuantityDisplay value={line.quantity_requested} unit={line.unit ?? ''} precision={2} />
                          )}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                          {stored ? <QuantityDisplay value={stored.quantity_ordered} unit={stored.unit ?? ''} precision={2} /> : '-'}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                          {stored ? <QuantityDisplay value={stored.quantity_received} unit={stored.unit ?? ''} precision={2} /> : '-'}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                          {stored ? <QuantityDisplay value={stored.quantity_outstanding} unit={stored.unit ?? ''} precision={2} /> : '-'}
                        </td>
                        <td className="py-1.5 pr-3 text-xs text-content-tertiary">
                          {line.sources.length === 0
                            ? t('procurement.requisitions.no_sources', { defaultValue: 'Entered by hand' })
                            : t('procurement.requisitions.source_count', {
                                defaultValue: 'BOQ sources: {{n}}',
                                n: line.sources.length,
                              })}
                        </td>
                        {isDraft && (
                          <td className="py-1.5">
                            <button
                              type="button"
                              aria-label={t('procurement.requisitions.remove_line', { defaultValue: 'Remove line' })}
                              className="text-content-tertiary hover:text-semantic-error"
                              onClick={() => removeLine(index)}
                            >
                              <Trash2 size={14} />
                            </button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </WideModal>
  );
}
