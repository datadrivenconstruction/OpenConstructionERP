// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan tab: parcels coloured by acquisition status, the work zone outlined,
 * and parcels that block the works (PAR-003) drawn with a dashed red edge.
 * Loaded lazily so the map bundle only ships when the tab opens.
 */

import { useState } from 'react';
import { Layer, Source } from 'react-map-gl/maplibre';
import { MapLibreViewer } from '@/features/geo-hub/MapLibreViewer';
import type { BasemapId } from '@/features/geo-hub/mapStyles';
import type { PlanCollection } from './api';
import { STATUS_FILL, planCentre } from './parcelFormat';

const fillColour = [
  'match',
  ['get', 'status'],
  'acquired',
  STATUS_FILL.acquired,
  'negotiating',
  STATUS_FILL.negotiating,
  'expropriation',
  STATUS_FILL.expropriation,
  STATUS_FILL.needed,
] as unknown as string;

export default function ParcelPlan({ plan }: { plan: PlanCollection }) {
  const [basemap] = useState<BasemapId>('streets');
  const centre = planCentre(plan);
  const parcels = { ...plan, features: plan.features.filter((f) => f.properties.kind === 'parcel') };
  const zones = { ...plan, features: plan.features.filter((f) => f.properties.kind === 'work_zone') };
  return (
    <div className="h-[480px] w-full overflow-hidden rounded-lg border border-border-light" data-testid="parcels-plan">
      <MapLibreViewer mode="project" basemap={basemap} anchor={centre}>
        <Source id="lp-parcels" type="geojson" data={parcels as never}>
          <Layer id="lp-parcels-fill" type="fill" paint={{ 'fill-color': fillColour, 'fill-opacity': 0.35 }} />
          <Layer id="lp-parcels-edge" type="line" paint={{ 'line-color': fillColour, 'line-width': 1.5 }} />
          <Layer
            id="lp-parcels-blocking"
            type="line"
            filter={['==', ['get', 'blocking'], true]}
            paint={{ 'line-color': '#dc2626', 'line-width': 3, 'line-dasharray': [2, 2] }}
          />
        </Source>
        <Source id="lp-zones" type="geojson" data={zones as never}>
          <Layer id="lp-zones-edge" type="line" paint={{ 'line-color': '#2563eb', 'line-width': 2.5 }} />
        </Source>
      </MapLibreViewer>
    </div>
  );
}
