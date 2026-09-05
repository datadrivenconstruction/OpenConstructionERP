// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import {
  Database,
  Loader2,
  CheckCircle2,
  XCircle,
  Download,
} from 'lucide-react';
import { Button, Card, CardHeader, CardContent, Badge, Breadcrumb, CountryFlag, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet, apiPost } from '@/shared/lib/api';
import { reportBackgroundIndexFailure } from '@/features/costs/vectorIndex';
import { useBaseCatalog, flattenVariants, type BaseVariant } from '@/features/costs/baseCatalog';
import { BaseCatalogBrowser } from '@/features/costs/BaseCatalogBrowser';
import { BaseCatalogError } from '@/features/costs/BaseCatalogError';
import { getNumberLocale } from '@/stores/usePreferencesStore';

// ── Types ────────────────────────────────────────────────────────────────────

interface RegionStat {
  region: string;
  count: number;
}

interface DemoInstallResult {
  project_id: string;
  project_name: string;
  demo_id: string;
  sections: number;
  positions: number;
  markups: number;
  grand_total: number;
  currency: string;
  schedule_months: number;
}

// ── CWICR Database definitions ──────────────────────────────────────────────

// CWICR base definitions (all base families and their market variants, with
// real per-base work-item counts) now come from the shared base-catalog
// endpoint via useBaseCatalog(); the <BaseCatalogBrowser> renders them. The
// former hardcoded CWICR_DATABASES array lived here and has been removed.

// ── Demo project definitions ────────────────────────────────────────────────

interface DemoProject {
  id: string;
  name: string;
  city: string;
  flagId: string;
}

const DEMO_PROJECTS: DemoProject[] = [
  { id: 'residential-berlin', name: 'Berlin Residential', city: 'Berlin', flagId: 'de' },
  { id: 'office-london', name: 'London Office', city: 'London', flagId: 'gb' },
  { id: 'medical-us', name: 'US Medical Center', city: 'Chicago', flagId: 'us' },
  { id: 'school-paris', name: 'Paris School', city: 'Paris', flagId: 'fr' },
  { id: 'warehouse-dubai', name: 'Dubai Warehouse', city: 'Dubai', flagId: 'ae' },
];

// ── LocalStorage helpers ────────────────────────────────────────────────────

const LOADED_DBS_KEY = 'oe_loaded_databases';
const ACTIVE_DB_KEY = 'oe_active_database';
const INSTALLED_DEMOS_KEY = 'oe_installed_demos';

function getLoadedDatabases(): string[] {
  try {
    const raw = localStorage.getItem(LOADED_DBS_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function addLoadedDatabase(dbId: string): void {
  try {
    const current = getLoadedDatabases();
    if (!current.includes(dbId)) {
      localStorage.setItem(LOADED_DBS_KEY, JSON.stringify([...current, dbId]));
    }
  } catch {
    // Storage unavailable
  }
}

// Active database is a global concept shared with the import page via the same
// ``oe_active_database`` key, so setting it here keeps both surfaces in sync.
function getActiveDatabase(): string | null {
  try {
    return localStorage.getItem(ACTIVE_DB_KEY);
  } catch {
    return null;
  }
}

function setActiveDatabase(dbId: string): void {
  try {
    localStorage.setItem(ACTIVE_DB_KEY, dbId);
  } catch {
    // Storage unavailable
  }
}

function getInstalledDemos(): string[] {
  try {
    const raw = localStorage.getItem(INSTALLED_DEMOS_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function addInstalledDemo(demoId: string): void {
  try {
    const current = getInstalledDemos();
    if (!current.includes(demoId)) {
      localStorage.setItem(INSTALLED_DEMOS_KEY, JSON.stringify([...current, demoId]));
    }
  } catch {
    // Storage unavailable
  }
}

// ── Region Card ─────────────────────────────────────────────────────────────

type CardStatus = 'idle' | 'loading' | 'loaded' | 'failed';

// RegionCard was removed: the shared <BaseCatalogBrowser> now renders every
// base card (flag, real work-item count, load/active controls) consistently
// across the import, setup and onboarding surfaces.

// ── Demo Project Card ───────────────────────────────────────────────────────

function DemoCard({
  demo,
  status,
  onInstall,
  disabled,
}: {
  demo: DemoProject;
  status: CardStatus;
  onInstall: () => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();

  return (
    <div
      className={`
        relative flex flex-col rounded-xl border transition-all duration-normal ease-oe
        ${
          status === 'loaded'
            ? 'border-semantic-success/30 bg-semantic-success-bg/40'
            : status === 'loading'
              ? 'border-oe-blue/40 bg-oe-blue-subtle/30'
              : status === 'failed'
                ? 'border-semantic-error/30 bg-semantic-error-bg/40'
                : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary'
        }
        ${disabled && status === 'idle' ? 'opacity-40 pointer-events-none' : ''}
      `}
    >
      <button
        onClick={onInstall}
        disabled={disabled || status === 'loading' || status === 'loaded'}
        className="flex items-center gap-3 px-3.5 py-3 text-left active:scale-[0.98] transition-transform"
      >
        <CountryFlag code={demo.flagId} size={32} className="shadow-xs border border-black/5" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-content-primary truncate">
              {demo.name}
            </span>
            {status === 'loaded' && (
              <CheckCircle2 size={14} className="text-semantic-success shrink-0" />
            )}
            {status === 'failed' && (
              <XCircle size={14} className="text-semantic-error shrink-0" />
            )}
          </div>
          <div className="text-2xs text-content-tertiary">{demo.city}</div>
          <div className="mt-1">
            {status === 'loaded' ? (
              <span className="text-2xs text-semantic-success font-medium">
                {t('setup.installed', { defaultValue: 'Installed' })}
              </span>
            ) : status === 'loading' ? (
              <span className="text-2xs text-oe-blue font-medium">
                {t('setup.installing', { defaultValue: 'Installing...' })}
              </span>
            ) : status === 'failed' ? (
              <span className="text-2xs text-semantic-error font-medium">
                {t('setup.install_failed', { defaultValue: 'Install failed' })}
              </span>
            ) : (
              <span className="text-2xs text-content-quaternary">
                {t('setup.click_to_install', { defaultValue: 'Click to install' })}
              </span>
            )}
          </div>
        </div>
        {status === 'loading' && (
          <Loader2 size={16} className="animate-spin text-oe-blue shrink-0" />
        )}
      </button>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

export function DatabaseSetupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  // ── Database load tracking ──
  // The whole loadable catalog (base families + market variants with real
  // work-item counts) comes from the single-source backend registry; the
  // shared <BaseCatalogBrowser> renders it and this page keeps the load,
  // progress and toast logic.
  const { data: baseCatalog, error: baseCatalogError, refetch: refetchBaseCatalog } = useBaseCatalog();
  const [loading, setLoading] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<Set<string>>(() => new Set(getLoadedDatabases()));
  const [activeDb, setActiveDb] = useState<string | null>(() => getActiveDatabase());
  const [elapsed, setElapsed] = useState(0);
  const [loadAllActive, setLoadAllActive] = useState(false);
  const loadAllAbortRef = useRef(false);

  // ── Demo status tracking ──
  const [demoStatuses, setDemoStatuses] = useState<Record<string, CardStatus>>(() => {
    const installed = new Set(getInstalledDemos());
    const initial: Record<string, CardStatus> = {};
    for (const demo of DEMO_PROJECTS) {
      initial[demo.id] = installed.has(demo.id) ? 'loaded' : 'idle';
    }
    return initial;
  });
  const [demoLoading, setDemoLoading] = useState(false);

  // ── Sync loaded databases with backend region stats ──
  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats/').catch(() => []),
    retry: false,
    refetchOnWindowFocus: true,
  });

  // Backend region stats are the source of truth for which bases are loaded.
  useEffect(() => {
    if (regionStats) {
      setLoaded(new Set(regionStats.map((r) => r.region)));
    }
  }, [regionStats]);

  // Elapsed-time tick for the in-flight import; drives the browser spinner
  // label and the Load All progress copy.
  useEffect(() => {
    if (!loading) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const interval = setInterval(
      () => setElapsed(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(interval);
  }, [loading]);

  // Deep-link from the Match panel: ``?vectorize=DE_BERLIN`` surfaces a hint
  // toast pointing at the base to load and vectorise. We intentionally do NOT
  // auto-trigger the load - auto-actions on URL params are jarring when the
  // user lands here from a stale tab. Resolve the base label once the catalog
  // is available, fire the toast once, then clear the param.
  const vectorizeHandledRef = useRef(false);
  useEffect(() => {
    if (vectorizeHandledRef.current) return;
    const target = searchParams.get('vectorize');
    if (!target || !baseCatalog) return;
    vectorizeHandledRef.current = true;
    const known = flattenVariants(baseCatalog).find((v) => v.region === target);
    if (known) {
      const isLoaded = loaded.has(target);
      addToast({
        type: 'info',
        title: t('setup.vectorize_target_title', {
          defaultValue: `Click "${known.market}" to vectorise`,
          catalog: known.market,
        }),
        message: isLoaded
          ? t('setup.vectorize_already_loaded', {
              defaultValue:
                'Catalogue already loaded - click the card to refresh and (re)build vectors.',
            })
          : t('setup.vectorize_not_loaded', {
              defaultValue:
                'Catalogue not yet loaded - click the card to load and build vectors.',
            }),
      });
    }
    // Clear the param so reloading the page doesn't re-toast.
    searchParams.delete('vectorize');
    setSearchParams(searchParams, { replace: true });
  }, [baseCatalog, searchParams, setSearchParams, addToast, t, loaded]);

  // ── Set the active cost database (shared with the import page). ──
  const handleSetActive = useCallback(
    (region: string) => {
      setActiveDatabase(region);
      setActiveDb(region);
      const name = flattenVariants(baseCatalog).find((v) => v.region === region)?.market ?? region;
      addToast({
        type: 'success',
        title: t('setup.active_db_changed', { defaultValue: 'Active database changed' }),
        message: `${name} ${t('setup.is_now_active', { defaultValue: 'is now the active database' })}`,
      });
    },
    [addToast, t, baseCatalog],
  );

  // ── Load a single region ──
  // One click loads BOTH layers — abstract cost items (oe_costs_item via
  // ``/v1/costs/load-cwicr/``) AND the priced resource catalogue
  // (oe_catalog_resource via ``/v1/catalog/import/``). They're separate
  // tables with different shapes, but share the same CWICR origin and
  // both surfaces ("Cost Database" and "Resource Catalog" in the
  // sidebar) need data populated for the user to see anything. Earlier
  // version only loaded /costs, so /catalog stayed empty after the
  // success toast — confused users into thinking the load failed.
  const handleLoadRegion = useCallback(
    async (variant: BaseVariant) => {
      // Local alias so the load / progress / toast body below reads naturally.
      const db = { id: variant.region, name: variant.market };
      setLoading(db.id);

      try {
        // Run both imports in parallel. Catalog import is treated as
        // best-effort: not every region ships a priced catalogue file
        // and we still want the costs layer to count as success.
        const [costsData, catalogData] = await Promise.all([
          apiPost<Record<string, unknown>>(`/v1/costs/load-cwicr/${db.id}`),
          apiPost<{ imported: number; skipped: number; region: string }>(
            `/v1/catalog/import/${db.id}`,
          ).catch((e: unknown) => {
            // eslint-disable-next-line no-console
            console.warn(`[setup] catalog import for ${db.id} failed:`, e);
            return null;
          }),
        ]);

        const imported = (costsData.imported as number) ?? 0;
        const totalItems = (costsData.total_items as number) ?? imported;
        const status = costsData.status as string | undefined;
        const catalogImported = catalogData?.imported ?? 0;

        setLoaded((prev) => new Set(prev).add(db.id));
        addLoadedDatabase(db.id);

        // Auto-set as active if it is the first loaded database.
        if (getLoadedDatabases().length === 1 || !getActiveDatabase()) {
          setActiveDatabase(db.id);
          setActiveDb(db.id);
        }

        // Single combined toast with longer duration so the user has time to
        // follow up in the Cost Database / Resource Catalog.
        const lines = [
          `${(totalItems || imported).toLocaleString(getNumberLocale())} ${t('setup.cost_items', { defaultValue: 'cost items' })}`,
        ];
        if (catalogData) {
          lines.push(
            `${catalogImported.toLocaleString(getNumberLocale())} ${t('setup.catalog_resources', { defaultValue: 'catalog resources' })}`,
          );
        }
        addToast(
          {
            type: status === 'already_loaded' ? 'info' : 'success',
            // The database name is a variable, not a prefix: several languages
            // do not open the sentence with it.
            title: status === 'already_loaded'
              ? t('setup.db_already_loaded', { name: db.name, defaultValue: '{{name}} already loaded' })
              : t('setup.db_loaded', { name: db.name, defaultValue: 'Loaded {{name}}' }),
            message: lines.join(' - '),
          },
          { duration: 8000 },
        );

        // Partial success: the rates (load-cwicr) landed but the parallel
        // resource catalogue (catalog/import) returned nothing - usually the
        // GitHub source for that region was unreachable. Do NOT let the plain
        // success above mislead the user into thinking everything arrived.
        // Surface a separate, non-blocking notice with a one-click retry that
        // re-runs the whole region load (rates re-detect as already loaded).
        if (!catalogData) {
          addToast(
            {
              type: 'warning',
              title: t('setup.catalog_partial_title', {
                defaultValue: 'Rates loaded, resources unavailable',
              }),
              message: t('setup.catalog_partial_message', {
                defaultValue:
                  'Rates loaded. The resource breakdown is unavailable for this region right now, often a blocked network or GitHub connection issue. Rates work without it, you can retry to fetch resources.',
              }),
              action: {
                label: t('setup.load_failed_retry', { defaultValue: 'Retry' }),
                onClick: () => {
                  void handleLoadRegion(variant);
                },
              },
            },
            { duration: 10000 },
          );
        }

        // Trigger vector indexing in background. Long budget: the endpoint loads the
        // embedding model (up to 30s) before embedding ~55K items, so the 45s default
        // aborts work the server goes on to finish and shows a "Request timed out"
        // toast for an import that actually succeeded (GitHub #436).
        //
        // The failure is reported rather than dropped. This is first-run setup: the
        // toast above says the region loaded, and an index that never built is only
        // discovered later, when search returns nothing and there is no longer
        // anything on screen connecting the two. The wrapper's timeout toast is
        // suppressed because the sentence it shows - cancelled - is not what
        // happened to the server.
        apiPost('/v1/costs/vector/index/', undefined, {
          longRunning: true,
          suppressTimeoutToast: true,
        }).catch(reportBackgroundIndexFailure);

        // Invalidate BOTH costs and catalog so /costs and /catalog pages
        // refetch the moment the user navigates there. Without the
        // catalog invalidation, the Resource Catalog page kept showing
        // its previous (sparse) state and looked broken.
        queryClient.invalidateQueries({ queryKey: ['costs'] });
        queryClient.invalidateQueries({ queryKey: ['catalog'] });
      } catch (err: unknown) {
        // First load downloads the regional data from GitHub, which is the
        // usual point of failure on networks where that host is blocked.
        // Prefer the backend detail (it names the source URL) and fall back
        // to an actionable reachability hint, plus a one-click retry.
        const backendDetail = err instanceof Error ? err.message : '';
        const message =
          backendDetail ||
          t('setup.load_failed_unreachable', {
            defaultValue:
              'Could not reach the data host to download this region. This is often a blocked network or a GitHub connection issue. Check your connection and that github.com is reachable, then try again.',
          });
        addToast({
          type: 'error',
          title: t('setup.load_failed_title', {
            defaultValue: 'Could not load {{name}}',
            name: db.name,
          }),
          message,
          action: {
            label: t('setup.load_failed_retry', { defaultValue: 'Retry' }),
            onClick: () => {
              void handleLoadRegion(variant);
            },
          },
        });
      } finally {
        setLoading(null);
      }
    },
    [addToast, t, queryClient],
  );

  // ── Load All bases sequentially ──
  const handleLoadAll = useCallback(async () => {
    const variants = flattenVariants(baseCatalog);
    setLoadAllActive(true);
    loadAllAbortRef.current = false;

    // Dedupe by region: the catalog now carries many market cards per base that
    // all share one region, so load each unique base only once.
    const seenRegions = new Set<string>();
    const pending = variants.filter((v) => {
      if (loaded.has(v.region) || seenRegions.has(v.region)) return false;
      seenRegions.add(v.region);
      return true;
    });
    let processed = 0;

    for (const v of pending) {
      if (loadAllAbortRef.current) break;

      setLoading(v.region);

      try {
        // Run both layers in parallel - same shape as ``handleLoadRegion``.
        await Promise.all([
          apiPost<Record<string, unknown>>(`/v1/costs/load-cwicr/${v.region}`),
          apiPost<{ imported: number; skipped: number; region: string }>(
            `/v1/catalog/import/${v.region}`,
          ).catch(() => null),
        ]);

        setLoaded((prev) => new Set(prev).add(v.region));
        addLoadedDatabase(v.region);
        processed += 1;
      } catch {
        // Skip a failed base and keep going with the rest.
      } finally {
        setLoading(null);
      }
    }

    // Trigger vector indexing once at the end (long budget and reported failure -
    // see handleLoadRegion). This is the heaviest of the four: every region just
    // loaded is embedded in one request, and "Batch loading complete" is shown
    // below whatever happens to it.
    apiPost('/v1/costs/vector/index/', undefined, {
      longRunning: true,
      suppressTimeoutToast: true,
    }).catch(reportBackgroundIndexFailure);
    queryClient.invalidateQueries({ queryKey: ['costs'] });
    queryClient.invalidateQueries({ queryKey: ['catalog'] });

    setLoadAllActive(false);
    setLoading(null);

    addToast({
      type: 'success',
      title: t('setup.load_all_complete', { defaultValue: 'Batch loading complete' }),
      message: t('setup.load_all_summary', {
        defaultValue: '{{count}} regions processed',
        count: processed,
      }),
    });
  }, [baseCatalog, loaded, addToast, t, queryClient]);

  // ── Install demo project ──
  const handleInstallDemo = useCallback(
    async (demo: DemoProject) => {
      if (demoStatuses[demo.id] === 'loading' || demoStatuses[demo.id] === 'loaded') return;

      setDemoStatuses((prev) => ({ ...prev, [demo.id]: 'loading' }));
      setDemoLoading(true);

      try {
        await apiPost<DemoInstallResult>(`/demo/install/${demo.id}`);
        setDemoStatuses((prev) => ({ ...prev, [demo.id]: 'loaded' }));
        addInstalledDemo(demo.id);

        addToast({
          type: 'success',
          title: t('setup.demo_installed', { defaultValue: 'Demo project installed' }),
          message: demo.name,
        });

        queryClient.invalidateQueries({ queryKey: ['projects'] });
      } catch {
        setDemoStatuses((prev) => ({ ...prev, [demo.id]: 'failed' }));
        addToast({
          type: 'error',
          title: t('setup.demo_install_failed', { defaultValue: 'Failed to install demo' }),
          message: demo.name,
        });
      } finally {
        setDemoLoading(false);
      }
    },
    [demoStatuses, addToast, t, queryClient],
  );

  // ── Computed stats ──
  const totalBases = baseCatalog?.total_bases ?? 0;
  const loadedCount = loaded.size;
  const totalItems = regionStats?.reduce((sum, r) => sum + r.count, 0) ?? 0;
  const allBasesLoaded = totalBases > 0 && loadedCount >= totalBases;
  const installedDemoCount = DEMO_PROJECTS.filter((d) => demoStatuses[d.id] === 'loaded').length;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('setup.databases_resources', { defaultValue: 'Databases & Resources' }) },
        ]}
      />

      {/* Page header */}
      <PageHeader
        srTitle={t('setup.databases_resources', { defaultValue: 'Databases & Resources' })}
        subtitle={t('setup.page_subtitle', {
          defaultValue:
            'Load regional cost databases, resource catalogs, and demo projects.',
        })}
        actions={
          <div className="hidden sm:flex items-center gap-2">
            {loadedCount > 0 && (
              <Badge variant="success" size="sm">
                {totalBases > 0 ? `${loadedCount}/${totalBases}` : loadedCount}{' '}
                {t('setup.regions', { defaultValue: 'regions' })}
              </Badge>
            )}
            {totalItems > 0 && (
              <Badge variant="blue" size="sm">
                {totalItems.toLocaleString(getNumberLocale())} {t('setup.items', { defaultValue: 'items' })}
              </Badge>
            )}
          </div>
        }
      />

      {/* Canonical module intro — pain-named, copy from MODULE_INTRO_COPY. */}
      <DismissibleInfo
        storageKey="setup-databases"
        title={t('setup.intro_title', {
          defaultValue: 'Get priced and ready in minutes',
        })}
        more={
          t('setup.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('setup.intro_more')} />
            : undefined
        }
        links={[
          { label: t('nav.costs', { defaultValue: 'Cost Database' }), onClick: () => navigate('/costs') },
          { label: t('nav.catalog', { defaultValue: 'Resource Catalog' }), onClick: () => navigate('/catalog') },
          { label: t('nav.projects', { defaultValue: 'Projects' }), onClick: () => navigate('/projects') },
        ]}
      >
        {t('setup.intro_body', {
          defaultValue:
            'Pick your country and install the matching CWICR cost database of 55,000+ priced items, so the catalogue and unit rates arrive already in the right currency and language. The same screen drops in ready-made demo projects with sections, positions and a schedule, giving you live data to estimate against straight away.',
        })}
      </DismissibleInfo>

      {/* ── Section 1: Cost Databases ────────────────────────────────────── */}
      <Card>
        <CardHeader
          title={t('setup.cost_databases', { defaultValue: 'Cost Databases' })}
          subtitle={t('setup.cost_databases_desc', {
            defaultValue:
              'Load regional cost databases with 55,000+ items and pricing data per region.',
          })}
          action={
            <Button
              variant="primary"
              size="sm"
              onClick={handleLoadAll}
              disabled={loadAllActive || !baseCatalog || allBasesLoaded}
              loading={loadAllActive}
              icon={<Download size={14} />}
            >
              {loadAllActive
                ? t('setup.loading_all', { defaultValue: 'Loading all...' })
                : t('setup.load_all', { defaultValue: 'Load All' })}
            </Button>
          }
        />
        <CardContent>
          {/* One browser for all base families (global CWICR markets + national
              bases), with real work-item counts, search, load and active-set. */}
          {baseCatalog ? (
            <BaseCatalogBrowser
              catalog={baseCatalog}
              loadedRegions={loaded}
              loadingRegion={loading}
              activeRegion={activeDb}
              onLoad={handleLoadRegion}
              onSetActive={handleSetActive}
              elapsedSeconds={elapsed}
            />
          ) : baseCatalogError ? (
            <BaseCatalogError error={baseCatalogError} onRetry={() => void refetchBaseCatalog()} />
          ) : (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-content-tertiary">
              <Loader2 size={16} className="animate-spin" />
              {t('setup.loading_catalog', { defaultValue: 'Loading cost bases...' })}
            </div>
          )}

          {/* Load all progress indicator */}
          {loadAllActive && (
            <div className="mt-4 flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-secondary">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-500 transition-all duration-500 ease-out"
                  style={{
                    width: `${Math.round((loadedCount / (totalBases || 1)) * 100)}%`,
                  }}
                />
              </div>
              <span className="text-xs text-content-secondary whitespace-nowrap">
                {loadedCount}/{totalBases}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  loadAllAbortRef.current = true;
                }}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Section 2: Resource Catalog ──────────────────────────────────── */}
      <Card>
        <CardHeader
          title={t('setup.resource_catalog', { defaultValue: 'Resource Catalog' })}
          subtitle={t('setup.resource_catalog_desc', {
            defaultValue:
              'Materials, equipment, and labor resources are loaded together with each cost database region above.',
          })}
        />
        <CardContent>
          <div className="flex items-center gap-4 rounded-xl bg-surface-secondary p-4">
            <Database size={24} className="text-content-tertiary shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-content-secondary">
                {loadedCount > 0
                  ? t('setup.resources_available', {
                      defaultValue:
                        '{{count}} region(s) loaded. Resources are included with each cost database.',
                      count: loadedCount,
                    })
                  : t('setup.resources_hint', {
                      defaultValue:
                        'Load a cost database above to include resources for that region.',
                    })}
              </p>
            </div>
            <Link to="/catalog">
              <Button variant="ghost" size="sm">
                {t('setup.view_catalog', { defaultValue: 'View Catalog' })}
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>

      {/* ── Section 3: Demo Projects ─────────────────────────────────────── */}
      <Card>
        <CardHeader
          title={t('setup.demo_projects', { defaultValue: 'Demo Projects' })}
          subtitle={t('setup.demo_projects_desc', {
            defaultValue: 'Install example projects to explore all features of the platform.',
          })}
        />
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5">
            {DEMO_PROJECTS.map((demo) => (
              <DemoCard
                key={demo.id}
                demo={demo}
                status={demoStatuses[demo.id] ?? 'idle'}
                onInstall={() => handleInstallDemo(demo)}
                disabled={demoLoading && demoStatuses[demo.id] !== 'loading'}
              />
            ))}
          </div>

          {installedDemoCount > 0 && (
            <div className="mt-3 text-xs text-content-tertiary">
              {installedDemoCount}/{DEMO_PROJECTS.length}{' '}
              {t('setup.demos_installed', { defaultValue: 'demo projects installed' })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Footer hint */}
      <p className="text-center text-xs text-content-tertiary">
        {t('setup.footer_hint', {
          defaultValue:
            'Databases and demo projects can also be managed from the Cost Database and Modules pages.',
        })}
      </p>
    </div>
  );
}
