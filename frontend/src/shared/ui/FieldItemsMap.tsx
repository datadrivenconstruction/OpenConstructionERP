// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Map of field items (punch items, defects) that carry a WGS84 pin.
 *
 * Same lazy MapLibre pattern and basemap as the dashboard project map: the map
 * library and its marker component resolve together before the first render,
 * so markers attach to the canvas on the first pass. Items without a pin are
 * counted in the legend rather than dropped silently.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Map as MapIcon } from 'lucide-react';
import type { MapRef, MarkerProps } from 'react-map-gl/maplibre';
import { TILE_ATTRIBUTION_HTML, useStreetBasemapStyleUrl } from '@/shared/ui/ProjectMap/basemap';
import type { MapPin } from '@/shared/lib/photoEvidence';
import 'maplibre-gl/dist/maplibre-gl.css';

type MapLibreModule = typeof import('react-map-gl/maplibre');

const TONE_CLASS: Record<NonNullable<MapPin['tone']>, string> = {
  open: 'bg-amber-500',
  progress: 'bg-oe-blue',
  done: 'bg-emerald-600',
  critical: 'bg-red-600',
};

interface FieldItemsMapProps {
  pins: MapPin[];
  /** Items in the list, pinned or not, for the "n of m on the map" legend. */
  total: number;
  onSelect?: (id: string) => void;
  selectedId?: string | null;
  className?: string;
}

export function FieldItemsMap({ pins, total, onSelect, selectedId, className }: FieldItemsMapProps) {
  const { t } = useTranslation();
  const [mapLib, setMapLib] = useState<MapLibreModule | null>(null);
  const styleUrl = useStreetBasemapStyleUrl();
  const mapRef = useRef<MapRef | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([import('@/shared/lib/mapLibre'), import('react-map-gl/maplibre')]).then(([, mod]) => {
      if (!cancelled) setMapLib(mod);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const initialView = useMemo(() => {
    if (pins.length === 0) return { longitude: 0, latitude: 20, zoom: 1.2 };
    const lats = pins.map((p) => p.lat);
    const lons = pins.map((p) => p.lon);
    return {
      longitude: (Math.min(...lons) + Math.max(...lons)) / 2,
      latitude: (Math.min(...lats) + Math.max(...lats)) / 2,
      zoom: pins.length === 1 ? 17 : 15,
    };
  }, [pins]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || pins.length < 2) return;
    const lats = pins.map((p) => p.lat);
    const lons = pins.map((p) => p.lon);
    map.fitBounds(
      [
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)],
      ],
      { padding: 40, duration: 400, maxZoom: 19 },
    );
  }, [pins, mapLib]);

  const Map = mapLib?.default;
  const Marker = mapLib?.Marker;
  const Attribution = mapLib?.AttributionControl;

  return (
    <div
      className={clsx(
        'relative h-[28rem] overflow-hidden rounded-xl border border-border-light bg-surface-secondary',
        className,
      )}
      data-testid="field-items-map"
    >
      {pins.length === 0 ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center text-sm text-content-tertiary">
          <MapIcon size={28} strokeWidth={1.5} />
          <p>
            {t('field_evidence.map_empty', {
              defaultValue: 'No item has a map position yet. Photos taken in the app with location enabled place their item on the map.',
            })}
          </p>
        </div>
      ) : Map && Marker && Attribution ? (
        <Map
          ref={(instance: MapRef | null) => {
            mapRef.current = instance;
          }}
          initialViewState={initialView}
          mapStyle={styleUrl}
          style={{ width: '100%', height: '100%' }}
          dragRotate={false}
          attributionControl={false}
        >
          <Attribution compact customAttribution={TILE_ATTRIBUTION_HTML} />
          {pins.map((pin) => (
            <Marker
              key={pin.id}
              longitude={pin.lon}
              latitude={pin.lat}
              anchor="bottom"
              onClick={(e: Parameters<NonNullable<MarkerProps['onClick']>>[0]) => {
                e.originalEvent.stopPropagation();
                onSelect?.(pin.id);
              }}
            >
              <button
                type="button"
                className={clsx(
                  'flex h-6 w-6 items-center justify-center rounded-full text-white shadow-md ring-2',
                  TONE_CLASS[pin.tone ?? 'open'],
                  selectedId === pin.id ? 'ring-content-primary scale-125' : 'ring-white',
                )}
                title={pin.label}
                aria-label={pin.label}
              >
                <span className="h-2 w-2 rounded-full bg-white" />
              </button>
            </Marker>
          ))}
        </Map>
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-content-tertiary">
          <MapIcon size={24} strokeWidth={1.5} />
        </div>
      )}
      <div className="pointer-events-none absolute left-3 top-3 rounded-md bg-surface-elevated/90 px-2 py-1 text-[11px] font-medium text-content-primary shadow-sm">
        {t('field_evidence.map_legend', {
          defaultValue: '{{pinned}} of {{total}} on the map',
          pinned: pins.length,
          total,
        })}
      </div>
    </div>
  );
}
