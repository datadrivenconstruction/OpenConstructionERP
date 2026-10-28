// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Floating "Adjust anchor" affordance for the project-scoped Geo Hub.
 *
 * Mounted in the CesiumViewer overlay slot when a project already has an
 * anchor. Provides:
 *
 *   * Coords + precision chip (address / street / city / region / country)
 *   * Re-geocode button (POST /anchors/from-address/ with ?force=true)
 *   * Drag-to-adjust toggle (parent wires click-on-map -> PATCH)
 *   * Source attribution (OSM Nominatim) per ToS
 *
 * Lives in its own file so ProjectGeoPage's overlay slot stays readable
 * and so the panel can be unit-tested independently.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronUp,
  Crosshair,
  Loader2,
  MapPinned,
  RefreshCw,
  Sparkles,
} from 'lucide-react';

import { ApiError } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { AnchorDriftIndicator } from './AnchorDriftIndicator';
import { autoAnchorFromAddress } from './api';
import type { GeoAnchor } from './types';

interface AnchorAdjustPanelProps {
  projectId: string;
  anchor: GeoAnchor;
  dragMode: boolean;
  onToggleDragMode: () => void;
  /**
   * Free-text address typed on the project (NOT the geocoded
   * ``anchor.address`` — that one is the cached Nominatim display
   * name). When present and divergent from ``anchor.address`` the
   * drift indicator surfaces the "Re-anchor" CTA.
   */
  projectAddressText?: string | null;
}

type Precision = 'address' | 'street' | 'city' | 'region' | 'country';

const PRECISION_LABEL: Record<Precision, string> = {
  address: 'Precise',
  street: 'Street-level',
  city: 'City-level',
  region: 'Region-level',
  country: 'Country-level',
};

const PRECISION_TONE: Record<Precision, string> = {
  address: 'bg-emerald-500/15 text-emerald-200 ring-emerald-400/30',
  street: 'bg-lime-500/15 text-lime-200 ring-lime-400/30',
  city: 'bg-amber-500/15 text-amber-200 ring-amber-400/30',
  region: 'bg-orange-500/15 text-orange-200 ring-orange-400/30',
  country: 'bg-red-500/15 text-red-200 ring-red-400/30',
};

// Persisted across reloads so the user's preferred chrome density survives
// navigation. Versioned (`v1`) so a future incompatible rename never
// resurrects with stale boolean semantics. Mirrors the OverlayPanel /
// TilesetSidebar collapse-persistence pattern.
const ANCHOR_PANEL_COLLAPSED_LS_KEY =
  'oe.geo_hub.anchor_panel_collapsed.v1';

function readAnchorPanelCollapsed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return (
      window.localStorage.getItem(ANCHOR_PANEL_COLLAPSED_LS_KEY) === '1'
    );
  } catch {
    return false;
  }
}

export function AnchorAdjustPanel({
  projectId,
  anchor,
  dragMode,
  onToggleDragMode,
  projectAddressText,
}: AnchorAdjustPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [isRegeocoding, setIsRegeocoding] = useState(false);
  // Collapsible so the panel never permanently masks the map. It shares
  // the canvas corner with the HUD scale/coordinate pods, so the user can
  // tuck it away to a small pill and still read the live cursor readout.
  const [collapsed, setCollapsed] = useState<boolean>(
    readAnchorPanelCollapsed,
  );
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(
        ANCHOR_PANEL_COLLAPSED_LS_KEY,
        collapsed ? '1' : '0',
      );
    } catch {
      /* localStorage disabled / quota full - UX still works in-memory */
    }
  }, [collapsed]);

  const metadata = anchor.metadata as Record<string, unknown> | undefined;
  const rawPrecision =
    typeof metadata?.geocode_precision === 'string'
      ? (metadata.geocode_precision as string)
      : null;
  const precision: Precision | null =
    rawPrecision &&
    ['address', 'street', 'city', 'region', 'country'].includes(rawPrecision)
      ? (rawPrecision as Precision)
      : null;
  const sourceRaw =
    typeof metadata?.geocode_source === 'string'
      ? (metadata.geocode_source as string)
      : null;
  const sourceLabel =
    sourceRaw === 'cache'
      ? t('geo_hub.adjust.source_cached', {
          defaultValue: 'OSM Nominatim (cached)',
        })
      : sourceRaw === 'manual'
        ? t('geo_hub.adjust.source_manual', {
            defaultValue: 'Manually placed',
          })
        : t('geo_hub.adjust.source_nominatim', {
            defaultValue: 'OSM Nominatim',
          });

  async function reGeocode() {
    if (isRegeocoding) return;
    setIsRegeocoding(true);
    try {
      await autoAnchorFromAddress(projectId, { force: true });
      addToast({
        type: 'success',
        title: t('geo_hub.adjust.regeocode_success', {
          defaultValue: 'Anchor refreshed from address',
        }),
      });
      await queryClient.invalidateQueries({
        queryKey: ['geo-hub', 'map-config', projectId],
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        addToast({
          type: 'warning',
          title: t('geo_hub.adjust.regeocode_address_missing', {
            defaultValue: 'Project address is incomplete',
          }),
          message: t('geo_hub.adjust.regeocode_address_hint', {
            defaultValue: 'Add a country to the project address and try again.',
          }),
        });
      } else if (err instanceof ApiError && err.status === 502) {
        addToast({
          type: 'error',
          title: t('geo_hub.adjust.regeocode_unavailable', {
            defaultValue: 'Geocoder unavailable',
          }),
        });
      } else {
        addToast({
          type: 'error',
          title: t('geo_hub.adjust.regeocode_failed', {
            defaultValue: 'Re-geocode failed',
          }),
        });
      }
    } finally {
      setIsRegeocoding(false);
    }
  }

  // Collapsed: a small pill in the same (relocated) corner that the user
  // taps to bring the panel back. Mirrors OverlayPanel's collapsed pill.
  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className={[
          'pointer-events-auto absolute bottom-20 left-3 z-20 inline-flex items-center gap-2',
          'rounded-full border border-white/15 bg-slate-900/85 px-3 py-1.5',
          'text-xs font-medium text-white shadow-lg shadow-black/20 backdrop-blur-md',
          'ring-1 ring-white/5 transition hover:bg-slate-800/90',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300',
        ].join(' ')}
        aria-expanded={false}
        aria-label={t('geo_hub.adjust.expand', {
          defaultValue: 'Show project anchor',
        })}
        data-testid="geo-anchor-adjust-pill"
      >
        <MapPinned size={13} strokeWidth={2} className="text-emerald-300" />
        <ChevronUp size={13} strokeWidth={2.25} className="text-white/70" />
      </button>
    );
  }

  return (
    <aside
      className={[
        // Relocated off the top-right corner (which OverlayPanel owns) to the
        // free left side, lifted above the bottom-left HUD pods so the two
        // chrome panels stop overlapping (#284 follow-up items 7+8).
        'pointer-events-auto absolute bottom-20 left-3 z-20',
        'flex w-64 max-w-[calc(100vw-1.5rem)] flex-col gap-2',
        'rounded-lg border border-white/15 bg-slate-900/85 p-3',
        'text-xs text-slate-100 shadow-lg shadow-black/30 backdrop-blur-md',
        'ring-1 ring-white/5',
      ].join(' ')}
      aria-label={t('geo_hub.adjust.aria', {
        defaultValue: 'Adjust project anchor',
      })}
      data-testid="geo-anchor-adjust-panel"
    >
      <div className="flex items-center gap-2">
        <span
          className={[
            'inline-flex h-7 w-7 items-center justify-center rounded-md',
            'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-400/30',
          ].join(' ')}
        >
          <MapPinned size={13} strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-2xs font-semibold uppercase tracking-[0.12em] text-slate-400">
            {t('geo_hub.adjust.title', { defaultValue: 'Project anchor' })}
          </div>
          <div className="font-mono text-2xs text-slate-200 tabular-nums">
            {Number(anchor.lat).toFixed(5)}, {Number(anchor.lon).toFixed(5)}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className={[
            'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md',
            'text-slate-400 hover:bg-white/10 hover:text-slate-100',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300',
          ].join(' ')}
          aria-expanded
          aria-label={t('geo_hub.adjust.collapse', {
            defaultValue: 'Hide project anchor',
          })}
          data-testid="geo-anchor-adjust-collapse"
        >
          <ChevronDown size={14} strokeWidth={2} />
        </button>
      </div>

      {precision && (
        <div className="flex items-center gap-2">
          <span
            className={[
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5',
              'text-2xs font-semibold ring-1',
              PRECISION_TONE[precision],
            ].join(' ')}
          >
            {t(`geo_hub.adjust.precision_${precision}`, {
              defaultValue: PRECISION_LABEL[precision],
            })}
          </span>
          {precision !== 'address' && (
            <span className="text-2xs text-amber-200">
              {t('geo_hub.adjust.drag_hint', {
                defaultValue: 'Drag to refine',
              })}
            </span>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5 pt-1">
        <button
          type="button"
          onClick={reGeocode}
          disabled={isRegeocoding}
          className={[
            'inline-flex items-center gap-1 rounded-md',
            'border border-white/15 bg-white/5 px-2 py-1 text-2xs font-medium',
            'hover:bg-white/10 disabled:cursor-wait disabled:opacity-70',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300',
          ].join(' ')}
          data-testid="geo-anchor-regeocode"
        >
          {isRegeocoding ? (
            <Loader2 size={11} strokeWidth={2.25} className="animate-spin" />
          ) : (
            <Sparkles size={11} strokeWidth={2.25} />
          )}
          {t('geo_hub.adjust.regeocode', { defaultValue: 'Re-geocode' })}
        </button>
        <button
          type="button"
          onClick={onToggleDragMode}
          aria-pressed={dragMode}
          className={[
            'inline-flex items-center gap-1 rounded-md',
            'px-2 py-1 text-2xs font-medium ring-1',
            dragMode
              ? 'bg-emerald-500 text-white ring-emerald-400'
              : 'border border-white/15 bg-white/5 hover:bg-white/10 ring-transparent',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300',
          ].join(' ')}
          data-testid="geo-anchor-drag-toggle"
        >
          {dragMode ? (
            <RefreshCw size={11} strokeWidth={2.25} />
          ) : (
            <Crosshair size={11} strokeWidth={2.25} />
          )}
          {dragMode
            ? t('geo_hub.adjust.drag_on', { defaultValue: 'Click map to set' })
            : t('geo_hub.adjust.drag_off', {
                defaultValue: 'Drag to adjust',
              })}
        </button>
      </div>

      <div className="pt-1 text-2xs text-slate-400">
        {t('geo_hub.adjust.source_prefix', { defaultValue: 'Source:' })}{' '}
        <span className="text-slate-300">{sourceLabel}</span>
      </div>

      {/* Drift indicator — only renders when the typed project address
          diverges from the cached anchor display name, so the panel
          stays compact for in-sync projects. */}
      {projectAddressText && (
        <div className="mt-1">
          <AnchorDriftIndicator
            projectAddressText={projectAddressText}
            anchoredAddress={anchor.address}
            onReanchor={reGeocode}
            isReanchoring={isRegeocoding}
            compact
          />
        </div>
      )}
    </aside>
  );
}

export default AnchorAdjustPanel;
