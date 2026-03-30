import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronRight,
  Search,
  Package,
  HardHat,
  Wrench,
  Users,
  Layers,
  BookmarkPlus,
  Check,
} from 'lucide-react';
import { boqApi, type ResourceSummaryItem, type ResourceSummaryResponse } from './api';
import { apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

/* ── Constants ──────────────────────────────────────────────────────── */

const RESOURCE_TYPE_FILTERS = ['all', 'material', 'labor', 'equipment', 'subcontractor', 'other'] as const;
type ResourceTypeFilter = (typeof RESOURCE_TYPE_FILTERS)[number];

const TYPE_BADGE_STYLES: Record<string, string> = {
  material: 'bg-blue-500/10 text-blue-600',
  labor: 'bg-amber-500/10 text-amber-600',
  equipment: 'bg-violet-500/10 text-violet-600',
  subcontractor: 'bg-rose-500/10 text-rose-600',
  other: 'bg-gray-500/10 text-gray-600',
};

const TYPE_ICONS: Record<string, React.ReactNode> = {
  material: <Package size={13} />,
  labor: <HardHat size={13} />,
  equipment: <Wrench size={13} />,
  subcontractor: <Users size={13} />,
  other: <Layers size={13} />,
};

/* ── Helpers ─────────────────────────────────────────────────────────── */

function createRSFormatter(locale: string) {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/* ── Component ───────────────────────────────────────────────────────── */

export function ResourceSummary({ boqId, locale = 'de-DE' }: { boqId: string; locale?: string }) {
  const { t } = useTranslation();
  const fmt = useMemo(() => createRSFormatter(locale), [locale]);
  const [collapsed, setCollapsed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [typeFilter, setTypeFilter] = useState<ResourceTypeFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [savedResources, setSavedResources] = useState<Set<string>>(new Set());
  const [savingResource, setSavingResource] = useState<string | null>(null);
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const handleSaveToCatalog = useCallback(
    async (resource: ResourceSummaryItem) => {
      const key = `${resource.type}:${resource.name}`;
      setSavingResource(key);
      try {
        const code = `MY-${resource.type.toUpperCase().slice(0, 3)}-${Date.now().toString(36).toUpperCase()}`;

        // Read project & BOQ info from React Query cache
        const boqData = queryClient.getQueryData<{ name?: string; project_id?: string }>(['boq', boqId]);
        const projectData = boqData?.project_id
          ? queryClient.getQueryData<{ name?: string }>(['project', boqData.project_id])
          : undefined;

        await apiPost('/v1/catalog/', {
          resource_code: code,
          name: resource.name,
          resource_type: resource.type,
          category: resource.type.charAt(0).toUpperCase() + resource.type.slice(1),
          unit: resource.unit,
          base_price: resource.avg_unit_rate,
          min_price: resource.avg_unit_rate,
          max_price: resource.avg_unit_rate,
          currency: 'EUR',
          source: 'boq_import',
          region: 'CUSTOM',
          specifications: {
            total_quantity: resource.total_quantity,
            total_cost: resource.total_cost,
            positions_used: resource.positions_used,
            source_project_name: projectData?.name || '',
            source_project_id: boqData?.project_id || '',
            source_boq_name: boqData?.name || '',
            source_boq_id: boqId || '',
            saved_at: new Date().toISOString(),
          },
          metadata: {},
        });
        setSavedResources((prev) => new Set(prev).add(key));
        addToast({
          type: 'success',
          title: t('boq.rs_saved_to_catalog', { defaultValue: 'Saved to catalog' }),
          message: resource.name,
        });
      } catch (err: unknown) {
        const detail = err instanceof Error ? err.message : t('boq.rs_save_failed', { defaultValue: 'Failed to save' });
        addToast({
          type: 'error',
          title: t('boq.rs_save_failed', { defaultValue: 'Save failed' }),
          message: detail,
        });
      } finally {
        setSavingResource(null);
      }
    },
    [addToast, t, boqId, queryClient],
  );

  void savingResource; // used implicitly via savedResources

  const { data, isLoading, isError } = useQuery({
    queryKey: ['boq-resource-summary', boqId],
    queryFn: () => boqApi.getResourceSummary(boqId),
    enabled: !!boqId,
  });

  const summary: ResourceSummaryResponse = data ?? {
    total_resources: 0,
    by_type: {},
    resources: [],
  };

  /* ── Filtered resources ─────────────────────────────────────────────── */

  const filteredResources = useMemo(() => {
    let items = summary.resources;

    if (typeFilter !== 'all') {
      items = items.filter((r) => r.type === typeFilter);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      items = items.filter(
        (r) => r.name.toLowerCase().includes(q) || r.type.toLowerCase().includes(q),
      );
    }

    return items;
  }, [summary.resources, typeFilter, searchQuery]);

  if (summary.total_resources === 0 && !isLoading && !isError) {
    return null;
  }

  /* ── Type filter labels ─────────────────────────────────────────────── */

  const typeFilterLabel = (filter: ResourceTypeFilter): string => {
    switch (filter) {
      case 'all':
        return t('boq.rs_all', { defaultValue: 'All' });
      case 'material':
        return t('boq.rs_material', { defaultValue: 'Material' });
      case 'labor':
        return t('boq.rs_labor', { defaultValue: 'Labor' });
      case 'equipment':
        return t('boq.rs_equipment', { defaultValue: 'Equipment' });
      case 'subcontractor':
        return t('boq.rs_subcontractor', { defaultValue: 'Subcontractor' });
      case 'other':
        return t('boq.rs_other', { defaultValue: 'Other' });
      default:
        return filter;
    }
  };

  const typeCount = (filter: ResourceTypeFilter): number => {
    if (filter === 'all') return summary.total_resources;
    return summary.by_type[filter]?.count ?? 0;
  };

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <div className="rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden animate-fade-in">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <button
        onClick={() => setCollapsed((prev) => !prev)}
        aria-expanded={!collapsed}
        aria-label={t('boq.resource_summary', { defaultValue: 'Resource Summary' })}
        className="flex w-full items-center justify-between px-4 py-3 hover:bg-surface-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Layers size={15} className="text-oe-blue" />
          <span className="text-xs font-semibold text-content-primary">
            {t('boq.resource_summary', { defaultValue: 'Resource Summary' })}
          </span>
          <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-oe-blue/10 px-1.5 text-2xs font-medium text-oe-blue tabular-nums">
            {summary.total_resources}
          </span>

          {/* Inline type badges */}
          {!collapsed && summary.total_resources > 0 && (
            <div className="hidden sm:flex items-center gap-1.5 ml-1">
              {Object.entries(summary.by_type).map(([type, info]) => (
                <span
                  key={type}
                  className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${TYPE_BADGE_STYLES[type] || TYPE_BADGE_STYLES.other}`}
                >
                  {info.count} {typeFilterLabel(type as ResourceTypeFilter).toLowerCase()}
                </span>
              ))}
            </div>
          )}
        </div>
        {collapsed ? (
          <ChevronRight size={14} className="text-content-tertiary" />
        ) : (
          <ChevronDown size={14} className="text-content-tertiary" />
        )}
      </button>

      {!collapsed && (
        <div className="border-t border-border-light">
          {/* ── Summary stats row ───────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-3 px-4 py-2.5 bg-surface-secondary/30">
            {Object.entries(summary.by_type).map(([type, info]) => (
              <div
                key={type}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 ${TYPE_BADGE_STYLES[type] || TYPE_BADGE_STYLES.other}`}
              >
                {TYPE_ICONS[type] || TYPE_ICONS.other}
                <span className="text-xs font-semibold tabular-nums">{info.count}</span>
                <span className="text-xs">
                  {typeFilterLabel(type as ResourceTypeFilter)}
                </span>
                <span className="text-xs font-medium tabular-nums ml-1">
                  {fmt.format(info.total_cost)}
                </span>
              </div>
            ))}
          </div>

          {/* ── Filter bar ──────────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-t border-border-light/50">
            {/* Type filter tabs */}
            <div className="flex items-center gap-1">
              {RESOURCE_TYPE_FILTERS
                .filter((f) => f === 'all' || typeCount(f) > 0)
                .map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setTypeFilter(filter)}
                    className={`px-2.5 py-1 rounded-md text-2xs font-medium transition-colors ${
                      typeFilter === filter
                        ? 'bg-oe-blue text-white'
                        : 'text-content-secondary hover:bg-surface-secondary'
                    }`}
                  >
                    {typeFilterLabel(filter)}
                    {typeCount(filter) > 0 && (
                      <span className="ml-1 tabular-nums">({typeCount(filter)})</span>
                    )}
                  </button>
                ))}
            </div>

            {/* Search */}
            <div className="ml-auto relative">
              <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-content-quaternary" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('boq.rs_search', { defaultValue: 'Search resources...' })}
                aria-label={t('boq.rs_search', { defaultValue: 'Search resources...' })}
                className="w-44 pl-7 pr-2 py-1 text-2xs rounded-md border border-border-light bg-surface-primary text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue/40"
              />
            </div>
          </div>

          {/* ── Resource table ──────────────────────────────────────────── */}
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <span className="text-xs text-content-tertiary">
                {t('common.loading', { defaultValue: 'Loading...' })}
              </span>
            </div>
          ) : isError ? (
            <div className="flex items-center justify-center py-8">
              <span className="text-xs text-content-secondary">
                {t('boq.rs_error', { defaultValue: 'Failed to load resource summary.' })}
              </span>
            </div>
          ) : filteredResources.length === 0 ? (
            <div className="flex items-center justify-center py-6">
              <span className="text-xs text-content-tertiary">
                {searchQuery
                  ? t('boq.rs_no_results', { defaultValue: 'No resources match your search' })
                  : t('boq.rs_no_resources', { defaultValue: 'No resources in this category' })}
              </span>
            </div>
          ) : (
            <div className="relative overflow-x-auto">
              {(() => {
                const PREVIEW_COUNT = 4;
                const canExpand = filteredResources.length > PREVIEW_COUNT;
                const visibleResources = expanded ? filteredResources : filteredResources.slice(0, PREVIEW_COUNT);
                const hiddenCount = filteredResources.length - PREVIEW_COUNT;

                return (
                  <>
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="border-t border-border-light/50 text-content-quaternary bg-surface-secondary/20">
                          <th className="px-4 py-2 text-left font-medium">
                            {t('boq.rs_col_name', { defaultValue: 'Name' })}
                          </th>
                          <th className="px-3 py-2 text-left font-medium w-24">
                            {t('boq.rs_col_type', { defaultValue: 'Type' })}
                          </th>
                          <th className="px-3 py-2 text-center font-medium w-16">
                            {t('boq.rs_col_unit', { defaultValue: 'Unit' })}
                          </th>
                          <th className="px-3 py-2 text-right font-medium w-24">
                            {t('boq.rs_col_total_qty', { defaultValue: 'Total Qty' })}
                          </th>
                          <th className="px-3 py-2 text-right font-medium w-24">
                            {t('boq.rs_col_avg_rate', { defaultValue: 'Avg Rate' })}
                          </th>
                          <th className="px-3 py-2 text-right font-medium w-28">
                            {t('boq.rs_col_total_cost', { defaultValue: 'Total Cost' })}
                          </th>
                          <th className="px-3 py-2 text-center font-medium w-16">
                            {t('boq.rs_col_positions', { defaultValue: 'Pos.' })}
                          </th>
                          <th className="px-2 py-2 text-center font-medium w-10">
                            <BookmarkPlus size={12} className="inline" />
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleResources.map((res, idx) => (
                          <ResourceRow
                            key={`${res.name}-${res.type}-${idx}`}
                            resource={res}
                            fmt={fmt}
                            onSaveToCatalog={handleSaveToCatalog}
                            isSaved={savedResources.has(`${res.type}:${res.name}`)}
                          />
                        ))}
                      </tbody>
                      {expanded && (
                        <tfoot>
                          <tr className="border-t border-border bg-surface-secondary/30">
                            <td className="px-4 py-2 text-xs font-semibold text-content-primary">
                              {t('boq.rs_total', { defaultValue: 'Total' })}
                              <span className="ml-1 text-content-tertiary font-normal">
                                ({filteredResources.length}{' '}
                                {t('boq.rs_resources', { defaultValue: 'resources' })})
                              </span>
                            </td>
                            <td />
                            <td />
                            <td />
                            <td />
                            <td className="px-3 py-2 text-right text-xs font-bold text-content-primary tabular-nums">
                              {fmt.format(
                                filteredResources.reduce((sum, r) => sum + r.total_cost, 0),
                              )}
                            </td>
                            <td />
                            <td />
                          </tr>
                        </tfoot>
                      )}
                    </table>

                    {/* Fade overlay + expand/collapse button */}
                    {canExpand && (
                      <div className={`relative ${!expanded ? '-mt-8' : ''}`}>
                        {!expanded && (
                          <div className="absolute inset-x-0 -top-10 h-14 bg-gradient-to-t from-surface-elevated via-surface-elevated/80 to-transparent pointer-events-none" />
                        )}
                        <div className="relative flex justify-center py-2 border-t border-border-light/50">
                          <button
                            onClick={() => setExpanded((prev) => !prev)}
                            className="flex items-center gap-1.5 px-3 py-1 text-2xs font-medium text-oe-blue hover:text-oe-blue-dark hover:bg-oe-blue-subtle/40 rounded-md transition-colors"
                          >
                            {expanded ? (
                              <>
                                <ChevronDown size={12} className="rotate-180" />
                                {t('boq.rs_show_less', { defaultValue: 'Show less' })}
                              </>
                            ) : (
                              <>
                                <ChevronDown size={12} />
                                {t('boq.rs_show_all', { defaultValue: 'Show all {{count}} resources', count: filteredResources.length })}
                                <span className="text-content-tertiary">+{hiddenCount}</span>
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── ResourceRow ─────────────────────────────────────────────────────── */

function ResourceRow({
  resource,
  fmt,
  onSaveToCatalog,
  isSaved,
}: {
  resource: ResourceSummaryItem;
  fmt: Intl.NumberFormat;
  onSaveToCatalog: (resource: ResourceSummaryItem) => void;
  isSaved: boolean;
}) {
  const { t } = useTranslation();
  const badgeStyle = TYPE_BADGE_STYLES[resource.type] || TYPE_BADGE_STYLES.other;

  return (
    <tr className="border-t border-border-light/30 hover:bg-surface-secondary/40 transition-colors group">
      <td className="px-4 py-2 text-content-primary font-medium">{resource.name}</td>
      <td className="px-3 py-2">
        <span
          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${badgeStyle}`}
        >
          {TYPE_ICONS[resource.type] || TYPE_ICONS.other}
          {resource.type}
        </span>
      </td>
      <td className="px-3 py-2 text-center text-content-secondary font-mono uppercase">
        {resource.unit}
      </td>
      <td className="px-3 py-2 text-right text-content-primary tabular-nums">
        {fmt.format(resource.total_quantity)}
      </td>
      <td className="px-3 py-2 text-right text-content-secondary tabular-nums">
        {fmt.format(resource.avg_unit_rate)}
      </td>
      <td className="px-3 py-2 text-right text-content-primary font-semibold tabular-nums">
        {fmt.format(resource.total_cost)}
      </td>
      <td className="px-3 py-2 text-center text-content-tertiary tabular-nums">
        {resource.positions_used}
      </td>
      <td className="px-2 py-2 text-center">
        {isSaved ? (
          <span className="inline-flex items-center gap-0.5 text-semantic-success text-[10px] font-medium">
            <Check size={12} />
          </span>
        ) : (
          <button
            onClick={() => onSaveToCatalog(resource)}
            title={t('boq.rs_save_to_catalog', { defaultValue: 'Save to My Catalog' })}
            className="inline-flex items-center justify-center h-6 w-6 rounded-md text-content-tertiary opacity-0 group-hover:opacity-100 hover:text-oe-blue hover:bg-oe-blue-subtle/40 transition-all"
          >
            <BookmarkPlus size={13} />
          </button>
        )}
      </td>
    </tr>
  );
}
