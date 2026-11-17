// Revision impact on the BOQ (issue #569). Rendered under a schedule
// comparison: for every activity the revision changed it shows the before and
// after finish, the finish movement, the duration and planned-cost deltas, the
// BOQ positions the activity is linked to and the variations on them.
// Read-only; it reuses the activity-to-BOQ links that already exist.

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link2Off, Layers } from 'lucide-react';

import { Badge, Card, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { scheduleApi, type RevisionImpact, type RevisionImpactActivity } from './api';
import { deltaTone, signedDays } from './scheduleInterop';

interface RevisionImpactCardProps {
  scheduleId: string;
  baseBaselineId: string;
  /** Another baseline as the target; omitted for the live schedule. */
  targetBaselineId?: string;
  currency?: string;
}

const TONE_CLS: Record<string, string> = {
  up: 'text-semantic-error',
  down: 'text-semantic-success',
  flat: 'text-content-secondary',
  none: 'text-content-tertiary',
};

function money(value: string | null | undefined, currency?: string, signed = false): string {
  if (value === null || value === undefined || value === '') return '';
  const n = Number(value);
  const text = formatCurrency(Math.abs(n), currency, undefined, { maximumFractionDigits: 0, minimumFractionDigits: 0 });
  if (!signed) return formatCurrency(n, currency, undefined, { maximumFractionDigits: 0, minimumFractionDigits: 0 });
  if (n > 0) return `+${text}`;
  if (n < 0) return `-${text}`;
  return text;
}

export function RevisionImpactCard({
  scheduleId,
  baseBaselineId,
  targetBaselineId,
  currency,
}: RevisionImpactCardProps) {
  const { t } = useTranslation();
  const q = useQuery<RevisionImpact>({
    queryKey: ['schedule', 'revision-impact', scheduleId, baseBaselineId, targetBaselineId ?? 'live'],
    queryFn: () => scheduleApi.getRevisionImpact(scheduleId, baseBaselineId, targetBaselineId),
    enabled: !!scheduleId && !!baseBaselineId,
  });

  const title = t('schedule.impact.title', { defaultValue: 'Revision impact on BOQ and cost' });

  if (q.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={3} columns={5} />
      </Card>
    );
  }
  if (q.isError) {
    return (
      <Card padding="md">
        <RecoveryCard error={q.error} onRetry={() => q.refetch()} />
      </Card>
    );
  }
  const data = q.data;
  if (!data) return null;
  const s = data.summary;

  return (
    <Card padding="none" data-testid="schedule-revision-impact">
      <div className="space-y-1 border-b border-border-light px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Layers size={16} className="text-content-secondary" />
          <h3 className="oe-card-title">{title}</h3>
          <Badge variant="neutral">{s.activities_revised}</Badge>
        </div>
        <p className="text-xs text-content-secondary">
          {t('schedule.impact.summary', {
            defaultValue:
              '{{linked}} of {{revised}} revised activities are linked to {{positions}} BOQ positions and {{variations}} variations.',
            linked: s.activities_linked,
            revised: s.activities_revised,
            positions: s.positions_linked,
            variations: s.variations_linked,
          })}
        </p>
        <div className="flex flex-wrap gap-4 text-xs">
          <span className="text-content-tertiary">
            {t('schedule.impact.cost_total', { defaultValue: 'Planned cost delta' })}:{' '}
            <span className={`font-semibold tabular-nums ${TONE_CLS[deltaTone(s.cost_delta_total)]}`}>
              {money(s.cost_delta_total, currency, true)}
            </span>
          </span>
          <span className="text-content-tertiary">
            {t('schedule.impact.linked_value', { defaultValue: 'Linked BOQ value' })}:{' '}
            <span className="font-semibold tabular-nums text-content-primary">
              {money(s.linked_value_total, currency)}
            </span>
          </span>
        </div>
      </div>

      {data.activities.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-content-tertiary">
          {t('schedule.impact.none', { defaultValue: 'This comparison has no revised activities.' })}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-surface-secondary text-content-tertiary">
              <tr>
                <th className="px-3 py-2 text-start font-medium">
                  {t('schedule.activity', { defaultValue: 'Activity' })}
                </th>
                <th className="px-3 py-2 text-start font-medium">
                  {t('schedule.impact.col_finish', { defaultValue: 'Finish before / after' })}
                </th>
                <th className="px-3 py-2 text-end font-medium">
                  {t('schedule.impact.col_movement', { defaultValue: 'Finish movement' })}
                </th>
                <th className="px-3 py-2 text-end font-medium">
                  {t('schedule.duration', { defaultValue: 'Duration' })}
                </th>
                <th className="px-3 py-2 text-end font-medium">
                  {t('schedule.impact.cost_total', { defaultValue: 'Planned cost delta' })}
                </th>
                <th className="px-3 py-2 text-start font-medium">
                  {t('schedule.impact.col_positions', { defaultValue: 'BOQ positions and variations' })}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {data.activities.map((row) => (
                <ImpactRow key={row.activity_id} row={row} currency={currency} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ImpactRow({ row, currency }: { row: RevisionImpactActivity; currency?: string }) {
  const { t } = useTranslation();
  const days = t('common.days', { defaultValue: 'days' });
  return (
    <tr className="align-top">
      <td className="px-3 py-2">
        <div className="font-medium text-content-primary">
          {row.wbs_code ? `${row.wbs_code} ` : ''}
          {row.name}
        </div>
        <Badge variant={row.change_type === 'added' ? 'success' : row.change_type === 'removed' ? 'error' : 'warning'}>
          {t(`schedule.compare.change_${row.change_type}`, { defaultValue: row.change_type })}
        </Badge>
      </td>
      <td className="px-3 py-2 tabular-nums text-content-secondary">
        {row.finish_before ?? '-'} / {row.finish_after ?? '-'}
      </td>
      <td className={`px-3 py-2 text-end tabular-nums ${TONE_CLS[deltaTone(row.finish_movement_days)]}`}>
        {row.finish_movement_days ? `${signedDays(row.finish_movement_days)} ${days}` : ''}
      </td>
      <td className="px-3 py-2 text-end tabular-nums text-content-secondary">
        {row.duration_delta_days !== null && row.duration_delta_days !== 0
          ? `${row.duration_before} → ${row.duration_after}`
          : ''}
      </td>
      <td className={`px-3 py-2 text-end tabular-nums ${TONE_CLS[deltaTone(row.cost_delta)]}`}>
        {money(row.cost_delta, currency, true)}
      </td>
      <td className="px-3 py-2">
        {row.positions.length === 0 ? (
          <span className="inline-flex items-center gap-1 text-content-tertiary">
            <Link2Off size={12} />
            {t('schedule.impact.unlinked', { defaultValue: 'Not linked to the BOQ' })}
          </span>
        ) : (
          <ul className="space-y-1">
            {row.positions.map((p) => (
              <li key={p.id}>
                {p.missing ? (
                  <span className="text-content-tertiary">
                    {t('schedule.impact.position_missing', { defaultValue: 'Position no longer in the BOQ' })}
                  </span>
                ) : (
                  <span className="text-content-primary">
                    <span className="font-mono">{p.ordinal}</span> {p.description}{' '}
                    <span className="tabular-nums text-content-tertiary">{money(p.total, currency)}</span>
                  </span>
                )}
                {p.variations.map((v) => (
                  <Badge key={v.id} variant="blue" className="ms-1">
                    {v.code}
                  </Badge>
                ))}
              </li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

export default RevisionImpactCard;
