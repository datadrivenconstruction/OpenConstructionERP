// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Framework agreements register: every agreement the user can see, highest use of the cap
 * first. Inside a project (/projects/:projectId/framework-agreements) it lists that project's
 * agreements and the ones its parent holds.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Layers3, Plus, Gauge, CalendarClock, ClipboardList, Search } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  KpiBand,
  ModuleGuideButton,
  PageHeader,
  SkeletonTable,
} from '@/shared/ui';
import type { KpiBandItem } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { fwkApi, fwkKeys, type AgreementSummary } from './api';
import { CapMeter } from './CapMeter';
import { CreateAgreementModal } from './CreateAgreementModal';
import { frameworkGuide } from './frameworkGuide';
import { statusVariant } from './status';

type StatusFilter = 'open' | 'all' | 'exhausted' | 'closed';

export function FrameworkRegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useActiveProjectId();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<StatusFilter>('open');
  const [creating, setCreating] = useState(false);

  const query = useQuery({
    queryKey: fwkKeys.list(routeProjectId),
    queryFn: () => fwkApi.list(routeProjectId),
  });
  const rows = query.data?.items ?? [];

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (status === 'open' && (r.status === 'closed' || r.status === 'expired')) return false;
      if (status === 'exhausted' && r.status !== 'exhausted') return false;
      if (status === 'closed' && r.status !== 'closed' && r.status !== 'expired') return false;
      if (!needle) return true;
      return `${r.code} ${r.title} ${r.client_name}`.toLowerCase().includes(needle);
    });
  }, [rows, search, status]);

  const kpis: KpiBandItem[] = useMemo(() => {
    const active = rows.filter((r) => r.status === 'active' || r.status === 'signed');
    const highest = rows.reduce<AgreementSummary | null>(
      (best, r) => (r.consumption.pct != null && (!best || Number(r.consumption.pct) > Number(best.consumption.pct)) ? r : best),
      null,
    );
    const near = rows.filter(
      (r) => r.consumption.pct != null && Number(r.consumption.pct) >= Number(r.consumption.threshold_pct),
    ).length;
    return [
      { key: 'active', label: t('framework.kpi.active', { defaultValue: 'Active' }), value: active.length, icon: Layers3 },
      {
        key: 'highest',
        label: t('framework.kpi.highest_use', { defaultValue: 'Highest use' }),
        value: highest?.consumption.pct != null ? `${highest.consumption.pct} %` : '-',
        sub: highest?.code,
        icon: Gauge,
        tone: near ? 'warning' : undefined,
        tintValue: near > 0,
      },
      {
        key: 'month',
        label: t('framework.kpi.orders_this_month', { defaultValue: 'Orders this month' }),
        value: rows.reduce((s, r) => s + r.orders_this_month, 0),
        icon: ClipboardList,
      },
      {
        key: 'near',
        label: t('framework.kpi.near_cap', { defaultValue: 'At or past the threshold' }),
        value: near,
        icon: CalendarClock,
        tone: near ? 'warning' : undefined,
      },
    ];
  }, [rows, t]);

  const canCreate = Boolean(routeProjectId || activeProjectId);
  const crumbs = [
    { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
    { label: t('framework.title', { defaultValue: 'Framework agreements' }) },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={crumbs} />
      <PageHeader
        srTitle={t('framework.title', { defaultValue: 'Framework agreements' })}
        subtitle={t('framework.subtitle', {
          defaultValue: 'Agreed unit rates ordered job by job, with the agreement cap always in view.',
        })}
        actions={
          <>
            <Button variant="primary" icon={<Plus size={16} />} disabled={!canCreate} onClick={() => setCreating(true)}>
              {t('framework.new_agreement', { defaultValue: 'New agreement' })}
            </Button>
            <ModuleGuideButton content={frameworkGuide} />
          </>
        }
      />
      <DismissibleInfo
        storageKey="framework.how"
        title={t('framework.intro_title', { defaultValue: 'Rates agreed once, ordered job by job' })}
      >
        {t('framework.intro_body', {
          defaultValue:
            'Each call-off order takes its rates from the agreement price list, adjusted for the order date and conditions, and counts against the cap. The meter shows how much is left before the next order.',
        })}
      </DismissibleInfo>

      <KpiBand items={kpis} />

      <div className="flex flex-wrap items-center gap-2">
        <label className="relative">
          <span className="sr-only">{t('common.search', { defaultValue: 'Search' })}</span>
          <Search size={14} className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('framework.search', { defaultValue: 'Agreement, client or code' })}
            className="oe-input w-64 ps-8 text-sm"
          />
        </label>
        {(['open', 'exhausted', 'closed', 'all'] as const).map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={status === s}
            onClick={() => setStatus(s)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              status === s
                ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                : 'border-border-light text-content-secondary hover:bg-surface-secondary'
            }`}
          >
            {t(`framework.filter.${s}`, { defaultValue: FILTER_DEFAULTS[s] })}
          </button>
        ))}
      </div>

      <Card padding="none">
        {query.isLoading ? (
          <SkeletonTable rows={5} columns={7} />
        ) : query.isError ? (
          <ErrorState
            title={t('framework.error.load', { defaultValue: 'The agreements could not be loaded.' })}
            onRetry={() => query.refetch()}
          />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<Layers3 size={28} />}
            title={t('framework.empty.agreements', { defaultValue: 'No framework agreements yet.' })}
            description={t('framework.empty.agreements_hint', {
              defaultValue: 'Create one with its price list; orders are priced from it.',
            })}
            action={
              canCreate ? (
                <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
                  {t('framework.new_agreement', { defaultValue: 'New agreement' })}
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-start text-xs text-content-tertiary">
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.agreement', { defaultValue: 'Agreement' })}</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.client', { defaultValue: 'Client' })}</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.term', { defaultValue: 'Term' })}</th>
                  <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.kpi.cap', { defaultValue: 'Cap' })}</th>
                  <th scope="col" className="w-48 px-4 py-2 text-start font-medium">{t('framework.col.used', { defaultValue: 'Used' })}</th>
                  <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.orders', { defaultValue: 'Orders' })}</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.status', { defaultValue: 'Status' })}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr
                    key={r.id}
                    tabIndex={0}
                    onClick={() => navigate(`/framework-agreements/${r.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') navigate(`/framework-agreements/${r.id}`);
                    }}
                    className="cursor-pointer border-b border-border-light last:border-0 hover:bg-surface-secondary focus-visible:bg-surface-secondary focus-visible:outline-none"
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-content-primary">{r.title}</div>
                      <div className="text-xs text-content-tertiary"><bdi>{r.code}</bdi></div>
                    </td>
                    <td className="px-4 py-2.5 text-content-secondary">{r.client_name || '-'}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-content-secondary">
                      <DateDisplay value={r.start_date} /> - <DateDisplay value={r.end_date} />
                    </td>
                    <td className="px-4 py-2.5 text-end tabular-nums">
                      {r.consumption.cap != null ? <MoneyDisplay amount={r.consumption.cap} currency={r.currency} compact /> : '-'}
                    </td>
                    <td className="px-4 py-2.5">
                      <CapMeter
                        compact
                        cap={r.consumption.cap}
                        committed={r.consumption.committed}
                        certified={r.consumption.certified}
                        threshold_pct={r.consumption.threshold_pct}
                        valueText={`${r.consumption.pct ?? '-'} %`}
                      />
                    </td>
                    <td className="px-4 py-2.5 text-end tabular-nums">{r.consumption.orders}</td>
                    <td className="px-4 py-2.5">
                      <Badge variant={statusVariant(r.status)} size="sm">
                        {t(`framework.status.${r.status}`, { defaultValue: r.status })}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {creating && (
        <CreateAgreementModal
          projectId={routeProjectId || activeProjectId}
          onClose={() => setCreating(false)}
          onCreated={(id) => navigate(`/framework-agreements/${id}`)}
        />
      )}
    </div>
  );
}

const FILTER_DEFAULTS: Record<StatusFilter, string> = {
  open: 'Open',
  exhausted: 'Used up',
  closed: 'Closed or expired',
  all: 'All',
};
