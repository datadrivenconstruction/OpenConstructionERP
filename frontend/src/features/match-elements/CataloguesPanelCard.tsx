/**
 * CataloguesPanelCard — collapsible panel surfacing the 30 CWICR v3
 * catalogues so users can see what's loaded vs available and install
 * missing language/region snapshots without leaving /match-elements.
 *
 * Solves the "only Russian candidates show up" problem documented in
 * the v2.9.34 handover (#236): when only `cwicr_ru_v3` happens to be
 * loaded on the server, auto_bind picks it for every project regardless
 * of region, so a US/DE/UK project sees Russian rates. Letting the user
 * one-click install the matching catalogue is the obvious fix.
 *
 * Backend wiring (already in place, see backend/app/modules/costs/router.py):
 *   GET  /api/v1/costs/catalogues-v3/                 — list with status
 *   POST /api/v1/costs/catalogues-v3/{region}/install — download + restore
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCatalogueInstallStore } from '@/stores/useCatalogueInstallStore';
import {
  Database,
  ChevronDown,
  ChevronUp,
  Download,
  CheckCircle2,
  Loader2,
  Clock,
  AlertCircle,
} from 'lucide-react';
import clsx from 'clsx';
import { CountryFlag, originFlagCode } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';

// ── Types ────────────────────────────────────────────────────────────────
//
// Mirrors the catalogue dict produced by `list_v3_catalogues` in the
// backend (router.py:1660). Keep this in sync when adding fields.

type InstallStatus = 'loaded' | 'available' | 'installing' | 'coming_soon';

interface Catalogue {
  region: string;
  country_iso: string;
  city: string;
  language: string;
  currency: string;
  collection: string;
  size_mb: number;
  available: boolean;
  snapshot_cached: boolean;
  install_status: InstallStatus;
}

interface ServerInfo {
  url: string | null;
  reachable: boolean;
  total_collections: number;
  v3_collections: string[];
}

interface CataloguesResponse {
  catalogues: Catalogue[];
  server: ServerInfo;
}

// ── API helpers ──────────────────────────────────────────────────────────

export async function fetchCatalogues(): Promise<CataloguesResponse> {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch('/api/v1/costs/catalogues-v3/', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`catalogues-v3 ${res.status}`);
  return res.json();
}

export type { Catalogue, CataloguesResponse, InstallStatus };

// ── Sub-components ───────────────────────────────────────────────────────

function StatusBadge({ status }: { status: InstallStatus }) {
  const { t } = useTranslation();
  const config: Record<
    InstallStatus,
    { icon: typeof CheckCircle2; cls: string; label: string }
  > = {
    loaded: {
      icon: CheckCircle2,
      cls: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200 border-emerald-200 dark:border-emerald-700',
      label: t('catalogues.status_loaded', 'Loaded'),
    },
    installing: {
      icon: Loader2,
      cls: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200 border-sky-200 dark:border-sky-700',
      label: t('catalogues.status_installing', 'Installing…'),
    },
    available: {
      icon: Download,
      cls: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200 border-amber-200 dark:border-amber-700',
      label: t('catalogues.status_available', 'Available'),
    },
    coming_soon: {
      icon: Clock,
      cls: 'bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300 border-slate-200 dark:border-slate-700',
      label: t('catalogues.status_coming_soon', 'Coming soon'),
    },
  };
  const { icon: Icon, cls, label } = config[status];
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium',
        cls,
      )}
    >
      <Icon
        size={10}
        className={status === 'installing' ? 'animate-spin' : ''}
      />
      {label}
    </span>
  );
}

function InstallButton({
  region,
  status,
  isPending,
  onInstall,
}: {
  region: string;
  status: InstallStatus;
  isPending: boolean;
  onInstall: () => void;
}) {
  const { t } = useTranslation();
  if (status === 'loaded') {
    return (
      <span className="text-[11px] text-content-tertiary">
        {t('catalogues.installed_hint', 'Ready to use')}
      </span>
    );
  }
  if (status === 'coming_soon') {
    return (
      <span className="text-[11px] text-content-quaternary italic">
        {t('catalogues.coming_soon_hint', 'Not yet published by DDC')}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={onInstall}
      disabled={isPending}
      className={clsx(
        'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium',
        'bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60',
        'transition-colors',
      )}
      aria-label={t('catalogues.install_aria', 'Install catalogue {{region}}', {
        region,
      })}
    >
      {isPending ? (
        <Loader2 size={11} className="animate-spin" />
      ) : (
        <Download size={11} />
      )}
      {isPending
        ? t('catalogues.installing_button', 'Installing…')
        : t('catalogues.install_button', 'Install')}
    </button>
  );
}

// ── Main card ────────────────────────────────────────────────────────────

interface Props {
  /** Optional — when present and matches a catalogue.region, the card
   *  pins that row to the top so the project's expected catalogue is
   *  always one click away. */
  preferredRegion?: string | null;
}

export function CataloguesPanelCard({ preferredRegion }: Props) {
  const { t } = useTranslation();
  const { addToast } = useToastStore();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const cataloguesQ = useQuery({
    queryKey: ['catalogues-v3'],
    queryFn: fetchCatalogues,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  // Install jobs live in a global Zustand store so the download survives
  // route changes — the user can kick off an install on /match-elements,
  // navigate to another page, and a floating dock pill keeps them
  // informed. The local component still subscribes to the store to
  // surface per-row spinner state.
  const installJobs = useCatalogueInstallStore((s) => s.jobs);
  const startInstall = useCatalogueInstallStore((s) => s.startInstall);

  const handleInstall = useCallback(
    (cat: Catalogue) => {
      startInstall(
        {
          region: cat.region,
          label: `${cat.country_iso} · ${cat.city}`,
          language: cat.language,
          sizeMb: cat.size_mb,
        },
        {
          onSuccess: async (region) => {
            addToast({
              type: 'success',
              title: t('catalogues.install_success_title', 'Catalogue installed'),
              message: t(
                'catalogues.install_success_body',
                'Region {{region}} is now ready. Re-bind the project to use it.',
                { region },
              ),
            });
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ['catalogues-v3'] }),
              queryClient.invalidateQueries({
                queryKey: ['match-vector-readiness'],
              }),
            ]);
          },
          onError: (region, error) => {
            addToast({
              type: 'error',
              title: t('catalogues.install_failed_title', 'Install failed'),
              message: t(
                'catalogues.install_failed_body',
                'Could not install {{region}}: {{error}}',
                { region, error },
              ),
            });
          },
        },
      );
    },
    [startInstall, addToast, t, queryClient],
  );

  // Pull `catalogues` once with an Array.isArray guard so every consumer
  // (sorted/stats/auto-open effect) receives a real array even when the
  // cached `data` is a bare list, an envelope, an error body, or null
  // (cross-version cache rehydrate / queryFn shape drift). Fixes
  // "p.data.filter is not a function" (#124).
  const catalogues: Catalogue[] = useMemo(() => {
    const raw = cataloguesQ.data as unknown;
    if (Array.isArray(raw)) return raw as Catalogue[];
    if (raw && typeof raw === 'object' && Array.isArray((raw as { catalogues?: unknown }).catalogues)) {
      return (raw as { catalogues: Catalogue[] }).catalogues;
    }
    return [];
  }, [cataloguesQ.data]);

  // Sort with preferred region first, then by status order, then alpha.
  // Server already pre-sorts by status — we only re-pin the project's
  // expected region so the install path is one scroll away.
  const sorted = useMemo<Catalogue[]>(() => {
    if (!preferredRegion) return catalogues;
    const idx = catalogues.findIndex((c) => c.region === preferredRegion);
    if (idx <= 0) return catalogues;
    const pinned = catalogues[idx];
    if (!pinned) return catalogues;
    return [pinned, ...catalogues.slice(0, idx), ...catalogues.slice(idx + 1)];
  }, [catalogues, preferredRegion]);

  const stats = useMemo(() => {
    return {
      loaded: catalogues.filter((c) => c.install_status === 'loaded').length,
      available: catalogues.filter((c) => c.install_status === 'available').length,
      coming: catalogues.filter((c) => c.install_status === 'coming_soon').length,
      total: catalogues.length,
    };
  }, [catalogues]);

  const handleToggle = useCallback(() => setOpen((o) => !o), []);

  // Auto-open the panel once if the project region's catalogue isn't
  // loaded — this is the user's most likely path to fixing "I only
  // see Russian candidates" and the panel being collapsed hides it.
  // The ref guard ensures we only auto-open once per mount, so user
  // collapse intentions stick.
  const autoOpenedRef = useRef(false);
  useEffect(() => {
    if (autoOpenedRef.current) return;
    if (!preferredRegion) return;
    if (catalogues.length === 0) return;
    const target = catalogues.find((c) => c.region === preferredRegion);
    if (target && target.install_status === 'available') {
      setOpen(true);
      autoOpenedRef.current = true;
    }
  }, [preferredRegion, catalogues]);

  // Failure path — keep silent / minimal so a borked endpoint doesn't
  // break the rest of /match-elements.
  if (cataloguesQ.isError) {
    return null;
  }

  return (
    <section
      className="rounded-xl border border-border bg-surface-primary shadow-sm"
      aria-label={t('catalogues.section_label', 'Cost catalogues')}
    >
      <button
        type="button"
        onClick={handleToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-surface-secondary/50 transition-colors rounded-xl"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="shrink-0 w-9 h-9 rounded-lg bg-gradient-to-br from-emerald-100 to-sky-100 dark:from-emerald-900/40 dark:to-sky-900/30 border border-emerald-200 dark:border-emerald-800 flex items-center justify-center">
            <Database className="w-4 h-4 text-emerald-600 dark:text-emerald-300" />
          </div>
          <div className="min-w-0">
            <div className="text-xs font-semibold text-content-primary">
              {t('catalogues.title', 'Cost catalogues')}
            </div>
            <div className="text-[11px] text-content-tertiary truncate">
              {cataloguesQ.isLoading ? (
                t('catalogues.loading', 'Checking server…')
              ) : (
                <>
                  <span className="text-emerald-700 dark:text-emerald-300 font-medium">
                    {stats.loaded}
                  </span>{' '}
                  {t('catalogues.stat_loaded', 'loaded')} ·{' '}
                  <span className="text-amber-700 dark:text-amber-300 font-medium">
                    {stats.available}
                  </span>{' '}
                  {t('catalogues.stat_available', 'available')} ·{' '}
                  {stats.total}{' '}
                  {t('catalogues.stat_total', 'total regions')}
                </>
              )}
            </div>
          </div>
        </div>
        <span className="shrink-0 text-content-tertiary">
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </span>
      </button>

      {open && (
        <div className="relative border-t border-border px-4 py-3">
          {/* Top-of-card progress strip — visible while React Query is
              fetching (initial load OR an install-triggered refetch) and
              while ANY install is mid-flight (the floating dock shows the
              detailed view, this is the in-card hint). Without this the
              long-running install (30–120 s) gives no feedback past the
              tiny spinner inside the row's button. */}
          {(cataloguesQ.isFetching ||
            Array.from(installJobs.values()).some(
              (j) => j.status === 'downloading',
            )) && (
            <div
              role="progressbar"
              aria-busy="true"
              aria-label={
                Array.from(installJobs.values()).some(
                  (j) => j.status === 'downloading',
                )
                  ? t('catalogues.install_progress', 'Installing catalogue…')
                  : t('catalogues.refresh_progress', 'Refreshing catalogues…')
              }
              className="pointer-events-none absolute top-0 left-0 right-0 h-0.5 overflow-hidden bg-indigo-500/15"
            >
              <div className="h-full w-1/3 bg-indigo-500 dark:bg-indigo-400 animate-[catalogues-progress_1.2s_ease-in-out_infinite]" />
              <style>{`@keyframes catalogues-progress { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }`}</style>
            </div>
          )}
          {cataloguesQ.data?.server && !cataloguesQ.data.server.reachable && (
            <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-200 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-[11px] text-amber-900 dark:text-amber-200">
              <AlertCircle size={13} className="shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold">
                  {t(
                    'catalogues.server_unreachable_title',
                    'Qdrant server unreachable',
                  )}
                </div>
                <div className="mt-0.5">
                  {t(
                    'catalogues.server_unreachable_hint',
                    'Set CWICR_QDRANT_URL or QDRANT_URL and run docker compose up -d qdrant.',
                  )}
                </div>
              </div>
            </div>
          )}

          <p className="text-[11px] text-content-tertiary mb-2">
            {t(
              'catalogues.help',
              'Install the catalogue for the project region. The matcher will switch automatically once installed.',
            )}{' '}
            <span className="text-content-quaternary">
              {t(
                'catalogues.install_time_hint',
                'Install takes 30–120 s depending on connection (~50–500 MB download).',
              )}
            </span>
          </p>

          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-content-tertiary uppercase tracking-wider text-[10px] border-b border-border">
                  <th className="py-1.5 pr-2">
                    {t('catalogues.col_region', 'Region')}
                  </th>
                  <th className="py-1.5 pr-2 hidden sm:table-cell">
                    {t('catalogues.col_language', 'Lang')}
                  </th>
                  <th className="py-1.5 pr-2 hidden sm:table-cell">
                    {t('catalogues.col_currency', 'Curr')}
                  </th>
                  <th className="py-1.5 pr-2 hidden md:table-cell">
                    {t('catalogues.col_size', 'Size')}
                  </th>
                  <th className="py-1.5 pr-2">
                    {t('catalogues.col_status', 'Status')}
                  </th>
                  <th className="py-1.5">
                    {t('catalogues.col_action', 'Action')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((c) => {
                  const installJob = installJobs.get(c.region);
                  const isPending = installJob?.status === 'downloading';
                  const isPreferred = preferredRegion === c.region;
                  return (
                    <tr
                      key={c.region}
                      className={clsx(
                        'border-b border-border/50 last:border-b-0',
                        isPreferred &&
                          'bg-indigo-50/60 dark:bg-indigo-900/15',
                      )}
                    >
                      <td className="py-1.5 pr-2">
                        <div className="flex items-center gap-1.5">
                          <CountryFlag
                            code={originFlagCode(c.country_iso)}
                            size={16}
                            className="shadow-xs border border-black/5"
                          />
                          <span className="font-medium text-content-primary">
                            {c.country_iso}
                          </span>
                          <span className="text-content-tertiary">·</span>
                          <span className="text-content-secondary">
                            {c.city}
                          </span>
                          {isPreferred && (
                            <span className="ml-1 text-[9px] uppercase tracking-wider text-indigo-700 dark:text-indigo-300 font-bold">
                              {t('catalogues.preferred_tag', 'Project')}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-1.5 pr-2 hidden sm:table-cell text-content-secondary">
                        {c.language}
                      </td>
                      <td className="py-1.5 pr-2 hidden sm:table-cell text-content-secondary">
                        {c.currency}
                      </td>
                      <td className="py-1.5 pr-2 hidden md:table-cell text-content-tertiary">
                        {c.size_mb ? `${c.size_mb} MB` : '—'}
                      </td>
                      <td className="py-1.5 pr-2">
                        <StatusBadge
                          status={isPending ? 'installing' : c.install_status}
                        />
                      </td>
                      <td className="py-1.5">
                        <InstallButton
                          region={c.region}
                          status={isPending ? 'installing' : c.install_status}
                          isPending={isPending}
                          onInstall={() => handleInstall(c)}
                        />
                      </td>
                    </tr>
                  );
                })}
                {/* Skeleton rows on initial load — without these the table
                    pops in empty for ~200–800 ms which the user reads as a
                    broken state. We render 6 placeholder rows that match
                    the real row layout so the height doesn't jump on swap. */}
                {sorted.length === 0 && cataloguesQ.isFetching && (
                  Array.from({ length: 6 }).map((_, i) => (
                    <tr
                      key={`sk-${i}`}
                      className="border-b border-border/50 last:border-b-0"
                    >
                      <td className="py-2 pr-2">
                        <div className="h-3 w-32 rounded bg-content-tertiary/15 animate-pulse" />
                      </td>
                      <td className="py-2 pr-2 hidden sm:table-cell">
                        <div className="h-3 w-6 rounded bg-content-tertiary/15 animate-pulse" />
                      </td>
                      <td className="py-2 pr-2 hidden sm:table-cell">
                        <div className="h-3 w-8 rounded bg-content-tertiary/15 animate-pulse" />
                      </td>
                      <td className="py-2 pr-2 hidden md:table-cell">
                        <div className="h-3 w-12 rounded bg-content-tertiary/15 animate-pulse" />
                      </td>
                      <td className="py-2 pr-2">
                        <div className="h-4 w-16 rounded bg-content-tertiary/15 animate-pulse" />
                      </td>
                      <td className="py-2">
                        <div className="h-5 w-16 rounded bg-content-tertiary/15 animate-pulse" />
                      </td>
                    </tr>
                  ))
                )}
                {/* Empty-state — only when the query has actually settled
                    (no in-flight fetch) AND returned zero rows. The previous
                    `!isLoading` check fired during invalidation refetches
                    after install (isLoading flips false the moment we have
                    *any* data ever) and flashed the alarming "registry
                    missing" copy on every successful install. */}
                {sorted.length === 0 &&
                  !cataloguesQ.isFetching &&
                  cataloguesQ.isFetched && (
                    <tr>
                      <td
                        colSpan={6}
                        className="py-4 text-center text-content-tertiary"
                      >
                        {t(
                          'catalogues.empty',
                          'No catalogues registered. Check backend/app/modules/costs/cwicr_v3_catalogue.py.',
                        )}
                      </td>
                    </tr>
                  )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
