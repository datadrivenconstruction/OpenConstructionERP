import { useState, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { Plus, Trash2, Send, X, Database, Search, Loader2, Check, GripVertical, Share2, Tag } from 'lucide-react';
import { Button, Badge, Card, Input, Breadcrumb, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, triggerDownload } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  assembliesApi,
  type AssemblyComponent,
  type CreateComponentData,
} from './api';

/* -- Constants ------------------------------------------------------------ */

const UNITS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'];

/* -- Component ------------------------------------------------------------ */

export function AssemblyEditorPage() {
  const { t } = useTranslation();
  const { assemblyId } = useParams<{ assemblyId: string }>();
  const queryClient = useQueryClient();

  const [applyModalOpen, setApplyModalOpen] = useState(false);
  const [costDbModalOpen, setCostDbModalOpen] = useState(false);
  const [showTagEditor, setShowTagEditor] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const addToast = useToastStore((s) => s.addToast);

  // Drag state for component reordering
  const dragIdx = useRef<number | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);

  const { data: assembly, isLoading } = useQuery({
    queryKey: ['assembly', assemblyId],
    queryFn: () => assembliesApi.get(assemblyId!),
    enabled: !!assemblyId,
  });

  const addComponentMutation = useMutation({
    mutationFn: (data: CreateComponentData) =>
      assembliesApi.addComponent(assemblyId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
      addToast({ type: 'success', title: t('toasts.component_added', { defaultValue: 'Component added' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const updateComponentMutation = useMutation({
    mutationFn: ({ componentId, data }: { componentId: string; data: Partial<CreateComponentData> }) =>
      assembliesApi.updateComponent(assemblyId!, componentId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.update_failed', { defaultValue: 'Update failed' }), message: error.message });
    },
  });

  const deleteComponentMutation = useMutation({
    mutationFn: (componentId: string) =>
      assembliesApi.deleteComponent(assemblyId!, componentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
      addToast({ type: 'success', title: t('toasts.component_deleted', { defaultValue: 'Component deleted' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const reorderMutation = useMutation({
    mutationFn: (componentIds: string[]) =>
      assembliesApi.reorderComponents(assemblyId!, componentIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.reorder_failed', { defaultValue: 'Reorder failed' }), message: error.message });
    },
  });

  const tagsMutation = useMutation({
    mutationFn: (tags: string[]) =>
      assembliesApi.updateTags(assemblyId!, tags),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
      addToast({ type: 'success', title: t('toasts.tags_updated', { defaultValue: 'Tags updated' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const handleAddComponent = useCallback(() => {
    addComponentMutation.mutate({
      description: 'New component',
      factor: 1,
      quantity: 1,
      unit: assembly?.unit || 'm2',
      unit_cost: 0,
    });
  }, [addComponentMutation, assembly?.unit]);

  const handleExportJson = useCallback(async () => {
    if (!assemblyId) return;
    try {
      const exported = await assembliesApi.exportAssembly(assemblyId);
      const json = JSON.stringify(exported, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      triggerDownload(blob, `${assembly?.code || 'assembly'}.json`);
      addToast({ type: 'success', title: t('assemblies.exported_json', { defaultValue: 'JSON exported' }) });
    } catch {
      addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }) });
    }
  }, [assemblyId, assembly?.code, addToast, t]);

  const handleDragEnd = useCallback((fromIndex: number, toIndex: number) => {
    if (fromIndex === toIndex) return;
    const comps = assembly?.components ?? [];
    if (fromIndex < 0 || fromIndex >= comps.length) return;
    const reordered = [...comps];
    const moved = reordered.splice(fromIndex, 1)[0];
    if (!moved) return;
    reordered.splice(toIndex, 0, moved);
    reorderMutation.mutate(reordered.map((c) => c.id));
  }, [assembly?.components, reorderMutation]);

  const handleAddTag = useCallback(() => {
    const tag = tagInput.trim().toLowerCase();
    if (!tag || !assembly) return;
    const currentTags: string[] = (assembly as { tags?: string[] }).tags ?? [];
    if (currentTags.includes(tag)) {
      setTagInput('');
      return;
    }
    tagsMutation.mutate([...currentTags, tag]);
    setTagInput('');
  }, [tagInput, assembly, tagsMutation]);

  const handleRemoveTag = useCallback((tag: string) => {
    if (!assembly) return;
    const currentTags: string[] = (assembly as { tags?: string[] }).tags ?? [];
    tagsMutation.mutate(currentTags.filter((t) => t !== tag));
  }, [assembly, tagsMutation]);

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  if (isLoading) {
    return (
      <div className="w-full py-8 flex flex-col items-center gap-3 text-content-secondary animate-fade-in">
        <Loader2 size={24} className="animate-spin text-oe-blue" />
        {t('assemblies.loading', { defaultValue: 'Loading assembly...' })}
      </div>
    );
  }

  if (!assembly) {
    return (
      <div className="w-full py-16 text-center">
        <p className="text-content-secondary">{t('assemblies.not_found', { defaultValue: 'Assembly not found' })}</p>
      </div>
    );
  }

  const components = assembly.components ?? [];
  const computedTotal = components.reduce((sum, c) => sum + c.total, 0);
  const adjustedTotal = computedTotal * assembly.bid_factor;

  return (
    <div className="w-full animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        className="mb-4"
        items={[
          { label: t('assemblies.title', 'Assemblies'), to: '/assemblies' },
          { label: assembly.name },
        ]}
      />

      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-content-primary truncate">
              {assembly.name}
            </h1>
            <Badge variant="blue" size="md">
              {assembly.code}
            </Badge>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-content-secondary">
            {assembly.category && (
              <span className="capitalize">{assembly.category}</span>
            )}
            <span className="text-content-tertiary">/</span>
            <span>{assembly.unit}</span>
            <span className="text-content-tertiary">/</span>
            <span>{assembly.currency || 'EUR'}</span>
            {assembly.bid_factor !== 1.0 && (
              <>
                <span className="text-content-tertiary">/</span>
                <span>
                  {t('assemblies.bid_factor', { defaultValue: 'Bid Factor' })}:{' '}
                  <strong className="text-content-primary">{assembly.bid_factor}</strong>
                </span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="secondary"
            size="sm"
            icon={<Share2 size={15} />}
            onClick={handleExportJson}
          >
            {t('assemblies.export_json', { defaultValue: 'Export JSON' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Tag size={15} />}
            onClick={() => setShowTagEditor((v) => !v)}
            className={showTagEditor ? 'ring-2 ring-violet-400/50 border-violet-400' : ''}
          >
            {t('assemblies.tags', { defaultValue: 'Tags' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Send size={15} />}
            onClick={() => setApplyModalOpen(true)}
          >
            {t('assemblies.apply_to_boq', { defaultValue: 'Apply to BOQ' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Database size={15} />}
            onClick={() => setCostDbModalOpen(true)}
            className="border-purple-300/30 text-purple-600 hover:bg-purple-50"
          >
            {t('assemblies.from_database', { defaultValue: 'From Database' })}
          </Button>
          <Button
            variant="primary"
            icon={<Plus size={16} />}
            onClick={handleAddComponent}
          >
            {t('assemblies.add_component', { defaultValue: 'Add Component' })}
          </Button>
        </div>
      </div>

      {/* Tags Editor */}
      {showTagEditor && (
        <Card className="mb-4">
          <div className="flex items-center gap-2 flex-wrap">
            <Tag size={14} className="text-violet-500 shrink-0" />
            {((assembly as { tags?: string[] }).tags ?? []).map((tag) => (
              <Badge
                key={tag}
                variant="neutral"
                size="md"
                className="bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-400 border-violet-200/50 pr-1"
              >
                {tag}
                <button
                  onClick={() => handleRemoveTag(tag)}
                  className="ml-1 flex h-4 w-4 items-center justify-center rounded-full hover:bg-violet-200 dark:hover:bg-violet-800/40 transition-colors"
                >
                  <X size={10} />
                </button>
              </Badge>
            ))}
            <div className="flex items-center gap-1.5">
              <input
                type="text"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAddTag();
                  if (e.key === 'Escape') setShowTagEditor(false);
                }}
                placeholder={t('assemblies.add_tag', { defaultValue: 'Add tag...' })}
                className="h-7 w-28 rounded-md border border-border-light bg-surface-primary px-2 text-xs text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-1 focus:ring-violet-400"
                autoFocus
              />
              <Button
                variant="secondary"
                size="sm"
                onClick={handleAddTag}
                disabled={!tagInput.trim()}
                className="h-7 px-2 text-xs"
              >
                +
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Components Table */}
      <Card padding="none" className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-tertiary text-left">
                <th className="w-8 px-1 py-3" />
                <th className="px-4 py-3 font-medium text-content-secondary min-w-[280px]">
                  {t('boq.description')}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-24 text-right">
                  {t('assemblies.factor', { defaultValue: 'Factor' })}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-24 text-right">
                  {t('boq.quantity', { defaultValue: 'Qty' })}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-20 text-center">
                  {t('boq.unit')}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-28 text-right">
                  {t('assemblies.unit_cost', { defaultValue: 'Unit Cost' })}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-32 text-right">
                  {t('boq.total', { defaultValue: 'Total' })}
                </th>
                <th className="px-4 py-3 w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {components.map((component, idx) => (
                <ComponentRow
                  key={component.id}
                  component={component}
                  isDragOver={dragOverIdx === idx}
                  onDragStart={() => { dragIdx.current = idx; }}
                  onDragOver={(e) => { e.preventDefault(); setDragOverIdx(idx); }}
                  onDragEnd={() => {
                    if (dragIdx.current !== null && dragOverIdx !== null) {
                      handleDragEnd(dragIdx.current, dragOverIdx);
                    }
                    dragIdx.current = null;
                    setDragOverIdx(null);
                  }}
                  onDragLeave={() => setDragOverIdx(null)}
                  onUpdate={(data) =>
                    updateComponentMutation.mutate({
                      componentId: component.id,
                      data,
                    })
                  }
                  onDelete={() => deleteComponentMutation.mutate(component.id)}
                  fmt={fmt}
                />
              ))}
              {components.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-content-tertiary">
                    {t('assemblies.no_components_hint', { defaultValue: 'No components yet. Click "Add Component" to start building this assembly.' })}
                  </td>
                </tr>
              )}
            </tbody>
            {components.length > 0 && (
              <tfoot>
                {assembly.bid_factor !== 1.0 && (
                  <tr className="border-t border-border-light bg-surface-tertiary/50">
                    <td colSpan={6} className="px-4 py-2.5 text-right text-sm text-content-secondary">
                      {t('assemblies.subtotal', { defaultValue: 'Subtotal' })}
                    </td>
                    <td className="px-4 py-2.5 text-right text-sm text-content-secondary tabular-nums">
                      {fmt(computedTotal)}
                    </td>
                    <td />
                  </tr>
                )}
                {assembly.bid_factor !== 1.0 && (
                  <tr className="border-t border-border-light bg-surface-tertiary/50">
                    <td colSpan={6} className="px-4 py-2.5 text-right text-sm text-content-secondary">
                      {t('assemblies.bid_factor', { defaultValue: 'Bid Factor' })} ({assembly.bid_factor})
                    </td>
                    <td className="px-4 py-2.5 text-right text-sm text-content-secondary tabular-nums">
                      x {assembly.bid_factor}
                    </td>
                    <td />
                  </tr>
                )}
                <tr className="border-t-2 border-border bg-surface-tertiary font-semibold">
                  <td colSpan={6} className="px-4 py-3 text-right text-content-primary">
                    {assembly.bid_factor !== 1.0
                      ? t('assemblies.total_rate_adjusted', {
                          defaultValue: 'Total Rate (\u00d7{{factor}} bid factor)',
                          factor: assembly.bid_factor,
                        })
                      : t('assemblies.total_rate', { defaultValue: 'Total Rate' })}
                  </td>
                  <td className="px-4 py-3 text-right text-content-primary text-base tabular-nums">
                    {fmt(adjustedTotal)}
                    <span className="ml-1 text-xs font-normal text-content-tertiary">
                      / {assembly.unit}
                    </span>
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </Card>

      {/* Apply to BOQ Modal */}
      {applyModalOpen && (
        <ApplyToBOQModal
          assemblyId={assemblyId!}
          assemblyName={assembly.name}
          regionalFactors={assembly.regional_factors}
          onClose={() => setApplyModalOpen(false)}
        />
      )}

      {/* Cost Database Search Modal */}
      {costDbModalOpen && assemblyId && (
        <CostDbSearchForAssembly
          assemblyId={assemblyId}
          onClose={() => setCostDbModalOpen(false)}
          onAdded={() => {
            setCostDbModalOpen(false);
            queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
            addToast({ type: 'success', title: t('assemblies.components_added_from_db', { defaultValue: 'Components added from cost database' }) });
          }}
        />
      )}
    </div>
  );
}

/* -- Cost DB Search for Assembly ------------------------------------------ */

interface CostSearchItem {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
}

function CostDbSearchForAssembly({
  assemblyId,
  onClose,
  onAdded,
}: {
  assemblyId: string;
  onClose: () => void;
  onAdded: () => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState<Set<string>>(new Set());
  const addToast = useToastStore((s) => s.addToast);

  const { data: items, isLoading } = useQuery({
    queryKey: ['cost-search-assembly', search],
    queryFn: () => {
      const params = search.length >= 2 ? `q=${encodeURIComponent(search)}&limit=20` : 'limit=20';
      return apiGet<{ items: CostSearchItem[] }>(`/v1/costs/?${params}`).then((r) => r.items);
    },
    retry: false,
  });

  const handleAdd = useCallback(
    async (item: CostSearchItem) => {
      setAdding((prev) => new Set(prev).add(item.id));
      try {
        await assembliesApi.addComponent(assemblyId, {
          cost_item_id: item.id,
          description: item.description,
          unit: item.unit,
          unit_cost: item.rate,
          quantity: 1,
          factor: 1.0,
        });
        setAdded((prev) => new Set(prev).add(item.id));
        addToast({ type: 'success', title: t('common.added', { defaultValue: 'Added' }), message: (item.description || item.code).slice(0, 60) });
      } catch {
        addToast({ type: 'error', title: t('assemblies.add_failed', { defaultValue: 'Failed to add' }) });
      } finally {
        setAdding((prev) => {
          const next = new Set(prev);
          next.delete(item.id);
          return next;
        });
      }
    },
    [assemblyId, addToast],
  );

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-100 text-purple-600 dark:bg-purple-900/30">
              <Database size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">{t('assemblies.add_from_cost_db', { defaultValue: 'Add from Cost Database' })}</h2>
              <p className="text-xs text-content-tertiary">{t('assemblies.add_from_cost_db_desc', { defaultValue: 'Search and add cost items as assembly components' })}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="primary" size="sm" onClick={onAdded}>
              {t('common.done', { defaultValue: 'Done' })}
            </Button>
            <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="px-6 py-3 border-b border-border-light shrink-0">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-quaternary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('assemblies.search_cost_placeholder', { defaultValue: 'Search cost items by description or code...' })}
              className="w-full h-9 pl-9 pr-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-purple-500/30 focus:border-purple-400"
              autoFocus
            />
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-6 py-3">
          {isLoading ? (
            <div className="flex items-center justify-center py-12 text-xs text-content-tertiary">
              <Loader2 size={16} className="animate-spin mr-2" /> {t('common.searching', { defaultValue: 'Searching...' })}
            </div>
          ) : !items || items.length === 0 ? (
            <div className="flex items-center justify-center py-12 text-xs text-content-tertiary">
              {t('assemblies.no_cost_items_found', { defaultValue: 'No cost items found for' })} &quot;{search}&quot;
            </div>
          ) : (
            <div className="space-y-1">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border-light px-3 py-2.5 hover:bg-surface-secondary/50 transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-content-primary truncate">{item.description || item.code}</p>
                    {item.description && <p className="text-2xs text-content-tertiary font-mono">{item.code}</p>}
                  </div>
                  <span className="text-xs text-content-secondary font-mono uppercase shrink-0">{item.unit}</span>
                  <span className="text-sm font-semibold text-content-primary tabular-nums shrink-0 w-20 text-right">
                    {fmt(item.rate)}
                  </span>
                  {added.has(item.id) ? (
                    <span className="flex items-center gap-1 text-xs font-medium text-green-600 px-2">
                      <Check size={14} /> {t('common.added', { defaultValue: 'Added' })}
                    </span>
                  ) : (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleAdd(item)}
                      loading={adding.has(item.id)}
                      disabled={adding.size > 0}
                    >
                      + {t('common.add', { defaultValue: 'Add' })}
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


/* -- Component Row (inline editable) -------------------------------------- */

function ComponentRow({
  component,
  isDragOver,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDragLeave,
  onUpdate,
  onDelete,
  fmt,
}: {
  component: AssemblyComponent;
  isDragOver: boolean;
  onDragStart: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragEnd: () => void;
  onDragLeave: () => void;
  onUpdate: (data: Partial<CreateComponentData>) => void;
  onDelete: () => void;
  fmt: (n: number) => string;
}) {
  const { t } = useTranslation();
  const { confirm, ...confirmProps } = useConfirm();
  const [editing, setEditing] = useState<string | null>(null);

  const handleBlur = (field: string, value: string) => {
    setEditing(null);
    const numFields = ['factor', 'quantity', 'unit_cost'];
    const update: Partial<CreateComponentData> = {
      [field]: numFields.includes(field) ? parseFloat(value) || 0 : value,
    };
    onUpdate(update);
  };

  const cellClass =
    'px-4 py-2.5 transition-colors cursor-text hover:bg-oe-blue-subtle/50';
  const inputClass =
    'w-full bg-transparent border-none outline-none focus:ring-0 p-0 text-sm';

  return (
    <>
    <tr
      className={`group hover:bg-surface-secondary/50 transition-colors ${isDragOver ? 'border-t-2 border-oe-blue' : ''}`}
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragLeave={onDragLeave}
    >
      {/* Drag handle */}
      <td className="px-1 py-2.5 cursor-grab active:cursor-grabbing">
        <div className="flex items-center justify-center text-content-quaternary group-hover:text-content-tertiary transition-colors">
          <GripVertical size={14} />
        </div>
      </td>

      {/* Description */}
      <td className={cellClass}>
        <EditableCell
          value={component.description}
          field="description"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={inputClass}
          placeholder={t('assemblies.enter_description', { defaultValue: 'Enter description...' })}
        />
      </td>

      {/* Factor */}
      <td className={`${cellClass} text-right`}>
        <EditableCell
          value={String(component.factor)}
          field="factor"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} text-right`}
          type="number"
        />
      </td>

      {/* Quantity */}
      <td className={`${cellClass} text-right`}>
        <EditableCell
          value={String(component.quantity)}
          field="quantity"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} text-right`}
          type="number"
        />
      </td>

      {/* Unit */}
      <td className="px-4 py-2.5 text-center">
        <select
          value={component.unit}
          onChange={(e) => onUpdate({ unit: e.target.value })}
          className="bg-transparent text-sm text-center cursor-pointer border-none outline-none text-content-secondary hover:text-content-primary"
        >
          {UNITS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
      </td>

      {/* Unit Cost */}
      <td className={`${cellClass} text-right`}>
        <EditableCell
          value={String(component.unit_cost)}
          field="unit_cost"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} text-right`}
          type="number"
        />
      </td>

      {/* Total (computed) */}
      <td className="px-4 py-2.5 text-right font-semibold text-content-primary tabular-nums">
        {fmt(component.total)}
      </td>

      {/* Delete */}
      <td className="px-2 py-2.5">
        <button
          onClick={async () => {
            const ok = await confirm({
              title: t('assemblies.confirm_delete_component_title', { defaultValue: 'Remove component?' }),
              message: t('assemblies.confirm_delete_component', { defaultValue: 'Remove this component from the assembly?' }),
            });
            if (ok) onDelete();
          }}
          className="opacity-0 group-hover:opacity-100 flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-all"
        >
          <Trash2 size={14} />
        </button>
      </td>
    </tr>
    <ConfirmDialog {...confirmProps} />
    </>
  );
}

/* -- Editable Cell -------------------------------------------------------- */

function EditableCell({
  value,
  field,
  editing,
  setEditing,
  onBlur,
  className,
  placeholder,
  type = 'text',
}: {
  value: string;
  field: string;
  editing: string | null;
  setEditing: (f: string | null) => void;
  onBlur: (field: string, value: string) => void;
  className?: string;
  placeholder?: string;
  type?: string;
}) {
  if (editing === field) {
    return (
      <input
        type={type}
        defaultValue={value}
        autoFocus
        className={className}
        placeholder={placeholder}
        onBlur={(e) => onBlur(field, e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          if (e.key === 'Escape') setEditing(null);
        }}
      />
    );
  }

  return (
    <span
      onClick={() => setEditing(field)}
      className={`block min-h-[20px] ${!value && placeholder ? 'text-content-tertiary' : ''}`}
    >
      {value || placeholder || ''}
    </span>
  );
}

/* -- Apply to BOQ Modal --------------------------------------------------- */

function ApplyToBOQModal({
  assemblyId,
  assemblyName,
  regionalFactors,
  onClose,
}: {
  assemblyId: string;
  assemblyName: string;
  regionalFactors?: Record<string, string>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [projectId, setProjectId] = useState('');
  const [boqId, setBoqId] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [region, setRegion] = useState('');

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Array<{ id: string; name: string }>>('/v1/projects/'),
    retry: false,
    staleTime: 5 * 60_000,
  });

  const { data: boqs } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () =>
      apiGet<Array<{ id: string; name: string }>>(`/v1/boq/boqs/?project_id=${projectId}`),
    enabled: !!projectId,
    retry: false,
  });

  const applyMutation = useMutation({
    mutationFn: () =>
      assembliesApi.applyToBoq(assemblyId, boqId, parseFloat(quantity) || 1),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boq'] });
      queryClient.invalidateQueries({ queryKey: ['boqs'] });
      addToast({ type: 'success', title: t('toasts.assembly_applied', { defaultValue: 'Assembly applied to BOQ' }) });
      onClose();
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!boqId) return;
    applyMutation.mutate();
  };

  const hasRegionalFactors =
    regionalFactors && Object.keys(regionalFactors).length > 0;

  const selectClass =
    'w-full h-10 px-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue-light/50 focus:border-oe-blue-light';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-md mx-4 animate-fade-in">
        <Card>
          <div className="flex items-start justify-between mb-5">
            <div>
              <h2 className="text-lg font-semibold text-content-primary">{t('assemblies.apply_to_boq', { defaultValue: 'Apply to BOQ' })}</h2>
              <p className="mt-0.5 text-sm text-content-secondary line-clamp-1">
                {assemblyName}
              </p>
            </div>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-all"
            >
              <X size={16} />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Project selector */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('projects.project', { defaultValue: 'Project' })}
              </label>
              <select
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value);
                  setBoqId('');
                }}
                className={selectClass}
                autoFocus
              >
                <option value="">
                  {t('projects.select_project', { defaultValue: 'Select project...' })}
                </option>
                {projects?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            {/* BOQ selector */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('boq.boq', { defaultValue: 'BOQ' })}
              </label>
              <select
                value={boqId}
                onChange={(e) => setBoqId(e.target.value)}
                className={selectClass}
                disabled={!projectId}
              >
                <option value="">
                  {t('boq.select_boq', { defaultValue: 'Select BOQ...' })}
                </option>
                {boqs?.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
              {projectId && boqs && boqs.length === 0 && (
                <p className="mt-1 text-xs text-content-tertiary">
                  {t('boq.no_boqs_for_project', { defaultValue: 'No BOQs found for this project' })}
                </p>
              )}
            </div>

            {/* Regional factor selector */}
            {hasRegionalFactors && (
              <div>
                <label className="block text-sm font-medium text-content-primary mb-1.5">
                  {t('assemblies.select_region', { defaultValue: 'Region (applies regional factor)' })}
                </label>
                <select
                  value={region}
                  onChange={(e) => setRegion(e.target.value)}
                  className={selectClass}
                >
                  <option value="">
                    {t('assemblies.no_regional_factor', { defaultValue: 'No regional factor' })}
                  </option>
                  {Object.entries(regionalFactors!).map(([r, factor]) => (
                    <option key={r} value={r}>
                      {r} (&times;{factor})
                    </option>
                  ))}
                </select>
              </div>
            )}

            <Input
              label={t('boq.quantity', { defaultValue: 'Quantity' })}
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="1"
              hint={t('assemblies.quantity_hint', { defaultValue: 'Number of times to apply this assembly' })}
            />

            {applyMutation.error && (
              <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
                {(applyMutation.error as Error).message || t('assemblies.apply_failed', { defaultValue: 'Failed to apply assembly to BOQ' })}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-1">
              <Button variant="secondary" type="button" onClick={onClose}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                type="submit"
                loading={applyMutation.isPending}
                disabled={!boqId}
                icon={<Send size={15} />}
              >
                {t('common.apply', { defaultValue: 'Apply' })}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
