/**
 * BIMQuantityRulesPage — rule-based bulk linking of BIM elements to BOQ positions.
 *
 * Route: /bim/rules
 *
 * Lets the user define patterns like "category=Walls AND storey=01 Entry Level"
 * and map them to a BOQ position (either existing or auto-created). Applying a
 * rule creates `BOQElementLink` rows in bulk against a selected BIM model.
 *
 * Reads the active project from the global project-context store.
 */

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Pencil,
  Trash2,
  Copy,
  Play,
  Eye,
  SlidersHorizontal,
  X,
  Check,
  AlertCircle,
  Loader2,
  Boxes,
  BookOpen,
  Sparkles,
  ChevronRight,
  ClipboardCheck,
  Shield,
  Search,
} from 'lucide-react';
import clsx from 'clsx';

import { Badge, ConfirmDialog, EmptyState } from '@/shared/ui';
import BIMRequirementsImport from './BIMRequirementsImport';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  applyQuantityMaps,
  createQuantityMap,
  fetchBIMModels,
  listQuantityMaps,
  patchQuantityMap,
  type BIMQuantityMap,
  type CreateBIMQuantityMapRequest,
  type QuantityMapApplyResult,
  type QuantityMapTarget,
} from './api';
import { boqApi, type BOQ, type Position } from '@/features/boq/api';
import {
  type BIMFormat,
  getCategoriesForFormat,
  getFilterParamsForFormat,
  getPropertyNamesForFormat,
  CONSTRAINT_TYPES,
  CONSTRAINT_TYPE_LABELS,
  type ConstraintType,
} from './bimConstants';
import {
  fetchRequirementSets,
  fetchRequirementSetDetail,
  createRequirementSet,
  deleteRequirementSet,
  addRequirement,
  updateRequirement,
  deleteRequirement,
  type Requirement,
  type RequirementSet,
  type AddRequirementPayload,
  type UpdateRequirementPayload,
} from '@/features/requirements/api';

/* ── Form state types ─────────────────────────────────────────────────── */

type TargetKind = 'existing' | 'auto_create';

interface PropertyRow {
  key: string;
  value: string;
}

interface RuleFormState {
  name: string;
  element_type_filter: string;
  property_filter: PropertyRow[];
  quantity_source: string;
  custom_quantity_source: string;
  multiplier: string;
  unit: string;
  waste_factor_pct: string;
  target_kind: TargetKind;
  target_boq_id: string;
  target_position_id: string;
  /** Default unit rate for auto-created positions, persisted into
   *  ``boq_target.unit_rate``. */
  target_unit_rate: string;
  is_active: boolean;
}

const QUANTITY_SOURCE_PRESETS = [
  'area_m2',
  'volume_m3',
  'length_m',
  'weight_kg',
  'count',
  'custom',
] as const;

type QuantitySourcePreset = (typeof QUANTITY_SOURCE_PRESETS)[number];

function blankForm(): RuleFormState {
  return {
    name: '',
    element_type_filter: '',
    property_filter: [],
    quantity_source: 'area_m2',
    custom_quantity_source: '',
    multiplier: '1',
    unit: 'm²',
    waste_factor_pct: '0',
    target_kind: 'auto_create',
    target_boq_id: '',
    target_position_id: '',
    target_unit_rate: '',
    is_active: true,
  };
}

function presetFromQuantitySource(source: string): QuantitySourcePreset {
  if ((QUANTITY_SOURCE_PRESETS as readonly string[]).includes(source)) {
    return source as QuantitySourcePreset;
  }
  return 'custom';
}

function toFormState(rule: BIMQuantityMap, boqPositionLookup: Map<string, string>): RuleFormState {
  const props: PropertyRow[] = Object.entries(rule.property_filter ?? {}).map(([key, value]) => ({
    key,
    value: String(value),
  }));
  const preset = presetFromQuantitySource(rule.quantity_source);
  const target = rule.boq_target ?? {};
  const existingPositionId = target.position_id ?? '';
  const boqId = existingPositionId ? (boqPositionLookup.get(existingPositionId) ?? '') : '';
  const targetKind: TargetKind = existingPositionId ? 'existing' : 'auto_create';
  return {
    name: rule.name,
    element_type_filter: rule.element_type_filter ?? '',
    property_filter: props,
    quantity_source: preset,
    custom_quantity_source: preset === 'custom' ? rule.quantity_source : '',
    multiplier: rule.multiplier ?? '1',
    unit: rule.unit ?? 'm²',
    waste_factor_pct: rule.waste_factor_pct ?? '0',
    target_kind: targetKind,
    target_boq_id: boqId,
    target_position_id: existingPositionId,
    target_unit_rate: typeof target.unit_rate === 'string' ? target.unit_rate : '',
    is_active: rule.is_active,
  };
}

function buildPayload(
  form: RuleFormState,
  projectId: string | null,
): CreateBIMQuantityMapRequest {
  const propertyFilter: Record<string, string> = {};
  for (const row of form.property_filter) {
    const k = row.key.trim();
    if (!k) continue;
    propertyFilter[k] = row.value;
  }
  const quantitySource =
    form.quantity_source === 'custom'
      ? form.custom_quantity_source.trim() || 'count'
      : form.quantity_source;

  const boqTarget: QuantityMapTarget = {};
  if (form.target_kind === 'existing' && form.target_position_id) {
    boqTarget.position_id = form.target_position_id;
  } else {
    boqTarget.auto_create = true;
    // Persist a default unit_rate when the user has prefilled one
    // (typically via the "Suggest from CWICR" button).  The backend
    // apply path reads this from boq_target.unit_rate and creates the
    // new Position with a non-zero rate so the user doesn't have to
    // chase up the BOQ editor afterwards.
    const trimmedRate = form.target_unit_rate.trim();
    if (trimmedRate) {
      boqTarget.unit_rate = trimmedRate;
    }
  }

  return {
    org_id: null,
    project_id: projectId,
    name: form.name.trim(),
    name_translations: null,
    element_type_filter: form.element_type_filter.trim(),
    property_filter: Object.keys(propertyFilter).length > 0 ? propertyFilter : null,
    quantity_source: quantitySource,
    multiplier: form.multiplier.trim() || '1',
    unit: form.unit.trim() || 'm²',
    waste_factor_pct: form.waste_factor_pct.trim() || '0',
    boq_target: Object.keys(boqTarget).length > 0 ? boqTarget : null,
    is_active: form.is_active,
    metadata: {},
  };
}

/* ── Rule editor modal ────────────────────────────────────────────────── */

interface RuleEditorModalProps {
  open: boolean;
  onClose: () => void;
  initial: RuleFormState;
  mode: 'create' | 'edit' | 'duplicate';
  projectId: string | null;
  onSubmit: (payload: CreateBIMQuantityMapRequest) => void;
  submitting: boolean;
}

function RuleEditorModal({
  open,
  onClose,
  initial,
  mode,
  projectId,
  onSubmit,
  submitting,
}: RuleEditorModalProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState<RuleFormState>(initial);

  useEffect(() => {
    if (open) setForm(initial);
  }, [open, initial]);

  // BOQs for the active project
  const boqsQuery = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => (projectId ? boqApi.list(projectId) : Promise.resolve<BOQ[]>([])),
    enabled: !!projectId && open && form.target_kind === 'existing',
  });

  const positionsQuery = useQuery({
    queryKey: ['boq-positions', form.target_boq_id],
    queryFn: () =>
      form.target_boq_id
        ? boqApi.get(form.target_boq_id)
        : Promise.resolve(null),
    enabled: !!form.target_boq_id && open && form.target_kind === 'existing',
  });

  const [positionSearch, setPositionSearch] = useState('');

  const filteredPositions = useMemo<Position[]>(() => {
    const all = positionsQuery.data?.positions ?? [];
    const q = positionSearch.trim().toLowerCase();
    if (!q) return all.slice(0, 200);
    return all
      .filter(
        (p) =>
          p.ordinal.toLowerCase().includes(q) ||
          p.description.toLowerCase().includes(q),
      )
      .slice(0, 200);
  }, [positionsQuery.data, positionSearch]);

  const updateField = useCallback(
    <K extends keyof RuleFormState>(key: K, value: RuleFormState[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleAddPropertyRow = useCallback(() => {
    setForm((prev) => ({
      ...prev,
      property_filter: [...prev.property_filter, { key: '', value: '' }],
    }));
  }, []);

  const handleRemovePropertyRow = useCallback((index: number) => {
    setForm((prev) => ({
      ...prev,
      property_filter: prev.property_filter.filter((_, i) => i !== index),
    }));
  }, []);

  const handleUpdatePropertyRow = useCallback(
    (index: number, field: 'key' | 'value', value: string) => {
      setForm((prev) => ({
        ...prev,
        property_filter: prev.property_filter.map((row, i) =>
          i === index ? { ...row, [field]: value } : row,
        ),
      }));
    },
    [],
  );

  const handleSubmit = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (!form.name.trim()) return;
      onSubmit(buildPayload(form, projectId));
    },
    [form, projectId, onSubmit],
  );

  if (!open) return null;

  const modeTitle =
    mode === 'edit'
      ? t('bim_rules.edit_rule', { defaultValue: 'Edit rule' })
      : mode === 'duplicate'
        ? t('bim_rules.duplicate_rule', { defaultValue: 'Duplicate rule' })
        : t('bim_rules.new_rule', { defaultValue: 'New rule' });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        className="relative flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-light px-5 py-4">
          <div className="flex items-center gap-2">
            <SlidersHorizontal size={18} className="text-oe-blue" />
            <h2 className="text-base font-semibold text-content-primary">{modeTitle}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-content-secondary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
            {/* Name */}
            <div>
              <label
                htmlFor="rule-name"
                className="mb-1 block text-xs font-medium text-content-secondary"
              >
                {t('bim_rules.field_name', { defaultValue: 'Name' })}
                <span className="ml-0.5 text-red-500">*</span>
              </label>
              <input
                id="rule-name"
                type="text"
                required
                value={form.name}
                onChange={(e) => updateField('name', e.target.value)}
                placeholder={t('bim_rules.field_name_placeholder', {
                  defaultValue: 'e.g. Exterior walls — concrete',
                })}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
              />
            </div>

            {/* Element type filter */}
            <div>
              <label
                htmlFor="rule-element-type"
                className="mb-1 block text-xs font-medium text-content-secondary"
              >
                {t('bim_rules.field_element_type', { defaultValue: 'Element type filter' })}
              </label>
              <input
                id="rule-element-type"
                type="text"
                value={form.element_type_filter}
                onChange={(e) => updateField('element_type_filter', e.target.value)}
                placeholder={t('bim_rules.field_element_type_placeholder', {
                  defaultValue: 'Wall*, IfcWall, Curtainwall*',
                })}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 font-mono text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
              />
              <p className="mt-1 text-[11px] text-content-tertiary">
                {t('bim_rules.field_element_type_hint', {
                  defaultValue: 'Wildcards supported. Leave empty to match any element type.',
                })}
              </p>
            </div>

            {/* Property filter */}
            <div>
              <div className="mb-1 flex items-center justify-between">
                <label className="text-xs font-medium text-content-secondary">
                  {t('bim_rules.field_property_filter', { defaultValue: 'Property filter' })}
                </label>
                <button
                  type="button"
                  onClick={handleAddPropertyRow}
                  className="flex items-center gap-1 text-[11px] font-medium text-oe-blue hover:underline"
                >
                  <Plus size={12} />
                  {t('bim_rules.add_property', { defaultValue: 'Add property' })}
                </button>
              </div>
              {form.property_filter.length === 0 ? (
                <p className="rounded-lg border border-dashed border-border-light px-3 py-2 text-[11px] text-content-tertiary">
                  {t('bim_rules.no_properties', {
                    defaultValue: 'No property filters. Click "Add property" to add a key/value pair.',
                  })}
                </p>
              ) : (
                <div className="space-y-2">
                  {form.property_filter.map((row, index) => (
                    <div key={`prop-${row.key}-${index}`} className="flex items-center gap-2">
                      <input
                        type="text"
                        value={row.key}
                        onChange={(e) =>
                          handleUpdatePropertyRow(index, 'key', e.target.value)
                        }
                        placeholder={t('bim_rules.property_key', { defaultValue: 'Property key' })}
                        className="flex-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 font-mono text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                      />
                      <span className="text-xs text-content-tertiary">=</span>
                      <input
                        type="text"
                        value={row.value}
                        onChange={(e) =>
                          handleUpdatePropertyRow(index, 'value', e.target.value)
                        }
                        placeholder={t('bim_rules.property_value', { defaultValue: 'Value (wildcards OK)' })}
                        className="flex-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 font-mono text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => handleRemovePropertyRow(index)}
                        className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-red-600"
                        aria-label={t('common.remove', { defaultValue: 'Remove' })}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Quantity source + multiplier + unit + waste */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="rule-qsrc"
                  className="mb-1 block text-xs font-medium text-content-secondary"
                >
                  {t('bim_rules.field_quantity_source', { defaultValue: 'Quantity source' })}
                </label>
                <select
                  id="rule-qsrc"
                  value={form.quantity_source}
                  onChange={(e) => updateField('quantity_source', e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
                >
                  <option value="area_m2">area_m2</option>
                  <option value="volume_m3">volume_m3</option>
                  <option value="length_m">length_m</option>
                  <option value="weight_kg">weight_kg</option>
                  <option value="count">count</option>
                  <option value="custom">
                    {t('bim_rules.custom_property', { defaultValue: 'Custom (property:xxx)' })}
                  </option>
                </select>
              </div>

              <div>
                <label
                  htmlFor="rule-unit"
                  className="mb-1 block text-xs font-medium text-content-secondary"
                >
                  {t('bim_rules.field_unit', { defaultValue: 'Unit' })}
                </label>
                <input
                  id="rule-unit"
                  type="text"
                  value={form.unit}
                  onChange={(e) => updateField('unit', e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
                />
              </div>
            </div>

            {form.quantity_source === 'custom' && (
              <div>
                <label
                  htmlFor="rule-custom-src"
                  className="mb-1 block text-xs font-medium text-content-secondary"
                >
                  {t('bim_rules.field_custom_source', {
                    defaultValue: 'Custom source (e.g. property:net_area)',
                  })}
                </label>
                <input
                  id="rule-custom-src"
                  type="text"
                  value={form.custom_quantity_source}
                  onChange={(e) => updateField('custom_quantity_source', e.target.value)}
                  placeholder="property:net_area"
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 font-mono text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
                />
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="rule-mult"
                  className="mb-1 block text-xs font-medium text-content-secondary"
                >
                  {t('bim_rules.field_multiplier', { defaultValue: 'Multiplier' })}
                </label>
                <input
                  id="rule-mult"
                  type="number"
                  step="0.001"
                  min="0"
                  value={form.multiplier}
                  onChange={(e) => updateField('multiplier', e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
                />
              </div>

              <div>
                <label
                  htmlFor="rule-waste"
                  className="mb-1 block text-xs font-medium text-content-secondary"
                >
                  {t('bim_rules.field_waste', { defaultValue: 'Waste factor %' })}
                </label>
                <input
                  id="rule-waste"
                  type="number"
                  step="0.1"
                  min="0"
                  value={form.waste_factor_pct}
                  onChange={(e) => updateField('waste_factor_pct', e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
                />
              </div>
            </div>

            {/* Target */}
            <div>
              <label className="mb-2 block text-xs font-medium text-content-secondary">
                {t('bim_rules.field_target', { defaultValue: 'Target' })}
              </label>
              <div className="mb-3 flex gap-4">
                <label className="flex items-center gap-2 text-xs text-content-primary">
                  <input
                    type="radio"
                    name="target-kind"
                    checked={form.target_kind === 'existing'}
                    onChange={() => updateField('target_kind', 'existing')}
                    className="accent-oe-blue"
                  />
                  {t('bim_rules.target_existing', { defaultValue: 'Link to existing BOQ position' })}
                </label>
                <label className="flex items-center gap-2 text-xs text-content-primary">
                  <input
                    type="radio"
                    name="target-kind"
                    checked={form.target_kind === 'auto_create'}
                    onChange={() => updateField('target_kind', 'auto_create')}
                    className="accent-oe-blue"
                  />
                  {t('bim_rules.target_auto_create', { defaultValue: 'Auto-create position' })}
                </label>
              </div>

              {form.target_kind === 'existing' && (
                <div className="space-y-2 rounded-lg border border-border-light bg-surface-secondary p-3">
                  <div>
                    <label
                      htmlFor="rule-boq"
                      className="mb-1 block text-[11px] font-medium text-content-secondary"
                    >
                      {t('bim_rules.pick_boq', { defaultValue: 'BOQ' })}
                    </label>
                    <select
                      id="rule-boq"
                      value={form.target_boq_id}
                      onChange={(e: ChangeEvent<HTMLSelectElement>) => {
                        updateField('target_boq_id', e.target.value);
                        updateField('target_position_id', '');
                      }}
                      className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                    >
                      <option value="">
                        {t('bim_rules.select_boq', { defaultValue: 'Select a BOQ…' })}
                      </option>
                      {(boqsQuery.data ?? []).map((b) => (
                        <option key={b.id} value={b.id}>
                          {b.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  {form.target_boq_id && (
                    <div>
                      <label
                        htmlFor="rule-pos-search"
                        className="mb-1 block text-[11px] font-medium text-content-secondary"
                      >
                        {t('bim_rules.pick_position', { defaultValue: 'Position' })}
                      </label>
                      <input
                        id="rule-pos-search"
                        type="text"
                        value={positionSearch}
                        onChange={(e) => setPositionSearch(e.target.value)}
                        placeholder={t('bim_rules.search_positions', {
                          defaultValue: 'Search by ordinal or description…',
                        })}
                        className="mb-2 w-full rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                      />
                      <div className="max-h-40 overflow-y-auto rounded-lg border border-border-light bg-surface-primary">
                        {positionsQuery.isLoading ? (
                          <div className="p-3 text-center text-[11px] text-content-tertiary">
                            <Loader2 size={14} className="mx-auto animate-spin" />
                          </div>
                        ) : filteredPositions.length === 0 ? (
                          <div className="p-3 text-center text-[11px] text-content-tertiary">
                            {t('bim_rules.no_positions', {
                              defaultValue: 'No positions found.',
                            })}
                          </div>
                        ) : (
                          filteredPositions.map((p) => (
                            <button
                              key={p.id}
                              type="button"
                              onClick={() => updateField('target_position_id', p.id)}
                              className={clsx(
                                'flex w-full items-center gap-2 border-b border-border-light px-3 py-1.5 text-left text-[11px] last:border-b-0 hover:bg-surface-secondary',
                                form.target_position_id === p.id && 'bg-oe-blue/10',
                              )}
                            >
                              <span className="font-mono text-content-tertiary">{p.ordinal}</span>
                              <span className="flex-1 truncate text-content-primary">
                                {p.description}
                              </span>
                              {form.target_position_id === p.id && (
                                <Check size={12} className="text-oe-blue" />
                              )}
                            </button>
                          ))
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {form.target_kind === 'auto_create' && (
                <div className="space-y-2 rounded-lg border border-dashed border-border-light p-3">
                  <p className="text-[11px] text-content-tertiary">
                    {t('bim_rules.auto_create_hint', {
                      defaultValue:
                        "On apply, a new BOQ position will be created using this rule's name as the description. Quantities will be computed at apply time.",
                    })}
                  </p>
                  {/* Unit-rate prefill — calls the cost suggestion endpoint
                      with the rule's filter context to get the top CWICR
                      match.  When set, the apply path uses this rate so
                      the new position lands fully priced. */}
                  <div className="flex items-end gap-2">
                    <div className="flex-1">
                      <label
                        htmlFor="rule-unit-rate"
                        className="mb-1 block text-[11px] font-medium text-content-secondary"
                      >
                        {t('bim_rules.field_default_rate', {
                          defaultValue: 'Default unit rate',
                        })}
                      </label>
                      <input
                        id="rule-unit-rate"
                        type="text"
                        value={form.target_unit_rate}
                        onChange={(e) => updateField('target_unit_rate', e.target.value)}
                        placeholder="0.00"
                        className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none tabular-nums"
                      />
                    </div>
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          const { apiPost } = await import('@/shared/lib/api');
                          // Construct a synthetic element from the rule's
                          // filters so the cost ranker has something to
                          // match against.  We pull element_type from
                          // element_type_filter, plus material/family
                          // from the property_filter rows when present.
                          const props: Record<string, string> = {};
                          for (const row of form.property_filter) {
                            if (row.key.trim()) props[row.key.trim()] = row.value;
                          }
                          const suggestions = await apiPost<
                            Array<{
                              cost_item_id: string;
                              code: string;
                              description: string;
                              unit: string;
                              unit_rate: number | string;
                              score: number;
                            }>
                          >('/api/v1/costs/suggest-for-element/', {
                            element_type: form.element_type_filter || null,
                            name: form.name || null,
                            properties: Object.keys(props).length > 0 ? props : null,
                            limit: 1,
                          });
                          const top = suggestions?.[0];
                          if (top) {
                            const rateStr =
                              typeof top.unit_rate === 'number'
                                ? String(top.unit_rate)
                                : String(top.unit_rate);
                            updateField('target_unit_rate', rateStr);
                          }
                        } catch (err) {
                          // Soft-fail — the cost endpoint is optional and
                          // shouldn't block rule editing if it errors.
                          // eslint-disable-next-line no-console
                          console.warn('Cost suggestion failed', err);
                        }
                      }}
                      className="inline-flex items-center gap-1 rounded-lg border border-oe-blue/40 bg-oe-blue/5 px-2 py-1.5 text-[11px] font-medium text-oe-blue hover:bg-oe-blue/10"
                      title={t('bim_rules.suggest_rate_title', {
                        defaultValue:
                          'Use the rule filter to look up a matching CWICR cost item and prefill its unit rate',
                      })}
                    >
                      <Sparkles size={11} />
                      {t('bim_rules.suggest_rate', {
                        defaultValue: 'Suggest from CWICR',
                      })}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Is active */}
            <div>
              <label className="flex items-center gap-2 text-xs text-content-primary">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => updateField('is_active', e.target.checked)}
                  className="accent-oe-blue"
                />
                {t('bim_rules.field_is_active', { defaultValue: 'Rule is active' })}
              </label>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border-light bg-surface-secondary px-5 py-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-tertiary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type="submit"
              disabled={submitting || !form.name.trim()}
              className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-oe-blue-dark disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting && <Loader2 size={12} className="animate-spin" />}
              {t('common.save', { defaultValue: 'Save' })}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ── Preview modal ────────────────────────────────────────────────────── */

interface PreviewModalProps {
  open: boolean;
  onClose: () => void;
  result: QuantityMapApplyResult | null;
  loading: boolean;
}

function PreviewModal({ open, onClose, result, loading }: PreviewModalProps) {
  const { t } = useTranslation();
  if (!open) return null;
  const sample = result?.results.slice(0, 20) ?? [];
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-border-light px-5 py-4">
          <div className="flex items-center gap-2">
            <Eye size={18} className="text-oe-blue" />
            <h2 className="text-base font-semibold text-content-primary">
              {t('bim_rules.preview_title', { defaultValue: 'Dry-run preview' })}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-content-secondary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {loading && (
            <div className="flex items-center justify-center py-8 text-sm text-content-secondary">
              <Loader2 size={18} className="mr-2 animate-spin" />
              {t('bim_rules.preview_loading', { defaultValue: 'Running dry-run…' })}
            </div>
          )}
          {!loading && result && (
            <>
              <div className="mb-4 grid grid-cols-4 gap-3">
                <StatCard
                  label={t('bim_rules.stat_matched', { defaultValue: 'Matched elements' })}
                  value={result.matched_elements}
                />
                <StatCard
                  label={t('bim_rules.stat_rules', { defaultValue: 'Rules applied' })}
                  value={result.rules_applied}
                />
                <StatCard
                  label={t('bim_rules.stat_links', { defaultValue: 'Links that would be created' })}
                  value={result.links_created}
                />
                <StatCard
                  label={t('bim_rules.stat_positions', { defaultValue: 'Positions that would be created' })}
                  value={result.positions_created}
                />
              </div>

              <div className="mb-2 text-xs font-medium text-content-secondary">
                {t('bim_rules.sample_results', { defaultValue: 'Sample results (first 20)' })}
              </div>
              <div className="overflow-hidden rounded-lg border border-border-light">
                <table className="w-full text-left text-[11px]">
                  <thead className="bg-surface-secondary text-content-secondary">
                    <tr>
                      <th className="px-2 py-1.5 font-medium">
                        {t('bim_rules.col_stable_id', { defaultValue: 'Stable ID' })}
                      </th>
                      <th className="px-2 py-1.5 font-medium">
                        {t('bim_rules.col_element_type', { defaultValue: 'Type' })}
                      </th>
                      <th className="px-2 py-1.5 font-medium">
                        {t('bim_rules.col_rule', { defaultValue: 'Rule' })}
                      </th>
                      <th className="px-2 py-1.5 font-medium">
                        {t('bim_rules.col_source', { defaultValue: 'Source' })}
                      </th>
                      <th className="px-2 py-1.5 text-right font-medium">
                        {t('bim_rules.col_raw', { defaultValue: 'Raw' })}
                      </th>
                      <th className="px-2 py-1.5 text-right font-medium">
                        {t('bim_rules.col_adjusted', { defaultValue: 'Adjusted' })}
                      </th>
                      <th className="px-2 py-1.5 font-medium">
                        {t('bim_rules.col_unit', { defaultValue: 'Unit' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sample.length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-2 py-3 text-center text-content-tertiary">
                          {t('bim_rules.no_sample', { defaultValue: 'No matches.' })}
                        </td>
                      </tr>
                    )}
                    {sample.map((item, idx) => (
                      <tr
                        key={`${item.element_id}-${idx}`}
                        className="border-t border-border-light text-content-primary"
                      >
                        <td className="truncate px-2 py-1 font-mono text-content-tertiary">
                          {item.stable_id}
                        </td>
                        <td className="truncate px-2 py-1">{item.element_type}</td>
                        <td className="truncate px-2 py-1">{item.rule_name}</td>
                        <td className="truncate px-2 py-1 font-mono text-content-tertiary">
                          {item.quantity_source}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">
                          {item.raw_quantity.toFixed(3)}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">
                          {item.adjusted_quantity.toFixed(3)}
                        </td>
                        <td className="px-2 py-1">{item.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-content-primary">{value}</div>
    </div>
  );
}

/* ── Tabs ─────────────────────────────────────────────────────────────── */

type RulesTab = 'quantity_rules' | 'requirements';

/* ── Requirements Rule Editor (three-column) ─────────────────────────── */

interface RequirementRuleForm {
  format: BIMFormat;
  /** Column 1: main filter parameter + value */
  filter_param: string;
  filter_value: string;
  /** Column 2: parameter to check */
  check_param: string;
  /** Column 3: constraint type + value/pattern */
  constraint_type: ConstraintType;
  constraint_value: string;
  /** Extra fields */
  category: string;
  priority: string;
  source_ref: string;
  notes: string;
}

function blankRequirementForm(): RequirementRuleForm {
  return {
    format: 'revit',
    filter_param: 'Category',
    filter_value: '',
    check_param: '',
    constraint_type: 'min',
    constraint_value: '',
    category: 'structural',
    priority: 'must',
    source_ref: '',
    notes: '',
  };
}

const REQ_CATEGORIES = [
  'structural', 'fire_safety', 'thermal', 'acoustic',
  'waterproofing', 'electrical', 'mechanical', 'architectural',
] as const;

const REQ_PRIORITIES = ['must', 'should', 'may'] as const;

interface RequirementRuleEditorProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (form: RequirementRuleForm) => void;
  submitting: boolean;
  initial?: RequirementRuleForm;
  mode: 'create' | 'edit' | 'from_model';
  /** When mode='from_model', model-derived parameter names and values. */
  modelParams?: { params: string[]; values: Record<string, string[]> };
}

function RequirementRuleEditor({
  open,
  onClose,
  onSubmit,
  submitting,
  initial,
  mode,
  modelParams,
}: RequirementRuleEditorProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState<RequirementRuleForm>(initial || blankRequirementForm());

  useEffect(() => {
    if (open) setForm(initial || blankRequirementForm());
  }, [open, initial]);

  const categories = useMemo(() => getCategoriesForFormat(form.format), [form.format]);
  const filterParams = useMemo(() => getFilterParamsForFormat(form.format), [form.format]);
  const propertyNames = useMemo(() => {
    if (mode === 'from_model' && modelParams?.params) {
      return modelParams.params;
    }
    return [...getPropertyNamesForFormat(form.format)];
  }, [form.format, mode, modelParams]);

  const filterValues = useMemo(() => {
    if (mode === 'from_model' && modelParams?.values?.[form.filter_param]) {
      return modelParams.values[form.filter_param]!;
    }
    // For manual mode, use the category list for the Category parameter
    if (form.filter_param === 'Category' || form.filter_param === 'category') {
      return [...categories];
    }
    return [];
  }, [form.filter_param, mode, modelParams, categories]);

  const [paramSearch, setParamSearch] = useState('');
  const filteredPropertyNames = useMemo(() => {
    const q = paramSearch.trim().toLowerCase();
    if (!q) return propertyNames.slice(0, 50);
    return propertyNames.filter((p) => p.toLowerCase().includes(q)).slice(0, 50);
  }, [propertyNames, paramSearch]);

  const set = useCallback(
    <K extends keyof RequirementRuleForm>(key: K, value: RequirementRuleForm[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      if (!form.filter_value.trim() || !form.check_param.trim() || !form.constraint_value.trim()) {
        return;
      }
      onSubmit(form);
    },
    [form, onSubmit],
  );

  if (!open) return null;

  const title =
    mode === 'edit'
      ? t('bim_rules.req_edit', { defaultValue: 'Edit Requirement Rule' })
      : mode === 'from_model'
        ? t('bim_rules.req_from_model', { defaultValue: 'Create from BIM Model' })
        : t('bim_rules.req_new', { defaultValue: 'New Requirement Rule' });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-light px-5 py-4">
          <div className="flex items-center gap-2">
            <Shield size={18} className="text-oe-blue" />
            <h2 className="text-base font-semibold text-content-primary">{title}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-content-secondary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
            {/* Format selection */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-content-secondary">
                {t('bim_rules.req_format', { defaultValue: 'BIM Format' })}
              </label>
              <div className="flex gap-3">
                {(['revit', 'ifc'] as BIMFormat[]).map((fmt) => (
                  <label
                    key={fmt}
                    className={clsx(
                      'flex items-center gap-2 rounded-lg border px-4 py-2 text-xs font-medium cursor-pointer transition-all',
                      form.format === fmt
                        ? 'border-oe-blue bg-oe-blue/5 text-oe-blue'
                        : 'border-border-light text-content-secondary hover:border-content-tertiary',
                    )}
                  >
                    <input
                      type="radio"
                      name="bim-format"
                      value={fmt}
                      checked={form.format === fmt}
                      onChange={() => {
                        set('format', fmt);
                        set('filter_param', getFilterParamsForFormat(fmt)[0] ?? '');
                        set('filter_value', '');
                        set('check_param', '');
                      }}
                      className="sr-only"
                    />
                    {fmt === 'revit' ? 'Revit' : 'IFC'}
                  </label>
                ))}
              </div>
            </div>

            {/* Three-column rule editor */}
            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
              <p className="mb-3 text-xs font-semibold text-content-secondary uppercase tracking-wide">
                {t('bim_rules.req_rule_definition', { defaultValue: 'Rule Definition' })}
              </p>
              <div className="grid grid-cols-3 gap-4">
                {/* Column 1: Filter */}
                <div className="space-y-2">
                  <p className="text-[11px] font-semibold text-content-tertiary">
                    {t('bim_rules.req_col1', { defaultValue: '1. Filter elements by' })}
                  </p>
                  <select
                    value={form.filter_param}
                    onChange={(e) => {
                      set('filter_param', e.target.value);
                      set('filter_value', '');
                    }}
                    className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                  >
                    {filterParams.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  {filterValues.length > 0 ? (
                    <select
                      value={form.filter_value}
                      onChange={(e) => set('filter_value', e.target.value)}
                      className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                    >
                      <option value="">
                        {t('bim_rules.req_select_value', { defaultValue: 'Select...' })}
                      </option>
                      {filterValues.map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={form.filter_value}
                      onChange={(e) => set('filter_value', e.target.value)}
                      placeholder={t('bim_rules.req_filter_value', {
                        defaultValue: 'e.g. Walls, IfcWall',
                      })}
                      className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                    />
                  )}
                </div>

                {/* Column 2: Parameter to check */}
                <div className="space-y-2">
                  <p className="text-[11px] font-semibold text-content-tertiary">
                    {t('bim_rules.req_col2', { defaultValue: '2. Parameter to check' })}
                  </p>
                  <div className="relative">
                    <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-content-tertiary" />
                    <input
                      type="text"
                      value={paramSearch}
                      onChange={(e) => setParamSearch(e.target.value)}
                      placeholder={t('bim_rules.req_search_param', { defaultValue: 'Search parameter...' })}
                      className="w-full rounded-lg border border-border-light bg-surface-primary pl-7 pr-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                    />
                  </div>
                  <select
                    value={form.check_param}
                    onChange={(e) => set('check_param', e.target.value)}
                    size={5}
                    className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                  >
                    {filteredPropertyNames.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    value={form.check_param}
                    onChange={(e) => set('check_param', e.target.value)}
                    placeholder={t('bim_rules.req_custom_param', {
                      defaultValue: 'Or type custom...',
                    })}
                    className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 font-mono text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                  />
                </div>

                {/* Column 3: Constraint */}
                <div className="space-y-2">
                  <p className="text-[11px] font-semibold text-content-tertiary">
                    {t('bim_rules.req_col3', { defaultValue: '3. Constraint / boundary' })}
                  </p>
                  <select
                    value={form.constraint_type}
                    onChange={(e) => set('constraint_type', e.target.value as ConstraintType)}
                    className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
                  >
                    {CONSTRAINT_TYPES.map((ct) => (
                      <option key={ct} value={ct}>
                        {CONSTRAINT_TYPE_LABELS[ct]}
                      </option>
                    ))}
                  </select>
                  {form.constraint_type !== 'exists' && form.constraint_type !== 'not_exists' && (
                    <input
                      type="text"
                      value={form.constraint_value}
                      onChange={(e) => set('constraint_value', e.target.value)}
                      placeholder={
                        form.constraint_type === 'regex'
                          ? '^F[0-9]+$'
                          : form.constraint_type === 'range'
                            ? '200..400'
                            : 'Value'
                      }
                      className={clsx(
                        'w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none',
                        form.constraint_type === 'regex' && 'font-mono',
                      )}
                    />
                  )}
                  {form.constraint_type === 'regex' && form.constraint_value && (() => {
                    try {
                      new RegExp(form.constraint_value);
                      return (
                        <p className="text-[10px] text-green-600">
                          {t('bim_rules.regex_valid', { defaultValue: 'Valid pattern' })}
                        </p>
                      );
                    } catch {
                      return (
                        <p className="text-[10px] text-red-500">
                          {t('bim_rules.regex_invalid', { defaultValue: 'Invalid pattern' })}
                        </p>
                      );
                    }
                  })()}
                </div>
              </div>
            </div>

            {/* Category + Priority */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  {t('bim_rules.req_category', { defaultValue: 'Category' })}
                </label>
                <select
                  value={form.category}
                  onChange={(e) => set('category', e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
                >
                  {REQ_CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {t(`requirements.cat_${c}`, { defaultValue: c.replace(/_/g, ' ') })}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  {t('bim_rules.req_priority', { defaultValue: 'Priority' })}
                </label>
                <div className="flex gap-2">
                  {REQ_PRIORITIES.map((p) => {
                    const color =
                      p === 'must'
                        ? 'border-red-400/50 bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
                        : p === 'should'
                          ? 'border-amber-400/50 bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400'
                          : 'border-oe-blue/50 bg-oe-blue/5 text-oe-blue';
                    return (
                      <label
                        key={p}
                        className={clsx(
                          'flex-1 cursor-pointer rounded-lg border px-3 py-1.5 text-center text-xs font-medium transition-all',
                          form.priority === p
                            ? color
                            : 'border-border-light text-content-secondary hover:border-content-tertiary',
                        )}
                      >
                        <input
                          type="radio"
                          name="req-priority"
                          value={p}
                          checked={form.priority === p}
                          onChange={() => set('priority', p)}
                          className="sr-only"
                        />
                        {p.charAt(0).toUpperCase() + p.slice(1)}
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Source + Notes */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  {t('bim_rules.req_source_ref', { defaultValue: 'Source Reference' })}
                </label>
                <input
                  type="text"
                  value={form.source_ref}
                  onChange={(e) => set('source_ref', e.target.value)}
                  placeholder={t('bim_rules.req_source_placeholder', {
                    defaultValue: 'e.g. Drawing A-101, DIN 4102',
                  })}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  {t('bim_rules.req_notes', { defaultValue: 'Notes' })}
                </label>
                <input
                  type="text"
                  value={form.notes}
                  onChange={(e) => set('notes', e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
                />
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border-light bg-surface-secondary px-5 py-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-tertiary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type="submit"
              disabled={
                submitting ||
                !form.filter_value.trim() ||
                !form.check_param.trim() ||
                (!form.constraint_value.trim() &&
                  form.constraint_type !== 'exists' &&
                  form.constraint_type !== 'not_exists')
              }
              className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-oe-blue-dark disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting && <Loader2 size={12} className="animate-spin" />}
              {t('common.save', { defaultValue: 'Save' })}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ── Requirements Tab Content ────────────────────────────────────────── */

function RequirementsTabContent({
  projectId,
  elements,
}: {
  projectId: string | null;
  elements?: Array<{ element_type?: string; properties?: Record<string, unknown> }>;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<'create' | 'edit' | 'from_model'>('create');
  const [editorInitial, setEditorInitial] = useState<RequirementRuleForm | undefined>();
  const [editingReqId, setEditingReqId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSetId, setActiveSetId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Fetch requirement sets for project
  const { data: sets = [], isLoading: setsLoading } = useQuery({
    queryKey: ['requirement-sets', projectId],
    queryFn: () => (projectId ? fetchRequirementSets(projectId) : Promise.resolve([] as RequirementSet[])),
    enabled: !!projectId,
  });

  const currentSetId = activeSetId || sets[0]?.id || '';

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ['requirement-set-detail', currentSetId],
    queryFn: () => fetchRequirementSetDetail(currentSetId),
    enabled: !!currentSetId,
  });

  const requirements = detail?.requirements ?? [];

  const filteredReqs = useMemo(() => {
    if (!searchQuery.trim()) return requirements;
    const q = searchQuery.toLowerCase();
    return requirements.filter(
      (r) =>
        r.entity.toLowerCase().includes(q) ||
        r.attribute.toLowerCase().includes(q) ||
        r.constraint_value.toLowerCase().includes(q),
    );
  }, [requirements, searchQuery]);

  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['requirement-sets'] });
    qc.invalidateQueries({ queryKey: ['requirement-set-detail'] });
  }, [qc]);

  // Model-derived parameter names for "from model" mode
  const modelParams = useMemo(() => {
    if (!elements || elements.length === 0) return undefined;
    const paramSet = new Set<string>();
    const valueMap: Record<string, Set<string>> = {};
    for (const el of elements) {
      if (el.element_type) {
        if (!valueMap['Category']) valueMap['Category'] = new Set();
        valueMap['Category']!.add(el.element_type);
      }
      if (el.properties) {
        for (const [k, v] of Object.entries(el.properties)) {
          paramSet.add(k);
          if (typeof v === 'string' || typeof v === 'number') {
            if (!valueMap[k]) valueMap[k] = new Set();
            valueMap[k]!.add(String(v));
          }
        }
      }
    }
    return {
      params: Array.from(paramSet).sort(),
      values: Object.fromEntries(
        Object.entries(valueMap).map(([k, s]) => [k, Array.from(s).sort()]),
      ),
    };
  }, [elements]);

  // Create set mutation
  const createSetMut = useMutation({
    mutationFn: (name: string) =>
      createRequirementSet({
        project_id: projectId!,
        name,
        description: 'Created from BIM Rules page',
      }),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('bim_rules.req_set_created', { defaultValue: 'Requirement set created' }) });
    },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  // Add requirement mutation
  const addMut = useMutation({
    mutationFn: (data: AddRequirementPayload) => addRequirement(currentSetId, data),
    onSuccess: () => {
      invalidateAll();
      setEditorOpen(false);
      addToast({ type: 'success', title: t('bim_rules.req_added', { defaultValue: 'Requirement rule added' }) });
    },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  // Update requirement mutation
  const editMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateRequirementPayload }) =>
      updateRequirement(currentSetId, id, data),
    onSuccess: () => {
      invalidateAll();
      setEditorOpen(false);
      setEditingReqId(null);
      addToast({ type: 'success', title: t('bim_rules.req_updated', { defaultValue: 'Requirement rule updated' }) });
    },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  // Delete requirement mutation
  const delMut = useMutation({
    mutationFn: (reqId: string) => deleteRequirement(currentSetId, reqId),
    onSuccess: () => {
      invalidateAll();
      setConfirmDeleteId(null);
      addToast({ type: 'success', title: t('bim_rules.req_deleted', { defaultValue: 'Requirement rule deleted' }) });
    },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  // Delete set mutation
  const delSetMut = useMutation({
    mutationFn: (setId: string) => deleteRequirementSet(setId),
    onSuccess: () => {
      invalidateAll();
      setActiveSetId(null);
    },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const handleSubmit = useCallback(
    (form: RequirementRuleForm) => {
      const payload: AddRequirementPayload = {
        entity: form.filter_value,
        attribute: form.check_param,
        constraint_type: form.constraint_type,
        constraint_value:
          form.constraint_type === 'exists' || form.constraint_type === 'not_exists'
            ? '*'
            : form.constraint_value,
        unit: '',
        category: form.category,
        priority: form.priority,
        source_ref: form.source_ref,
        notes: `[${form.format.toUpperCase()}] ${form.filter_param}=${form.filter_value} | ${form.notes}`,
      };
      if (editorMode === 'edit' && editingReqId) {
        editMut.mutate({ id: editingReqId, data: payload });
      } else {
        addMut.mutate(payload);
      }
    },
    [editorMode, editingReqId, addMut, editMut],
  );

  const openCreate = useCallback(() => {
    setEditorMode('create');
    setEditingReqId(null);
    setEditorInitial(undefined);
    setEditorOpen(true);
  }, []);

  const openFromModel = useCallback(() => {
    setEditorMode('from_model');
    setEditingReqId(null);
    setEditorInitial(undefined);
    setEditorOpen(true);
  }, []);

  const openEdit = useCallback((req: Requirement) => {
    setEditorMode('edit');
    setEditingReqId(req.id);
    // Attempt to parse the notes for format info
    const notesMatch = req.notes?.match(/^\[(\w+)\]\s*([\w\s]+)=(.*?)\s*\|/);
    const format: BIMFormat =
      notesMatch?.[1]?.toLowerCase() === 'ifc' ? 'ifc' : 'revit';
    const filterParam = notesMatch?.[2]?.trim() || 'Category';
    setEditorInitial({
      format,
      filter_param: filterParam,
      filter_value: req.entity,
      check_param: req.attribute,
      constraint_type: (CONSTRAINT_TYPES as readonly string[]).includes(req.constraint_type)
        ? (req.constraint_type as ConstraintType)
        : 'equals',
      constraint_value: req.constraint_value,
      category: req.category,
      priority: req.priority,
      source_ref: req.source_ref,
      notes: notesMatch ? req.notes.replace(notesMatch[0], '').trim() : req.notes,
    });
    setEditorOpen(true);
  }, []);

  const isLoading = setsLoading || detailLoading;

  const priorityColor = (p: string) => {
    if (p === 'must') return 'error' as const;
    if (p === 'should') return 'warning' as const;
    return 'blue' as const;
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {sets.length > 0 && (
          <select
            value={currentSetId}
            onChange={(e) => setActiveSetId(e.target.value)}
            className="rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-[11px] text-content-primary focus:border-oe-blue focus:outline-none"
          >
            {sets.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        )}
        {!currentSetId && projectId && (
          <button
            type="button"
            onClick={() => createSetMut.mutate('BIM Requirements')}
            disabled={createSetMut.isPending}
            className="flex items-center gap-1 text-[11px] text-oe-blue font-medium hover:underline"
          >
            <Plus size={12} />
            {t('bim_rules.req_new_set', { defaultValue: 'Create requirement set' })}
          </button>
        )}

        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('bim_rules.req_search', { defaultValue: 'Search entity, attribute, value...' })}
            className="w-full rounded-lg border border-border-light bg-surface-primary pl-8 pr-3 py-1.5 text-[11px] text-content-primary focus:border-oe-blue focus:outline-none"
          />
        </div>

        <div className="ml-auto flex items-center gap-2">
          {elements && elements.length > 0 && (
            <button
              type="button"
              onClick={openFromModel}
              className="flex items-center gap-1.5 rounded-lg border border-oe-blue/40 bg-oe-blue/5 px-3 py-1.5 text-[11px] font-medium text-oe-blue hover:bg-oe-blue/10"
            >
              <Sparkles size={12} />
              {t('bim_rules.req_from_model_btn', { defaultValue: 'From BIM Model' })}
            </button>
          )}
          <button
            type="button"
            onClick={openCreate}
            disabled={!currentSetId}
            className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-[11px] font-semibold text-white shadow-sm hover:bg-oe-blue-dark disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Plus size={13} />
            {t('bim_rules.req_new_rule', { defaultValue: 'New Rule' })}
          </button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12 text-sm text-content-secondary">
          <Loader2 size={18} className="mr-2 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      ) : !currentSetId || filteredReqs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-light bg-surface-secondary/30 px-6 py-12 text-center">
          <Shield size={28} className="mx-auto mb-2 text-content-tertiary" />
          <p className="text-sm font-medium text-content-secondary">
            {!currentSetId
              ? t('bim_rules.req_no_set', { defaultValue: 'Create a requirement set to start adding rules.' })
              : t('bim_rules.req_empty', { defaultValue: 'No requirement rules yet. Create your first rule.' })}
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-sm">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-border-light bg-surface-secondary text-content-secondary">
              <tr>
                <th className="px-3 py-2 font-medium">
                  {t('bim_rules.req_th_entity', { defaultValue: 'Entity (Filter)' })}
                </th>
                <th className="px-3 py-2 font-medium">
                  {t('bim_rules.req_th_attribute', { defaultValue: 'Parameter' })}
                </th>
                <th className="px-3 py-2 font-medium">
                  {t('bim_rules.req_th_constraint', { defaultValue: 'Constraint' })}
                </th>
                <th className="px-3 py-2 font-medium">
                  {t('bim_rules.req_th_category', { defaultValue: 'Category' })}
                </th>
                <th className="px-3 py-2 font-medium">
                  {t('bim_rules.req_th_priority', { defaultValue: 'Priority' })}
                </th>
                <th className="px-3 py-2 text-right font-medium">
                  {t('bim_rules.col_actions', { defaultValue: 'Actions' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredReqs.map((req) => (
                <tr
                  key={req.id}
                  className="border-t border-border-light text-content-primary hover:bg-surface-secondary"
                >
                  <td className="px-3 py-2 font-medium">{req.entity}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-content-tertiary">
                    {req.attribute}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant="neutral" size="sm">
                      {req.constraint_type}
                    </Badge>
                    <span className="ml-1 font-mono text-[11px]">
                      {req.constraint_value}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-[11px]">
                    {t(`requirements.cat_${req.category}`, {
                      defaultValue: req.category.replace(/_/g, ' '),
                    })}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={priorityColor(req.priority)} size="sm">
                      {req.priority}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => openEdit(req)}
                        className="rounded p-1 text-content-secondary hover:bg-surface-tertiary hover:text-oe-blue"
                        title={t('common.edit', { defaultValue: 'Edit' })}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(req.id)}
                        className="rounded p-1 text-content-secondary hover:bg-red-50 hover:text-red-600"
                        title={t('common.delete', { defaultValue: 'Delete' })}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-border-light bg-surface-secondary/30 px-3 py-2 text-[10px] text-content-tertiary flex items-center justify-between">
            <span>
              {filteredReqs.length} {t('bim_rules.req_rules_label', { defaultValue: 'requirement rules' })}
            </span>
            {currentSetId && (
              <button
                type="button"
                onClick={() => delSetMut.mutate(currentSetId)}
                className="text-content-quaternary hover:text-red-600"
                title={t('bim_rules.req_delete_set', { defaultValue: 'Delete set' })}
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Editor modal */}
      <RequirementRuleEditor
        open={editorOpen}
        onClose={() => { setEditorOpen(false); setEditingReqId(null); }}
        onSubmit={handleSubmit}
        submitting={addMut.isPending || editMut.isPending}
        initial={editorInitial}
        mode={editorMode}
        modelParams={modelParams}
      />

      {/* Delete confirm */}
      <ConfirmDialog
        open={confirmDeleteId !== null}
        onConfirm={() => {
          if (confirmDeleteId) delMut.mutate(confirmDeleteId);
        }}
        onCancel={() => setConfirmDeleteId(null)}
        title={t('bim_rules.req_confirm_delete', { defaultValue: 'Delete requirement rule?' })}
        message={t('bim_rules.req_confirm_delete_msg', {
          defaultValue: 'This requirement rule will be permanently removed.',
        })}
        loading={delMut.isPending}
      />
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────────────── */

export function BIMQuantityRulesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  /* ── Queries ───────────────────────────────────────────────────────── */

  const rulesQuery = useQuery({
    queryKey: ['bim-quantity-maps'],
    queryFn: () => listQuantityMaps(0, 500),
  });

  const modelsQuery = useQuery({
    queryKey: ['bim-models', activeProjectId],
    queryFn: () =>
      activeProjectId
        ? fetchBIMModels(activeProjectId)
        : Promise.resolve({ items: [], total: 0 }),
    enabled: !!activeProjectId,
  });

  const rules = useMemo<BIMQuantityMap[]>(() => {
    const items = rulesQuery.data?.items ?? [];
    if (!activeProjectId) return items;
    // Show project-specific rules + org-wide rules (project_id=null)
    return items.filter(
      (r) => !r.project_id || r.project_id === activeProjectId,
    );
  }, [rulesQuery.data, activeProjectId]);

  /* ── Lookup: boq_position_id → boq_id (for edit form) ──────────────── */

  const boqsListQuery = useQuery({
    queryKey: ['boqs', activeProjectId],
    queryFn: () =>
      activeProjectId ? boqApi.list(activeProjectId) : Promise.resolve<BOQ[]>([]),
    enabled: !!activeProjectId,
  });

  // Build a flat map position_id → boq_id from every BOQ in the project
  const boqPositionLookupQuery = useQuery({
    queryKey: ['boq-position-lookup', activeProjectId, boqsListQuery.data?.length ?? 0],
    queryFn: async () => {
      const map = new Map<string, string>();
      const boqs = boqsListQuery.data ?? [];
      for (const b of boqs) {
        try {
          const full = await boqApi.get(b.id);
          for (const p of full.positions) {
            map.set(p.id, b.id);
          }
        } catch {
          // skip — worst case the edit form just won't pre-select the BOQ
        }
      }
      return map;
    },
    enabled: !!activeProjectId && !!boqsListQuery.data && boqsListQuery.data.length > 0,
  });

  const boqPositionLookup = boqPositionLookupQuery.data ?? new Map<string, string>();

  /* ── State ─────────────────────────────────────────────────────────── */

  const [modelId, setModelId] = useState<string>('');
  const [activeTab, setActiveTab] = useState<RulesTab>('quantity_rules');

  useEffect(() => {
    const items = modelsQuery.data?.items ?? [];
    if (!modelId && items.length > 0 && items[0]) {
      setModelId(items[0].id);
    }
  }, [modelsQuery.data, modelId]);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<'create' | 'edit' | 'duplicate'>('create');
  const [editorInitial, setEditorInitial] = useState<RuleFormState>(blankForm());
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewResult, setPreviewResult] = useState<QuantityMapApplyResult | null>(null);

  /* ── Mutations ─────────────────────────────────────────────────────── */

  const createMutation = useMutation({
    mutationFn: createQuantityMap,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bim-quantity-maps'] });
      setEditorOpen(false);
      addToast({
        type: 'success',
        title: t('bim_rules.toast_created_title', { defaultValue: 'Rule created' }),
        message: t('bim_rules.toast_created_msg', {
          defaultValue: 'The new rule is now available.',
        }),
      });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('bim_rules.toast_create_failed', { defaultValue: 'Failed to create rule' }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: CreateBIMQuantityMapRequest }) =>
      patchQuantityMap(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bim-quantity-maps'] });
      setEditorOpen(false);
      addToast({
        type: 'success',
        title: t('bim_rules.toast_saved_title', { defaultValue: 'Rule saved' }),
        message: t('bim_rules.toast_saved_msg', { defaultValue: 'Changes applied.' }),
      });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('bim_rules.toast_save_failed', { defaultValue: 'Failed to save rule' }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      patchQuantityMap(id, { is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bim-quantity-maps'] });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('bim_rules.toast_toggle_failed', { defaultValue: 'Failed to toggle rule' }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => patchQuantityMap(id, { is_active: false, metadata: { deleted: true } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bim-quantity-maps'] });
      setConfirmDeleteId(null);
      addToast({
        type: 'success',
        title: t('bim_rules.toast_deleted_title', { defaultValue: 'Rule deleted' }),
        message: t('bim_rules.toast_deleted_msg', { defaultValue: 'The rule has been removed.' }),
      });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('bim_rules.toast_delete_failed', { defaultValue: 'Failed to delete rule' }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  const previewMutation = useMutation({
    mutationFn: (id: string) => applyQuantityMaps(id, true),
    onMutate: () => {
      setPreviewResult(null);
      setPreviewOpen(true);
    },
    onSuccess: (data) => {
      setPreviewResult(data);
    },
    onError: (err: unknown) => {
      setPreviewOpen(false);
      addToast({
        type: 'error',
        title: t('bim_rules.toast_preview_failed', { defaultValue: 'Preview failed' }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  const applyMutation = useMutation({
    mutationFn: (id: string) => applyQuantityMaps(id, false),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['bim-quantity-maps'] });
      addToast({
        type: 'success',
        title: t('bim_rules.toast_applied_title', { defaultValue: 'Rules applied' }),
        message: t('bim_rules.toast_applied_msg', {
          defaultValue: '{{links}} links created, {{positions}} positions created.',
          links: data.links_created,
          positions: data.positions_created,
        }),
      });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('bim_rules.toast_apply_failed', { defaultValue: 'Apply failed' }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  /* ── Handlers ──────────────────────────────────────────────────────── */

  const openCreate = useCallback(() => {
    setEditorMode('create');
    setEditingRuleId(null);
    setEditorInitial(blankForm());
    setEditorOpen(true);
  }, []);

  const openEdit = useCallback(
    (rule: BIMQuantityMap) => {
      setEditorMode('edit');
      setEditingRuleId(rule.id);
      setEditorInitial(toFormState(rule, boqPositionLookup));
      setEditorOpen(true);
    },
    [boqPositionLookup],
  );

  const openDuplicate = useCallback(
    (rule: BIMQuantityMap) => {
      setEditorMode('duplicate');
      setEditingRuleId(null);
      const form = toFormState(rule, boqPositionLookup);
      form.name = `${form.name} (copy)`;
      setEditorInitial(form);
      setEditorOpen(true);
    },
    [boqPositionLookup],
  );

  const handleSubmit = useCallback(
    (payload: CreateBIMQuantityMapRequest) => {
      if (editorMode === 'edit' && editingRuleId) {
        patchMutation.mutate({ id: editingRuleId, payload });
      } else {
        createMutation.mutate(payload);
      }
    },
    [editorMode, editingRuleId, createMutation, patchMutation],
  );

  const handlePreview = useCallback(() => {
    if (!modelId) {
      addToast({
        type: 'warning',
        title: t('bim_rules.toast_no_model_title', { defaultValue: 'Select a BIM model' }),
        message: t('bim_rules.toast_no_model_msg', {
          defaultValue: 'Please pick a BIM model first.',
        }),
      });
      return;
    }
    previewMutation.mutate(modelId);
  }, [modelId, previewMutation, addToast, t]);

  const handleApply = useCallback(() => {
    if (!modelId) {
      addToast({
        type: 'warning',
        title: t('bim_rules.toast_no_model_title', { defaultValue: 'Select a BIM model' }),
        message: t('bim_rules.toast_no_model_msg', {
          defaultValue: 'Please pick a BIM model first.',
        }),
      });
      return;
    }
    applyMutation.mutate(modelId);
  }, [modelId, applyMutation, addToast, t]);

  const modelOptions = modelsQuery.data?.items ?? [];

  /* ── Render ────────────────────────────────────────────────────────── */

  return (
    <div className="flex min-h-full flex-col bg-surface-secondary">
      {/* Header */}
      <div className="border-b border-border-light bg-surface-primary px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
              <SlidersHorizontal size={20} />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-content-primary">
                {t('bim_rules.page_title_combined', { defaultValue: 'BIM Rules & Requirements' })}
              </h1>
              <p className="text-xs text-content-secondary">
                {t('bim_rules.page_subtitle_combined', {
                  defaultValue:
                    'Quantity mapping rules and BIM requirement checks for your project.',
                })}
                {activeProjectName && (
                  <>
                    {' — '}
                    <span className="font-medium text-content-primary">{activeProjectName}</span>
                  </>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {activeTab === 'quantity_rules' && (
              <button
                type="button"
                onClick={openCreate}
                className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-[11px] font-semibold text-white shadow-sm hover:bg-oe-blue-dark"
              >
                <Plus size={13} />
                {t('bim_rules.new_rule', { defaultValue: 'New rule' })}
              </button>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="mt-4 flex border-b border-border-light -mb-px">
          <button
            type="button"
            onClick={() => setActiveTab('quantity_rules')}
            className={clsx(
              'px-4 py-2 text-xs font-medium border-b-2 transition-colors flex items-center gap-1.5',
              activeTab === 'quantity_rules'
                ? 'border-oe-blue text-oe-blue'
                : 'border-transparent text-content-tertiary hover:text-content-secondary hover:border-border-light',
            )}
          >
            <SlidersHorizontal size={13} />
            {t('bim_rules.tab_quantity_rules', { defaultValue: 'Quantity Rules' })}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('requirements')}
            className={clsx(
              'px-4 py-2 text-xs font-medium border-b-2 transition-colors flex items-center gap-1.5',
              activeTab === 'requirements'
                ? 'border-oe-blue text-oe-blue'
                : 'border-transparent text-content-tertiary hover:text-content-secondary hover:border-border-light',
            )}
          >
            <ClipboardCheck size={13} />
            {t('bim_rules.tab_requirements', { defaultValue: 'Requirements' })}
          </button>
        </div>

        {/* Toolbar (quantity rules tab only) */}
        {activeTab === 'quantity_rules' && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
          <div className="flex items-center gap-2">
            <Boxes size={14} className="text-content-tertiary" />
            <label htmlFor="model-picker" className="text-[11px] font-medium text-content-secondary">
              {t('bim_rules.model_picker', { defaultValue: 'BIM model' })}
            </label>
            <select
              id="model-picker"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              disabled={modelOptions.length === 0}
              className="rounded-lg border border-border-light bg-surface-primary px-2 py-1 text-[11px] text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-50"
            >
              {modelOptions.length === 0 ? (
                <option value="">
                  {t('bim_rules.no_models', { defaultValue: 'No models in this project' })}
                </option>
              ) : (
                modelOptions.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))
              )}
            </select>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={handlePreview}
              disabled={!modelId || previewMutation.isPending}
              className="flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-[11px] font-medium text-content-secondary hover:bg-surface-tertiary disabled:cursor-not-allowed disabled:opacity-60"
            >
              {previewMutation.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Eye size={12} />
              )}
              {t('bim_rules.preview', { defaultValue: 'Preview (dry run)' })}
            </button>
            <button
              type="button"
              onClick={handleApply}
              disabled={!modelId || applyMutation.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-[11px] font-semibold text-white shadow-sm hover:bg-oe-blue-dark disabled:cursor-not-allowed disabled:opacity-60"
            >
              {applyMutation.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Play size={12} />
              )}
              {t('bim_rules.apply', { defaultValue: 'Apply rules' })}
            </button>
          </div>
        </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'requirements' ? (
          <RequirementsTabContent projectId={activeProjectId} />
        ) : rulesQuery.isLoading ? (
          <div className="flex items-center justify-center py-16 text-sm text-content-secondary">
            <Loader2 size={18} className="mr-2 animate-spin" />
            {t('bim_rules.loading', { defaultValue: 'Loading rules…' })}
          </div>
        ) : rulesQuery.error ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-red-600">
            <AlertCircle size={18} />
            {t('bim_rules.load_error', { defaultValue: 'Failed to load rules.' })}
          </div>
        ) : rules.length === 0 ? (
          <EmptyState
            icon={<SlidersHorizontal size={32} />}
            title={t('bim_rules.empty_title', { defaultValue: 'No rules yet' })}
            description={t('bim_rules.empty_description', {
              defaultValue:
                'Create your first rule to bulk-link BIM elements to BOQ positions based on patterns.',
            })}
            action={
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={openCreate}
                  className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-oe-blue-dark"
                >
                  <Plus size={13} />
                  {t('bim_rules.empty_cta', { defaultValue: 'Create your first rule' })}
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/about')}
                  className="flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-tertiary"
                >
                  <BookOpen size={13} />
                  {t('bim_rules.empty_docs', { defaultValue: 'Read the docs' })}
                </button>
              </div>
            }
          />
        ) : (
          <div className="overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-sm">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border-light bg-surface-secondary text-content-secondary">
                <tr>
                  <th className="px-4 py-2 font-medium">
                    {t('bim_rules.col_name', { defaultValue: 'Name' })}
                  </th>
                  <th className="px-4 py-2 font-medium">
                    {t('bim_rules.col_pattern', { defaultValue: 'Element pattern' })}
                  </th>
                  <th className="px-4 py-2 font-medium">
                    {t('bim_rules.col_source', { defaultValue: 'Source' })}
                  </th>
                  <th className="px-4 py-2 font-medium">
                    {t('bim_rules.col_unit', { defaultValue: 'Unit' })}
                  </th>
                  <th className="px-4 py-2 font-medium">
                    {t('bim_rules.col_target', { defaultValue: 'Target' })}
                  </th>
                  <th className="px-4 py-2 text-center font-medium">
                    {t('bim_rules.col_active', { defaultValue: 'Active' })}
                  </th>
                  <th className="px-4 py-2 text-right font-medium">
                    {t('bim_rules.col_actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <Fragment key={rule.id}>
                    <tr className="border-t border-border-light text-content-primary hover:bg-surface-secondary">
                      <td className="px-4 py-2 font-medium">{rule.name}</td>
                      <td className="px-4 py-2 font-mono text-[11px] text-content-tertiary">
                        {rule.element_type_filter || '*'}
                        {rule.property_filter &&
                          Object.keys(rule.property_filter).length > 0 && (
                            <div className="mt-0.5 flex flex-wrap gap-1">
                              {Object.entries(rule.property_filter).map(([k, v]) => (
                                <Badge key={k} variant="neutral" size="sm">
                                  {k}={String(v)}
                                </Badge>
                              ))}
                            </div>
                          )}
                      </td>
                      <td className="px-4 py-2 font-mono text-[11px]">{rule.quantity_source}</td>
                      <td className="px-4 py-2">{rule.unit}</td>
                      <td className="px-4 py-2">
                        {rule.boq_target?.position_id ? (
                          <Badge variant="neutral">
                            {t('bim_rules.target_linked', { defaultValue: 'Linked position' })}
                          </Badge>
                        ) : rule.boq_target?.position_ordinal ? (
                          <Badge variant="neutral">{rule.boq_target.position_ordinal}</Badge>
                        ) : rule.boq_target?.auto_create ? (
                          <Badge variant="success">
                            {t('bim_rules.target_auto', { defaultValue: 'Auto-create' })}
                          </Badge>
                        ) : (
                          <span className="text-content-tertiary">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-center">
                        <button
                          type="button"
                          onClick={() =>
                            toggleActiveMutation.mutate({
                              id: rule.id,
                              is_active: !rule.is_active,
                            })
                          }
                          aria-label={t('bim_rules.toggle_active', {
                            defaultValue: 'Toggle active',
                          })}
                          className={clsx(
                            'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                            rule.is_active ? 'bg-oe-blue' : 'bg-border-light',
                          )}
                        >
                          <span
                            className={clsx(
                              'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                              rule.is_active ? 'translate-x-4' : 'translate-x-0.5',
                            )}
                          />
                        </button>
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => openEdit(rule)}
                            className="rounded p-1 text-content-secondary hover:bg-surface-tertiary hover:text-oe-blue"
                            aria-label={t('common.edit', { defaultValue: 'Edit' })}
                            title={t('common.edit', { defaultValue: 'Edit' })}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => openDuplicate(rule)}
                            className="rounded p-1 text-content-secondary hover:bg-surface-tertiary hover:text-oe-blue"
                            aria-label={t('common.duplicate', { defaultValue: 'Duplicate' })}
                            title={t('common.duplicate', { defaultValue: 'Duplicate' })}
                          >
                            <Copy size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(rule.id)}
                            className="rounded p-1 text-content-secondary hover:bg-red-50 hover:text-red-600"
                            aria-label={t('common.delete', { defaultValue: 'Delete' })}
                            title={t('common.delete', { defaultValue: 'Delete' })}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Editor modal */}
      <RuleEditorModal
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        initial={editorInitial}
        mode={editorMode}
        projectId={activeProjectId}
        onSubmit={handleSubmit}
        submitting={createMutation.isPending || patchMutation.isPending}
      />

      {/* Preview modal */}
      {/* BIM Requirements Import */}
      <div className="border-t border-border-light bg-surface-primary px-6 py-4">
        <details className="group" open>
          <summary className="cursor-pointer text-sm font-semibold text-content-primary flex items-center gap-2">
            <BookOpen size={16} className="text-oe-blue" />
            {t('bim_rules.requirements_import', { defaultValue: 'BIM Requirements Import/Export' })}
            <ChevronRight size={14} className="text-content-tertiary transition-transform group-open:rotate-90" />
          </summary>
          <div className="mt-4">
            <BIMRequirementsImport />
          </div>
        </details>
      </div>

      <PreviewModal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        result={previewResult}
        loading={previewMutation.isPending}
      />

      {/* Delete confirm */}
      <ConfirmDialog
        open={confirmDeleteId !== null}
        onConfirm={() => {
          if (confirmDeleteId) deleteMutation.mutate(confirmDeleteId);
        }}
        onCancel={() => setConfirmDeleteId(null)}
        title={t('bim_rules.confirm_delete_title', { defaultValue: 'Delete rule?' })}
        message={t('bim_rules.confirm_delete_msg', {
          defaultValue: 'This rule will be deactivated and hidden from the list.',
        })}
        loading={deleteMutation.isPending}
      />
    </div>
  );
}

export default BIMQuantityRulesPage;
