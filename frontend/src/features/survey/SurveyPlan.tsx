// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan view of the survey: points, surface outlines and a cut/fill heat map,
 * on the shared MapLibre viewer. The backend serves WGS 84; a local grid has
 * no place on the earth, so it gets a note instead of a wrong map. The toolbar
 * measures distance and area, snaps to survey points and switches layers.
 */

import { lazy, Suspense, useCallback, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Map as MapIcon, Pentagon, Ruler, X } from 'lucide-react';
import { Button, EmptyState, ErrorState, Skeleton } from '@/shared/ui';
import { fmtFixed } from '@/shared/lib/formatters';
import type { GeoJsonLayer } from '@/features/geo-hub/MapLibreViewer';
import type { BasemapId } from '@/features/geo-hub/mapStyles';
import type { SurveyPlan as Plan } from './volumesApi';
import { measure, measureFeatures, snapToPoint, type Vertex } from './planMeasure';

const MapLibreViewer = lazy(() => import('@/features/geo-hub/MapLibreViewer'));

export const CUT_COLOUR = '#c2410c';
export const FILL_COLOUR = '#1d4ed8';
export const PLAN_LAYERS = ['points', 'surfaces', 'breaklines', 'heat'] as const;
export type PlanLayer = (typeof PLAN_LAYERS)[number];
const SNAP_RADIUS_M = 3;

/** Split one served collection into the viewer's styled layers. */
export function planLayers(plan: Plan, hidden: ReadonlySet<string> = new Set()): GeoJsonLayer[] {
  // Hidden layers keep their data so the map does not refit when one is switched off.
  const vis = (layer: string) => ({ visibility: hidden.has(layer) ? ('none' as const) : ('visible' as const) });
  const pick = (layer: string) => ({
    type: 'FeatureCollection' as const,
    features: plan.features.filter((f) => f.properties?.layer === layer),
  });
  return [
    {
      id: 'heat',
      data: pick('heat'),
      layers: [
        {
          id: 'survey-heat',
          type: 'fill',
          layout: vis('heat'),
          paint: {
            'fill-color': ['match', ['get', 'side'], 'cut', CUT_COLOUR, 'fill', FILL_COLOUR, '#94a3b8'],
            'fill-opacity': ['min', 0.85, ['+', 0.2, ['/', ['abs', ['get', 'dh']], 2]]],
          },
        },
      ],
    },
    {
      id: 'surfaces',
      data: pick('surfaces'),
      layers: [{ id: 'survey-surfaces', type: 'line', layout: vis('surfaces'), paint: { 'line-color': '#0f766e', 'line-width': 2 } }],
    },
    {
      id: 'breaklines',
      data: pick('breaklines'),
      layers: [
        {
          id: 'survey-breaklines',
          type: 'line',
          layout: vis('breaklines'),
          paint: { 'line-color': '#b45309', 'line-width': 2, 'line-dasharray': [2, 1] },
        },
      ],
    },
    {
      id: 'points',
      data: pick('points'),
      layers: [
        {
          id: 'survey-points',
          type: 'circle',
          layout: vis('points'),
          paint: {
            'circle-radius': ['match', ['get', 'kind'], 'control', 6, 'benchmark', 6, 3],
            'circle-color': ['match', ['get', 'kind'], 'control', '#dc2626', 'benchmark', '#7c3aed', '#111827'],
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 1,
          },
        },
      ],
    },
  ];
}

interface Props {
  plan: Plan | undefined;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  showLegend?: boolean;
  /** Export controls the page puts at the end of the toolbar. */
  exportSlot?: ReactNode;
}

export function SurveyPlan({ plan, isLoading, error, onRetry, showLegend = false, exportSlot }: Props) {
  const { t } = useTranslation();
  const [basemap, setBasemap] = useState<BasemapId>('streets');
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [tool, setTool] = useState<'none' | 'distance' | 'area'>('none');
  const [snap, setSnap] = useState(true);
  const [vertices, setVertices] = useState<Vertex[]>([]);
  const closed = tool === 'area';
  const pointFeatures = useMemo(() => (plan?.features ?? []).filter((f) => f.properties?.layer === 'points'), [plan]);
  const present = useMemo(() => new Set((plan?.features ?? []).map((f) => String(f.properties?.layer ?? ''))), [plan]);
  const layers = useMemo(() => {
    if (!plan) return [];
    const base = planLayers(plan, hidden);
    if (vertices.length === 0) return base;
    const data = { type: 'FeatureCollection' as const, features: measureFeatures(vertices, closed) };
    return [
      ...base,
      {
        id: 'measure',
        data,
        layers: [
          { id: 'survey-measure-fill', type: 'fill' as const, filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.2 } },
          { id: 'survey-measure-line', type: 'line' as const, paint: { 'line-color': '#f59e0b', 'line-width': 2 } },
          { id: 'survey-measure-pts', type: 'circle' as const, filter: ['==', '$type', 'Point'], paint: { 'circle-radius': 4, 'circle-color': '#f59e0b' } },
        ],
      } as GeoJsonLayer,
    ];
  }, [plan, hidden, vertices, closed]);
  const onMapClick = useCallback(
    (c: { lat: number; lon: number }) => {
      const v: Vertex = { lon: c.lon, lat: c.lat };
      setVertices((prev) => [...prev, snap ? snapToPoint(v, pointFeatures, SNAP_RADIUS_M) : v]);
    },
    [snap, pointFeatures],
  );
  const result = vertices.length >= 2 ? measure(vertices, closed) : null;
  const pickTool = (next: 'distance' | 'area') => {
    setTool((cur) => (cur === next ? 'none' : next));
    setVertices([]);
  };
  const toggleLayer = (layer: string) =>
    setHidden((prev) => {
      const out = new Set(prev);
      if (out.has(layer)) out.delete(layer);
      else out.add(layer);
      return out;
    });

  if (isLoading) return <Skeleton className="h-96" />;
  if (error) return <ErrorState title={t('survey.plan.error', { defaultValue: 'The plan could not be loaded.' })} onRetry={onRetry} />;
  if (!plan || plan.features.length === 0) {
    return (
      <EmptyState
        icon={<MapIcon size={24} />}
        title={t('survey.plan.empty', { defaultValue: 'Nothing to draw yet: import points or add a surface.' })}
      />
    );
  }
  if (plan.properties?.local_grid) {
    return (
      <EmptyState
        icon={<MapIcon size={24} />}
        title={t('survey.plan.local_grid', {
          defaultValue: 'This project uses a local grid, which has no place on a map. Set an EPSG code to see the plan.',
        })}
      />
    );
  }
  return (
    <div className="space-y-2" data-testid="survey-plan">
      <div className="flex flex-wrap items-center gap-3 text-xs text-content-secondary">
        <select
          className="oe-input w-36"
          value={basemap}
          onChange={(e) => setBasemap(e.target.value as BasemapId)}
          aria-label={t('survey.plan.basemap', { defaultValue: 'Basemap' })}
        >
          <option value="streets">{t('survey.plan.basemap_streets', { defaultValue: 'Streets' })}</option>
          <option value="paper">{t('survey.plan.basemap_paper', { defaultValue: 'Paper (offline)' })}</option>
        </select>
        {showLegend && (
          <>
            <span className="inline-flex items-center gap-1">
              <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: CUT_COLOUR }} aria-hidden />
              {t('volumes.field.cut', { defaultValue: 'Cut' })}
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: FILL_COLOUR }} aria-hidden />
              {t('volumes.field.fill', { defaultValue: 'Fill' })}
            </span>
          </>
        )}
        <span>
          <bdi dir="ltr">{plan.properties?.epsg ? `EPSG ${plan.properties.epsg}` : ''}</bdi>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs" role="toolbar" aria-label={t('survey.plan.toolbar', { defaultValue: 'Plan tools' })} data-testid="survey-plan-toolbar">
        <Button size="sm" variant={tool === 'distance' ? 'primary' : 'secondary'} icon={<Ruler size={14} />} onClick={() => pickTool('distance')} aria-pressed={tool === 'distance'}>
          {t('survey.plan.measure_distance', { defaultValue: 'Distance' })}
        </Button>
        <Button size="sm" variant={tool === 'area' ? 'primary' : 'secondary'} icon={<Pentagon size={14} />} onClick={() => pickTool('area')} aria-pressed={tool === 'area'}>
          {t('survey.plan.measure_area', { defaultValue: 'Area' })}
        </Button>
        <label className="inline-flex items-center gap-1">
          <input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)} />
          {t('survey.plan.snap', { defaultValue: 'Snap to points' })}
        </label>
        <span className="mx-1 h-4 border-s border-border-light" aria-hidden />
        {PLAN_LAYERS.filter((l) => present.has(l)).map((l) => (
          <label key={l} className="inline-flex items-center gap-1">
            <input type="checkbox" checked={!hidden.has(l)} onChange={() => toggleLayer(l)} />
            {t(`survey.plan.layer_${l}`, { defaultValue: l })}
          </label>
        ))}
        {exportSlot && <span className="ms-auto">{exportSlot}</span>}
      </div>
      {tool !== 'none' && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-surface-secondary px-3 py-2 text-sm" data-testid="survey-measure-result">
          {result ? (
            <>
              <span>
                {t('survey.plan.length', { defaultValue: 'Length' })}: <bdi dir="ltr" className="font-mono">{fmtFixed(result.distance_m, 3)} m</bdi>
              </span>
              {result.area_m2 != null && (
                <span>
                  {t('survey.plan.area', { defaultValue: 'Area' })}: <bdi dir="ltr" className="font-mono">{fmtFixed(result.area_m2, 2)} m²</bdi>
                </span>
              )}
              <span className="text-xs text-content-tertiary">
                {result.exact
                  ? t('survey.plan.exact', { defaultValue: 'On the project grid, from snapped points' })
                  : t('survey.plan.approx', { defaultValue: 'Approximate, measured on the map' })}
              </span>
            </>
          ) : (
            <span className="text-content-secondary">{t('survey.plan.click_hint', { defaultValue: 'Click on the map to add points.' })}</span>
          )}
          {vertices.length > 0 && (
            <Button size="sm" variant="ghost" icon={<X size={14} />} onClick={() => setVertices([])}>
              {t('survey.plan.clear', { defaultValue: 'Clear' })}
            </Button>
          )}
        </div>
      )}
      <div className="h-[28rem] overflow-hidden rounded-lg border border-border-light">
        <Suspense fallback={<Skeleton className="h-full" />}>
          <MapLibreViewer
            mode="development"
            basemap={basemap}
            geojsonLayers={layers}
            fitGeojson
            pickMode={tool !== 'none'}
            onMapClick={onMapClick}
          />
        </Suspense>
      </div>
    </div>
  );
}
