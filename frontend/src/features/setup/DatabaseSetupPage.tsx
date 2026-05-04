import { useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Database,
  Loader2,
  CheckCircle2,
  XCircle,
  Download,
} from 'lucide-react';
import { Button, Card, CardHeader, CardContent, Badge, Breadcrumb, CountryFlag } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet, apiPost } from '@/shared/lib/api';

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

interface CWICRDatabase {
  id: string;
  name: string;
  city: string;
  lang: string;
  currency: string;
  flagId: string;
}

const CWICR_DATABASES: CWICRDatabase[] = [
  { id: 'DE_BERLIN', name: 'Germany / DACH', city: 'Berlin', lang: 'Deutsch', currency: 'EUR', flagId: 'de' },
  { id: 'UK_GBP', name: 'United Kingdom', city: 'London', lang: 'English', currency: 'GBP', flagId: 'gb' },
  { id: 'USA_USD', name: 'United States', city: 'National', lang: 'English', currency: 'USD', flagId: 'us' },
  { id: 'FR_PARIS', name: 'France', city: 'Paris', lang: 'Francais', currency: 'EUR', flagId: 'fr' },
  { id: 'SP_BARCELONA', name: 'Spain / Latin America', city: 'Barcelona', lang: 'Espanol', currency: 'EUR', flagId: 'es' },
  { id: 'PT_SAOPAULO', name: 'Brazil / Portugal', city: 'Sao Paulo', lang: 'Portugues', currency: 'BRL', flagId: 'br' },
  { id: 'RU_STPETERSBURG', name: 'Russia / CIS', city: 'St. Petersburg', lang: 'Russian', currency: 'RUB', flagId: 'ru' },
  { id: 'AR_DUBAI', name: 'Middle East / Gulf', city: 'Dubai', lang: 'Arabic', currency: 'AED', flagId: 'ae' },
  { id: 'ZH_SHANGHAI', name: 'China', city: 'Shanghai', lang: 'Chinese', currency: 'CNY', flagId: 'cn' },
  { id: 'HI_MUMBAI', name: 'India / South Asia', city: 'Mumbai', lang: 'Hindi', currency: 'INR', flagId: 'in' },
  { id: 'ENG_TORONTO', name: 'Canada / International', city: 'Toronto', lang: 'English', currency: 'CAD', flagId: 'ca' },
  // Added 2026-04-28 — DDC CWICR repo grew from 11 to 30 country folders.
  { id: 'AU_SYDNEY', name: 'Australia', city: 'Sydney', lang: 'English', currency: 'AUD', flagId: 'au' },
  { id: 'NZ_AUCKLAND', name: 'New Zealand', city: 'Auckland', lang: 'English', currency: 'NZD', flagId: 'nz' },
  { id: 'IT_ROME', name: 'Italy', city: 'Rome', lang: 'Italiano', currency: 'EUR', flagId: 'it' },
  { id: 'NL_AMSTERDAM', name: 'Netherlands', city: 'Amsterdam', lang: 'Nederlands', currency: 'EUR', flagId: 'nl' },
  { id: 'PL_WARSAW', name: 'Poland', city: 'Warsaw', lang: 'Polski', currency: 'PLN', flagId: 'pl' },
  { id: 'CS_PRAGUE', name: 'Czech Republic', city: 'Prague', lang: 'Cestina', currency: 'CZK', flagId: 'cz' },
  { id: 'HR_ZAGREB', name: 'Croatia', city: 'Zagreb', lang: 'Hrvatski', currency: 'EUR', flagId: 'hr' },
  { id: 'BG_SOFIA', name: 'Bulgaria', city: 'Sofia', lang: 'Balgarski', currency: 'BGN', flagId: 'bg' },
  { id: 'RO_BUCHAREST', name: 'Romania', city: 'Bucharest', lang: 'Romana', currency: 'RON', flagId: 'ro' },
  { id: 'SV_STOCKHOLM', name: 'Sweden', city: 'Stockholm', lang: 'Svenska', currency: 'SEK', flagId: 'se' },
  { id: 'TR_ISTANBUL', name: 'Türkiye', city: 'Istanbul', lang: 'Türkçe', currency: 'TRY', flagId: 'tr' },
  { id: 'JA_TOKYO', name: 'Japan', city: 'Tokyo', lang: 'Nihongo', currency: 'JPY', flagId: 'jp' },
  { id: 'KO_SEOUL', name: 'South Korea', city: 'Seoul', lang: 'Hangugeo', currency: 'KRW', flagId: 'kr' },
  { id: 'TH_BANGKOK', name: 'Thailand', city: 'Bangkok', lang: 'Thai', currency: 'THB', flagId: 'th' },
  { id: 'VI_HANOI', name: 'Vietnam', city: 'Hanoi', lang: 'Tieng Viet', currency: 'VND', flagId: 'vn' },
  { id: 'ID_JAKARTA', name: 'Indonesia', city: 'Jakarta', lang: 'Bahasa Indonesia', currency: 'IDR', flagId: 'id' },
  { id: 'MX_MEXICOCITY', name: 'Mexico', city: 'Mexico City', lang: 'Espanol', currency: 'MXN', flagId: 'mx' },
  { id: 'ZA_JOHANNESBURG', name: 'South Africa', city: 'Johannesburg', lang: 'English', currency: 'ZAR', flagId: 'za' },
  { id: 'NG_LAGOS', name: 'Nigeria', city: 'Lagos', lang: 'English', currency: 'NGN', flagId: 'ng' },
];

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

function RegionCard({
  db,
  status,
  itemCount,
  onLoad,
  disabled,
}: {
  db: CWICRDatabase;
  status: CardStatus;
  itemCount: number | null;
  onLoad: () => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();

  return (
    <div
      data-region={db.id}
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
        onClick={onLoad}
        disabled={disabled || status === 'loading'}
        className="flex items-center gap-3 px-3.5 py-3 text-left active:scale-[0.98] transition-transform"
      >
        <CountryFlag code={db.flagId} size={32} className="shadow-xs border border-black/5" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-content-primary truncate">
              {db.name}
            </span>
            {status === 'loaded' && (
              <CheckCircle2 size={14} className="text-semantic-success shrink-0" />
            )}
            {status === 'failed' && (
              <XCircle size={14} className="text-semantic-error shrink-0" />
            )}
          </div>
          <div className="text-2xs text-content-tertiary">
            {db.city} &middot; {db.currency}
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            {status === 'loaded' && itemCount != null ? (
              <span className="text-2xs text-semantic-success font-medium">
                {itemCount.toLocaleString()} {t('setup.items', { defaultValue: 'items' })}
              </span>
            ) : status === 'loading' ? (
              <span className="text-2xs text-oe-blue font-medium">
                {t('setup.loading', { defaultValue: 'Loading...' })}
              </span>
            ) : status === 'failed' ? (
              <span className="text-2xs text-semantic-error font-medium">
                {t('setup.failed', { defaultValue: 'Failed' })}
              </span>
            ) : (
              <span className="text-2xs text-content-quaternary">
                {t('setup.ready_to_load', { defaultValue: 'Ready to load' })}
              </span>
            )}
          </div>
        </div>
        {status === 'loading' && (
          <Loader2 size={16} className="animate-spin text-oe-blue shrink-0" />
        )}
      </button>
      {status === 'loaded' && (
        <div className="flex items-center gap-2 px-3.5 pb-2 pt-0">
          <Link
            to={`/costs?region=${db.id}`}
            className="text-2xs text-oe-blue hover:underline font-medium"
            data-testid={`region-view-costs-${db.id}`}
          >
            {t('setup.view_in_costs', {
              defaultValue: 'View cost items →',
            })}
          </Link>
          <span className="text-2xs text-content-quaternary">·</span>
          <Link
            to={`/catalog?region=${db.id}`}
            className="text-2xs text-oe-blue hover:underline font-medium"
            data-testid={`region-view-catalog-${db.id}`}
          >
            {t('setup.view_in_catalog', {
              defaultValue: 'View resources →',
            })}
          </Link>
        </div>
      )}
    </div>
  );
}

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
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  // ── Database status tracking ──
  const [dbStatuses, setDbStatuses] = useState<Record<string, CardStatus>>(() => {
    const initial: Record<string, CardStatus> = {};
    for (const db of CWICR_DATABASES) {
      initial[db.id] = 'idle';
    }
    return initial;
  });
  const [dbItemCounts, setDbItemCounts] = useState<Record<string, number>>({});
  const [_singleLoading, setSingleLoading] = useState(false);
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

  useEffect(() => {
    if (regionStats && regionStats.length > 0) {
      const newStatuses = { ...dbStatuses };
      const newCounts = { ...dbItemCounts };
      for (const stat of regionStats) {
        if (stat.count > 0) {
          newStatuses[stat.region] = 'loaded';
          newCounts[stat.region] = stat.count;
        }
      }
      setDbStatuses(newStatuses);
      setDbItemCounts(newCounts);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regionStats]);

  // Deep-link from the Match panel: ``?vectorize=DE_BERLIN`` scrolls to
  // the targeted region card and surfaces a hint toast. We intentionally
  // do NOT auto-trigger the load — auto-actions on URL params are jarring
  // when the user lands here from a stale tab. The toast points at the
  // load button so the action is one obvious click away.
  useEffect(() => {
    const target = searchParams.get('vectorize');
    if (!target) return;
    const known = CWICR_DATABASES.find((d) => d.id === target);
    if (!known) return;
    const node = document.querySelector(`[data-region="${target}"]`);
    if (node) {
      node.scrollIntoView({ behavior: 'smooth', block: 'center' });
      node.classList.add('ring-2', 'ring-oe-blue', 'ring-offset-2');
      window.setTimeout(() => {
        node.classList.remove('ring-2', 'ring-oe-blue', 'ring-offset-2');
      }, 2400);
    }
    const isLoaded = (regionStats ?? []).some((r) => r.region === target && r.count > 0);
    addToast({
      type: 'info',
      title: t('setup.vectorize_target_title', {
        defaultValue: `Click "${known.name}" to vectorise`,
        catalog: known.name,
      }),
      message: isLoaded
        ? t('setup.vectorize_already_loaded', {
            defaultValue:
              'Catalogue already loaded — click the card to refresh and (re)build vectors.',
          })
        : t('setup.vectorize_not_loaded', {
            defaultValue:
              'Catalogue not yet loaded — click the card to load and build vectors.',
          }),
    });
    // Clear the param so reloading the page doesn't re-toast.
    searchParams.delete('vectorize');
    setSearchParams(searchParams, { replace: true });
  // Intentionally one-shot: only on mount with the initial regionStats.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    async (db: CWICRDatabase) => {
      if (dbStatuses[db.id] === 'loading') return;

      setDbStatuses((prev) => ({ ...prev, [db.id]: 'loading' }));
      setSingleLoading(true);

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

        setDbStatuses((prev) => ({ ...prev, [db.id]: 'loaded' }));
        setDbItemCounts((prev) => ({ ...prev, [db.id]: totalItems || imported }));
        addLoadedDatabase(db.id);

        // Single combined toast with longer duration so the user has
        // time to follow the "View →" links surfaced on the card.
        const lines = [
          `${(totalItems || imported).toLocaleString()} ${t('setup.cost_items', { defaultValue: 'cost items' })}`,
          catalogData
            ? `${catalogImported.toLocaleString()} ${t('setup.catalog_resources', { defaultValue: 'catalog resources' })}`
            : t('setup.catalog_unavailable', { defaultValue: 'catalogue not available for this region' }),
        ];
        addToast(
          {
            type: status === 'already_loaded' ? 'info' : 'success',
            title: status === 'already_loaded'
              ? t('setup.db_already_loaded', { defaultValue: `${db.name} already loaded` })
              : t('setup.db_loaded', { defaultValue: `Loaded ${db.name}` }),
            message: lines.join(' · '),
          },
          { duration: 8000 },
        );

        // Trigger vector indexing in background
        apiPost('/v1/costs/vector/index/').catch(() => {
          // Non-critical
        });

        // Invalidate BOTH costs and catalog so /costs and /catalog pages
        // refetch the moment the user navigates there. Without the
        // catalog invalidation, the Resource Catalog page kept showing
        // its previous (sparse) state and looked broken.
        queryClient.invalidateQueries({ queryKey: ['costs'] });
        queryClient.invalidateQueries({ queryKey: ['catalog'] });
      } catch (err: unknown) {
        setDbStatuses((prev) => ({ ...prev, [db.id]: 'failed' }));
        const detail = err instanceof Error ? err.message : 'Failed to load database';
        addToast({
          type: 'error',
          title: `${t('setup.load_failed', { defaultValue: 'Failed to load' })} ${db.name}`,
          message: detail,
        });
      } finally {
        setSingleLoading(false);
      }
    },
    [dbStatuses, addToast, t, queryClient],
  );

  // ── Load All regions sequentially ──
  const handleLoadAll = useCallback(async () => {
    setLoadAllActive(true);
    loadAllAbortRef.current = false;

    const pending = CWICR_DATABASES.filter((db) => dbStatuses[db.id] !== 'loaded');

    for (const db of pending) {
      if (loadAllAbortRef.current) break;

      setDbStatuses((prev) => ({ ...prev, [db.id]: 'loading' }));
      setSingleLoading(true);

      try {
        // Run both layers in parallel — same shape as ``handleLoadRegion``.
        const [data, _catalog] = await Promise.all([
          apiPost<Record<string, unknown>>(`/v1/costs/load-cwicr/${db.id}`),
          apiPost<{ imported: number; skipped: number; region: string }>(
            `/v1/catalog/import/${db.id}`,
          ).catch(() => null),
        ]);

        const imported = (data.imported as number) ?? 0;
        const totalItems = (data.total_items as number) ?? imported;

        setDbStatuses((prev) => ({ ...prev, [db.id]: 'loaded' }));
        setDbItemCounts((prev) => ({ ...prev, [db.id]: totalItems || imported }));
        addLoadedDatabase(db.id);
      } catch {
        setDbStatuses((prev) => ({ ...prev, [db.id]: 'failed' }));
      }
    }

    // Trigger vector indexing once at the end
    apiPost('/v1/costs/vector/index/').catch(() => {});
    queryClient.invalidateQueries({ queryKey: ['costs'] });
    queryClient.invalidateQueries({ queryKey: ['catalog'] });

    setLoadAllActive(false);
    setSingleLoading(false);

    const loadedCount = CWICR_DATABASES.filter(
      (db) => dbStatuses[db.id] === 'loaded' || pending.some((p) => p.id === db.id),
    ).length;

    addToast({
      type: 'success',
      title: t('setup.load_all_complete', { defaultValue: 'Batch loading complete' }),
      message: t('setup.load_all_summary', {
        defaultValue: '{{count}} regions processed',
        count: loadedCount,
      }),
    });
  }, [dbStatuses, addToast, t, queryClient]);

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
  const loadedCount = CWICR_DATABASES.filter((db) => dbStatuses[db.id] === 'loaded').length;
  const totalItems = Object.values(dbItemCounts).reduce((sum, c) => sum + c, 0);
  const installedDemoCount = DEMO_PROJECTS.filter((d) => demoStatuses[d.id] === 'loaded').length;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('nav.settings', { defaultValue: 'Settings' }), to: '/settings' },
          { label: t('setup.databases_resources', { defaultValue: 'Databases & Resources' }) },
        ]}
      />

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('setup.page_title', { defaultValue: 'Databases & Resources' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('setup.page_subtitle', {
              defaultValue:
                'Load regional cost databases, resource catalogs, and demo projects.',
            })}
          </p>
        </div>

        {/* Summary badges */}
        <div className="hidden sm:flex items-center gap-2">
          {loadedCount > 0 && (
            <Badge variant="success" size="sm">
              {loadedCount}/{CWICR_DATABASES.length} {t('setup.regions', { defaultValue: 'regions' })}
            </Badge>
          )}
          {totalItems > 0 && (
            <Badge variant="blue" size="sm">
              {totalItems.toLocaleString()} {t('setup.items', { defaultValue: 'items' })}
            </Badge>
          )}
        </div>
      </div>

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
              disabled={loadAllActive || loadedCount === CWICR_DATABASES.length}
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
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            {CWICR_DATABASES.map((db) => (
              <RegionCard
                key={db.id}
                db={db}
                status={dbStatuses[db.id] ?? 'idle'}
                itemCount={dbItemCounts[db.id] ?? null}
                onLoad={() => handleLoadRegion(db)}
                disabled={loadAllActive && dbStatuses[db.id] !== 'loading'}
              />
            ))}
          </div>

          {/* Load all progress indicator */}
          {loadAllActive && (
            <div className="mt-4 flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-secondary">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-500 transition-all duration-500 ease-out"
                  style={{
                    width: `${Math.round((loadedCount / CWICR_DATABASES.length) * 100)}%`,
                  }}
                />
              </div>
              <span className="text-xs text-content-secondary whitespace-nowrap">
                {loadedCount}/{CWICR_DATABASES.length}
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
