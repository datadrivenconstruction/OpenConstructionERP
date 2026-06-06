import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ExternalLink, Loader2, LineChart } from 'lucide-react';

import { SideDrawer, EmptyState } from '@/shared/ui';

import type { ControlsKPI } from './api';
import { useControlsDrill } from './api';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Humanise a snake_case field key, e.g. ``planned_value`` -> ``Planned value``. */
function humanizeKey(key: string): string {
  const spaced = key.replace(/_/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Title for a drill record. Prefers a real label; never shows a bare UUID. */
function recordTitle(
  fields: Record<string, unknown>,
  kind: string,
  idx: number,
): string {
  const named =
    (fields['title'] as string) ||
    (fields['name'] as string) ||
    (fields['code'] as string) ||
    (fields['po_number'] as string) ||
    (fields['ncr_number'] as string) ||
    (fields['incident_number'] as string);
  if (named && named.trim()) return named;
  // Fall back to a humanised "kind #n" rather than leaking a raw UUID, so a
  // row whose owning module didn't supply a display name still reads cleanly.
  const kindLabel = kind ? humanizeKey(kind) : 'Record';
  return `${kindLabel} #${idx + 1}`;
}

/**
 * Opens on tile click and fetches the underlying source rows behind a KPI.
 * Each row that maps to an owning module renders a deep link so a click
 * jumps straight to the source record (e.g. a pending variation -> /variations).
 */
export function DrillDrawer({
  kpi,
  projectId,
  open,
  onClose,
}: {
  kpi: ControlsKPI | null;
  projectId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const drillQ = useControlsDrill(kpi?.code ?? null, projectId, open);

  const records = drillQ.data?.records ?? [];

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title={kpi?.label ?? t('controls.drill_title', { defaultValue: 'Details' })}
      subtitle={
        kpi
          ? t('controls.drill_subtitle', {
              defaultValue: '{{n}} source records',
              n: drillQ.data?.record_count ?? 0,
            })
          : undefined
      }
      headerActions={
        kpi ? (
          <Link
            to="/bi-dashboards"
            onClick={onClose}
            className="flex items-center gap-1.5 rounded-md border border-border-subtle px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            title={t('controls.drill_trend_alerts_tip', {
              defaultValue: 'See this KPI trend over time and configure threshold alerts in BI Dashboards',
            })}
          >
            <LineChart className="h-3.5 w-3.5" />
            {t('controls.drill_trend_alerts', { defaultValue: 'Trend & alerts' })}
          </Link>
        ) : undefined
      }
    >
      {drillQ.isLoading ? (
        <div className="flex items-center gap-2 p-4 text-sm text-content-tertiary">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading…' })}
        </div>
      ) : records.length === 0 ? (
        <EmptyState
          title={t('controls.drill_empty', {
            defaultValue: 'No underlying records',
          })}
        />
      ) : (
        <div className="flex flex-col gap-2 p-1">
          {records.map((rec, idx) => {
            const fields = rec.fields;
            const kind = String(fields['kind'] ?? '');
            const title = recordTitle(fields, kind, idx);
            return (
              <div
                key={(fields['id'] as string) ?? idx}
                className="rounded-md border border-border-subtle bg-surface-secondary p-2.5"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-content-primary">
                    {title}
                  </span>
                  {rec.deep_link && (
                    <Link
                      to={rec.deep_link}
                      onClick={onClose}
                      className="flex items-center gap-1 text-xs text-accent hover:underline"
                    >
                      {t('controls.open', { defaultValue: 'Open' })}
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  )}
                </div>
                <dl className="mt-1.5 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-2xs text-content-tertiary">
                  {Object.entries(fields)
                    .filter(
                      ([k, v]) =>
                        k !== 'id' &&
                        k !== 'kind' &&
                        k !== 'project_id' &&
                        // Hide empty values and any bare UUID id-like field so
                        // the row stays readable instead of dumping raw keys.
                        v != null &&
                        String(v).trim() !== '' &&
                        !UUID_RE.test(String(v)),
                    )
                    .map(([k, v]) => (
                      <div key={k} className="contents">
                        <dt className="font-medium">{humanizeKey(k)}</dt>
                        <dd className="truncate tabular-nums">{String(v)}</dd>
                      </div>
                    ))}
                </dl>
              </div>
            );
          })}
        </div>
      )}
    </SideDrawer>
  );
}
