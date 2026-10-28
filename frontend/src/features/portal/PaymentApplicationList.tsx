// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Subcontractor-portal payment-application list.
 *
 * Portal-user-facing (magic-link session), NOT the internal-admin PortalPage.
 * Mobile-first: single-column stacked cards at 375px, a light table from sm+.
 * Money is rendered exactly as the backend serialises it (Decimal string) with
 * the application's own currency — never a hardcoded symbol.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { FileText, Plus, AlertCircle } from 'lucide-react';
import { Button, Badge, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import {
  listMyPaymentApplications,
  type PaymentApplicationListItem,
} from './api';

const STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'warning' | 'success' | 'error'> = {
  submitted: 'blue',
  foreman_approved: 'warning',
  finance_approved: 'success',
  paid: 'success',
  rejected: 'error',
};

function formatMoney(amount: string, currency: string): string {
  // Keep the backend's exact Decimal string; prefix the ISO currency so we
  // never invent a locale-specific symbol the agreement did not specify.
  return currency ? `${currency} ${amount}` : amount;
}

export function PaymentApplicationList({
  onNew,
  onOpen,
}: {
  onNew: () => void;
  onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['portal', 'payment-applications'],
    queryFn: () => listMyPaymentApplications({ limit: 100 }),
  });

  const items = q.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-content-primary">
            {t('payportal.title', { defaultValue: 'Payment Applications' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('payportal.subtitle', {
              defaultValue: 'Submit and track your payment applications.',
            })}
          </p>
        </div>
        <Button variant="primary" icon={<Plus size={14} />} onClick={onNew}>
          {t('payportal.new_application', { defaultValue: 'New application' })}
        </Button>
      </div>

      {q.isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={5} columns={4} />
        </Card>
      ) : q.error ? (
        <Card padding="none">
          <EmptyState
            icon={<AlertCircle size={22} />}
            title={t('payportal.load_failed', {
              defaultValue: 'Could not load payment applications',
            })}
            description={q.error instanceof Error ? q.error.message : ''}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => void q.refetch(),
            }}
          />
        </Card>
      ) : items.length === 0 ? (
        <Card padding="none">
          <EmptyState
            icon={<FileText size={22} />}
            title={t('payportal.empty_title', {
              defaultValue: 'No payment applications yet',
            })}
            description={t('payportal.empty_desc', {
              defaultValue:
                'Submit your first payment application to start tracking certifications and payments.',
            })}
            action={{
              label: t('payportal.new_application', { defaultValue: 'New application' }),
              onClick: onNew,
            }}
          />
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((it) => (
            <PaymentApplicationCard key={it.id} item={it} onOpen={onOpen} />
          ))}
        </ul>
      )}
    </div>
  );
}

function PaymentApplicationCard({
  item,
  onOpen,
}: {
  item: PaymentApplicationListItem;
  onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(item.id)}
        className={clsx(
          'w-full rounded-xl border border-border bg-surface-primary p-4 text-left',
          'transition-colors hover:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-sm font-semibold text-content-primary">
            {item.application_number}
          </span>
          <Badge variant={STATUS_VARIANT[item.status] ?? 'neutral'} dot>
            {t(`payportal.status_${item.status}`, { defaultValue: item.status })}
          </Badge>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('payportal.period', { defaultValue: 'Period' })}
            </dt>
            <dd className="text-content-secondary">
              {item.period_start ? <DateDisplay value={item.period_start} /> : '—'}
              {item.period_end ? (
                <>
                  {' – '}
                  <DateDisplay value={item.period_end} />
                </>
              ) : null}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('payportal.gross', { defaultValue: 'Gross' })}
            </dt>
            <dd className="font-medium text-content-primary">
              {formatMoney(item.gross_amount, item.currency)}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('payportal.net', { defaultValue: 'Net' })}
            </dt>
            <dd className="font-medium text-content-primary">
              {formatMoney(item.net_amount, item.currency)}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('payportal.submitted_on', { defaultValue: 'Submitted' })}
            </dt>
            <dd className="text-content-secondary">
              {item.submitted_at ? <DateDisplay value={item.submitted_at} /> : '—'}
            </dd>
          </div>
        </dl>
      </button>
    </li>
  );
}
