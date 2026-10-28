// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Glass-panel empty states for the Geo Hub.
 *
 * Three distinct modes:
 *
 * 1. ``no_anchor`` — project exists but has not been anchored on the map.
 *    Primary CTA: auto-geocode from the project's stored address.
 *    Secondary CTA: open the project settings to set the anchor manually.
 * 2. ``no_tilesets`` — anchor is set but no 3D Tiles have been generated.
 *    CTA: jump to BIM Hub to convert + send a model to the map.
 * 3. ``all_failed`` — at least one tileset exists, all are in failed state.
 *    CTA: jobs/status page so the user can investigate.
 *
 * Visually elevated — the empty state sits *over* the dark Cesium globe
 * background so we use a translucent surface card rather than the flat
 * surface used by the shared ``EmptyState`` component.
 */

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import {
  MapPin,
  Layers,
  AlertTriangle,
  ArrowUpRight,
  Loader2,
  Sparkles,
  Plus,
  X,
  ChevronUp,
  type LucideIcon,
} from 'lucide-react';

import { ApiError } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { autoAnchorFromAddress } from './api';

export type GeoEmptyKind = 'no_anchor' | 'no_tilesets' | 'all_failed';

interface GeoEmptyStateProps {
  kind: GeoEmptyKind;
  projectId?: string | null;
  /** Optional callback invoked after a successful auto-anchor so the
   *  parent can re-fetch the map config without forcing the user to
   *  reload the page. */
  onAnchored?: () => void;
  /** Optional - when provided on the ``no_tilesets`` state, the primary
   *  CTA opens the in-place "Place on map" picker (existing project files)
   *  instead of only linking out to BIM Hub. */
  onPlaceOnMap?: () => void;
  /** Optional - when provided on the ``no_anchor`` state, the "Set anchor
   *  manually" CTA turns on in-map pin placement (click the map to drop
   *  the anchor) instead of navigating away to the project settings page.
   *  The reporter's bug (#284) was exactly that the manual-anchor button
   *  redirected to the project page rather than letting them place a pin. */
  onPlaceManually?: () => void;
}

interface Variant {
  icon: LucideIcon;
  title: string;
  description: string;
  ctaLabel: string;
  ctaHref: string | null;
  tone: 'info' | 'warning' | 'danger';
}

const TONE_RING: Record<Variant['tone'], string> = {
  info: 'from-blue-500/30 to-cyan-500/20 ring-blue-400/20',
  warning: 'from-amber-500/30 to-orange-500/20 ring-amber-400/20',
  danger: 'from-red-500/30 to-rose-500/20 ring-red-400/20',
};

const TONE_ICON_BG: Record<Variant['tone'], string> = {
  info: 'bg-blue-500/15 text-blue-300 ring-blue-400/30',
  warning: 'bg-amber-500/15 text-amber-300 ring-amber-400/30',
  danger: 'bg-red-500/15 text-red-300 ring-red-400/30',
};

export function GeoEmptyState({
  kind,
  projectId,
  onAnchored,
  onPlaceOnMap,
  onPlaceManually,
}: GeoEmptyStateProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [isAnchoring, setIsAnchoring] = useState(false);
  // The centered card sits over the middle of the globe; for the no-anchor
  // state (the reporter's masked-map complaint, #284) the user can tuck it
  // away to a small corner pill so it stops covering the map while they
  // pan/zoom to eyeball where the project should sit. Kept as transient
  // view state (not persisted) so the anchoring CTA is never permanently
  // hidden - it returns on the next page open. Only the no-anchor variant
  // is dismissible; no_tilesets / all_failed always show their card.
  const [dismissed, setDismissed] = useState(false);
  const collapsible = kind === 'no_anchor';

  async function runAutoAnchor() {
    if (!projectId || isAnchoring) return;
    setIsAnchoring(true);
    try {
      await autoAnchorFromAddress(projectId);
      addToast({
        type: 'success',
        title: t('geo_hub.auto_anchor.success_title', {
          defaultValue: 'Project anchored on the map',
        }),
        message: t('geo_hub.auto_anchor.success_message', {
          defaultValue:
            'We placed your project at the geocoded address. Drag the marker to fine-tune.',
        }),
      });
      // Refetch the map config so the globe shows the new anchor without
      // a full page reload.
      await queryClient.invalidateQueries({
        queryKey: ['geo-hub', 'map-config', projectId],
      });
      onAnchored?.();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 422) {
          addToast({
            type: 'warning',
            title: t('geo_hub.auto_anchor.address_missing_title', {
              defaultValue: 'Add a project address first',
            }),
            message: t('geo_hub.auto_anchor.address_missing_message', {
              defaultValue:
                'Open the project settings and fill in the address (country is required) before auto-anchoring.',
            }),
          });
          // Jump to settings so the user can complete the address in one click.
          if (projectId) navigate(`/projects/${projectId}/settings`);
          return;
        }
        if (err.status === 409) {
          addToast({
            type: 'info',
            title: t('geo_hub.auto_anchor.already_anchored_title', {
              defaultValue: 'Project already anchored',
            }),
            message: t('geo_hub.auto_anchor.already_anchored_message', {
              defaultValue:
                'Open the project map and use Re-geocode if you want to overwrite the existing anchor.',
            }),
          });
          await queryClient.invalidateQueries({
            queryKey: ['geo-hub', 'map-config', projectId],
          });
          onAnchored?.();
          return;
        }
        if (err.status === 502) {
          addToast({
            type: 'error',
            title: t('geo_hub.auto_anchor.unavailable_title', {
              defaultValue: 'Geocoder unavailable',
            }),
            message: t('geo_hub.auto_anchor.unavailable_message', {
              defaultValue:
                'The address service did not respond. Try again later or anchor the project manually.',
            }),
          });
          return;
        }
      }
      addToast({
        type: 'error',
        title: t('geo_hub.auto_anchor.error_title', {
          defaultValue: 'Auto-anchor failed',
        }),
      });
    } finally {
      setIsAnchoring(false);
    }
  }

  const variants: Record<GeoEmptyKind, Variant> = {
    no_anchor: {
      icon: MapPin,
      tone: 'info',
      title: t('geo_hub.empty.no_anchor_title', {
        defaultValue: 'Anchor this project on the map',
      }),
      description: onPlaceManually
        ? t('geo_hub.empty.no_anchor_description_v3', {
            defaultValue:
              'Auto-anchor from the address you set in project settings, or place a pin directly on the map. You can fine-tune by dragging once the pin lands.',
          })
        : t('geo_hub.empty.no_anchor_description_v2', {
            defaultValue:
              'Auto-anchor from the address you set in project settings, or pick a coordinate manually. You can fine-tune by dragging once the pin lands.',
          }),
      ctaLabel: t('geo_hub.empty.no_anchor_manual_cta', {
        defaultValue: 'Set anchor manually',
      }),
      // When the page wires ``onPlaceManually`` the manual CTA places a pin
      // in-map (rendered as a button below); the settings link is only the
      // fallback for callers that don't. Keeping the link as the fallback
      // means the legacy "edit the address in settings" path still exists.
      ctaHref: onPlaceManually
        ? null
        : projectId
          ? `/projects/${projectId}/settings`
          : null,
    },
    no_tilesets: {
      icon: Layers,
      tone: 'warning',
      title: t('geo_hub.empty.no_tilesets_title', {
        defaultValue: 'Nothing on the map yet',
      }),
      description: t('geo_hub.empty.no_tilesets_description_v2', {
        defaultValue:
          'The project is anchored but no file is on the map. Place an existing model or PDF drawing, or convert a new BIM model in BIM Hub.',
      }),
      ctaLabel: t('geo_hub.empty.no_tilesets_cta_v2', {
        defaultValue: 'Convert a new model in BIM Hub',
      }),
      ctaHref: projectId ? `/projects/${projectId}/bim` : '/bim',
    },
    all_failed: {
      icon: AlertTriangle,
      tone: 'danger',
      title: t('geo_hub.empty.all_failed_title', {
        defaultValue: 'Every tileset failed to generate',
      }),
      description: t('geo_hub.empty.all_failed_description', {
        defaultValue:
          'No tileset is currently servable. Inspect the job log to diagnose the converter error and rerun the failed tiles.',
      }),
      ctaLabel: t('geo_hub.empty.all_failed_cta', {
        defaultValue: 'Open conversion jobs',
      }),
      ctaHref: projectId
        ? `/projects/${projectId}/bim?tab=conversions`
        : '/bim',
    },
  };

  const v = variants[kind];
  const Icon = v.icon;
  const showAutoAnchor = kind === 'no_anchor' && Boolean(projectId);
  const showPlaceButton = kind === 'no_tilesets' && Boolean(onPlaceOnMap);
  // In-map manual placement for the no-anchor state (#284): the user drops
  // the pin by clicking the map instead of being bounced to settings.
  const showPlaceManually = kind === 'no_anchor' && Boolean(onPlaceManually);
  const hasPrimaryAction = showAutoAnchor || showPlaceButton || showPlaceManually;

  // Dismissed no-anchor card -> bottom-centre pill clear of the corner
  // chrome (tileset sidebar / overlay panel / HUD). Tapping it restores the
  // full anchoring prompt.
  if (collapsible && dismissed) {
    return (
      <div className="pointer-events-none absolute inset-x-0 bottom-3 z-10 flex justify-center px-3">
        <button
          type="button"
          onClick={() => setDismissed(false)}
          className={[
            'pointer-events-auto inline-flex items-center gap-2 rounded-full',
            'border border-white/15 bg-slate-900/85 px-3 py-1.5',
            'text-xs font-medium text-white shadow-lg shadow-black/20 backdrop-blur-md',
            'ring-1 ring-white/5 transition hover:bg-slate-800/90',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300',
          ].join(' ')}
          aria-expanded={false}
          data-testid="geo-empty-pill"
        >
          <MapPin size={13} strokeWidth={2} className="text-blue-300" />
          {t('geo_hub.empty.no_anchor_pill', {
            defaultValue: 'Anchor this project',
          })}
          <ChevronUp size={13} strokeWidth={2.25} className="text-white/70" />
        </button>
      </div>
    );
  }

  return (
    <div
      className={
        // The no-anchor prompt docks to the top-left as a side panel so the map
        // stays visible behind it (#288: the centred card used to cover the
        // whole map). Other empty states stay centred.
        collapsible
          ? 'pointer-events-none absolute left-3 top-3 z-10 w-full max-w-xs sm:max-w-sm'
          : 'pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6'
      }
    >
      <div
        className={[
          `pointer-events-auto relative w-full overflow-hidden ${collapsible ? '' : 'max-w-md'}`,
          'rounded-xl border border-white/10 bg-slate-900/70 p-6 text-slate-100',
          'shadow-xl backdrop-blur-md ring-1 ring-white/5',
        ].join(' ')}
        role="status"
      >
        {/* Soft tinted glow ring matching tone */}
        <div
          aria-hidden
          className={[
            'pointer-events-none absolute -inset-px rounded-xl bg-gradient-to-br opacity-60 blur-2xl ring-1',
            TONE_RING[v.tone],
          ].join(' ')}
        />
        {collapsible && (
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className={[
              'absolute right-2 top-2 z-10 inline-flex h-7 w-7 items-center justify-center rounded-md',
              'text-slate-400 transition hover:bg-white/10 hover:text-slate-100',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60',
            ].join(' ')}
            aria-label={t('geo_hub.empty.dismiss', {
              defaultValue: 'Hide and show the map',
            })}
            data-testid="geo-empty-dismiss"
          >
            <X size={15} strokeWidth={2.25} />
          </button>
        )}
        <div className="relative">
          <div
            className={[
              'mb-4 inline-flex h-10 w-10 items-center justify-center rounded-md ring-1',
              TONE_ICON_BG[v.tone],
            ].join(' ')}
          >
            <Icon size={18} strokeWidth={2} />
          </div>
          <h3 className="text-base font-semibold text-white">{v.title}</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-300">
            {v.description}
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            {showAutoAnchor && (
              <button
                type="button"
                onClick={runAutoAnchor}
                disabled={isAnchoring}
                data-testid="geo-empty-auto-anchor"
                className={[
                  'inline-flex items-center gap-1.5 rounded-md',
                  'bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-white',
                  'shadow-sm transition hover:bg-emerald-400',
                  'disabled:cursor-wait disabled:opacity-70',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/70',
                ].join(' ')}
              >
                {isAnchoring ? (
                  <Loader2 size={13} strokeWidth={2.25} className="animate-spin" />
                ) : (
                  <Sparkles size={13} strokeWidth={2.25} />
                )}
                {t('geo_hub.empty.auto_anchor_cta', {
                  defaultValue: 'Auto-anchor from project address',
                })}
              </button>
            )}
            {showPlaceButton && (
              <button
                type="button"
                onClick={onPlaceOnMap}
                data-testid="geo-empty-place-on-map"
                className={[
                  'inline-flex items-center gap-1.5 rounded-md',
                  'bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-white',
                  'shadow-sm transition hover:bg-emerald-400',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/70',
                ].join(' ')}
              >
                <Plus size={13} strokeWidth={2.25} />
                {t('geo_hub.empty.place_existing_cta', {
                  defaultValue: 'Place a project file on the map',
                })}
              </button>
            )}
            {showPlaceManually && (
              <button
                type="button"
                onClick={onPlaceManually}
                data-testid="geo-empty-place-manually"
                className={[
                  'inline-flex items-center gap-1.5 rounded-md',
                  // Secondary to the emerald auto-anchor button: this is the
                  // "I'll point at it myself" alternative, not the default.
                  'border border-white/15 bg-white/5 px-3 py-1.5',
                  'text-xs font-semibold text-white shadow-sm transition hover:bg-white/10',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60',
                ].join(' ')}
              >
                <MapPin size={13} strokeWidth={2.25} />
                {t('geo_hub.empty.place_manually_cta', {
                  defaultValue: 'Place a pin on the map',
                })}
              </button>
            )}
            {v.ctaHref && (
              <Link
                to={v.ctaHref}
                className={[
                  'inline-flex items-center gap-1.5 rounded-md',
                  hasPrimaryAction
                    ? 'border border-white/15 bg-white/5 text-white hover:bg-white/10'
                    : 'bg-white text-slate-900 hover:bg-slate-100',
                  'px-3 py-1.5 text-xs font-semibold shadow-sm transition',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60',
                ].join(' ')}
              >
                {v.ctaLabel}
                <ArrowUpRight size={13} strokeWidth={2.25} />
              </Link>
            )}
          </div>
          {kind === 'no_anchor' && (
            <p className="mt-3 text-2xs text-slate-400">
              {t('geo_hub.empty.auto_anchor_attribution', {
                defaultValue:
                  'Geocoded via OpenStreetMap Nominatim. Cached for 30 days.',
              })}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default GeoEmptyState;
