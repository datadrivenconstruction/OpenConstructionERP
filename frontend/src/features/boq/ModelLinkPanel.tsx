// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ModelLinkPanel — Feature 1 ("live model→BOQ quantity binding").
 *
 * Lets the user bind a BOQ position's quantity to a set of BIM model
 * elements (an extraction rule, e.g. "sum of area_m2 across these
 * elements → quantity"), see existing links, and delete them. Creating
 * a link NEVER mutates the quantity — that requires the explicit
 * BOQ-wide refresh + per-row Apply in {@link ModelLinkReviewPanel}
 * (the architecture guide §7 — propose, human confirms).
 *
 * Every string goes through i18n `t()`; no hardcoded UI text.
 */

import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Cuboid, Trash2, Link2 } from 'lucide-react';
import { WideModal, Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { fetchBIMModels, fetchBIMElements } from '@/features/bim/api';
import { boqApi, type CreateQuantityLinkData, type QuantityAggregation } from './api';

export interface ModelLinkPanelProps {
  /** The position being bound. */
  positionId: string;
  /** Ordinal shown in the subtitle. */
  positionOrdinal: string;
  /** Owning project (to list its BIM models). */
  projectId: string;
  onClose: () => void;
}

const AGGREGATIONS: QuantityAggregation[] = ['sum', 'max', 'min', 'count', 'first'];

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
  const [selectedElementIds, setSelectedElementIds] = useState<Set<string>>(new Set());
  const [quantityField, setQuantityField] = useState<string>('');
  const [aggregation, setAggregation] = useState<QuantityAggregation>('sum');

  const { data: links, isLoading: linksLoading } = useQuery({
    queryKey: ['quantity-links', positionId],
    queryFn: () => boqApi.getQuantityLinks(positionId),
  });

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

  // Canonical quantity keys available across the currently-selected
  // elements — drives the "which quantity" picker without hardcoding a
  // fixed list (a model can expose any canonical key).
  const availableFields = useMemo(() => {
    const keys = new Set<string>();
    for (const e of elements) {
      if (!selectedElementIds.has(e.stable_id ?? e.id)) continue;
      for (const k of Object.keys(e.quantities ?? {})) keys.add(k);
    }
    return Array.from(keys).sort();
  }, [elements, selectedElementIds]);

  const toggleElement = useCallback((stableId: string) => {
    setSelectedElementIds((prev) => {
      const next = new Set(prev);
      if (next.has(stableId)) next.delete(stableId);
      else next.add(stableId);
      return next;
    });
  }, []);

  const createMutation = useMutation({
    mutationFn: (data: CreateQuantityLinkData) =>
      boqApi.createQuantityLink(positionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quantity-links', positionId] });
      setSelectedElementIds(new Set());
      setQuantityField('');
      addToast({
        type: 'success',
        title: t('boq.model_link_created', { defaultValue: 'Model link created' }),
        message: t('boq.model_link_created_hint', {
          defaultValue:
            'The quantity is not changed yet - use “Refresh from model” then Apply to pull it in.',
        }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.model_link_failed', { defaultValue: 'Could not create model link' }),
        message: e.message,
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (linkId: string) => boqApi.deleteQuantityLink(positionId, linkId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quantity-links', positionId] });
      addToast({
        type: 'success',
        title: t('boq.model_link_deleted', { defaultValue: 'Model link removed' }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.model_link_delete_failed', {
          defaultValue: 'Could not remove model link',
        }),
        message: e.message,
      });
    },
  });

  const canSubmit =
    !!selectedModelId &&
    selectedElementIds.size > 0 &&
    (aggregation === 'count' || !!quantityField) &&
    !createMutation.isPending;

  const handleSubmit = useCallback(() => {
    createMutation.mutate({
      model_id: selectedModelId,
      element_stable_ids: Array.from(selectedElementIds),
      quantity_field: aggregation === 'count' ? 'count' : quantityField,
      aggregation,
    });
  }, [createMutation, selectedModelId, selectedElementIds, quantityField, aggregation]);

  const statusVariant = (status: string): 'neutral' | 'blue' | 'success' | 'warning' | 'error' => {
    if (status === 'active') return 'success';
    if (status === 'stale') return 'warning';
    if (status === 'broken') return 'error';
    return 'neutral';
  };

  // i18next's typed `t()` rejects an inline options object that carries
  // a custom interpolation variable alongside `defaultValue` (only
  // `count` is special-cased). The codebase convention (see
  // LinkedPositionsModal) is to widen the options to
  // `Record<string, unknown>` so the strict overload is not selected.
  const subtitleText = t('boq.model_link_subtitle', {
    defaultValue: 'Position {{ordinal}} - bind its quantity to BIM model elements',
    ordinal: positionOrdinal,
  } as Record<string, unknown>);
  const elementsLabel = t('boq.model_link_elements', {
    defaultValue: 'Elements ({{selected}} selected)',
    selected: selectedElementIds.size,
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
            disabled={!canSubmit}
            onClick={handleSubmit}
          >
            {createMutation.isPending ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <Link2 size={14} className="mr-1" />
            )}
            {t('boq.model_link_create', { defaultValue: 'Create link' })}
          </Button>
        </div>
      }
    >
      {/* Existing links */}
      <div className="mb-5">
        <h4 className="text-xs font-semibold text-content-secondary mb-2">
          {t('boq.model_link_existing', { defaultValue: 'Existing links' })}
        </h4>
        {linksLoading ? (
          <div className="flex items-center gap-2 text-xs text-content-tertiary py-3">
            <Loader2 size={14} className="animate-spin" />
            {t('common.loading', { defaultValue: 'Loading…' })}
          </div>
        ) : !links || links.length === 0 ? (
          <p className="text-xs text-content-tertiary py-2">
            {t('boq.model_link_none', {
              defaultValue: 'No model links yet for this position.',
            })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light rounded-lg border border-border-light">
            {links.map((lnk) => (
              <li
                key={lnk.id}
                className="flex items-center justify-between gap-3 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-content-primary truncate">
                      {lnk.aggregation}({lnk.quantity_field}) → {lnk.target_field}
                    </span>
                    <Badge variant={statusVariant(lnk.status)} size="sm">
                      {t(`boq.model_link_status_${lnk.status}`, {
                        defaultValue: lnk.status,
                      })}
                    </Badge>
                  </div>
                  <p className="text-2xs text-content-tertiary mt-0.5">
                    {t('boq.model_link_elem_count', {
                      defaultValue: '{{count}} element(s)',
                      count: lnk.element_stable_ids.length,
                    })}
                    {lnk.source_model_version
                      ? ` · ${t('boq.model_link_version', {
                          defaultValue: 'model v{{v}}',
                          v: lnk.source_model_version,
                        } as Record<string, unknown>)}`
                      : ''}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate(lnk.id)}
                  disabled={deleteMutation.isPending}
                  aria-label={t('boq.model_link_delete', {
                    defaultValue: 'Delete link',
                  })}
                  className="shrink-0 flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error/10 transition-colors disabled:opacity-50"
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* New link builder */}
      <div className="space-y-4">
        <h4 className="text-xs font-semibold text-content-secondary">
          {t('boq.model_link_new', { defaultValue: 'New link' })}
        </h4>

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
                setSelectedElementIds(new Set());
                setQuantityField('');
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

        {/* Element selector */}
        {selectedModelId && (
          <div>
            <span className="block text-2xs font-medium text-content-secondary mb-1">
              {elementsLabel}
            </span>
            {elementsLoading ? (
              <div className="flex items-center gap-2 text-xs text-content-tertiary py-3">
                <Loader2 size={14} className="animate-spin" />
                {t('common.loading', { defaultValue: 'Loading…' })}
              </div>
            ) : elements.length === 0 ? (
              <p className="text-xs text-content-tertiary py-2">
                {t('boq.model_link_no_elements', {
                  defaultValue: 'This model has no elements.',
                })}
              </p>
            ) : (
              <div className="max-h-56 overflow-y-auto rounded-lg border border-border-light divide-y divide-border-light">
                {elements.map((el) => {
                  const sid = el.stable_id ?? el.id;
                  const checked = selectedElementIds.has(sid);
                  return (
                    <label
                      key={el.id}
                      className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-surface-secondary/50"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleElement(sid)}
                        className="accent-oe-blue"
                      />
                      <Cuboid size={13} className="text-content-tertiary shrink-0" />
                      <span className="text-xs text-content-primary truncate">
                        {el.name || el.element_type || sid}
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

        {/* Aggregation + quantity field */}
        {selectedElementIds.size > 0 && (
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-2xs font-medium text-content-secondary mb-1">
                {t('boq.model_link_aggregation', { defaultValue: 'Aggregation' })}
              </span>
              <select
                value={aggregation}
                onChange={(e) =>
                  setAggregation(e.target.value as QuantityAggregation)
                }
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              >
                {AGGREGATIONS.map((a) => (
                  <option key={a} value={a}>
                    {t(`boq.model_link_agg_${a}`, { defaultValue: a })}
                  </option>
                ))}
              </select>
            </label>
            {aggregation !== 'count' && (
              <label className="block">
                <span className="block text-2xs font-medium text-content-secondary mb-1">
                  {t('boq.model_link_quantity_field', {
                    defaultValue: 'Quantity field',
                  })}
                </span>
                <select
                  value={quantityField}
                  onChange={(e) => setQuantityField(e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                >
                  <option value="">
                    {t('boq.model_link_pick_field', {
                      defaultValue: '- Select a quantity -',
                    })}
                  </option>
                  {availableFields.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        )}
      </div>
    </WideModal>
  );
}
