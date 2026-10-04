// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ChangeReviewPanel: what changed under the estimate since it was measured.
 *
 * Two tabs:
 *  - Flags: positions measured on a drawing that has a newer revision, or
 *    linked to BIM elements whose model has a newer version. Each flag is a
 *    review item; marking it reviewed changes no figure. Opening the panel
 *    runs a check so the list is current without an extra click.
 *  - Model quantities: positions linked to BIM elements whose quantity moved
 *    with a newer model version, old against new, with an explicit accept per
 *    line. Nothing is written until the estimator accepts.
 *
 * Every string goes through i18n `t()` with an English default; numbers and
 * money go through Intl via the shared formatters.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  Box,
  Check,
  CheckCircle2,
  FileDiff,
  FileText,
  Loader2,
  LocateFixed,
  RefreshCw,
  RotateCcw,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { formatCurrency } from '@/shared/lib/money';
import {
  changeReviewApi,
  changeReviewKeys,
  type BIMQuantityProposal,
  type ChangeFlag,
} from './changeReviewApi';

type Tab = 'flags' | 'quantities';
type FlagFilter = 'open' | 'reviewed';

/* ── Toolbar button with the open-flag badge ─────────────────────────── */

export interface ChangeReviewButtonProps {
  boqId: string;
  onClick: () => void;
}

/** Toolbar entry. Reads only the open count, so it costs one small query. */
export function ChangeReviewButton({ boqId, onClick }: ChangeReviewButtonProps) {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: changeReviewKeys.summary(boqId),
    queryFn: () => changeReviewApi.summary(boqId),
    enabled: !!boqId,
    staleTime: 60_000,
  });
  const open = data?.open_count ?? 0;
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onClick}
      title={t('boq.changes_btn_hint', {
        defaultValue: 'Positions affected by new drawing revisions or BIM model versions',
      })}
      data-testid="boq-changes-btn"
    >
      <FileDiff size={14} className="mr-1" />
      {t('boq.changes_btn', { defaultValue: 'Changes' })}
      {open > 0 && (
        <span
          className="ml-1.5 inline-flex min-w-[18px] items-center justify-center rounded-full bg-amber-500 px-1 text-2xs font-semibold leading-[18px] text-white"
          aria-label={t('boq.changes_open_count', {
            defaultValue: 'Open flags: {{count}}',
            count: open,
          })}
          data-testid="boq-changes-badge"
        >
          {open}
        </span>
      )}
    </Button>
  );
}

/* ── Panel ───────────────────────────────────────────────────────────── */

export interface ChangeReviewPanelProps {
  boqId: string;
  locale: string;
  currencyCode: string;
  isOpen: boolean;
  isLocked: boolean;
  onClose: () => void;
  /** Called after accepted quantities were written so the editor refetches. */
  onApplied: () => void;
  /** Scroll the grid to a position. */
  onJumpToPosition?: (positionId: string) => void;
}

export function ChangeReviewPanel({
  boqId,
  locale,
  currencyCode,
  isOpen,
  isLocked,
  onClose,
  onApplied,
  onJumpToPosition,
}: ChangeReviewPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [tab, setTab] = useState<Tab>('flags');
  const [filter, setFilter] = useState<FlagFilter>('open');

  const qtyFmt = useMemo(
    () =>
      new Intl.NumberFormat(locale || undefined, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 4,
      }),
    [locale],
  );
  const fmtQty = useCallback(
    (v: string | null | undefined) => {
      if (v == null || v === '') return '—';
      const n = Number(v);
      return Number.isFinite(n) ? qtyFmt.format(n) : v;
    },
    [qtyFmt],
  );
  const fmtSignedQty = useCallback(
    (v: string) => {
      const n = Number(v);
      if (!Number.isFinite(n)) return v;
      return `${n > 0 ? '+' : ''}${qtyFmt.format(n)}`;
    },
    [qtyFmt],
  );
  const fmtMoney = useCallback(
    (v: string | number) => formatCurrency(v, currencyCode, locale || undefined),
    [currencyCode, locale],
  );
  const fmtSignedMoney = useCallback(
    (v: string | number) => {
      const n = Number(v);
      if (!Number.isFinite(n) || n === 0) return fmtMoney(0);
      return `${n > 0 ? '+' : ''}${fmtMoney(n)}`;
    },
    [fmtMoney],
  );
  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(locale || undefined, { dateStyle: 'medium' }),
    [locale],
  );

  /* ── Flags ── */

  const flagsQuery = useQuery({
    queryKey: changeReviewKeys.flags(boqId, filter),
    queryFn: () => changeReviewApi.listFlags(boqId, filter),
    enabled: isOpen && !!boqId,
  });

  const invalidateFlags = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: changeReviewKeys.all(boqId) });
  }, [queryClient, boqId]);

  const scanMutation = useMutation({
    mutationFn: () => changeReviewApi.scan(boqId),
    onSuccess: (res) => {
      invalidateFlags();
      if (res.created > 0) {
        addToast({
          type: 'info',
          title: t('boq.changes_scan_found', {
            defaultValue: 'New flags: {{count}}',
            count: res.created,
          }),
        });
      }
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.changes_scan_failed', { defaultValue: 'Could not check for changes' }),
        message: e.message,
      });
    },
  });

  // Check once per opening, so the list reflects revisions uploaded since.
  const scannedForOpen = useRef(false);
  const runScan = scanMutation.mutate;
  useEffect(() => {
    if (!isOpen) {
      scannedForOpen.current = false;
      return;
    }
    if (!scannedForOpen.current && boqId) {
      scannedForOpen.current = true;
      runScan();
    }
  }, [isOpen, boqId, runScan]);

  const reviewMutation = useMutation({
    mutationFn: (body: { flag_ids?: string[]; all_open?: boolean; status?: 'open' | 'reviewed' }) =>
      changeReviewApi.review(boqId, body),
    onSuccess: () => invalidateFlags(),
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.changes_review_failed', { defaultValue: 'Could not update the flag' }),
        message: e.message,
      });
    },
  });

  /* ── Model quantities ── */

  const proposalsQuery = useQuery({
    queryKey: changeReviewKeys.proposals(boqId),
    queryFn: () => changeReviewApi.proposals(boqId),
    enabled: isOpen && tab === 'quantities' && !!boqId,
  });
  const proposals = useMemo(() => proposalsQuery.data?.rows ?? [], [proposalsQuery.data]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => {
    // Pre-tick every line that can be accepted, each time a fresh list lands.
    setSelected(new Set(proposals.filter((r) => r.appliable).map((r) => r.position_id)));
  }, [proposals]);

  const toggle = useCallback((positionId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(positionId)) next.delete(positionId);
      else next.add(positionId);
      return next;
    });
  }, []);

  const selectedTotal = useMemo(
    () =>
      proposals
        .filter((r) => r.appliable && selected.has(r.position_id))
        .reduce((acc, r) => acc + Number(r.total_delta || 0), 0),
    [proposals, selected],
  );

  const applyMutation = useMutation({
    mutationFn: (ids: string[]) => changeReviewApi.applyProposals(boqId, ids),
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      void queryClient.invalidateQueries({ queryKey: changeReviewKeys.proposals(boqId) });
      invalidateFlags();
      onApplied();
      addToast({
        type: 'success',
        title: t('boq.changes_qty_applied', {
          defaultValue: 'Quantities updated: {{count}}',
          count: res.applied,
        }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.changes_qty_apply_failed', {
          defaultValue: 'Could not apply the quantities',
        }),
        message: e.message,
      });
    },
  });

  if (!isOpen) return null;

  const flags = flagsQuery.data?.flags ?? [];
  const openCount = flagsQuery.data?.open_count ?? 0;
  const appliableCount = proposals.filter((r) => r.appliable).length;
  const selectedAppliable = proposals.filter((r) => r.appliable && selected.has(r.position_id));

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex">
      <div className="fixed inset-0 bg-black/20" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('boq.changes_title', { defaultValue: 'What changed since measuring' })}
        className="relative ml-auto flex h-full w-full max-w-[480px] flex-col border-l border-border bg-surface-elevated shadow-2xl animate-slide-in-right"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <FileDiff size={16} className="text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('boq.changes_title', { defaultValue: 'What changed since measuring' })}
            </h3>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border px-2" role="tablist">
          {(
            [
              ['flags', t('boq.changes_tab_flags', { defaultValue: 'Flags' }), openCount],
              ['quantities', t('boq.changes_tab_quantities', { defaultValue: 'Model quantities' }), appliableCount],
            ] as Array<[Tab, string, number]>
          ).map(([key, label, count]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={clsx(
                'flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors',
                tab === key
                  ? 'border-oe-blue text-content-primary'
                  : 'border-transparent text-content-tertiary hover:text-content-secondary',
              )}
            >
              {label}
              {count > 0 && (
                <Badge variant={key === 'flags' ? 'warning' : 'blue'} size="sm">
                  {count}
                </Badge>
              )}
            </button>
          ))}
        </div>

        {tab === 'flags' ? (
          <>
            <div className="space-y-2 border-b border-border p-3">
              <Button
                variant="secondary"
                size="sm"
                className="w-full"
                onClick={() => scanMutation.mutate()}
                disabled={scanMutation.isPending}
              >
                {scanMutation.isPending ? (
                  <Loader2 size={14} className="mr-1 animate-spin" />
                ) : (
                  <RefreshCw size={14} className="mr-1" />
                )}
                {t('boq.changes_scan', { defaultValue: 'Check for changes' })}
              </Button>
              <p className="text-2xs text-content-tertiary">
                {t('boq.changes_scan_hint', {
                  defaultValue:
                    'Looks for drawings with a newer revision and BIM models with a newer version since your positions were measured. Nothing in the estimate changes.',
                })}
              </p>
              <div className="flex gap-1" role="group">
                {(['open', 'reviewed'] as FlagFilter[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    aria-pressed={filter === f}
                    className={clsx(
                      'rounded-md px-2 py-1 text-2xs font-medium transition-colors',
                      filter === f
                        ? 'bg-oe-blue-subtle text-oe-blue'
                        : 'text-content-tertiary hover:bg-surface-secondary',
                    )}
                  >
                    {f === 'open'
                      ? t('boq.changes_filter_open', { defaultValue: 'Open' })
                      : t('boq.changes_filter_reviewed', { defaultValue: 'Reviewed' })}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {flagsQuery.isLoading ? (
                <div className="flex justify-center py-12">
                  <Loader2 size={20} className="animate-spin text-content-tertiary" />
                </div>
              ) : flagsQuery.isError ? (
                <p className="px-4 py-8 text-center text-sm text-semantic-error">
                  {t('boq.changes_load_failed', { defaultValue: 'Could not load change flags' })}
                </p>
              ) : flags.length === 0 ? (
                <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
                  <CheckCircle2 size={32} className="mb-3 text-semantic-success" />
                  <p className="text-sm text-content-secondary">
                    {filter === 'open'
                      ? t('boq.changes_empty_open', {
                          defaultValue: 'No open flags. Positions are in step with their drawings and models.',
                        })
                      : t('boq.changes_empty_reviewed', { defaultValue: 'Nothing reviewed yet.' })}
                  </p>
                </div>
              ) : (
                <ul className="divide-y divide-border-light" data-testid="change-flag-list">
                  {flags.map((flag) => (
                    <FlagRow
                      key={flag.id}
                      flag={flag}
                      dateFmt={dateFmt}
                      busy={reviewMutation.isPending}
                      onReview={(status) => reviewMutation.mutate({ flag_ids: [flag.id], status })}
                      onJump={onJumpToPosition}
                    />
                  ))}
                </ul>
              )}
            </div>

            {filter === 'open' && flags.length > 1 && (
              <div className="border-t border-border p-3">
                <Button
                  variant="primary"
                  size="sm"
                  className="w-full"
                  disabled={reviewMutation.isPending}
                  onClick={() => reviewMutation.mutate({ all_open: true })}
                >
                  <Check size={14} className="mr-1" />
                  {t('boq.changes_mark_all_reviewed', { defaultValue: 'Mark all reviewed' })}
                </Button>
              </div>
            )}
          </>
        ) : (
          <>
            <div className="border-b border-border p-3">
              <p className="text-2xs text-content-tertiary">
                {t('boq.changes_qty_hint', {
                  defaultValue:
                    'Positions linked to BIM elements whose quantity moved with a newer model version. Tick the lines to accept; nothing changes until you do.',
                })}
              </p>
              <p className="mt-1 text-2xs text-content-quaternary">
                {t('boq.changes_qty_sync_note', {
                  defaultValue: 'Positions bound through Model sync are reviewed there.',
                })}
              </p>
            </div>

            <div className="flex-1 overflow-y-auto">
              {proposalsQuery.isLoading ? (
                <div className="flex justify-center py-12">
                  <Loader2 size={20} className="animate-spin text-content-tertiary" />
                </div>
              ) : proposalsQuery.isError ? (
                <p className="px-4 py-8 text-center text-sm text-semantic-error">
                  {t('boq.changes_qty_load_failed', {
                    defaultValue: 'Could not load model quantities',
                  })}
                </p>
              ) : proposals.length === 0 ? (
                <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
                  <CheckCircle2 size={32} className="mb-3 text-semantic-success" />
                  <p className="text-sm text-content-secondary">
                    {t('boq.changes_qty_empty', {
                      defaultValue: 'No linked quantity changed with a newer model version.',
                    })}
                  </p>
                </div>
              ) : (
                <ul className="divide-y divide-border-light" data-testid="bim-proposal-list">
                  {proposals.map((row) => (
                    <ProposalRow
                      key={row.position_id}
                      row={row}
                      checked={selected.has(row.position_id)}
                      onToggle={toggle}
                      fmtQty={fmtQty}
                      fmtSignedQty={fmtSignedQty}
                      fmtSignedMoney={fmtSignedMoney}
                      onJump={onJumpToPosition}
                    />
                  ))}
                </ul>
              )}
            </div>

            {appliableCount > 0 && (
              <div className="space-y-2 border-t border-border p-3">
                <div className="flex items-center justify-between text-xs">
                  <button
                    className="text-oe-blue hover:underline"
                    onClick={() =>
                      setSelected(
                        selected.size === appliableCount
                          ? new Set()
                          : new Set(proposals.filter((r) => r.appliable).map((r) => r.position_id)),
                      )
                    }
                  >
                    {selected.size === appliableCount
                      ? t('boq.changes_qty_select_none', { defaultValue: 'Clear selection' })
                      : t('boq.changes_qty_select_all', { defaultValue: 'Select all' })}
                  </button>
                  <span className="text-content-secondary" data-testid="bim-proposal-total">
                    {t('boq.changes_qty_total', {
                      defaultValue: 'Change to line totals: {{amount}}',
                      amount: fmtSignedMoney(selectedTotal),
                    })}
                  </span>
                </div>
                {isLocked && (
                  <p className="text-2xs text-amber-600 dark:text-amber-400">
                    {t('boq.changes_qty_locked', {
                      defaultValue: 'This estimate is locked. Create a revision to change quantities.',
                    })}
                  </p>
                )}
                <Button
                  variant="primary"
                  size="sm"
                  className="w-full"
                  disabled={isLocked || selectedAppliable.length === 0 || applyMutation.isPending}
                  onClick={() => applyMutation.mutate(selectedAppliable.map((r) => r.position_id))}
                >
                  {applyMutation.isPending ? (
                    <Loader2 size={14} className="mr-1 animate-spin" />
                  ) : (
                    <CheckCircle2 size={14} className="mr-1" />
                  )}
                  {t('boq.changes_qty_accept', {
                    defaultValue: 'Accept selected: {{count}}',
                    count: selectedAppliable.length,
                  })}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ── Rows ────────────────────────────────────────────────────────────── */

function FlagRow({
  flag,
  dateFmt,
  busy,
  onReview,
  onJump,
}: {
  flag: ChangeFlag;
  dateFmt: Intl.DateTimeFormat;
  busy: boolean;
  onReview: (status: 'open' | 'reviewed') => void;
  onJump?: (positionId: string) => void;
}) {
  const { t } = useTranslation();
  const isDoc = flag.source_type === 'document_revision';
  const details = flag.details ?? {};
  const changed = Number(details.modified_count ?? 0);
  const removed = Number(details.deleted_count ?? 0);
  const created = new Date(flag.created_at);
  const reviewedByQuantity = flag.review_note === 'quantity_updated_from_model';

  return (
    <li className="px-4 py-3" data-testid="change-flag-row">
      <div className="flex items-start gap-2">
        {isDoc ? (
          <FileText size={14} className="mt-0.5 shrink-0 text-amber-500" />
        ) : (
          <Box size={14} className="mt-0.5 shrink-0 text-oe-blue" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-xs font-medium text-content-primary">
              {flag.ordinal} — {flag.description}
            </span>
            <Badge variant={isDoc ? 'warning' : 'blue'} size="sm">
              {isDoc
                ? t('boq.changes_source_document', { defaultValue: 'Drawing revised' })
                : t('boq.changes_source_bim', { defaultValue: 'Model version' })}
            </Badge>
          </div>
          <p className="mt-0.5 truncate text-2xs text-content-secondary">
            {isDoc
              ? t('boq.changes_doc_line', {
                  defaultValue: '{{name}}, revision {{version}}',
                  name: flag.source_label || '—',
                  version: flag.source_version || '—',
                })
              : t('boq.changes_bim_line', {
                  defaultValue: '{{name}}, version {{version}}',
                  name: flag.source_label || '—',
                  version: flag.source_version || '—',
                })}
          </p>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {t(`boq.changes_reason_${flag.reason}`, {
              defaultValue: REASON_DEFAULTS[flag.reason] ?? REASON_DEFAULTS.model_changed,
            })}
          </p>
          {(changed > 0 || removed > 0) && (
            <p className="mt-0.5 text-2xs text-content-tertiary">
              {changed > 0 &&
                t('boq.changes_changed_count', { defaultValue: 'Changed: {{count}}', count: changed })}
              {changed > 0 && removed > 0 && ' · '}
              {removed > 0 &&
                t('boq.changes_removed_count', { defaultValue: 'Removed: {{count}}', count: removed })}
            </p>
          )}
          <p className="mt-0.5 text-2xs text-content-quaternary">
            {Number.isNaN(created.getTime())
              ? null
              : t('boq.changes_detected_on', {
                  defaultValue: 'Found {{date}}',
                  date: dateFmt.format(created),
                })}
            {reviewedByQuantity &&
              ` · ${t('boq.changes_reviewed_by_quantity', {
                defaultValue: 'Closed when the new model quantity was accepted',
              })}`}
          </p>
          <div className="mt-1.5 flex items-center gap-3">
            {flag.status === 'open' ? (
              <button
                className="inline-flex items-center gap-1 text-2xs font-medium text-oe-blue hover:underline disabled:opacity-50"
                disabled={busy}
                onClick={() => onReview('reviewed')}
              >
                <Check size={12} />
                {t('boq.changes_mark_reviewed', { defaultValue: 'Mark reviewed' })}
              </button>
            ) : (
              <button
                className="inline-flex items-center gap-1 text-2xs font-medium text-content-secondary hover:underline disabled:opacity-50"
                disabled={busy}
                onClick={() => onReview('open')}
              >
                <RotateCcw size={12} />
                {t('boq.changes_reopen', { defaultValue: 'Reopen' })}
              </button>
            )}
            {onJump && (
              <button
                className="inline-flex items-center gap-1 text-2xs text-content-secondary hover:underline"
                onClick={() => onJump(flag.position_id)}
              >
                <LocateFixed size={12} />
                {t('boq.changes_show_position', { defaultValue: 'Show position' })}
              </button>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

const REASON_DEFAULTS: Record<string, string> = {
  document_revised: 'The drawing was revised after this quantity was measured.',
  elements_modified: 'Linked elements changed in the new model version.',
  elements_deleted: 'Linked elements were removed in the new model version.',
  elements_changed: 'Linked elements changed or were removed in the new model version.',
  model_changed: 'The linked model has a new version with changed elements.',
};

function ProposalRow({
  row,
  checked,
  onToggle,
  fmtQty,
  fmtSignedQty,
  fmtSignedMoney,
  onJump,
}: {
  row: BIMQuantityProposal;
  checked: boolean;
  onToggle: (positionId: string) => void;
  fmtQty: (v: string) => string;
  fmtSignedQty: (v: string) => string;
  fmtSignedMoney: (v: string) => string;
  onJump?: (positionId: string) => void;
}) {
  const { t } = useTranslation();
  const deltaNum = Number(row.delta);
  return (
    <li className="px-4 py-3" data-testid="bim-proposal-row">
      <label className={clsx('flex items-start gap-2', row.appliable ? 'cursor-pointer' : 'cursor-default')}>
        <input
          type="checkbox"
          checked={row.appliable && checked}
          disabled={!row.appliable}
          onChange={() => onToggle(row.position_id)}
          className="mt-0.5 accent-oe-blue"
          aria-label={`${row.ordinal} ${row.description}`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-xs font-medium text-content-primary">
              {row.ordinal} — {row.description}
            </span>
            <Badge variant="neutral" size="sm">
              {row.method === 'rule'
                ? t('boq.changes_qty_method_rule', { defaultValue: 'Quantity rule' })
                : t('boq.changes_qty_method_unit', { defaultValue: 'By unit' })}
            </Badge>
          </div>
          {row.appliable ? (
            <div className="mt-1 flex items-center gap-2 font-mono text-2xs">
              <span className="text-content-tertiary">{fmtQty(row.current_quantity)}</span>
              <ArrowRight size={11} className="text-content-quaternary" />
              <span className="font-semibold text-content-primary">{fmtQty(row.new_model_quantity)}</span>
              <span className="text-content-tertiary">{row.unit}</span>
              {Number.isFinite(deltaNum) && deltaNum !== 0 && (
                <span
                  className={clsx(
                    'ml-1 font-medium',
                    deltaNum > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400',
                  )}
                >
                  {fmtSignedQty(row.delta)}
                </span>
              )}
            </div>
          ) : (
            <p className="mt-1 flex items-start gap-1 text-2xs text-amber-600 dark:text-amber-400">
              <AlertTriangle size={12} className="mt-px shrink-0" />
              {row.status === 'elements_missing'
                ? t('boq.changes_qty_status_elements_missing', {
                    defaultValue:
                      'All linked elements were removed in the new version. Review the position by hand.',
                  })
                : t('boq.changes_qty_status_no_quantity', {
                    defaultValue: 'The new version has no measurable quantity for this unit.',
                  })}
            </p>
          )}
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {t('boq.changes_qty_previous', {
              defaultValue: 'Previous model version measured {{value}} {{unit}}',
              value: fmtQty(row.previous_model_quantity),
              unit: row.unit,
            })}
            {' · '}
            {t('boq.changes_bim_line', {
              defaultValue: '{{name}}, version {{version}}',
              name: row.model_name || '—',
              version: row.model_version || '—',
            })}
          </p>
          {row.appliable && (
            <p className="mt-0.5 text-2xs text-content-secondary">
              {t('boq.changes_qty_amount', {
                defaultValue: 'Line total {{amount}}',
                amount: fmtSignedMoney(row.total_delta),
              })}
            </p>
          )}
          {row.appliable && row.manual_override && (
            <p className="mt-0.5 flex items-start gap-1 text-2xs text-amber-600 dark:text-amber-400">
              <AlertTriangle size={12} className="mt-px shrink-0" />
              {t('boq.changes_qty_manual_override', {
                defaultValue: 'This quantity was edited by hand. Accepting replaces it.',
              })}
            </p>
          )}
          {onJump && (
            <button
              type="button"
              className="mt-1 inline-flex items-center gap-1 text-2xs text-content-secondary hover:underline"
              onClick={(e) => {
                e.preventDefault();
                onJump(row.position_id);
              }}
            >
              <LocateFixed size={12} />
              {t('boq.changes_show_position', { defaultValue: 'Show position' })}
            </button>
          )}
        </div>
      </label>
    </li>
  );
}
