// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Small MapLibre map for geofences​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: draws every fence as a filled outline, the
 * fence being edited as a highlighted draft, and optional pins (clock-in
 * positions). Click events are handed to the parent, which owns the drawing
 * state. Loaded lazily (maplibre is heavy); see GeofenceEditor.
 */

import { useCallback, useEffect, useMemo, useRef } from 'react';
import Map, {
  Layer,
  Marker,
  NavigationControl,
  ScaleControl,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
} from 'react-map-gl/maplibre';
import type { FeatureCollection } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';
import '@/shared/lib/mapLibre';
import { buildBasemapStyle } from '@/features/geo-hub/mapStyles';
import { geoAuthHeaders } from '@/features/geo-hub/api';
import { useThemeStore } from '@/stores/useThemeStore';
import { fenceRing, type FenceShape, type LatLng } from './geometry';

export interface MapFence extends FenceShape {
  id: string;
  name: string;
  active: boolean;
}

export interface MapPin {
  id: string;
  lat: number;
  lng: number;
  label?: string;
  tone: 'ok' | 'warn';
}

export interface GeofenceMapProps {
  fences: MapFence[];
  /** The fence being drawn or edited. */
  draft?: FenceShape | null;
  /** Vertices placed so far while a polygon is still open (no ring yet). */
  draftPoints?: LatLng[];
  pins?: MapPin[];
  /** Fly here when it changes. */
  focus?: { lat: number; lng: number; zoom?: number } | null;
  drawing?: boolean;
  onMapClick?: (p: LatLng) => void;
}

/** True when this browser can create a WebGL context at all. */
export function mapSupported(): boolean {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

function toCollection(
  items: { ring: [number, number][] | null; props: Record<string, unknown> }[],
): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: items
      .filter((i) => i.ring)
      .map((i) => ({
        type: 'Feature' as const,
        properties: i.props,
        geometry: { type: 'Polygon' as const, coordinates: [i.ring as [number, number][]] },
      })),
  };
}

export function GeofenceMap({ fences, draft, draftPoints = [], pins = [], focus, drawing, onMapClick }: GeofenceMapProps) {
  const mapRef = useRef<MapRef>(null);
  const theme = useThemeStore((s) => s.resolved);

  const initial = useMemo(() => {
    const first = focus ?? (pins[0] ? pins[0] : null);
    if (first) return { latitude: first.lat, longitude: first.lng, zoom: 16 };
    const f = fences.find((x) => x.center_lat != null) ?? null;
    if (f && f.center_lat != null && f.center_lng != null) {
      return { latitude: f.center_lat, longitude: f.center_lng, zoom: 16 };
    }
    const p = fences.find((x) => x.polygon.length > 0)?.polygon[0];
    if (p) return { latitude: p[0], longitude: p[1], zoom: 16 };
    return { latitude: 30, longitude: 12, zoom: 1.4 };
    // Read once: later moves go through the focus effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!focus) return;
    mapRef.current?.flyTo({ center: [focus.lng, focus.lat], zoom: focus.zoom ?? 16, duration: 600 });
  }, [focus]);

  const existing = useMemo(
    () => toCollection(fences.map((f) => ({ ring: fenceRing(f), props: { name: f.name, active: f.active } }))),
    [fences],
  );
  const draftRing = useMemo(() => (draft ? fenceRing(draft) : null), [draft]);
  const draftFc = useMemo(() => toCollection([{ ring: draftRing, props: {} }]), [draftRing]);
  const pointsFc = useMemo<FeatureCollection>(
    () => ({
      type: 'FeatureCollection',
      features: draftPoints.map(([lat, lng]) => ({
        type: 'Feature' as const,
        properties: {},
        geometry: { type: 'Point' as const, coordinates: [lng, lat] },
      })),
    }),
    [draftPoints],
  );

  const transformRequest = useCallback((url: string) => {
    if (url.startsWith('/api') || url.includes('/api/v1/geo-hub/')) {
      const headers = geoAuthHeaders();
      if (headers.Authorization) return { url, headers };
    }
    return { url };
  }, []);

  const handleClick = (e: MapLayerMouseEvent) => {
    if (drawing && onMapClick) onMapClick([e.lngLat.lat, e.lngLat.lng]);
  };

  return (
    <Map
      ref={mapRef}
      initialViewState={initial}
      mapStyle={buildBasemapStyle('streets', theme)}
      style={{ width: '100%', height: '100%' }}
      cursor={drawing ? 'crosshair' : undefined}
      dragRotate={false}
      touchZoomRotate={false}
      transformRequest={transformRequest}
      onClick={handleClick}
    >
      <NavigationControl position="top-right" showCompass={false} />
      <ScaleControl position="bottom-right" />
      <Source id="fences" type="geojson" data={existing}>
        <Layer id="fences-fill" type="fill" paint={{ 'fill-color': '#64748b', 'fill-opacity': 0.18 }} />
        <Layer id="fences-line" type="line" paint={{ 'line-color': '#475569', 'line-width': 2 }} />
      </Source>
      <Source id="draft" type="geojson" data={draftFc}>
        <Layer id="draft-fill" type="fill" paint={{ 'fill-color': '#0071e3', 'fill-opacity': 0.25 }} />
        <Layer id="draft-line" type="line" paint={{ 'line-color': '#0071e3', 'line-width': 3 }} />
      </Source>
      <Source id="draft-points" type="geojson" data={pointsFc}>
        <Layer
          id="draft-points-circle"
          type="circle"
          paint={{
            'circle-radius': 6,
            'circle-color': '#0071e3',
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 2,
          }}
        />
      </Source>
      {pins.map((p) => (
        <Marker key={p.id} latitude={p.lat} longitude={p.lng} anchor="center">
          <span
            title={p.label}
            className={
              p.tone === 'warn'
                ? 'block h-4 w-4 rounded-full border-2 border-white bg-semantic-warning shadow'
                : 'block h-4 w-4 rounded-full border-2 border-white bg-semantic-success shadow'
            }
          />
        </Marker>
      ))}
    </Map>
  );
}

export default GeofenceMap;
