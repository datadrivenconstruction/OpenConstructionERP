// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan view of the survey: points, surface outlines and a cut/fill heat map,
 * on the shared MapLibre viewer. The backend serves WGS 84; a local grid has
 * no place on the earth, so it gets a note instead of a wrong map.
 */

import { lazy, Suspense, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Map as MapIcon } from 'lucide-react';
import { EmptyState, ErrorState, Skeleton } from '@/shared/ui';
import type { GeoJsonLayer } from '@/features/geo-hub/MapLibreViewer';
import type { BasemapId } from '@/features/geo-hub/mapStyles';
import type { SurveyPlan as Plan } from './volumesApi';

const MapLibreViewer = lazy(() => import('@/features/geo-hub/MapLibreViewer'));

export const CUT_COLOUR = '#c2410c';
export const FILL_COLOUR = '#1d4ed8';

/** Split one served collection into the viewer's styled layers. */
export function planLayers(plan: Plan): GeoJsonLayer[] {
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
      layers: [{ id: 'survey-surfaces', type: 'line', paint: { 'line-color': '#0f766e', 'line-width': 2 } }],
    },
    {
      id: 'points',
      data: pick('points'),
      layers: [
        {
          id: 'survey-points',
          type: 'circle',
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
}

export function SurveyPlan({ plan, isLoading, error, onRetry, showLegend = false }: Props) {
  const { t } = useTranslation();
  const [basemap, setBasemap] = useState<BasemapId>('streets');
  const layers = useMemo(() => (plan ? planLayers(plan) : []), [plan]);

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
      <div className="h-[28rem] overflow-hidden rounded-lg border border-border-light">
        <Suspense fallback={<Skeleton className="h-full" />}>
          <MapLibreViewer mode="development" basemap={basemap} geojsonLayers={layers} fitGeojson />
        </Suspense>
      </div>
    </div>
  );
}
