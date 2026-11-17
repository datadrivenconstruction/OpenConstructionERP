// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Morning briefing for the site manager: weather, RFIs, inspections, deliveries, yesterday's
 * diary. Facts come from the platform; an AI provider only adds the opening paragraph.
 * `loader` lets the field PWA read the same briefing through its own session.
 */

import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { CloudSun, Loader2, RefreshCw, Sunrise } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { fetchLatestBriefing, runBriefing, type BriefingEnvelope, type BriefingItem } from './api';
import { DegradedBanner } from './ProposalReview';

interface Props {
  projectId: string;
  /** Replaces the default fetch (field PWA); also hides the generate / refresh buttons. */
  loader?: () => Promise<BriefingEnvelope>;
  compact?: boolean;
}

export function SiteBriefingCard({ projectId, loader, compact }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const canRun = useHasPermission('ai_agents.site.run') && !loader;
  const key = ['site-briefing', projectId, loader ? 'field' : 'app'];

  const latest = useQuery<BriefingEnvelope>({
    queryKey: key,
    queryFn: () => (loader ? loader() : fetchLatestBriefing(projectId)),
    enabled: !!projectId,
    staleTime: 60_000,
    retry: false,
  });

  const run = useMutation({
    mutationFn: (refresh: boolean) => runBriefing(projectId, refresh),
    onSuccess: (data) => qc.setQueryData(key, { ...data, exists: true, is_today: true }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('site_ai.briefing.run_failed', { defaultValue: 'Could not prepare the briefing' }),
        message: e.message,
      }),
  });

  if (latest.isError && !loader) return null;
  const data = latest.data;
  const hasBriefing = !!data?.exists;
  const current = hasBriefing && data?.is_today;
  if (loader && !hasBriefing) return null;

  return (
    <section
      data-testid="site-briefing-card"
      className="rounded-xl border border-border-light bg-surface-elevated p-4 shadow-sm"
    >
      <header className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <Sunrise size={16} className="text-amber-500" />
          {t('site_ai.briefing.title', { defaultValue: 'Morning briefing' })}
        </h2>
        {canRun && (
          <Button
            size="sm"
            variant={hasBriefing ? 'ghost' : 'primary'}
            disabled={run.isPending}
            onClick={() => run.mutate(hasBriefing)}
            icon={run.isPending ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            data-testid="site-briefing-run"
          >
            {hasBriefing
              ? t('site_ai.briefing.refresh', { defaultValue: 'Refresh' })
              : t('site_ai.briefing.prepare', { defaultValue: 'Prepare today' })}
          </Button>
        )}
      </header>

      {latest.isLoading && (
        <p className="mt-3 text-sm text-content-tertiary">{t('site_ai.loading', { defaultValue: 'Loading...' })}</p>
      )}

      {!latest.isLoading && !hasBriefing && (
        <p className="mt-3 text-sm text-content-tertiary" data-testid="site-briefing-empty">
          {t('site_ai.briefing.none', { defaultValue: 'No briefing yet. Prepare today\'s briefing or set a daily time in Settings.' })}
        </p>
      )}

      {hasBriefing && data && (
        <div className="mt-3 flex flex-col gap-3">
          {!current && (
            <p className="text-xs text-content-tertiary" data-testid="site-briefing-stale">
              {t('site_ai.briefing.from_day', { defaultValue: 'From {{day}}', day: data.day })}
            </p>
          )}
          {data.degraded && <DegradedBanner />}
          {data.narrative && (
            <p className="text-sm leading-relaxed text-content-primary" data-testid="site-briefing-narrative">
              {data.narrative}
            </p>
          )}
          {data.items.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('site_ai.briefing.all_clear', { defaultValue: 'Nothing needs attention today.' })}
            </p>
          ) : (
            <ul className={`grid gap-3 ${compact ? '' : 'sm:grid-cols-2'}`}>
              {data.items.map((item) => (
                <BriefingBlock key={item.id} item={item} projectId={projectId} />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

const BLOCK_DEFAULTS: Record<BriefingItem['id'], string> = {
  weather: 'Weather today',
  rfis_overdue: 'Overdue RFIs ({{n}})',
  rfis_open: 'Open RFIs ({{n}})',
  inspections_due: 'Inspections in the next 48 hours ({{n}})',
  deliveries_today: 'Deliveries today ({{n}})',
  diary_yesterday: "Yesterday's diary",
};

const LINKS: Partial<Record<BriefingItem['id'], string>> = {
  rfis_overdue: 'rfi',
  rfis_open: 'rfi',
  inspections_due: 'inspections',
  deliveries_today: 'site-logistics',
  diary_yesterday: 'daily-diary',
};

function BriefingBlock({ item, projectId }: { item: BriefingItem; projectId: string }) {
  const { t } = useTranslation();
  const link = LINKS[item.id];
  const heading = t(`site_ai.briefing.block.${item.id}`, {
    defaultValue: BLOCK_DEFAULTS[item.id],
    n: item.count,
  });
  return (
    <li className="rounded-lg border border-border-light p-3" data-testid={`site-briefing-${item.id}`}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {item.id === 'weather' && <CloudSun size={13} />}
          {heading}
        </h3>
        {link && (
          <Link to={`/${link}?project=${projectId}`} className="text-xs text-oe-blue hover:underline">
            {t('site_ai.briefing.open', { defaultValue: 'Open' })}
          </Link>
        )}
      </div>
      <ul className="mt-2 flex flex-col gap-1 text-sm text-content-primary">
        {item.entries.map((e, idx) => (
          <li key={idx} className="truncate">
            {item.id === 'weather' ? (
              t('site_ai.briefing.weather_line', {
                defaultValue: '{{conditions}}, {{temp}} °C, wind {{wind}} km/h',
                conditions: e.conditions ?? '-',
                temp: e.temperature_c ?? '-',
                wind: e.wind_kmh ?? '-',
              })
            ) : item.id === 'diary_yesterday' ? (
              t('site_ai.briefing.diary_line', {
                defaultValue: '{{labour}} on site, {{n}} entries',
                labour: e.labour ?? 0,
                n: item.count,
              })
            ) : (
              <>
                {e.ref && <span className="font-medium">{e.ref} </span>}
                {e.title}
                {e.due && <span className="text-content-tertiary"> · {e.due}</span>}
              </>
            )}
          </li>
        ))}
      </ul>
    </li>
  );
}
