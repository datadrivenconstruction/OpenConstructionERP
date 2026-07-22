// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery } from '@tanstack/react-query';
import { Landmark, Lock } from 'lucide-react';
import clsx from 'clsx';
import { Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ApiError } from '@/shared/lib/api';
import { getRetentionLedger } from './api';

/* ── Helpers ────────────────────────────────────────────────────────────── */

/** A 403 (missing ``finance.read``) is surfaced as an access-required state. */
function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}

/** Human label for the payable / receivable direction of a retainage line. */
function directionLabel(t: TFunction, direction: string): string {
  if (direction === 'payable') {
    return t('finance.retention_payable', { defaultValue: 'Payable' });
  }
  if (direction === 'receivable') {
    return t('finance.retention_receivable', { defaultValue: 'Receivable' });
  }
  return direction;
}

/** Badge tint per direction: receivable (owed to us) blue, payable amber. */
function directionVariant(direction: string): 'blue' | 'warning' | 'neutral' {
  if (direction === 'receivable') return 'blue';
  if (direction === 'payable') return 'warning';
  return 'neutral';
}

/** Render a 0-100 percentage string ("42.50") as "42.5%", else the n/a label. */
function formatPct(value: string | null, naLabel: string): string {
  if (value == null) return naLabel;
  const n = parseFloat(value);
  if (Number.isNaN(n)) return naLabel;
  return `${n.toFixed(1)}%`;
}

/** A labelled money figure used inside a per-total summary card. */
function Stat({
  label,
  amount,
  currency,
  strong,
}: {
  label: string;
  amount: string;
  currency: string;
  strong?: boolean;
}) {
  return (
    <div>
      <p className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
        {label}
      </p>
      <p
        className={clsx(
          'mt-0.5 tabular-nums',
          strong ? 'text-base font-semibold text-content-primary' : 'text-sm text-content-primary',
        )}
      >
        <MoneyDisplay amount={amount} currency={currency || undefined} />
      </p>
    </div>
  );
}

/* ── Tab ────────────────────────────────────────────────────────────────── */

/**
 * Retention / withholding ledger for the active project. Reads the
 * ``/v1/finance/retention-ledger/`` rollup and shows per-(currency, direction)
 * totals plus a per-counterparty breakdown. Nothing is blended across
 * currencies or across payable / receivable, so each row carries its own
 * currency for display.
 */
export function RetentionLedgerTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const ledgerQ = useQuery({
    queryKey: ['finance', 'retention-ledger', projectId],
    queryFn: () => getRetentionLedger(projectId),
  });

  const naLabel = t('finance.retention_na', { defaultValue: 'n/a' });

  const loading = !ledgerQ.data && !ledgerQ.isError;
  const isEmpty =
    !!ledgerQ.data && ledgerQ.data.totals.length === 0 && ledgerQ.data.groups.length === 0;

  return (
    <div className="space-y-4">
      {/* Intro */}
      <div className="rounded-lg border border-oe-blue/15 bg-oe-blue/[0.03] p-3">
        <p className="text-sm text-content-secondary">
          {t('finance.retention_subtitle', {
            defaultValue:
              'Retainage held back across the project, computed from invoice retention and payment withholding. Totals are grouped per currency and per payable / receivable, with a per-counterparty breakdown of what has been scheduled, held, released and is still outstanding. Released means the contractual release date has been reached, not that cash has been returned.',
          })}
        </p>
      </div>

      {ledgerQ.isError && isForbidden(ledgerQ.error) ? (
        <EmptyState
          icon={<Lock size={26} strokeWidth={1.5} />}
          title={t('finance.retention_forbidden_title', {
            defaultValue: 'Finance access required',
          })}
          description={t('finance.retention_forbidden_desc', {
            defaultValue:
              'You do not have permission to read finance data, so the retention ledger cannot be shown. Ask an administrator to grant the finance read role.',
          })}
        />
      ) : ledgerQ.isError ? (
        <RecoveryCard error={ledgerQ.error} onRetry={() => ledgerQ.refetch()} />
      ) : loading ? (
        <SkeletonTable rows={6} columns={4} />
      ) : isEmpty ? (
        <EmptyState
          icon={<Landmark size={26} strokeWidth={1.5} />}
          title={t('finance.retention_empty_title', { defaultValue: 'No retention recorded' })}
          description={t('finance.retention_empty_desc', {
            defaultValue:
              'No invoice retention or payment withholding has been recorded on this project yet. Retainage appears here once invoices carry a retention amount or payments hold back a withholding.',
          })}
        />
      ) : (
        <>
          {/* As-of caption */}
          {ledgerQ.data?.as_of && (
            <p className="flex flex-wrap items-center gap-1.5 text-xs text-content-tertiary">
              <span>{t('finance.retention_as_of', { defaultValue: 'Released as of' })}</span>
              <DateDisplay
                value={ledgerQ.data.as_of}
                className="font-medium text-content-secondary"
              />
            </p>
          )}

          {/* Per-(currency, direction) totals */}
          <div className="grid gap-3 sm:grid-cols-2">
            {(ledgerQ.data?.totals ?? []).map((row) => (
              <Card
                key={`${row.currency_code}-${row.direction}`}
                padding="none"
                className="space-y-3 p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge variant={directionVariant(row.direction)} size="sm">
                      {directionLabel(t, row.direction)}
                    </Badge>
                    <span className="font-mono text-xs text-content-secondary">
                      {row.currency_code}
                    </span>
                  </div>
                  <span className="text-2xs text-content-tertiary">
                    {t('finance.retention_outstanding_of_held', {
                      defaultValue: '{{pct}} of held outstanding',
                      pct: formatPct(row.outstanding_pct, naLabel),
                    })}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Stat
                    label={t('finance.retention_scheduled', { defaultValue: 'Scheduled' })}
                    amount={row.scheduled}
                    currency={row.currency_code}
                  />
                  <Stat
                    label={t('finance.retention_held_to_date', { defaultValue: 'Held to date' })}
                    amount={row.held_to_date}
                    currency={row.currency_code}
                  />
                  <Stat
                    label={t('finance.retention_released_to_date', {
                      defaultValue: 'Released to date',
                    })}
                    amount={row.released_to_date}
                    currency={row.currency_code}
                  />
                  <Stat
                    label={t('finance.retention_outstanding', { defaultValue: 'Outstanding' })}
                    amount={row.outstanding}
                    currency={row.currency_code}
                    strong
                  />
                </div>
              </Card>
            ))}
          </div>

          {/* Per-counterparty breakdown */}
          <div>
            <h4 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('finance.retention_by_counterparty', { defaultValue: 'By counterparty' })}
            </h4>
            <Card padding="none" className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-secondary">
                      <th className="px-4 py-3 font-medium">
                        {t('finance.retention_col_counterparty', {
                          defaultValue: 'Counterparty',
                        })}
                      </th>
                      <th className="px-4 py-3 font-medium">
                        {t('finance.retention_col_direction', { defaultValue: 'Direction' })}
                      </th>
                      <th className="px-4 py-3 text-right font-medium">
                        {t('finance.retention_col_held', { defaultValue: 'Held to date' })}
                      </th>
                      <th className="px-4 py-3 text-right font-medium">
                        {t('finance.retention_col_released', { defaultValue: 'Released' })}
                      </th>
                      <th className="px-4 py-3 text-right font-medium">
                        {t('finance.retention_col_outstanding', { defaultValue: 'Outstanding' })}
                      </th>
                      <th className="px-4 py-3 text-right font-medium">
                        {t('finance.retention_col_payments', { defaultValue: 'Payments' })}
                      </th>
                      <th className="px-4 py-3 font-medium">
                        {t('finance.retention_col_latest_release', {
                          defaultValue: 'Latest release',
                        })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ledgerQ.data?.groups ?? []).map((row) => (
                      <tr
                        key={`${row.contact_id ?? 'none'}-${row.currency_code}-${row.direction}`}
                        className="border-b border-border/60 last:border-0 hover:bg-surface-secondary/50"
                      >
                        <td className="px-4 py-2.5 text-content-primary">
                          {row.counterparty_name ||
                            t('finance.retention_unnamed', {
                              defaultValue: 'Unspecified counterparty',
                            })}
                          <span className="ml-2 font-mono text-2xs text-content-tertiary">
                            {row.currency_code}
                          </span>
                        </td>
                        <td className="px-4 py-2.5">
                          <Badge variant={directionVariant(row.direction)} size="sm">
                            {directionLabel(t, row.direction)}
                          </Badge>
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-content-primary">
                          <MoneyDisplay
                            amount={row.held_to_date}
                            currency={row.currency_code || undefined}
                          />
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-content-secondary">
                          <MoneyDisplay
                            amount={row.released_to_date}
                            currency={row.currency_code || undefined}
                          />
                        </td>
                        <td className="px-4 py-2.5 text-right font-medium tabular-nums text-content-primary">
                          <MoneyDisplay
                            amount={row.outstanding}
                            currency={row.currency_code || undefined}
                          />
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-content-secondary">
                          {row.payment_count}
                        </td>
                        <td className="px-4 py-2.5 text-content-secondary">
                          {row.latest_release_date ? (
                            <DateDisplay value={row.latest_release_date} />
                          ) : (
                            <span className="text-content-tertiary">{naLabel}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
