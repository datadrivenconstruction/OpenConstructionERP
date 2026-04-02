import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  Database,
  Sparkles,
  Globe,
  FileInput,
  BarChart3,
  Plug,
  Package,
  Check,
  Download,
  ShieldCheck,
  Building2,
  Boxes,
  Loader2,
  Clock,
  AlertTriangle,
  Trash2,
  Info,
  type LucideIcon,
} from 'lucide-react';
import { Card, Badge, Button, Input, InfoHint } from '@/shared/ui';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { getModulesByCategory } from '@/modules/_registry';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface MarketplaceModule {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  version: string;
  size_mb: number;
  author: string;
  tags: string[];
  requires: string[];
  installed: boolean;
  price: string;
}

/* ── Category config (marketplace data packages) ─────────────────────── */

type CategoryKey =
  | 'all'
  | 'demo_project'
  | 'resource_catalog'
  | 'cost_database'
  | 'vector_index'
  | 'language'
  | 'converter'
  | 'analytics'
  | 'integration';

interface CategoryMeta {
  labelKey: string;
  defaultLabel: string;
  icon: LucideIcon;
}

const CATEGORIES: Record<CategoryKey, CategoryMeta> = {
  all: { labelKey: 'marketplace.category_all', defaultLabel: 'All', icon: Package },
  demo_project: {
    labelKey: 'marketplace.category_demo',
    defaultLabel: 'Demo Projects',
    icon: Building2,
  },
  resource_catalog: {
    labelKey: 'marketplace.category_resource_catalog',
    defaultLabel: 'Resource Catalogs',
    icon: Boxes,
  },
  cost_database: {
    labelKey: 'marketplace.category_cost_database',
    defaultLabel: 'Cost Databases',
    icon: Database,
  },
  vector_index: {
    labelKey: 'marketplace.category_vector_index',
    defaultLabel: 'Vector Indices',
    icon: Sparkles,
  },
  language: {
    labelKey: 'marketplace.category_language',
    defaultLabel: 'Languages',
    icon: Globe,
  },
  converter: {
    labelKey: 'marketplace.category_converter',
    defaultLabel: 'Converters',
    icon: FileInput,
  },
  analytics: {
    labelKey: 'marketplace.category_analytics',
    defaultLabel: 'Analytics',
    icon: BarChart3,
  },
  integration: {
    labelKey: 'marketplace.category_integration',
    defaultLabel: 'Integrations',
    icon: Plug,
  },
};

const CATEGORY_KEYS = Object.keys(CATEGORIES) as CategoryKey[];

/** Map icon name string from the backend to a lucide-react component. */
const ICON_MAP: Record<string, LucideIcon> = {
  Database: Database,
  Sparkles: Sparkles,
  Globe: Globe,
  FileInput: FileInput,
  BarChart3: BarChart3,
  Plug: Plug,
  Building2: Building2,
  Boxes: Boxes,
};

function getModuleIcon(iconName: string): LucideIcon {
  return ICON_MAP[iconName] ?? Package;
}

/** Turn a module ID like "cost-benchmark" into "Cost Benchmark". */
function formatModuleId(id: string): string {
  return id
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/** Format size in MB with sensible precision. */
function formatSize(sizeMb: number): string {
  if (sizeMb < 1) return `${Math.round(sizeMb * 1024)} KB`;
  if (sizeMb >= 1024) return `${(sizeMb / 1024).toFixed(1)} GB`;
  return `${sizeMb.toFixed(1)} MB`;
}

/* ── Validation rule set metadata ───────────────────────────────────── */

const RULE_SET_META: Record<string, { label: string; flag: string; description: string; variant: 'neutral' | 'blue' | 'success' | 'warning' }> = {
  boq_quality: {
    label: 'BOQ Quality',
    flag: '🌐',
    description: 'Universal checks: quantities, rates, duplicates, anomalies, currency, measurement units',
    variant: 'blue',
  },
  din276: {
    label: 'DIN 276',
    flag: '🇩🇪',
    description: 'DACH cost group hierarchy (Kostengruppen), valid KG codes, completeness',
    variant: 'neutral',
  },
  gaeb: {
    label: 'GAEB',
    flag: '🇩🇪',
    description: 'GAEB DA XML 3.3 ordinal format (XX.XX.XXXX), LV structure',
    variant: 'neutral',
  },
  nrm: {
    label: 'NRM 1/2 (RICS)',
    flag: '🇬🇧',
    description: 'New Rules of Measurement — element codes, structure, completeness (Substructure/Superstructure/Services)',
    variant: 'neutral',
  },
  masterformat: {
    label: 'CSI MasterFormat',
    flag: '🇺🇸',
    description: 'US 6-digit division codes (00–49), core divisions completeness',
    variant: 'neutral',
  },
  sinapi: {
    label: 'SINAPI',
    flag: '🇧🇷',
    description: 'Brazilian SINAPI composition codes (Caixa Econômica Federal), 5-digit format',
    variant: 'neutral',
  },
  gesn: {
    label: 'ГЭСН / ФЕР',
    flag: '🇷🇺',
    description: 'Russian state estimate norms — code format XX-XX-XXX-XX, collection structure',
    variant: 'neutral',
  },
  dpgf: {
    label: 'DPGF / DQE',
    flag: '🇫🇷',
    description: 'French Lots techniques assignment, pricing completeness per NF DTU',
    variant: 'neutral',
  },
  onorm: {
    label: 'ÖNORM B 2063',
    flag: '🇦🇹',
    description: 'Austrian LV position format, description length requirements',
    variant: 'neutral',
  },
  gbt50500: {
    label: 'GB/T 50500',
    flag: '🇨🇳',
    description: 'Chinese 工程量清单计价规范 — 9/12-digit item codes',
    variant: 'neutral',
  },
  cpwd: {
    label: 'CPWD / IS 1200',
    flag: '🇮🇳',
    description: 'Indian DSR item references, IS 1200 metric measurement units',
    variant: 'neutral',
  },
  birimfiyat: {
    label: 'Bayındırlık Birim Fiyat',
    flag: '🇹🇷',
    description: 'Turkish poz number format (XX.XXX/X), Çevre ve Şehircilik standards',
    variant: 'neutral',
  },
  sekisan: {
    label: '積算基準 (Sekisan)',
    flag: '🇯🇵',
    description: 'Japanese construction estimation standards, metric units compliance',
    variant: 'neutral',
  },
};

/* ── Module category display config ──────────────────────────────────── */

const MODULE_CATEGORY_ORDER = ['estimation', 'planning', 'procurement', 'tools', 'regional'] as const;

const MODULE_CATEGORY_META: Record<string, { labelKey: string; defaultLabel: string; descKey: string; defaultDesc: string }> = {
  estimation: {
    labelKey: 'nav.group_estimation',
    defaultLabel: 'Estimation',
    descKey: 'modules.cat_estimation_desc',
    defaultDesc: 'Core tools for building and managing estimates',
  },
  planning: {
    labelKey: 'nav.group_planning',
    defaultLabel: 'Planning',
    descKey: 'modules.cat_planning_desc',
    defaultDesc: 'Scheduling, cost modeling, and timeline management',
  },
  procurement: {
    labelKey: 'nav.group_procurement',
    defaultLabel: 'Procurement',
    descKey: 'modules.cat_procurement_desc',
    defaultDesc: 'Tendering, bid management, and reporting',
  },
  tools: {
    labelKey: 'nav.group_tools',
    defaultLabel: 'Tools',
    descKey: 'modules.cat_tools_desc',
    defaultDesc: 'Analysis, sustainability, exchange formats, and more',
  },
  regional: {
    labelKey: 'modules.cat_regional',
    defaultLabel: 'Regional Standards',
    descKey: 'modules.cat_regional_desc',
    defaultDesc: 'Country-specific BOQ import/export formats and classification standards',
  },
};

/* ── Main component ───────────────────────────────────────────────────── */

export function ModulesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [activeCategory, setActiveCategory] = useState<CategoryKey>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [marketplaceLimit, setMarketplaceLimit] = useState(12);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const { setModuleEnabled, isModuleEnabled, canDisable, getEnabledDependents, syncFromServer } = useModuleStore();

  // Sync module preferences from server on mount
  useEffect(() => {
    void syncFromServer();
  }, [syncFromServer]);

  const { data: modules, isLoading } = useQuery({
    queryKey: ['marketplace'],
    queryFn: () => apiGet<MarketplaceModule[]>('/marketplace'),
  });

  /* Also fetch loaded system modules for the installed-modules section */
  const { data: systemModules } = useQuery({
    queryKey: ['modules'],
    queryFn: () =>
      apiGet<{ modules: SystemModule[] }>('/system/modules').then((d) => d.modules),
  });

  const { data: rules } = useQuery({
    queryKey: ['validation-rules'],
    queryFn: () => apiGet<ValidationRulesResponse>('/system/validation-rules'),
  });

  const { data: demoStatus } = useQuery({
    queryKey: ['demo-status'],
    queryFn: () => apiGet<Record<string, boolean>>('/demo/status'),
  });

  /* Filter modules */
  const filtered = useMemo(() => {
    if (!modules) return [];
    const query = searchQuery.toLowerCase().trim();
    return modules.filter((mod) => {
      const matchesCategory =
        activeCategory === 'all' || mod.category === activeCategory;
      const matchesSearch =
        !query ||
        mod.name.toLowerCase().includes(query) ||
        mod.description.toLowerCase().includes(query) ||
        mod.tags.some((tag) => tag.toLowerCase().includes(query)) ||
        mod.author.toLowerCase().includes(query);
      return matchesCategory && matchesSearch;
    });
  }, [modules, activeCategory, searchQuery]);

  /* Category counts */
  const categoryCounts = useMemo(() => {
    if (!modules) return {} as Record<CategoryKey, number>;
    const counts: Record<string, number> = { all: modules.length };
    for (const mod of modules) {
      counts[mod.category] = (counts[mod.category] ?? 0) + 1;
    }
    return counts as Record<CategoryKey, number>;
  }, [modules]);

  /** Map catalog marketplace module ID to the region key used by the import API. */
  const CATALOG_ID_TO_REGION: Record<string, string> = {
    'catalog-ar-dubai': 'AR_DUBAI',
    'catalog-de-berlin': 'DE_BERLIN',
    'catalog-en-toronto': 'ENG_TORONTO',
    'catalog-sp-barcelona': 'SP_BARCELONA',
    'catalog-fr-paris': 'FR_PARIS',
    'catalog-hi-mumbai': 'HI_MUMBAI',
    'catalog-pt-saopaulo': 'PT_SAOPAULO',
    'catalog-ru-stpetersburg': 'RU_STPETERSBURG',
    'catalog-uk-gbp': 'UK_GBP',
    'catalog-usa-usd': 'USA_USD',
    'catalog-zh-shanghai': 'ZH_SHANGHAI',
  };

  async function handleInstallClick(mod: MarketplaceModule): Promise<void> {
    switch (mod.category) {
      case 'resource_catalog': {
        const region = CATALOG_ID_TO_REGION[mod.id];
        if (!region) {
          addToast({ type: 'error', title: t('marketplace.unknown_region', { defaultValue: 'Unknown region' }), message: t('marketplace.no_region_mapping', { defaultValue: 'No region mapping for {{id}}', id: mod.id }) });
          break;
        }
        setInstallingId(mod.id);
        try {
          const result = await apiPost<{ imported: number; skipped: number; region: string }>(`/v1/catalog/import/${region}`);
          addToast({
            type: 'success',
            title: t('marketplace.catalog_imported', { defaultValue: 'Catalog imported' }),
            message: t('marketplace.catalog_imported_message', { defaultValue: '{{imported}} resources imported, {{skipped}} skipped for {{region}}.', imported: result.imported, skipped: result.skipped, region: result.region }),
          });
          queryClient.invalidateQueries({ queryKey: ['marketplace'] });
          queryClient.invalidateQueries({ queryKey: ['catalog'] });
        } catch (err) {
          addToast({ type: 'error', title: t('marketplace.import_failed', { defaultValue: 'Import failed' }), message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }) });
        } finally {
          setInstallingId(null);
        }
        break;
      }
      case 'cost_database':
        navigate('/costs/import');
        break;
      case 'vector_index': {
        const VECTOR_ID_TO_DB: Record<string, string> = {
          'vector-usa-usd': 'USA_USD',
          'vector-uk-gbp': 'UK_GBP',
          'vector-de-berlin': 'DE_BERLIN',
          'vector-eng-toronto': 'ENG_TORONTO',
          'vector-fr-paris': 'FR_PARIS',
          'vector-sp-barcelona': 'SP_BARCELONA',
          'vector-pt-saopaulo': 'PT_SAOPAULO',
          'vector-ru-stpetersburg': 'RU_STPETERSBURG',
          'vector-ar-dubai': 'AR_DUBAI',
          'vector-zh-shanghai': 'ZH_SHANGHAI',
          'vector-hi-mumbai': 'HI_MUMBAI',
        };
        const dbId = VECTOR_ID_TO_DB[mod.id];
        if (!dbId) {
          addToast({ type: 'error', title: t('marketplace.unknown_region', { defaultValue: 'Unknown region' }), message: t('marketplace.no_region_mapping', { defaultValue: 'No region mapping for {{id}}', id: mod.id }) });
          break;
        }
        setInstallingId(mod.id);
        try {
          // Check what vector backend is available
          const status = await apiGet<{ backend: string; connected: boolean; can_restore_snapshots: boolean; can_generate_locally: boolean }>('/v1/costs/vector/status');

          let result;
          if (status.can_restore_snapshots) {
            // Qdrant: restore pre-built 3072d snapshot from GitHub
            result = await apiPost<{ restored?: boolean; indexed?: number; database?: string; duration_seconds?: number }>(`/v1/costs/vector/restore-snapshot/${dbId}`);
          } else if (status.connected) {
            // LanceDB: generate or load vectors
            result = await apiPost<{ restored?: boolean; indexed?: number; database?: string; duration_seconds?: number }>(`/v1/costs/vector/load-github/${dbId}`);
          } else {
            throw new Error('No vector database available. Install LanceDB (pip install lancedb) or start Qdrant (docker run -p 6333:6333 qdrant/qdrant)');
          }

          addToast({
            type: 'success',
            title: t('marketplace.vector_imported', { defaultValue: 'Vector index loaded' }),
            message: `${result.indexed || result.restored ? 'Vectors ready' : 'Restored'} for ${dbId}`,
          });
          queryClient.invalidateQueries({ queryKey: ['marketplace'] });
          queryClient.invalidateQueries({ queryKey: ['vector-status'] });
        } catch (err) {
          addToast({ type: 'error', title: t('marketplace.import_failed', { defaultValue: 'Import failed' }), message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }) });
        } finally {
          setInstallingId(null);
        }
        break;
      }
      case 'demo_project': {
        const demoId = mod.id.replace('demo-', '');
        setInstallingId(mod.id);
        try {
          const result = await apiPost<{ project_id: string; project_name: string }>(`/demo/install/${demoId}`);
          addToast({ type: 'success', title: t('marketplace.demo_installed', { defaultValue: 'Demo installed' }), message: t('marketplace.demo_installed_message', { defaultValue: '{{name}} created with full BOQ, schedule, budget, and tendering.', name: result.project_name }) });
          queryClient.invalidateQueries({ queryKey: ['demo-status'] });
          queryClient.invalidateQueries({ queryKey: ['marketplace'] });
          queryClient.invalidateQueries({ queryKey: ['projects'] });
          navigate(`/projects/${result.project_id}`);
        } catch (err) {
          addToast({ type: 'error', title: t('marketplace.install_failed', { defaultValue: 'Install failed' }), message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }) });
        } finally {
          setInstallingId(null);
        }
        break;
      }
      // language, converter, analytics, integration categories show
      // static badges (Included / Built-in / Coming Soon) — no install action.
    }
  }

  async function handleUninstallDemo(demoId: string): Promise<void> {
    const confirmed = window.confirm(
      t('marketplace.uninstall_demo_confirm', {
        defaultValue: 'Are you sure you want to uninstall this demo project? All associated data will be deleted.',
      }),
    );
    if (!confirmed) return;

    setInstallingId(`demo-${demoId}`);
    try {
      const result = await apiDelete<{ deleted_projects: number }>(`/demo/uninstall/${demoId}`);
      addToast({
        type: 'success',
        title: t('marketplace.demo_uninstalled', { defaultValue: 'Demo uninstalled' }),
        message: t('marketplace.demo_uninstalled_message', {
          defaultValue: '{{count}} project(s) removed.',
          count: result.deleted_projects,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['demo-status'] });
      queryClient.invalidateQueries({ queryKey: ['marketplace'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('marketplace.uninstall_failed', { defaultValue: 'Uninstall failed' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setInstallingId(null);
    }
  }

  async function handleClearAllDemos(): Promise<void> {
    const confirmed = window.confirm(
      t('marketplace.clear_all_demos_confirm', {
        defaultValue: 'Are you sure you want to remove ALL demo projects and their data? This cannot be undone.',
      }),
    );
    if (!confirmed) return;

    try {
      const result = await apiDelete<{ deleted_projects: number }>('/demo/clear-all');
      addToast({
        type: 'success',
        title: t('marketplace.demos_cleared', { defaultValue: 'Demo data cleared' }),
        message: t('marketplace.demos_cleared_message', {
          defaultValue: '{{count}} demo project(s) removed.',
          count: result.deleted_projects,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['demo-status'] });
      queryClient.invalidateQueries({ queryKey: ['marketplace'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('marketplace.clear_failed', { defaultValue: 'Clear failed' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    }
  }

  return (
    <div className="max-w-content mx-auto">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="mb-8 animate-card-in" style={{ animationDelay: '0ms' }}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-content-primary">
              {t('modules.page_title', { defaultValue: 'Modules & Marketplace' })}
            </h1>
            <p className="mt-1 text-sm text-content-secondary">
              {t('modules.page_subtitle', {
                defaultValue:
                  'Manage optional features and browse data packages for your platform.',
              })}
            </p>
            <InfoHint inline className="ml-1" text={t('marketplace.description', { defaultValue: 'Extend OpenEstimate with regional cost databases, resource catalogs (CWICR), vector search indices for AI, language packs, demo projects, and integrations. Install a module to activate it — uninstall anytime.' })} />
          </div>
          {demoStatus && Object.values(demoStatus).some(Boolean) && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Trash2 size={14} />}
              onClick={() => void handleClearAllDemos()}
            >
              {t('marketplace.clear_demo_data', { defaultValue: 'Clear All Demo Data' })}
            </Button>
          )}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════ */}
      {/* ── SECTION 1: Modules (unified toggles) ─────────────────── */}
      {/* ══════════════════════════════════════════════════════════════ */}
      <UnifiedModulesSection
        isModuleEnabled={isModuleEnabled}
        setModuleEnabled={setModuleEnabled}
        canDisable={canDisable}
        getEnabledDependents={getEnabledDependents}
      />

      {/* ══════════════════════════════════════════════════════════════ */}
      {/* ── SECTION 2: Marketplace (data packages) ───────────────── */}
      {/* ══════════════════════════════════════════════════════════════ */}

      {/* Installed data packages */}
      {modules && modules.filter((m) => m.installed).length > 0 && (
        <div className="mb-6 animate-card-in" style={{ animationDelay: '80ms' }}>
          <h3 className="text-xs font-semibold text-content-tertiary uppercase tracking-wider mb-2">
            {t('marketplace.my_modules', { defaultValue: 'Installed Packages' })}
          </h3>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {modules.filter((m) => m.installed).map((mod) => {
              const Icon = getModuleIcon(mod.icon);
              const statusBadge = getInstalledModuleBadge(mod, t);

              return (
                <div
                  key={mod.id}
                  className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-elevated px-3 py-2.5 transition-all hover:border-border"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-semantic-success-bg text-[#15803d] dark:text-emerald-400">
                    <Icon size={15} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <span className="text-xs font-medium text-content-primary truncate block">{mod.name}</span>
                    <span className="text-2xs text-content-tertiary">
                      {statusBadge.subtitle}
                    </span>
                  </div>

                  {statusBadge.type === 'badge' ? (
                    <Badge variant="success" size="sm">
                      <Check size={10} className="mr-0.5" />
                      {statusBadge.label}
                    </Badge>
                  ) : statusBadge.type === 'manage' ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => navigate('/costs/import')}
                    >
                      {t('marketplace.manage', 'Manage')}
                    </Button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Marketplace header */}
      <h2 className="text-sm font-semibold text-content-secondary uppercase tracking-wider mb-3 mt-10">
        {t('marketplace.available', { defaultValue: 'Data Packages & Add-ons' })}
      </h2>

      {/* Search bar */}
      <div
        className="mb-6 max-w-md animate-card-in"
        style={{ animationDelay: '100ms' }}
      >
        <Input
          placeholder={t('marketplace.search_placeholder', {
            defaultValue: 'Search packages...',
          })}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          icon={<Search size={16} />}
        />
      </div>

      {/* Category tabs */}
      <div
        className="mb-6 flex flex-wrap gap-2 animate-card-in"
        style={{ animationDelay: '120ms' }}
      >
        {CATEGORY_KEYS.map((key) => {
          const meta = CATEGORIES[key];
          const Icon = meta.icon;
          const isActive = activeCategory === key;
          const count = categoryCounts[key] ?? 0;
          return (
            <button
              key={key}
              onClick={() => setActiveCategory(key)}
              className={`
                inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5
                text-sm font-medium transition-all duration-fast ease-oe
                ${
                  isActive
                    ? 'bg-oe-blue text-content-inverse shadow-xs'
                    : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary hover:text-content-primary'
                }
              `}
            >
              <Icon size={14} strokeWidth={1.75} />
              <span>{t(meta.labelKey, { defaultValue: meta.defaultLabel })}</span>
              {count > 0 && (
                <span
                  className={`
                    ml-0.5 text-2xs font-semibold rounded-full px-1.5
                    ${isActive ? 'bg-white/20 text-content-inverse' : 'bg-surface-primary text-content-tertiary'}
                  `}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Module grid */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="animate-pulse">
              <div className="flex items-start gap-3">
                <div className="h-11 w-11 rounded-xl bg-surface-secondary" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-2/3 rounded bg-surface-secondary" />
                  <div className="h-3 w-full rounded bg-surface-secondary" />
                  <div className="h-3 w-1/2 rounded bg-surface-secondary" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-16 text-center">
          <Package size={40} className="mx-auto mb-3 text-content-tertiary" />
          <p className="text-sm font-medium text-content-secondary">
            {t('marketplace.no_results', { defaultValue: 'No modules found' })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('marketplace.no_results_hint', {
              defaultValue: 'Try adjusting your search or category filter.',
            })}
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.slice(0, marketplaceLimit).map((mod, i) => {
              const isDemoInstalled =
                mod.category === 'demo_project' &&
                demoStatus?.[mod.id.replace('demo-', '')] === true;
              return (
                <MarketplaceCard
                  key={mod.id}
                  module={mod}
                  index={i}
                  isInstalling={installingId === mod.id}
                  onInstall={() => void handleInstallClick(mod)}
                  isDemoInstalled={isDemoInstalled}
                  onUninstallDemo={
                    mod.category === 'demo_project'
                      ? () => void handleUninstallDemo(mod.id.replace('demo-', ''))
                      : undefined
                  }
                />
              );
            })}
          </div>
          {filtered.length > marketplaceLimit && (
            <div className="mt-6 text-center">
              <Button
                variant="secondary"
                onClick={() => setMarketplaceLimit((prev) => prev + 12)}
              >
                {t('marketplace.show_more', {
                  defaultValue: 'Show more ({{remaining}} remaining)',
                  remaining: filtered.length - marketplaceLimit,
                })}
              </Button>
            </div>
          )}
        </>
      )}

      {/* ── Installed system modules section ──────────────────────── */}
      {systemModules && systemModules.length > 0 && (
        <div className="mt-12 animate-card-in" style={{ animationDelay: '300ms' }}>
          <h2 className="text-lg font-semibold text-content-primary mb-1">
            {t('marketplace.installed_modules', {
              defaultValue: 'Installed Core Modules',
            })}
          </h2>
          <p className="text-sm text-content-secondary mb-4">
            {systemModules.length}{' '}
            {t('marketplace.modules_loaded', { defaultValue: 'modules loaded' })}
            {rules?.rules ? `, ${rules.rules.length} ${t('marketplace.validation_rules_active', { defaultValue: 'validation rules active' })}` : ''}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {systemModules.map((mod, i) => (
              <Card
                key={mod.name}
                className="animate-card-in"
                style={{ animationDelay: `${350 + i * 40}ms` }}
                padding="sm"
              >
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-semantic-success-bg text-[#15803d] dark:text-emerald-400">
                    <ShieldCheck size={15} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-semibold text-content-primary truncate">
                        {mod.display_name}
                      </span>
                      <Badge variant="success" size="sm" dot>
                        {t('marketplace.active', { defaultValue: 'Active' })}
                      </Badge>
                    </div>
                    <div className="text-2xs text-content-tertiary font-mono">
                      v{mod.version}
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* ── Validation Rules ─────────────────────────────────────── */}
      {rules?.rule_sets && Object.keys(rules.rule_sets).length > 0 && (
        <div
          className="mt-8 animate-card-in"
          style={{ animationDelay: '500ms' }}
        >
          <h2 className="text-lg font-semibold text-content-primary mb-1">
            {t('marketplace.validation_rule_sets', {
              defaultValue: 'Validation Rule Sets',
            })}
          </h2>
          <p className="text-sm text-content-secondary mb-4">
            {t('marketplace.validation_rule_sets_desc', {
              defaultValue: '{{count}} rule sets with {{total}} rules — automatically applied based on project region and classification standard',
              count: Object.keys(rules.rule_sets).length,
              total: Object.values(rules.rule_sets).reduce((a, b) => a + b, 0),
            })}
          </p>
          <Card padding="none">
            <div className="divide-y divide-border-light">
              {Object.entries(rules.rule_sets).map(([name, count]) => {
                const meta = RULE_SET_META[name];
                return (
                  <div
                    key={name}
                    className="flex items-center justify-between px-5 py-3.5"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-base shrink-0" aria-hidden="true">{meta?.flag ?? '📋'}</span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-content-primary">
                            {meta?.label ?? name}
                          </span>
                          <span className="text-2xs font-mono text-content-quaternary">
                            {name}
                          </span>
                        </div>
                        {meta?.description && (
                          <p className="text-xs text-content-tertiary mt-0.5 truncate">
                            {meta.description}
                          </p>
                        )}
                      </div>
                    </div>
                    <Badge variant={meta?.variant ?? 'neutral'} size="sm" className="shrink-0 ml-3">
                      {count} {t('marketplace.rules', { defaultValue: 'rules' })}
                    </Badge>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>
      )}

    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* ── Unified Modules Section (all optional features in one place) ─────── */
/* ══════════════════════════════════════════════════════════════════════════ */

interface UnifiedModulesSectionProps {
  isModuleEnabled: (key: string) => boolean;
  setModuleEnabled: (key: string, enabled: boolean) => void;
  canDisable: (key: string) => { allowed: boolean; blockedBy: string[] };
  getEnabledDependents: (key: string) => string[];
}

function UnifiedModulesSection({
  isModuleEnabled,
  setModuleEnabled,
  canDisable,
  getEnabledDependents,
}: UnifiedModulesSectionProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const grouped = getModulesByCategory();

  function handleToggle(key: string, name: string, currentlyEnabled: boolean) {
    if (currentlyEnabled) {
      const { allowed, blockedBy } = canDisable(key);
      if (!allowed) {
        addToast({
          type: 'warning',
          title: t('modules.cannot_disable', { defaultValue: 'Cannot disable' }),
          message: t('modules.required_by', {
            defaultValue: '{{name}} is required by: {{deps}}',
            name,
            deps: blockedBy.join(', '),
          }),
        });
        return;
      }
    }
    setModuleEnabled(key, !currentlyEnabled);
    addToast({
      type: 'success',
      title: !currentlyEnabled
        ? t('modules.enabled', { defaultValue: '{{name}} enabled', name })
        : t('modules.disabled', { defaultValue: '{{name}} disabled', name }),
    });
  }

  const isI18nKey = (s: string) => s.startsWith('modules.') || s.startsWith('nav.') || s.startsWith('validation.') || s.startsWith('schedule.') || s.startsWith('tendering.');

  return (
    <div className="mb-10 animate-card-in" style={{ animationDelay: '30ms' }}>
      <div className="mb-5">
        <h2 className="text-sm font-semibold text-content-secondary uppercase tracking-wider mb-1">
          {t('modules.section_title', { defaultValue: 'Modules' })}
        </h2>
        <p className="text-xs text-content-tertiary">
          {t('modules.section_desc', {
            defaultValue: 'Toggle optional features on or off. Disabled modules are hidden from the sidebar.',
          })}
        </p>
      </div>

      <div className="space-y-6">
        {MODULE_CATEGORY_ORDER.map((cat) => {
          const mods = grouped[cat];
          if (!mods || mods.length === 0) return null;
          const catMeta = MODULE_CATEGORY_META[cat] ?? { labelKey: cat, defaultLabel: cat, descKey: '', defaultDesc: '' };

          return (
            <div key={cat}>
              {/* Category header */}
              <div className="flex items-center gap-2 mb-2.5">
                <h3 className="text-xs font-semibold text-content-primary">
                  {t(catMeta.labelKey, { defaultValue: catMeta.defaultLabel })}
                </h3>
                <div className="flex-1 h-px bg-border-light" />
                <span className="text-2xs text-content-quaternary">
                  {mods.filter((m) => isModuleEnabled(m.id)).length}/{mods.length} {t('modules.active_count', { defaultValue: 'active' })}
                </span>
              </div>

              {/* Module grid */}
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {mods.map((mod) => {
                  const Icon = mod.icon;
                  const enabled = isModuleEnabled(mod.id);
                  const deps = mod.depends ?? [];
                  const dependents = getEnabledDependents(mod.id);
                  const displayName = isI18nKey(mod.name)
                    ? t(mod.name, { defaultValue: formatModuleId(mod.id) })
                    : mod.name;
                  const displayDesc = isI18nKey(mod.description)
                    ? t(mod.description, { defaultValue: '' })
                    : mod.description;

                  return (
                    <ModuleToggleCard
                      key={mod.id}
                      icon={Icon}
                      name={displayName}
                      description={displayDesc}
                      version={mod.version}
                      enabled={enabled}
                      onToggle={() => handleToggle(mod.id, displayName, enabled)}
                      deps={deps}
                      dependents={dependents}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Module Toggle Card ──────────────────────────────────────────────── */

interface ModuleToggleCardProps {
  icon: LucideIcon;
  name: string;
  description: string;
  version?: string;
  enabled: boolean;
  onToggle: () => void;
  deps?: string[];
  dependents?: string[];
}

function ModuleToggleCard({
  icon: Icon,
  name,
  description,
  version,
  enabled,
  onToggle,
  deps,
  dependents,
}: ModuleToggleCardProps) {
  const { t } = useTranslation();
  const hasBlockers = (dependents ?? []).length > 0;

  return (
    <div
      className={`
        flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-all
        ${enabled
          ? 'border-border-light bg-surface-elevated hover:border-border'
          : 'border-border-light/50 bg-surface-secondary/50 opacity-60 hover:opacity-80'
        }
      `}
    >
      <div
        className={`
          flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors
          ${enabled ? 'bg-oe-blue-subtle text-oe-blue' : 'bg-surface-tertiary text-content-quaternary'}
        `}
      >
        <Icon size={15} />
      </div>
      <div className="min-w-0 flex-1">
        <span className="text-xs font-medium text-content-primary truncate block">{name}</span>
        <span className="text-2xs text-content-tertiary line-clamp-1">
          {description}
          {version ? ` · v${version}` : ''}
        </span>
        {hasBlockers && enabled && (
          <div className="flex items-center gap-1 mt-0.5">
            <AlertTriangle size={9} className="text-amber-500 shrink-0" />
            <span className="text-2xs text-amber-600 dark:text-amber-400 truncate">
              {t('modules.required_by_short', {
                defaultValue: 'Required by {{deps}}',
                deps: (dependents ?? []).join(', '),
              })}
            </span>
          </div>
        )}
        {deps && deps.length > 0 && (
          <span className="text-2xs text-content-quaternary">
            {t('modules.depends_on', { defaultValue: 'Requires: {{deps}}', deps: deps.join(', ') })}
          </span>
        )}
      </div>

      {/* Toggle switch */}
      <button
        onClick={onToggle}
        role="switch"
        aria-checked={enabled}
        aria-label={`${enabled ? 'Disable' : 'Enable'} ${name}`}
        className="shrink-0"
      >
        <div
          className={`
            relative h-5 w-9 rounded-full transition-colors duration-200
            ${enabled ? 'bg-oe-blue' : 'bg-content-quaternary/40'}
          `}
        >
          <div
            className={`
              absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200
              ${enabled ? 'translate-x-[18px]' : 'translate-x-0.5'}
            `}
          />
        </div>
      </button>
    </div>
  );
}

/* ── Marketplace Card ────────────────────────────────────────────────── */

interface MarketplaceCardProps {
  module: MarketplaceModule;
  index: number;
  isInstalling?: boolean;
  onInstall: () => void;
  isDemoInstalled?: boolean;
  onUninstallDemo?: () => void;
}

function MarketplaceCard({ module: mod, index, isInstalling, onInstall, isDemoInstalled, onUninstallDemo }: MarketplaceCardProps) {
  const { t } = useTranslation();
  const Icon = getModuleIcon(mod.icon);

  const isLanguage = mod.category === 'language';
  const isBuiltIn = mod.category === 'converter' || mod.category === 'analytics';
  const isIntegration = mod.category === 'integration';

  return (
    <Card
      hoverable
      className="animate-card-in group"
      style={{ animationDelay: `${150 + index * 40}ms` }}
    >
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div
          className={`
            flex h-11 w-11 shrink-0 items-center justify-center rounded-xl
            transition-colors duration-fast ease-oe
            ${
              mod.category === 'resource_catalog'
                ? 'bg-[#fef3c7] text-[#92400e] dark:bg-amber-900/30 dark:text-amber-300'
                : mod.category === 'cost_database'
                  ? 'bg-oe-blue-subtle text-oe-blue'
                  : mod.category === 'vector_index'
                    ? 'bg-[#f0e6ff] text-[#7c3aed] dark:bg-purple-900/30 dark:text-purple-400'
                    : mod.category === 'language'
                      ? 'bg-semantic-success-bg text-[#15803d] dark:text-emerald-400'
                      : mod.category === 'converter'
                      ? 'bg-semantic-warning-bg text-[#b45309] dark:text-amber-400'
                      : mod.category === 'analytics'
                        ? 'bg-[#e0f2fe] text-[#0369a1] dark:bg-sky-900/30 dark:text-sky-400'
                        : 'bg-surface-secondary text-content-secondary'
            }
          `}
        >
          <Icon size={20} strokeWidth={1.75} />
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          {/* Title row */}
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-content-primary truncate">
              {mod.name}
            </span>
          </div>

          {/* Author & version */}
          <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-content-tertiary">
            <span>{mod.author}</span>
            <span className="text-border">|</span>
            <span className="font-mono">v{mod.version}</span>
            <span className="text-border">|</span>
            <span>{formatSize(mod.size_mb)}</span>
          </div>

          {/* Description */}
          <p className="mt-2 text-xs text-content-secondary line-clamp-2 leading-relaxed">
            {mod.description}
          </p>

          {/* Vector Index prerequisite hint */}
          {mod.category === 'vector_index' && !mod.installed && (
            <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-purple-50 dark:bg-purple-900/20 border border-purple-200/50 dark:border-purple-800/30 px-2.5 py-1.5">
              <Info size={12} className="text-purple-500 shrink-0 mt-0.5" />
              <div className="text-2xs text-purple-700 dark:text-purple-300 leading-relaxed">
                <strong>Option A:</strong> Qdrant + Snapshot (best quality, 3072d):<br/>
                <code className="font-mono bg-purple-100 dark:bg-purple-800/40 px-1 rounded text-[10px]">docker run -p 6333:6333 qdrant/qdrant</code><br/>
                <strong>Option B:</strong> LanceDB (lightweight, 384d):<br/>
                <code className="font-mono bg-purple-100 dark:bg-purple-800/40 px-1 rounded text-[10px]">pip install lancedb sentence-transformers</code>
              </div>
            </div>
          )}

          {/* Tags & price */}
          <div className="mt-3 flex items-center gap-1.5 flex-wrap">
            {mod.tags.slice(0, 3).map((tag) => (
              <Badge key={tag} variant="neutral" size="sm">
                {tag}
              </Badge>
            ))}
            {mod.tags.length > 3 && (
              <Badge variant="neutral" size="sm">
                +{mod.tags.length - 3}
              </Badge>
            )}

            <div className="flex-1" />

            {!isLanguage && !isIntegration && (
              <Badge variant="success" size="sm">
                {t('marketplace.free', { defaultValue: 'Free' })}
              </Badge>
            )}
          </div>

          {/* Install / Status button */}
          <div className="mt-3">
            {/* Language packs are always bundled */}
            {isLanguage ? (
              <Badge variant="success" size="sm">
                <Check size={10} className="mr-0.5" />
                {t('marketplace.included', { defaultValue: 'Included' })}
              </Badge>
            ) : /* Converters and analytics are built-in */
            isBuiltIn ? (
              <Badge variant="success" size="sm">
                <Check size={10} className="mr-0.5" />
                {t('marketplace.builtin', { defaultValue: 'Built-in' })}
              </Badge>
            ) : /* Integrations are coming soon */
            isIntegration ? (
              <Badge variant="neutral" size="sm">
                <Clock size={10} className="mr-0.5" />
                {t('marketplace.coming_soon', { defaultValue: 'Coming Soon' })}
              </Badge>
            ) : /* Installed states for installable categories */
            mod.installed && mod.category === 'cost_database' ? (
              <Button variant="secondary" size="sm" icon={<Check size={14} />} onClick={onInstall}>
                {t('marketplace.manage', { defaultValue: 'Manage' })}
              </Button>
            ) : mod.installed && mod.category === 'resource_catalog' ? (
              <Button variant="secondary" size="sm" disabled icon={<Check size={14} />}>
                {t('marketplace.imported', { defaultValue: 'Imported' })}
              </Button>
            ) : mod.installed && mod.category === 'vector_index' ? (
              <Button variant="secondary" size="sm" disabled icon={<Check size={14} />}>
                {t('marketplace.indexed', { defaultValue: 'Indexed' })}
              </Button>
            ) : (mod.installed || isDemoInstalled) && mod.category === 'demo_project' ? (
              <div className="flex items-center gap-2">
                <Badge variant="success" size="sm">
                  <Check size={10} className="mr-0.5" />
                  {t('marketplace.installed', { defaultValue: 'Installed' })}
                </Badge>
                {onUninstallDemo && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={isInstalling ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    onClick={onUninstallDemo}
                    disabled={isInstalling}
                    className="text-red-600 hover:text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:text-red-300 dark:hover:bg-red-900/20"
                  >
                    {t('marketplace.uninstall', { defaultValue: 'Uninstall' })}
                  </Button>
                )}
              </div>
            ) : (
              <Button
                variant="primary"
                size="sm"
                icon={isInstalling ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                onClick={onInstall}
                disabled={isInstalling}
              >
                {isInstalling
                  ? t('marketplace.installing', { defaultValue: 'Installing...' })
                  : t('marketplace.install', { defaultValue: 'Install' })}
              </Button>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

/* ── Installed module badge helper ────────────────────────────────────── */

interface InstalledBadgeInfo {
  type: 'badge' | 'manage';
  label: string;
  subtitle: string;
}

function getInstalledModuleBadge(
  mod: MarketplaceModule,
  t: (key: string, opts?: Record<string, unknown>) => string,
): InstalledBadgeInfo {
  switch (mod.category) {
    case 'language':
      return { type: 'badge', label: t('marketplace.included', { defaultValue: 'Included' }), subtitle: t('marketplace.included', { defaultValue: 'Included' }) };
    case 'analytics':
    case 'integration':
    case 'converter':
      return { type: 'badge', label: t('marketplace.builtin', { defaultValue: 'Built-in' }), subtitle: t('marketplace.builtin', { defaultValue: 'Built-in' }) };
    case 'resource_catalog':
      return { type: 'badge', label: t('marketplace.imported', { defaultValue: 'Imported' }), subtitle: t('marketplace.imported', { defaultValue: 'Imported' }) };
    case 'vector_index':
      return { type: 'badge', label: t('marketplace.indexed', { defaultValue: 'Indexed' }), subtitle: t('marketplace.indexed', { defaultValue: 'Indexed' }) };
    case 'demo_project':
      return { type: 'badge', label: t('marketplace.installed', { defaultValue: 'Installed' }), subtitle: t('marketplace.installed', { defaultValue: 'Installed' }) };
    case 'cost_database':
      return { type: 'manage', label: t('marketplace.manage', { defaultValue: 'Manage' }), subtitle: `v${mod.version}` };
    default:
      return { type: 'badge', label: t('marketplace.installed', { defaultValue: 'Installed' }), subtitle: `v${mod.version}` };
  }
}

/* ── Helper types for system modules query ────────────────────────────── */

interface SystemModule {
  name: string;
  version: string;
  display_name: string;
  category: string;
  depends: string[];
  has_router: boolean;
  loaded: boolean;
}

interface ValidationRulesResponse {
  rule_sets: Record<string, number>;
  rules: Array<{ rule_id: string; name: string; standard: string }>;
}
