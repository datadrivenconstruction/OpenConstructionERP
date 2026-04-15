import { useState, useCallback, useMemo, useEffect } from 'react';
import { triggerDownload } from '@/shared/lib/api';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Search, Plus, Layers, ChevronDown, ChevronLeft, ChevronRight, MoreHorizontal,
  Copy, Trash2, Download, ExternalLink, FileSpreadsheet, X, Sparkles, Loader2,
  Upload, Tag, Eye, Share2,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, InfoHint, SkeletonGrid } from '@/shared/ui';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  assembliesApi,
  type Assembly,
  type AssemblySearchResponse,
  type AIGeneratedAssembly,
} from './api';
import { CreateAssemblyModal } from './CreateAssemblyPage';

/* -- Constants ------------------------------------------------------------ */

// Labels are resolved via t() at render time; keep value-only entries here
const CATEGORY_VALUES = [
  { value: '', key: 'assemblies.category_all' },
  { value: 'concrete', key: 'assemblies.category_concrete' },
  { value: 'masonry', key: 'assemblies.category_masonry' },
  { value: 'steel', key: 'assemblies.category_steel' },
  { value: 'mep', key: 'assemblies.category_mep' },
  { value: 'earthwork', key: 'assemblies.category_earthwork' },
  { value: 'insulation', key: 'assemblies.category_insulation' },
  { value: 'finishing', key: 'assemblies.category_finishing' },
  { value: 'roofing', key: 'assemblies.category_roofing' },
  { value: 'general', key: 'assemblies.category_general' },
] as const;

const CATEGORY_COLORS: Record<string, 'blue' | 'success' | 'warning' | 'error' | 'neutral'> = {
  concrete: 'blue',
  masonry: 'warning',
  steel: 'neutral',
  mep: 'success',
  earthwork: 'warning',
  insulation: 'blue',
  finishing: 'success',
  roofing: 'warning',
  general: 'neutral',
};

const UNIT_OPTIONS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'];

/* Templates removed — assemblies are managed via New/AI Generate/Clone/Save from BOQ */

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
  const location = useLocation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Create assembly modal
  const [createModalOpen, setCreateModalOpen] = useState(false);
  useEffect(() => {
    const state = location.state as { openCreateModal?: boolean } | null;
    if (state?.openCreateModal) {
      setCreateModalOpen(true);
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  const PAGE_SIZE = 50;

  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [category, setCategory] = useState('');
  const [offset, setOffset] = useState(0);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showAiGenerate, setShowAiGenerate] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [tagFilter, setTagFilter] = useState('');

  // Debounce search query (300ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!showExportMenu) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowExportMenu(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showExportMenu]);

  const params: Record<string, string> = {};
  if (debouncedQuery) params.q = debouncedQuery;
  if (category) params.category = category;
  if (tagFilter) params.tag = tagFilter;
  params.limit = String(PAGE_SIZE);
  params.offset = String(offset);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['assemblies', debouncedQuery, category, tagFilter, offset],
    queryFn: () => assembliesApi.list(params),
    placeholderData: (prev) => prev,
  });

  const total = data?.total ?? 0;

  // Sort: assemblies with valid names and rates first, garbage/test data last
  const items = useMemo(() => {
    const raw = data?.items ?? [];
    return [...raw].sort((a, b) => {
      const aValid = a.total_rate > 0 && /[a-zA-Z0-9]/.test(a.name);
      const bValid = b.total_rate > 0 && /[a-zA-Z0-9]/.test(b.name);
      if (aValid === bValid) return 0;
      return aValid ? -1 : 1;
    });
  }, [data]);

  const handleSearch = useCallback((value: string) => {
    setQuery(value);
  }, []);

  const handleCategoryChange = useCallback((value: string) => {
    setCategory(value);
    setOffset(0);
  }, []);

  // Templates removed — use New / AI Generate / Clone instead

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  return (
    <div className="w-full animate-fade-in">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('assemblies.title', 'Assemblies')}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {total > 0
              ? `${total} ${t('assemblies.assemblies_found', 'assemblies')}`
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
                      const resp = await apiGet<AssemblySearchResponse>('/v1/assemblies/?limit=500');
                      const allItems = resp.items;
                      // Build CSV with components flattened
                      const rows: string[] = ['Assembly,Category,Unit,Total Rate,Component,Comp Unit,Factor,Rate'];
                      for (const a of allItems) {
                        rows.push([csvEscape(a.name), a.category, a.unit || '', String(a.total_rate ?? ''), '', '', '', ''].join(','));
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
                      const resp = await apiGet<AssemblySearchResponse>('/v1/assemblies/?limit=500');
                      downloadFile(JSON.stringify(resp.items, null, 2), `assemblies_${new Date().toISOString().slice(0, 10)}.json`, 'application/json');
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
            variant="secondary"
            size="sm"
            icon={<Upload size={14} />}
            onClick={() => setShowImportModal(true)}
          >
            {t('assemblies.import', { defaultValue: 'Import' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Sparkles size={14} />}
            onClick={() => setShowAiGenerate(true)}
            className="border-violet-300/40 text-violet-600 hover:bg-violet-50 dark:border-violet-700/30 dark:text-violet-400 dark:hover:bg-violet-950/30"
          >
            {t('assemblies.ai_generate', { defaultValue: 'AI Generate' })}
          </Button>
          <Button
            variant="primary"
            icon={<Plus size={16} />}
            onClick={() => setCreateModalOpen(true)}
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
            <label htmlFor="assemblies-search" className="sr-only">
              {t('common.search', { defaultValue: 'Search' })}
            </label>
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              id="assemblies-search"
              type="text"
              value={query}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder={t(
                'assemblies.search_placeholder',
                'Search by name or code...',
              )}
              aria-label={t('assemblies.search_placeholder', { defaultValue: 'Search by name or code...' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-9 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            />
            {query && (
              <button
                onClick={() => { setQuery(''); setDebouncedQuery(''); setOffset(0); }}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-content-tertiary hover:text-content-primary transition-colors"
                aria-label={t('common.clear', { defaultValue: 'Clear' })}
              >
                <X size={14} />
              </button>
            )}
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

          {/* Tag filter */}
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Tag size={14} />
            </div>
            <input
              type="text"
              value={tagFilter}
              onChange={(e) => { setTagFilter(e.target.value); setOffset(0); }}
              placeholder={t('assemblies.filter_by_tag', { defaultValue: 'Filter by tag...' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-40"
            />
          </div>
        </div>
      </Card>

      {/* Results */}
      {isLoading ? (
        <SkeletonGrid items={6} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Layers size={28} strokeWidth={1.5} />}
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
                  onClick: () => setCreateModalOpen(true),
                }
              : undefined
          }
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((assembly) => (
              <AssemblyCard
                key={assembly.id}
                assembly={assembly}
                fmt={fmt}
                onClick={() => navigate(`/assemblies/${assembly.id}`)}
                onDuplicate={async () => {
                  try {
                    const cloned = await apiPost<Assembly>(`/v1/assemblies/${assembly.id}/clone/`, {});
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
                onExport={async () => {
                  try {
                    const exported = await assembliesApi.exportAssembly(assembly.id);
                    const json = JSON.stringify(exported, null, 2);
                    const blob = new Blob([json], { type: 'application/json' });
                    triggerDownload(blob, `${assembly.code}.json`);
                    addToast({ type: 'success', title: t('assemblies.exported_json', { defaultValue: 'JSON exported' }) });
                  } catch {
                    addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }) });
                  }
                }}
              />
            ))}
          </div>

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
                  {t('assemblies.showing_range', {
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
                        <button onClick={() => goToPage(1)} className="flex h-8 min-w-[32px] items-center justify-center rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors">1</button>
                        {start > 2 && <span className="text-content-quaternary text-xs px-1">...</span>}
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
                        {end < totalPages - 1 && <span className="text-content-quaternary text-xs px-1">...</span>}
                        <button onClick={() => goToPage(totalPages)} className="flex h-8 min-w-[32px] items-center justify-center rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors">{totalPages}</button>
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

      {/* AI Generate Modal */}
      {showAiGenerate && (
        <AIGenerateModal
          onClose={() => setShowAiGenerate(false)}
          onCreated={(id) => {
            setShowAiGenerate(false);
            queryClient.invalidateQueries({ queryKey: ['assemblies'] });
            navigate(`/assemblies/${id}`);
          }}
        />
      )}

      <CreateAssemblyModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
      />

      {/* Import Modal */}
      {showImportModal && (
        <ImportAssemblyModal
          onClose={() => setShowImportModal(false)}
          onImported={() => {
            setShowImportModal(false);
            queryClient.invalidateQueries({ queryKey: ['assemblies'] });
          }}
        />
      )}
    </div>
  );
}

/* -- AI Generate Modal ---------------------------------------------------- */

function AIGenerateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (assemblyId: string) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [description, setDescription] = useState('');
  const [region, setRegion] = useState('');
  const [unit, setUnit] = useState('m2');
  const [result, setResult] = useState<AIGeneratedAssembly | null>(null);
  const [saving, setSaving] = useState(false);

  const generateMutation = useMutation({
    mutationFn: () => assembliesApi.aiGenerate({ description, region, unit }),
    onSuccess: (data) => setResult(data),
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('assemblies.ai_generate_failed', { defaultValue: 'Generation failed' }), message: err.message });
    },
  });

  const handleSave = async () => {
    if (!result) return;
    setSaving(true);
    try {
      // Create the assembly
      const assembly = await assembliesApi.create({
        code: result.code,
        name: result.name,
        unit: result.unit,
        category: result.category || 'general',
        bid_factor: 1.0,
      });

      // Add all components
      for (const comp of result.components) {
        await assembliesApi.addComponent(assembly.id, {
          cost_item_id: comp.cost_item_id || undefined,
          description: comp.name,
          factor: 1.0,
          quantity: comp.quantity,
          unit: comp.unit,
          unit_cost: comp.unit_rate,
        });
      }

      addToast({
        type: 'success',
        title: t('assemblies.ai_assembly_saved', { defaultValue: 'Assembly saved' }),
        message: result.name,
      });
      onCreated(assembly.id);
    } catch {
      addToast({
        type: 'error',
        title: t('assemblies.ai_save_failed', { defaultValue: 'Failed to save assembly' }),
      });
    } finally {
      setSaving(false);
    }
  };

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  const confidenceColor = result
    ? result.confidence >= 0.7
      ? 'text-emerald-600'
      : result.confidence >= 0.4
        ? 'text-amber-600'
        : 'text-red-500'
    : '';

  const confidenceLabel = result
    ? result.confidence >= 0.7
      ? t('assemblies.confidence_high', { defaultValue: 'High' })
      : result.confidence >= 0.4
        ? t('assemblies.confidence_medium', { defaultValue: 'Medium' })
        : t('assemblies.confidence_low', { defaultValue: 'Low' })
    : '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-violet-100 to-blue-100 text-violet-600 dark:from-violet-900/30 dark:to-blue-900/30">
              <Sparkles size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">
                {t('assemblies.ai_generate_title', { defaultValue: 'AI Assembly Generator' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('assemblies.ai_generate_desc', { defaultValue: 'Describe what you need and AI will find matching components' })}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Input form */}
        <div className="px-6 py-4 border-b border-border-light shrink-0 space-y-3">
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('assemblies.ai_description_label', { defaultValue: 'Description' })}
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('assemblies.ai_description_placeholder', { defaultValue: 'e.g. Reinforced concrete wall C30/37, 25cm thickness' })}
              className="w-full h-10 px-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && description.trim().length >= 3 && !generateMutation.isPending) {
                  generateMutation.mutate();
                }
              }}
            />
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-xs font-medium text-content-tertiary mb-1">
                {t('assemblies.unit', { defaultValue: 'Unit' })}
              </label>
              <select
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                className="w-full h-9 px-2.5 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-violet-500/30 appearance-none cursor-pointer"
              >
                {UNIT_OPTIONS.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="block text-xs font-medium text-content-tertiary mb-1">
                {t('assemblies.region', { defaultValue: 'Region (optional)' })}
              </label>
              <input
                type="text"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                placeholder={t('assemblies.region_placeholder', { defaultValue: 'e.g. Berlin' })}
                className="w-full h-9 px-2.5 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-violet-500/30"
              />
            </div>
            <div className="flex items-end">
              <Button
                variant="primary"
                size="sm"
                icon={generateMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                onClick={() => generateMutation.mutate()}
                disabled={description.trim().length < 3 || generateMutation.isPending}
                className="bg-violet-600 hover:bg-violet-700 h-9"
              >
                {generateMutation.isPending
                  ? t('assemblies.generating', { defaultValue: 'Generating...' })
                  : t('assemblies.generate', { defaultValue: 'Generate' })
                }
              </Button>
            </div>
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {!result && !generateMutation.isPending && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Sparkles size={32} className="text-content-quaternary mb-3" />
              <p className="text-sm text-content-tertiary">
                {t('assemblies.ai_generate_hint', { defaultValue: 'Enter a description and click Generate to search for matching cost components' })}
              </p>
            </div>
          )}

          {generateMutation.isPending && (
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin text-violet-500 mb-3" />
              <p className="text-sm text-content-tertiary">
                {t('assemblies.ai_searching', { defaultValue: 'Searching cost database for matching components...' })}
              </p>
            </div>
          )}

          {result && (
            <div className="space-y-4">
              {/* Summary */}
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-content-primary">{result.name}</h3>
                  <p className="text-xs text-content-tertiary mt-0.5">
                    {result.source_items_count} {t('assemblies.items_found', { defaultValue: 'items found' })}
                    {' / '}
                    {t('assemblies.confidence', { defaultValue: 'Confidence' })}: <span className={`font-semibold ${confidenceColor}`}>{confidenceLabel}</span>
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-content-primary tabular-nums">
                    {fmt(result.total_rate)}
                    <span className="text-xs font-normal text-content-tertiary ml-1">/ {result.unit}</span>
                  </p>
                </div>
              </div>

              {/* Components table */}
              {result.components.length > 0 ? (
                <div className="rounded-lg border border-border-light overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border-light bg-surface-tertiary">
                        <th className="px-3 py-2 text-left font-medium text-content-secondary">{t('boq.description', { defaultValue: 'Description' })}</th>
                        <th className="px-3 py-2 text-center font-medium text-content-secondary w-16">{t('assemblies.type', { defaultValue: 'Type' })}</th>
                        <th className="px-3 py-2 text-center font-medium text-content-secondary w-14">{t('boq.unit', { defaultValue: 'Unit' })}</th>
                        <th className="px-3 py-2 text-right font-medium text-content-secondary w-14">{t('boq.quantity', { defaultValue: 'Qty' })}</th>
                        <th className="px-3 py-2 text-right font-medium text-content-secondary w-20">{t('assemblies.rate', { defaultValue: 'Rate' })}</th>
                        <th className="px-3 py-2 text-right font-medium text-content-secondary w-20">{t('boq.total', { defaultValue: 'Total' })}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {result.components.map((comp, idx) => {
                        const typeBadge = comp.type === 'labor'
                          ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400'
                          : comp.type === 'equipment'
                            ? 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400'
                            : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400';
                        return (
                          <tr key={`${comp.name}-${comp.type}-${idx}`} className="hover:bg-surface-secondary/50">
                            <td className="px-3 py-2 text-content-primary truncate max-w-[250px]">{comp.name}</td>
                            <td className="px-3 py-2 text-center">
                              <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${typeBadge}`}>
                                {comp.type}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-center text-content-secondary font-mono uppercase">{comp.unit}</td>
                            <td className="px-3 py-2 text-right text-content-primary tabular-nums">{comp.quantity}</td>
                            <td className="px-3 py-2 text-right text-content-primary tabular-nums">{fmt(comp.unit_rate)}</td>
                            <td className="px-3 py-2 text-right font-semibold text-content-primary tabular-nums">{fmt(comp.total)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="rounded-lg bg-surface-tertiary p-6 text-center">
                  <p className="text-sm text-content-tertiary">
                    {t('assemblies.no_components_found', { defaultValue: 'No matching cost items found. Try a different description.' })}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer actions */}
        {result && result.components.length > 0 && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-border-light shrink-0">
            <Button variant="secondary" size="sm" onClick={() => setResult(null)}>
              {t('assemblies.discard', { defaultValue: 'Discard' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              loading={saving}
              icon={<Layers size={14} />}
              className="bg-violet-600 hover:bg-violet-700"
            >
              {t('assemblies.save_as_assembly', { defaultValue: 'Save as Assembly' })}
            </Button>
          </div>
        )}
      </div>
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
  onExport,
}: {
  assembly: Assembly;
  fmt: (n: number) => string;
  onClick: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onExport: () => void;
}) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
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

      {/* Quick preview overlay */}
      {previewOpen && (
        <QuickPreview
          assemblyId={assembly.id}
          assemblyName={assembly.name}
          onClose={() => setPreviewOpen(false)}
        />
      )}

      <div className="p-5">
        {/* Top row: code + menu */}
        <div className="flex items-start justify-between mb-1.5">
          <p className="text-xs font-mono text-content-tertiary">{assembly.code}</p>
          <div className="flex items-center gap-1">
            <button
              onClick={(e) => { e.stopPropagation(); setPreviewOpen(true); }}
              className="opacity-0 group-hover:opacity-100 flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-all"
              title={t('assemblies.quick_preview', { defaultValue: 'Quick preview' })}
            >
              <Eye size={14} />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
              className="opacity-0 group-hover:opacity-100 flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-all"
            >
              <MoreHorizontal size={14} />
            </button>
          </div>
        </div>

        {/* Context menu */}
        {menuOpen && (
          <div
            className="absolute top-10 right-4 z-20 w-44 rounded-lg border border-border bg-surface-elevated shadow-lg overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => { setMenuOpen(false); onClick(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <ExternalLink size={14} /> {t('assemblies.open_editor', { defaultValue: 'Open Editor' })}
            </button>
            <button
              onClick={() => { setMenuOpen(false); onDuplicate(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Copy size={14} /> {t('assemblies.duplicate', { defaultValue: 'Duplicate & Edit' })}
            </button>
            <button
              onClick={() => { setMenuOpen(false); onExport(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Share2 size={14} /> {t('assemblies.export_json', { defaultValue: 'Export as JSON' })}
            </button>
            <button
              onClick={() => {
                setMenuOpen(false);
                const text = `${assembly.code}\t${assembly.name}\t${assembly.unit}\t${assembly.total_rate}\t${assembly.category}`;
                navigator.clipboard.writeText(text).catch(() => {});
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Download size={14} /> {t('assemblies.copy_data', { defaultValue: 'Copy to Clipboard' })}
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

        {/* Component count + usage count */}
        <div className="mt-1 flex items-center gap-2 text-2xs text-content-tertiary">
          <span>
            {assembly.component_count ?? 0} {t('assemblies.components', { defaultValue: 'components' })}
          </span>
          {(assembly.usage_count ?? 0) > 0 && (
            <>
              <span className="text-content-quaternary">|</span>
              <span className="text-oe-blue">
                {assembly.usage_count} {t('assemblies.times_used', { defaultValue: 'used in BOQ' })}
              </span>
            </>
          )}
        </div>

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

        {/* Category + currency badges */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
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
          {/* Tags */}
          {(assembly.tags ?? []).map((tag) => (
            <Badge key={tag} variant="neutral" size="sm" className="bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-400 border-violet-200/50">
              {tag}
            </Badge>
          ))}
        </div>
      </div>
    </Card>
  );
}

/* -- Quick Preview -------------------------------------------------------- */

function QuickPreview({
  assemblyId,
  assemblyName,
  onClose,
}: {
  assemblyId: string;
  assemblyName: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  const { data, isLoading } = useQuery({
    queryKey: ['assembly-preview', assemblyId],
    queryFn: () => assembliesApi.get(assemblyId),
    staleTime: 60_000,
  });

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  const components = data?.components ?? [];
  const preview = components.slice(0, 5);
  const remaining = components.length - preview.length;

  return (
    <div
      className="absolute inset-0 z-30 flex flex-col rounded-xl bg-white/98 dark:bg-gray-900/98 backdrop-blur-sm p-4 animate-fade-in overflow-hidden"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-content-primary truncate flex-1 mr-2">
          {assemblyName}
        </p>
        <button
          onClick={onClose}
          className="flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:text-content-primary transition-colors shrink-0"
        >
          <X size={12} />
        </button>
      </div>

      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={16} className="animate-spin text-content-tertiary" />
        </div>
      ) : preview.length === 0 ? (
        <p className="text-2xs text-content-tertiary text-center flex-1 flex items-center justify-center">
          {t('assemblies.no_components_hint', { defaultValue: 'No components yet' })}
        </p>
      ) : (
        <div className="flex-1 overflow-hidden">
          <div className="space-y-1">
            {preview.map((comp) => (
              <div key={comp.id} className="flex items-center justify-between gap-2 text-2xs">
                <span className="text-content-primary truncate flex-1">{comp.description}</span>
                <span className="text-content-secondary tabular-nums shrink-0">{fmt(comp.total)}</span>
              </div>
            ))}
          </div>
          {remaining > 0 && (
            <p className="mt-1.5 text-2xs text-content-quaternary">
              +{remaining} {t('assemblies.more_components', { defaultValue: 'more' })}...
            </p>
          )}
          {data && (
            <div className="mt-2 pt-2 border-t border-border-light flex items-center justify-between text-xs">
              <span className="font-medium text-content-secondary">
                {t('assemblies.total_rate', { defaultValue: 'Total Rate' })}
              </span>
              <span className="font-bold text-content-primary tabular-nums">
                {fmt(data.total_rate)} / {data.unit}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* -- Import Assembly Modal ------------------------------------------------ */

function ImportAssemblyModal({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [jsonText, setJsonText] = useState('');
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setJsonText(ev.target?.result as string || '');
      setError('');
    };
    reader.readAsText(file);
  }, []);

  const handleImport = async () => {
    setError('');
    setImporting(true);
    try {
      const parsed = JSON.parse(jsonText);
      if (!parsed.code || !parsed.name || !parsed.unit) {
        setError(t('assemblies.import_invalid', { defaultValue: 'Invalid JSON: must contain code, name, and unit fields' }));
        setImporting(false);
        return;
      }
      await assembliesApi.importAssembly(parsed);
      addToast({ type: 'success', title: t('assemblies.import_success', { defaultValue: 'Assembly imported' }) });
      onImported();
    } catch (err) {
      if (err instanceof SyntaxError) {
        setError(t('assemblies.import_json_error', { defaultValue: 'Invalid JSON format' }));
      } else {
        setError((err as Error).message || t('assemblies.import_failed', { defaultValue: 'Import failed' }));
      }
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-lg mx-4 flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
              <Upload size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">
                {t('assemblies.import_title', { defaultValue: 'Import Assembly' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('assemblies.import_desc', { defaultValue: 'Paste JSON or upload an exported assembly file' })}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-3">
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-content-primary mb-1.5">
              <Upload size={14} />
              {t('assemblies.upload_file', { defaultValue: 'Upload JSON file' })}
            </label>
            <input
              type="file"
              accept=".json"
              onChange={handleFileSelect}
              className="w-full text-sm text-content-secondary file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-border-light file:bg-surface-secondary file:text-sm file:font-medium file:text-content-primary file:cursor-pointer hover:file:bg-surface-tertiary"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('assemblies.or_paste_json', { defaultValue: 'Or paste JSON' })}
            </label>
            <textarea
              value={jsonText}
              onChange={(e) => { setJsonText(e.target.value); setError(''); }}
              rows={8}
              placeholder='{"code": "ASM-001", "name": "...", "unit": "m2", "components": [...]}'
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs font-mono text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue-light/50 focus:border-oe-blue-light resize-none"
            />
          </div>
          {error && (
            <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleImport}
            disabled={!jsonText.trim()}
            loading={importing}
            icon={<Upload size={15} />}
          >
            {t('assemblies.import_btn', { defaultValue: 'Import' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
