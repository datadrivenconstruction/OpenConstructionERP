import { useState, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Plus,
  Package,
  Wrench,
  Users,
  HardHat,
  Boxes,
  X,
  Layers,
  Copy,
  Check,
  CheckSquare,
  Square,
  Database,
  Upload,
  Trash2,
  House,
  TrendingUp,
  AlertTriangle,
  type LucideIcon,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Skeleton, InfoHint, CountryFlag } from '@/shared/ui';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { REGION_MAP } from '@/stores/useCostDatabaseStore';
import {
  assembliesApi,
  type CreateAssemblyData,
  type CreateComponentData,
} from '@/features/assemblies/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface CatalogResource {
  id: string;
  resource_code: string;
  name: string;
  resource_type: string;
  category: string;
  unit: string;
  base_price: number;
  min_price: number;
  max_price: number;
  currency: string;
  usage_count: number;
  source: string;
  region: string | null;
  specifications: Record<string, unknown>;
  is_active: boolean;
  metadata_: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface CatalogSearchResponse {
  items: CatalogResource[];
  total: number;
  limit: number;
  offset: number;
}

interface CatalogTypeStat {
  resource_type: string;
  count: number;
}

interface CatalogCategoryStat {
  category: string;
  count: number;
}

interface CatalogStatsResponse {
  total: number;
  by_type: CatalogTypeStat[];
  by_category: CatalogCategoryStat[];
}

interface CatalogRegionStat {
  region: string;
  count: number;
}

interface SelectedResourceEntry {
  resource: CatalogResource;
  quantity: number;
}

/* ── Constants ─────────────────────────────────────────────────────────── */

const PAGE_SIZE = 20;

interface TypeTabConfig {
  key: string;
  label: string;
  icon: LucideIcon;
}

const TYPE_TABS: TypeTabConfig[] = [
  { key: '', label: 'All', icon: Boxes },
  { key: 'material', label: 'Materials', icon: Package },
  { key: 'equipment', label: 'Equipment', icon: Wrench },
  { key: 'labor', label: 'Labor', icon: Users },
  { key: 'operator', label: 'Operators', icon: HardHat },
];

const UNITS = ['', 'm', 'm2', 'm3', 'kg', 't', 'h', 'pcs', 'lsum', 'set', 'lm'] as const;

interface CWICRRegionInfo {
  id: string;
  name: string;
  flagId: string;
  currency: string;
}

const CWICR_REGIONS: CWICRRegionInfo[] = [
  { id: 'USA_USD', name: 'United States', flagId: 'us', currency: 'USD' },
  { id: 'UK_GBP', name: 'United Kingdom', flagId: 'gb', currency: 'GBP' },
  { id: 'DE_BERLIN', name: 'Germany / DACH', flagId: 'de', currency: 'EUR' },
  { id: 'ENG_TORONTO', name: 'Canada', flagId: 'ca', currency: 'CAD' },
  { id: 'FR_PARIS', name: 'France', flagId: 'fr', currency: 'EUR' },
  { id: 'SP_BARCELONA', name: 'Spain', flagId: 'es', currency: 'EUR' },
  { id: 'PT_SAOPAULO', name: 'Brazil', flagId: 'br', currency: 'BRL' },
  { id: 'RU_STPETERSBURG', name: 'Russia / CIS', flagId: 'ru', currency: 'RUB' },
  { id: 'AR_DUBAI', name: 'Middle East', flagId: 'ae', currency: 'AED' },
  { id: 'ZH_SHANGHAI', name: 'China', flagId: 'cn', currency: 'CNY' },
  { id: 'HI_MUMBAI', name: 'India', flagId: 'in', currency: 'INR' },
];

/* ── API helpers ───────────────────────────────────────────────────────── */

function buildSearchUrl(
  q: string,
  resourceType: string,
  category: string,
  unit: string,
  region: string,
  offset: number,
): string {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (resourceType) params.set('resource_type', resourceType);
  if (category) params.set('category', category);
  if (unit) params.set('unit', unit);
  if (region) params.set('region', region);
  params.set('limit', String(PAGE_SIZE));
  params.set('offset', String(offset));
  return `/v1/catalog/?${params.toString()}`;
}

/* ── Number formatting ─────────────────────────────────────────────────── */

const fmt = (n: number) =>
  new Intl.NumberFormat(getIntlLocale(), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);

/* ── Mini Flag ─────────────────────────────────────────────────────────── */

function MiniFlag({ code, size = 14 }: { code: string; size?: number }) {
  if (!code || code === 'custom') {
    return <House size={size} className="shrink-0 text-oe-blue" />;
  }
  return <CountryFlag code={code} size={Math.round(size * 1.6)} className="shadow-xs border border-black/5" />;
}

/* ── Region Import Grid ──────────────────────────────────────────────── */

function RegionImportGrid({
  loadedRegionIds,
  onImported,
}: {
  loadedRegionIds: Set<string>;
  onImported: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [importingId, setImportingId] = useState<string | null>(null);

  const importMutation = useMutation({
    mutationFn: (regionId: string) =>
      apiPost<{ imported: number; skipped: number; region: string }>(
        `/v1/catalog/import/${regionId}`,
      ),
    onSuccess: (result) => {
      addToast({
        type: 'success',
        title: t('catalog.import_success', { defaultValue: 'Import complete' }),
        message: `${result.imported} ${t('catalog.resources_imported', { defaultValue: 'resources imported' })}`,
      });
      setImportingId(null);
      onImported();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('catalog.import_failed', { defaultValue: 'Import failed' }),
        message: err.message,
      });
      setImportingId(null);
    },
  });

  const handleImport = useCallback(
    (regionId: string) => {
      setImportingId(regionId);
      importMutation.mutate(regionId);
    },
    [importMutation],
  );

  return (
    <Card padding="none" className="mb-6">
      <div className="p-5 border-b border-border-light">
        <div className="flex items-center gap-3 mb-1">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
            <Database size={18} />
          </div>
          <div>
            <h2 className="text-base font-semibold text-content-primary">
              {t('catalog.import_regions_title', { defaultValue: 'Import Resource Catalog' })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {t('catalog.import_regions_desc', {
                defaultValue:
                  'Download pre-built resource catalogs from CWICR regional databases',
              })}
            </p>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {CWICR_REGIONS.map((region) => {
          const isLoaded = loadedRegionIds.has(region.id);
          const isImporting = importingId === region.id;

          return (
            <div
              key={region.id}
              className={`relative flex items-center gap-3 rounded-xl border p-3.5 transition-all ${
                isLoaded
                  ? 'border-green-200 bg-green-50/50 dark:border-green-800 dark:bg-green-900/10'
                  : 'border-border hover:border-oe-blue/40 hover:bg-surface-secondary/50'
              }`}
            >
              <MiniFlag code={region.flagId} size={20} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-content-primary truncate">{region.name}</p>
                <p className="text-2xs text-content-tertiary">{region.currency}</p>
              </div>
              {isLoaded ? (
                <Badge variant="success" size="sm">
                  {t('catalog.loaded', { defaultValue: 'Loaded' })}
                </Badge>
              ) : (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={
                    isImporting ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Upload size={12} />
                    )
                  }
                  onClick={() => handleImport(region.id)}
                  disabled={isImporting}
                >
                  {isImporting
                    ? t('catalog.importing', { defaultValue: 'Importing...' })
                    : t('catalog.import', { defaultValue: 'Import' })}
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/* ── Region Tab Bar ──────────────────────────────────────────────────── */

function RegionTabBar({
  regionStats,
  activeRegion,
  onChangeRegion,
  onImportClick,
}: {
  regionStats: CatalogRegionStat[];
  activeRegion: string;
  onChangeRegion: (region: string) => void;
  onImportClick: () => void;
}) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const totalItems = regionStats.reduce((s, r) => s + r.count, 0);
  const statsMap = new Map(regionStats.map((r) => [r.region, r.count]));

  const checkScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 4);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    checkScroll();
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener('scroll', checkScroll, { passive: true });
    const ro = new ResizeObserver(checkScroll);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', checkScroll);
      ro.disconnect();
    };
  }, [checkScroll, regionStats]);

  const scroll = useCallback((dir: 'left' | 'right') => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollBy({ left: dir === 'left' ? -200 : 200, behavior: 'smooth' });
  }, []);

  if (regionStats.length === 0) return null;

  return (
    <div className="mb-4 relative rounded-xl border border-border-light bg-surface-elevated/50 px-1 pt-1 pb-0">
      {canScrollLeft && (
        <button
          onClick={() => scroll('left')}
          className="absolute left-0 top-0 bottom-0 z-10 flex items-center pl-0.5 pr-3 bg-gradient-to-r from-surface-elevated/80 via-surface-elevated/60 to-transparent rounded-l-xl"
        >
          <ChevronLeft size={16} className="text-content-tertiary" />
        </button>
      )}
      {canScrollRight && (
        <button
          onClick={() => scroll('right')}
          className="absolute right-0 top-0 bottom-0 z-10 flex items-center pr-0.5 pl-3 bg-gradient-to-l from-surface-elevated/80 via-surface-elevated/60 to-transparent rounded-r-xl"
        >
          <ChevronRight size={16} className="text-content-tertiary" />
        </button>
      )}

      <div
        ref={scrollRef}
        className="flex items-stretch gap-0.5 overflow-x-auto scrollbar-none scroll-smooth"
      >
        {/* All tab */}
        <button
          onClick={() => onChangeRegion('')}
          className={`
            group relative flex items-center gap-2 shrink-0 rounded-t-lg px-4 py-2.5
            border-b-2 transition-all duration-fast ease-oe
            ${
              activeRegion === ''
                ? 'border-oe-blue bg-oe-blue-subtle/20 text-content-primary'
                : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
            }
          `}
        >
          <Database
            size={14}
            className={activeRegion === '' ? 'text-oe-blue' : 'text-content-tertiary'}
          />
          <span className="text-sm font-medium whitespace-nowrap">
            {t('catalog.all_regions', { defaultValue: 'All' })}
          </span>
          <span
            className={`text-2xs tabular-nums ${activeRegion === '' ? 'text-oe-blue' : 'text-content-quaternary'}`}
          >
            {totalItems > 0 ? totalItems.toLocaleString() : ''}
          </span>
        </button>

        <div className="w-px shrink-0 bg-border-light my-2" />

        {/* My Catalog — always visible */}
        {(() => {
          const isActive = activeRegion === 'CUSTOM';
          const count = statsMap.get('CUSTOM') ?? 0;
          return (
            <button
              onClick={() => onChangeRegion('CUSTOM')}
              className={`
                group relative flex items-center gap-2 shrink-0 rounded-t-lg px-3.5 py-2.5
                border-b-2 transition-all duration-fast ease-oe
                ${
                  isActive
                    ? 'border-oe-blue bg-oe-blue-subtle/20 text-content-primary'
                    : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                }
              `}
            >
              <House size={14} className={isActive ? 'text-oe-blue' : 'text-content-tertiary'} />
              <span className="text-sm font-medium whitespace-nowrap">
                {t('catalog.my_catalog', { defaultValue: 'My Catalog' })}
              </span>
              <span
                className={`text-2xs tabular-nums ${isActive ? 'text-oe-blue' : 'text-content-quaternary'}`}
              >
                {count > 0 ? count.toLocaleString() : '0'}
              </span>
            </button>
          );
        })()}

        <div className="w-px shrink-0 bg-border-light my-2" />

        {/* Region tabs */}
        {regionStats.filter((rs) => rs.region !== 'CUSTOM').map((rs) => {
          const info = REGION_MAP[rs.region];
          if (!info) return null;
          const isActive = activeRegion === rs.region;
          const count = statsMap.get(rs.region) ?? 0;

          return (
            <button
              key={rs.region}
              onClick={() => onChangeRegion(rs.region)}
              className={`
                group relative flex items-center gap-2 shrink-0 rounded-t-lg px-3.5 py-2.5
                border-b-2 transition-all duration-fast ease-oe
                ${
                  isActive
                    ? 'border-oe-blue bg-oe-blue-subtle/20 text-content-primary'
                    : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                }
              `}
            >
              <MiniFlag code={info.flag} size={13} />
              <span className="text-sm font-medium whitespace-nowrap">{info.name}</span>
              <span
                className={`text-2xs tabular-nums ${isActive ? 'text-oe-blue' : 'text-content-quaternary'}`}
              >
                {count > 0 ? count.toLocaleString() : ''}
              </span>
            </button>
          );
        })}

        <div className="w-px shrink-0 bg-border-light my-2" />

        {/* Import button */}
        <button
          onClick={onImportClick}
          className="flex items-center gap-1.5 shrink-0 rounded-t-lg px-3 py-2.5 border-b-2 border-transparent text-content-tertiary hover:text-oe-blue hover:bg-oe-blue-subtle/10 transition-all duration-fast ease-oe"
          title={t('catalog.import_region', { defaultValue: 'Import region' })}
        >
          <Plus size={14} />
          <span className="text-sm font-medium whitespace-nowrap">
            {t('catalog.import', { defaultValue: 'Import' })}
          </span>
        </button>
      </div>

      <div className="h-px bg-border-light -mt-px" />
    </div>
  );
}

/* ── Price Bar Visualization ──────────────────────────────────────────── */

function PriceBar({
  min,
  avg,
  max,
  currency,
}: {
  min: number;
  avg: number;
  max: number;
  currency: string;
}) {
  if (max <= 0) return <span className="text-xs text-content-quaternary">--</span>;

  const range = max - min;
  const avgPos = range > 0 ? ((avg - min) / range) * 100 : 50;

  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <span className="text-2xs text-content-quaternary tabular-nums whitespace-nowrap">
        {fmt(min)}
      </span>
      <div className="relative flex-1 h-2 bg-surface-tertiary rounded-full overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-green-400 to-amber-400 rounded-full"
          style={{ width: '100%' }}
        />
        <div
          className="absolute top-0 h-full w-0.5 bg-content-primary rounded-full"
          style={{ left: `${Math.min(Math.max(avgPos, 2), 98)}%` }}
          title={`Avg: ${fmt(avg)} ${currency}`}
        />
      </div>
      <span className="text-2xs text-content-quaternary tabular-nums whitespace-nowrap">
        {fmt(max)}
      </span>
    </div>
  );
}

/* ── Resource Row ────────────────────────────────────────────────────── */

function ResourceRow({
  resource,
  isExpanded,
  isSelected,
  onToggle,
  onSelect,
  onCopy,
  copiedId,
  t: translate,
}: {
  resource: CatalogResource;
  isExpanded: boolean;
  isSelected: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onCopy: () => void;
  copiedId: string | null;
  t: ReturnType<typeof useTranslation>['t'];
}) {
  const typeColors: Record<string, string> = {
    material: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    equipment: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    labor: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    operator: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  };

  const regionInfo = resource.region ? REGION_MAP[resource.region] : null;

  return (
    <>
      <tr
        className={`group cursor-pointer transition-colors duration-fast ${
          isSelected
            ? 'bg-oe-blue-subtle/10'
            : 'hover:bg-surface-secondary/50'
        }`}
        onClick={onToggle}
      >
        {/* Checkbox */}
        <td className="px-3 py-3 w-10">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onSelect();
            }}
            className="flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:text-oe-blue transition-colors"
          >
            {isSelected ? (
              <CheckSquare size={16} className="text-oe-blue" />
            ) : (
              <Square size={16} />
            )}
          </button>
        </td>

        {/* Name */}
        <td className="px-4 py-3 text-sm text-content-primary font-medium">
          <div className="flex items-center gap-2">
            {regionInfo && <MiniFlag code={regionInfo.flag} size={11} />}
            <span className="truncate max-w-[280px]">{resource.name}</span>
          </div>
          {resource.source === 'boq_import' && resource.specifications?.source_project_name ? (
            <div className="text-2xs text-content-quaternary mt-0.5 truncate">
              {translate('common.from', { defaultValue: 'from' })}{' '}
              {String(resource.specifications.source_project_name)}
              {resource.specifications.saved_at ? (
                <>{' \u00b7 '}{new Date(String(resource.specifications.saved_at)).toLocaleDateString(getIntlLocale())}</>
              ) : null}
            </div>
          ) : null}
        </td>

        {/* Code */}
        <td className="px-3 py-3 max-w-[130px]">
          <span className="font-mono text-2xs text-content-tertiary truncate block" title={resource.resource_code}>
            {resource.resource_code}
          </span>
        </td>

        {/* Category */}
        <td className="px-3 py-3 max-w-[120px]">
          <span
            className={`inline-block truncate max-w-full rounded px-1.5 py-0.5 text-2xs font-medium ${
              typeColors[resource.resource_type] || 'bg-gray-100 text-gray-700'
            }`}
            title={resource.category}
          >
            {translate(`catalog.category_${resource.category.toLowerCase().replace(/[^a-z0-9]+/g, '_')}`, { defaultValue: resource.category })}
          </span>
        </td>

        {/* Unit */}
        <td className="px-4 py-3 text-center text-xs text-content-secondary">{resource.unit}</td>

        {/* Price (avg) */}
        <td className="px-3 py-3 text-right text-xs font-semibold text-content-primary tabular-nums whitespace-nowrap">
          {fmt(resource.base_price)}
        </td>

        {/* Price Range */}
        <td className="px-4 py-3">
          <PriceBar
            min={resource.min_price}
            avg={resource.base_price}
            max={resource.max_price}
            currency={resource.currency}
          />
        </td>

        {/* Usage */}
        <td className="px-4 py-3 text-center">
          <Badge
            variant={
              resource.usage_count > 20
                ? 'success'
                : resource.usage_count > 5
                  ? 'warning'
                  : 'neutral'
            }
          >
            {resource.usage_count}
          </Badge>
        </td>

        {/* Actions */}
        <td className="px-2 py-3">
          <div className="flex items-center gap-1">
            <button
              className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                onCopy();
              }}
              title={translate('catalog.copy_rate', { defaultValue: 'Copy rate' })}
            >
              {copiedId === resource.id ? (
                <Check size={14} className="text-green-500" />
              ) : (
                <Copy size={14} />
              )}
            </button>
            <button
              className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                onToggle();
              }}
            >
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
        </td>
      </tr>

      {/* Expanded details */}
      {isExpanded && (
        <tr>
          <td colSpan={9} className="p-0">
            <ResourceDetailPanel resource={resource} regionInfo={regionInfo ?? undefined} fmt={fmt} translate={translate} />
          </td>
        </tr>
      )}
    </>
  );
}

/* ── Resource Detail Panel ────────────────────────────────────────────── */

function ResourceDetailPanel({
  resource,
  regionInfo,
  fmt,
  translate: t,
}: {
  resource: CatalogResource;
  regionInfo: { name: string; flag: string; currency: string } | undefined;
  fmt: (n: number) => string;
  translate: (key: string, opts?: Record<string, string>) => string;
}) {
  const specs = resource.specifications || {};
  const priceSpread = resource.max_price > 0 ? ((resource.max_price - resource.min_price) / resource.max_price * 100) : 0;

  // Parse hierarchy from specs
  const hierarchy = [
    specs.parent_category,
    specs.parent_collection,
    specs.parent_department,
    specs.parent_section,
  ].filter(Boolean).map(String);

  return (
    <div className="bg-surface-secondary/20 border-t border-b border-border-light animate-fade-in">
      {/* Breadcrumb */}
      {hierarchy.length > 0 && (
        <div className="px-6 pt-3 pb-0">
          <div className="flex flex-wrap items-center gap-1">
            {hierarchy.map((part, i) => (
              <span key={`${part}-${i}`} className="flex items-center gap-1">
                <span className="text-2xs text-content-quaternary">{part}</span>
                {i < hierarchy.length - 1 && <span className="text-2xs text-content-quaternary/40">&rsaquo;</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="px-6 py-4">
        {/* Top row: Price cards + Identity */}
        <div className="flex gap-4 mb-4">
          {/* Price cards */}
          <div className="flex gap-2 shrink-0">
            <div className="rounded-lg bg-green-50 dark:bg-green-500/10 border border-green-200/50 dark:border-green-500/20 px-3 py-2 text-center min-w-[80px]">
              <div className="text-2xs text-green-600 dark:text-green-400 font-medium mb-0.5">Min</div>
              <div className="text-sm font-bold text-green-700 dark:text-green-300 tabular-nums">{fmt(resource.min_price)}</div>
            </div>
            <div className="rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200/50 dark:border-amber-500/20 px-3 py-2 text-center min-w-[80px]">
              <div className="text-2xs text-amber-600 dark:text-amber-400 font-medium mb-0.5">Avg</div>
              <div className="text-sm font-bold text-amber-700 dark:text-amber-300 tabular-nums">{fmt(resource.base_price)}</div>
            </div>
            <div className="rounded-lg bg-red-50 dark:bg-red-500/10 border border-red-200/50 dark:border-red-500/20 px-3 py-2 text-center min-w-[80px]">
              <div className="text-2xs text-red-600 dark:text-red-400 font-medium mb-0.5">Max</div>
              <div className="text-sm font-bold text-red-700 dark:text-red-300 tabular-nums">{fmt(resource.max_price)}</div>
            </div>
          </div>

          {/* Price spread bar */}
          <div className="flex-1 flex flex-col justify-center">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-2xs text-content-tertiary">{resource.currency}</span>
              {priceSpread > 0 && (
                <span className="text-2xs text-content-quaternary">{t('catalog.spread', { defaultValue: 'spread' })} {priceSpread.toFixed(0)}%</span>
              )}
            </div>
            <div className="h-2 w-full rounded-full bg-surface-tertiary overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-green-400 via-amber-400 to-red-400"
                style={{ width: '100%' }}
              />
            </div>
          </div>
        </div>

        {/* Info grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {/* Identity */}
          <div className="rounded-lg bg-surface-primary border border-border-light p-2.5">
            <div className="text-2xs text-content-quaternary uppercase tracking-wider mb-1">{t('catalog.resource_label', { defaultValue: 'Resource' })}</div>
            <div className="text-xs font-medium text-content-primary truncate" title={resource.name}>{resource.name}</div>
            <div className="text-2xs text-content-tertiary font-mono mt-0.5 truncate" title={resource.resource_code}>{resource.resource_code}</div>
          </div>

          {/* Type + Category */}
          <div className="rounded-lg bg-surface-primary border border-border-light p-2.5">
            <div className="text-2xs text-content-quaternary uppercase tracking-wider mb-1">{t('catalog.type_label', { defaultValue: 'Type' })}</div>
            <div className="text-xs font-medium text-content-primary capitalize">{resource.resource_type}</div>
            <div className="text-2xs text-content-tertiary mt-0.5">{resource.category}</div>
          </div>

          {/* Usage */}
          <div className="rounded-lg bg-surface-primary border border-border-light p-2.5">
            <div className="text-2xs text-content-quaternary uppercase tracking-wider mb-1">{t('catalog.usage', { defaultValue: 'Usage' })}</div>
            <div className="text-xs font-medium text-content-primary">{resource.usage_count.toLocaleString()} {t('catalog.references', { defaultValue: 'references' })}</div>
            {specs.used_in_work_items ? (
              <div className="text-2xs text-content-tertiary mt-0.5">{Number(specs.used_in_work_items).toLocaleString()} {t('catalog.work_items', { defaultValue: 'work items' })}</div>
            ) : null}
          </div>

          {/* Region */}
          <div className="rounded-lg bg-surface-primary border border-border-light p-2.5">
            <div className="text-2xs text-content-quaternary uppercase tracking-wider mb-1">{t('catalog.region_label', { defaultValue: 'Region' })}</div>
            <div className="flex items-center gap-1.5">
              {regionInfo && <MiniFlag code={regionInfo.flag} size={12} />}
              <span className="text-xs font-medium text-content-primary">{regionInfo?.name ?? resource.region}</span>
            </div>
            <div className="text-2xs text-content-tertiary mt-0.5">{resource.unit} · {resource.source}</div>
          </div>
        </div>

        {/* Source info for boq_import items */}
        {resource.source === 'boq_import' && Boolean(specs.source_project_name || specs.source_boq_name || specs.saved_at) && (
          <div className="mt-3 rounded-lg bg-oe-blue-subtle/20 border border-oe-blue/10 px-3 py-2.5">
            <div className="text-2xs text-oe-blue font-semibold uppercase tracking-wider mb-1.5">
              {t('catalog.saved_from_project', { defaultValue: 'Saved from project' })}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              {specs.source_project_name ? (
                <div className="flex items-center gap-1.5">
                  <span className="text-content-tertiary">{t('projects.project', { defaultValue: 'Project' })}:</span>
                  <span className="font-medium text-content-primary">{String(specs.source_project_name)}</span>
                </div>
              ) : null}
              {specs.source_boq_name ? (
                <div className="flex items-center gap-1.5">
                  <span className="text-content-tertiary">{t('boq.boq_abbr', { defaultValue: 'BOQ' })}:</span>
                  <span className="font-medium text-content-primary">{String(specs.source_boq_name)}</span>
                </div>
              ) : null}
              {specs.saved_at ? (
                <div className="flex items-center gap-1.5">
                  <span className="text-content-tertiary">{t('common.saved', { defaultValue: 'Saved' })}:</span>
                  <span className="text-content-secondary">
                    {new Date(String(specs.saved_at)).toLocaleDateString(undefined, {
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                </div>
              ) : null}
            </div>
          </div>
        )}

        {/* Additional specs (collapsed by default) */}
        {Object.keys(specs).length > 4 && (
          <details className="mt-3">
            <summary className="text-2xs font-medium text-content-tertiary cursor-pointer hover:text-content-secondary select-none">
              {t('catalog.all_properties', { defaultValue: 'All properties' })} ({Object.keys(specs).length})
            </summary>
            <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-2xs">
              {Object.entries(specs)
                .filter(([, v]) => v && String(v).trim() !== '')
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2 py-0.5">
                    <span className="text-content-quaternary capitalize">{k.replace(/_/g, ' ').replace('parent ', '')}</span>
                    <span className="text-content-secondary truncate max-w-[150px] text-right" title={String(v)}>
                      {!isNaN(Number(v)) ? Number(Number(v).toFixed(2)).toLocaleString() : String(v)}
                    </span>
                  </div>
                ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

/* ── Build Assembly Modal ────────────────────────────────────────────── */

function BuildAssemblyModal({
  resources,
  onClose,
  onSuccess,
}: {
  resources: CatalogResource[];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);

  const [name, setName] = useState('');
  const [assemblyUnit, setAssemblyUnit] = useState('m2');
  const [assemblyCategory, setAssemblyCategory] = useState('general');
  const [isCreating, setIsCreating] = useState(false);
  const [entries, setEntries] = useState<SelectedResourceEntry[]>(() =>
    resources.map((r) => ({ resource: r, quantity: 1 })),
  );

  const total = entries.reduce((sum, e) => sum + e.resource.base_price * e.quantity, 0);
  const currency = resources[0]?.currency ?? 'EUR';

  const handleQuantityChange = useCallback((idx: number, value: string) => {
    setEntries((prev) =>
      prev.map((e, i) => (i === idx ? { ...e, quantity: Math.max(0, parseFloat(value) || 0) } : e)),
    );
  }, []);

  const handleRemoveEntry = useCallback((idx: number) => {
    setEntries((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleCreate = useCallback(async () => {
    if (!name.trim() || entries.length === 0) return;
    setIsCreating(true);

    try {
      // Create assembly
      const code = `ASM-${Date.now().toString(36).toUpperCase()}`;
      const assemblyData: CreateAssemblyData = {
        code,
        name: name.trim(),
        unit: assemblyUnit,
        category: assemblyCategory,
        currency,
      };
      const assembly = await assembliesApi.create(assemblyData);

      // Add components
      for (const entry of entries) {
        if (entry.quantity <= 0) continue;
        const componentData: CreateComponentData = {
          description: entry.resource.name,
          unit: entry.resource.unit,
          unit_cost: entry.resource.base_price,
          quantity: entry.quantity,
          factor: 1.0,
        };
        await assembliesApi.addComponent(assembly.id, componentData);
      }

      addToast({
        type: 'success',
        title: t('catalog.assembly_created', { defaultValue: 'Assembly created' }),
        message: `"${name.trim()}" ${t('catalog.with_n_components', { defaultValue: `with ${entries.length} components` })}`,
      });
      onSuccess();
      navigate(`/assemblies/${assembly.id}`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('catalog.assembly_failed', { defaultValue: 'Failed to create assembly' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setIsCreating(false);
    }
  }, [name, assemblyUnit, assemblyCategory, currency, entries, addToast, t, onSuccess, navigate]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-2xl mx-4 overflow-hidden max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
              <Layers size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">
                {t('catalog.build_assembly', { defaultValue: 'Build Assembly' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {entries.length}{' '}
                {entries.length === 1
                  ? t('catalog.resource', { defaultValue: 'resource' })
                  : t('catalog.resources', { defaultValue: 'resources' })}{' '}
                {t('catalog.selected', { defaultValue: 'selected' })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4 overflow-y-auto flex-1">
          {/* Assembly name */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="text-xs font-medium text-content-secondary mb-1.5 block">
                {t('catalog.assembly_name', { defaultValue: 'Assembly Name' })} *
              </label>
              <input
                autoFocus
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('catalog.assembly_name_placeholder', {
                  defaultValue: 'e.g. Reinforced Concrete Wall C30/37',
                })}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1.5 block">
                {t('boq.unit', { defaultValue: 'Unit' })}
              </label>
              <select
                value={assemblyUnit}
                onChange={(e) => setAssemblyUnit(e.target.value)}
                className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              >
                {['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'].map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-content-secondary mb-1.5 block">
              {t('catalog.category', { defaultValue: 'Category' })}
            </label>
            <select
              value={assemblyCategory}
              onChange={(e) => setAssemblyCategory(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent sm:w-48"
            >
              {['general', 'concrete', 'masonry', 'steel', 'mep', 'earthwork', 'custom'].map(
                (c) => (
                  <option key={c} value={c}>
                    {c.charAt(0).toUpperCase() + c.slice(1)}
                  </option>
                ),
              )}
            </select>
          </div>

          {/* Resource table */}
          <div className="rounded-lg border border-border-light bg-surface-secondary/50 overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-surface-tertiary text-content-secondary">
                  <th className="px-3 py-2 text-left font-medium">
                    {t('catalog.resource_name', { defaultValue: 'Resource' })}
                  </th>
                  <th className="px-3 py-2 text-center font-medium w-14">
                    {t('boq.unit', { defaultValue: 'Unit' })}
                  </th>
                  <th className="px-3 py-2 text-right font-medium w-24">
                    {t('catalog.unit_rate', { defaultValue: 'Unit Rate' })}
                  </th>
                  <th className="px-3 py-2 text-center font-medium w-20">
                    {t('catalog.quantity', { defaultValue: 'Qty' })}
                  </th>
                  <th className="px-3 py-2 text-right font-medium w-24">
                    {t('catalog.subtotal', { defaultValue: 'Subtotal' })}
                  </th>
                  <th className="px-1 py-2 w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {entries.map((entry, idx) => (
                  <tr key={entry.resource.id}>
                    <td className="px-3 py-2 text-content-primary truncate max-w-[220px]">
                      {entry.resource.name}
                    </td>
                    <td className="px-3 py-2 text-center text-content-tertiary">
                      {entry.resource.unit}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium text-content-primary">
                      {fmt(entry.resource.base_price)}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={entry.quantity}
                        onChange={(e) => handleQuantityChange(idx, e.target.value)}
                        className="h-7 w-16 rounded border border-border bg-surface-primary px-1.5 text-center text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue"
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium text-content-primary">
                      {fmt(entry.resource.base_price * entry.quantity)}
                    </td>
                    <td className="px-1 py-2 text-center">
                      <button
                        onClick={() => handleRemoveEntry(idx)}
                        className="flex h-6 w-6 items-center justify-center rounded text-content-quaternary hover:text-red-500 hover:bg-red-50 transition-colors"
                      >
                        <X size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-surface-tertiary font-medium">
                  <td colSpan={4} className="px-3 py-2 text-right text-sm text-content-primary">
                    {t('catalog.total', { defaultValue: 'Total' })}:
                  </td>
                  <td className="px-3 py-2 text-right text-sm tabular-nums text-content-primary">
                    {fmt(total)} {currency}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border-light bg-surface-secondary/30 shrink-0">
          <span className="text-xs text-content-tertiary">
            {entries.length}{' '}
            {entries.length === 1
              ? t('catalog.component', { defaultValue: 'component' })
              : t('catalog.components', { defaultValue: 'components' })}
            {' | '}
            {fmt(total)} {currency}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={
                isCreating ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Layers size={14} />
                )
              }
              onClick={handleCreate}
              disabled={!name.trim() || entries.length === 0 || isCreating}
            >
              {isCreating
                ? t('catalog.creating', { defaultValue: 'Creating...' })
                : t('catalog.create_assembly', { defaultValue: 'Create Assembly' })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Main CatalogPage ────────────────────────────────────────────────── */

export function CatalogPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const navigate = useNavigate();

  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [resourceType, setResourceType] = useState('');
  const [category, setCategory] = useState('');
  const [unit, setUnit] = useState('');
  const [region, setRegion] = useState('');
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showImportGrid, setShowImportGrid] = useState(false);
  const [showCreateResource, setShowCreateResource] = useState(false);
  const [showBuildAssembly, setShowBuildAssembly] = useState(false);
  const [showPriceAdjust, setShowPriceAdjust] = useState(false);

  // Debounce search query by 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Fetch stats (for tab counts)
  const { data: stats } = useQuery({
    queryKey: ['catalog', 'stats'],
    queryFn: () => apiGet<CatalogStatsResponse>('/v1/catalog/stats/'),
    retry: false,
  });

  // Fetch loaded regions
  const { data: regionStats } = useQuery({
    queryKey: ['catalog', 'regions'],
    queryFn: () => apiGet<CatalogRegionStat[]>('/v1/catalog/regions/'),
    retry: false,
  });

  // Fetch resources
  const searchUrl = buildSearchUrl(debouncedQuery, resourceType, category, unit, region, offset);
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['catalog', debouncedQuery, resourceType, category, unit, region, offset],
    queryFn: () => apiGet<CatalogSearchResponse>(searchUrl),
    placeholderData: (prev) => prev,
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  // Count per type for tabs
  const typeCountMap = new Map(
    (stats?.by_type ?? []).map((s) => [s.resource_type, s.count]),
  );
  const totalCount = stats?.total ?? 0;

  // Categories for dropdown
  const categories = (stats?.by_category ?? []).map((c) => c.category);

  // Loaded region IDs
  const loadedRegionIds = new Set((regionStats ?? []).map((r) => r.region));
  const hasAnyRegions = loadedRegionIds.size > 0;

  // Selected items for actions
  const selectedItems = items.filter((i) => selectedIds.has(i.id));

  // Region info for subtitle
  const regionInfo = region ? REGION_MAP[region] : null;

  const handleSearch = useCallback((value: string) => {
    setQuery(value);
  }, []);

  const handleTypeChange = useCallback((value: string) => {
    setResourceType(value);
    setOffset(0);
  }, []);

  const handleCategoryChange = useCallback((value: string) => {
    setCategory(value);
    setOffset(0);
  }, []);

  const handleRegionChange = useCallback((value: string) => {
    setRegion(value);
    setOffset(0);
  }, []);

  const handleCopyRate = useCallback(async (resource: CatalogResource) => {
    try {
      await navigator.clipboard.writeText(String(resource.base_price));
      setCopiedId(resource.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // Clipboard API unavailable -- silently ignore.
    }
  }, []);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((i) => i.id)));
    }
  }, [items, selectedIds.size]);

  const handleDeleteRegion = useCallback(
    async (regionId: string) => {
      try {
        const result = await apiDelete<{ deleted: number; region: string }>(
          `/v1/catalog/region/${regionId}`,
        );
        addToast({
          type: 'success',
          title: t('catalog.region_deleted', { defaultValue: 'Region deleted' }),
          message: `${result.deleted} ${t('catalog.resources_removed', { defaultValue: 'resources removed' })}`,
        });
        queryClient.invalidateQueries({ queryKey: ['catalog'] });
        if (region === regionId) setRegion('');
      } catch (err) {
        addToast({
          type: 'error',
          title: t('catalog.delete_failed', { defaultValue: 'Delete failed' }),
          message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
        });
      }
    },
    [addToast, t, queryClient, region],
  );

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['catalog'] });
  }, [queryClient]);

  return (
    <div className="w-full animate-fade-in">
      {/* Header */}
      <div className="mb-5 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('catalog.title', { defaultValue: 'Resource Catalog' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {regionInfo
              ? `${regionInfo.name} -- ${total.toLocaleString()} ${t('catalog.resources', { defaultValue: 'resources' })}`
              : total > 0
                ? `${total.toLocaleString()} ${t('catalog.resources_found', { defaultValue: 'resources found' })}`
                : t('catalog.search_hint', {
                    defaultValue: 'Browse materials, equipment, labor, and operators',
                  })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Region selector dropdown */}
          {hasAnyRegions && (
            <div className="relative">
              <select
                value={region}
                onChange={(e) => handleRegionChange(e.target.value)}
                className="h-9 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-8 text-sm text-content-primary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              >
                <option value="">
                  {t('catalog.all_regions', { defaultValue: 'All regions' })}
                </option>
                {(regionStats ?? []).map((rs) => {
                  const info = REGION_MAP[rs.region];
                  return (
                    <option key={rs.region} value={rs.region}>
                      {info?.name ?? rs.region} ({rs.count.toLocaleString()})
                    </option>
                  );
                })}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>
          )}

          {/* Delete region button */}
          {region && (
            <Button
              variant="secondary"
              size="sm"
              icon={<Trash2 size={14} />}
              onClick={() => handleDeleteRegion(region)}
            >
              {t('catalog.delete_region', { defaultValue: 'Delete Region' })}
            </Button>
          )}

          {/* Bulk price adjustment */}
          {totalCount > 0 && (
            <Button
              variant="secondary"
              size="sm"
              icon={<TrendingUp size={14} />}
              onClick={() => setShowPriceAdjust(true)}
            >
              {t('catalog.adjust_prices', { defaultValue: 'Adjust Prices' })}
            </Button>
          )}

          {/* Add custom resource */}
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setShowCreateResource(true)}
          >
            {t('catalog.add_resource', { defaultValue: 'Add Resource' })}
          </Button>

          {/* Import region button */}
          <Button
            variant="primary"
            size="sm"
            icon={<Upload size={14} />}
            onClick={() => setShowImportGrid(!showImportGrid)}
          >
            {t('catalog.import_region', { defaultValue: 'Import Region' })}
          </Button>
        </div>
      </div>

      {/* What is catalog info hint */}
      <InfoHint
        className="mb-4"
        text={t('catalog.what_is_catalog', {
          defaultValue:
            'Resource Catalog contains atomic building blocks for estimates: individual materials, labor rates, and equipment costs. Use it to manage and update prices across all your projects -- apply inflation adjustments, regional coefficients, or group-level price changes.',
        })}
      />

      {/* Region Import Grid (expandable) */}
      {(showImportGrid || (!hasAnyRegions && totalCount === 0)) && (
        <RegionImportGrid loadedRegionIds={loadedRegionIds} onImported={invalidateAll} />
      )}

      {/* Region Tab Bar */}
      {hasAnyRegions && (
        <RegionTabBar
          regionStats={regionStats ?? []}
          activeRegion={region}
          onChangeRegion={handleRegionChange}
          onImportClick={() => setShowImportGrid(!showImportGrid)}
        />
      )}

      {/* Type Filter Pills */}
      <div className="mb-5">
        <div className="flex items-center gap-1.5 flex-wrap">
          {TYPE_TABS.map((tab) => {
            const isActive = resourceType === tab.key;
            const count = tab.key === '' ? totalCount : (typeCountMap.get(tab.key) ?? 0);
            const Icon = tab.icon;

            return (
              <button
                key={tab.key}
                onClick={() => handleTypeChange(tab.key)}
                className={`
                  flex items-center gap-1.5 shrink-0 rounded-full px-3 py-1.5
                  text-xs font-medium transition-all duration-fast ease-oe
                  ${
                    isActive
                      ? 'bg-oe-blue text-white shadow-sm'
                      : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary hover:text-content-primary'
                  }
                `}
              >
                <Icon
                  size={13}
                  className={isActive ? 'text-white/80' : 'text-content-tertiary'}
                />
                <span className="whitespace-nowrap">
                  {t(`catalog.tab_${tab.key || 'all'}`, { defaultValue: tab.label })}
                </span>
                {count > 0 && (
                  <span
                    className={`text-2xs tabular-nums ${
                      isActive ? 'text-white/70' : 'text-content-quaternary'
                    }`}
                  >
                    {count.toLocaleString()}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div className="h-px bg-border-light -mt-px" />
      </div>

      {/* Search & Filters */}
      <Card padding="none" className="mb-6">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          {/* Search input */}
          <div className="relative flex-1">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder={
                regionInfo
                  ? `${t('catalog.search_in', { defaultValue: 'Search in' })} ${regionInfo.name}...`
                  : t('catalog.search_placeholder', {
                      defaultValue: 'Search by name or code...',
                    })
              }
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-9 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            />
            {query && (
              <button
                onClick={() => {
                  setQuery('');
                  setDebouncedQuery('');
                  setOffset(0);
                }}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-content-tertiary hover:text-content-secondary transition-colors"
                aria-label={t('common.clear', { defaultValue: 'Clear' })}
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Category filter */}
          {categories.length > 0 && (
            <div className="relative">
              <select
                value={category}
                onChange={(e) => handleCategoryChange(e.target.value)}
                className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-48"
              >
                <option value="">
                  {t('catalog.all_categories', { defaultValue: 'All categories' })}
                </option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>
                    {t(`catalog.category_${cat.toLowerCase().replace(/[^a-z0-9]+/g, '_')}`, { defaultValue: cat })}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>
          )}

          {/* Unit filter */}
          <div className="relative">
            <select
              value={unit}
              onChange={(e) => {
                setUnit(e.target.value);
                setOffset(0);
              }}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-32"
            >
              <option value="">
                {t('catalog.all_units', { defaultValue: 'All units' })}
              </option>
              {UNITS.filter(Boolean).map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </div>
      </Card>

      {/* Results Table */}
      {isLoading ? (
        <Card padding="none" className="overflow-hidden">
          <div className="space-y-0 divide-y divide-border-light">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3.5">
                <Skeleton width={20} height={20} rounded="md" />
                <Skeleton className="flex-1" height={14} />
                <Skeleton width={72} height={14} />
                <Skeleton width={80} height={14} />
                <Skeleton width={40} height={14} />
                <Skeleton width={80} height={14} />
                <Skeleton width={120} height={14} />
                <Skeleton width={40} height={14} />
                <Skeleton width={56} height={28} rounded="md" />
              </div>
            ))}
          </div>
        </Card>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Boxes size={28} strokeWidth={1.5} />}
          title={
            region === 'CUSTOM'
              ? t('catalog.my_catalog_empty', { defaultValue: 'Your catalog is empty' })
              : !hasAnyRegions && !debouncedQuery
                ? t('catalog.empty_title', { defaultValue: 'Resource Catalog' })
                : t('catalog.no_results', { defaultValue: 'No resources found' })
          }
          description={
            region === 'CUSTOM'
              ? t('catalog.my_catalog_empty_desc', {
                  defaultValue:
                    'Add your own materials, equipment, and labor rates. Custom resources can be used in assemblies and applied to BOQ positions.',
                })
              : !hasAnyRegions && !debouncedQuery
                ? t('catalog.empty_desc', {
                    defaultValue:
                      'The catalog stores individual materials, equipment, and labor rates. Import a regional database to get started, or add custom resources.',
                  })
                : debouncedQuery
                  ? t('catalog.no_results_hint', {
                      defaultValue: 'Try adjusting your search or filters',
                    })
                  : hasAnyRegions
                    ? t('catalog.empty_with_regions', {
                        defaultValue:
                          'No resources match the current filters. Try changing the type or region.',
                      })
                    : t('catalog.empty_hint', {
                        defaultValue:
                          'Import a regional catalog to populate resources, or extract from cost items.',
                      })
          }
          action={
            region === 'CUSTOM' ? (
              <Button
                variant="primary"
                icon={<Plus size={16} />}
                onClick={() => setShowCreateResource(true)}
              >
                {t('catalog.add_resource', { defaultValue: 'Add Resource' })}
              </Button>
            ) : !hasAnyRegions ? (
              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  icon={<Upload size={16} />}
                  onClick={() => setShowImportGrid(true)}
                >
                  {t('catalog.import_region', { defaultValue: 'Import Region' })}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => navigate('/costs/import')}
                >
                  {t('catalog.import_database', { defaultValue: 'Import Database' })}
                </Button>
              </div>
            ) : undefined
          }
        />
      ) : (
        <>
          <Card padding="none" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-tertiary text-left">
                    <th className="px-3 py-3 w-10">
                      <button
                        onClick={toggleSelectAll}
                        className="flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:text-oe-blue transition-colors"
                      >
                        {selectedIds.size > 0 && selectedIds.size === items.length ? (
                          <CheckSquare size={16} className="text-oe-blue" />
                        ) : (
                          <Square size={16} />
                        )}
                      </button>
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary">
                      {t('catalog.name', { defaultValue: 'Name' })}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-36">
                      {t('catalog.code', { defaultValue: 'Code' })}
                    </th>
                    <th className="px-3 py-3 font-medium text-content-secondary w-28">
                      {t('catalog.category', { defaultValue: 'Category' })}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-16 text-center">
                      {t('boq.unit', { defaultValue: 'Unit' })}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-32 text-right">
                      {t('catalog.price_avg', { defaultValue: 'Price (avg)' })}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-48">
                      {t('catalog.price_range', { defaultValue: 'Price Range' })}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-16 text-center">
                      {t('catalog.usage', { defaultValue: 'Usage' })}
                    </th>
                    <th className="px-2 py-3 w-16" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {items.map((resource) => {
                    const isExpanded = expandedId === resource.id;
                    return (
                      <ResourceRow
                        key={resource.id}
                        resource={resource}
                        isExpanded={isExpanded}
                        isSelected={selectedIds.has(resource.id)}
                        onToggle={() => setExpandedId(isExpanded ? null : resource.id)}
                        onSelect={() => toggleSelect(resource.id)}
                        onCopy={() => handleCopyRate(resource)}
                        copiedId={copiedId}
                        t={t}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Pagination */}
          {(() => {
            const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
            const totalPages = Math.ceil(total / PAGE_SIZE);
            const goToPage = (p: number) => setOffset((p - 1) * PAGE_SIZE);
            const start = Math.max(1, currentPage - 2);
            const end = Math.min(totalPages, start + 4);
            const pages = Array.from({ length: end - start + 1 }, (_, i) => start + i);

            return (
              <div className="mt-6 flex flex-col items-center gap-3">
                <p className="text-xs text-content-tertiary">
                  {t('catalog.showing_range', {
                    defaultValue: '{{from}}-{{to}} of {{total}}',
                    from: offset + 1,
                    to: Math.min(offset + PAGE_SIZE, total),
                    total: total.toLocaleString(),
                  })}
                </p>
                {totalPages > 1 && (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => goToPage(currentPage - 1)}
                      disabled={currentPage === 1 || isFetching}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronLeft size={16} />
                    </button>
                    {start > 1 && (
                      <>
                        <button
                          onClick={() => goToPage(1)}
                          className="flex h-8 min-w-[32px] items-center justify-center rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors"
                        >
                          1
                        </button>
                        {start > 2 && (
                          <span className="text-content-quaternary text-xs px-1">...</span>
                        )}
                      </>
                    )}
                    {pages.map((p) => (
                      <button
                        key={p}
                        onClick={() => goToPage(p)}
                        disabled={isFetching}
                        className={`flex h-8 min-w-[32px] items-center justify-center rounded-lg text-xs font-medium transition-colors ${
                          p === currentPage
                            ? 'bg-oe-blue text-white'
                            : 'text-content-secondary hover:bg-surface-secondary'
                        }`}
                      >
                        {p}
                      </button>
                    ))}
                    {end < totalPages && (
                      <>
                        {end < totalPages - 1 && (
                          <span className="text-content-quaternary text-xs px-1">...</span>
                        )}
                        <button
                          onClick={() => goToPage(totalPages)}
                          className="flex h-8 min-w-[32px] items-center justify-center rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors"
                        >
                          {totalPages}
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => goToPage(currentPage + 1)}
                      disabled={currentPage === totalPages || isFetching}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                )}
              </div>
            );
          })()}
        </>
      )}

      {/* Floating Selection Bar */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 animate-fade-in">
          <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface-elevated px-5 py-3 shadow-xl">
            <span className="text-sm font-semibold text-content-primary tabular-nums">
              {selectedIds.size}{' '}
              {t('catalog.selected', { defaultValue: 'selected' })}
            </span>
            <div className="w-px h-6 bg-border-light" />
            <Button
              variant="primary"
              size="sm"
              icon={<Layers size={14} />}
              onClick={() => setShowBuildAssembly(true)}
            >
              {t('catalog.build_assembly', { defaultValue: 'Build Assembly' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Copy size={14} />}
              onClick={() => {
                const text = selectedItems
                  .map(
                    (r) =>
                      `${r.resource_code}\t${r.name}\t${r.unit}\t${r.base_price}\t${r.currency}`,
                  )
                  .join('\n');
                navigator.clipboard.writeText(text).catch(() => {});
                addToast({
                  type: 'success',
                  title: t('catalog.copied', { defaultValue: 'Copied' }),
                  message: `${selectedIds.size} ${t('catalog.items_copied', { defaultValue: 'resources copied to clipboard' })}`,
                });
              }}
            >
              {t('catalog.copy', { defaultValue: 'Copy' })}
            </Button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Build Assembly Modal */}
      {showBuildAssembly && selectedItems.length > 0 && (
        <BuildAssemblyModal
          resources={selectedItems}
          onClose={() => setShowBuildAssembly(false)}
          onSuccess={() => {
            setShowBuildAssembly(false);
            setSelectedIds(new Set());
          }}
        />
      )}

      {showCreateResource && (
        <CreateResourceModal
          onClose={() => setShowCreateResource(false)}
          onCreated={() => {
            setShowCreateResource(false);
            invalidateAll();
          }}
        />
      )}

      {showPriceAdjust && (
        <PriceAdjustModal
          stats={stats}
          regionStats={regionStats ?? []}
          currentFilters={{ resourceType, category, region }}
          onClose={() => setShowPriceAdjust(false)}
          onSuccess={() => {
            setShowPriceAdjust(false);
            invalidateAll();
          }}
        />
      )}
    </div>
  );
}

/* ── Price Adjust Modal ──────────────────────────────────────────────── */

// Published construction cost indices (BKI, BCIS, ENR, Eurostat) — stable data, kept outside component
const PRICE_INDICES: Record<string, { label: string; rates: Record<string, number> }> = {
  DE: { label: 'Germany (BKI)', rates: { '2020': 3.2, '2021': 5.1, '2022': 14.6, '2023': 7.8, '2024': 4.2, '2025': 3.5, '2026': 3.0 } },
  AT: { label: 'Austria', rates: { '2020': 2.8, '2021': 4.9, '2022': 12.3, '2023': 6.5, '2024': 3.8, '2025': 3.2, '2026': 2.8 } },
  CH: { label: 'Switzerland', rates: { '2020': 1.5, '2021': 2.8, '2022': 6.2, '2023': 3.4, '2024': 2.5, '2025': 2.0, '2026': 1.8 } },
  UK: { label: 'UK (BCIS)', rates: { '2020': 2.0, '2021': 8.5, '2022': 10.2, '2023': 4.8, '2024': 3.5, '2025': 3.0, '2026': 2.8 } },
  US: { label: 'USA (ENR)', rates: { '2020': 1.2, '2021': 6.3, '2022': 11.5, '2023': 3.2, '2024': 2.8, '2025': 2.5, '2026': 2.3 } },
  FR: { label: 'France', rates: { '2020': 2.3, '2021': 5.5, '2022': 9.8, '2023': 5.6, '2024': 3.6, '2025': 2.8, '2026': 2.5 } },
  EU: { label: 'EU Average', rates: { '2020': 2.5, '2021': 5.8, '2022': 11.0, '2023': 6.0, '2024': 3.5, '2025': 3.0, '2026': 2.5 } },
  AE: { label: 'UAE / Gulf', rates: { '2020': 1.8, '2021': 3.5, '2022': 7.2, '2023': 4.0, '2024': 3.0, '2025': 2.5, '2026': 2.2 } },
  RU: { label: 'Russia', rates: { '2020': 4.5, '2021': 8.2, '2022': 18.5, '2023': 9.0, '2024': 6.0, '2025': 5.0, '2026': 4.5 } },
  IN: { label: 'India', rates: { '2020': 3.0, '2021': 5.0, '2022': 8.5, '2023': 5.5, '2024': 4.5, '2025': 4.0, '2026': 3.5 } },
};

function PriceAdjustModal({
  stats,
  regionStats,
  currentFilters,
  onClose,
  onSuccess,
}: {
  stats: CatalogStatsResponse | undefined;
  regionStats: CatalogRegionStat[];
  currentFilters: { resourceType: string; category: string; region: string };
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [factor, setFactor] = useState(1.05);
  const [filterType, setFilterType] = useState(currentFilters.resourceType);
  const [filterCategory, setFilterCategory] = useState(currentFilters.category);
  const [filterRegion, setFilterRegion] = useState(currentFilters.region);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const [useIndex, setUseIndex] = useState(false);
  const [indexRegion, setIndexRegion] = useState('DE');
  const [baseYear, setBaseYear] = useState(2024);
  const [targetYear, setTargetYear] = useState(2026);

  // Auto-compute factor from published index
  useEffect(() => {
    if (!useIndex || baseYear >= targetYear) return;
    const indexData = PRICE_INDICES[indexRegion];
    if (!indexData) return;
    let f = 1;
    for (let y = baseYear; y < targetYear; y++) {
      const rate = indexData.rates[String(y)] ?? indexData.rates[String(Math.min(y, 2026))] ?? 3.0;
      f *= 1 + rate / 100;
    }
    setFactor(Math.round(f * 10000) / 10000);
    setConfirmed(false);
  }, [useIndex, indexRegion, baseYear, targetYear]);

  const percentage = ((factor - 1) * 100).toFixed(1);
  const isIncrease = factor > 1;
  const isDecrease = factor < 1;
  const isLargeChange = Math.abs(factor - 1) > 0.2;

  // Estimate affected count
  const totalResources = stats?.total ?? 0;
  const categories = (stats?.by_category ?? []).map((c) => c.category);

  // Rough estimate of affected resources based on filters
  let estimatedCount = totalResources;
  if (filterType) {
    const typeStat = (stats?.by_type ?? []).find((s) => s.resource_type === filterType);
    estimatedCount = typeStat?.count ?? 0;
  }

  const handleApply = useCallback(async () => {
    setIsSubmitting(true);
    try {
      const params = new URLSearchParams();
      params.set('factor', String(factor));
      if (filterType) params.set('resource_type', filterType);
      if (filterCategory) params.set('category', filterCategory);
      if (filterRegion) params.set('region', filterRegion);

      const result = await apiPatch<{ adjusted: number; factor: number }>(
        `/v1/catalog/adjust-prices?${params.toString()}`,
      );

      addToast({
        type: 'success',
        title: t('catalog.prices_adjusted', { defaultValue: 'Prices adjusted' }),
        message: t('catalog.prices_adjusted_desc', {
          defaultValue: '{{count}} resources updated by {{pct}}%',
          count: result.adjusted,
          pct: percentage,
        }),
      });
      onSuccess();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('catalog.adjust_failed', { defaultValue: 'Adjustment failed' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setIsSubmitting(false);
    }
  }, [factor, filterType, filterCategory, filterRegion, percentage, addToast, t, onSuccess]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-lg mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400">
              <TrendingUp size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">
                {t('catalog.adjust_prices', { defaultValue: 'Adjust Prices' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('catalog.adjust_prices_desc', {
                  defaultValue: 'Apply a multiplication factor to resource prices',
                })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          {/* Mode toggle: Manual vs Published Index */}
          <div className="flex rounded-lg border border-border overflow-hidden">
            <button
              onClick={() => setUseIndex(false)}
              className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${!useIndex ? 'bg-oe-blue text-white' : 'bg-surface-primary text-content-secondary hover:bg-surface-secondary'}`}
            >
              {t('catalog.manual_factor', { defaultValue: 'Manual Factor' })}
            </button>
            <button
              onClick={() => setUseIndex(true)}
              className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${useIndex ? 'bg-oe-blue text-white' : 'bg-surface-primary text-content-secondary hover:bg-surface-secondary'}`}
            >
              {t('catalog.from_inflation_index', { defaultValue: 'From Inflation Index' })}
            </button>
          </div>

          {/* Published Index selector */}
          {useIndex && (
            <div className="rounded-lg border border-amber-200 dark:border-amber-800/40 bg-amber-50/50 dark:bg-amber-900/10 p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-medium text-amber-700 dark:text-amber-300">
                <TrendingUp size={14} />
                {t('catalog.inflation_index', { defaultValue: 'Published Construction Cost Indices' })}
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-2xs text-content-tertiary mb-1 block">{t('catalog.index_country', { defaultValue: 'Country / Source' })}</label>
                  <select value={indexRegion} onChange={(e) => setIndexRegion(e.target.value)} className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30">
                    {Object.entries(PRICE_INDICES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-2xs text-content-tertiary mb-1 block">{t('catalog.from_year', { defaultValue: 'From year' })}</label>
                  <select value={baseYear} onChange={(e) => setBaseYear(Number(e.target.value))} className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30">
                    {[2020,2021,2022,2023,2024,2025,2026].map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-2xs text-content-tertiary mb-1 block">{t('catalog.to_year', { defaultValue: 'To year' })}</label>
                  <select value={targetYear} onChange={(e) => setTargetYear(Number(e.target.value))} className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30">
                    {[2020,2021,2022,2023,2024,2025,2026,2027,2028,2029,2030].map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
              </div>
              {baseYear < targetYear && (
                <div className="flex flex-wrap gap-1.5">
                  {(() => {
                    const idx = PRICE_INDICES[indexRegion];
                    const items = [];
                    for (let y = baseYear; y < targetYear; y++) {
                      const rate = idx?.rates[String(y)] ?? idx?.rates[String(Math.min(y, 2026))] ?? 3.0;
                      items.push(<span key={y} className="inline-flex items-center gap-1 rounded bg-surface-secondary px-2 py-0.5 text-2xs"><span className="text-content-tertiary">{y}</span><span className="font-medium text-amber-600">+{rate.toFixed(1)}%</span></span>);
                    }
                    return items;
                  })()}
                  <span className="inline-flex items-center gap-1 rounded bg-amber-100 dark:bg-amber-900/20 px-2 py-0.5 text-2xs font-bold text-amber-700 dark:text-amber-300">
                    = ×{factor.toFixed(4)} (+{percentage}%)
                  </span>
                </div>
              )}
              <p className="text-2xs text-content-quaternary">
                {t('catalog.index_sources', { defaultValue: 'Sources: BKI (Germany), BCIS (UK), ENR (USA), Eurostat (EU). Representative averages.' })}
              </p>
            </div>
          )}

          {/* Factor input (manual or auto-filled from index) */}
          <div>
            <label className="text-xs font-medium text-content-secondary mb-2 block">
              {useIndex
                ? t('catalog.computed_factor', { defaultValue: 'Computed Factor (from index above)' })
                : t('catalog.price_factor', { defaultValue: 'Price Factor' })}
            </label>
            <div className="flex items-center gap-4">
              <input
                type="range"
                min="0.50"
                max="2.00"
                step="0.01"
                value={factor}
                onChange={(e) => {
                  setFactor(parseFloat(e.target.value));
                  setConfirmed(false);
                }}
                className="flex-1 h-2 accent-oe-blue"
              />
              <input
                type="number"
                min="0.50"
                max="2.00"
                step="0.01"
                value={factor}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  if (!isNaN(val) && val >= 0.5 && val <= 2.0) {
                    setFactor(val);
                    setConfirmed(false);
                  }
                }}
                className="h-9 w-20 rounded-lg border border-border bg-surface-primary px-2 text-center text-sm font-mono tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue"
              />
            </div>
            <div className="mt-2 flex items-center gap-2">
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${
                  isIncrease
                    ? 'bg-red-100 text-red-700 dark:bg-red-900/20 dark:text-red-400'
                    : isDecrease
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/20 dark:text-green-400'
                      : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
                }`}
              >
                {isIncrease ? '+' : ''}{percentage}%
              </span>
              <span className="text-xs text-content-tertiary">
                {factor === 1
                  ? t('catalog.no_change', { defaultValue: 'No change' })
                  : isIncrease
                    ? t('catalog.price_increase', { defaultValue: 'Price increase' })
                    : t('catalog.price_decrease', { defaultValue: 'Price decrease' })}
              </span>
            </div>
          </div>

          {/* Filter selectors */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">
                {t('catalog.type_label', { defaultValue: 'Type' })}
              </label>
              <select
                value={filterType}
                onChange={(e) => {
                  setFilterType(e.target.value);
                  setConfirmed(false);
                }}
                className="h-9 w-full appearance-none rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
              >
                <option value="">
                  {t('catalog.all_types', { defaultValue: 'All types' })}
                </option>
                <option value="material">
                  {t('catalog.type_material', { defaultValue: 'Material' })}
                </option>
                <option value="equipment">
                  {t('catalog.type_equipment', { defaultValue: 'Equipment' })}
                </option>
                <option value="labor">
                  {t('catalog.type_labor', { defaultValue: 'Labor' })}
                </option>
                <option value="operator">
                  {t('catalog.type_operator', { defaultValue: 'Operator' })}
                </option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">
                {t('catalog.category', { defaultValue: 'Category' })}
              </label>
              <select
                value={filterCategory}
                onChange={(e) => {
                  setFilterCategory(e.target.value);
                  setConfirmed(false);
                }}
                className="h-9 w-full appearance-none rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
              >
                <option value="">
                  {t('catalog.all_categories', { defaultValue: 'All categories' })}
                </option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>
                    {t(`catalog.category_${cat.toLowerCase().replace(/[^a-z0-9]+/g, '_')}`, { defaultValue: cat })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">
                {t('catalog.region_label', { defaultValue: 'Region' })}
              </label>
              <select
                value={filterRegion}
                onChange={(e) => {
                  setFilterRegion(e.target.value);
                  setConfirmed(false);
                }}
                className="h-9 w-full appearance-none rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
              >
                <option value="">
                  {t('catalog.all_regions', { defaultValue: 'All regions' })}
                </option>
                {regionStats.map((rs) => {
                  const info = REGION_MAP[rs.region];
                  return (
                    <option key={rs.region} value={rs.region}>
                      {info?.name ?? rs.region}
                    </option>
                  );
                })}
              </select>
            </div>
          </div>

          {/* Preview */}
          <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3">
            <p className="text-sm text-content-secondary">
              {t('catalog.adjust_preview', {
                defaultValue: 'This will affect approximately {{num}} resources',
                num: estimatedCount.toLocaleString(),
              })}
            </p>
            {factor !== 1 && (
              <p className="text-xs text-content-tertiary mt-1">
                {t('catalog.adjust_example', {
                  defaultValue: 'Example: {{oldPrice}} -> {{newPrice}}',
                  oldPrice: '100.00',
                  newPrice: (100 * factor).toFixed(2),
                })}
              </p>
            )}
          </div>

          {/* Warning for large changes */}
          {isLargeChange && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/10 px-4 py-3">
              <AlertTriangle size={16} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-medium text-amber-700 dark:text-amber-300">
                  {t('catalog.large_change_warning', {
                    defaultValue: 'Large price change detected (>20%)',
                  })}
                </p>
                <p className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                  {t('catalog.large_change_hint', {
                    defaultValue:
                      'Please confirm this is intentional. This operation cannot be undone.',
                  })}
                </p>
              </div>
            </div>
          )}

          {/* Confirmation checkbox for large changes */}
          {isLargeChange && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                className="h-4 w-4 rounded border-border accent-oe-blue"
              />
              <span className="text-xs text-content-secondary">
                {t('catalog.confirm_large_change', {
                  defaultValue: 'I confirm this price adjustment of {{pct}}%',
                  pct: percentage,
                })}
              </span>
            </label>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border-light bg-surface-secondary/30">
          <span className="text-xs text-content-tertiary">
            {t('catalog.factor_label', { defaultValue: 'Factor' })}: {factor.toFixed(2)}{' '}
            ({isIncrease ? '+' : ''}{percentage}%)
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={
                isSubmitting ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <TrendingUp size={14} />
                )
              }
              onClick={handleApply}
              disabled={factor === 1 || isSubmitting || (isLargeChange && !confirmed)}
            >
              {isSubmitting
                ? t('catalog.adjusting', { defaultValue: 'Adjusting...' })
                : t('catalog.apply_adjustment', { defaultValue: 'Apply' })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Create Resource Modal ───────────────────────────────────────────── */

function CreateResourceModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    name: '',
    resource_type: 'material',
    category: '',
    unit: 'm2',
    base_price: '',
    currency: 'EUR',
  });

  const TYPES = ['material', 'equipment', 'labor', 'operator'];
  const UNITS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'hrs', 'Machine hours', 'set', 'l', 'kWh'];
  const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'CAD', 'AUD', 'AED', 'RUB', 'CNY', 'INR', 'BRL'];

  const handleSubmit = useCallback(async () => {
    if (!form.name.trim()) return;
    setSubmitting(true);
    try {
      await apiPost('/v1/catalog/', {
        resource_code: `CUSTOM-${Date.now().toString(36).toUpperCase()}`,
        name: form.name.trim(),
        resource_type: form.resource_type,
        category: form.category.trim() || 'Custom',
        unit: form.unit,
        base_price: parseFloat(form.base_price) || 0,
        min_price: parseFloat(form.base_price) || 0,
        max_price: parseFloat(form.base_price) || 0,
        currency: form.currency,
        usage_count: 0,
        source: 'manual',
        region: 'CUSTOM',
      });
      addToast({ type: 'success', title: t('catalog.resource_created', { defaultValue: 'Resource created' }) });
      onCreated();
    } catch (err) {
      addToast({ type: 'error', title: t('common.error'), message: err instanceof Error ? err.message : 'Failed' });
    } finally {
      setSubmitting(false);
    }
  }, [form, addToast, t, onCreated]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-md mx-4 animate-fade-in" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-base font-semibold text-content-primary">
              {t('catalog.create_resource', { defaultValue: 'Add Custom Resource' })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {t('catalog.create_resource_desc', { defaultValue: 'Create a new resource for your catalog' })}
            </p>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary">
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3">
          <div>
            <label className="text-xs font-medium text-content-secondary mb-1 block">
              {t('catalog.name', { defaultValue: 'Name' })} *
            </label>
            <input
              autoFocus type="text" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder={t('catalog.resource_name_placeholder', { defaultValue: 'e.g. Reinforced concrete C30/37' })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">{t('catalog.type_label', { defaultValue: 'Type' })}</label>
              <select value={form.resource_type} onChange={(e) => setForm({ ...form, resource_type: e.target.value })}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue">
                {TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(`catalog.type_${type}`, { defaultValue: type.charAt(0).toUpperCase() + type.slice(1) })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">{t('catalog.category', { defaultValue: 'Category' })}</label>
              <input type="text" value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                placeholder={t('catalog.category_placeholder', { defaultValue: 'e.g. Concrete & Cement' })}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">{t('boq.unit', { defaultValue: 'Unit' })}</label>
              <select value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue">
                {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">{t('catalog.price', { defaultValue: 'Price' })}</label>
              <input type="number" step="0.01" value={form.base_price}
                onChange={(e) => setForm({ ...form, base_price: e.target.value })}
                placeholder="0.00"
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-right focus:outline-none focus:ring-2 focus:ring-oe-blue"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">{t('catalog.currency', { defaultValue: 'Currency' })}</label>
              <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue">
                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-3 border-t border-border-light bg-surface-secondary/30">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" size="sm" disabled={!form.name.trim() || submitting}
            icon={submitting ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            onClick={handleSubmit}>
            {submitting
              ? t('catalog.creating', { defaultValue: 'Creating...' })
              : t('catalog.create_resource_btn', { defaultValue: 'Create Resource' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
