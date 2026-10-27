// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sync tab: push approved documents and pull payments (live providers), the
 * pre-flight findings that explain why a document would be refused, a preview of
 * the documents in the period, and the sync log with a retry on every failure
 * that is still open.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { CheckCircle2, Download, RefreshCw, RotateCcw, Upload } from 'lucide-react';
import { Button, Card, EmptyState } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  LIVE_PROVIDERS,
  LOG_PAGE_SIZE,
  canRetry,
  needsAuthorisation,
  pullPayments,
  pushRecords,
  retryLogEntry,
  useDocuments,
  useFindings,
  useSyncLog,
  useSyncMutation,
  type Connection,
  type DateRange,
  type PushResult,
} from './api';
import { actionLabel, recordTypeLabel, ruleLabel, severityClass, severityLabel, sourceLabel } from './labels';
import { Money, StatusChip } from './ui';
import { PeriodPicker } from './PeriodPicker';

export function SyncTab({
  connection,
  range,
  onRange,
  canEdit,
}: {
  connection: Connection;
  range: DateRange;
  onRange: (r: DateRange) => void;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const id = connection.id;
  const live = LIVE_PROVIDERS.includes(connection.provider);
  const [failedOnly, setFailedOnly] = useState(false);
  const [offset, setOffset] = useState(0);

  const findingsQ = useFindings(id);
  const docsQ = useDocuments(id, range);
  const logQ = useSyncLog(id, failedOnly, offset);

  const onError = (err: unknown) =>
    addToast({ type: 'error', title: t('accountingSync.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });
  const resultToast = (r: PushResult) =>
    addToast({
      type: r.failed > 0 ? 'warning' : 'success',
      title: t('accountingSync.sync.result', {
        defaultValue: '{{success}} synced, {{failed}} failed, {{skipped}} skipped',
        success: r.success,
        failed: r.failed,
        skipped: r.skipped,
      }),
    });

  const pushMut = useSyncMutation(() => pushRecords(id));
  const pullMut = useSyncMutation(() => pullPayments(id));
  const retryMut = useSyncMutation((entryId: string) => retryLogEntry(id, entryId));

  const findings = findingsQ.data ?? [];
  const docs = docsQ.data ?? [];
  const log = logQ.data;
  const total = log?.total ?? 0;
  const blocked = needsAuthorisation(connection);

  return (
    <div className="space-y-4" data-testid="accounting-sync-sync">
      {live && (
        <Card padding="md">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              icon={<Upload size={14} />}
              disabled={!canEdit || blocked}
              loading={pushMut.isPending}
              onClick={() => pushMut.mutate(undefined, { onSuccess: resultToast, onError })}
            >
              {t('accountingSync.sync.push', { defaultValue: 'Push now' })}
            </Button>
            <Button
              variant="secondary"
              icon={<Download size={14} />}
              disabled={!canEdit || blocked}
              loading={pullMut.isPending}
              onClick={() => pullMut.mutate(undefined, { onSuccess: resultToast, onError })}
            >
              {t('accountingSync.sync.pull', { defaultValue: 'Pull payments' })}
            </Button>
            <p className="text-xs text-content-tertiary">
              {blocked
                ? t('accountingSync.sync.authorise_first', { defaultValue: 'Authorise the connection in Settings before you push.' })
                : t('accountingSync.sync.push_hint', { defaultValue: 'Sends approved invoices and bills that were not sent yet. Payments recorded in your books come back.' })}
            </p>
          </div>
        </Card>
      )}

      <Card padding="md">
        <h3 className="mb-2 text-sm font-semibold text-content-primary">{t('accountingSync.findings.title', { defaultValue: 'Checks before sending' })}</h3>
        {findingsQ.isLoading ? (
          <p className="text-sm text-content-tertiary">{t('accountingSync.loading', { defaultValue: 'Loading...' })}</p>
        ) : findings.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400" data-testid="accounting-sync-findings-ok">
            <CheckCircle2 size={16} />
            {t('accountingSync.findings.ok', { defaultValue: 'Nothing blocks the next sync' })}
          </p>
        ) : (
          <ul className="space-y-1.5" data-testid="accounting-sync-findings">
            {findings.map((f, i) => (
              <li key={`${f.rule_id}-${f.record_id ?? f.element_ref ?? i}`} className="flex flex-wrap items-baseline gap-2 text-sm">
                <span className={clsx('rounded-full px-2 py-0.5 text-2xs font-medium', severityClass(f.severity))}>
                  {severityLabel(t, f.severity)}
                </span>
                <span className="font-medium text-content-primary">{ruleLabel(t, f.rule_id)}</span>
                <span className="text-content-secondary">{f.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card padding="md">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h3 className="text-sm font-semibold text-content-primary">{t('accountingSync.docs.title', { defaultValue: 'Documents in the period' })}</h3>
          <PeriodPicker range={range} onChange={onRange} />
        </div>
        {docsQ.isLoading ? (
          <p className="text-sm text-content-tertiary">{t('accountingSync.loading', { defaultValue: 'Loading...' })}</p>
        ) : docs.length === 0 ? (
          <p className="text-sm text-content-tertiary">{t('accountingSync.docs.empty', { defaultValue: 'No documents in this period.' })}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] text-sm" data-testid="accounting-sync-docs">
              <thead>
                <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.docs.number', { defaultValue: 'Number' })}</th>
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.docs.type', { defaultValue: 'Type' })}</th>
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.docs.date', { defaultValue: 'Date' })}</th>
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.docs.counterparty', { defaultValue: 'Counterparty' })}</th>
                  <th className="pb-2 pr-3 text-right font-medium">{t('accountingSync.docs.net', { defaultValue: 'Net' })}</th>
                  <th className="pb-2 pr-3 text-right font-medium">{t('accountingSync.docs.tax', { defaultValue: 'Tax' })}</th>
                  <th className="pb-2 text-right font-medium">{t('accountingSync.docs.gross', { defaultValue: 'Gross' })}</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={`${d.record_type}-${d.record_id}`} className="border-t border-border-light">
                    <td className="py-1.5 pr-3 font-medium text-content-primary">{d.number}</td>
                    <td className="py-1.5 pr-3 text-content-secondary">
                      {recordTypeLabel(t, d.record_type)}
                      <span className="block text-2xs text-content-tertiary">{sourceLabel(t, d.source)}</span>
                    </td>
                    <td className="py-1.5 pr-3 text-content-secondary"><DateDisplay value={d.doc_date} /></td>
                    <td className="py-1.5 pr-3 text-content-secondary">{d.counterparty || '—'}</td>
                    <td className="py-1.5 pr-3 text-right"><Money value={d.net_total} currency={d.currency} /></td>
                    <td className="py-1.5 pr-3 text-right"><Money value={d.tax_total} currency={d.currency} /></td>
                    <td className="py-1.5 text-right font-medium"><Money value={d.gross_total} currency={d.currency} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card padding="md">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-content-primary">{t('accountingSync.log.title', { defaultValue: 'Sync log' })}</h3>
          <label className="flex items-center gap-2 text-sm text-content-secondary">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
              checked={failedOnly}
              onChange={(e) => {
                setFailedOnly(e.target.checked);
                setOffset(0);
              }}
            />
            {t('accountingSync.log.failed_only', { defaultValue: 'Failed only' })}
          </label>
        </div>
        {logQ.isLoading ? (
          <p className="text-sm text-content-tertiary">{t('accountingSync.loading', { defaultValue: 'Loading...' })}</p>
        ) : !log || log.items.length === 0 ? (
          <EmptyState
            title={t('accountingSync.log.empty', { defaultValue: 'Nothing in the log yet' })}
            description={t('accountingSync.log.empty_hint', { defaultValue: 'Every push, pull and export is recorded here.' })}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] text-sm" data-testid="accounting-sync-log">
              <thead>
                <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.log.time', { defaultValue: 'Time' })}</th>
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.log.action', { defaultValue: 'Action' })}</th>
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.log.record', { defaultValue: 'Record' })}</th>
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.log.status', { defaultValue: 'Status' })}</th>
                  <th className="pb-2 pr-3 font-medium">{t('accountingSync.log.reason', { defaultValue: 'Reason' })}</th>
                  <th className="pb-2 pr-3 text-right font-medium">{t('accountingSync.log.attempt', { defaultValue: 'Attempt' })}</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {log.items.map((e) => (
                  <tr key={e.id} className="border-t border-border-light align-top" data-testid={`log-row-${e.id}`}>
                    <td className="py-1.5 pr-3 text-content-secondary"><DateDisplay value={e.created_at} /></td>
                    <td className="py-1.5 pr-3 text-content-secondary">{actionLabel(t, e.action)}</td>
                    <td className="py-1.5 pr-3 text-content-primary">
                      {e.record_label || '—'}
                      {e.amount && <span className="block text-2xs text-content-tertiary"><Money value={e.amount} currency={connection.base_currency} /></span>}
                    </td>
                    <td className="py-1.5 pr-3"><StatusChip status={e.status} /></td>
                    <td className="max-w-[18rem] py-1.5 pr-3 text-content-secondary">{e.error_reason || '—'}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">{e.attempt}</td>
                    <td className="py-1.5 text-right">
                      {canRetry(e) && canEdit && (
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<RotateCcw size={13} />}
                          loading={retryMut.isPending && retryMut.variables === e.id}
                          onClick={() => retryMut.mutate(e.id, { onError })}
                        >
                          {t('accountingSync.log.retry', { defaultValue: 'Retry' })}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > LOG_PAGE_SIZE && (
          <div className="mt-3 flex items-center justify-between text-xs text-content-tertiary">
            <span>
              {t('accountingSync.log.range', {
                defaultValue: '{{from}} to {{to}} of {{total}}',
                from: offset + 1,
                to: Math.min(offset + LOG_PAGE_SIZE, total),
                total,
              })}
            </span>
            <span className="flex gap-2">
              <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LOG_PAGE_SIZE))}>
                {t('accountingSync.log.prev', { defaultValue: 'Previous' })}
              </Button>
              <Button variant="secondary" size="sm" disabled={offset + LOG_PAGE_SIZE >= total} onClick={() => setOffset(offset + LOG_PAGE_SIZE)}>
                {t('accountingSync.log.next', { defaultValue: 'Next' })}
              </Button>
            </span>
          </div>
        )}
        <div className="mt-2 flex justify-end">
          <Button variant="ghost" size="sm" icon={<RefreshCw size={13} />} onClick={() => void logQ.refetch()}>
            {t('accountingSync.log.refresh', { defaultValue: 'Refresh' })}
          </Button>
        </div>
      </Card>
    </div>
  );
}
