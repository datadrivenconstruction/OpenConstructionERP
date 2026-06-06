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
import { useNavigate, useSearchParams } from 'react-router-dom';
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
  Upload,
  Download,
  CheckCircle2,
  LayoutPanelTop,
  Layers3,
  DoorOpen,
  AppWindow,
  Flame,
  Thermometer,
  Construction,
  FlaskConical,
  History,
  RotateCcw,
  ShieldAlert,
  ListChecks,
  type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';

import { Badge, Breadcrumb, ConfirmDialog, DismissibleInfo, IntroRichText, EmptyState, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { apiGet } from '@/shared/lib/api';
import { FolderOpen } from 'lucide-react';
import BIMRequirementsImport from './BIMRequirementsImport';
import { RulePackLibrary } from '@/features/bim_requirements/RulePackLibrary';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  applyQuantityMaps,
  createQuantityMap,
  fetchBIMElements,
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
  buildCoverageReport,
  checkUnitSafety,
  draftConfidence,
  formulaSignature,
  pushVersion,
  readVersions,
  runSandbox,
  type RuleFormulaFields,
  type RuleVersionSnapshot,
  type SandboxElement,
  type SandboxRunResult,
} from './ruleSandbox';
import {
  fetchRequirementSets,
  fetchRequirementSetDetail,
  createRequirementSet,
  deleteRequirementSet,
  addRequirement,
  updateRequirement,
  deleteRequirement,
  importRequirementsFromFile,
  validateRequirementSetAgainstModel,
  requirementsTemplateUrl,
  type Requirement,
  type RequirementSet,
  type AddRequirementPayload,
  type UpdateRequirementPayload,
  type ValidateBIMResult,
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

/**
 * Pre-configured Quantity Rule starter templates shown in the empty state.
 * One click pre-fills the rule editor with a sensible starting point so the
 * user understands what a rule looks like instead of staring at a blank form.
 */
interface QuantityRulePreset {
  id: string;
  icon: LucideIcon;
  title: string;
  subtitle: string;
  patch: Partial<RuleFormState>;
}

const QUANTITY_RULES_PRESETS: QuantityRulePreset[] = [
  {
    id: 'walls-area',
    icon: LayoutPanelTop,
    title: 'Walls - area',
    subtitle: 'Auto-create one BOQ position per wall type, sized by surface area (m²).',
    patch: {
      name: 'Walls - area',
      element_type_filter: 'Wall*, IfcWall*',
      quantity_source: 'area_m2',
      unit: 'm²',
      waste_factor_pct: '5',
    },
  },
  {
    id: 'slabs-volume',
    icon: Layers3,
    title: 'Slabs - concrete volume',
    subtitle: 'Roll up floor / slab elements into a concrete pour position (m³).',
    patch: {
      name: 'Slabs - concrete volume',
      element_type_filter: 'Floor*, Slab*, IfcSlab*',
      quantity_source: 'volume_m3',
      unit: 'm³',
      waste_factor_pct: '3',
    },
  },
  {
    id: 'doors-count',
    icon: DoorOpen,
    title: 'Doors - count',
    subtitle: 'Count every door element and create one supply-and-install position.',
    patch: {
      name: 'Doors - count',
      element_type_filter: 'Door*, IfcDoor*',
      quantity_source: 'count',
      unit: 'pcs',
      waste_factor_pct: '0',
    },
  },
  {
    id: 'windows-count',
    icon: AppWindow,
    title: 'Windows - count',
    subtitle: 'Count windows and create a glazing position priced per piece.',
    patch: {
      name: 'Windows - count',
      element_type_filter: 'Window*, IfcWindow*',
      quantity_source: 'count',
      unit: 'pcs',
      waste_factor_pct: '0',
    },
  },
];

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

/** Context the payload builder needs to maintain the metadata-stored version
 *  history when editing an existing rule. ``previousFields`` is the rule's
 *  formula *before* this edit; ``baseMetadata`` is its current metadata bag so
 *  we preserve unrelated keys. Omitted entirely on create. */
interface VersionContext {
  previousFields: RuleFormulaFields;
  baseMetadata: Record<string, unknown>;
  label?: string;
}

function buildPayload(
  form: RuleFormState,
  projectId: string | null,
  versionCtx?: VersionContext,
): CreateBIMQuantityMapRequest {
  const propertyFilter = propertyFilterMap(form.property_filter);
  const quantitySource = effectiveQuantitySource(form);

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

  // Version history (metadata-only, no migration). When editing, snapshot the
  // PREVIOUS formula into metadata.versions if it changed, so the user can
  // restore an earlier formula later. On create there's no history yet.
  let metadata: Record<string, unknown> = {};
  if (versionCtx) {
    metadata = { ...versionCtx.baseMetadata };
    const nextFields = formToFormulaFields(form);
    const changed = formulaSignature(nextFields) !== formulaSignature(versionCtx.previousFields);
    if (changed) {
      const existing = readVersions(versionCtx.baseMetadata);
      metadata.versions = pushVersion(existing, versionCtx.previousFields, {
        label: versionCtx.label,
      });
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
    metadata,
  };
}

/** Collapse the editor's property rows into the flat key/value map the
 *  sandbox + payload share. Blank keys are dropped. */
function propertyFilterMap(rows: PropertyRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const k = row.key.trim();
    if (!k) continue;
    out[k] = row.value;
  }
  return out;
}

/** Resolve the effective quantity source from the form (custom falls back to
 *  its free-text field, then to ``count``). */
function effectiveQuantitySource(form: RuleFormState): string {
  return form.quantity_source === 'custom'
    ? form.custom_quantity_source.trim() || 'count'
    : form.quantity_source;
}

/** The formula-bearing slice of the form, used for the sandbox, unit-safety
 *  and version snapshots. */
function formToFormulaFields(form: RuleFormState): RuleFormulaFields {
  return {
    element_type_filter: form.element_type_filter.trim(),
    property_filter: propertyFilterMap(form.property_filter),
    quantity_source: effectiveQuantitySource(form),
    multiplier: form.multiplier.trim() || '1',
    waste_factor_pct: form.waste_factor_pct.trim() || '0',
    unit: form.unit.trim(),
  };
}

/* ── Rule editor modal ────────────────────────────────────────────────── */

/* ── Sandbox result view ──────────────────────────────────────────────── */

/** Confidence pill colour by bucket. */
const CONFIDENCE_STYLES: Record<'high' | 'medium' | 'low', string> = {
  high: 'border-emerald-400/50 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400',
  medium: 'border-amber-400/50 bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400',
  low: 'border-red-400/50 bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400',
};

/** Renders the outcome of a sandbox dry-run: roll-up counters, a confidence
 *  pill, the per-element quantity breakdown (first 25) and a skip note. */
function SandboxResultView({ result, unit }: { result: SandboxRunResult; unit: string }) {
  const { t } = useTranslation();
  const { confidence, ratio } = draftConfidence(result);
  const sample = result.matches.slice(0, 25);

  if (result.matches.length === 0 && result.skips.length === 0) {
    return (
      <div className="mt-2 rounded-md border border-dashed border-border-light px-3 py-3 text-center text-[11px] text-content-tertiary">
        {t('bim_rules.sandbox_no_match', {
          defaultValue:
            'No elements matched in the {{n}} scanned. Loosen the element type or property filter.',
          n: result.scanned,
        })}
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-2.5">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="rounded-md bg-oe-blue/10 px-2 py-0.5 font-medium text-oe-blue">
          {t('bim_rules.sandbox_matched', {
            defaultValue: '{{n}} matched',
            n: result.matches.length,
          })}
        </span>
        {result.skips.length > 0 && (
          <span className="rounded-md bg-amber-100 px-2 py-0.5 font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
            {t('bim_rules.sandbox_skipped', {
              defaultValue: '{{n}} skipped (no quantity)',
              n: result.skips.length,
            })}
          </span>
        )}
        <span className="rounded-md bg-surface-tertiary px-2 py-0.5 font-medium tabular-nums text-content-secondary">
          {t('bim_rules.sandbox_total', {
            defaultValue: 'Σ {{total}} {{unit}}',
            total: result.totalAdjusted.toLocaleString(undefined, {
              maximumFractionDigits: 3,
            }),
            unit: unit || '',
          })}
        </span>
        <span
          className={clsx(
            'ml-auto rounded-md border px-2 py-0.5 font-medium',
            CONFIDENCE_STYLES[confidence],
          )}
          title={t('bim_rules.sandbox_confidence_title', {
            defaultValue:
              'Share of matched elements that produced a usable quantity ({{pct}}%). Review low-confidence rules before saving.',
            pct: Math.round(ratio * 100),
          })}
        >
          {t('bim_rules.sandbox_confidence', {
            defaultValue: 'Confidence: {{level}}',
            level: t(`bim_rules.confidence_${confidence}`, { defaultValue: confidence }),
          })}
        </span>
      </div>

      <div className="max-h-44 overflow-y-auto rounded-md border border-border-light">
        <table className="w-full text-left text-[10px]">
          <thead className="sticky top-0 bg-surface-secondary text-content-secondary">
            <tr>
              <th className="px-2 py-1 font-medium">
                {t('bim_rules.col_element_type', { defaultValue: 'Type' })}
              </th>
              <th className="px-2 py-1 font-medium">
                {t('bim_rules.sandbox_col_name', { defaultValue: 'Name' })}
              </th>
              <th className="px-2 py-1 text-right font-medium">
                {t('bim_rules.col_raw', { defaultValue: 'Raw' })}
              </th>
              <th className="px-2 py-1 text-right font-medium">
                {t('bim_rules.col_adjusted', { defaultValue: 'Adjusted' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {sample.map((m, idx) => (
              <tr
                key={`${m.element_id}-${idx}`}
                className="border-t border-border-light text-content-primary"
              >
                <td className="truncate px-2 py-1">{m.element_type}</td>
                <td className="max-w-[160px] truncate px-2 py-1 text-content-tertiary">
                  {m.name || m.stable_id || m.element_id}
                </td>
                <td className="px-2 py-1 text-right tabular-nums">{m.raw_quantity.toFixed(3)}</td>
                <td className="px-2 py-1 text-right tabular-nums">
                  {m.adjusted_quantity.toFixed(3)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.matches.length > sample.length && (
        <p className="text-[10px] text-content-tertiary">
          {t('bim_rules.sandbox_more', {
            defaultValue: 'Showing first {{shown}} of {{total}} matched elements.',
            shown: sample.length,
            total: result.matches.length,
          })}
        </p>
      )}
    </div>
  );
}

interface RuleEditorModalProps {
  open: boolean;
  onClose: () => void;
  initial: RuleFormState;
  mode: 'create' | 'edit' | 'duplicate';
  projectId: string | null;
  /** Currently-selected BIM model — drives the live test sandbox. */
  modelId: string;
  modelName?: string;
  /** Formula of the rule before this edit, used to version on save. */
  previousFields?: RuleFormulaFields;
  /** The rule's current metadata bag (carries version history). */
  baseMetadata?: Record<string, unknown>;
  onSubmit: (payload: CreateBIMQuantityMapRequest) => void;
  submitting: boolean;
}

function RuleEditorModal({
  open,
  onClose,
  initial,
  mode,
  projectId,
  modelId,
  modelName,
  previousFields,
  baseMetadata,
  onSubmit,
  submitting,
}: RuleEditorModalProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState<RuleFormState>(initial);

  useEffect(() => {
    if (open) setForm(initial);
  }, [open, initial]);

  // ── Live test sandbox ────────────────────────────────────────────────
  // Runs the DRAFT rule against the selected model's elements client-side,
  // mirroring the backend engine, so the user sees matched elements +
  // per-element computed quantities before ever saving. AI-augmented,
  // human-confirmed: this is a preview, the apply still happens server-side.
  const [sandboxResult, setSandboxResult] = useState<SandboxRunResult | null>(null);
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [sandboxError, setSandboxError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  // Reset the sandbox + history panels whenever the modal is (re)opened.
  useEffect(() => {
    if (open) {
      setSandboxResult(null);
      setSandboxError(null);
      setHistoryOpen(false);
    }
  }, [open]);

  const formula = useMemo(() => formToFormulaFields(form), [form]);
  const unitSafety = useMemo(
    () => checkUnitSafety(formula.quantity_source, formula.unit),
    [formula.quantity_source, formula.unit],
  );
  const versions = useMemo(() => readVersions(baseMetadata), [baseMetadata]);

  const runTest = useCallback(async () => {
    if (!modelId) {
      setSandboxError(
        t('bim_rules.sandbox_no_model', {
          defaultValue: 'Pick a BIM model in the toolbar to test this rule.',
        }),
      );
      return;
    }
    setSandboxBusy(true);
    setSandboxError(null);
    try {
      // Skeleton fetch carries element_type + quantities + properties, which
      // is everything the rule engine reads — no geometry round-trip needed.
      const resp = await fetchBIMElements(modelId, { skeleton: true });
      const elements = resp.items as unknown as SandboxElement[];
      setSandboxResult(runSandbox(formula, elements));
    } catch (err) {
      setSandboxError(err instanceof Error ? err.message : String(err));
      setSandboxResult(null);
    } finally {
      setSandboxBusy(false);
    }
  }, [modelId, formula, t]);

  const restoreVersion = useCallback((v: RuleVersionSnapshot) => {
    setForm((prev) => ({
      ...prev,
      element_type_filter: v.element_type_filter,
      property_filter: Object.entries(v.property_filter ?? {}).map(([key, value]) => ({
        key,
        value: String(value),
      })),
      quantity_source: presetFromQuantitySource(v.quantity_source),
      custom_quantity_source: presetFromQuantitySource(v.quantity_source) === 'custom'
        ? v.quantity_source
        : '',
      multiplier: v.multiplier,
      waste_factor_pct: v.waste_factor_pct,
      unit: v.unit,
    }));
    setHistoryOpen(false);
    setSandboxResult(null);
  }, []);

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
      // Only edits carry a version context; create/duplicate start clean.
      const versionCtx =
        mode === 'edit' && previousFields
          ? {
              previousFields,
              baseMetadata: baseMetadata ?? {},
              label: form.name.trim(),
            }
          : undefined;
      onSubmit(buildPayload(form, projectId, versionCtx));
    },
    [form, projectId, onSubmit, mode, previousFields, baseMetadata],
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
                required aria-required="true"
                value={form.name}
                onChange={(e) => updateField('name', e.target.value)}
                placeholder={t('bim_rules.field_name_placeholder', {
                  defaultValue: 'e.g. Exterior walls - concrete',
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

            {/* Unit-safety guard — warns when the declared unit's dimension
                disagrees with the quantity source (e.g. an area_m2 rule that
                declares an m³ unit). Silent when either side is unknown. */}
            {unitSafety.mismatch && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] text-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
                <ShieldAlert size={14} className="mt-0.5 shrink-0" />
                <span>
                  {t('bim_rules.unit_mismatch', {
                    defaultValue:
                      'Unit mismatch: the source produces a {{src}} quantity but the unit "{{unit}}" reads as {{unitDim}}. Pick a matching unit or quantity source before saving.',
                    src: t(`bim_rules.dim_${unitSafety.sourceDimension}`, {
                      defaultValue: unitSafety.sourceDimension,
                    }),
                    unit: formula.unit,
                    unitDim: t(`bim_rules.dim_${unitSafety.unitDimension}`, {
                      defaultValue: unitSafety.unitDimension,
                    }),
                  })}
                </span>
              </div>
            )}

            {/* Live test sandbox — run the draft rule against the picked model
                and show matched elements + computed quantities before saving. */}
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-content-secondary">
                  <FlaskConical size={14} className="text-oe-blue" />
                  {t('bim_rules.sandbox_title', { defaultValue: 'Test this rule' })}
                </div>
                <button
                  type="button"
                  onClick={runTest}
                  disabled={sandboxBusy}
                  className="flex items-center gap-1.5 rounded-lg border border-oe-blue/40 bg-oe-blue/5 px-2.5 py-1 text-[11px] font-medium text-oe-blue hover:bg-oe-blue/10 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {sandboxBusy ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
                  {modelName
                    ? t('bim_rules.sandbox_run_named', {
                        defaultValue: 'Run on {{model}}',
                        model: modelName,
                      })
                    : t('bim_rules.sandbox_run', { defaultValue: 'Run dry test' })}
                </button>
              </div>
              <p className="mt-1 text-[10px] text-content-tertiary">
                {t('bim_rules.sandbox_hint', {
                  defaultValue:
                    'Runs the current draft against the selected model in your browser. Nothing is saved or linked until you press Save.',
                })}
              </p>

              {sandboxError && (
                <div className="mt-2 flex items-center gap-1.5 text-[11px] text-red-600">
                  <AlertCircle size={12} />
                  {sandboxError}
                </div>
              )}

              {sandboxResult && !sandboxBusy && (
                <SandboxResultView result={sandboxResult} unit={formula.unit} />
              )}
            </div>

            {/* Version history — restore an earlier formula. Stored in the
                rule's metadata.versions, so no migration is needed. */}
            {mode === 'edit' && versions.length > 0 && (
              <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
                <button
                  type="button"
                  onClick={() => setHistoryOpen((o) => !o)}
                  className="flex w-full items-center justify-between gap-2 text-xs font-semibold text-content-secondary"
                >
                  <span className="flex items-center gap-1.5">
                    <History size={14} className="text-oe-blue" />
                    {t('bim_rules.versions_title', {
                      defaultValue: 'Previous versions ({{n}})',
                      n: versions.length,
                    })}
                  </span>
                  <ChevronRight
                    size={14}
                    className={clsx(
                      'text-content-tertiary transition-transform',
                      historyOpen && 'rotate-90',
                    )}
                  />
                </button>
                {historyOpen && (
                  <ul className="mt-2 space-y-1.5">
                    {[...versions].reverse().map((v, i) => (
                      <li
                        key={`${v.saved_at}-${i}`}
                        className="flex items-center justify-between gap-2 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5"
                      >
                        <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-content-tertiary">
                          {(v.element_type_filter || '*')} · {v.quantity_source} · ×{v.multiplier} ·{' '}
                          {v.waste_factor_pct}% · {v.unit || '-'}
                        </span>
                        <span className="shrink-0 text-[10px] text-content-quaternary tabular-nums">
                          {new Date(v.saved_at).toLocaleString()}
                        </span>
                        <button
                          type="button"
                          onClick={() => restoreVersion(v)}
                          className="flex shrink-0 items-center gap-1 rounded-md border border-border-light px-2 py-0.5 text-[10px] font-medium text-oe-blue hover:bg-oe-blue/5"
                        >
                          <RotateCcw size={10} />
                          {t('bim_rules.versions_restore', { defaultValue: 'Restore' })}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

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
                          if (import.meta.env.DEV) console.warn('Cost suggestion failed', err);
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
              {t('common.save')}
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

type RulesTab = 'quantity_rules' | 'requirements' | 'rule_library';

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

/* ── ConstraintValueInput — picks the right widget per operator ─────── */

const NUMERIC_OPERATORS = new Set<ConstraintType>(['min', 'max', 'range']);
const PRESENCE_OPERATORS = new Set<ConstraintType>(['exists', 'not_exists']);

function parseRange(text: string): { from: string; to: string } {
  // Split on '..', '-', ',', or ';' — same operators the backend accepts.
  const m = text.split(/\s*(?:\.\.|;|,|-)\s*/).filter((s) => s.length > 0);
  return { from: m[0] ?? '', to: m[1] ?? '' };
}

interface ConstraintValueInputProps {
  constraintType: ConstraintType;
  value: string;
  onChange: (v: string) => void;
}

function ConstraintValueInput({
  constraintType,
  value,
  onChange,
}: ConstraintValueInputProps) {
  const { t } = useTranslation();

  if (PRESENCE_OPERATORS.has(constraintType)) {
    return (
      <p className="rounded-md border border-border-light bg-surface-tertiary px-2 py-1.5 text-[10px] text-content-tertiary">
        {constraintType === 'exists'
          ? t('bim_rules.req_exists_hint', {
              defaultValue: 'No value needed - passes when the property is present.',
            })
          : t('bim_rules.req_not_exists_hint', {
              defaultValue: 'No value needed - passes when the property is missing.',
            })}
      </p>
    );
  }

  if (constraintType === 'range') {
    const { from, to } = parseRange(value);
    const update = (next: { from: string; to: string }) => {
      const a = next.from.trim();
      const b = next.to.trim();
      if (!a && !b) onChange('');
      else if (a && b) onChange(`${a}..${b}`);
      else onChange(a || b);
    };
    return (
      <div className="flex items-center gap-1">
        <input
          type="number"
          step="any"
          value={from}
          onChange={(e) => update({ from: e.target.value, to })}
          placeholder={t('bim_rules.req_range_from', { defaultValue: 'from' })}
          className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
        />
        <span className="text-[10px] text-content-tertiary">–</span>
        <input
          type="number"
          step="any"
          value={to}
          onChange={(e) => update({ from, to: e.target.value })}
          placeholder={t('bim_rules.req_range_to', { defaultValue: 'to' })}
          className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
        />
      </div>
    );
  }

  if (NUMERIC_OPERATORS.has(constraintType)) {
    return (
      <input
        type="number"
        step="any"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          constraintType === 'min'
            ? t('bim_rules.req_min_placeholder', { defaultValue: '≥ value' })
            : t('bim_rules.req_max_placeholder', { defaultValue: '≤ value' })
        }
        className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
      />
    );
  }

  if (constraintType === 'regex') {
    let regexValid: boolean | null = null;
    if (value.trim()) {
      try {
        new RegExp(value);
        regexValid = true;
      } catch {
        regexValid = false;
      }
    }
    return (
      <div className="space-y-1">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="^F[0-9]{2,3}$"
          className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 font-mono text-xs text-content-primary focus:border-oe-blue focus:outline-none"
        />
        {regexValid === true && (
          <p className="text-[10px] text-green-600">
            {t('bim_rules.regex_valid', { defaultValue: 'Valid pattern' })}
          </p>
        )}
        {regexValid === false && (
          <p className="text-[10px] text-red-500">
            {t('bim_rules.regex_invalid', { defaultValue: 'Invalid pattern' })}
          </p>
        )}
      </div>
    );
  }

  // equals | not_equals | contains | not_contains
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={t('bim_rules.req_value_placeholder', { defaultValue: 'Value' })}
      className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
    />
  );
}

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
                  <ConstraintValueInput
                    constraintType={form.constraint_type}
                    value={form.constraint_value}
                    onChange={(v) => set('constraint_value', v)}
                  />
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

/**
 * Pre-built requirement packs. Clicking a pack adds 3-5 ready-made compliance
 * checks at once (e.g. "Fire safety" = walls/doors fire-rating + smoke-seal
 * checks). Lets a user go from empty page to a runnable compliance set in
 * seconds without having to author each rule from scratch.
 */
interface RequirementPack {
  id: string;
  icon: LucideIcon;
  title: string;
  subtitle: string;
  rules: AddRequirementPayload[];
}

// All ten operators (equals | not_equals | min | max | range | contains |
// not_contains | regex | exists | not_exists) are accepted by the backend
// schema as of the v2.8.8 unified contract — preset packs use the operator
// that fits the rule semantically.
const REQUIREMENTS_PRESET_PACKS: RequirementPack[] = [
  {
    id: 'fire-safety',
    icon: Flame,
    title: 'Fire safety basics',
    subtitle: 'Walls and doors must declare a fire rating; structural columns must match a code-compliant pattern.',
    rules: [
      {
        entity: 'Walls',
        attribute: 'FireRating',
        constraint_type: 'exists',
        constraint_value: '',
        unit: '',
        category: 'fire_safety',
        priority: 'must',
        notes: 'Walls must declare a fire rating',
      },
      {
        entity: 'Doors',
        attribute: 'FireRating',
        constraint_type: 'exists',
        constraint_value: '',
        unit: '',
        category: 'fire_safety',
        priority: 'must',
        notes: 'Doors must declare a fire rating',
      },
      {
        entity: 'Structural Columns',
        attribute: 'FireRating',
        constraint_type: 'regex',
        constraint_value: '^F\\d{2,3}$',
        unit: '',
        category: 'fire_safety',
        priority: 'must',
        notes: 'Structural columns must match F30/F60/F90/F120 format',
      },
    ],
  },
  {
    id: 'thermal',
    icon: Thermometer,
    title: 'Thermal performance',
    subtitle: 'Exterior walls and roofs must hit U-value targets; windows must declare U-value.',
    rules: [
      {
        entity: 'Walls',
        attribute: 'U-Value',
        constraint_type: 'max',
        constraint_value: '0.24',
        unit: 'W/m²K',
        category: 'thermal',
        priority: 'must',
        notes: '[REVIT] Category=Walls | Exterior wall U ≤ 0.24 W/m²K',
      },
      {
        entity: 'Roofs',
        attribute: 'U-Value',
        constraint_type: 'max',
        constraint_value: '0.20',
        unit: 'W/m²K',
        category: 'thermal',
        priority: 'must',
        notes: '[REVIT] Category=Roofs | Roof U ≤ 0.20 W/m²K',
      },
      {
        entity: 'Windows',
        attribute: 'U-Value',
        constraint_type: 'max',
        constraint_value: '1.4',
        unit: 'W/m²K',
        category: 'thermal',
        priority: 'should',
        notes: '[REVIT] Category=Windows | Windows U ≤ 1.4 W/m²K',
      },
    ],
  },
  {
    id: 'structural',
    icon: Construction,
    title: 'Structural integrity',
    subtitle: 'Structural elements must declare a material grade and load-bearing flag.',
    rules: [
      {
        entity: 'Structural Columns',
        attribute: 'Material',
        constraint_type: 'exists',
        constraint_value: '',
        unit: '',
        category: 'structural',
        priority: 'must',
        notes: 'Structural columns must declare a material',
      },
      {
        entity: 'Structural Framing',
        attribute: 'Material',
        constraint_type: 'exists',
        constraint_value: '',
        unit: '',
        category: 'structural',
        priority: 'must',
        notes: 'Structural framing must declare a material',
      },
      {
        entity: 'Walls',
        attribute: 'Structural',
        constraint_type: 'exists',
        constraint_value: '',
        unit: '',
        category: 'structural',
        priority: 'should',
        notes: 'Load-bearing flag set where applicable',
      },
    ],
  },
];

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

  // BIM models for the current project — needed for the
  // "Validate against BIM model" CTA. We fetch them lazily so the
  // Requirements tab opens fast even when the project has many models.
  const { data: bimModelsData } = useQuery({
    queryKey: ['bim-models-for-validation', projectId],
    queryFn: () => (projectId ? fetchBIMModels(projectId) : Promise.resolve({ items: [] } as { items: Array<{ id: string; name: string }> })),
    enabled: !!projectId,
  });
  const bimModels = bimModelsData?.items ?? [];
  const [pickModelOpen, setPickModelOpen] = useState(false);
  const [lastValidation, setLastValidation] = useState<ValidateBIMResult | null>(null);

  const validateMut = useMutation({
    mutationFn: (modelId: string) =>
      validateRequirementSetAgainstModel(currentSetId, modelId),
    onSuccess: (result) => {
      setLastValidation(result);
      setPickModelOpen(false);
      addToast({
        type: result.errors > 0 ? 'error' : result.warnings > 0 ? 'warning' : 'success',
        title: t('bim_rules.req_validate_done', {
          defaultValue: 'Validation finished',
        }),
        message: t('bim_rules.req_validate_summary', {
          defaultValue: '{{passed}} passed · {{warnings}} warnings · {{errors}} errors ({{checks}} checks)',
          passed: result.passed,
          warnings: result.warnings,
          errors: result.errors,
          checks: result.total_checks,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const importFileMut = useMutation({
    mutationFn: async (file: File) => {
      let setId = currentSetId;
      if (!setId) {
        if (!projectId) throw new Error('No active project');
        const created = await createRequirementSet({
          project_id: projectId,
          name: file.name.replace(/\.[^.]+$/, ''),
          description: `Imported from ${file.name}`,
        });
        setId = created.id;
        setActiveSetId(setId);
      }
      return importRequirementsFromFile(setId, file);
    },
    onSuccess: (result) => {
      invalidateAll();
      addToast({
        type: result.warnings.length > 0 ? 'warning' : 'success',
        title: t('bim_rules.req_import_done', { defaultValue: 'Import complete' }),
        message: t('bim_rules.req_import_summary', {
          defaultValue: 'Imported {{n}} rules · skipped {{s}} · {{w}} warnings',
          n: result.imported,
          s: result.skipped,
          w: result.warnings.length,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  // One-click pack installer — creates the set if missing, then bulk-adds
  // every rule in the pack so the user lands on a populated table without
  // hand-authoring each row.
  const installPackMut = useMutation({
    mutationFn: async (pack: RequirementPack) => {
      let setId = currentSetId;
      if (!setId) {
        if (!projectId) throw new Error('No active project');
        const created = await createRequirementSet({
          project_id: projectId,
          name: pack.title,
          description: `Preset: ${pack.subtitle}`,
        });
        setId = created.id;
        setActiveSetId(setId);
      }
      for (const rule of pack.rules) {
        await addRequirement(setId, rule);
      }
      return { setId, count: pack.rules.length, title: pack.title };
    },
    onSuccess: ({ count, title }) => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('bim_rules.req_pack_added_title', { defaultValue: 'Pack installed' }),
        message: t('bim_rules.req_pack_added_msg', {
          defaultValue: '{{count}} rules added from "{{title}}".',
          count,
          title,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const handleSubmit = useCallback(
    (form: RequirementRuleForm) => {
      const payload: AddRequirementPayload = {
        entity: form.filter_value,
        attribute: form.check_param,
        constraint_type: form.constraint_type,
        constraint_value:
          form.constraint_type === 'exists' || form.constraint_type === 'not_exists'
            ? ''
            : form.constraint_value,
        unit: '',
        category: form.category,
        priority: form.priority,
        source_ref: form.source_ref,
        notes: form.notes,
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
          {/* Import from Excel / CSV */}
          <label
            className={clsx(
              'flex cursor-pointer items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-[11px] font-medium text-content-secondary hover:border-oe-blue hover:text-oe-blue',
              importFileMut.isPending && 'pointer-events-none opacity-60',
            )}
            title={t('bim_rules.req_import_btn_title', {
              defaultValue: 'Upload Excel or CSV',
            })}
          >
            {importFileMut.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Upload size={12} />
            )}
            {t('bim_rules.req_import_btn', { defaultValue: 'Import' })}
            <input
              type="file"
              accept=".xlsx,.xls,.csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importFileMut.mutate(f);
                e.target.value = '';
              }}
            />
          </label>

          {/* Excel template download */}
          <a
            href={requirementsTemplateUrl()}
            className="flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-[11px] font-medium text-content-secondary hover:border-oe-blue hover:text-oe-blue"
            title={t('bim_rules.req_template_btn_title', {
              defaultValue: 'Download Excel template',
            })}
          >
            <Download size={12} />
            {t('bim_rules.req_template_btn', { defaultValue: 'Template' })}
          </a>

          {/* Export current set */}
          {currentSetId && requirements.length > 0 && (
            <a
              href={`/api/v1/requirements/${currentSetId}/export.xlsx`}
              className="flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-[11px] font-medium text-content-secondary hover:border-oe-blue hover:text-oe-blue"
              title={t('bim_rules.req_export_xlsx', { defaultValue: 'Export as Excel' })}
            >
              <Download size={12} />
              {t('common.export')}
            </a>
          )}

          {/* Validate against BIM model — the headline action */}
          {currentSetId && requirements.length > 0 && bimModels.length > 0 && (
            <button
              type="button"
              onClick={() => setPickModelOpen(true)}
              disabled={validateMut.isPending}
              className="flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-700 shadow-sm hover:bg-emerald-100 dark:bg-emerald-900/30 dark:text-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {validateMut.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <CheckCircle2 size={12} />
              )}
              {t('bim_rules.req_validate_btn', {
                defaultValue: 'Validate against model',
              })}
            </button>
          )}

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

      {/* Last validation summary card */}
      {lastValidation && (
        <div
          className={clsx(
            'rounded-xl border px-4 py-3 text-xs',
            lastValidation.errors > 0
              ? 'border-red-300 bg-red-50 text-red-800 dark:bg-red-900/20 dark:text-red-300'
              : lastValidation.warnings > 0
                ? 'border-amber-300 bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-300'
                : 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300',
          )}
        >
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-base font-semibold">
              {Math.round(lastValidation.score * 100)}%
            </span>
            <span>
              {t('bim_rules.req_validate_passed', { defaultValue: '{{n}} passed', n: lastValidation.passed })}
            </span>
            <span>·</span>
            <span>
              {t('bim_rules.req_validate_warned', { defaultValue: '{{n}} warnings', n: lastValidation.warnings })}
            </span>
            <span>·</span>
            <span>
              {t('bim_rules.req_validate_errored', { defaultValue: '{{n}} errors', n: lastValidation.errors })}
            </span>
            <span>·</span>
            <span>
              {t('bim_rules.req_validate_skipped', {
                defaultValue: '{{n}} requirements skipped (no matching elements)',
                n: lastValidation.skipped_requirements,
              })}
            </span>
            <a
              href={`/validation?report_id=${lastValidation.report_id}`}
              className="ml-auto font-medium underline-offset-2 hover:underline"
            >
              {t('bim_rules.req_validate_open_report', { defaultValue: 'Open full report →' })}
            </a>
          </div>
        </div>
      )}

      {/* Pick model modal */}
      {pickModelOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          onClick={() => !validateMut.isPending && setPickModelOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-xl bg-surface-primary p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-1 text-sm font-semibold text-content-primary">
              {t('bim_rules.req_pick_model_title', {
                defaultValue: 'Validate against which BIM model?',
              })}
            </h3>
            <p className="mb-4 text-xs text-content-secondary">
              {t('bim_rules.req_pick_model_subtitle', {
                defaultValue:
                  'Each requirement will be checked against every element in the chosen model. The score and findings will be saved as a regular validation report.',
              })}
            </p>
            <div className="max-h-72 space-y-1 overflow-auto">
              {bimModels.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  disabled={validateMut.isPending}
                  onClick={() => validateMut.mutate(m.id)}
                  className="flex w-full items-center justify-between rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-left text-xs font-medium text-content-primary hover:border-oe-blue hover:bg-oe-blue/5 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span>{m.name}</span>
                  {validateMut.isPending && validateMut.variables === m.id && (
                    <Loader2 size={12} className="animate-spin" />
                  )}
                </button>
              ))}
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setPickModelOpen(false)}
                disabled={validateMut.isPending}
                className="rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-tertiary disabled:opacity-60"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      {isLoading ? (
        <SkeletonTable rows={6} columns={4} />
      ) : !currentSetId || filteredReqs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-light bg-surface-secondary/30 px-6 py-8">
          <div className="text-center">
            <Shield size={28} className="mx-auto mb-2 text-content-tertiary" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('bim_rules.req_empty_title', {
                defaultValue: 'Start with a ready-made pack',
              })}
            </h3>
            <p className="mx-auto mt-1 max-w-md text-[12px] text-content-secondary">
              {t('bim_rules.req_empty_subtitle', {
                defaultValue:
                  'A pack adds 3-5 compliance rules in one click. Pick the area that fits your project; you can edit each rule afterwards.',
              })}
            </p>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {REQUIREMENTS_PRESET_PACKS.map((pack) => {
              const PackIcon = pack.icon;
              return (
              <button
                key={pack.id}
                type="button"
                disabled={installPackMut.isPending || !projectId}
                onClick={() => installPackMut.mutate(pack)}
                className="group flex flex-col items-start gap-2 rounded-lg border border-border-light bg-surface-primary p-4 text-left transition hover:-translate-y-0.5 hover:border-oe-blue/60 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue group-hover:bg-oe-blue group-hover:text-white transition-colors">
                  <PackIcon size={18} strokeWidth={1.85} />
                </span>
                <span className="text-sm font-semibold text-content-primary group-hover:text-oe-blue">
                  {pack.title}
                </span>
                <span className="text-[11px] leading-snug text-content-secondary">
                  {pack.subtitle}
                </span>
                <span className="mt-1 flex items-center gap-1 text-[11px] font-medium text-oe-blue">
                  <Plus size={12} />
                  {t('bim_rules.req_install_pack', {
                    defaultValue: 'Add {{count}} rules',
                    count: pack.rules.length,
                  })}
                </span>
              </button>
              );
            })}
          </div>

          <div className="mt-4 flex items-center justify-center gap-3 text-[11px] text-content-tertiary">
            <span>
              {t('bim_rules.req_empty_or', { defaultValue: 'or' })}
            </span>
            <button
              type="button"
              onClick={() => {
                if (!currentSetId && projectId) {
                  createSetMut.mutate('BIM Requirements');
                  return;
                }
                openCreate();
              }}
              disabled={createSetMut.isPending || !projectId}
              className="font-medium text-oe-blue hover:underline disabled:opacity-60"
            >
              {!currentSetId
                ? t('bim_rules.req_create_blank_set', {
                    defaultValue: 'Start with an empty set',
                  })
                : t('bim_rules.req_create_blank_rule', {
                    defaultValue: 'Add a custom rule',
                  })}
            </button>
          </div>

          {installPackMut.isPending && (
            <div className="mt-4 flex items-center justify-center gap-2 text-[11px] text-content-secondary">
              <Loader2 size={12} className="animate-spin" />
              {t('bim_rules.req_installing', { defaultValue: 'Installing pack…' })}
            </div>
          )}
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
                        title={t('common.edit')}
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

/* ── No-project empty state ──────────────────────────────────────────── */

interface ProjectOption { id: string; name: string }

/**
 * Inline project picker rendered in the EmptyState body. Loads the
 * project list lazily on focus so the cold paint of /bim/rules does
 * NOT pay the projects round-trip when a project is already active.
 * After the user picks one, ``setActiveProject`` is fired against the
 * shared store — every page reads from the same source so no manual
 * navigation is needed.
 */
function NoProjectPicker() {
  const { t } = useTranslation();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || projects.length > 0) return;
    setLoading(true);
    apiGet<{ items?: ProjectOption[] } | ProjectOption[]>('/v1/projects/')
      .then((res) => {
        const items = Array.isArray(res) ? res : res.items ?? [];
        setProjects(items);
      })
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, [open, projects.length]);

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-oe-blue-dark"
      >
        <FolderOpen size={14} />
        {t('bim_rules.no_project_pick_btn', { defaultValue: 'Pick a project' })}
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="absolute left-1/2 z-20 mt-2 w-64 -translate-x-1/2 rounded-lg border border-border-light bg-surface-primary py-1 shadow-lg">
          {loading && (
            <div className="px-3 py-2 text-[11px] text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          )}
          {!loading && projects.length === 0 && (
            <div className="px-3 py-2 text-[11px] text-content-tertiary">
              {t('bim_rules.no_project_no_projects', { defaultValue: 'No projects available' })}
            </div>
          )}
          {!loading &&
            projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setActiveProject(p.id, p.name);
                  setOpen(false);
                }}
                className="block w-full truncate px-3 py-1.5 text-left text-[12px] text-content-primary hover:bg-surface-secondary"
              >
                {p.name}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

/* ── Coverage report panel ────────────────────────────────────────────── */

/**
 * Missing-scope detector. Lists every element type present in the active model
 * and whether at least one active rule selects it. Uncovered categories (the
 * trades nobody has written a rule for yet) are surfaced first with a one-click
 * "create a rule for this" affordance, so a half-covered model is obvious at a
 * glance instead of silently shipping under-scoped quantities.
 */
function CoverageReportPanel({
  report,
  onCreateForCategory,
  modelName,
}: {
  report: ReturnType<typeof buildCoverageReport>;
  onCreateForCategory: (category: string) => void;
  modelName?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const pct = Math.round(report.coverageRatio * 100);
  const hasGaps = report.uncovered.length > 0;

  return (
    <div
      className={clsx(
        'rounded-xl border bg-surface-primary shadow-sm',
        hasGaps ? 'border-amber-300' : 'border-emerald-300',
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <span
          className={clsx(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
            hasGaps
              ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
              : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
          )}
        >
          <ListChecks size={16} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-content-primary">
            {t('bim_rules.coverage_title', { defaultValue: 'Rule coverage' })}
            {modelName ? <span className="text-content-tertiary"> · {modelName}</span> : null}
          </span>
          <span className="block text-[11px] text-content-secondary">
            {hasGaps
              ? t('bim_rules.coverage_gaps', {
                  defaultValue:
                    '{{pct}}% of categories covered. {{n}} element type(s) have no active rule.',
                  pct,
                  n: report.uncovered.length,
                })
              : t('bim_rules.coverage_full', {
                  defaultValue: 'Every element type in this model is covered by a rule.',
                })}
          </span>
        </span>
        <span className="shrink-0 text-lg font-semibold tabular-nums text-content-primary">
          {pct}%
        </span>
        <ChevronRight
          size={16}
          className={clsx('shrink-0 text-content-tertiary transition-transform', open && 'rotate-90')}
        />
      </button>

      {open && (
        <div className="border-t border-border-light px-4 py-3">
          <div className="overflow-hidden rounded-lg border border-border-light">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-surface-secondary text-content-secondary">
                <tr>
                  <th className="px-3 py-1.5 font-medium">
                    {t('bim_rules.coverage_col_category', { defaultValue: 'Element type' })}
                  </th>
                  <th className="px-3 py-1.5 text-right font-medium">
                    {t('bim_rules.coverage_col_count', { defaultValue: 'Elements' })}
                  </th>
                  <th className="px-3 py-1.5 font-medium">
                    {t('bim_rules.coverage_col_rules', { defaultValue: 'Covered by' })}
                  </th>
                  <th className="px-3 py-1.5 text-right font-medium">
                    {t('bim_rules.col_actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row) => (
                  <tr
                    key={row.category}
                    className="border-t border-border-light text-content-primary"
                  >
                    <td className="px-3 py-1.5">
                      <span className="flex items-center gap-1.5">
                        <span
                          className={clsx(
                            'inline-block h-2 w-2 shrink-0 rounded-full',
                            row.covered ? 'bg-emerald-500' : 'bg-amber-500',
                          )}
                        />
                        {row.category}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-content-tertiary">
                      {row.elementCount}
                    </td>
                    <td className="px-3 py-1.5 text-content-tertiary">
                      {row.covered ? (
                        <span className="truncate">{row.ruleNames.join(', ')}</span>
                      ) : (
                        <span className="text-amber-600">
                          {t('bim_rules.coverage_no_rule', { defaultValue: 'No rule' })}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {!row.covered && (
                        <button
                          type="button"
                          onClick={() => onCreateForCategory(row.category)}
                          className="inline-flex items-center gap-1 rounded-md border border-oe-blue/40 px-2 py-0.5 text-[10px] font-medium text-oe-blue hover:bg-oe-blue/5"
                        >
                          <Plus size={10} />
                          {t('bim_rules.coverage_add_rule', { defaultValue: 'Add rule' })}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
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
    // No active project → only show org-wide rules. Previously we returned
    // every rule regardless of project_id, which leaked project-scoped rules
    // from other projects and made it look like a just-created project-scoped
    // rule "didn't appear" after the user switched projects.
    if (!activeProjectId) return items.filter((r) => !r.project_id);
    // Active project → show org-wide rules + rules scoped to this project.
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
  // URL param ?mode=requirements locks the page to the Requirements tab so
  // the sidebar can expose the compliance half as its own entry under
  // Takeoff, while /bim/rules (no param) remains the Estimation-side
  // Quantity Rules editor. Keeping a single page component avoids code
  // duplication; the mode flag just hides the tab switcher + fixes the
  // active tab.
  const [searchParams] = useSearchParams();
  const lockedMode = searchParams.get('mode') === 'requirements' ? 'requirements' : null;
  const [activeTab, setActiveTab] = useState<RulesTab>(
    lockedMode === 'requirements' ? 'requirements' : 'quantity_rules',
  );
  useEffect(() => {
    if (lockedMode === 'requirements' && activeTab !== 'requirements') {
      setActiveTab('requirements');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lockedMode]);

  useEffect(() => {
    const items = modelsQuery.data?.items ?? [];
    if (!modelId && items.length > 0 && items[0]) {
      setModelId(items[0].id);
    }
  }, [modelsQuery.data, modelId]);

  // Skeleton fetch (5 fields per element, no geometry) of the selected
  // model. The Requirements tab uses it for the "From BIM Model" auto-fill;
  // the Quantity Rules tab uses it for the coverage / missing-scope report.
  // Disabled on the Rule Library tab to avoid pulling 50k rows for nothing.
  const elementsQuery = useQuery({
    queryKey: ['bim-elements-skeleton', modelId],
    queryFn: () =>
      modelId
        ? fetchBIMElements(modelId, { skeleton: true })
        : Promise.resolve({ items: [], total: 0 }),
    enabled:
      !!modelId && (activeTab === 'requirements' || activeTab === 'quantity_rules'),
    staleTime: 5 * 60 * 1000,
  });
  const requirementsElements = elementsQuery.data?.items;

  // Coverage / missing-scope report: which element types in the active model
  // have NO active rule selecting them. Computed purely client-side from the
  // skeleton elements + the visible rules.
  const coverageReport = useMemo(() => {
    const items = elementsQuery.data?.items;
    if (!items || items.length === 0) return null;
    return buildCoverageReport(
      items as unknown as SandboxElement[],
      rules.map((r) => ({
        name: r.name,
        element_type_filter: r.element_type_filter ?? '',
        is_active: r.is_active,
      })),
    );
  }, [elementsQuery.data, rules]);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<'create' | 'edit' | 'duplicate'>('create');
  const [editorInitial, setEditorInitial] = useState<RuleFormState>(blankForm());
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  // The rule being edited (or null) so the editor can version its previous
  // formula on save and surface its metadata-stored history.
  const [editingRule, setEditingRule] = useState<BIMQuantityMap | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewResult, setPreviewResult] = useState<QuantityMapApplyResult | null>(null);

  /* ── Mutations ─────────────────────────────────────────────────────── */

  const createMutation = useMutation({
    // Explicit key so the global MutationCache handler in main.tsx also
    // invalidates the list — guards against a forgotten refetch if the
    // local onSuccess below is ever skipped (e.g. component unmount mid-flight).
    mutationKey: ['bim-quantity-maps', 'create'],
    mutationFn: createQuantityMap,
    onSuccess: async () => {
      // Await the invalidation so the list is guaranteed to have been
      // refetched before the dialog closes and the success toast fires.
      // Without the await, the user briefly sees an empty list after close.
      await queryClient.invalidateQueries({ queryKey: ['bim-quantity-maps'] });
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
      // The apply result does not carry a single BOQ id (positions can land
      // across several BOQs), so the "View in BOQ" action opens the active
      // project's BOQ list, where the freshly created positions now live.
      // Only offer the action when something was actually written.
      const wroteSomething =
        data.links_created > 0 || data.positions_created > 0;
      addToast({
        type: 'success',
        title: t('bim_rules.toast_applied_title', { defaultValue: 'Rules applied' }),
        message: t('bim_rules.toast_applied_msg', {
          defaultValue: '{{links}} links created, {{positions}} positions created.',
          links: data.links_created,
          positions: data.positions_created,
        }),
        ...(wroteSomething
          ? {
              action: {
                label: t('bim_rules.toast_applied_view_boq', {
                  defaultValue: 'View in BOQ',
                }),
                onClick: () => navigate('/boq'),
              },
            }
          : {}),
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
    setEditingRule(null);
    setEditorInitial(blankForm());
    setEditorOpen(true);
  }, []);

  // Opens the editor pre-filled from one of the QUANTITY_RULES_PRESETS so
  // first-time users can ship a usable rule with a single review-and-Save
  // pass instead of having to invent every field from scratch.
  const openCreateFromPreset = useCallback((preset: QuantityRulePreset) => {
    setEditorMode('create');
    setEditingRuleId(null);
    setEditingRule(null);
    setEditorInitial({ ...blankForm(), ...preset.patch });
    setEditorOpen(true);
  }, []);

  const openEdit = useCallback(
    (rule: BIMQuantityMap) => {
      setEditorMode('edit');
      setEditingRuleId(rule.id);
      setEditingRule(rule);
      setEditorInitial(toFormState(rule, boqPositionLookup));
      setEditorOpen(true);
    },
    [boqPositionLookup],
  );

  const openDuplicate = useCallback(
    (rule: BIMQuantityMap) => {
      setEditorMode('duplicate');
      setEditingRuleId(null);
      setEditingRule(null);
      const form = toFormState(rule, boqPositionLookup);
      form.name = `${form.name} (copy)`;
      setEditorInitial(form);
      setEditorOpen(true);
    },
    [boqPositionLookup],
  );

  // Pre-fill a new rule whose element-type filter targets one uncovered
  // category — the "fix this gap" affordance on the coverage report.
  const openCreateForCategory = useCallback((category: string) => {
    setEditorMode('create');
    setEditingRuleId(null);
    setEditingRule(null);
    setEditorInitial({
      ...blankForm(),
      name: `${category} - quantity`,
      element_type_filter: category,
    });
    setEditorOpen(true);
  }, []);

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
  const selectedModelName = modelOptions.find((m) => m.id === modelId)?.name;

  // Formula + metadata of the rule being edited, fed to the editor so it can
  // version the previous formula on save and show its history.
  const editingPreviousFields = useMemo<RuleFormulaFields | undefined>(() => {
    if (!editingRule) return undefined;
    return {
      element_type_filter: editingRule.element_type_filter ?? '',
      property_filter: Object.fromEntries(
        Object.entries(editingRule.property_filter ?? {}).map(([k, v]) => [k, String(v)]),
      ),
      quantity_source: editingRule.quantity_source ?? '',
      multiplier: editingRule.multiplier ?? '1',
      waste_factor_pct: editingRule.waste_factor_pct ?? '0',
      unit: editingRule.unit ?? '',
    };
  }, [editingRule]);

  /* ── Render ────────────────────────────────────────────────────────── */

  return (
    <div className="flex min-h-full flex-col">
      {/* Header */}
      <div className="border-b border-border-light bg-surface-primary px-6 py-4">
        <Breadcrumb
          items={[
            ...(activeProjectId && activeProjectName
              ? [{ label: activeProjectName, to: `/projects/${activeProjectId}` }]
              : []),
            { label: t('nav.bim_rules', { defaultValue: 'BIM Rules' }) },
          ]}
          className="mb-3"
        />
        <PageHeader
          srTitle={
            lockedMode === 'requirements'
              ? t('bim_rules.page_title_requirements', {
                  defaultValue: 'BIM Rules (Compliance)',
                })
              : t('bim_rules.page_title_quantity', {
                  defaultValue: 'Quantity Rules',
                })
          }
          subtitle={
            lockedMode === 'requirements'
              ? t('bim_rules.page_subtitle_requirements', {
                  defaultValue:
                    'Import and check BIM requirements (IDS, COBie, Excel) for your project.',
                })
              : t('bim_rules.page_subtitle_quantity', {
                  defaultValue:
                    'Bulk-link BIM elements to BOQ positions via pattern-based rules.',
                })
          }
          actions={
            activeTab === 'quantity_rules' ? (
              <button
                type="button"
                onClick={openCreate}
                className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-[11px] font-semibold text-white shadow-sm hover:bg-oe-blue-dark"
              >
                <Plus size={13} />
                {t('bim_rules.new_rule', { defaultValue: 'New rule' })}
              </button>
            ) : undefined
          }
        />

        <DismissibleInfo
          storageKey="bim-rules"
          className="mt-4"
          title={t('bim_rules.intro_title', {
            defaultValue: 'Link hundreds of elements without clicking each one',
          })}
          more={
            t('bim_rules.intro_more', { defaultValue: '' })
              ? <IntroRichText text={t('bim_rules.intro_more')} />
              : undefined
          }
          links={[
            { label: t('bim_rules.intro_link_bim', { defaultValue: 'BIM viewer' }), onClick: () => navigate('/bim') },
            { label: t('bim_rules.intro_link_boq', { defaultValue: 'Open BOQ' }), onClick: () => navigate('/boq') },
            { label: t('bim_rules.intro_link_matrix', { defaultValue: 'Requirements matrix' }), onClick: () => navigate('/requirements/matrix') },
          ]}
        >
          {t('bim_rules.intro_body', {
            defaultValue:
              'Define a pattern such as category equals Walls and storey equals Level 01, then map it to a BOQ position that already exists or is created for you. Applying the rule links matching elements from a BIM model in bulk, so quantities roll into the BOQ instead of being linked by hand. The same page holds the EIR and information-requirement rules that incoming models are checked against.',
          })}
        </DismissibleInfo>

        {/* Tabs — hidden when the URL locks the page to a single mode so
            the Takeoff "BIM Rules" and Estimation "Quantity Rules" sidebar
            entries read as dedicated pages, not as two tabs on the same
            screen. */}
        {!lockedMode && (
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
            <button
              type="button"
              onClick={() => setActiveTab('rule_library')}
              data-testid="bim-rules-tab-rule-library"
              className={clsx(
                'px-4 py-2 text-xs font-medium border-b-2 transition-colors flex items-center gap-1.5',
                activeTab === 'rule_library'
                  ? 'border-oe-blue text-oe-blue'
                  : 'border-transparent text-content-tertiary hover:text-content-secondary hover:border-border-light',
              )}
            >
              <BookOpen size={13} />
              {t('rulePacks.title', { defaultValue: 'Rule Library' })}
            </button>
          </div>
        )}

        {/* Toolbar — model picker for both tabs (Requirements uses it to
            populate the "From BIM Model" auto-fill); Preview/Apply only
            apply to Quantity Rules. */}
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

          {activeTab === 'quantity_rules' && (
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
          )}
          {activeTab === 'requirements' && (
            <span className="ml-auto text-[10px] text-content-tertiary">
              {modelId
                ? t('bim_rules.model_helps_req', {
                    defaultValue: 'Picked model lets you auto-fill rules from real elements.',
                  })
                : t('bim_rules.model_picker_hint', {
                    defaultValue: 'Pick a model to auto-fill rules from real elements.',
                  })}
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'rule_library' ? (
          /* Rule Library tab — works without an active project too
             because the seed packs are inlined; install button stays
             disabled until a project is selected. */
          <RulePackLibrary projectId={activeProjectId} />
        ) : !activeProjectId ? (
          <EmptyState
            icon={<FolderOpen size={28} strokeWidth={1.5} />}
            title={t('bim_rules.no_project_title', { defaultValue: 'Pick a project to view rules' })}
            description={t('bim_rules.no_project_desc', {
              defaultValue:
                'BIM Quantity Rules and Requirements are project-scoped. Select a project to load its rule sets, BIM models, and validation history.',
            })}
            action={<NoProjectPicker />}
          />
        ) : activeTab === 'requirements' ? (
          <RequirementsTabContent projectId={activeProjectId} elements={requirementsElements} />
        ) : rulesQuery.isLoading ? (
          <SkeletonTable rows={6} columns={4} />
        ) : rulesQuery.error ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-red-600">
            <AlertCircle size={18} />
            {t('bim_rules.load_error', { defaultValue: 'Failed to load rules.' })}
          </div>
        ) : rules.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-light bg-surface-secondary/30 px-6 py-8">
            <div className="text-center">
              <SlidersHorizontal size={28} className="mx-auto mb-2 text-content-tertiary" />
              <h3 className="text-sm font-semibold text-content-primary">
                {t('bim_rules.empty_title_v2', {
                  defaultValue: 'Start from a template',
                })}
              </h3>
              <p className="mx-auto mt-1 max-w-md text-[12px] text-content-secondary">
                {t('bim_rules.empty_subtitle_v2', {
                  defaultValue:
                    'A rule auto-creates a BOQ position from BIM elements that match a pattern. Pick a template to see an example you can save or adjust.',
                })}
              </p>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {QUANTITY_RULES_PRESETS.map((preset) => {
                const PresetIcon = preset.icon;
                return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => openCreateFromPreset(preset)}
                  className="group flex flex-col items-start gap-2 rounded-lg border border-border-light bg-surface-primary p-4 text-left transition hover:-translate-y-0.5 hover:border-oe-blue/60 hover:shadow-md"
                >
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue group-hover:bg-oe-blue group-hover:text-white transition-colors">
                    <PresetIcon size={18} strokeWidth={1.85} />
                  </span>
                  <span className="text-sm font-semibold text-content-primary group-hover:text-oe-blue">
                    {preset.title}
                  </span>
                  <span className="text-[11px] leading-snug text-content-secondary">
                    {preset.subtitle}
                  </span>
                  <span className="mt-1 flex items-center gap-1 text-[11px] font-medium text-oe-blue">
                    <Plus size={12} />
                    {t('bim_rules.empty_use_template', {
                      defaultValue: 'Use this template',
                    })}
                  </span>
                </button>
                );
              })}
            </div>

            <div className="mt-4 flex items-center justify-center gap-3 text-[11px] text-content-tertiary">
              <span>{t('bim_rules.empty_or', { defaultValue: 'or' })}</span>
              <button
                type="button"
                onClick={openCreate}
                className="font-medium text-oe-blue hover:underline"
              >
                {t('bim_rules.empty_blank', { defaultValue: 'Start from a blank rule' })}
              </button>
              <span>·</span>
              <button
                type="button"
                onClick={() => navigate('/about')}
                className="flex items-center gap-1 hover:text-content-secondary"
              >
                <BookOpen size={12} />
                {t('bim_rules.empty_docs', { defaultValue: 'Read the docs' })}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Coverage / missing-scope report — which element types in the
                active model no active rule yet selects. */}
            {coverageReport && (
              <CoverageReportPanel
                report={coverageReport}
                onCreateForCategory={openCreateForCategory}
                modelName={selectedModelName}
              />
            )}
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
        modelId={modelId}
        modelName={selectedModelName}
        previousFields={editingPreviousFields}
        baseMetadata={editingRule?.metadata}
        onSubmit={handleSubmit}
        submitting={createMutation.isPending || patchMutation.isPending}
      />

      {/* BIM Requirements Import — only shown on the Requirements tab (or
          requirements-locked page), since it has no relevance to Quantity
          Rules. */}
      {activeTab === 'requirements' && (
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
      )}

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
