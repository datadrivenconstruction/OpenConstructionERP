// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Inventory Heatmap (task #140) - groups Plots by Phase → Block.
 *
 * Each cell is one Plot, coloured by status. Layout follows
 * ``Phase.sequence`` then ``Block.code``. Legacy plots (no block_id)
 * surface in a synthetic "Legacy" phase as a fallback.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import type {
  HeatmapBlock,
  HeatmapPhase,
  HeatmapUnit,
  InventoryHeatmapResponse,
} from '../api';
import { getInventoryHeatmap } from '../api';
import {
  DashboardEmpty,
  DashboardError,
  DashboardSkeleton,
  PLOT_STATUS_FILL,
  PLOT_STATUS_STROKE,
  StatusLegend,
  num,
} from './_shared';
import { fmtFixed } from '@/shared/lib/formatters';

interface InventoryHeatmapProps {
  developmentId: string;
  onUnitClick?: (unit: HeatmapUnit) => void;
}

export function InventoryHeatmap({
  developmentId,
  onUnitClick,
}: InventoryHeatmapProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<InventoryHeatmapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reloadKey, setReloadKey] = useState(0);
  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getInventoryHeatmap(developmentId)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'Failed to load heatmap');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [developmentId, reloadKey]);

  const totalUnits = data?.total_units ?? 0;

  const summary = useMemo(() => {
    if (!data) return null;
    const sc = data.status_counts ?? {};
    return Object.entries(sc).sort(([, a], [, b]) => b - a);
  }, [data]);

  if (loading) return <DashboardSkeleton variant="bars" rows={6} />;
  if (error)
    return (
      <DashboardError
        title={t('propdev.dashboards.heatmap.error', {
          defaultValue: 'Could not load inventory heatmap',
        })}
        message={error}
        onRetry={refetch}
      />
    );
  if (!data || totalUnits === 0)
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.heatmap.empty_title', {
          defaultValue: 'No plots yet',
        })}
        description={t('propdev.dashboards.heatmap.empty_desc', {
          defaultValue: 'Add plots to a Block under a Phase to see them here.',
        })}
      />
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('propdev.dashboards.heatmap.title', {
              defaultValue: 'Inventory heatmap',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('propdev.dashboards.heatmap.subtitle', {
              defaultValue: 'Plots by Phase → Block, coloured by status.',
            })}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-content-tertiary">
          <span>
            {t('propdev.dashboards.heatmap.units_total', {
              defaultValue: '{{count}} units',
              count: totalUnits,
            })}
          </span>
        </div>
      </div>

      <StatusLegend />

      {summary && summary.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {summary.map(([status, count]) => (
            <span
              key={status}
              className="inline-flex items-center gap-1.5 rounded-full bg-surface-secondary px-2.5 py-1 text-xs text-content-secondary"
              style={{ borderLeft: `3px solid ${PLOT_STATUS_FILL[status] ?? '#94a3b8'}` }}
            >
              <span className="font-medium">{count}</span>
              <span>
                {t(`propdev.status.${status}`, {
                  defaultValue: status.replace(/_/g, ' '),
                })}
              </span>
            </span>
          ))}
        </div>
      )}

      <div className="space-y-5">
        {data.phases.map((phase) => (
          <PhaseRow
            key={phase.phase_id ?? `legacy-${phase.code}`}
            phase={phase}
            onUnitClick={onUnitClick}
          />
        ))}
      </div>
    </div>
  );
}

function PhaseRow({
  phase,
  onUnitClick,
}: {
  phase: HeatmapPhase;
  onUnitClick?: (unit: HeatmapUnit) => void;
}) {
  const { t } = useTranslation();
  const unitCount = phase.blocks.reduce((acc, b) => acc + b.units.length, 0);
  return (
    <section
      aria-label={t('propdev.dashboards.heatmap.phase', {
        defaultValue: 'Phase {{name}}',
        name: phase.name || phase.code,
      })}
      className="rounded-xl border border-divider/60 bg-surface-primary p-3"
    >
      <header className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs font-medium text-content-secondary">
              {phase.code}
            </span>
            <h4 className="text-sm font-semibold text-content-primary">
              {phase.name || phase.code}
            </h4>
          </div>
          <p className="text-2xs text-content-tertiary">
            {t('propdev.dashboards.heatmap.phase_meta', {
              defaultValue: 'Sequence {{seq}} • {{count}} units',
              seq: phase.sequence,
              count: unitCount,
            })}
          </p>
        </div>
      </header>
      <div className="space-y-3">
        {phase.blocks.map((block) => (
          <BlockRow
            key={block.block_id ?? `${phase.phase_id ?? 'l'}-${block.code}`}
            block={block}
            onUnitClick={onUnitClick}
          />
        ))}
      </div>
    </section>
  );
}

function BlockRow({
  block,
  onUnitClick,
}: {
  block: HeatmapBlock;
  onUnitClick?: (unit: HeatmapUnit) => void;
}) {
  const { t } = useTranslation();
  // Group units by level_in_block for a per-level row layout when available.
  const byLevel = useMemo(() => {
    const map = new Map<number | null, HeatmapUnit[]>();
    for (const u of block.units) {
      const k = u.level_in_block ?? null;
      const list = map.get(k) ?? [];
      list.push(u);
      map.set(k, list);
    }
    return Array.from(map.entries()).sort(([a], [b]) => {
      if (a === null && b === null) return 0;
      if (a === null) return 1;
      if (b === null) return -1;
      return (b as number) - (a as number); // higher floor first
    });
  }, [block.units]);

  return (
    <div className="rounded-xl border border-divider/40 bg-surface-secondary/40 p-2">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="rounded bg-surface-primary px-1.5 py-0.5 text-2xs font-medium text-content-secondary">
            {block.code}
          </span>
          <span className="text-xs font-medium text-content-primary">
            {block.name || block.code}
          </span>
        </div>
        <span className="text-2xs text-content-tertiary">
          {t('propdev.dashboards.heatmap.block_meta', {
            defaultValue: '{{levels}} levels • {{count}} units',
            levels: block.levels_count,
            count: block.units.length,
          })}
        </span>
      </div>
      <div className="space-y-1.5">
        {byLevel.map(([level, units]) => (
          <div key={String(level)} className="flex items-center gap-1">
            <span
              className="w-7 shrink-0 text-right text-2xs text-content-tertiary"
              aria-label={
                level === null
                  ? t('propdev.dashboards.heatmap.no_level', {
                      defaultValue: 'No level',
                    })
                  : t('propdev.dashboards.heatmap.level', {
                      defaultValue: 'Level {{level}}',
                      level,
                    })
              }
            >
              {level === null ? '—' : level}
            </span>
            <div className="flex flex-wrap gap-1">
              {units.map((u) => (
                <UnitCell key={u.plot_id} unit={u} onClick={onUnitClick} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function UnitCell({
  unit,
  onClick,
}: {
  unit: HeatmapUnit;
  onClick?: (unit: HeatmapUnit) => void;
}) {
  const { t } = useTranslation();
  const dq = useDisplayQuantity();
  const fill = PLOT_STATUS_FILL[unit.status] ?? '#94a3b8';
  const stroke = PLOT_STATUS_STROKE[unit.status] ?? '#64748b';
  const area = dq.convert(num(unit.area_m2), 'm²');
  const label = t('propdev.dashboards.heatmap.cell_label_u', {
    defaultValue: 'Plot {{number}}, {{status}}, {{area}} {{unit}}',
    number: unit.plot_number,
    status: t(`propdev.status.${unit.status}`, {
      defaultValue: unit.status.replace(/_/g, ' '),
    }),
    area: fmtFixed(area.value, 0),
    unit: area.unit,
  });
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={() => onClick?.(unit)}
      className="h-7 w-9 cursor-pointer rounded-md border text-2xs font-medium text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-1"
      style={{ backgroundColor: fill, borderColor: stroke }}
    >
      {unit.plot_number.slice(-3)}
    </button>
  );
}
