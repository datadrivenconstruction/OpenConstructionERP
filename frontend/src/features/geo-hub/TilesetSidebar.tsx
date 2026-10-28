// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Left rail listing every tileset in the project map config.
 *
 * Behaviour:
 *
 * * Each card surfaces name, status (colour-coded), tile count + size,
 *   last-updated relative time and the underlying source kind.
 * * Visibility toggle (eye icon) flips a per-id ``hidden`` flag the
 *   parent owns so it can be wired to a future Cesium "hide tileset"
 *   action without reaching across components.
 * * Click anywhere else on the card → ``onFocus(tileset)`` so the
 *   parent can fly the camera to the bounding volume.
 * * Skeleton state is rendered while the map config is loading; an
 *   empty list renders a small inline note (the *page-level* empty
 *   state handles the bigger "convert a model" CTA).
 */

import { useTranslation } from 'react-i18next';
import {
  Layers,
  Eye,
  EyeOff,
  ChevronRight,
  ChevronLeft,
  type LucideIcon,
  Cuboid,
  Building,
  CloudCog,
  Camera,
  UploadCloud,
  Map as MapIcon,
} from 'lucide-react';

import { GeoStatusBadge } from './GeoStatusBadge';
import type { GeoSourceKind, Tileset } from './types';
import { formatBytes, formatRelativeTime } from './utils';

interface TilesetSidebarProps {
  tilesets: Tileset[] | undefined;
  isLoading: boolean;
  hiddenIds: Set<string>;
  focusedId: string | null;
  onToggleVisibility: (tilesetId: string) => void;
  onFocus: (tileset: Tileset) => void;
  /**
   * ``overlay`` (default) anchors the panel ``absolute top-3 left-3``
   * over the Cesium canvas with translucent chrome + a 60vh cap so the
   * map stays mostly visible. ``rail`` keeps the legacy full-height
   * left rail for callers that want the old chrome (none currently).
   */
  variant?: 'rail' | 'overlay';
  /** When true, render the collapsed pill instead of the full panel. */
  collapsed?: boolean;
  /** Toggles ``collapsed`` — required when ``collapsed`` is supplied. */
  onToggleCollapsed?: () => void;
  /**
   * Per-tileset opacity in [0, 1]. ``undefined`` resolves to ``1`` so
   * legacy callers that don't pass it see fully-opaque tilesets as
   * before — no slider rendered.
   */
  getOpacity?: (tilesetId: string) => number;
  /**
   * Called when the user drags the opacity slider on a card. The
   * caller is expected to clamp + persist the value. Passing this
   * prop enables the slider; omitting it hides it entirely.
   */
  onChangeOpacity?: (tilesetId: string, opacity: number) => void;
}

const SOURCE_ICON: Record<GeoSourceKind, LucideIcon> = {
  bim_model: Cuboid,
  federation: Building,
  development: Building,
  upload: UploadCloud,
  point_cloud: CloudCog,
  photogrammetry: Camera,
};

function TilesetCard({
  tileset,
  hidden,
  focused,
  opacity,
  onToggleVisibility,
  onFocus,
  onChangeOpacity,
}: {
  tileset: Tileset;
  hidden: boolean;
  focused: boolean;
  /** ``undefined`` ↦ slider not rendered (legacy callers). */
  opacity: number | undefined;
  onToggleVisibility: (id: string) => void;
  onFocus: (t: Tileset) => void;
  onChangeOpacity?: (id: string, opacity: number) => void;
}) {
  const { t } = useTranslation();
  const Icon = SOURCE_ICON[tileset.source_kind] ?? Layers;
  const lastUpdated = tileset.generated_at ?? tileset.updated_at;

  return (
    <div
      className={[
        'group relative w-full rounded-md border bg-surface-primary p-2.5',
        'transition-colors duration-fast ease-oe',
        focused
          ? 'border-oe-blue/60 ring-1 ring-oe-blue/30'
          : 'border-border hover:border-content-tertiary',
        hidden ? 'opacity-60' : '',
      ].join(' ')}
    >
      <button
        type="button"
        onClick={() => onFocus(tileset)}
        className="flex w-full items-start gap-2 text-left"
        aria-label={t('geo_hub.sidebar.fly_to', {
          defaultValue: 'Fly to {{name}}',
          name: tileset.name,
        })}
      >
        <span
          className={[
            'mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center',
            'rounded-sm bg-surface-secondary text-content-secondary',
          ].join(' ')}
        >
          <Icon size={14} strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-xs font-medium text-content-primary">
              {tileset.name || tileset.id.slice(0, 8)}
            </span>
            <ChevronRight
              size={12}
              className="ml-auto shrink-0 text-content-tertiary opacity-0 transition-opacity group-hover:opacity-100"
            />
          </div>
          <div className="mt-1 flex items-center gap-1.5">
            <GeoStatusBadge status={tileset.status} />
            <span className="text-2xs text-content-tertiary uppercase tracking-wider">
              {tileset.tile_format}
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-content-tertiary">
            {tileset.tile_count > 0 && (
              <span>
                {t('geo_hub.sidebar.tile_count', {
                  defaultValue: '{{count}} tiles',
                  count: tileset.tile_count,
                })}
              </span>
            )}
            {tileset.total_bytes > 0 && <span>{formatBytes(tileset.total_bytes)}</span>}
            {lastUpdated && (
              <span title={lastUpdated}>
                {t('geo_hub.sidebar.updated_ago', {
                  defaultValue: 'updated {{rel}} ago',
                  rel: formatRelativeTime(lastUpdated),
                })}
              </span>
            )}
          </div>
        </div>
      </button>
      {/* Top-right eye button — preserved for hover affordance + keyboard
          parity. When the opacity slider is wired (onChangeOpacity given)
          we ALSO render a persistent inline row below the card body so the
          control is always visible and reachable without a hover gesture. */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onToggleVisibility(tileset.id);
        }}
        className={[
          'absolute right-1.5 top-1.5 inline-flex h-6 w-6 items-center justify-center',
          'rounded-sm text-content-tertiary opacity-0 transition',
          'hover:bg-surface-secondary hover:text-content-primary group-hover:opacity-100',
          // Keyboard parity: reveal the button when it receives focus so
          // users tabbing through the rail can toggle visibility without
          // a mouse hover (the only previous way to see it).
          'focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-oe-blue focus:outline-none',
          hidden ? 'opacity-100' : '',
        ].join(' ')}
        aria-pressed={!hidden}
        aria-label={
          hidden
            ? t('geo_hub.sidebar.show', { defaultValue: 'Show on map' })
            : t('geo_hub.sidebar.hide', { defaultValue: 'Hide from map' })
        }
      >
        {hidden ? <EyeOff size={13} /> : <Eye size={13} />}
      </button>
      {onChangeOpacity && (
        <div
          className="mt-2 flex items-center gap-2 border-t border-border/60 pt-2"
          data-testid="geo-tileset-overlay-controls"
          data-tileset-id={tileset.id}
        >
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleVisibility(tileset.id);
            }}
            data-testid="geo-tileset-visibility-toggle"
            aria-pressed={!hidden}
            aria-label={
              hidden
                ? t('geo_hub.sidebar.show', { defaultValue: 'Show on map' })
                : t('geo_hub.sidebar.hide', { defaultValue: 'Hide from map' })
            }
            title={
              hidden
                ? t('geo_hub.sidebar.show', { defaultValue: 'Show on map' })
                : t('geo_hub.sidebar.hide', { defaultValue: 'Hide from map' })
            }
            className={[
              'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-sm',
              hidden
                ? 'text-content-tertiary hover:bg-surface-secondary'
                : 'text-oe-blue hover:bg-surface-secondary',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
            ].join(' ')}
          >
            {hidden ? <EyeOff size={13} aria-hidden /> : <Eye size={13} aria-hidden />}
          </button>
          <label className="flex flex-1 items-center gap-2 text-2xs text-content-tertiary">
            <span className="sr-only">
              {t('geo_hub.sidebar.opacity', { defaultValue: 'Opacity' })}
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={opacity ?? 1}
              disabled={hidden}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (Number.isFinite(n)) onChangeOpacity(tileset.id, n);
              }}
              // Stop click from bubbling to the focus button — dragging
              // the slider must never re-fly the camera.
              onClick={(e) => e.stopPropagation()}
              data-testid="geo-tileset-opacity-slider"
              className={[
                'flex-1 accent-oe-blue',
                hidden ? 'opacity-40' : '',
              ].join(' ')}
              aria-label={t('geo_hub.sidebar.opacity', {
                defaultValue: 'Opacity',
              })}
              aria-valuetext={`${Math.round((opacity ?? 1) * 100)}%`}
            />
            <span className="w-9 text-right tabular-nums text-content-secondary">
              {Math.round((opacity ?? 1) * 100)}%
            </span>
          </label>
        </div>
      )}
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="rounded-md border border-border bg-surface-primary p-2.5">
      <div className="flex items-start gap-2">
        <div className="h-7 w-7 shrink-0 rounded-sm bg-surface-secondary animate-pulse" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="h-3 w-3/4 rounded bg-surface-secondary animate-pulse" />
          <div className="h-2.5 w-1/2 rounded bg-surface-secondary animate-pulse" />
          <div className="h-2.5 w-2/3 rounded bg-surface-secondary animate-pulse" />
        </div>
      </div>
    </div>
  );
}

export function TilesetSidebar({
  tilesets,
  isLoading,
  hiddenIds,
  focusedId,
  onToggleVisibility,
  onFocus,
  variant = 'overlay',
  collapsed = false,
  onToggleCollapsed,
  getOpacity,
  onChangeOpacity,
}: TilesetSidebarProps) {
  const { t } = useTranslation();

  const readyCount = (tilesets ?? []).filter((ts) => ts.status === 'ready').length;
  const failedCount = (tilesets ?? []).filter((ts) => ts.status === 'failed').length;
  const procCount = (tilesets ?? []).filter((ts) => ts.status === 'generating').length;
  const totalCount = tilesets?.length ?? 0;

  // Collapsed → slim pill so the user can hide the panel entirely and
  // see the full map. Only valid in overlay variant — the legacy rail
  // chrome is never collapsible since it is not absolutely positioned.
  if (variant === 'overlay' && collapsed) {
    return (
      <button
        type="button"
        onClick={onToggleCollapsed}
        className={[
          'absolute top-3 left-3 z-20 inline-flex items-center gap-2',
          'rounded-full border border-white/15 bg-slate-900/85 px-3 py-1.5',
          'text-xs font-medium text-white shadow-lg shadow-black/20 backdrop-blur-md',
          'ring-1 ring-white/5 transition hover:bg-slate-800/90',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
        ].join(' ')}
        aria-expanded={false}
        aria-label={t('geo_hub.sidebar.expand', { defaultValue: 'Show tilesets' })}
        title={t('geo_hub.sidebar.expand', { defaultValue: 'Show tilesets' })}
      >
        <Layers size={13} strokeWidth={2} className="text-emerald-300" />
        <span className="tabular-nums">{isLoading ? '…' : totalCount}</span>
        <ChevronRight size={13} strokeWidth={2.25} className="text-white/70" />
      </button>
    );
  }

  const isOverlay = variant === 'overlay';
  // Shared chrome between overlay + legacy rail variants. The overlay
  // variant adds absolute positioning + translucent dark plate; the
  // rail variant keeps the old full-height left rail (unused by current
  // callers but preserved for non-Cesium future surfaces).
  const containerClasses = isOverlay
    ? [
        'absolute top-3 left-3 z-20 flex w-72 max-w-[calc(100vw-1.5rem)] flex-col',
        'rounded-xl border border-white/15 bg-white/95 dark:bg-slate-900/90',
        'shadow-lg shadow-black/20 ring-1 ring-black/5 backdrop-blur-md',
        // Hide on phone-width — the collapsed pill takes its place when
        // the user opens the panel from the toggle button.
        'hidden md:flex',
      ].join(' ')
    : [
        'flex w-72 shrink-0 flex-col border-r border-border bg-surface-secondary',
      ].join(' ');

  return (
    <aside
      className={containerClasses}
      aria-label={t('geo_hub.sidebar.aria', { defaultValue: 'Tileset rail' })}
    >
      <header
        className={
          isOverlay
            ? 'border-b border-black/5 px-3 py-2.5 dark:border-white/10'
            : 'border-b border-border px-3 py-2.5'
        }
      >
        <div className="flex items-center gap-1.5">
          <Layers size={13} className="text-content-tertiary" />
          <h2 className="text-2xs font-semibold uppercase tracking-[0.14em] text-content-secondary">
            {t('geo_hub.sidebar.title', { defaultValue: 'Tilesets' })}
          </h2>
          {tilesets && (
            <span className="ml-auto text-2xs font-medium text-content-tertiary">
              {tilesets.length}
            </span>
          )}
          {isOverlay && onToggleCollapsed && (
            <button
              type="button"
              onClick={onToggleCollapsed}
              className={[
                'inline-flex h-6 w-6 items-center justify-center rounded-md',
                'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
              ].join(' ')}
              aria-expanded={true}
              aria-label={t('geo_hub.sidebar.collapse', {
                defaultValue: 'Hide tilesets',
              })}
              title={t('geo_hub.sidebar.collapse', {
                defaultValue: 'Hide tilesets',
              })}
            >
              <ChevronLeft size={13} strokeWidth={2} />
            </button>
          )}
        </div>
        {tilesets && tilesets.length > 0 && (
          <div className="mt-1.5 flex items-center gap-2 text-2xs text-content-tertiary">
            <span className="inline-flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {readyCount}
            </span>
            {procCount > 0 && (
              <span className="inline-flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
                {procCount}
              </span>
            )}
            {failedCount > 0 && (
              <span className="inline-flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                {failedCount}
              </span>
            )}
          </div>
        )}
      </header>
      {/* Self-sized in overlay variant — caps at 60vh so it never spans
          the full canvas. Rail variant keeps the legacy flex-1 stretch. */}
      <div
        className={
          isOverlay
            ? 'max-h-[60vh] overflow-y-auto p-2 space-y-1.5'
            : 'flex-1 overflow-y-auto p-2 space-y-1.5'
        }
      >
        {isLoading && (
          <>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </>
        )}
        {!isLoading && (!tilesets || tilesets.length === 0) && (
          <div className="flex flex-col items-center gap-1.5 px-3 py-6 text-center">
            <MapIcon size={18} className="text-content-quaternary" />
            <p className="text-xs text-content-tertiary">
              {t('geo_hub.sidebar.empty', {
                defaultValue: 'No tilesets in this project yet.',
              })}
            </p>
          </div>
        )}
        {!isLoading &&
          tilesets?.map((ts) => (
            <TilesetCard
              key={ts.id}
              tileset={ts}
              hidden={hiddenIds.has(ts.id)}
              focused={focusedId === ts.id}
              opacity={getOpacity ? getOpacity(ts.id) : undefined}
              onToggleVisibility={onToggleVisibility}
              onFocus={onFocus}
              onChangeOpacity={onChangeOpacity}
            />
          ))}
      </div>
    </aside>
  );
}

export default TilesetSidebar;
