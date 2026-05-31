// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ModelLinkPanel — "live model→BOQ quantity binding" (option C rewrite).
 *
 * Two coordinated concerns, cleanly separated:
 *
 *   1. BINDING (which BIM elements) — the element selector creates/deletes
 *      rows in `oe_bim_boq_link` directly (via the bim_hub links API). Each
 *      checkbox toggle persists immediately; a tri-state "select all
 *      (filtered)" binds/unbinds the whole filtered set in one call.
 *
 *   2. PROJECTION (how to compute the quantity) — the shared
 *      {@link ProjectionEditor} (value vs. formula, aggregation, live
 *      preview). Saving persists the projection on the position's
 *      QuantityLink (upserted server-side, one per position).
 *
 * Neither action mutates the position quantity: that still requires the
 * explicit BOQ-wide "Refresh from model" + per-row Apply (propose → human
 * confirms). Every string goes through i18n `t()`.
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Cuboid, Search, Link2, Check } from 'lucide-react';
import { WideModal, Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchBIMModels,
  fetchBIMElements,
  listLinks,
  createLink,
  deleteLink,
  bulkCreateLinks,
  enrichElementsFromParquet,
} from '@/features/bim/api';
import { boqApi, type QuantityAggregation } from './api';
import { ProjectionEditor, safeParamName, type ProjectionValue } from './ProjectionEditor';

export interface ModelLinkPanelProps {
  /** The position being bound. */
  positionId: string;
  /** Ordinal shown in the subtitle. */
  positionOrdinal: string;
  /** Owning project (to list its BIM models). */
  projectId: string;
  onClose: () => void;
}

const DEFAULT_PROJECTION: ProjectionValue = {
  projection_kind: 'simple',
  quantity_field: '',
  aggregation: 'sum',
  formula: '',
};

export function ModelLinkPanel({
  positionId,
  positionOrdinal,
  projectId,
  onClose,
}: ModelLinkPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [selectedModelId, setSelectedModelId] = useState<string>('');
  const [filter, setFilter] = useState('');
  const [projection, setProjection] = useState<ProjectionValue>(DEFAULT_PROJECTION);

  /* ── Existing binding (oe_bim_boq_link) for this position ────────── */
  const { data: linksResp, isLoading: linksLoading } = useQuery({
    queryKey: ['bim-element-links', positionId],
    queryFn: () => listLinks(positionId),
  });
  const elementLinks = useMemo(() => linksResp?.items ?? [], [linksResp]);

  /** bim_element_id → link id, for delete + checked lookups. */
  const linkByElement = useMemo(() => {
    const m = new Map<string, string>();
    for (const lnk of elementLinks) m.set(lnk.bim_element_id, lnk.id);
    return m;
  }, [elementLinks]);

  /* ── Existing projection (QuantityLink) — initialise the editor ──── */
  const { data: quantityLinks } = useQuery({
    queryKey: ['quantity-links', positionId],
    queryFn: () => boqApi.getQuantityLinks(positionId),
  });
  const existingProjection = quantityLinks?.[0];

  // Seed the editor + model from the saved projection exactly once.
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    if (seeded || !existingProjection) return;
    setProjection({
      projection_kind:
        existingProjection.projection_kind === 'formula' ? 'formula' : 'simple',
      quantity_field: existingProjection.quantity_field ?? '',
      aggregation: (existingProjection.aggregation as QuantityAggregation) ?? 'sum',
      formula: existingProjection.formula ?? '',
    });
    if (existingProjection.model_id) setSelectedModelId(existingProjection.model_id);
    setSeeded(true);
  }, [seeded, existingProjection]);

  /* ── Models + elements ───────────────────────────────────────────── */
  const { data: modelsResp, isLoading: modelsLoading } = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: !!projectId,
  });
  const models = modelsResp?.items ?? [];

  const { data: elementsResp, isLoading: elementsLoading } = useQuery({
    queryKey: ['bim-elements', selectedModelId],
    queryFn: () => fetchBIMElements(selectedModelId, { limit: 500 }),
    enabled: !!selectedModelId,
  });
  const elements = elementsResp?.items ?? [];

  const filteredElements = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return elements;
    return elements.filter((e) =>
      `${e.name ?? ''} ${e.element_type ?? ''} ${e.stable_id ?? ''}`
        .toLowerCase()
        .includes(q),
    );
  }, [elements, filter]);

  /** Canonical params available across the BOUND elements (chips + field).
   *  Mirrors the backend's `_element_formula_names` exactly: every key in
   *  `quantities` or `properties` whose value coerces to a finite number —
   *  including numeric *strings* like `qto_wallbasequantities_volume: "12.5"`
   *  (raw IFC QTO sets serialise as strings). Using a strict `typeof
   *  'number'` test here is what previously hid all the string-valued IFC
   *  parameters and left only the ~5 canonical float quantities. */
  const availableParams = useMemo(() => {
    const keys = new Set<string>();
    const isNumericLike = (v: unknown) =>
      typeof v === 'number' ? Number.isFinite(v) : Number.isFinite(parseFloat(String(v)));
    for (const e of elements) {
      if (!linkByElement.has(e.id)) continue;
      for (const [k, v] of Object.entries(e.quantities ?? {})) {
        if (isNumericLike(v)) keys.add(safeParamName(k));
      }
      for (const [k, v] of Object.entries(e.properties ?? {})) {
        if (isNumericLike(v)) keys.add(safeParamName(k));
      }
    }
    return Array.from(keys).sort();
  }, [elements, linkByElement]);

  const boundCount = elementLinks.length;

  /* ── Binding mutations (live, per-toggle) ────────────────────────── */
  const invalidateBinding = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['bim-element-links', positionId] });
    if (selectedModelId)
      queryClient.invalidateQueries({ queryKey: ['model-boq-links', selectedModelId] });
  }, [queryClient, positionId, selectedModelId]);

  const onBindError = useCallback(
    (e: Error) =>
      addToast({
        type: 'error',
        title: t('boq.model_link_bind_failed', { defaultValue: 'Could not update binding' }),
        message: e.message,
      }),
    [addToast, t],
  );

  const bindMutation = useMutation({
    mutationFn: (elementId: string) =>
      createLink({ boq_position_id: positionId, bim_element_id: elementId }),
    onSuccess: invalidateBinding,
    onError: onBindError,
  });

  const unbindMutation = useMutation({
    mutationFn: (linkId: string) => deleteLink(linkId),
    onSuccess: invalidateBinding,
    onError: onBindError,
  });

  const toggleElement = useCallback(
    (elementId: string) => {
      const linkId = linkByElement.get(elementId);
      if (linkId) unbindMutation.mutate(linkId);
      else bindMutation.mutate(elementId);
    },
    [linkByElement, bindMutation, unbindMutation],
  );

  /* ── Tri-state "select all (filtered)" ───────────────────────────── */
  const filteredBoundCount = useMemo(
    () => filteredElements.filter((e) => linkByElement.has(e.id)).length,
    [filteredElements, linkByElement],
  );
  const allFilteredBound =
    filteredElements.length > 0 && filteredBoundCount === filteredElements.length;
  const someFilteredBound = filteredBoundCount > 0 && !allFilteredBound;

  const bulkBindMutation = useMutation({
    mutationFn: (elementIds: string[]) =>
      bulkCreateLinks({ boq_position_id: positionId, bim_element_ids: elementIds }),
    onSuccess: invalidateBinding,
    onError: onBindError,
  });

  const bulkUnbindMutation = useMutation({
    mutationFn: async (linkIds: string[]) => {
      for (const id of linkIds) await deleteLink(id);
    },
    onSuccess: invalidateBinding,
    onError: onBindError,
  });

  const bulkBusy = bulkBindMutation.isPending || bulkUnbindMutation.isPending;

  const toggleSelectAllFiltered = useCallback(() => {
    if (allFilteredBound) {
      const linkIds = filteredElements
        .map((e) => linkByElement.get(e.id))
        .filter((x): x is string => !!x);
      bulkUnbindMutation.mutate(linkIds);
    } else {
      const toBind = filteredElements
        .filter((e) => !linkByElement.has(e.id))
        .map((e) => e.id);
      if (toBind.length > 0) bulkBindMutation.mutate(toBind);
    }
  }, [allFilteredBound, filteredElements, linkByElement, bulkBindMutation, bulkUnbindMutation]);

  /* ── Save projection ─────────────────────────────────────────────── */
  const saveProjection = useMutation({
    mutationFn: () =>
      boqApi.createQuantityLink(positionId, {
        model_id: selectedModelId,
        projection_kind: projection.projection_kind,
        quantity_field:
          projection.projection_kind === 'simple' && projection.aggregation !== 'count'
            ? projection.quantity_field
            : '',
        aggregation: projection.aggregation,
        formula: projection.projection_kind === 'formula' ? projection.formula : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quantity-links', positionId] });
      addToast({
        type: 'success',
        title: t('boq.projection_saved', { defaultValue: 'Projection saved' }),
        message: t('boq.projection_saved_hint', {
          defaultValue:
            'The quantity is not changed yet - use “Refresh from model” then Apply to pull it in.',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('boq.projection_save_failed', { defaultValue: 'Could not save projection' }),
        message: e.message,
      }),
  });

  // Backfill the model's elements with the full numeric param set from the
  // Parquet (the params the 3D viewer shows), so the formula chips expose
  // every parameter — not just the curated import subset.
  const enrichParams = useMutation({
    mutationFn: () => enrichElementsFromParquet(selectedModelId),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['bim-elements', selectedModelId] });
      addToast({
        type: 'success',
        title: t('boq.enrich_params_done', { defaultValue: 'BIM parameters loaded' }),
        message: t('boq.enrich_params_done_hint', {
          defaultValue: '{{enriched}} element(s) enriched with {{added}} parameter(s).',
          enriched: r.elements_enriched,
          added: r.properties_added,
        } as Record<string, unknown>),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('boq.enrich_params_failed', { defaultValue: 'Could not load BIM parameters' }),
        message: e.message,
      }),
  });

  const projectionValid =
    !!selectedModelId &&
    (projection.projection_kind === 'formula'
      ? projection.formula.trim().length > 0
      : projection.aggregation === 'count' || !!projection.quantity_field);

  /* ── i18n strings with interpolation (widened per codebase convention) */
  const subtitleText = t('boq.model_link_subtitle', {
    defaultValue: 'Position {{ordinal}} - bind its quantity to BIM model elements',
    ordinal: positionOrdinal,
  } as Record<string, unknown>);
  const boundLabel = t('boq.model_link_bound_count', {
    defaultValue: '{{count}} element(s) bound',
    count: boundCount,
  } as Record<string, unknown>);

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('boq.model_link_title', { defaultValue: 'Model link' })}
      subtitle={subtitleText}
      size="xl"
      footer={
        <div className="flex justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!projectionValid || saveProjection.isPending}
            onClick={() => saveProjection.mutate()}
          >
            {saveProjection.isPending ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <Link2 size={14} className="mr-1" />
            )}
            {t('boq.projection_save', { defaultValue: 'Save projection' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        {/* Model picker */}
        <label className="block">
          <span className="block text-2xs font-medium text-content-secondary mb-1">
            {t('boq.model_link_model', { defaultValue: 'BIM model' })}
          </span>
          {modelsLoading ? (
            <div className="flex items-center gap-2 text-xs text-content-tertiary">
              <Loader2 size={14} className="animate-spin" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          ) : models.length === 0 ? (
            <p className="text-xs text-content-tertiary">
              {t('boq.model_link_no_models', {
                defaultValue: 'This project has no BIM models yet.',
              })}
            </p>
          ) : (
            <select
              value={selectedModelId}
              onChange={(e) => {
                setSelectedModelId(e.target.value);
                setFilter('');
              }}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            >
              <option value="">
                {t('boq.model_link_pick_model', { defaultValue: '- Select a model -' })}
              </option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          )}
        </label>

        {/* Element binding */}
        {selectedModelId && (
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-2xs font-medium text-content-secondary">
                {t('boq.model_link_binding', { defaultValue: 'Bound elements' })}
                {linksLoading ? null : (
                  <span className="ml-1.5 text-content-tertiary">· {boundLabel}</span>
                )}
              </span>
            </div>

            {/* Filter + select-all-filtered */}
            <div className="flex items-center gap-2 mb-2">
              <div className="relative flex-1">
                <Search
                  size={13}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-quaternary"
                />
                <input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder={t('boq.model_link_filter', { defaultValue: 'Filter elements…' })}
                  className="w-full rounded-lg border border-border-light bg-surface-primary pl-8 pr-3 py-1.5 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                />
              </div>
              {filteredElements.length > 0 && (
                <button
                  type="button"
                  onClick={toggleSelectAllFiltered}
                  disabled={bulkBusy}
                  className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border-light text-xs text-content-secondary hover:bg-surface-secondary/60 disabled:opacity-50 transition-colors"
                >
                  {bulkBusy ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <span
                      className={`inline-flex h-3.5 w-3.5 items-center justify-center rounded border ${
                        allFilteredBound
                          ? 'bg-oe-blue border-oe-blue text-white'
                          : someFilteredBound
                            ? 'bg-oe-blue/30 border-oe-blue'
                            : 'border-border-light'
                      }`}
                    >
                      {allFilteredBound ? (
                        <Check size={10} />
                      ) : someFilteredBound ? (
                        <span className="h-0.5 w-2 bg-oe-blue rounded" />
                      ) : null}
                    </span>
                  )}
                  {allFilteredBound
                    ? t('boq.model_link_deselect_all', { defaultValue: 'Unbind all' })
                    : t('boq.model_link_select_all', { defaultValue: 'Bind all (filtered)' })}
                </button>
              )}
            </div>

            {elementsLoading ? (
              <div className="flex items-center gap-2 text-xs text-content-tertiary py-3">
                <Loader2 size={14} className="animate-spin" />
                {t('common.loading', { defaultValue: 'Loading…' })}
              </div>
            ) : filteredElements.length === 0 ? (
              <p className="text-xs text-content-tertiary py-2">
                {elements.length === 0
                  ? t('boq.model_link_no_elements', { defaultValue: 'This model has no elements.' })
                  : t('boq.model_link_no_matches', { defaultValue: 'No elements match the filter.' })}
              </p>
            ) : (
              <div className="max-h-56 overflow-y-auto rounded-lg border border-border-light divide-y divide-border-light">
                {filteredElements.map((el) => {
                  const checked = linkByElement.has(el.id);
                  return (
                    <label
                      key={el.id}
                      className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-surface-secondary/50"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleElement(el.id)}
                        className="accent-oe-blue"
                      />
                      <Cuboid size={13} className="text-content-tertiary shrink-0" />
                      <span className="text-xs text-content-primary truncate">
                        {el.name || el.element_type || el.stable_id}
                      </span>
                      <span className="text-2xs text-content-tertiary ml-auto shrink-0">
                        {el.element_type}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Projection editor */}
        {selectedModelId && boundCount > 0 && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs font-semibold text-content-secondary">
                {t('boq.model_link_rule', { defaultValue: 'Quantity rule' })}
              </h4>
              <button
                type="button"
                onClick={() => enrichParams.mutate()}
                disabled={enrichParams.isPending}
                title={t('boq.enrich_params_hint', {
                  defaultValue:
                    'Load every numeric parameter from the BIM model (the ones shown in the 3D viewer) so the formula can use them.',
                })}
                className="shrink-0 inline-flex items-center gap-1.5 px-2 py-1 rounded-lg border border-border-light text-2xs text-content-secondary hover:bg-surface-secondary/60 disabled:opacity-50 transition-colors"
              >
                {enrichParams.isPending ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Cuboid size={12} />
                )}
                {t('boq.enrich_params', { defaultValue: 'Load all BIM parameters' })}
              </button>
            </div>
            <ProjectionEditor
              positionId={positionId}
              availableParams={availableParams}
              value={projection}
              onChange={setProjection}
              livePreview
            />
          </div>
        )}
      </div>
    </WideModal>
  );
}
