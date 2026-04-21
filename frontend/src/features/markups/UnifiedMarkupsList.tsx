/**
 * Unified markup feed — renders the aggregated list from ``useUnifiedMarkups``
 * as a table with source badges, file/type/source filter chips and
 * click-through navigation to the original module.
 *
 * This is the "one place to see everything" experience the user asked for.
 * The existing hub-only CRUD in MarkupsPage is preserved side-by-side.
 */

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Cloud,
  ArrowRight,
  Type,
  Stamp,
  Ruler,
  Highlighter,
  Square,
  Hash,
  Pentagon,
  PenTool,
  FileText,
  FileSpreadsheet,
  Layers,
  Filter,
  Search,
  ChevronRight,
  Circle,
  MapPin,
  Minus,
  TriangleRight,
} from 'lucide-react';
import { Badge, Card, EmptyState } from '@/shared/ui';
import { useUnifiedMarkups } from './useUnifiedMarkups';
import {
  applyFilters,
  type UnifiedMarkup,
  type UnifiedMarkupSource,
  type UnifiedMarkupType,
} from './aggregator';

/* ── Visual tokens ───────────────────────────────────────────────────── */

const SOURCE_META: Record<
  UnifiedMarkupSource,
  { label: string; badge: 'blue' | 'success' | 'warning' | 'neutral'; icon: React.ElementType }
> = {
  markups_hub: { label: 'Markups hub', badge: 'blue', icon: PenTool },
  pdf_takeoff: { label: 'PDF takeoff', badge: 'warning', icon: FileText },
  dwg_takeoff: { label: 'DWG takeoff', badge: 'success', icon: FileSpreadsheet },
};

const TYPE_ICONS: Partial<Record<UnifiedMarkupType, React.ElementType>> = {
  cloud: Cloud,
  arrow: ArrowRight,
  text: Type,
  rectangle: Square,
  highlight: Highlighter,
  distance: Ruler,
  area: TriangleRight,
  count: Hash,
  stamp: Stamp,
  polygon: Pentagon,
  polyline: Pentagon,
  circle: Circle,
  text_pin: MapPin,
  line: Minus,
  volume: Square,
  other: Layers,
};

const inputCls =
  'h-8 rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors';
const selectCls = inputCls + ' pr-7 appearance-none cursor-pointer';

/* ── Table row ───────────────────────────────────────────────────────── */

function UnifiedRow({ item, onOpen }: { item: UnifiedMarkup; onOpen: () => void }) {
  const { t } = useTranslation();
  const SourceIcon = SOURCE_META[item.source].icon;
  const TypeIcon = TYPE_ICONS[item.type] ?? Layers;
  const createdLabel = useMemo(() => {
    try {
      return new Date(item.createdAt).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
    } catch {
      return item.createdAt;
    }
  }, [item.createdAt]);

  return (
    <tr
      onClick={onOpen}
      className="cursor-pointer hover:bg-surface-secondary/60 transition-colors"
      data-testid={`unified-markup-row-${item.id}`}
      data-source={item.source}
      data-native-id={item.nativeId}
    >
      <td className="px-3 py-2.5 max-w-[220px]">
        <div className="flex items-center gap-1.5 min-w-0">
          <SourceIcon size={12} className="text-content-tertiary shrink-0" />
          <span className="text-xs text-content-secondary truncate" title={item.sourceFileName}>
            {item.sourceFileName}
          </span>
        </div>
      </td>
      <td className="px-3 py-2.5">
        <Badge variant={SOURCE_META[item.source].badge} size="sm">
          {t(`markups.source_${item.source}`, { defaultValue: SOURCE_META[item.source].label })}
        </Badge>
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          <TypeIcon size={13} className="text-content-tertiary shrink-0" />
          <span className="text-xs text-content-secondary capitalize">
            {item.type.replace(/_/g, ' ')}
          </span>
        </div>
      </td>
      <td className="px-3 py-2.5 text-xs text-content-secondary tabular-nums text-center">
        {item.page ?? '-'}
      </td>
      <td className="px-3 py-2.5 max-w-[260px]">
        <span
          className="text-sm text-content-primary font-medium truncate block"
          title={item.label}
        >
          {item.label || '-'}
        </span>
      </td>
      <td className="px-3 py-2.5 text-xs text-content-tertiary whitespace-nowrap">
        {createdLabel}
      </td>
      <td className="px-3 py-2.5 text-xs text-content-tertiary max-w-[120px]">
        <span className="truncate block" title={item.author}>
          {item.author}
        </span>
      </td>
      <td className="px-3 py-2.5 text-right">
        <ChevronRight size={14} className="inline text-content-tertiary" />
      </td>
    </tr>
  );
}

/* ── Panel ───────────────────────────────────────────────────────────── */

interface UnifiedMarkupsListProps {
  projectId: string;
  /** Extra query-string to append to deep links (e.g. ``&return=/markups``). */
}

export function UnifiedMarkupsList({ projectId }: UnifiedMarkupsListProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { items, summary, isLoading } = useUnifiedMarkups(projectId);

  const [selectedSources, setSelectedSources] = useState<Set<UnifiedMarkupSource>>(
    () => new Set<UnifiedMarkupSource>(),
  );
  const [selectedTypes, setSelectedTypes] = useState<Set<UnifiedMarkupType>>(
    () => new Set<UnifiedMarkupType>(),
  );
  const [selectedFileId, setSelectedFileId] = useState<string>('');
  const [search, setSearch] = useState('');

  const filtered = useMemo(
    () =>
      applyFilters(items, {
        sources: selectedSources.size > 0 ? selectedSources : undefined,
        types: selectedTypes.size > 0 ? selectedTypes : undefined,
        fileIds:
          selectedFileId && selectedFileId.length > 0 ? new Set([selectedFileId]) : undefined,
        search,
      }),
    [items, selectedSources, selectedTypes, selectedFileId, search],
  );

  const toggleSource = (src: UnifiedMarkupSource) => {
    setSelectedSources((prev) => {
      const next = new Set(prev);
      if (next.has(src)) next.delete(src);
      else next.add(src);
      return next;
    });
  };
  const toggleType = (tp: UnifiedMarkupType) => {
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(tp)) next.delete(tp);
      else next.add(tp);
      return next;
    });
  };

  const sourceChips: UnifiedMarkupSource[] = ['markups_hub', 'pdf_takeoff', 'dwg_takeoff'];
  const typesWithItems = (Object.keys(summary.byType) as UnifiedMarkupType[]).sort();

  return (
    <div className="space-y-3" data-testid="unified-markups-list">
      {/* Toolbar — search + filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[220px] max-w-sm">
          <Search
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('markups.unified_search', {
              defaultValue: 'Search across all annotations...',
            })}
            className={inputCls + ' w-full pl-8'}
            data-testid="unified-markups-search"
          />
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          {sourceChips.map((src) => {
            const active = selectedSources.has(src);
            const count = summary.bySource[src];
            const Icon = SOURCE_META[src].icon;
            return (
              <button
                key={src}
                type="button"
                onClick={() => toggleSource(src)}
                data-testid={`unified-filter-source-${src}`}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition-all',
                  active
                    ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                    : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                )}
              >
                <Icon size={12} />
                {t(`markups.source_${src}`, { defaultValue: SOURCE_META[src].label })}
                <span className="text-content-tertiary tabular-nums">{count}</span>
              </button>
            );
          })}
        </div>

        {summary.files.length > 0 && (
          <select
            value={selectedFileId}
            onChange={(e) => setSelectedFileId(e.target.value)}
            className={selectCls + ' max-w-[200px]'}
            data-testid="unified-filter-file"
          >
            <option value="">
              {t('markups.unified_all_files', { defaultValue: 'All files' })}
            </option>
            {summary.files.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Type filter row — only if > 1 type present */}
      {typesWithItems.length > 1 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <Filter size={12} className="text-content-tertiary" />
          {typesWithItems.map((tp) => {
            const Icon = TYPE_ICONS[tp] ?? Layers;
            const active = selectedTypes.has(tp);
            return (
              <button
                key={tp}
                type="button"
                onClick={() => toggleType(tp)}
                data-testid={`unified-filter-type-${tp}`}
                className={clsx(
                  'inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-2xs font-medium transition-all capitalize',
                  active
                    ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                    : 'border-border-light bg-surface-primary text-content-tertiary hover:bg-surface-secondary',
                )}
              >
                <Icon size={11} />
                {tp.replace(/_/g, ' ')}
                <span className="tabular-nums">{summary.byType[tp]}</span>
              </button>
            );
          })}
          {(selectedTypes.size > 0 || selectedSources.size > 0 || selectedFileId) && (
            <button
              type="button"
              onClick={() => {
                setSelectedTypes(new Set());
                setSelectedSources(new Set());
                setSelectedFileId('');
                setSearch('');
              }}
              className="text-2xs text-oe-blue hover:underline ml-1"
            >
              {t('markups.clear_filters', { defaultValue: 'Clear' })}
            </button>
          )}
        </div>
      )}

      {/* Table */}
      {isLoading && items.length === 0 ? (
        <div className="flex items-center justify-center py-10">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<PenTool size={24} strokeWidth={1.5} />}
          title={
            items.length === 0
              ? t('markups.unified_empty_title', {
                  defaultValue: 'No annotations yet',
                })
              : t('markups.unified_no_match_title', {
                  defaultValue: 'No matching annotations',
                })
          }
          description={
            items.length === 0
              ? t('markups.unified_empty_desc', {
                  defaultValue:
                    'Markups from the Markups hub, PDF takeoff and DWG takeoff will appear here automatically.',
                })
              : t('markups.unified_no_match_desc', {
                  defaultValue: 'Try adjusting your search or filter selection.',
                })
          }
        />
      ) : (
        <Card padding="none" className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="unified-markups-table">
              <thead>
                <tr className="border-b border-border-light bg-surface-secondary/50">
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                    {t('markups.col_file', { defaultValue: 'File' })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[140px]">
                    {t('markups.col_source', { defaultValue: 'Source' })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[130px]">
                    {t('markups.col_type', { defaultValue: 'Type' })}
                  </th>
                  <th className="px-3 py-2 text-center text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[60px]">
                    {t('markups.col_page', { defaultValue: 'Pg' })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                    {t('markups.col_label', { defaultValue: 'Label / Text' })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[110px]">
                    {t('markups.col_created', { defaultValue: 'Created' })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[120px]">
                    {t('markups.col_author', { defaultValue: 'Author' })}
                  </th>
                  <th className="px-3 py-2 text-right text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[40px]" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {filtered.map((item) => (
                  <UnifiedRow
                    key={item.id}
                    item={item}
                    onOpen={() => navigate(item.deepLink)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
