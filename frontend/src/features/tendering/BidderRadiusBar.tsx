// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Trade, radius and favourites filter for the bidder picker.
 *
 * Distance is measured from the project site anchor to each firm's stored
 * coordinates. Firms without coordinates are never hidden by the radius: the
 * picker says they have none rather than pretending they are far away.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MapPin, Star } from 'lucide-react';
import {
  addFavourite,
  removeFavourite,
  searchBidders,
  type BidderRow,
  type BidderSearch,
} from '@/features/subcontractors/termsApi';

export const RADIUS_CHOICES = [25, 50, 100, 200] as const;

export interface BidderFilterState {
  trade: string;
  radiusKm: number | null;
  favouritesOnly: boolean;
  includeOutside: boolean;
}

/** True when the filter narrows the directory, so rows must come from the search. */
export function isFiltering(state: BidderFilterState): boolean {
  return state.radiusKm !== null || state.favouritesOnly || state.trade !== '';
}

/** Keep and order directory rows by the search result; unfiltered rows pass through. */
export function applyBidderSearch<T extends { id: string }>(
  rows: T[],
  state: BidderFilterState,
  search: BidderSearch | undefined,
): T[] {
  if (!search || !isFiltering(state)) return rows;
  const order = new Map(search.items.map((b, i) => [b.id, i]));
  return rows.filter((r) => order.has(r.id)).sort((a, b) => order.get(a.id)! - order.get(b.id)!);
}

export function useBidderFilter(projectId: string | undefined) {
  const [state, setState] = useState<BidderFilterState>({
    trade: '',
    radiusKm: null,
    favouritesOnly: false,
    includeOutside: false,
  });
  const query = useQuery({
    queryKey: ['tendering', 'bidder-search', projectId, state],
    queryFn: () =>
      searchBidders({
        project_id: projectId!,
        trade: state.trade || undefined,
        radius_km: state.radiusKm,
        favourites_only: state.favouritesOnly,
        include_outside: state.includeOutside,
      }),
    enabled: !!projectId,
    staleTime: 30_000,
  });
  const byId = useMemo(
    () => new Map<string, BidderRow>((query.data?.items ?? []).map((b) => [b.id, b])),
    [query.data],
  );
  return { state, setState, search: query.data, byId };
}

export function BidderRadiusBar({
  state,
  setState,
  search,
  trades,
}: {
  state: BidderFilterState;
  setState: (s: BidderFilterState) => void;
  search: BidderSearch | undefined;
  trades: string[];
}) {
  const { t } = useTranslation();
  const selectCls =
    'h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30';
  const noSite = state.radiusKm !== null && search && !search.site_has_coordinates;
  return (
    <div className="space-y-2" data-testid="bidder-radius-bar">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t('tendering.bidder_trade', { defaultValue: 'Trade' })}
          value={state.trade}
          onChange={(e) => setState({ ...state, trade: e.target.value })}
          className={selectCls}
        >
          <option value="">{t('tendering.bidder_all_trades', { defaultValue: 'All trades' })}</option>
          {trades.map((tr) => (
            <option key={tr} value={tr}>
              {tr}
            </option>
          ))}
        </select>
        <select
          aria-label={t('tendering.bidder_radius', { defaultValue: 'Distance from site' })}
          value={state.radiusKm ?? ''}
          onChange={(e) => setState({ ...state, radiusKm: e.target.value ? Number(e.target.value) : null })}
          className={selectCls}
        >
          <option value="">{t('tendering.bidder_any_distance', { defaultValue: 'Any distance' })}</option>
          {RADIUS_CHOICES.map((km) => (
            <option key={km} value={km}>
              {t('tendering.bidder_within_km', { defaultValue: 'Within {{km}} km', km })}
            </option>
          ))}
        </select>
        <label className="inline-flex items-center gap-1.5 text-sm text-content-secondary">
          <input
            type="checkbox"
            checked={state.favouritesOnly}
            onChange={(e) => setState({ ...state, favouritesOnly: e.target.checked })}
          />
          {t('tendering.bidder_favourites_only', { defaultValue: 'Favourites only' })}
        </label>
        {state.radiusKm !== null && (
          <label className="inline-flex items-center gap-1.5 text-sm text-content-secondary">
            <input
              type="checkbox"
              checked={state.includeOutside}
              onChange={(e) => setState({ ...state, includeOutside: e.target.checked })}
            />
            {t('tendering.bidder_include_outside', { defaultValue: 'Also show firms outside the radius' })}
          </label>
        )}
      </div>
      {noSite && (
        <p className="text-xs text-amber-700 dark:text-amber-400" data-testid="bidder-no-site">
          {t('tendering.bidder_no_site_coords', {
            defaultValue:
              'The project site has no coordinates yet, so distances cannot be measured. Set the site location in the project map.',
          })}
        </p>
      )}
      {search && state.radiusKm !== null && search.without_coordinates > 0 && (
        <p className="text-xs text-content-tertiary">
          {t('tendering.bidder_without_coords', {
            defaultValue: '{{count}} firms have no coordinates and stay in the list.',
            count: search.without_coordinates,
          })}
        </p>
      )}
    </div>
  );
}

/** Distance or "no coordinates", plus the per-trade favourite star. */
export function BidderRowMeta({ row, trade }: { row: BidderRow | undefined; trade: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: () => (row!.is_favourite ? removeFavourite(row!.id, trade) : addFavourite(row!.id, trade)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tendering', 'bidder-search'] }),
  });
  if (!row) return null;
  return (
    <span className="flex shrink-0 items-center gap-2 text-xs text-content-tertiary">
      <span className="inline-flex items-center gap-1" data-testid="bidder-distance">
        <MapPin size={12} />
        {row.distance_km !== null
          ? t('tendering.bidder_km', { defaultValue: '{{km}} km', km: Math.round(Number(row.distance_km)) })
          : t('tendering.bidder_no_coords', { defaultValue: 'no coordinates' })}
      </span>
      {row.within_radius === false && (
        <span className="rounded bg-surface-secondary px-1.5 py-0.5">
          {t('tendering.bidder_outside', { defaultValue: 'outside radius' })}
        </span>
      )}
      {trade && (
        <span
          role="button"
          tabIndex={0}
          aria-label={t('tendering.bidder_favourite_toggle', { defaultValue: 'Favourite for this trade' })}
          aria-pressed={row.is_favourite}
          onClick={(e) => {
            e.stopPropagation();
            toggle.mutate();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              e.stopPropagation();
              toggle.mutate();
            }
          }}
          className="cursor-pointer"
        >
          <Star size={14} className={row.is_favourite ? 'fill-amber-400 text-amber-500' : ''} />
        </span>
      )}
    </span>
  );
}
