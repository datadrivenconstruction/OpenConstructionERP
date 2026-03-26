import { useState, useCallback, useMemo } from 'react';
import { triggerDownload } from '@/shared/lib/api';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Search, Plus, Layers, ChevronDown, MoreHorizontal,
  Copy, Trash2, Download, ExternalLink, FileSpreadsheet,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, InfoHint, SkeletonGrid } from '@/shared/ui';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { assembliesApi, type Assembly } from './api';

/* -- Constants ------------------------------------------------------------ */

// Labels are resolved via t() at render time; keep value-only entries here
const CATEGORY_VALUES = [
  { value: '', key: 'assemblies.category_all' },
  { value: 'concrete', key: 'assemblies.category_concrete' },
  { value: 'masonry', key: 'assemblies.category_masonry' },
  { value: 'steel', key: 'assemblies.category_steel' },
  { value: 'mep', key: 'assemblies.category_mep' },
  { value: 'earthwork', key: 'assemblies.category_earthwork' },
  { value: 'general', key: 'assemblies.category_general' },
] as const;

const CATEGORY_COLORS: Record<string, 'blue' | 'success' | 'warning' | 'error' | 'neutral'> = {
  concrete: 'blue',
  masonry: 'warning',
  steel: 'neutral',
  mep: 'success',
  earthwork: 'warning',
  general: 'neutral',
};

/* -- Helpers -------------------------------------------------------------- */

function csvEscape(val: string): string {
  if (val.includes(',') || val.includes('"') || val.includes('\n')) {
    return `"${val.replace(/"/g, '""')}"`;
  }
  return val;
}

function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  triggerDownload(blob, filename);
}

/* -- Component ------------------------------------------------------------ */

export function AssembliesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [showExportMenu, setShowExportMenu] = useState(false);

  const params: Record<string, string> = {};
  if (query) params.q = query;
  if (category) params.category = category;

  const { data: assemblies, isLoading } = useQuery({
    queryKey: ['assemblies', query, category],
    queryFn: () => assembliesApi.list(params),
    placeholderData: (prev) => prev,
  });

  // Sort: assemblies with valid names and rates first, garbage/test data last
  const items = useMemo(() => {
    const raw = assemblies ?? [];
    return [...raw].sort((a, b) => {
      const aValid = a.total_rate > 0 && /[a-zA-Z0-9]/.test(a.name);
      const bValid = b.total_rate > 0 && /[a-zA-Z0-9]/.test(b.name);
      if (aValid === bValid) return 0;
      return aValid ? -1 : 1;
    });
  }, [assemblies]);

  const handleSearch = useCallback((value: string) => {
    setQuery(value);
  }, []);

  const handleCategoryChange = useCallback((value: string) => {
    setCategory(value);
  }, []);

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('assemblies.title', 'Assemblies')}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {items.length > 0
              ? `${items.length} ${t('assemblies.assemblies_found', 'assemblies')}`
              : t('assemblies.description', 'Reusable cost recipes for common construction elements')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              onClick={() => setShowExportMenu((p) => !p)}
            >
              {t('common.export', { defaultValue: 'Export' })}
            </Button>
            {showExportMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-lg border border-border-light bg-surface-elevated shadow-md animate-fade-in">
                <button
                  onClick={async () => {
                    setShowExportMenu(false);
                    try {
                      const data = await apiGet<Assembly[]>('/v1/assemblies/?limit=500');
                      // Build CSV with components flattened
                      const rows: string[] = ['Assembly,Category,Unit,Total Rate,Component,Comp Unit,Factor,Rate'];
                      for (const a of data) {
                        if (a.components && a.components.length > 0) {
                          for (const c of a.components) {
                            rows.push(
                              [
                                csvEscape(a.name), a.category, a.unit || '', String(a.total_rate ?? ''),
                                csvEscape(c.name || c.description || ''), c.unit || '', String(c.factor ?? c.quantity ?? ''), String(c.unit_rate ?? ''),
                              ].join(','),
                            );
                          }
                        } else {
                          rows.push([csvEscape(a.name), a.category, a.unit || '', String(a.total_rate ?? ''), '', '', '', ''].join(','));
                        }
                      }
                      downloadFile(rows.join('\n'), `assemblies_${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv');
                      addToast({ type: 'success', title: t('assemblies.exported_csv', { defaultValue: 'CSV exported' }) });
                    } catch {
                      addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }) });
                    }
                  }}
                  className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-t-lg"
                >
                  <FileSpreadsheet size={15} className="text-content-tertiary" />
                  CSV (.csv)
                </button>
                <button
                  onClick={async () => {
                    setShowExportMenu(false);
                    try {
                      const data = await apiGet<Assembly[]>('/v1/assemblies/?limit=500');
                      downloadFile(JSON.stringify(data, null, 2), `assemblies_${new Date().toISOString().slice(0, 10)}.json`, 'application/json');
                      addToast({ type: 'success', title: t('assemblies.exported_json', { defaultValue: 'JSON exported' }) });
                    } catch {
                      addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }) });
                    }
                  }}
                  className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-b-lg"
                >
                  <Download size={15} className="text-content-tertiary" />
                  JSON (.json)
                </button>
              </div>
            )}
          </div>
          <Button
            variant="primary"
            icon={<Plus size={16} />}
            onClick={() => navigate('/assemblies/new')}
          >
            {t('assemblies.new_assembly', 'New Assembly')}
          </Button>
        </div>
      </div>

      {/* Explanation */}
      <InfoHint className="mb-4" text={t('assemblies.what_are_assemblies', { defaultValue: 'Assemblies are reusable cost recipes that combine multiple resources (materials, labor, equipment) into a single composite rate. For example, a "Reinforced Concrete Wall" assembly includes concrete, rebar, formwork, and labor. Apply assemblies to BOQ positions to auto-populate component costs.' })} />

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
              placeholder={t(
                'assemblies.search_placeholder',
                'Search by name or code...',
              )}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            />
          </div>

          {/* Category filter */}
          <div className="relative">
            <select
              value={category}
              onChange={(e) => handleCategoryChange(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-44"
            >
              {CATEGORY_VALUES.map((c) => (
                <option key={c.value} value={c.value}>
                  {t(c.key, { defaultValue: c.value || 'All categories' })}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </div>
      </Card>

      {/* Results */}
      {isLoading ? (
        <SkeletonGrid items={6} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Layers size={24} strokeWidth={1.5} />}
          title={
            query || category
              ? t('assemblies.no_results', { defaultValue: 'No assemblies found' })
              : t('assemblies.no_assemblies', { defaultValue: 'No assemblies yet' })
          }
          description={
            query || category
              ? t('assemblies.no_results_hint', { defaultValue: 'Try adjusting your search or filters' })
              : t('assemblies.empty_hint', {
                  defaultValue: 'Create your first assembly to build reusable cost recipes',
                })
          }
          action={
            !query && !category
              ? {
                  label: t('assemblies.new_assembly', { defaultValue: 'Create Assembly' }),
                  onClick: () => navigate('/assemblies/new'),
                }
              : undefined
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((assembly) => (
            <AssemblyCard
              key={assembly.id}
              assembly={assembly}
              fmt={fmt}
              onClick={() => navigate(`/assemblies/${assembly.id}`)}
              onDuplicate={async () => {
                try {
                  const cloned = await apiPost<Assembly>(`/v1/assemblies/${assembly.id}/clone`, {});
                  queryClient.invalidateQueries({ queryKey: ['assemblies'] });
                  addToast({ type: 'success', title: t('toasts.assembly_duplicated', { defaultValue: 'Assembly duplicated' }), message: cloned.name });
                } catch {
                  addToast({ type: 'error', title: t('toasts.duplicate_failed', { defaultValue: 'Duplicate failed' }) });
                }
              }}
              onDelete={async () => {
                try {
                  await apiDelete(`/v1/assemblies/${assembly.id}`);
                  queryClient.invalidateQueries({ queryKey: ['assemblies'] });
                  addToast({ type: 'success', title: t('toasts.assembly_deleted', { defaultValue: 'Assembly deleted' }) });
                } catch {
                  addToast({ type: 'error', title: t('toasts.delete_failed', { defaultValue: 'Delete failed' }) });
                }
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* -- Assembly Card -------------------------------------------------------- */

function AssemblyCard({
  assembly,
  fmt,
  onClick,
  onDuplicate,
  onDelete,
}: {
  assembly: Assembly;
  fmt: (n: number) => string;
  onClick: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const badgeVariant = CATEGORY_COLORS[assembly.category] ?? 'neutral';

  return (
    <Card
      padding="none"
      hoverable
      className="cursor-pointer group relative"
      onClick={onClick}
    >
      {/* Delete confirmation overlay */}
      {confirmDelete && (
        <div
          className="absolute inset-0 z-30 flex items-center justify-center rounded-xl bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm p-4"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-50 dark:bg-red-900/20 mx-auto mb-3">
              <Trash2 size={18} className="text-red-500" />
            </div>
            <p className="text-sm font-semibold text-content-primary mb-1">{t('assemblies.delete_confirm', { defaultValue: 'Delete assembly?' })}</p>
            <p className="text-xs text-content-tertiary mb-4 max-w-[180px] mx-auto line-clamp-1">{assembly.name}</p>
            <div className="flex items-center justify-center gap-2">
              <Button variant="danger" size="sm" onClick={() => { onDelete(); setConfirmDelete(false); }}>
                {t('common.delete', { defaultValue: 'Delete' })}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setConfirmDelete(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      <div className="p-5">
        {/* Top row: code + menu */}
        <div className="flex items-start justify-between mb-1.5">
          <p className="text-xs font-mono text-content-tertiary">{assembly.code}</p>
          <button
            onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
            className="opacity-0 group-hover:opacity-100 flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-all"
          >
            <MoreHorizontal size={14} />
          </button>
        </div>

        {/* Context menu */}
        {menuOpen && (
          <div
            className="absolute top-10 right-4 z-20 w-40 rounded-lg border border-border bg-surface-elevated shadow-lg overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => { setMenuOpen(false); onClick(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <ExternalLink size={14} /> {t('common.open', { defaultValue: 'Open' })}
            </button>
            <button
              onClick={() => { setMenuOpen(false); onDuplicate(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Copy size={14} /> {t('common.duplicate', { defaultValue: 'Duplicate' })}
            </button>
            <div className="h-px bg-border-light" />
            <button
              onClick={() => { setMenuOpen(false); setConfirmDelete(true); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
            >
              <Trash2 size={14} /> {t('common.delete', { defaultValue: 'Delete' })}
            </button>
          </div>
        )}

        {/* Name */}
        <h3 className="text-sm font-semibold text-content-primary leading-snug line-clamp-2 group-hover:text-oe-blue transition-colors">
          {assembly.name}
        </h3>

        {/* Rate */}
        <p className="mt-3 text-lg font-bold tabular-nums" style={{ color: assembly.total_rate > 0 ? undefined : 'var(--color-content-tertiary)' }}>
          {assembly.total_rate > 0 ? fmt(assembly.total_rate) : '0,00'}
          <span className="ml-1 text-xs font-normal text-content-tertiary">
            / {assembly.unit}
          </span>
          {assembly.total_rate === 0 && (
            <span className="ml-2 text-2xs font-medium text-amber-500">
              ({t('assemblies.draft', { defaultValue: 'draft' })})
            </span>
          )}
        </p>

        {/* Tags */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {assembly.category && (
            <Badge variant={badgeVariant} size="sm">
              {assembly.category}
            </Badge>
          )}
          <Badge variant="neutral" size="sm">
            {assembly.currency || 'EUR'}
          </Badge>
          {assembly.bid_factor !== 1.0 && (
            <Badge variant="blue" size="sm">
              BF {assembly.bid_factor}
            </Badge>
          )}
        </div>
      </div>
    </Card>
  );
}
