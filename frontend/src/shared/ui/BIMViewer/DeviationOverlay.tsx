// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DeviationOverlay - scan-vs-design deviation legend for the BIM viewer.
 *
 * When a laser scan has been aligned to the open design model, the point-cloud
 * backend has already computed how far the as-built deviates from the design.
 * This overlay surfaces that verdict as a colour legend + headline banner in
 * the viewer's bottom-left corner (the colour-by / 5D legends live
 * bottom-right, so the two never collide). It renders nothing when no scan is
 * aligned to the model - the common case - so it is safe to always mount.
 *
 * It does NOT recompute any deviation; it only fetches and paints the result
 * via {@link fetchModelDeviation} and the pure {@link buildDeviationLegend} /
 * {@link deviationHeadline} derivations.
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  buildDeviationLegend,
  deviationHeadline,
  fetchModelDeviation,
  formatDeviationRms,
} from './deviationData';

export interface DeviationOverlayProps {
  projectId: string;
  modelId: string;
  /** Hide the overlay (e.g. while another full-screen overlay is active). */
  disabled?: boolean;
}

export function DeviationOverlay({
  projectId,
  modelId,
  disabled = false,
}: DeviationOverlayProps) {
  const { t } = useTranslation();

  const { data: summary } = useQuery({
    queryKey: ['bim-model-deviation', projectId, modelId],
    queryFn: () => fetchModelDeviation(projectId, modelId),
    enabled: !disabled && !!projectId && !!modelId,
    // Deviation results change only when a new scan is registered/aligned, so
    // they're effectively static for a viewing session - don't refetch on
    // window focus and keep them fresh for a few minutes.
    staleTime: 5 * 60_000,
    // A missing pointcloud module / no-permission is not an error worth a
    // retry storm; the overlay simply stays hidden.
    retry: false,
  });

  const rows = buildDeviationLegend(summary, t);
  if (disabled || rows.length === 0 || !summary) return null;

  // Show up to a few per-scan RMS detail lines under the legend so the
  // estimator can see the actual residual, not just the colour band. Capped
  // so a model aligned to many scans never overgrows the overlay.
  const MAX_DETAIL = 3;
  const detail = summary.items
    .map((it) => ({ key: it.registration_id, rms: formatDeviationRms(it), sev: it.severity }))
    .filter((d) => d.rms)
    .slice(0, MAX_DETAIL);
  const hiddenDetail = Math.max(0, summary.items.length - detail.length);

  return (
    <div
      className="absolute bottom-3 start-3 z-20 flex max-w-[240px] flex-col gap-1 rounded-lg border border-border-light bg-surface-primary/95 px-3 py-2 shadow-sm backdrop-blur-sm"
      data-testid="bim-deviation-overlay"
    >
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm border border-black/10"
          style={{ background: summary.worst_severity_color }}
        />
        <span className="text-[11px] font-semibold text-content-primary">
          {deviationHeadline(summary, t)}
        </span>
      </div>
      <span className="text-[10px] font-semibold uppercase tracking-wide text-content-tertiary">
        {t('bim.deviation_legend_title', {
          defaultValue: 'Scan vs design',
        })}
      </span>
      <ul className="flex flex-col gap-0.5">
        {rows.map((row) => (
          <li
            key={row.severity}
            className="flex items-center gap-1.5 text-[11px] text-content-secondary"
          >
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm border border-black/10"
              style={{ background: row.hex }}
            />
            <span className="truncate" title={row.label}>
              {row.label}
            </span>
            <span className="ms-auto tabular-nums text-content-tertiary">
              {row.count}
            </span>
          </li>
        ))}
      </ul>
      {detail.length > 0 && (
        <ul className="mt-0.5 flex flex-col gap-0.5 border-t border-border-light/60 pt-1">
          {detail.map((d) => (
            <li
              key={d.key}
              className="flex items-center gap-1.5 text-[10px] text-content-tertiary"
              title={d.rms ?? undefined}
            >
              <span className="truncate">{d.rms}</span>
            </li>
          ))}
          {hiddenDetail > 0 && (
            <li className="text-[10px] italic text-content-tertiary">
              {t('bim.deviation_more_scans', {
                defaultValue: '+{{count}} more scan(s)',
                count: hiddenDetail,
              })}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
