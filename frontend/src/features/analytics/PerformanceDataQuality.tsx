// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How far the selected projects' records can carry a position benchmark: the
// share of approved hours booked to a bill position, the share of priced
// positions with reported progress, and the share classified under the chosen
// standard. A share whose whole is zero reads "no data", never 0 %.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';
import { fmtNumber } from '@/shared/lib/formatters';
import { fetchDataQuality, toNumber, type BenchmarkCohort, type Decimalish } from './performance';
import { fmtShare } from './performanceFormat';

export function PerformanceDataQuality({
  cohort,
  classificationKey,
}: {
  cohort: BenchmarkCohort;
  classificationKey: string | null;
}) {
  const { t } = useTranslation();
  const body = { ...cohort, classification_key: classificationKey || null };
  const query = useQuery({
    queryKey: ['analytics', 'performance', 'data-quality', body],
    queryFn: () => fetchDataQuality(body),
    staleTime: 60_000,
  });
  const d = query.data;
  if (!d) return null;
  const none = t('analytics.perf.dq_no_data', { defaultValue: 'no data' });

  return (
    <div
      className="flex flex-wrap items-start gap-x-6 gap-y-2 rounded-lg border border-border-light px-3 py-2 text-xs"
      data-testid="analytics-performance-data-quality"
    >
      <span className="flex items-center gap-1 font-medium text-content-primary">
        <ShieldCheck size={14} />
        {t('analytics.perf.dq_title', { defaultValue: 'Data quality' })}
      </span>
      <Share
        label={t('analytics.perf.dq_hours', { defaultValue: 'Hours booked to a position' })}
        share={d.hours_linked_share}
        detail={
          toNumber(d.hours_total) === null
            ? null
            : t('analytics.perf.dq_hours_detail', {
                defaultValue: '{{linked}} of {{total}} h',
                linked: fmtNumber(toNumber(d.hours_linked) ?? 0, 0),
                total: fmtNumber(toNumber(d.hours_total) ?? 0, 0),
              })
        }
        none={none}
      />
      <Share
        label={t('analytics.perf.dq_progress', { defaultValue: 'Positions with progress' })}
        share={d.progress_share}
        detail={
          d.positions_total
            ? t('analytics.perf.dq_count_detail', {
                defaultValue: '{{count}} of {{total}}',
                count: d.positions_with_progress ?? 0,
                total: d.positions_total,
              })
            : null
        }
        none={none}
      />
      {d.classification_key && (
        <Share
          label={t('analytics.perf.dq_classified', {
            defaultValue: 'Positions classified ({{key}})',
            key: d.classification_key,
          })}
          share={d.classification_share}
          detail={
            d.positions_total
              ? t('analytics.perf.dq_count_detail', {
                  defaultValue: '{{count}} of {{total}}',
                  count: d.positions_classified ?? 0,
                  total: d.positions_total,
                })
              : null
          }
          none={none}
        />
      )}
      <span className="basis-full text-2xs text-content-tertiary">
        {t('analytics.perf.dq_hint', {
          defaultValue:
            'Productivity per position needs approved hours booked to bill positions and reported progress. Low shares here mean the benchmark rests on part of the work only.',
        })}
      </span>
    </div>
  );
}

function Share({
  label,
  share,
  detail,
  none,
}: {
  label: string;
  share: Decimalish;
  detail: string | null;
  none: string;
}) {
  const pct = fmtShare(share);
  const n = toNumber(share);
  const tone = n === null ? 'text-content-tertiary' : n >= 0.8 ? 'text-semantic-success' : n >= 0.5 ? 'text-content-primary' : 'text-semantic-warning';
  return (
    <span className="flex flex-col">
      <span className="text-content-tertiary">{label}</span>
      <span className={`font-semibold tabular-nums ${tone}`}>
        {pct ?? none}
        {detail && <span className="ms-1 font-normal text-content-tertiary">({detail})</span>}
      </span>
    </span>
  );
}
