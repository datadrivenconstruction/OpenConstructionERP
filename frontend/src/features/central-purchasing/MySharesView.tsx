// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a project team sees of central purchasing: its share of each bundle, its budget
 * and its own contract or order. Other projects' figures never reach this view.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { PackageOpen } from 'lucide-react';
import { Badge, Card, EmptyState, ErrorState, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { cpbApi, cpbKeys, type DocumentRef } from './api';
import { STATUS_DEFAULTS, statusVariant } from './status';

export function documentPath(doc: DocumentRef): string {
  if (doc.type === 'purchase_order') return '/procurement';
  return doc.project_id ? `/projects/${doc.project_id}/contracts` : '/contracts';
}

export function MySharesView({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: cpbKeys.myShares(projectId),
    queryFn: () => cpbApi.myShares(projectId),
    enabled: Boolean(projectId),
  });

  if (!projectId) {
    return (
      <Card>
        <EmptyState
          icon={<PackageOpen size={28} />}
          title={t('central_purchasing.my.no_project', { defaultValue: 'Open a project to see its share.' })}
          description={t('central_purchasing.my.no_project_hint', {
            defaultValue: 'Pick a project in the header. Its share of every bundle the buyer has published shows here.',
          })}
        />
      </Card>
    );
  }
  if (query.isLoading) return <SkeletonTable rows={4} columns={5} />;
  if (query.isError) {
    return (
      <ErrorState
        title={t('central_purchasing.error.load', { defaultValue: 'Central purchasing could not be loaded.' })}
        onRetry={() => query.refetch()}
      />
    );
  }
  const shares = query.data ?? [];
  if (shares.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<PackageOpen size={28} />}
          title={t('central_purchasing.my.empty', { defaultValue: 'This project is in no published bundle yet.' })}
          description={t('central_purchasing.my.empty_hint', {
            defaultValue: 'When the central buyer publishes a bundle with this project in it, your quantities and budget check appear here.',
          })}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {shares.map((s) => (
        <Card key={s.bundle_id} padding="none">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-light px-4 py-3">
            <div>
              <div className="font-medium text-content-primary">{s.title}</div>
              <div className="text-xs text-content-tertiary">
                <bdi>{s.code}</bdi>
                {s.vendor_name ? ` · ${s.vendor_name}` : ''}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusVariant(s.status)} size="sm">
                {t(`central_purchasing.status.${s.status}`, { defaultValue: STATUS_DEFAULTS[s.status] ?? s.status })}
              </Badge>
              {s.over_budget && (
                <Badge variant="warning" size="sm">
                  {t('central_purchasing.over_budget', { defaultValue: 'Over budget' })}
                </Badge>
              )}
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-3 px-4 py-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-content-tertiary">{t('central_purchasing.my.your_share', { defaultValue: 'Your share' })}</dt>
              <dd className="font-semibold tabular-nums"><MoneyDisplay amount={s.net} currency={s.currency} /></dd>
            </div>
            <div>
              <dt className="text-xs text-content-tertiary">{t('central_purchasing.col.budget', { defaultValue: 'Budget' })}</dt>
              <dd className="tabular-nums">{s.budget != null ? <MoneyDisplay amount={s.budget} currency={s.currency} /> : '-'}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-xs text-content-tertiary">{t('central_purchasing.col.document', { defaultValue: 'Document' })}</dt>
              <dd>
                {s.document?.id ? (
                  <Link to={documentPath(s.document)} className="text-oe-blue hover:underline">
                    <bdi>{s.document.code || s.document.id}</bdi>
                  </Link>
                ) : (
                  <span className="text-content-tertiary">
                    {t('central_purchasing.my.not_awarded', { defaultValue: 'Not awarded yet' })}
                  </span>
                )}
              </dd>
            </div>
          </dl>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-y border-border-light text-xs text-content-tertiary">
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.line', { defaultValue: 'Line' })}</th>
                  <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.your_qty', { defaultValue: 'Your quantity' })}</th>
                  {s.mode === 'framework_call_off' && (
                    <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.called_off', { defaultValue: 'Called off' })}</th>
                  )}
                  <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.rate', { defaultValue: 'Rate' })}</th>
                  <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.amount', { defaultValue: 'Amount' })}</th>
                </tr>
              </thead>
              <tbody>
                {s.lines.map((ln, i) => (
                  <tr key={`${ln.code}-${i}`} className="border-b border-border-light last:border-0">
                    <td className="px-4 py-2">
                      <div className="text-content-primary"><bdi>{ln.code}</bdi> {ln.description}</div>
                    </td>
                    <td className="px-4 py-2 text-end tabular-nums">{ln.quantity ?? '-'} {ln.unit}</td>
                    {s.mode === 'framework_call_off' && (
                      <td className="px-4 py-2 text-end tabular-nums">{ln.called_off ?? '-'}</td>
                    )}
                    <td className="px-4 py-2 text-end tabular-nums">
                      {ln.rate != null ? <MoneyDisplay amount={ln.rate} currency={s.currency} /> : '-'}
                    </td>
                    <td className="px-4 py-2 text-end tabular-nums">
                      {ln.net != null ? <MoneyDisplay amount={ln.net} currency={s.currency} /> : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  );
}
