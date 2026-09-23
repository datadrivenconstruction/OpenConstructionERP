// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useRef, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Plus,
  Trash2,
  Send,
  X,
  Database,
  Search,
  Loader2,
  Check,
  GripVertical,
  Share2,
  Tag,
  Hammer,
  HardHat,
  Wrench,
  Layers as LayersIcon,
  Briefcase,
  Boxes,
  ChevronDown,
  ChevronUp,
  Info,
  Play,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, Badge, Card, Input, Breadcrumb, ConfirmDialog, DismissibleInfo } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, triggerDownload } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { fmtPercent } from '@/shared/lib/formatters';
import { currencyFractionDigits } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { getUnitsForLocale } from '@/features/boq/boqHelpers';
import { unitGlyph, unitLabel } from '@/shared/lib/unitLabels';
import {
  assembliesApi,
  type AssemblyComponent,
  type AssemblyParameter,
  type ComponentMetadata,
  type CreateComponentData,
  type ResourceType,
} from './api';
import { ParametersPanel } from './ParametersPanel';
import { ExpandPreviewModal } from './ExpandPreviewModal';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* -- Component ------------------------------------------------------------ */

export function AssemblyEditorPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { assemblyId } = useParams<{ assemblyId: string }>();
  const queryClient = useQueryClient();
  // Seed new component units from the user's measurement system (imperial ->
  // sqft, metric -> m2) the same way the BOQ editor does, so an imperial user
  // no longer lands on a hardcoded metric unit. Storage stays free-text.
  const measurementSystem = usePreferencesStore((s) => s.measurementSystem);
  const defaultUnit = measurementSystem === 'imperial' ? 'sqft' : 'm2';

  const [applyModalOpen, setApplyModalOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [costDbModalOpen, setCostDbModalOpen] = useState(false);
  const [catalogPickerOpen, setCatalogPickerOpen] = useState(false);
  const [catalogPickerType, setCatalogPickerType] = useState<ResourceType | null>(null);
  // The "+ Add" split-button reveals six typed seeds — material is the
  // common case, the rest cover the standard professional vocabulary
  // (estimating tools split M/L/E/S; integrated 5D estimating suites also
  // include operator + overhead).
  const [addMenuOpen, setAddMenuOpen] = useState(false);
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

  // Typed seed defaults — picked to look intentional in the editor right
  // after add, so the user sees what each type expects (labor → "h",
  // equipment → "h", material → assembly's own unit). The seed metadata
  // primes the type-specific extended fields (waste/burden/fuel) at
  // sensible defaults so the per-type formula activates immediately.
  const handleAddComponent = useCallback(
    (resource_type: ResourceType = 'material') => {
      setAddMenuOpen(false);
      const defaults: Record<
        ResourceType,
        { description: string; unit: string; metadata?: CreateComponentData['metadata'] }
      > = {
        material: {
          description: t('assemblies.seed_material', { defaultValue: 'New material' }),
          unit: assembly?.unit || defaultUnit,
          metadata: { waste_pct: 0 },
        },
        labor: {
          description: t('assemblies.seed_labor', { defaultValue: 'New labor line' }),
          unit: 'h',
          metadata: { crew_size: 1, burden_pct: 0 },
        },
        equipment: {
          description: t('assemblies.seed_equipment', { defaultValue: 'New equipment' }),
          unit: 'h',
          metadata: { rental_days: 0, fuel_cost: 0 },
        },
        operator: {
          description: t('assemblies.seed_operator', { defaultValue: 'New operator' }),
          unit: 'h',
          metadata: {},
        },
        subcontractor: {
          description: t('assemblies.seed_subcontractor', { defaultValue: 'New subcontract' }),
          unit: assembly?.unit || 'lsum',
          metadata: {},
        },
        overhead: {
          description: t('assemblies.seed_overhead', { defaultValue: 'Overhead / markup' }),
          unit: assembly?.unit || 'lsum',
          metadata: {},
        },
      };
      const d = defaults[resource_type];
      addComponentMutation.mutate({
        description: d.description,
        resource_type,
        factor: 1,
        quantity: 1,
        unit: d.unit,
        unit_cost: 0,
        metadata: d.metadata,
      });
    },
    [addComponentMutation, assembly?.unit, defaultUnit, t],
  );

  const openCatalogPicker = useCallback((rt: ResourceType | null = null) => {
    setCatalogPickerType(rt);
    setCatalogPickerOpen(true);
    setAddMenuOpen(false);
  }, []);

  // M/L/E roll-up — sums by component.resource_type (falling back to the
  // legacy inference for un-typed rows so old assemblies still render
  // a useful breakdown until the user re-types them).
  const breakdown = useMemo(() => {
    const comps = assembly?.components ?? [];
    const totals: Record<string, number> = {};
    const counts: Record<string, number> = {};
    let grand = 0;
    for (const c of comps) {
      const t = c.resource_type ?? inferResourceType(c);
      // total is normalised to a number at the API boundary; coerce again
      // defensively so a stray string can never turn this sum into string
      // concatenation (which produced NaN and dropped whole categories).
      const lineTotal = Number(c.total) || 0;
      totals[t] = (totals[t] ?? 0) + lineTotal;
      counts[t] = (counts[t] ?? 0) + 1;
      grand += lineTotal;
    }
    const bid = Number(assembly?.bid_factor) || 1;
    return { totals, counts, grand, withBid: grand * bid };
  }, [assembly?.components, assembly?.bid_factor]);

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
    const currentTags: string[] = assembly.tags ?? [];
    if (currentTags.includes(tag)) {
      setTagInput('');
      return;
    }
    tagsMutation.mutate([...currentTags, tag]);
    setTagInput('');
  }, [tagInput, assembly, tagsMutation]);

  const handleRemoveTag = useCallback((tag: string) => {
    if (!assembly) return;
    const currentTags: string[] = assembly.tags ?? [];
    tagsMutation.mutate(currentTags.filter((t) => t !== tag));
  }, [assembly, tagsMutation]);

  // Decimals come from the assembly's own currency, not from a literal 2. An
  // assembly priced in CLP, JPY or KRW has no minor unit, so cents there are
  // not decoration, they are digits the currency cannot express - and this is
  // the number a unit price analysis carries into a tender.
  const fmtDigits = currencyFractionDigits(assembly?.currency);
  const fmt = (n: number) =>
    new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: fmtDigits,
      maximumFractionDigits: fmtDigits,
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
      <div className="w-full py-16 flex flex-col items-center gap-3 text-center animate-fade-in">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-surface-tertiary text-content-tertiary">
          <LayersIcon size={22} />
        </div>
        <p className="text-content-primary font-medium">{t('assemblies.not_found', { defaultValue: 'Assembly not found' })}</p>
        <p className="text-sm text-content-tertiary max-w-sm">
          {t('assemblies.not_found_hint', {
            defaultValue: 'This assembly may have been deleted, or you may not have access to it.',
          })}
        </p>
        <Button variant="secondary" size="sm" onClick={() => navigate('/assemblies')}>
          {t('assemblies.back_to_list', { defaultValue: 'Back to assemblies' })}
        </Button>
      </div>
    );
  }

  const components = assembly.components ?? [];
  // Parametric assembly state (Issue #365) — the parameter graph plus whether
  // any line drives its quantity from a formula. Gates the Preview button.
  const parameters = assembly.parameters ?? [];
  const hasParametrics =
    parameters.length > 0 || components.some((c) => !!c.quantity_formula);
  const computedTotal = components.reduce((sum, c) => sum + (Number(c.total) || 0), 0);
  // Prefer the server-persisted total_rate for the headline figure: it already
  // reflects the bid factor AND any per-type typed-formula adjustments
  // (waste / burden / fuel) that the naive client-side sum does not mirror.
  // Fall back to the local sum only when the server hasn't rolled up a rate
  // yet (e.g. a freshly created assembly with no persisted total).
  const localAdjustedTotal = computedTotal * assembly.bid_factor;
  const adjustedTotal = assembly.total_rate > 0 ? assembly.total_rate : localAdjustedTotal;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.assemblies', 'Assemblies'), to: '/assemblies' },
          { label: assembly.name },
        ]}
      />

      <DismissibleInfo
        storageKey="assembly-detail"
        title={t('assembly_detail.intro_title', { defaultValue: 'Build the rate component by component' })}
        links={[
          { label: t('nav.catalog', { defaultValue: 'Resource Catalog' }), onClick: () => navigate('/catalog') },
          { label: t('nav.assemblies', { defaultValue: 'Assemblies' }), onClick: () => navigate('/assemblies') },
        ]}
      >
        {t('assembly_detail.intro_body', {
          defaultValue:
            'Add, reorder and edit the material, labour and equipment lines of an assembly, each with its factor and unit, and watch the composite rate and the material, labour and equipment split recompute. The finished assembly is reusable across every BOQ.',
        })}
      </DismissibleInfo>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
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
            <span title={unitLabel(assembly.unit, t)}>{unitGlyph(assembly.unit)}</span>
            <span className="text-content-tertiary">/</span>
            {/* No silent EUR. An assembly stored without a currency has an
                unknown one, and printing "EUR" states something we do not
                know - the same guess MoneyDisplay was rewritten to stop
                making. Show the gap and say what it is. */}
            <span
              title={
                assembly.currency
                  ? undefined
                  : t('projects.currency_not_set', { defaultValue: 'Currency not set' })
              }
            >
              {assembly.currency || '—'}
            </span>
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
          {hasParametrics && (
            <Button
              variant="secondary"
              size="sm"
              icon={<Play size={15} />}
              onClick={() => setPreviewOpen(true)}
              className="border-oe-blue/30 text-oe-blue hover:bg-oe-blue-subtle"
              title={t('assembly.preview.button_title', {
                defaultValue: 'Preview how the parameters expand each line quantity and the rate',
              })}
            >
              {t('assembly.preview.button', { defaultValue: 'Preview' })}
            </Button>
          )}
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
            title={t('assemblies.from_database_title', {
              defaultValue: 'Pick a finished rate from the cost database (CWICR / …)',
            })}
          >
            {t('assemblies.from_database', { defaultValue: 'Cost DB' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Boxes size={15} />}
            onClick={() => openCatalogPicker(null)}
            className="border-emerald-300/30 text-emerald-700 hover:bg-emerald-50"
            title={t('assemblies.from_catalog_title', {
              defaultValue: 'Pick a typed resource (material / labor / equipment) from the catalog',
            })}
          >
            {t('assemblies.from_catalog', { defaultValue: 'From Catalog' })}
          </Button>
          {/* Typed Add — split button. Default click adds a material;
              chevron opens the menu with all six standard kinds. Mirrors
              what every professional estimator uses (M/L/E/S + operator
              + overhead) so the user thinks in those buckets from the
              first row instead of typing free-text and hoping the
              inference picks the right type. */}
          <div className="relative">
            <div className="inline-flex rounded-lg shadow-sm">
              <Button
                variant="primary"
                icon={<Plus size={16} />}
                onClick={() => handleAddComponent('material')}
                className="rounded-r-none"
              >
                {t('assemblies.add_material', { defaultValue: 'Add material' })}
              </Button>
              <button
                type="button"
                onClick={() => setAddMenuOpen((o) => !o)}
                aria-label={t('assemblies.add_other_aria', {
                  defaultValue: 'Choose a different resource type',
                })}
                aria-expanded={addMenuOpen}
                className="px-2 rounded-r-lg border-l border-white/20 bg-oe-blue text-white hover:bg-oe-blue-hover transition-colors inline-flex items-center"
              >
                <ChevronDown size={14} />
              </button>
            </div>
            {addMenuOpen && (
              <>
                <div
                  className="fixed inset-0 z-30"
                  onClick={() => setAddMenuOpen(false)}
                  aria-hidden
                />
                <div
                  role="menu"
                  className="absolute right-0 mt-1.5 w-56 rounded-lg border border-border-light bg-surface-elevated shadow-lg z-40 py-1 animate-fade-in"
                >
                  {(
                    [
                      { rt: 'material', icon: LayersIcon, color: 'text-emerald-700' },
                      { rt: 'labor', icon: HardHat, color: 'text-blue-700' },
                      { rt: 'equipment', icon: Wrench, color: 'text-amber-700' },
                      { rt: 'operator', icon: Hammer, color: 'text-orange-700' },
                      { rt: 'subcontractor', icon: Briefcase, color: 'text-violet-700' },
                      { rt: 'overhead', icon: Plus, color: 'text-slate-700' },
                    ] as const
                  ).map(({ rt, icon: Icon, color }) => (
                    <button
                      key={rt}
                      type="button"
                      role="menuitem"
                      onClick={() => handleAddComponent(rt)}
                      className="w-full px-3 py-1.5 text-left text-xs hover:bg-surface-secondary flex items-center gap-2"
                    >
                      <Icon size={14} className={color} />
                      {t(`assemblies.add_${rt}`, {
                        defaultValue: `Add ${rt}`,
                      })}
                    </button>
                  ))}
                  <div className="my-1 h-px bg-border-light" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => openCatalogPicker(null)}
                    className="w-full px-3 py-1.5 text-left text-xs hover:bg-surface-secondary flex items-center gap-2 text-emerald-700"
                  >
                    <Boxes size={14} />
                    {t('assemblies.from_catalog', { defaultValue: 'From Catalog…' })}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Tags Editor */}
      {showTagEditor && (
        <Card>
          <div className="flex items-center gap-2 flex-wrap">
            <Tag size={14} className="text-violet-500 shrink-0" />
            {(assembly.tags ?? []).map((tag) => (
              <Badge
                key={tag}
                variant="neutral"
                size="md"
                className="bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-400 border-violet-200/50 pr-1"
              >
                {tag}
                <button aria-label={t('common.remove_tag', { tag, defaultValue: 'Remove tag {{tag}}' })}
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

      {/* Parameters editor (Issue #365) — name the values that drive the
          recipe, then reference them from each line's quantity formula. */}
      <ParametersPanel assemblyId={assemblyId!} parameters={parameters} />

      {/* Two-column workspace: components table on the left, M/L/E
          breakdown summary on the right. The summary is sticky so it
          stays visible as the user scrolls a long component list — this
          is the same pattern professional estimating tools use to
          keep the rolled-up cost driver split always in view. */}
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px] gap-4">
      {/* Components Table */}
      <Card padding="none" className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-tertiary text-left">
                <th className="w-8 px-1 py-3" />
                <th className="px-4 py-3 font-medium text-content-secondary min-w-[240px]">
                  {t('boq.description')}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-20 text-center">
                  {t('assemblies.type', { defaultValue: 'Type' })}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-24 text-right">
                  <span className="inline-flex items-center justify-end gap-1">
                    {t('assemblies.factor', { defaultValue: 'Factor' })}
                    <Info
                      size={12}
                      className="text-content-tertiary cursor-help shrink-0"
                      aria-label={t('assemblies.factor_hint', {
                        defaultValue:
                          'Consumption per 1 unit of the assembly (e.g. 0.12 t rebar per m3 of concrete). Multiplied by Qty and Unit Cost to give the line total.',
                      })}
                    >
                      <title>
                        {t('assemblies.factor_hint', {
                          defaultValue:
                            'Consumption per 1 unit of the assembly (e.g. 0.12 t rebar per m3 of concrete). Multiplied by Qty and Unit Cost to give the line total.',
                        })}
                      </title>
                    </Info>
                  </span>
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
                  onMove={(delta) => handleDragEnd(idx, idx + delta)}
                  canMoveUp={idx > 0}
                  canMoveDown={idx < components.length - 1}
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
                  <td colSpan={9} className="px-4 py-10 text-center text-content-tertiary">
                    {t('assemblies.no_components_hint', { defaultValue: 'No components yet. Use the typed Add buttons (material / labor / equipment / …), pick a row from the cost database, or import a typed resource from the catalog.' })}
                  </td>
                </tr>
              )}
            </tbody>
            {components.length > 0 && (
              <tfoot>
                {assembly.bid_factor !== 1.0 && (
                  <tr className="border-t border-border-light bg-surface-tertiary/50">
                    <td colSpan={7} className="px-4 py-2.5 text-right text-sm text-content-secondary">
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
                    <td colSpan={7} className="px-4 py-2.5 text-right text-sm text-content-secondary">
                      {t('assemblies.bid_factor', { defaultValue: 'Bid Factor' })} ({assembly.bid_factor})
                    </td>
                    <td className="px-4 py-2.5 text-right text-sm text-content-secondary tabular-nums">
                      x {assembly.bid_factor}
                    </td>
                    <td />
                  </tr>
                )}
                <tr className="border-t-2 border-border bg-surface-tertiary font-semibold">
                  <td colSpan={7} className="px-4 py-3 text-right text-content-primary">
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
                      / {unitGlyph(assembly.unit)}
                    </span>
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </Card>

      {/* M/L/E breakdown sidebar */}
      <BreakdownSidebar
        breakdown={breakdown}
        currency={assembly.currency}
        unit={assembly.unit}
        bidFactor={assembly.bid_factor}
      />
      </div>

      {/* Catalog Resource Picker Modal */}
      {catalogPickerOpen && assemblyId && (
        <CatalogResourcePickerModal
          assemblyId={assemblyId}
          initialType={catalogPickerType}
          onClose={() => setCatalogPickerOpen(false)}
          onAdded={() => {
            setCatalogPickerOpen(false);
            queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
            addToast({
              type: 'success',
              title: t('assemblies.resource_added_from_catalog', {
                defaultValue: 'Resource added from catalog',
              }),
            });
          }}
        />
      )}

      {/* Expansion Preview Modal (Issue #365) */}
      {previewOpen && assemblyId && (
        <ExpandPreviewModal
          assemblyId={assemblyId}
          parameters={parameters}
          unit={assembly.unit}
          currency={assembly.currency || 'EUR'}
          onClose={() => setPreviewOpen(false)}
        />
      )}

      {/* Apply to BOQ Modal */}
      {applyModalOpen && (
        <ApplyToBOQModal
          assemblyId={assemblyId!}
          assemblyName={assembly.name}
          regionalFactors={assembly.regional_factors}
          parameters={parameters}
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
  /**
   * The item's own currency. `CostItemResponse` always sends it (it backfills
   * from the region for legacy CWICR rows), but it stays optional here so a
   * cached bundle that outlives a deploy degrades to the default digits
   * instead of rendering nothing.
   */
  currency?: string;
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
  const queryClient = useQueryClient();
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

  // Close handler that always refreshes the assembly data when components were added
  const handleClose = useCallback(() => {
    if (added.size > 0) {
      queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
    }
    onClose();
  }, [added.size, assemblyId, onClose, queryClient]);

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
        // Refresh the assembly data so components table updates in real time
        queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
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
    [assemblyId, addToast, t, queryClient],
  );

  // Each search hit prices in its own currency, so the digits are per row
  // rather than per list: a catalogue can hold a CLP rate next to a USD one.
  const fmt = (n: number, currency?: string) => {
    const digits = currencyFractionDigits(currency);
    return new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(n);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={handleClose}>
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
            <button
              onClick={handleClose}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="px-6 py-3 border-b border-border-light shrink-0">
          <div className="relative">
            <Search size={14} className="absolute start-3 top-1/2 -translate-y-1/2 text-content-quaternary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('assemblies.search_cost_placeholder', { defaultValue: 'Search cost items by description or code...' })}
              className="w-full h-9 ps-9 pe-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-purple-500/30 focus:border-purple-400"
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
                    {fmt(item.rate, item.currency)}
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


/* -- Resource type inference ----------------------------------------------- */

const LABOR_KEYWORDS = [
  'labor', 'labour', 'worker', 'crew', 'mason', 'carpenter', 'plumber',
  'electrician', 'fitter', 'welder', 'helper', 'operator', 'plasterer',
  'roofer', 'driver', 'arbeit', 'lohn', 'monteur', 'arbeiter',
];
const EQUIPMENT_KEYWORDS = [
  'equip', 'machine', 'crane', 'excavator', 'pump', 'mixer', 'truck',
  'scaffold', 'vibrator', 'compressor', 'generator', 'maschine', 'bagger',
  'kran', 'gerät',
];

function inferResourceType(component: AssemblyComponent): 'material' | 'labor' | 'equipment' {
  // Check explicit metadata first
  const meta = component.metadata;
  if (meta && typeof meta === 'object') {
    const rt = (meta as Record<string, unknown>).resource_type;
    if (rt === 'labor' || rt === 'equipment' || rt === 'material') return rt;
  }
  // Infer from description
  const desc = (component.description || '').toLowerCase();
  if (LABOR_KEYWORDS.some((kw) => desc.includes(kw))) return 'labor';
  if (EQUIPMENT_KEYWORDS.some((kw) => desc.includes(kw))) return 'equipment';
  return 'material';
}

const RESOURCE_TYPE_STYLES: Record<string, string> = {
  material: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400',
  labor: 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400',
  equipment: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400',
  operator: 'bg-orange-50 text-orange-700 dark:bg-orange-900/20 dark:text-orange-400',
  subcontractor: 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-400',
  overhead: 'bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:text-slate-300',
};

// Hex bar colours for the M/L/E summary panel — slightly more saturated
// than the badge backgrounds so the percent bar reads at-a-glance.
const RESOURCE_TYPE_BAR: Record<string, string> = {
  material: 'bg-emerald-500',
  labor: 'bg-blue-500',
  equipment: 'bg-amber-500',
  operator: 'bg-orange-500',
  subcontractor: 'bg-violet-500',
  overhead: 'bg-slate-500',
};

/* -- Component Row (inline editable) --------------------------------------
   Exported for the drag-affordance test; the page itself renders it directly. */

export function ComponentRow({
  component,
  isDragOver,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDragLeave,
  onMove,
  canMoveUp = false,
  canMoveDown = false,
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
  /**
   * Move this row one place up (-1) or down (+1).
   *
   * HTML5 drag and drop does not fire on touch, so on a tablet on site the
   * rows above could not be reordered at all: the grip was visible, draggable
   * was set, and nothing happened. This is the path that does not go through
   * the drag API, which also makes the list reorderable from the keyboard.
   */
  onMove?: (delta: -1 | 1) => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  onUpdate: (data: Partial<CreateComponentData>) => void;
  onDelete: () => void;
  fmt: (n: number) => string;
}) {
  const { t, i18n } = useTranslation();
  const { confirm, ...confirmProps } = useConfirm();
  const [editing, setEditing] = useState<string | null>(null);
  // Per-row "details" panel toggle. Closed by default to keep the
  // table compact; opens to reveal type-specific fields (waste_pct
  // for material, burden_pct for labor, fuel_cost for equipment …).
  const [detailsOpen, setDetailsOpen] = useState(false);
  // Locale/imperial-aware unit list (same primitive as the BOQ editor) so the
  // per-component unit dropdown offers imperial + locale tokens, not metric only.
  const unitOptions = useMemo(() => getUnitsForLocale(i18n.language), [i18n.language]);

  const handleBlur = (field: string, value: string) => {
    setEditing(null);
    const numFields = ['factor', 'quantity', 'unit_cost'];
    const update: Partial<CreateComponentData> = {
      [field]: numFields.includes(field) ? parseFloat(value) || 0 : value,
    };
    onUpdate(update);
  };

  // Patch a single metadata field in-place. The server merges by
  // replacing the whole `metadata` blob, so we always send the
  // existing dict + the changed key — that way unrelated fields
  // (vendor, notes, productivity) on the same row stay intact.
  const patchMeta = (key: string, raw: string) => {
    const parsed = raw === '' ? undefined : Number.isNaN(Number(raw)) ? raw : Number(raw);
    const next = { ...(component.metadata as Record<string, unknown>), [key]: parsed };
    onUpdate({ metadata: next as ComponentMetadata });
  };

  const resType = (component.resource_type ?? inferResourceType(component)) as ResourceType;
  const meta = (component.metadata ?? {}) as ComponentMetadata;

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
      {/* Drag handle. `draggable` sits on the whole row, so this is the affordance
          rather than the drag source. It rests at `secondary`, not `tertiary`:
          quaternary and tertiary are three hex units apart per channel in both
          themes (#696c78 vs #666b78 light, #8b8e9d vs #9499a8 dark), so the old
          resting colour and its hover step were the same grey to the eye. */}
      <td className="px-1 py-2.5 cursor-grab active:cursor-grabbing">
        <div className="flex flex-col items-center gap-0.5">
          {/* The two buttons are always rendered, never hover-revealed. A
              touch device has no hover, and this is the only reorder path it
              has, so hiding them until hover would hide the whole feature on
              exactly the device that needs it. They are sized for a fingertip
              and kept quiet at rest so they do not shout on the desktop. */}
          <button
            type="button"
            onClick={() => onMove?.(-1)}
            disabled={!onMove || !canMoveUp}
            aria-label={t('common.move_up', { defaultValue: 'Move up' })}
            data-testid="component-move-up"
            className="flex h-5 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary hover:text-content-primary disabled:pointer-events-none disabled:opacity-30"
          >
            <ChevronUp size={13} aria-hidden="true" />
          </button>
          <div
            className="flex items-center justify-center text-content-secondary group-hover:text-content-primary transition-colors"
            title={t('assemblies.drag_to_reorder', { defaultValue: 'Drag to reorder' })}
          >
            <GripVertical size={16} />
          </div>
          <button
            type="button"
            onClick={() => onMove?.(1)}
            disabled={!onMove || !canMoveDown}
            aria-label={t('common.move_down', { defaultValue: 'Move down' })}
            data-testid="component-move-down"
            className="flex h-5 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary hover:text-content-primary disabled:pointer-events-none disabled:opacity-30"
          >
            <ChevronDown size={13} aria-hidden="true" />
          </button>
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

      {/* Resource Type — editable. Falls back to legacy text-inference
          only when the column is null (i.e. legacy row pre-v2940). */}
      <td className="px-2 py-2.5 text-center">
        {(() => {
          const resType = (component.resource_type ?? inferResourceType(component)) as ResourceType;
          return (
            <select
              value={resType}
              onChange={(e) =>
                onUpdate({ resource_type: e.target.value as ResourceType })
              }
              className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold cursor-pointer border-none outline-none focus:ring-1 focus:ring-oe-blue/40 ${RESOURCE_TYPE_STYLES[resType] ?? RESOURCE_TYPE_STYLES.material}`}
              title={t('assemblies.type_change_hint', {
                defaultValue: 'Change resource type - recomputes the line total',
              })}
            >
              <option value="material">{t('assemblies.type_material', { defaultValue: 'Mat' })}</option>
              <option value="labor">{t('assemblies.type_labor', { defaultValue: 'Labor' })}</option>
              <option value="equipment">{t('assemblies.type_equipment', { defaultValue: 'Equip' })}</option>
              <option value="operator">{t('assemblies.type_operator', { defaultValue: 'Oper' })}</option>
              <option value="subcontractor">{t('assemblies.type_subcontractor', { defaultValue: 'Sub' })}</option>
              <option value="overhead">{t('assemblies.type_overhead', { defaultValue: 'OH' })}</option>
            </select>
          );
        })()}
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

      {/* Quantity — an "fx" badge flags a line whose quantity is computed
          from a parameter formula (Issue #365). The static value below stays
          editable and is the fallback when no parameters are supplied. */}
      <td className={`${cellClass} text-right`}>
        <div className="flex items-center justify-end gap-1">
          {component.quantity_formula ? (
            <span
              title={t('assemblies.qty_formula_badge_title', {
                defaultValue: 'Quantity is computed from a formula: {{formula}}',
                formula: component.quantity_formula,
              })}
              className="text-[9px] font-mono font-bold text-oe-blue bg-oe-blue/10 rounded px-1 py-0.5 leading-none cursor-help shrink-0"
            >
              fx
            </span>
          ) : null}
          <EditableCell
            value={String(component.quantity)}
            field="quantity"
            editing={editing}
            setEditing={setEditing}
            onBlur={handleBlur}
            className={`${inputClass} text-right`}
            type="number"
          />
        </div>
      </td>

      {/* Unit — dense cell keeps the compact glyph (m2 -> m²); the friendly
          localized name is a hover/aria title so the column stays narrow.
          Option value stays the canonical token, storage is unchanged. */}
      <td className="px-4 py-2.5 text-center">
        <select
          value={component.unit}
          onChange={(e) => onUpdate({ unit: e.target.value })}
          title={unitLabel(component.unit, t)}
          aria-label={t('boq.unit', { defaultValue: 'Unit' })}
          className="bg-transparent text-sm text-center cursor-pointer border-none outline-none text-content-secondary hover:text-content-primary"
        >
          {unitOptions.map((u) => (
            <option key={u} value={u} title={unitLabel(u, t)}>
              {unitGlyph(u)}
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

      {/* Row actions: details toggle + delete. Details opens a sub-row
          with type-specific extended fields (waste/burden/fuel/crew/…)
          — kept off-screen by default to keep the table compact. */}
      <td className="px-2 py-2.5">
        <div className="flex items-center justify-end gap-0.5">
          <button
            type="button"
            onClick={() => setDetailsOpen((o) => !o)}
            aria-expanded={detailsOpen}
            aria-label={t('assemblies.row_details_toggle', {
              defaultValue: 'Toggle component details',
            })}
            title={t('assemblies.row_details_title', {
              defaultValue: 'Show waste / burden / fuel / vendor fields for this row',
            })}
            className={clsx(
              'flex h-7 w-7 items-center justify-center rounded-md transition-all',
              detailsOpen
                ? 'text-oe-blue bg-oe-blue/10'
                : 'opacity-0 group-hover:opacity-100 text-content-tertiary hover:text-content-primary hover:bg-surface-secondary',
            )}
          >
            <ChevronDown
              size={14}
              className={clsx('transition-transform', detailsOpen && 'rotate-180')}
            />
          </button>
          <button aria-label={t('common.remove', { defaultValue: 'Remove' })}
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
        </div>
      </td>
    </tr>

    {/* Details sub-row — type-aware fields. Only the inputs that
        actually drive the typed total formula appear; for
        operator/subcontractor/overhead we show generic "vendor" +
        "notes" so any structured info still has a home.
        Spans the full table width and uses a soft surface so it
        visually nests under its parent without breaking the row
        rhythm. */}
    {detailsOpen && (
      <tr className="bg-surface-secondary/40 dark:bg-surface-secondary/30">
        <td colSpan={9} className="px-4 py-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {/* Quantity formula (Issue #365) — available for every line type.
                An arithmetic expression over the assembly's parameters drives
                the computed quantity; empty keeps the static Qty above. */}
            <DetailField
              label={t('assemblies.field_quantity_formula', {
                defaultValue: 'Quantity formula (fx)',
              })}
              hint={t('assemblies.field_quantity_formula_hint', {
                defaultValue:
                  'Compute this line from the assembly parameters, e.g. wall_area * 0.12. Leave empty to use the static quantity.',
              })}
              type="text"
              value={component.quantity_formula ?? ''}
              onCommit={(v) => {
                const trimmed = v.trim();
                onUpdate({ quantity_formula: trimmed === '' ? null : trimmed });
              }}
              span="sm:col-span-2 lg:col-span-4"
            />
            {resType === 'material' && (
              <>
                <DetailField
                  label={t('assemblies.field_waste', { defaultValue: 'Waste %' })}
                  hint={t('assemblies.field_waste_hint', {
                    defaultValue: 'Adds to the line total - e.g. 10 = +10%.',
                  })}
                  type="number"
                  value={meta.waste_pct ?? ''}
                  onCommit={(v) => patchMeta('waste_pct', v)}
                />
                <DetailField
                  label={t('assemblies.field_vendor', { defaultValue: 'Vendor' })}
                  type="text"
                  value={(meta.vendor as string | undefined) ?? ''}
                  onCommit={(v) => patchMeta('vendor', v)}
                />
              </>
            )}
            {resType === 'labor' && (
              <>
                <DetailField
                  label={t('assemblies.field_crew', { defaultValue: 'Crew size' })}
                  type="number"
                  value={meta.crew_size ?? ''}
                  onCommit={(v) => patchMeta('crew_size', v)}
                />
                <DetailField
                  label={t('assemblies.field_hours', { defaultValue: 'Hours' })}
                  hint={t('assemblies.field_hours_hint', {
                    defaultValue: 'Informational - use the Qty column to drive the total.',
                  })}
                  type="number"
                  value={meta.hours ?? ''}
                  onCommit={(v) => patchMeta('hours', v)}
                />
                <DetailField
                  label={t('assemblies.field_burden', { defaultValue: 'Burden %' })}
                  hint={t('assemblies.field_burden_hint', {
                    defaultValue: 'Benefits / overhead uplift - e.g. 30 = +30%.',
                  })}
                  type="number"
                  value={meta.burden_pct ?? ''}
                  onCommit={(v) => patchMeta('burden_pct', v)}
                />
                <DetailField
                  label={t('assemblies.field_skill', { defaultValue: 'Skill level' })}
                  type="text"
                  value={(meta.skill_level as string | undefined) ?? ''}
                  onCommit={(v) => patchMeta('skill_level', v)}
                />
              </>
            )}
            {resType === 'equipment' && (
              <>
                <DetailField
                  label={t('assemblies.field_rental_days', { defaultValue: 'Rental days' })}
                  type="number"
                  value={meta.rental_days ?? ''}
                  onCommit={(v) => patchMeta('rental_days', v)}
                />
                <DetailField
                  label={t('assemblies.field_hourly_rate', { defaultValue: 'Hourly rate' })}
                  type="number"
                  value={meta.hourly_rate ?? ''}
                  onCommit={(v) => patchMeta('hourly_rate', v)}
                />
                <DetailField
                  label={t('assemblies.field_fuel', { defaultValue: 'Fuel / day' })}
                  hint={t('assemblies.field_fuel_hint', {
                    defaultValue: 'Added on top of qty × unit cost: + days × fuel.',
                  })}
                  type="number"
                  value={meta.fuel_cost ?? ''}
                  onCommit={(v) => patchMeta('fuel_cost', v)}
                />
              </>
            )}
            {(resType === 'operator' ||
              resType === 'subcontractor' ||
              resType === 'overhead') && (
              <DetailField
                label={t('assemblies.field_vendor', { defaultValue: 'Vendor' })}
                type="text"
                value={(meta.vendor as string | undefined) ?? ''}
                onCommit={(v) => patchMeta('vendor', v)}
              />
            )}
            <DetailField
              label={t('assemblies.field_notes', { defaultValue: 'Notes' })}
              type="text"
              value={(meta.notes as string | undefined) ?? ''}
              onCommit={(v) => patchMeta('notes', v)}
              span="sm:col-span-2 lg:col-span-2"
            />
          </div>
        </td>
      </tr>
    )}
    <ConfirmDialog {...confirmProps} />
    </>
  );
}

/* -- DetailField (used by the per-row details sub-row) ----------------- */

function DetailField({
  label,
  hint,
  type,
  value,
  onCommit,
  span,
}: {
  label: string;
  hint?: string;
  type: 'number' | 'text';
  value: number | string;
  onCommit: (raw: string) => void;
  span?: string;
}) {
  const [draft, setDraft] = useState<string>(String(value ?? ''));
  // Re-sync when the upstream value changes (post-save round-trip
  // from the server merges into the cached row).
  const lastSeenRef = useRef<string>(String(value ?? ''));
  useEffect(() => {
    const next = String(value ?? '');
    if (next !== lastSeenRef.current) {
      lastSeenRef.current = next;
      setDraft(next);
    }
  }, [value]);
  return (
    <label className={clsx('block', span)}>
      <div className="text-[10px] uppercase tracking-wider text-content-tertiary font-semibold mb-1">
        {label}
      </div>
      <input
        type={type}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          if (draft !== lastSeenRef.current) {
            onCommit(draft);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          if (e.key === 'Escape') {
            setDraft(lastSeenRef.current);
            (e.target as HTMLInputElement).blur();
          }
        }}
        className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-oe-blue/40"
      />
      {hint && <div className="text-[10px] text-content-tertiary mt-1">{hint}</div>}
    </label>
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
  parameters,
  onClose,
}: {
  assemblyId: string;
  assemblyName: string;
  regionalFactors?: Record<string, string>;
  parameters?: AssemblyParameter[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  // Seed from the global project switcher so the modal opens on the project
  // the user is actually looking at, not an empty selector.
  const [projectId, setProjectId] = useState(activeProjectId ?? '');
  const [boqId, setBoqId] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [region, setRegion] = useState('');
  // Issue #365 — values for the assembly's `input` parameters. Seeded from
  // each parameter's stored default; the component quantity formulas are then
  // computed against the resolved values server-side at apply time.
  const inputParams = (parameters ?? []).filter((p) => p.kind === 'input');
  const [paramValues, setParamValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(inputParams.map((p) => [p.name, p.value ?? ''])),
  );

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Array<{ id: string; name: string }>>(),
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
    mutationFn: () => {
      const parameterValues =
        inputParams.length > 0
          ? Object.fromEntries(
              inputParams.map((p) => {
                const raw = paramValues[p.name];
                const n =
                  raw === undefined || raw.trim() === ''
                    ? Number(p.value ?? 0)
                    : Number(raw);
                return [p.name, Number.isFinite(n) ? n : 0];
              }),
            )
          : undefined;
      return assembliesApi.applyToBoq(assemblyId, boqId, parseFloat(quantity) || 1, parameterValues);
    },
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
        className="absolute inset-0 bg-black/70 backdrop-blur-lg"
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
              aria-label={t('common.close', { defaultValue: 'Close' })}
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
                {t('common.boq')}
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

            {/* Input parameters (Issue #365) — drive each line's quantity
                formula. Empty falls back to the stored default. */}
            {inputParams.length > 0 && (
              <div className="space-y-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2.5">
                <div className="text-xs font-medium text-content-primary">
                  {t('assembly.apply.params_title', { defaultValue: 'Parameter values' })}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {inputParams.map((p) => (
                    <label key={p.name} className="block">
                      <div className="text-[11px] text-content-secondary mb-1 flex items-center gap-1">
                        <span className="font-mono">{p.name}</span>
                        {p.unit && <span className="text-content-tertiary">({p.unit})</span>}
                      </div>
                      <input
                        type="number"
                        inputMode="decimal"
                        step="any"
                        value={paramValues[p.name] ?? ''}
                        onChange={(e) =>
                          setParamValues((prev) => ({ ...prev, [p.name]: e.target.value }))
                        }
                        placeholder={p.value ?? '0'}
                        className="w-full h-9 px-2.5 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary text-right tabular-nums focus:outline-none focus:ring-1 focus:ring-oe-blue/40"
                      />
                    </label>
                  ))}
                </div>
              </div>
            )}

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

/* -- M/L/E Breakdown Sidebar --------------------------------------------- */

/**
 * Sticky right-rail summary that mirrors the cost-driver split a
 * professional estimator expects (professional estimating tools show this
 * always-visible). Renders one bar per resource type used by the
 * assembly, plus a final "Total rate / unit" line that already includes
 * the bid factor uplift.
 */
function BreakdownSidebar({
  breakdown,
  currency,
  unit,
  bidFactor,
}: {
  breakdown: {
    totals: Record<string, number>;
    counts: Record<string, number>;
    grand: number;
    withBid: number;
  };
  currency: string;
  unit: string;
  bidFactor: number;
}) {
  const { t } = useTranslation();
  // Every figure in this sidebar is printed next to `currency`, so the digits
  // have to come from it. The resource split is the part of a unit price
  // analysis a reviewer reads line by line.
  const breakdownDigits = currencyFractionDigits(currency);
  const fmt = (n: number) =>
    new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: breakdownDigits,
      maximumFractionDigits: breakdownDigits,
    }).format(n);
  const order: ResourceType[] = [
    'material',
    'labor',
    'equipment',
    'operator',
    'subcontractor',
    'overhead',
  ];
  const labelFor = (rt: string) =>
    rt === 'material'
      ? t('assemblies.type_material_full', { defaultValue: 'Material' })
      : rt === 'labor'
        ? t('assemblies.type_labor_full', { defaultValue: 'Labor' })
        : rt === 'equipment'
          ? t('assemblies.type_equipment_full', { defaultValue: 'Equipment' })
          : rt === 'operator'
            ? t('assemblies.type_operator_full', { defaultValue: 'Operator' })
            : rt === 'subcontractor'
              ? t('assemblies.type_subcontractor_full', { defaultValue: 'Subcontract' })
              : t('assemblies.type_overhead_full', { defaultValue: 'Overhead' });
  // Show every category that has components, not only the priced ones, so a
  // line you just added is visible (at 0) while you type its price in, and a
  // category with several components never silently drops out.
  const rows = order.filter(
    (rt) => (breakdown.totals[rt] ?? 0) > 0 || (breakdown.counts[rt] ?? 0) > 0,
  );
  return (
    <Card padding="md" className="xl:sticky xl:top-4 self-start">
      <div className="flex items-center gap-1.5 mb-3">
        <LayersIcon size={14} className="text-oe-blue" />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('assemblies.breakdown_title', { defaultValue: 'Cost Drivers' })}
        </h3>
      </div>
      {rows.length === 0 ? (
        <div className="text-xs text-content-tertiary leading-snug">
          {t('assemblies.breakdown_empty', {
            defaultValue: 'Add components to see how the rate is built up by material, labor and equipment.',
          })}
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((rt) => {
              const value = breakdown.totals[rt] ?? 0;
              const pct = breakdown.grand > 0 ? (value / breakdown.grand) * 100 : 0;
              return (
                <div key={rt}>
                  <div className="flex items-baseline justify-between gap-2 text-xs mb-1">
                    <span className="font-medium text-content-secondary">{labelFor(rt)}</span>
                    <span className="text-content-tertiary tabular-nums">
                      {fmtPercent(pct, 0)}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-surface-tertiary overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${RESOURCE_TYPE_BAR[rt]}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="text-[11px] text-content-tertiary tabular-nums mt-0.5">
                    {fmt(value)} {currency}
                  </div>
                </div>
              );
            })}
        </div>
      )}
      {rows.length > 0 && (
        <div className="mt-4 pt-3 border-t border-border-light space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-content-tertiary">
              {t('assemblies.breakdown_subtotal', { defaultValue: 'Subtotal' })}
            </span>
            <span className="font-medium text-content-secondary tabular-nums">
              {fmt(breakdown.grand)} {currency}
            </span>
          </div>
          {bidFactor !== 1.0 && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-content-tertiary">
                {t('assemblies.breakdown_bid', { defaultValue: 'Bid factor' })}
              </span>
              <span className="font-medium text-content-secondary tabular-nums">
                ×{bidFactor}
              </span>
            </div>
          )}
          <div className="flex items-center justify-between text-sm pt-1">
            <span className="font-semibold text-content-primary">
              {t('assemblies.breakdown_total', { defaultValue: 'Total / unit' })}
            </span>
            <span className="font-bold text-content-primary tabular-nums">
              {fmt(breakdown.withBid)} {currency} / {unitGlyph(unit)}
            </span>
          </div>
        </div>
      )}
    </Card>
  );
}

/* -- Catalog Resource Picker Modal --------------------------------------- */

interface CatalogResourceItem {
  id: string;
  resource_code: string;
  name: string;
  resource_type: string;
  category: string;
  unit: string;
  base_price: number;
  currency: string;
  region: string | null;
}

/**
 * Modal that lets the user search the global resource catalog
 * (`/v1/catalog/`) by type + free text and add the picked rows as
 * typed components. Auto-fills description, unit, unit_cost,
 * resource_type, currency from the catalog row — no double entry.
 */
function CatalogResourcePickerModal({
  assemblyId,
  initialType,
  onClose,
  onAdded,
}: {
  assemblyId: string;
  initialType: ResourceType | null;
  onClose: () => void;
  onAdded: () => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [type, setType] = useState<ResourceType | ''>(initialType ?? '');
  const [adding, setAdding] = useState<string | null>(null);

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (query.trim()) params.set('q', query.trim());
    if (type) params.set('resource_type', type);
    params.set('limit', '40');
    return params.toString();
  }, [query, type]);

  const search = useQuery({
    queryKey: ['catalog-search-for-assembly', queryString],
    queryFn: () =>
      apiGet<{ items: CatalogResourceItem[]; total: number }>(
        `/v1/catalog/?${queryString}`,
      ),
  });

  const addMut = useMutation({
    mutationFn: async (item: CatalogResourceItem) => {
      setAdding(item.id);
      try {
        await assembliesApi.addComponent(assemblyId, {
          catalog_resource_id: item.id,
          description: item.name,
          resource_type: (item.resource_type as ResourceType) || 'material',
          factor: 1,
          quantity: 1,
          unit: item.unit || 'pcs',
          unit_cost: item.base_price || 0,
        });
      } finally {
        setAdding(null);
      }
    },
    onSuccess: onAdded,
  });

  const items = search.data?.items ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 overflow-y-auto">
      <Card className="w-full max-w-3xl mt-12">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Boxes size={16} className="text-emerald-600" />
            <h2 className="text-base font-semibold">
              {t('assemblies.catalog_picker_title', {
                defaultValue: 'Add resource from catalog',
              })}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-content-tertiary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={18} />
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search
              size={14}
              className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
            />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('assemblies.catalog_search_ph', {
                defaultValue: 'Search materials / labor / equipment…',
              })}
              className="w-full ps-8 pe-3 py-1.5 text-sm rounded-lg border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-emerald-400"
              autoFocus
            />
          </div>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as ResourceType | '')}
            className="text-xs rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 cursor-pointer"
          >
            <option value="">
              {t('assemblies.catalog_type_any', { defaultValue: 'All types' })}
            </option>
            <option value="material">{t('assemblies.type_material_full', { defaultValue: 'Material' })}</option>
            <option value="labor">{t('assemblies.type_labor_full', { defaultValue: 'Labor' })}</option>
            <option value="equipment">{t('assemblies.type_equipment_full', { defaultValue: 'Equipment' })}</option>
            <option value="operator">{t('assemblies.type_operator_full', { defaultValue: 'Operator' })}</option>
          </select>
        </div>

        {/* Results */}
        <div className="max-h-[60vh] overflow-y-auto -mx-4 px-4 border-t border-border-light">
          {search.isLoading && (
            <div className="py-10 text-center text-content-tertiary">
              <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          )}
          {!search.isLoading && items.length === 0 && (
            <div className="py-10 text-center text-content-tertiary text-sm">
              {t('assemblies.catalog_no_results', {
                defaultValue: 'No matching resources. Try a broader search or import a regional catalog from /catalog.',
              })}
            </div>
          )}
          {items.length > 0 && (
            <table className="w-full text-sm mt-2">
              <thead>
                <tr className="text-xs text-content-tertiary text-left">
                  <th className="py-2 font-medium">
                    {t('assemblies.catalog_col_name', { defaultValue: 'Name' })}
                  </th>
                  <th className="py-2 font-medium w-20 text-center">
                    {t('assemblies.type', { defaultValue: 'Type' })}
                  </th>
                  <th className="py-2 font-medium w-16 text-center">
                    {t('boq.unit', { defaultValue: 'Unit' })}
                  </th>
                  <th className="py-2 font-medium w-28 text-right">
                    {t('assemblies.unit_cost', { defaultValue: 'Unit Cost' })}
                  </th>
                  <th className="py-2 w-16" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {items.map((it) => (
                  <tr key={it.id} className="hover:bg-surface-secondary/50">
                    <td className="py-2 pr-2">
                      <div className="font-medium text-content-primary truncate max-w-[260px]">
                        {it.name}
                      </div>
                      <div className="text-[11px] text-content-tertiary truncate max-w-[260px]">
                        {it.resource_code}{it.region ? ` · ${it.region}` : ''}
                      </div>
                    </td>
                    <td className="py-2 text-center">
                      <span
                        className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                          RESOURCE_TYPE_STYLES[it.resource_type] ?? RESOURCE_TYPE_STYLES.material
                        }`}
                      >
                        {it.resource_type}
                      </span>
                    </td>
                    <td className="py-2 text-center text-content-secondary">{it.unit}</td>
                    <td className="py-2 text-right tabular-nums text-content-primary">
                      {new Intl.NumberFormat(getNumberLocale(), {
                        minimumFractionDigits: currencyFractionDigits(it.currency),
                        maximumFractionDigits: currencyFractionDigits(it.currency),
                      }).format(it.base_price || 0)}{' '}
                      <span className="text-[10px] text-content-tertiary">{it.currency}</span>
                    </td>
                    <td className="py-2 text-right">
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => addMut.mutate(it)}
                        disabled={adding === it.id}
                        icon={
                          adding === it.id ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <Plus size={12} />
                          )
                        }
                      >
                        {t('common.add', { defaultValue: 'Add' })}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </div>
  );
}
