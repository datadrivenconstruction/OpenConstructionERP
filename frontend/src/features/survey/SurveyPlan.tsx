// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan view of the survey on the shared plan canvas (features/survey-plan):
 * points on the project grid, surface outlines, breaklines and the cut/fill
 * heat map. A local grid draws on the paper style instead of being refused.
 */

import { lazy, Suspense, useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { Feature, FeatureCollection, Geometry, Position } from 'geojson';
import { Map as MapIcon } from 'lucide-react';
import { EmptyState, ErrorState, Skeleton } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { layer } from '@/features/survey-plan/planLayers';
import type { PlanFeature, PlanGeometry, PlanLayerSpec } from '@/features/survey-plan/types';
import type { SurveyPlan as Plan } from './volumesApi';

const PlanCanvas = lazy(() => import('@/features/survey-plan/PlanCanvas'));

/** Hex cut/fill colours for screens outside the map (staged panel). */
export const CUT_COLOUR = '#c2410c';
export const FILL_COLOUR = '#1d4ed8';
export const PLAN_LAYERS = ['points', 'surfaces', 'breaklines', 'heat'] as const;
export type PlanLayer = (typeof PLAN_LAYERS)[number];

const xy = (c: Position): [number, number] => [c[0]!, c[1]!];

/** A served geometry already in grid metres (local grid) as plan geometries. */
function gridGeometries(g: Geometry): PlanGeometry[] {
  switch (g.type) {
    case 'Point':
      return [{ type: 'Point', coordinates: xy(g.coordinates) }];
    case 'LineString':
      return [{ type: 'LineString', coordinates: g.coordinates.map(xy) }];
    case 'MultiLineString':
      return g.coordinates.map((l) => ({ type: 'LineString' as const, coordinates: l.map(xy) }));
    case 'Polygon':
      return [{ type: 'Polygon', coordinates: g.coordinates.map((r) => r.map(xy)) }];
    case 'MultiPolygon':
      return g.coordinates.map((p) => ({ type: 'Polygon' as const, coordinates: p.map((r) => r.map(xy)) }));
    default:
      return [];
  }
}

/** Split the served collection into canvas layers; points always go by their grid E/N. */
export function planLayerSpecs(plan: Plan): PlanLayerSpec[] {
  const local = !!plan.properties?.local_grid;
  const byLayer = new Map<string, Feature[]>();
  for (const f of plan.features) {
    const id = String(f.properties?.layer ?? '');
    byLayer.set(id, [...(byLayer.get(id) ?? []), f]);
  }
  const out: PlanLayerSpec[] = [];
  const points: PlanFeature[] = (byLayer.get('points') ?? []).flatMap((f) => {
    const p = f.properties ?? {};
    if (typeof p.e !== 'number' || typeof p.n !== 'number') return [];
    const label = String(p.id ?? '');
    return [
      {
        id: `pt:${label}`,
        layer: 'points',
        geometry: { type: 'Point', coordinates: p.z == null ? [p.e, p.n] : [p.e, p.n, Number(p.z)] },
        properties: { label, kind: p.kind ?? null, code: p.code ?? null },
      },
    ];
  });
  if (points.length > 0) out.push(layer('points', points));
  for (const id of ['surfaces', 'breaklines', 'heat'] as const) {
    const feats = byLayer.get(id) ?? [];
    if (feats.length === 0) continue;
    if (local) {
      const grid: PlanFeature[] = feats.flatMap((f, i) =>
        gridGeometries(f.geometry).map((geometry, j) => ({ id: `${id}:${i}:${j}`, layer: id, geometry, properties: { ...(f.properties ?? {}) } })),
      );
      out.push(layer(id, grid));
    } else {
      const fc: FeatureCollection = { type: 'FeatureCollection', features: feats };
      out.push(layer(id, [], { viewFeatures: fc }));
    }
  }
  return out;
}

interface Props {
  plan: Plan | undefined;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  showLegend?: boolean;
  /** Export controls the page puts at the end of the toolbar. */
  exportSlot?: ReactNode;
  /** Defaults to the active project. */
  projectId?: string;
}

export function SurveyPlan({ plan, isLoading, error, onRetry, showLegend = false, exportSlot, projectId }: Props) {
  const { t } = useTranslation();
  const active = useProjectContextStore((s) => s.activeProjectId);
  const pid = projectId ?? active ?? '';
  const layers = useMemo(() => (plan ? planLayerSpecs(plan) : []), [plan]);

  if (isLoading) return <Skeleton className="h-96" />;
  if (error) return <ErrorState title={t('survey.plan.error', { defaultValue: 'The plan could not be loaded.' })} onRetry={onRetry} />;
  if (!plan || plan.features.length === 0 || !pid) {
    return (
      <EmptyState
        icon={<MapIcon size={24} />}
        title={t('survey.plan.empty', { defaultValue: 'Nothing to draw yet: import points or add a surface.' })}
      />
    );
  }
  const legend = showLegend ? (
    <span className="inline-flex items-center gap-2 text-xs text-content-secondary">
      <span className="inline-flex items-center gap-1">
        <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: 'var(--oe-map-cut-2)' }} aria-hidden />
        {t('volumes.field.cut', { defaultValue: 'Cut' })}
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: 'var(--oe-map-fill-2)' }} aria-hidden />
        {t('volumes.field.fill', { defaultValue: 'Fill' })}
      </span>
    </span>
  ) : null;
  return (
    <div data-testid="survey-plan">
      <Suspense fallback={<Skeleton className="h-[32rem]" />}>
        <PlanCanvas
          projectId={pid}
          layers={layers}
          editable={false}
          inspector={false}
          testId="survey-plan-canvas"
          toolbarSlot={
            legend || exportSlot ? (
              <span className="flex items-center gap-3">
                {legend}
                {exportSlot}
              </span>
            ) : undefined
          }
        />
      </Suspense>
    </div>
  );
}
