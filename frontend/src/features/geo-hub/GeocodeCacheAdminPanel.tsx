// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * <GeocodeCacheAdminPanel> — admin-only widget for the Geo Hub.
 *
 * Renders aggregate Nominatim cache stats + a "Clear stale (30d+)" CTA
 * that proxies the new ``DELETE /api/v1/geo-hub/geocode/cache`` admin
 * endpoint. Wrapped in ``<AdminOnly>`` so it never appears for regular
 * users — and the backend RBAC remains the real authority.
 *
 * Mountable as a panel inside Settings or as a standalone route. Stays
 * compact (under 200px tall) so it composes with the existing Geo Hub
 * page layouts without claiming the whole canvas.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Database,
  Loader2,
  RefreshCw,
  Trash2,
} from 'lucide-react';

import { ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

import { getGeocodeCacheStats, purgeGeocodeCache } from './api';
import { getIntlLocale } from '@/shared/lib/formatters';

function fmtTimestamp(ts: string | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString(getIntlLocale());
}

function PanelBody() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [isPurging, setIsPurging] = useState(false);

  const statsQuery = useQuery({
    queryKey: ['geo-hub', 'geocode-cache-stats'],
    queryFn: getGeocodeCacheStats,
    staleTime: 60_000,
    retry: 1,
  });

  async function purge(olderDays: number) {
    if (isPurging) return;
    setIsPurging(true);
    try {
      const res = await purgeGeocodeCache(olderDays);
      addToast({
        type: 'success',
        title: t('geo_hub.cache_admin.purge_success', {
          defaultValue: 'Purged {{count}} cache rows',
          count: res.deleted,
        }),
      });
      await queryClient.invalidateQueries({
        queryKey: ['geo-hub', 'geocode-cache-stats'],
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        addToast({
          type: 'error',
          title: t('geo_hub.cache_admin.purge_forbidden', {
            defaultValue: 'You do not have permission to purge the cache',
          }),
        });
      } else {
        addToast({
          type: 'error',
          title: t('geo_hub.cache_admin.purge_failed', {
            defaultValue: 'Cache purge failed',
          }),
        });
      }
    } finally {
      setIsPurging(false);
    }
  }

  const stats = statsQuery.data;
  return (
    <section
      aria-label={t('geo_hub.cache_admin.aria', {
        defaultValue: 'Geocode cache admin',
      })}
      className={[
        'rounded-lg border border-border bg-surface-primary p-4',
        'shadow-sm',
      ].join(' ')}
      data-testid="geo-cache-admin-panel"
    >
      <header className="flex items-center gap-2">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-oe-blue/10 text-oe-blue">
          <Database size={15} strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('geo_hub.cache_admin.title', {
              defaultValue: 'Nominatim geocode cache',
            })}
          </h3>
          <p className="text-2xs text-content-tertiary">
            {t('geo_hub.cache_admin.subtitle', {
              defaultValue:
                'Address-to-coords lookups cached for 30 days. Admin-only.',
            })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => statsQuery.refetch()}
          disabled={statsQuery.isFetching}
          className={[
            'inline-flex h-8 w-8 items-center justify-center rounded-md',
            'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
            'disabled:opacity-50',
          ].join(' ')}
          aria-label={t('common.refresh', { defaultValue: 'Refresh' })}
        >
          {statsQuery.isFetching ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <RefreshCw size={13} strokeWidth={2} />
          )}
        </button>
      </header>

      {statsQuery.isLoading && (
        <div className="mt-3 flex items-center gap-2 text-xs text-content-tertiary">
          <Loader2 size={13} className="animate-spin" />
          <span>
            {t('geo_hub.cache_admin.loading', {
              defaultValue: 'Loading cache stats…',
            })}
          </span>
        </div>
      )}
      {statsQuery.isError && !statsQuery.isLoading && (
        <p className="mt-3 text-xs text-red-600">
          {t('geo_hub.cache_admin.stats_error', {
            defaultValue: 'Could not load cache stats',
          })}
        </p>
      )}
      {stats && (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
          <div>
            <dt className="text-2xs uppercase tracking-[0.12em] text-content-tertiary">
              {t('geo_hub.cache_admin.total', { defaultValue: 'Total' })}
            </dt>
            <dd className="font-mono tabular-nums text-content-primary">
              {stats.total}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-[0.12em] text-content-tertiary">
              {t('geo_hub.cache_admin.fresh', { defaultValue: 'Fresh' })}
            </dt>
            <dd className="font-mono tabular-nums text-emerald-600">
              {stats.fresh}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-[0.12em] text-content-tertiary">
              {t('geo_hub.cache_admin.stale', { defaultValue: 'Stale' })}
            </dt>
            <dd className="font-mono tabular-nums text-amber-600">
              {stats.stale}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-[0.12em] text-content-tertiary">
              {t('geo_hub.cache_admin.hits', { defaultValue: 'Total hits' })}
            </dt>
            <dd className="font-mono tabular-nums text-content-primary">
              {stats.hit_sum}
            </dd>
          </div>
          <div className="col-span-2">
            <dt className="text-2xs uppercase tracking-[0.12em] text-content-tertiary">
              {t('geo_hub.cache_admin.oldest', { defaultValue: 'Oldest entry' })}
            </dt>
            <dd className="text-xs text-content-secondary">
              {fmtTimestamp(stats.oldest_cached_at)}
            </dd>
          </div>
          <div className="col-span-2">
            <dt className="text-2xs uppercase tracking-[0.12em] text-content-tertiary">
              {t('geo_hub.cache_admin.newest', { defaultValue: 'Newest entry' })}
            </dt>
            <dd className="text-xs text-content-secondary">
              {fmtTimestamp(stats.newest_cached_at)}
            </dd>
          </div>
        </dl>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border-light pt-3">
        <button
          type="button"
          onClick={() => purge(30)}
          disabled={isPurging}
          className={[
            'inline-flex items-center gap-1 rounded-md border border-border',
            'bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-primary',
            'hover:bg-surface-secondary disabled:cursor-wait disabled:opacity-70',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
          ].join(' ')}
          data-testid="geo-cache-admin-purge-stale"
        >
          {isPurging ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Trash2 size={12} strokeWidth={2.25} />
          )}
          {t('geo_hub.cache_admin.purge_stale', {
            defaultValue: 'Clear stale (30d+)',
          })}
        </button>
        <button
          type="button"
          onClick={() => {
            if (
              !window.confirm(
                t('geo_hub.cache_admin.purge_all_confirm', {
                  defaultValue:
                    'Delete every cached geocode? Future lookups will hit Nominatim again.',
                }),
              )
            ) {
              return;
            }
            purge(0);
          }}
          disabled={isPurging}
          className={[
            'inline-flex items-center gap-1 rounded-md',
            'border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700',
            'hover:bg-red-50 disabled:cursor-wait disabled:opacity-70',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-red-300',
          ].join(' ')}
          data-testid="geo-cache-admin-purge-all"
        >
          <Trash2 size={12} strokeWidth={2.25} />
          {t('geo_hub.cache_admin.purge_all', {
            defaultValue: 'Clear everything',
          })}
        </button>
        <span className="ml-auto text-2xs text-content-tertiary">
          {t('geo_hub.cache_admin.policy_hint', {
            defaultValue:
              'Per Nominatim policy: cached 30 days, 1 req/sec, public service only.',
          })}
        </span>
      </div>
    </section>
  );
}

/**
 * Inline admin gate — unlike ``<AdminOnly>`` (which redirects to /404
 * for whole routes), this returns ``null`` so the panel is invisible
 * to non-admins but the page hosting it doesn't 404. Backend RBAC
 * (``geo_hub.admin``) remains the real authority on every cache call.
 */
export function GeocodeCacheAdminPanel() {
  const userRole = useAuthStore((s) => s.userRole);
  if (userRole !== 'admin') return null;
  return <PanelBody />;
}

export default GeocodeCacheAdminPanel;
