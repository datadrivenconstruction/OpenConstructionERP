import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Wallet,
  Plus,
  Users,
  Coins,
  Loader2,
  ChevronRight,
  CheckCircle2,
  Send,
  BookCheck,
  Scale,
  Download,
  ExternalLink,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  Badge,
  DismissibleInfo,
  IntroRichText,
  EmptyState,
  Breadcrumb,
  ConfirmDialog,
  DateDisplay,
  Skeleton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  fetchPayrollBatches,
  fetchPayrollBatch,
  generatePayrollBatch,
  finalizeBatch,
  submitBatch,
  postBatch,
  reconcileBatch,
  downloadBatchExport,
  fetchLabourCost,
} from './api';
import type { PayrollBatch, Reconciliation } from './api';

/* ── Helpers ───────────────────────────────────────────────────────────── */

function money(value: string | number, currency?: string): string {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  try {
    return new Intl.NumberFormat(undefined, {
      style: currency ? 'currency' : 'decimal',
      currency: currency || undefined,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return n.toFixed(2);
  }
}

function hours(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : value;
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function PayrollPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const projectId = activeProjectId ?? '';

  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [confirmFinalizeOpen, setConfirmFinalizeOpen] = useState(false);
  const [confirmSubmitOpen, setConfirmSubmitOpen] = useState(false);
  const [confirmPostOpen, setConfirmPostOpen] = useState(false);
  const [reconciliation, setReconciliation] = useState<Reconciliation | null>(null);

  const batchesQuery = useQuery({
    queryKey: ['payroll', 'batches', projectId],
    queryFn: () => fetchPayrollBatches(projectId),
    enabled: Boolean(projectId),
  });

  const labourCostQuery = useQuery({
    queryKey: ['payroll', 'labour-cost', projectId],
    queryFn: () => fetchLabourCost(projectId),
    enabled: Boolean(projectId),
  });

  const batchDetailQuery = useQuery({
    queryKey: ['payroll', 'batch', selectedBatchId],
    queryFn: () => fetchPayrollBatch(selectedBatchId as string),
    enabled: Boolean(selectedBatchId),
  });

  const generateMut = useMutation({
    mutationFn: () => generatePayrollBatch(projectId, {}),
    onSuccess: (batch) => {
      addToast({
        type: 'success',
        title: '',
        message: t('payroll.generated', {
          defaultValue: 'Draft payroll batch generated ({{count}} entries).',
          count: batch.entry_count,
        }),
      });
      void queryClient.invalidateQueries({ queryKey: ['payroll', 'batches', projectId] });
      setSelectedBatchId(batch.id);
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(err),
      });
    },
  });

  const finalizeMut = useMutation({
    mutationFn: (batchId: string) => finalizeBatch(batchId),
    onSuccess: (batch) => {
      addToast({
        type: 'success',
        title: '',
        message: t('payroll.finalized', {
          defaultValue: 'Batch approved. Labour cost posted to the budget.',
        }),
      });
      // Refresh the list (status badge) and the open detail (Finalize hidden).
      void queryClient.invalidateQueries({ queryKey: ['payroll', 'batches', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['payroll', 'batch', batch.id] });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(err),
      });
    },
  });

  const invalidateBatch = useCallback(
    (batchId: string) => {
      void queryClient.invalidateQueries({ queryKey: ['payroll', 'batches', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['payroll', 'batch', batchId] });
      void queryClient.invalidateQueries({ queryKey: ['payroll', 'labour-cost', projectId] });
    },
    [queryClient, projectId],
  );

  const submitMut = useMutation({
    mutationFn: (batchId: string) => submitBatch(batchId),
    onSuccess: (batch) => {
      addToast({ type: 'success', title: '', message: t('payroll.submitted', { defaultValue: 'Batch submitted for approval.' }) });
      invalidateBatch(batch.id);
    },
    onError: (err) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(err) }),
  });

  const postMut = useMutation({
    mutationFn: (batchId: string) => postBatch(batchId),
    onSuccess: (batch) => {
      addToast({ type: 'success', title: '', message: t('payroll.posted', { defaultValue: 'Batch posted to the general ledger.' }) });
      invalidateBatch(batch.id);
    },
    onError: (err) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(err) }),
  });

  const reconcileMut = useMutation({
    mutationFn: (batchId: string) => reconcileBatch(batchId),
    onSuccess: (rec) => setReconciliation(rec),
    onError: (err) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(err) }),
  });

  const handleExport = useCallback(
    async (batchId: string, format: 'csv' | 'json') => {
      try {
        await downloadBatchExport(batchId, format);
      } catch (err) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });
      }
    },
    [addToast, t],
  );

  const handleSelect = useCallback((id: string) => {
    setSelectedBatchId((prev) => (prev === id ? null : id));
    setReconciliation(null);
  }, []);

  const selectedBatch = batchDetailQuery.data ?? null;
  const canSubmit = selectedBatch?.status === 'draft';
  const canFinalize = selectedBatch?.status === 'draft' || selectedBatch?.status === 'submitted';
  const canPost = selectedBatch?.status === 'approved';

  const handleConfirmFinalize = useCallback(() => {
    if (!selectedBatchId) return;
    finalizeMut.mutate(selectedBatchId, {
      onSettled: () => setConfirmFinalizeOpen(false),
    });
  }, [finalizeMut, selectedBatchId]);

  const handleConfirmSubmit = useCallback(() => {
    if (!selectedBatchId) return;
    submitMut.mutate(selectedBatchId, { onSettled: () => setConfirmSubmitOpen(false) });
  }, [submitMut, selectedBatchId]);

  const handleConfirmPost = useCallback(() => {
    if (!selectedBatchId) return;
    postMut.mutate(selectedBatchId, { onSettled: () => setConfirmPostOpen(false) });
  }, [postMut, selectedBatchId]);

  const batches = batchesQuery.data ?? [];
  const labourCost = labourCostQuery.data ?? null;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(activeProjectName
            ? [{ label: activeProjectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('nav.payroll', { defaultValue: 'Payroll' }) },
        ]}
      />

      {/* Header */}
      <PageHeader
        srTitle={t('payroll.title', { defaultValue: 'Payroll' })}
        subtitle={t('payroll.subtitle', {
          defaultValue: 'Aggregate field labour into pay batches, finalize and post to the cost model.',
        })}
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => generateMut.mutate()}
            disabled={!projectId || generateMut.isPending}
            aria-label={t('payroll.generate', { defaultValue: 'Generate draft batch' })}
          >
            {generateMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus size={14} />}
            {t('payroll.generate', { defaultValue: 'Generate draft batch' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="payroll"
        title={t('payroll.intro_title', {
          defaultValue: 'Turn hours worked into posted labour cost',
        })}
        more={
          t('payroll.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('payroll.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('payroll.intro_link_field_reports', { defaultValue: 'Field Reports' }),
            onClick: () => navigate('/field-reports'),
          },
          {
            label: t('payroll.intro_link_resources', {
              defaultValue: 'Resources & Crew (pay rates)',
            }),
            onClick: () => navigate('/resources'),
          },
          {
            label: t('payroll.intro_link_5d', { defaultValue: '5D Cost' }),
            onClick: () => navigate('/5d'),
          },
        ]}
      >
        {t('payroll.intro_body', {
          defaultValue:
            'Generate a draft batch to roll the hours logged in field reports into pay entries per worker, then walk the batch through its lifecycle: submit for approval, finalize to post labour cost to the project budget, and post to the general ledger. Reconcile at any point to confirm batch hours still match the underlying field records before money moves.',
        })}
      </DismissibleInfo>

      {/* Project gate: keep the canonical top block above, then show the
          select-a-project empty state as a rhythm child (instead of a
          full-page short-circuit that dropped the breadcrumb / header). */}
      {!projectId ? (
        <Card className="py-12">
          <RequiresProject
            emptyHint={t('payroll.no_project_desc', {
              defaultValue: 'Choose a project from the sidebar to view payroll.',
            })}
          >
            {null}
          </RequiresProject>
        </Card>
      ) : (
        <>

      {/* Labour cost rollup (surfaced beside the cost model) */}
      <Card className="p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
            <Coins size={18} />
          </div>
          <div className="flex-1">
            <p className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('payroll.labour_cost', { defaultValue: 'Labour cost' })}
            </p>
            {labourCostQuery.isLoading ? (
              <Skeleton className="mt-1 h-6 w-32" />
            ) : (
              <p className="text-lg font-semibold text-content-primary">
                {labourCost ? money(labourCost.labour_cost, labourCost.currency || undefined) : '-'}
                {labourCost && (
                  <span className="ml-2 text-sm font-normal text-content-tertiary">
                    {t('payroll.over_hours', {
                      defaultValue: 'over {{hours}} h',
                      hours: hours(labourCost.total_hours),
                    })}
                  </span>
                )}
              </p>
            )}
          </div>
        </div>
      </Card>

      {/* Batch list */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="p-0">
          <div className="border-b border-border-subtle px-4 py-3">
            <h2 className="text-sm font-semibold text-content-primary">
              {t('payroll.batches', { defaultValue: 'Pay batches' })}
            </h2>
          </div>
          {batchesQuery.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : batches.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={<Wallet size={28} />}
                title={t('payroll.empty_title', { defaultValue: 'No payroll batches yet' })}
                description={t('payroll.empty_desc', {
                  defaultValue: 'Generate a draft batch to aggregate field labour into pay entries.',
                })}
              />
            </div>
          ) : (
            <ul className="divide-y divide-border-subtle">
              {batches.map((b: PayrollBatch) => (
                <li key={b.id}>
                  <button
                    type="button"
                    onClick={() => handleSelect(b.id)}
                    className={clsx(
                      'flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-surface-hover',
                      selectedBatchId === b.id && 'bg-surface-hover',
                    )}
                    aria-pressed={selectedBatchId === b.id}
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-content-primary">{b.period_label}</span>
                        <Badge
                          variant={
                            b.status === 'posted'
                              ? 'success'
                              : b.status === 'approved'
                                ? 'success'
                                : b.status === 'submitted'
                                  ? 'blue'
                                  : 'neutral'
                          }
                        >
                          {t(`payroll.status.${b.status}`, { defaultValue: b.status })}
                        </Badge>
                      </div>
                      <p className="text-xs text-content-tertiary">
                        <DateDisplay value={b.created_at} format="date" />
                        {' · '}
                        {t('payroll.entry_count', { defaultValue: '{{count}} entries', count: b.entry_count })}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-semibold text-content-primary">
                        {money(b.total_amount, b.currency || undefined)}
                      </p>
                      <p className="text-xs text-content-tertiary">{hours(b.total_hours)} h</p>
                    </div>
                    <ChevronRight size={16} className="text-content-tertiary" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Entries for the selected batch */}
        <Card className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
              <Users size={16} />
              {t('payroll.entries', { defaultValue: 'Entries' })}
            </h2>
            {selectedBatchId && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => reconcileMut.mutate(selectedBatchId)}
                  disabled={reconcileMut.isPending}
                  aria-label={t('payroll.reconcile', { defaultValue: 'Reconcile' })}
                >
                  {reconcileMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale size={16} />}
                  {t('payroll.reconcile', { defaultValue: 'Reconcile' })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleExport(selectedBatchId, 'csv')}
                  aria-label={t('payroll.export_csv', { defaultValue: 'Export CSV' })}
                >
                  <Download size={16} />
                  {t('payroll.export_csv', { defaultValue: 'Export CSV' })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleExport(selectedBatchId, 'json')}
                  aria-label={t('payroll.export_json', { defaultValue: 'Export JSON' })}
                >
                  <Download size={16} />
                  {t('payroll.export_json', { defaultValue: 'Export JSON' })}
                </Button>
                {canSubmit && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setConfirmSubmitOpen(true)}
                    disabled={submitMut.isPending}
                    aria-label={t('payroll.submit', { defaultValue: 'Submit for approval' })}
                  >
                    {submitMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send size={16} />}
                    {t('payroll.submit', { defaultValue: 'Submit for approval' })}
                  </Button>
                )}
                {canFinalize && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => setConfirmFinalizeOpen(true)}
                    disabled={finalizeMut.isPending}
                    aria-label={t('payroll.finalize', { defaultValue: 'Finalize batch' })}
                  >
                    {finalizeMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 size={16} />}
                    {t('payroll.finalize', { defaultValue: 'Finalize batch' })}
                  </Button>
                )}
                {canPost && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => setConfirmPostOpen(true)}
                    disabled={postMut.isPending}
                    aria-label={t('payroll.post', { defaultValue: 'Post to ledger' })}
                  >
                    {postMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <BookCheck size={16} />}
                    {t('payroll.post', { defaultValue: 'Post to ledger' })}
                  </Button>
                )}
              </div>
            )}
          </div>
          {selectedBatch && (
            <div className="flex items-center gap-3 border-b border-border-subtle px-4 py-2 text-xs text-content-tertiary">
              <Link to="/field-reports" className="inline-flex items-center gap-1 hover:text-content-primary">
                <ExternalLink size={12} />
                {t('payroll.audit_field_reports', { defaultValue: 'View field reports' })}
              </Link>
              {selectedBatch.gl_transaction_ref && (
                <span className="font-mono">{selectedBatch.gl_transaction_ref}</span>
              )}
            </div>
          )}
          {reconciliation && reconciliation.batch_id === selectedBatchId && (
            <div className="border-b border-border-subtle px-4 py-3">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Scale size={14} />
                {t('payroll.reconcile_title', { defaultValue: 'Reconciliation' })}
                <Badge variant={reconciliation.balanced ? 'success' : 'warning'} className="whitespace-normal">
                  {reconciliation.balanced
                    ? t('payroll.reconcile_balanced', { defaultValue: 'Balanced - batch hours match the field records.' })
                    : t('payroll.reconcile_unbalanced', {
                        defaultValue: 'Unbalanced - batch hours differ from the field records by {{delta}} h.',
                        delta: reconciliation.delta_total_hours,
                      })}
                </Badge>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-content-tertiary">
                      <th className="px-2 py-1">{t('payroll.reconcile_col.worker', { defaultValue: 'Worker' })}</th>
                      <th className="px-2 py-1">{t('payroll.reconcile_col.date', { defaultValue: 'Date' })}</th>
                      <th className="px-2 py-1 text-right">{t('payroll.reconcile_col.batch', { defaultValue: 'Batch h' })}</th>
                      <th className="px-2 py-1 text-right">{t('payroll.reconcile_col.source', { defaultValue: 'Field h' })}</th>
                      <th className="px-2 py-1 text-right">{t('payroll.reconcile_col.delta', { defaultValue: 'Delta' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reconciliation.rows.map((r, i) => (
                      <tr key={`${r.worker_key}-${r.work_date}-${i}`} className={r.matched ? '' : 'text-amber-600'}>
                        <td className="px-2 py-1">{r.worker_key}</td>
                        <td className="px-2 py-1">{r.work_date ?? '-'}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r.batch_hours}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r.source_hours}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r.delta_hours}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {!selectedBatchId ? (
            <div className="p-6 text-sm text-content-tertiary">
              {t('payroll.select_batch', { defaultValue: 'Select a batch to view its entries.' })}
            </div>
          ) : batchDetailQuery.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-subtle text-left text-xs uppercase tracking-wide text-content-tertiary">
                    <th className="px-4 py-2">{t('payroll.col.worker', { defaultValue: 'Worker' })}</th>
                    <th className="px-4 py-2">{t('payroll.col.date', { defaultValue: 'Date' })}</th>
                    <th className="px-4 py-2 text-right">{t('payroll.col.hours', { defaultValue: 'Hours' })}</th>
                    <th className="px-4 py-2 text-right">{t('payroll.col.rate', { defaultValue: 'Rate' })}</th>
                    <th className="px-4 py-2 text-right">{t('payroll.col.amount', { defaultValue: 'Amount' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {(batchDetailQuery.data?.entries ?? []).map((e) => (
                    <tr key={e.id} className="border-b border-border-subtle/60">
                      <td className="px-4 py-2 text-content-primary">{e.worker}</td>
                      <td className="px-4 py-2 text-content-secondary">
                        {e.work_date ? <DateDisplay value={e.work_date} format="date" /> : '-'}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">{hours(e.hours)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {money(e.rate, e.currency || undefined)}
                      </td>
                      <td className="px-4 py-2 text-right font-medium tabular-nums">
                        {money(e.amount, e.currency || undefined)}
                      </td>
                    </tr>
                  ))}
                  {(batchDetailQuery.data?.entries ?? []).length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-6 text-center text-content-tertiary">
                        {t('payroll.no_entries', { defaultValue: 'This batch has no entries.' })}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <ConfirmDialog
        open={confirmSubmitOpen}
        variant="warning"
        title={t('payroll.submit_confirm_title', { defaultValue: 'Submit batch?' })}
        message={t('payroll.submit_confirm_message', {
          defaultValue: 'The batch will be sent for approval. No cost is posted yet.',
        })}
        confirmLabel={t('payroll.submit', { defaultValue: 'Submit for approval' })}
        cancelLabel={t('confirm_dialog.cancel', { defaultValue: 'Cancel' })}
        loading={submitMut.isPending}
        onConfirm={handleConfirmSubmit}
        onCancel={() => setConfirmSubmitOpen(false)}
      />

      <ConfirmDialog
        open={confirmFinalizeOpen}
        variant="warning"
        title={t('payroll.finalize_confirm_title', { defaultValue: 'Approve batch?' })}
        message={t('payroll.finalize_confirm_message', {
          defaultValue: 'Labour cost will post to the project budget. This cannot be undone.',
        })}
        confirmLabel={t('payroll.finalize', { defaultValue: 'Finalize batch' })}
        cancelLabel={t('confirm_dialog.cancel', { defaultValue: 'Cancel' })}
        loading={finalizeMut.isPending}
        onConfirm={handleConfirmFinalize}
        onCancel={() => setConfirmFinalizeOpen(false)}
      />

      <ConfirmDialog
        open={confirmPostOpen}
        variant="warning"
        title={t('payroll.post_confirm_title', { defaultValue: 'Post to the ledger?' })}
        message={t('payroll.post_confirm_message', {
          defaultValue: 'A payroll journal will be written to the finance ledger. This is final.',
        })}
        confirmLabel={t('payroll.post', { defaultValue: 'Post to ledger' })}
        cancelLabel={t('confirm_dialog.cancel', { defaultValue: 'Cancel' })}
        loading={postMut.isPending}
        onConfirm={handleConfirmPost}
        onCancel={() => setConfirmPostOpen(false)}
      />
        </>
      )}
    </div>
  );
}
