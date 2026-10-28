// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// <GeneratedReportsHistory> — recent reports panel for /reports.
// Wave V_REPORTING audit closed a gap: backend already persists every
// render via GET /api/v1/reporting/reports/?project_id=X
// (router.list_reports) but the UI never surfaced the history.
// IDOR-safe by construction — endpoint gated by verify_project_access.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Clock, FileText } from 'lucide-react';

import { apiGet } from '@/shared/lib/api';
import { DateDisplay, EmptyState, Skeleton } from '@/shared/ui';

interface GeneratedReportRow {
  id: string;
  report_type: string;
  title: string;
  format: string;
  created_at: string;
}

export interface GeneratedReportsHistoryProps {
  projectId: string;
}

export function GeneratedReportsHistory({ projectId }: GeneratedReportsHistoryProps) {
  const { t } = useTranslation();
  const { data: rows = [], isLoading } = useQuery<GeneratedReportRow[]>({
    queryKey: ['reporting', 'history', projectId],
    queryFn: () =>
      apiGet<GeneratedReportRow[]>(
        `/v1/reporting/reports/?project_id=${projectId}&limit=10`,
      ),
    enabled: !!projectId,
    staleTime: 15_000,
  });

  if (!projectId) return null;

  return (
    <section
      aria-labelledby="reports-history-heading"
      className="rounded-xl border border-border-light bg-surface-primary p-5 shadow-sm"
      data-testid="generated-reports-history"
    >
      <div className="mb-3 flex items-center gap-2">
        <Clock size={16} className="text-content-tertiary" aria-hidden="true" />
        <h2 id="reports-history-heading" className="text-sm font-semibold text-content-primary">
          {t('reports.history_title', { defaultValue: 'Recently generated reports' })}
        </h2>
      </div>

      {isLoading ? (
        <div className="space-y-2" data-testid="history-skeleton">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 w-full rounded-md" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Clock size={24} />}
          title={t('reports.history_empty_title', { defaultValue: 'No reports generated yet' })}
          description={t('reports.history_empty_desc', {
            defaultValue: 'Generated reports for this project will appear here.',
          })}
        />
      ) : (
        <ul className="divide-y divide-border-light" data-testid="history-list">
          {rows.map((row) => (
            <li key={row.id} className="flex items-center gap-3 py-2.5" data-testid="history-row">
              <FileText size={16} className="shrink-0 text-content-tertiary" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-content-primary">{row.title}</p>
                <p className="text-xs text-content-tertiary">
                  {row.report_type}
                  {' · '}
                  <DateDisplay value={row.created_at} format="relative" />
                </p>
              </div>
              <span className="rounded-md bg-surface-secondary px-2 py-0.5 text-2xs font-medium uppercase text-content-secondary">
                {(row.format || 'pdf').toLowerCase()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
