// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RfiTurnaroundCard - compact dashboard widget summarising RFI (request
 * for information) turnaround for the active project.
 *
 * Shows the open count as the headline number, how many of those are
 * overdue (amber when 1+, rose when it climbs), and the average number of
 * days to a response.
 *
 * Self-hides (returns null) when there is no active project, while the
 * stats are loading, or when the project has zero RFIs, so a fresh
 * install never shows an empty card.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, InfoHint } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchRFIStats } from '@/features/rfi/api';
import { KpiStrip } from './KpiStrip';
import { getNumberLocale } from '@/stores/usePreferencesStore';

function formatCount(value: number): string {
  if (!Number.isFinite(value)) return '-';
  // Read on each call. A formatter built once at module scope keeps the
  // language the chunk loaded in, and the header switcher does not reload.
  return value.toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 });
}

function formatDays(value: number | null | undefined): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  // Days to response is a small figure, so one decimal keeps sub-day
  // turnarounds honest while staying readable.
  const rounded = Math.round(value * 10) / 10;
  return rounded.toLocaleString(getNumberLocale(), { maximumFractionDigits: 1 });
}

export function RfiTurnaroundCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  const { data, isLoading } = useQuery({
    queryKey: ['rfi', 'stats', projectId],
    queryFn: () => fetchRFIStats(projectId),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  });

  // Hide entirely on no-project / loading / no-RFIs so the dashboard
  // stays clean for projects that have not raised any RFIs yet.
  if (!projectId) return null;
  if (isLoading) return null;
  if (!data || data.total <= 0) return null;

  const openCount = data.open;
  const overdueCount = data.overdue;
  const avgDays = formatDays(data.avg_days_to_response);

  return (
    <Card className="h-full">
      <CardHeader
        title={t('dashboard.rfi_title', { defaultValue: 'RFI turnaround' })}
        subtitle={t('dashboard.rfi_subtitle', {
          defaultValue: 'How quickly requests for information get answered',
        })}
        action={
          <button
            type="button"
            onClick={() => navigate('/rfi')}
            className="text-xs text-oe-blue hover:underline"
          >
            {t('dashboard.rfi_open', { defaultValue: 'Open RFIs' })}
          </button>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            {
              label: t('dashboard.rfi_open_count', { defaultValue: 'Open' }),
              value: formatCount(openCount),
            },
            {
              label: t('dashboard.rfi_overdue', { defaultValue: 'Overdue' }),
              value: formatCount(overdueCount),
              tone: overdueCount > 0 ? 'text-amber-600' : 'text-content-secondary',
            },
            {
              label: t('dashboard.rfi_avg_label', { defaultValue: 'Avg days' }),
              value: avgDays === null ? '-' : avgDays,
              tone: 'text-content-secondary',
            },
          ]}
        />
        <InfoHint
          className="mt-3"
          text={t('dashboard.rfi_help', {
            defaultValue:
              'Open counts RFIs that are still waiting for an answer. Overdue are the open ones already past their response date, and turn amber the moment one appears. The average is the response time across RFIs that have been answered, measured in days.',
          })}
        />
      </CardContent>
    </Card>
  );
}

export default RfiTurnaroundCard;
