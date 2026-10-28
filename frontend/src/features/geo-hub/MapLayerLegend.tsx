// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Project-map layer legend.
 *
 * A floating glass panel (bottom-right of the Cesium canvas) that shows,
 * per layer, how many features are on the map plus a small domain
 * breakdown (HSE by severity, punch by priority, tilesets by status).
 * Backed by the single ``GET /map-summary/{projectId}`` round-trip so the
 * counts stay correct even while the individual pin layers stream in
 * lazily, and so a project with hundreds of pins does not download every
 * row just to render a count.
 *
 * Layers with zero features render a muted "nothing pinned yet" row with
 * a deep-link into the source module - turning an invisible empty layer
 * into a discoverable call to action (e.g. "pin a safety incident").
 *
 * The legend is read-only: it never mutates map state, so it composes
 * cleanly alongside the tileset sidebar and overlay panel.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Layers,
  Box,
  Shapes,
  Image as ImageIcon,
  Camera,
  HardHat,
  ClipboardCheck,
  CameraIcon,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertTriangle,
  ArrowUpRight,
  MapPin,
} from 'lucide-react';

import { getMapSummary } from './api';
import type { MapLayerSummary } from './types';

interface MapLayerLegendProps {
  projectId: string;
}

type LayerKey =
  | 'tilesets'
  | 'overlays'
  | 'raster_overlays'
  | 'viewpoints'
  | 'hse_pins'
  | 'punchlist_pins'
  | 'diary_pins';

interface LayerRowMeta {
  key: LayerKey;
  Icon: typeof Box;
  label: string;
  /** Deep-link target for the "go pin one" CTA on empty layers. */
  emptyTo: (projectId: string) => string;
  emptyCta: string;
  /** Dot colour for the layer marker. */
  dot: string;
}

export function MapLayerLegend({ projectId }: MapLayerLegendProps) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);

  const query = useQuery({
    queryKey: ['geo-hub', 'map-summary', projectId],
    queryFn: () => getMapSummary(projectId),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });

  const rows = useMemo<LayerRowMeta[]>(
    () => [
      {
        key: 'tilesets',
        Icon: Box,
        label: t('geo_hub.legend.tilesets', { defaultValue: '3D models' }),
        emptyTo: () => '/bim',
        emptyCta: t('geo_hub.legend.add_model', { defaultValue: 'Add a 3D model' }),
        dot: 'bg-sky-500',
      },
      {
        key: 'overlays',
        Icon: Shapes,
        label: t('geo_hub.legend.overlays', { defaultValue: 'Vector overlays' }),
        emptyTo: (pid) => `/projects/${pid}/geo`,
        emptyCta: t('geo_hub.legend.import_geojson', {
          defaultValue: 'Import GeoJSON / KML',
        }),
        dot: 'bg-violet-500',
      },
      {
        key: 'raster_overlays',
        Icon: ImageIcon,
        label: t('geo_hub.legend.raster', { defaultValue: 'Drawings / images' }),
        emptyTo: (pid) => `/projects/${pid}/geo`,
        emptyCta: t('geo_hub.legend.place_drawing', {
          defaultValue: 'Place a drawing',
        }),
        dot: 'bg-amber-500',
      },
      {
        key: 'viewpoints',
        Icon: Camera,
        label: t('geo_hub.legend.viewpoints', { defaultValue: 'Saved views' }),
        emptyTo: (pid) => `/projects/${pid}/geo`,
        emptyCta: t('geo_hub.legend.save_view', { defaultValue: 'Save a view' }),
        dot: 'bg-teal-500',
      },
      {
        key: 'hse_pins',
        Icon: HardHat,
        label: t('geo_hub.legend.hse', { defaultValue: 'Safety incidents' }),
        emptyTo: (pid) => `/projects/${pid}/safety`,
        emptyCta: t('geo_hub.legend.log_incident', { defaultValue: 'Log an incident' }),
        dot: 'bg-orange-500',
      },
      {
        key: 'punchlist_pins',
        Icon: ClipboardCheck,
        label: t('geo_hub.legend.punchlist', { defaultValue: 'Punch list' }),
        emptyTo: () => '/punchlist',
        emptyCta: t('geo_hub.legend.add_punch', { defaultValue: 'Add a punch item' }),
        dot: 'bg-rose-500',
      },
      {
        key: 'diary_pins',
        Icon: CameraIcon,
        label: t('geo_hub.legend.diary', { defaultValue: 'Site photos' }),
        emptyTo: (pid) => `/projects/${pid}/daily-diary`,
        emptyCta: t('geo_hub.legend.add_photo', { defaultValue: 'Add a site photo' }),
        dot: 'bg-emerald-500',
      },
    ],
    [t],
  );

  // Collapsed pill — shows the headline feature count and re-expands.
  if (collapsed) {
    const total = query.data?.total_features ?? 0;
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        data-testid="geo-legend-pill"
        className={[
          'absolute bottom-3 right-3 z-20 inline-flex items-center gap-2',
          'rounded-full border border-white/15 bg-slate-900/85 px-3 py-1.5',
          'text-xs font-medium text-white shadow-lg shadow-black/20 backdrop-blur-md',
          'ring-1 ring-white/5 transition hover:bg-slate-800/90',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400',
        ].join(' ')}
        aria-expanded={false}
        aria-label={t('geo_hub.legend.expand', { defaultValue: 'Show map layers' })}
        title={t('geo_hub.legend.expand', { defaultValue: 'Show map layers' })}
      >
        <Layers size={13} strokeWidth={2} className="text-emerald-300" />
        <span className="tabular-nums">
          {query.isLoading ? '…' : query.isError ? '!' : total}
        </span>
        <ChevronUp size={13} strokeWidth={2.25} className="text-white/70" />
      </button>
    );
  }

  return (
    <aside
      data-testid="geo-layer-legend"
      className={[
        'absolute bottom-3 right-3 z-20 flex w-64 max-w-[calc(100vw-1.5rem)] flex-col',
        'rounded-xl border border-white/15 bg-white/95 dark:bg-slate-900/90',
        'shadow-lg shadow-black/20 ring-1 ring-black/5 backdrop-blur-md',
        'hidden md:flex',
      ].join(' ')}
      aria-label={t('geo_hub.legend.aria', { defaultValue: 'Map layers' })}
    >
      <div className="flex items-center justify-between gap-2 border-b border-black/5 px-3 py-2.5 dark:border-white/10">
        <div className="min-w-0">
          <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-content-secondary">
            {t('geo_hub.legend.title', { defaultValue: 'Map layers' })}
          </h2>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {query.isLoading
              ? t('geo_hub.legend.loading', { defaultValue: 'Counting…' })
              : query.isError
                ? t('geo_hub.legend.error', { defaultValue: 'Could not load counts' })
                : t('geo_hub.legend.feature_count', {
                    defaultValue: '{{count}} features on the map',
                    count: query.data?.total_features ?? 0,
                  })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className={[
            'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
            'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
          ].join(' ')}
          aria-label={t('geo_hub.legend.collapse', { defaultValue: 'Hide map layers' })}
          title={t('geo_hub.legend.collapse', { defaultValue: 'Hide map layers' })}
        >
          <ChevronDown size={14} strokeWidth={2} />
        </button>
      </div>

      {/* Derived-anchor nudge — the location is auto-placed from the
          project address, not yet confirmed. */}
      {query.data?.anchor_is_derived && (
        <div className="mx-2 mt-2 flex items-start gap-1.5 rounded-md border border-amber-300/40 bg-amber-50 px-2.5 py-1.5 text-2xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          <MapPin size={12} className="mt-0.5 shrink-0" />
          <span>
            {t('geo_hub.legend.derived_anchor', {
              defaultValue:
                'Location placed from the project address. Drag the anchor to confirm it.',
            })}
          </span>
        </div>
      )}

      <div className="max-h-[50vh] overflow-y-auto p-2">
        {query.isLoading && (
          <div className="flex items-center justify-center gap-2 px-3 py-5 text-2xs text-content-tertiary">
            <Loader2 size={14} className="animate-spin" />
            <span>{t('geo_hub.legend.loading_long', { defaultValue: 'Counting layers…' })}</span>
          </div>
        )}
        {!query.isLoading && query.isError && (
          <div className="m-1 flex items-start gap-2 rounded-md border border-red-300/40 bg-red-50 px-3 py-2.5 text-2xs text-red-900 dark:bg-red-950/40 dark:text-red-100">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            <span>
              {t('geo_hub.legend.error_hint', {
                defaultValue:
                  'Layer counts unavailable. The map itself is unaffected.',
              })}
            </span>
          </div>
        )}
        {!query.isLoading && !query.isError && query.data && (
          <ul className="space-y-0.5">
            {rows.map((row) => {
              const layer = query.data[row.key] as MapLayerSummary;
              const total = layer?.total ?? 0;
              const breakdown = layer?.breakdown ?? {};
              const empty = total === 0;
              return (
                <li
                  key={row.key}
                  className={[
                    'rounded-md px-2 py-1.5',
                    empty ? 'opacity-70' : 'hover:bg-surface-secondary',
                  ].join(' ')}
                >
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className={[
                        'inline-flex h-5 w-5 shrink-0 items-center justify-center rounded',
                        empty ? 'bg-surface-tertiary' : `${row.dot}/15`,
                      ].join(' ')}
                    >
                      <row.Icon
                        size={12}
                        strokeWidth={2}
                        className={empty ? 'text-content-tertiary' : 'text-content-secondary'}
                      />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-content-primary">
                      {row.label}
                    </span>
                    {empty ? (
                      <Link
                        to={row.emptyTo(projectId)}
                        className={[
                          'inline-flex shrink-0 items-center gap-0.5 rounded px-1.5 py-0.5',
                          'text-2xs font-medium text-oe-blue hover:bg-oe-blue/10',
                          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                        ].join(' ')}
                        title={row.emptyCta}
                      >
                        {row.emptyCta}
                        <ArrowUpRight size={10} strokeWidth={2.25} />
                      </Link>
                    ) : (
                      <span
                        className={[
                          'shrink-0 rounded px-1.5 py-px text-2xs font-semibold tabular-nums',
                          'bg-surface-tertiary text-content-secondary',
                        ].join(' ')}
                      >
                        {total}
                      </span>
                    )}
                  </div>
                  {/* Domain breakdown chips — only when meaningful. */}
                  {!empty && Object.keys(breakdown).length > 0 && (
                    <div className="ml-7 mt-1 flex flex-wrap gap-1">
                      {Object.entries(breakdown)
                        .sort((a, b) => b[1] - a[1])
                        .map(([bucket, count]) => (
                          <span
                            key={bucket}
                            className="rounded bg-surface-secondary px-1 py-px text-[10px] font-medium uppercase tracking-wide text-content-tertiary"
                          >
                            {bucket} · {count}
                          </span>
                        ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

export default MapLayerLegend;
