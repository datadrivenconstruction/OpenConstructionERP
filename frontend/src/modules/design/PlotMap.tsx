// Design module (ERP side of the design editor link).
/**
 * Map for drawing the plot outline. Uses the platform basemap (same style and tile access as the
 * geo hub). Clicks add corners while drawing; corners are draggable markers. Loaded lazily.
 */

import { useCallback, useEffect, useMemo, useRef, type KeyboardEvent } from 'react';
import Map, {
  Layer,
  Marker,
  NavigationControl,
  ScaleControl,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
  type MarkerDragEvent,
} from 'react-map-gl/maplibre';
import type { FeatureCollection } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';
import '@/shared/lib/mapLibre';
import { buildBasemapStyle } from '@/features/geo-hub/mapStyles';
import { geoAuthHeaders } from '@/features/geo-hub/api';
import { sameOrigin } from './data/geoOrigin';
import { useThemeStore } from '@/stores/useThemeStore';
import { useTranslation } from 'react-i18next';
import { bounds, closeRing, wrapLon, type LngLat } from './data/polygon';
import { tr } from './BriefFields';

const M_PER_DEGREE = 111_320;

export interface PlotMapProps {
  points: LngLat[];
  drawing: boolean;
  /** Where to look when there is no outline yet (the project address), else the whole world. */
  focus: { lat: number; lng: number } | null;
  onChange: (points: LngLat[]) => void;
}

export function PlotMap({ points, drawing, focus, onChange }: PlotMapProps) {
  const mapRef = useRef<MapRef>(null);
  const theme = useThemeStore((s) => s.resolved);
  const { t } = useTranslation();

  const initial = useMemo(() => {
    const b = bounds(points);
    if (b) return { bounds: b as [number, number, number, number], fitBoundsOptions: { padding: 60, maxZoom: 19 } };
    if (focus) return { latitude: focus.lat, longitude: focus.lng, zoom: 17 };
    return { latitude: 30, longitude: 12, zoom: 1.4 };
    // Read once: later moves come from the person or the focus effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (focus && points.length === 0) mapRef.current?.flyTo({ center: [focus.lng, focus.lat], zoom: 17, duration: 600 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.lat, focus?.lng]);

  const shape = useMemo<FeatureCollection>(() => {
    const features: FeatureCollection['features'] = [];
    if (points.length >= 3 && !drawing) {
      features.push({ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [closeRing(points)] } });
    } else if (points.length >= 2) {
      features.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: points } });
    }
    return { type: 'FeatureCollection', features };
  }, [points, drawing]);

  const transformRequest = useCallback((url: string) => {
    if (url.startsWith('/api') || url.includes('/api/v1/geo-hub/')) {
      // The style names the backend's own host; behind a proxy that is another origin (CORS): ask this one.
      const own = sameOrigin(url);
      const headers = geoAuthHeaders();
      return headers.Authorization ? { url: own, headers } : { url: own };
    }
    return { url };
  }, []);

  const handleClick = (e: MapLayerMouseEvent) => {
    if (drawing) onChange([...points, [wrapLon(e.lngLat.lng), e.lngLat.lat]]);
  };

  const moveCorner = (i: number) => (e: MarkerDragEvent) => {
    const next = points.slice();
    next[i] = [wrapLon(e.lngLat.lng), e.lngLat.lat];
    onChange(next);
  };

  // Keyboard: arrows nudge the focused corner 1 m (Shift 10 m), Delete removes it.
  const keyCorner = (i: number) => (e: KeyboardEvent<HTMLButtonElement>) => {
    const arrows: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
    const step = e.shiftKey ? 10 : 1;
    const p = points[i]!;
    if (e.key in arrows) {
      e.preventDefault();
      const [dx, dy] = arrows[e.key]!;
      const lat = Math.max(-90, Math.min(90, p[1] + (dy * step) / M_PER_DEGREE));
      const lon = wrapLon(p[0] + (dx * step) / (M_PER_DEGREE * Math.max(Math.cos((p[1] * Math.PI) / 180), 1e-6)));
      const next = points.slice();
      next[i] = [Math.round(lon * 1e7) / 1e7, Math.round(lat * 1e7) / 1e7];
      onChange(next);
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      onChange(points.filter((_, j) => j !== i));
    }
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
      doubleClickZoom={!drawing}
      transformRequest={transformRequest}
      onClick={handleClick}
    >
      <NavigationControl position="top-right" showCompass={false} />
      <ScaleControl position="bottom-right" />
      <Source id="plot" type="geojson" data={shape}>
        <Layer id="plot-fill" type="fill" filter={['==', '$type', 'Polygon']}
          paint={{ 'fill-color': '#0071e3', 'fill-opacity': 0.2 }} />
        <Layer id="plot-line" type="line" paint={{ 'line-color': '#0071e3', 'line-width': 3 }} />
      </Source>
      {points.map((p, i) => (
        <Marker key={i} longitude={p[0]} latitude={p[1]} anchor="center" draggable onDrag={moveCorner(i)}>
          <button
            type="button"
            className="block h-4 w-4 cursor-move rounded-full border-2 border-white bg-oe-blue shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2"
            aria-label={tr(t, 'design.plot.corner_pos', { n: i + 1, lon: p[0].toFixed(6), lat: p[1].toFixed(6) })}
            onKeyDown={keyCorner(i)}
          />
        </Marker>
      ))}
    </Map>
  );
}

export default PlotMap;
