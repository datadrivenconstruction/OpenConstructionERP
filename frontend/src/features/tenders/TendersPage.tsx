// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { Gavel, Inbox, Trophy, Scale } from 'lucide-react';
import { Badge, Breadcrumb, Card, EmptyState, ErrorState, KpiBand, SkeletonTable, TabBar } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import {
  fetchTenders,
  tenderCardPath,
  tendersQueryKey,
  type TenderKind,
  type TenderSource,
  type TenderSummary,
} from './api';
import { designRecordName } from '@/shared/lib/designRecordName';

type KindTab = 'all' | TenderKind;

const SOURCE_LABELS: Array<[TenderSource, string, string]> = [
  ['native', 'tenders.source_native', 'Tender'],
  ['tendering', 'tenders.source_tendering', 'Main contract tender'],
  ['rfq_bidding', 'tenders.source_rfq', 'Supplier RFQ'],
];

export function TendersPage() {
  const { t } = useTranslation();
  const projectId = useActiveProjectId();
  const [kind, setKind] = useState<KindTab>('all');
  const [searchParams] = useSearchParams();
  const [source, setSource] = useState<TenderSource | ''>(() => {
    const fromUrl = searchParams.get('source');
    return SOURCE_LABELS.some(([value]) => value === fromUrl) ? (fromUrl as TenderSource) : '';
  });
  const filters = { kind: kind === 'all' ? ('' as const) : kind, source };

  const query = useQuery({
    queryKey: tendersQueryKey(projectId, filters),
    queryFn: () => fetchTenders(projectId, filters),
    enabled: !!projectId,
  });
  const rows = useMemo(() => query.data ?? [], [query.data]);
  const counts = useMemo(
    () => ({
      total: rows.length,
      open: rows.filter((r) => r.status === 'published' || r.status === 'open').length,
      awarded: rows.filter((r) => r.status === 'awarded').length,
      bids: rows.reduce((sum, r) => sum + (r.bid_count || 0), 0),
    }),
    [rows],
  );

  const sourceLabel = (row: TenderSummary) => {
    const entry = SOURCE_LABELS.find(([value]) => value === row.source) ?? SOURCE_LABELS[0]!;
    return t(entry[1], { defaultValue: entry[2] });
  };

  return (
    <div className="min-w-0 space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('tenders.title', { defaultValue: 'Tenders' }) }]} />
      <PageHeader
        srTitle={t('tenders.title', { defaultValue: 'Tenders' })}
        subtitle={t('tenders.subtitle', {
          defaultValue: 'Every trade package and supplier quote request of the project in one list.',
        })}
      />
      {!projectId ? (
        <RequiresProject>{null}</RequiresProject>
      ) : (
        <>
          <KpiBand
            columns={4}
            items={[
              { key: 'total', label: t('tenders.kpi_total', { defaultValue: 'Tenders' }), value: counts.total, icon: Gavel },
              { key: 'open', label: t('tenders.kpi_open', { defaultValue: 'Open for bids' }), value: counts.open, icon: Inbox },
              { key: 'awarded', label: t('tenders.kpi_awarded', { defaultValue: 'Awarded' }), value: counts.awarded, icon: Trophy },
              { key: 'bids', label: t('tenders.kpi_bids', { defaultValue: 'Bids received' }), value: counts.bids, icon: Scale },
            ]}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <TabBar<KindTab>
              ariaLabel={t('tenders.kind_filter', { defaultValue: 'Kind of tender' })}
              activeId={kind}
              onChange={setKind}
              tabs={[
                { id: 'all', label: t('tenders.kind_all', { defaultValue: 'All' }) },
                { id: 'subcontract', label: t('tenders.kind_subcontract', { defaultValue: 'Trade packages' }) },
                { id: 'supply', label: t('tenders.kind_supply', { defaultValue: 'Supply' }) },
              ]}
            />
            <select
              className="oe-select w-56"
              aria-label={t('tenders.source_filter', { defaultValue: 'Created in' })}
              value={source}
              onChange={(e) => setSource(e.target.value as TenderSource | '')}
            >
              <option value="">{t('tenders.source_all', { defaultValue: 'Created anywhere' })}</option>
              {SOURCE_LABELS.map(([value, key, fallback]) => (
                <option key={value} value={value}>
                  {t(key, { defaultValue: fallback })}
                </option>
              ))}
            </select>
          </div>
          <Card>
            {query.isLoading ? (
              <SkeletonTable rows={5} columns={6} />
            ) : query.isError ? (
              <ErrorState
                title={t('tenders.load_failed', { defaultValue: 'The tenders could not be loaded.' })}
                onRetry={() => query.refetch()}
              />
            ) : rows.length === 0 ? (
              <EmptyState
                icon={<Gavel size={20} />}
                title={t('tenders.empty', { defaultValue: 'No tenders in this project yet.' })}
                action={
                  <Link className="text-sm text-oe-blue" to={`/projects/${projectId}/bid-management`}>
                    {t('tenders.create', { defaultValue: 'Create a trade package' })}
                  </Link>
                }
              />
            ) : (
              <div className="overflow-x-auto" data-testid="tenders-table-scroll">
                <table className="oe-table w-full whitespace-nowrap" data-testid="tenders-table">
                  <thead>
                    <tr>
                      <th>{t('tenders.col_code', { defaultValue: 'Code' })}</th>
                      <th>{t('tenders.col_title', { defaultValue: 'Title' })}</th>
                      <th>{t('tenders.source_filter', { defaultValue: 'Created in' })}</th>
                      <th>{t('tenders.col_status', { defaultValue: 'Status' })}</th>
                      <th>{t('tenders.col_deadline', { defaultValue: 'Bids due' })}</th>
                      <th className="num">{t('tenders.col_bids', { defaultValue: 'Bids' })}</th>
                      <th className="num">{t('tenders.col_lowest', { defaultValue: 'Lowest bid' })}</th>
                      <th>{t('tenders.col_awarded', { defaultValue: 'Awarded to' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.id}>
                        <td>
                          <Link className="text-oe-blue" to={tenderCardPath(row.id)}>
                            {row.code}
                          </Link>
                        </td>
                        <td className="text-content-primary">{designRecordName(t, row.title)}</td>
                        <td>
                          <Badge variant={row.source === 'native' ? 'neutral' : 'blue'}>{sourceLabel(row)}</Badge>
                        </td>
                        <td>{t(`bid_management.status_${row.status}`, { defaultValue: row.status })}</td>
                        <td>{row.submission_deadline ? <DateDisplay value={row.submission_deadline} /> : null}</td>
                        <td className="num tabular-nums">{row.bid_count}</td>
                        <td className="num tabular-nums">
                          {row.lowest_total != null ? (
                            <MoneyDisplay amount={row.lowest_total} currency={row.currency} />
                          ) : null}
                        </td>
                        <td>{row.awarded_bidder ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
