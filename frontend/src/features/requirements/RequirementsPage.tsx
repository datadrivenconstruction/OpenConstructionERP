import { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  ClipboardCheck,
  Plus,
  Search,
  ChevronDown,
  ChevronRight,
  Play,
  CheckCircle2,
  XCircle,
  Circle,
  Trash2,
  X,
  Upload,
  Link2,
  Filter,
  Edit3,
  Download,
  FileSpreadsheet,
  FileJson,
  FileText,
  AlertCircle,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ViewInBIMButton, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchRequirementSets,
  fetchRequirementSetDetail,
  fetchRequirementStats,
  createRequirementSet,
  deleteRequirementSet,
  addRequirement,
  updateRequirement,
  deleteRequirement,
  runGate,
  importFromText,
  exportRequirementsCSV,
  exportRequirementsExcel,
  exportRequirementsJSON,
} from './api';
import type {
  Requirement,
  GateResult,
  RequirementStats,
  AddRequirementPayload,
  UpdateRequirementPayload,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  currency: string;
}

const CATEGORIES = [
  'structural',
  'fire_safety',
  'thermal',
  'acoustic',
  'waterproofing',
  'electrical',
  'mechanical',
  'architectural',
] as const;

const PRIORITIES = ['must', 'should', 'may'] as const;

const CONSTRAINT_TYPES = ['equals', 'min', 'max', 'range', 'contains', 'regex'] as const;

const UNITS = [
  'mm', 'm', 'm2', 'm3', 'kg', 'MPa', 'kN', 'kN/m2',
  '\u00B0C', 'dB', 'W/m\u00B2K', '%', 'pcs', 'min', 'h', '-',
] as const;

const ENTITY_SUGGESTIONS = [
  'wall', 'floor', 'roof', 'foundation', 'beam', 'column', 'slab',
  'door', 'window', 'staircase', 'facade', 'ceiling', 'partition',
  'balcony', 'ramp', 'elevator_shaft', 'pipe', 'duct', 'cable_tray',
];

const ATTRIBUTE_SUGGESTIONS = [
  'thickness', 'fire_rating', 'concrete_grade', 'insulation', 'load_capacity',
  'u_value', 'sound_insulation', 'waterproofing_class', 'height', 'width',
  'span', 'depth', 'rebar_grade', 'surface_finish', 'paint_class',
  'material', 'coating', 'compressive_strength', 'tensile_strength',
];

const STATUSES = ['open', 'verified', 'linked', 'conflict'] as const;

const PRIORITY_COLORS: Record<string, 'error' | 'warning' | 'blue'> = {
  must: 'error',
  should: 'warning',
  may: 'blue',
};

const STATUS_COLORS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  open: 'neutral',
  verified: 'success',
  linked: 'blue',
  conflict: 'error',
};

const GATE_DEFS = [
  { number: 1, nameKey: 'requirements.gate_completeness', defaultName: 'Completeness', descKey: 'requirements.gate_completeness_desc', defaultDesc: 'All fields filled' },
  { number: 2, nameKey: 'requirements.gate_consistency', defaultName: 'Consistency', descKey: 'requirements.gate_consistency_desc', defaultDesc: 'No conflicts' },
  { number: 3, nameKey: 'requirements.gate_coverage', defaultName: 'Coverage', descKey: 'requirements.gate_coverage_desc', defaultDesc: 'BOQ positions linked' },
  { number: 4, nameKey: 'requirements.gate_compliance', defaultName: 'Compliance', descKey: 'requirements.gate_compliance_desc', defaultDesc: 'Standard met' },
];

/* ── Styling helpers ──────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Gate Pipeline Visual ─────────────────────────────────────────────── */

function GatePipeline({
  gates,
  onRunGate,
  runningGate,
}: {
  gates: GateResult[];
  onRunGate: (gateNum: number) => void;
  runningGate: number | null;
}) {
  const { t } = useTranslation();

  const gateMap = useMemo(() => {
    const m: Record<number, GateResult> = {};
    for (const g of gates) m[g.gate_number] = g;
    return m;
  }, [gates]);

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {GATE_DEFS.map((def, idx) => {
        const gate = gateMap[def.number];
        const status = gate?.status || 'pending';
        const score = gate?.score ?? 0;

        const statusIcon =
          status === 'pass' ? (
            <CheckCircle2 size={20} className="text-[#15803d]" />
          ) : status === 'fail' ? (
            <XCircle size={20} className="text-semantic-error" />
          ) : status === 'warning' ? (
            <CheckCircle2 size={20} className="text-[#b45309]" />
          ) : (
            <Circle size={20} className="text-content-quaternary" />
          );

        const borderColor =
          status === 'pass'
            ? 'border-[#15803d]/30'
            : status === 'fail'
              ? 'border-semantic-error/30'
              : status === 'warning'
                ? 'border-[#b45309]/30'
                : 'border-border';

        const bgGlow =
          status === 'pass'
            ? 'bg-green-50/50 dark:bg-green-950/20'
            : status === 'fail'
              ? 'bg-red-50/50 dark:bg-red-950/20'
              : status === 'warning'
                ? 'bg-amber-50/50 dark:bg-amber-950/20'
                : 'bg-surface-primary';

        return (
          <div key={def.number} className="relative">
            {/* Connector arrow between cards */}
            {idx < GATE_DEFS.length - 1 && (
              <div className="hidden lg:flex absolute -right-3 top-1/2 -translate-y-1/2 z-10">
                <ChevronRight size={20} className="text-content-quaternary" />
              </div>
            )}
            <Card
              className={clsx(
                'p-4 transition-all duration-200 animate-card-in',
                borderColor,
                bgGlow,
              )}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  {statusIcon}
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                      {t('requirements.gate_label', {
                        defaultValue: 'Gate {{num}}',
                        num: def.number,
                      })}
                    </p>
                    <p className="text-sm font-medium text-content-primary">
                      {t(def.nameKey, { defaultValue: def.defaultName })}
                    </p>
                  </div>
                </div>
              </div>
              <p className="text-xs text-content-tertiary mb-3">
                {t(def.descKey, { defaultValue: def.defaultDesc })}
              </p>
              <div className="flex items-center justify-between">
                {/* Score bar */}
                <div className="flex-1 mr-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-2xs text-content-tertiary">
                      {t('requirements.score', { defaultValue: 'Score' })}
                    </span>
                    <span
                      className={clsx(
                        'text-xs font-bold tabular-nums',
                        status === 'pass'
                          ? 'text-[#15803d]'
                          : status === 'fail'
                            ? 'text-semantic-error'
                            : status === 'warning'
                              ? 'text-[#b45309]'
                              : 'text-content-tertiary',
                      )}
                    >
                      {Math.round(Number(score))}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-surface-secondary overflow-hidden">
                    <div
                      className={clsx(
                        'h-full rounded-full transition-all duration-500',
                        status === 'pass'
                          ? 'bg-[#15803d]'
                          : status === 'fail'
                            ? 'bg-semantic-error'
                            : status === 'warning'
                              ? 'bg-[#b45309]'
                              : 'bg-content-quaternary',
                      )}
                      style={{ width: `${Math.round(Number(score))}%` }}
                    />
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onRunGate(def.number)}
                  disabled={runningGate !== null}
                  className="shrink-0 whitespace-nowrap"
                >
                  {runningGate === def.number ? (
                    <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent mr-1 shrink-0" />
                  ) : (
                    <Play size={14} className="mr-1 shrink-0" />
                  )}
                  <span className="whitespace-nowrap">{t('requirements.run', { defaultValue: 'Run' })}</span>
                </Button>
              </div>
            </Card>
          </div>
        );
      })}
    </div>
  );
}

/* ── Stats Cards ──────────────────────────────────────────────────────── */

function StatsCards({ stats }: { stats: RequirementStats | undefined }) {
  const { t } = useTranslation();

  const mustCount = stats?.by_priority?.must ?? 0;
  const shouldCount = stats?.by_priority?.should ?? 0;
  const mayCount = stats?.by_priority?.may ?? 0;

  const openCount = stats?.by_status?.open ?? 0;
  const verifiedCount = stats?.by_status?.verified ?? 0;
  const linkedCount = stats?.by_status?.linked ?? 0;

  const totalReqs = stats?.total_requirements ?? 0;
  const linked = stats?.linked_count ?? 0;
  const coveragePercent = totalReqs > 0 ? Math.round((linked / totalReqs) * 100) : 0;

  const items = [
    {
      label: t('requirements.stat_total', { defaultValue: 'Total Requirements' }),
      value: totalReqs,
      cls: 'text-content-primary',
    },
    {
      label: t('requirements.stat_priority', { defaultValue: 'By Priority' }),
      value: `${mustCount} / ${shouldCount} / ${mayCount}`,
      sub: t('requirements.stat_priority_labels', {
        defaultValue: 'Must / Should / May',
      }),
      cls: 'text-content-primary',
    },
    {
      label: t('requirements.stat_status', { defaultValue: 'By Status' }),
      value: `${openCount} / ${verifiedCount} / ${linkedCount}`,
      sub: t('requirements.stat_status_labels', {
        defaultValue: 'Open / Verified / Linked',
      }),
      cls: 'text-content-primary',
    },
    {
      label: t('requirements.stat_coverage', { defaultValue: 'Coverage' }),
      value: `${coveragePercent}%`,
      cls:
        coveragePercent >= 80
          ? 'text-[#15803d]'
          : coveragePercent >= 50
            ? 'text-[#b45309]'
            : 'text-semantic-error',
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {items.map((item) => (
        <Card key={item.label} className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">{item.label}</p>
          <p className={clsx('text-lg font-semibold mt-1 tabular-nums', item.cls)}>
            {item.value}
          </p>
          {'sub' in item && item.sub && (
            <p className="text-2xs text-content-quaternary mt-0.5">{item.sub}</p>
          )}
        </Card>
      ))}
    </div>
  );
}

/* ── Autocomplete Input ───────────────────────────────────────────────── */

function AutocompleteInput({
  value,
  onChange,
  suggestions,
  placeholder,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  suggestions: string[];
  placeholder?: string;
  className?: string;
}) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  const filtered = useMemo(
    () =>
      value.trim()
        ? suggestions.filter((s) => s.toLowerCase().includes(value.toLowerCase()))
        : suggestions,
    [value, suggestions],
  );

  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setShowSuggestions(true)}
        onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
        placeholder={placeholder}
        className={className || inputCls}
      />
      {showSuggestions && filtered.length > 0 && (
        <ul className="absolute z-20 top-full left-0 right-0 mt-1 max-h-40 overflow-y-auto rounded-lg border border-border bg-surface-primary shadow-lg">
          {filtered.slice(0, 10).map((s) => (
            <li key={s}>
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChange(s);
                  setShowSuggestions(false);
                }}
                className="w-full text-left px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              >
                {s}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── Add/Edit Requirement Modal ───────────────────────────────────────── */

interface RequirementFormData {
  entity: string;
  attribute: string;
  constraint_type: string;
  constraint_value: string;
  unit: string;
  category: string;
  priority: string;
  source_ref: string;
  notes: string;
}

const EMPTY_FORM: RequirementFormData = {
  entity: '',
  attribute: '',
  constraint_type: 'min',
  constraint_value: '',
  unit: 'mm',
  category: 'structural',
  priority: 'must',
  source_ref: '',
  notes: '',
};

function RequirementModal({
  mode,
  initial,
  onClose,
  onSubmit,
  isPending,
}: {
  mode: 'add' | 'edit';
  initial?: RequirementFormData;
  onClose: () => void;
  onSubmit: (data: RequirementFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [f, setF] = useState<RequirementFormData>(initial || EMPTY_FORM);
  const set = (k: keyof RequirementFormData, v: string) =>
    setF((prev) => ({ ...prev, [k]: v }));

  const isValid = f.entity.trim() && f.attribute.trim() && f.constraint_value.trim();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-xl bg-surface-primary p-6 shadow-xl border border-border max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-content-primary">
            {mode === 'add'
              ? t('requirements.add_requirement', { defaultValue: 'Add Requirement' })
              : t('requirements.edit_requirement', { defaultValue: 'Edit Requirement' })}
          </h2>
          <button
            onClick={onClose}
            className="text-content-tertiary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          {/* Entity */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('requirements.entity', { defaultValue: 'Entity' })} *
            </label>
            <AutocompleteInput
              value={f.entity}
              onChange={(v) => set('entity', v)}
              suggestions={ENTITY_SUGGESTIONS}
              placeholder={t('requirements.entity_placeholder', {
                defaultValue: 'e.g. wall, floor, roof',
              })}
            />
          </div>

          {/* Attribute */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('requirements.attribute', { defaultValue: 'Attribute' })} *
            </label>
            <AutocompleteInput
              value={f.attribute}
              onChange={(v) => set('attribute', v)}
              suggestions={ATTRIBUTE_SUGGESTIONS}
              placeholder={t('requirements.attribute_placeholder', {
                defaultValue: 'e.g. thickness, fire_rating',
              })}
            />
          </div>

          {/* Constraint Type + Value */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('requirements.constraint_type', { defaultValue: 'Constraint Type' })}
              </label>
              <select
                value={f.constraint_type}
                onChange={(e) => set('constraint_type', e.target.value)}
                className={inputCls}
              >
                {CONSTRAINT_TYPES.map((ct) => (
                  <option key={ct} value={ct}>
                    {t(`requirements.ct_${ct}`, { defaultValue: ct })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('requirements.constraint_value', { defaultValue: 'Value' })} *
              </label>
              <input
                value={f.constraint_value}
                onChange={(e) => set('constraint_value', e.target.value)}
                placeholder={
                  f.constraint_type === 'regex'
                    ? t('requirements.regex_placeholder', {
                        defaultValue: 'e.g. ^F[0-9]+$',
                      })
                    : t('requirements.value_placeholder', {
                        defaultValue: 'e.g. 200, C30/37, F90',
                      })
                }
                className={clsx(inputCls, f.constraint_type === 'regex' && 'font-mono')}
              />
              {f.constraint_type === 'regex' && (
                <p className="mt-1 text-2xs text-content-tertiary">
                  {t('requirements.regex_hint', {
                    defaultValue:
                      'Enter a regular expression pattern, e.g. ^F[0-9]+$',
                  })}
                  {f.constraint_value && (() => {
                    try {
                      new RegExp(f.constraint_value);
                      return (
                        <span className="ml-2 text-[#15803d]">
                          {t('requirements.regex_valid', { defaultValue: 'Valid pattern' })}
                        </span>
                      );
                    } catch {
                      return (
                        <span className="ml-2 text-semantic-error">
                          {t('requirements.regex_invalid', { defaultValue: 'Invalid pattern' })}
                        </span>
                      );
                    }
                  })()}
                </p>
              )}
            </div>
          </div>

          {/* Unit + Category */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('requirements.unit', { defaultValue: 'Unit' })}
              </label>
              <select
                value={f.unit}
                onChange={(e) => set('unit', e.target.value)}
                className={inputCls}
              >
                {UNITS.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('requirements.category', { defaultValue: 'Category' })}
              </label>
              <select
                value={f.category}
                onChange={(e) => set('category', e.target.value)}
                className={inputCls}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {t(`requirements.cat_${c}`, { defaultValue: c.replace(/_/g, ' ') })}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Priority */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-2">
              {t('requirements.priority', { defaultValue: 'Priority' })}
            </label>
            <div className="flex gap-4">
              {PRIORITIES.map((p) => {
                const color =
                  p === 'must'
                    ? 'text-semantic-error border-semantic-error/40 bg-semantic-error-bg'
                    : p === 'should'
                      ? 'text-[#b45309] border-[#b45309]/40 bg-semantic-warning-bg'
                      : 'text-oe-blue border-oe-blue/40 bg-oe-blue-subtle';
                const selected = f.priority === p;
                return (
                  <label
                    key={p}
                    className={clsx(
                      'flex items-center gap-2 px-4 py-2 rounded-lg border cursor-pointer transition-all',
                      selected ? color : 'border-border text-content-secondary hover:border-content-tertiary',
                    )}
                  >
                    <input
                      type="radio"
                      name="priority"
                      value={p}
                      checked={selected}
                      onChange={() => set('priority', p)}
                      className="sr-only"
                    />
                    <span className="text-sm font-medium capitalize">{t(`requirements.priority_${p}`, { defaultValue: p })}</span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Source Reference */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('requirements.source_reference', { defaultValue: 'Source Reference' })}
            </label>
            <input
              value={f.source_ref}
              onChange={(e) => set('source_ref', e.target.value)}
              placeholder={t('requirements.source_placeholder', {
                defaultValue: 'e.g. Drawing A-101, Detail 3',
              })}
              className={inputCls}
            />
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('requirements.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={f.notes}
              onChange={(e) => set('notes', e.target.value)}
              rows={3}
              placeholder={t('requirements.notes_placeholder', {
                defaultValue: 'Additional notes or context...',
              })}
              className={textareaCls}
            />
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!isValid || isPending}
            onClick={() => onSubmit(f)}
          >
            {isPending
              ? t('common.saving', { defaultValue: 'Saving...' })
              : mode === 'add'
                ? t('common.create', { defaultValue: 'Create' })
                : t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Export Dropdown ──────────────────────────────────────────────────── */

function ExportDropdown({
  setId,
  requirements,
  setName,
}: {
  setId: string;
  requirements: Requirement[];
  setName: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const handleExport = useCallback(
    async (format: 'csv' | 'excel' | 'json') => {
      setExporting(true);
      try {
        const safeName = setName.replace(/[^a-zA-Z0-9_-]/g, '_') || 'requirements';
        if (format === 'csv') {
          const blob = await exportRequirementsCSV(setId, requirements);
          triggerDownload(blob, `${safeName}.csv`);
        } else if (format === 'excel') {
          const blob = await exportRequirementsExcel(setId, requirements);
          triggerDownload(blob, `${safeName}.xls`);
        } else {
          const json = await exportRequirementsJSON(setId, requirements);
          const blob = new Blob([json], { type: 'application/json' });
          triggerDownload(blob, `${safeName}.json`);
        }
        addToast({
          type: 'success',
          title: t('requirements.exported', { defaultValue: 'Requirements exported' }),
        });
      } catch (e) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setExporting(false);
        setOpen(false);
      }
    },
    [setId, requirements, setName, addToast, t],
  );

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(!open)}
        disabled={exporting || requirements.length === 0}
        className="shrink-0 whitespace-nowrap"
      >
        {exporting ? (
          <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent mr-1.5 shrink-0" />
        ) : (
          <Download size={14} className="mr-1.5 shrink-0" />
        )}
        <span className="whitespace-nowrap">{t('requirements.export', { defaultValue: 'Export' })}</span>
        <ChevronDown size={12} className="ml-1 shrink-0" />
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-40 w-48 rounded-lg border border-border bg-surface-primary shadow-lg overflow-hidden animate-card-in">
            <button
              onClick={() => handleExport('csv')}
              className="flex items-center gap-2.5 w-full px-3 py-2.5 text-sm text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <FileText size={15} className="text-content-tertiary" />
              {t('requirements.export_csv', { defaultValue: 'Export CSV' })}
            </button>
            <button
              onClick={() => handleExport('excel')}
              className="flex items-center gap-2.5 w-full px-3 py-2.5 text-sm text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <FileSpreadsheet size={15} className="text-content-tertiary" />
              {t('requirements.export_excel', { defaultValue: 'Export Excel' })}
            </button>
            <button
              onClick={() => handleExport('json')}
              className="flex items-center gap-2.5 w-full px-3 py-2.5 text-sm text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <FileJson size={15} className="text-content-tertiary" />
              {t('requirements.export_json', { defaultValue: 'Export JSON' })}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/* ── Import Modal (Tabs: Text / CSV / JSON) ──────────────────────────── */

type ImportTab = 'text' | 'csv' | 'json';

interface ParsedImportRow {
  entity: string;
  attribute: string;
  constraint_type: string;
  constraint_value: string;
  unit: string;
  category: string;
  priority: string;
  source_ref: string;
  notes: string;
}

function parseCSVContent(content: string): ParsedImportRow[] {
  const lines = content.split('\n').map((l) => l.trim()).filter(Boolean);
  if (lines.length < 2) return [];
  const headerLine = lines[0] ?? '';
  const headers = headerLine.split(',').map((h: string) => h.trim().toLowerCase().replace(/^["']|["']$/g, ''));

  const entityIdx = headers.indexOf('entity');
  const attributeIdx = headers.indexOf('attribute');
  const constraintValueIdx = headers.indexOf('constraint_value');
  if (entityIdx < 0 || attributeIdx < 0 || constraintValueIdx < 0) return [];

  const getCol = (row: string[], idx: number) => (idx >= 0 && idx < row.length ? (row[idx] ?? '').replace(/^["']|["']$/g, '').trim() : '');

  const result: ParsedImportRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    // Simple CSV parse (handles quoted fields with commas)
    const row = parseCSVLine(lines[i] ?? '');
    const entity = getCol(row, entityIdx);
    const attribute = getCol(row, attributeIdx);
    const constraintValue = getCol(row, constraintValueIdx);
    if (!entity || !attribute || !constraintValue) continue;

    result.push({
      entity,
      attribute,
      constraint_type: getCol(row, headers.indexOf('constraint_type')) || 'equals',
      constraint_value: constraintValue,
      unit: getCol(row, headers.indexOf('unit')) || '',
      category: getCol(row, headers.indexOf('category')) || 'structural',
      priority: getCol(row, headers.indexOf('priority')) || 'must',
      source_ref: getCol(row, headers.indexOf('source_ref')) || '',
      notes: getCol(row, headers.indexOf('notes')) || '',
    });
  }
  return result;
}

function parseCSVLine(line: string): string[] {
  const result: string[] = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') {
        current += '"';
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        current += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        result.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
  }
  result.push(current);
  return result;
}

function parseJSONContent(content: string): ParsedImportRow[] {
  try {
    const data = JSON.parse(content);
    if (!Array.isArray(data)) return [];
    return data
      .filter(
        (item: Record<string, unknown>) =>
          typeof item === 'object' &&
          item !== null &&
          typeof item.entity === 'string' &&
          typeof item.attribute === 'string' &&
          (typeof item.constraint_value === 'string' || typeof item.constraint_value === 'number'),
      )
      .map((item: Record<string, unknown>) => ({
        entity: String(item.entity || ''),
        attribute: String(item.attribute || ''),
        constraint_type: String(item.constraint_type || 'equals'),
        constraint_value: String(item.constraint_value || ''),
        unit: String(item.unit || ''),
        category: String(item.category || 'structural'),
        priority: String(item.priority || 'must'),
        source_ref: String(item.source_ref || ''),
        notes: String(item.notes || ''),
      }));
  } catch {
    return [];
  }
}

function ImportModal({
  onClose,
  onImportText,
  onImportRows,
  isTextPending,
  isRowsPending,
}: {
  onClose: () => void;
  onImportText: (text: string) => void;
  onImportRows: (rows: AddRequirementPayload[]) => void;
  isTextPending: boolean;
  isRowsPending: boolean;
}) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<ImportTab>('text');
  const [text, setText] = useState('');
  const [csvContent, setCsvContent] = useState('');
  const [jsonContent, setJsonContent] = useState('');
  const [csvParsed, setCsvParsed] = useState<ParsedImportRow[]>([]);
  const [jsonParsed, setJsonParsed] = useState<ParsedImportRow[]>([]);
  const [parseError, setParseError] = useState('');

  const handleFileUpload = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>, type: 'csv' | 'json') => {
      const file = e.target.files?.[0];
      if (!file) return;
      setParseError('');
      const reader = new FileReader();
      reader.onload = (ev) => {
        const content = ev.target?.result as string;
        if (type === 'csv') {
          setCsvContent(content);
          const parsed = parseCSVContent(content);
          setCsvParsed(parsed);
          if (content.trim() && parsed.length === 0) {
            setParseError(
              t('requirements.csv_parse_error', {
                defaultValue:
                  'Could not parse CSV. Required headers: entity, attribute, constraint_value',
              }),
            );
          }
        } else {
          setJsonContent(content);
          const parsed = parseJSONContent(content);
          setJsonParsed(parsed);
          if (content.trim() && parsed.length === 0) {
            setParseError(
              t('requirements.json_parse_error', {
                defaultValue:
                  'Could not parse JSON. Expected an array of objects with entity, attribute, constraint_value fields.',
              }),
            );
          }
        }
      };
      reader.readAsText(file);
    },
    [t],
  );

  const handleImportParsed = useCallback(
    (rows: ParsedImportRow[]) => {
      onImportRows(
        rows.map((r) => ({
          entity: r.entity,
          attribute: r.attribute,
          constraint_type: r.constraint_type,
          constraint_value: r.constraint_value,
          unit: r.unit,
          category: r.category,
          priority: r.priority,
          source_ref: r.source_ref,
          notes: r.notes,
        })),
      );
    },
    [onImportRows],
  );

  const tabCls = (tab: ImportTab) =>
    clsx(
      'px-4 py-2 text-sm font-medium border-b-2 transition-colors',
      activeTab === tab
        ? 'border-oe-blue text-oe-blue'
        : 'border-transparent text-content-tertiary hover:text-content-secondary hover:border-border',
    );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-xl bg-surface-primary p-6 shadow-xl border border-border max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('requirements.import_requirements', {
              defaultValue: 'Import Requirements',
            })}
          </h2>
          <button
            onClick={onClose}
            className="text-content-tertiary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border mb-4">
          <button className={tabCls('text')} onClick={() => { setActiveTab('text'); setParseError(''); }}>
            <FileText size={14} className="inline mr-1.5 -mt-0.5" />
            {t('requirements.tab_text', { defaultValue: 'From Text' })}
          </button>
          <button className={tabCls('csv')} onClick={() => { setActiveTab('csv'); setParseError(''); }}>
            <FileSpreadsheet size={14} className="inline mr-1.5 -mt-0.5" />
            {t('requirements.tab_csv', { defaultValue: 'From CSV' })}
          </button>
          <button className={tabCls('json')} onClick={() => { setActiveTab('json'); setParseError(''); }}>
            <FileJson size={14} className="inline mr-1.5 -mt-0.5" />
            {t('requirements.tab_json', { defaultValue: 'From JSON' })}
          </button>
        </div>

        {/* Text tab (existing) */}
        {activeTab === 'text' && (
          <div>
            <p className="text-sm text-content-tertiary mb-3">
              {t('requirements.import_text_desc', {
                defaultValue:
                  'Paste requirement specifications. Each line should follow the format: entity | attribute | constraint_type | value | unit | category | priority',
              })}
            </p>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={10}
              placeholder={t('requirements.import_placeholder', {
                defaultValue:
                  'wall | thickness | min | 200 | mm | structural | must\nroof | u_value | max | 0.20 | W/m\u00B2K | thermal | must',
              })}
              className={textareaCls + ' font-mono text-xs'}
            />
            <div className="mt-4 flex justify-end gap-3">
              <Button variant="ghost" onClick={onClose}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={!text.trim() || isTextPending}
                onClick={() => onImportText(text)}
              >
                {isTextPending
                  ? t('common.importing', { defaultValue: 'Importing...' })
                  : t('common.import', { defaultValue: 'Import' })}
              </Button>
            </div>
          </div>
        )}

        {/* CSV tab */}
        {activeTab === 'csv' && (
          <div>
            <p className="text-sm text-content-tertiary mb-3">
              {t('requirements.import_csv_desc', {
                defaultValue:
                  'Upload a CSV file with headers. Required columns: entity, attribute, constraint_value. Optional: constraint_type, unit, category, priority, source_ref, notes.',
              })}
            </p>
            <label className="flex items-center justify-center w-full h-24 border-2 border-dashed border-border rounded-lg cursor-pointer hover:border-oe-blue/50 hover:bg-surface-secondary/30 transition-colors">
              <div className="text-center">
                <Upload size={20} className="mx-auto mb-1 text-content-tertiary" />
                <span className="text-sm text-content-tertiary">
                  {csvContent
                    ? t('requirements.csv_loaded', {
                        defaultValue: '{{count}} rows parsed',
                        count: csvParsed.length,
                      })
                    : t('requirements.click_to_upload_csv', {
                        defaultValue: 'Click to upload CSV file',
                      })}
                </span>
              </div>
              <input
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => handleFileUpload(e, 'csv')}
              />
            </label>

            {parseError && (
              <div className="mt-3 flex items-start gap-2 text-sm text-semantic-error bg-semantic-error-bg border border-semantic-error/20 rounded-lg px-3 py-2">
                <AlertCircle size={16} className="shrink-0 mt-0.5" />
                {parseError}
              </div>
            )}

            {/* Preview table */}
            {csvParsed.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-medium text-content-secondary mb-2">
                  {t('requirements.preview', {
                    defaultValue: 'Preview ({{count}} rows)',
                    count: csvParsed.length,
                  })}
                </p>
                <div className="max-h-48 overflow-auto border border-border rounded-lg">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-surface-secondary/50 border-b border-border">
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.entity', { defaultValue: 'Entity' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.attribute', { defaultValue: 'Attribute' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.constraint_type', { defaultValue: 'Type' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.constraint_value', { defaultValue: 'Value' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.unit', { defaultValue: 'Unit' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.priority', { defaultValue: 'Priority' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {csvParsed.slice(0, 10).map((row, idx) => (
                        <tr key={`${row.entity}-${row.attribute}-${idx}`} className="border-b border-border last:border-0">
                          <td className="px-2 py-1 text-content-primary">{row.entity}</td>
                          <td className="px-2 py-1 text-content-secondary font-mono">{row.attribute}</td>
                          <td className="px-2 py-1 text-content-secondary">{row.constraint_type}</td>
                          <td className="px-2 py-1 text-content-primary tabular-nums">{row.constraint_value}</td>
                          <td className="px-2 py-1 text-content-secondary">{row.unit}</td>
                          <td className="px-2 py-1 text-content-secondary">{row.priority}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {csvParsed.length > 10 && (
                    <p className="text-2xs text-content-tertiary text-center py-1.5">
                      {t('requirements.and_more', {
                        defaultValue: '... and {{count}} more',
                        count: csvParsed.length - 10,
                      })}
                    </p>
                  )}
                </div>
              </div>
            )}

            <div className="mt-4 flex justify-end gap-3">
              <Button variant="ghost" onClick={onClose}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={csvParsed.length === 0 || isRowsPending}
                onClick={() => handleImportParsed(csvParsed)}
              >
                {isRowsPending
                  ? t('common.importing', { defaultValue: 'Importing...' })
                  : t('requirements.import_count', {
                      defaultValue: 'Import {{count}} requirements',
                      count: csvParsed.length,
                    })}
              </Button>
            </div>
          </div>
        )}

        {/* JSON tab */}
        {activeTab === 'json' && (
          <div>
            <p className="text-sm text-content-tertiary mb-3">
              {t('requirements.import_json_desc', {
                defaultValue:
                  'Upload a JSON file containing an array of requirement objects. Each object must have: entity, attribute, constraint_value.',
              })}
            </p>
            <label className="flex items-center justify-center w-full h-24 border-2 border-dashed border-border rounded-lg cursor-pointer hover:border-oe-blue/50 hover:bg-surface-secondary/30 transition-colors">
              <div className="text-center">
                <Upload size={20} className="mx-auto mb-1 text-content-tertiary" />
                <span className="text-sm text-content-tertiary">
                  {jsonContent
                    ? t('requirements.json_loaded', {
                        defaultValue: '{{count}} items parsed',
                        count: jsonParsed.length,
                      })
                    : t('requirements.click_to_upload_json', {
                        defaultValue: 'Click to upload JSON file',
                      })}
                </span>
              </div>
              <input
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(e) => handleFileUpload(e, 'json')}
              />
            </label>

            {parseError && (
              <div className="mt-3 flex items-start gap-2 text-sm text-semantic-error bg-semantic-error-bg border border-semantic-error/20 rounded-lg px-3 py-2">
                <AlertCircle size={16} className="shrink-0 mt-0.5" />
                {parseError}
              </div>
            )}

            {/* Preview table */}
            {jsonParsed.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-medium text-content-secondary mb-2">
                  {t('requirements.preview', {
                    defaultValue: 'Preview ({{count}} rows)',
                    count: jsonParsed.length,
                  })}
                </p>
                <div className="max-h-48 overflow-auto border border-border rounded-lg">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-surface-secondary/50 border-b border-border">
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.entity', { defaultValue: 'Entity' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.attribute', { defaultValue: 'Attribute' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.constraint_type', { defaultValue: 'Type' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.constraint_value', { defaultValue: 'Value' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.unit', { defaultValue: 'Unit' })}
                        </th>
                        <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                          {t('requirements.priority', { defaultValue: 'Priority' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {jsonParsed.slice(0, 10).map((row, idx) => (
                        <tr key={`${row.entity}-${row.attribute}-${idx}`} className="border-b border-border last:border-0">
                          <td className="px-2 py-1 text-content-primary">{row.entity}</td>
                          <td className="px-2 py-1 text-content-secondary font-mono">{row.attribute}</td>
                          <td className="px-2 py-1 text-content-secondary">{row.constraint_type}</td>
                          <td className="px-2 py-1 text-content-primary tabular-nums">{row.constraint_value}</td>
                          <td className="px-2 py-1 text-content-secondary">{row.unit}</td>
                          <td className="px-2 py-1 text-content-secondary">{row.priority}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {jsonParsed.length > 10 && (
                    <p className="text-2xs text-content-tertiary text-center py-1.5">
                      {t('requirements.and_more', {
                        defaultValue: '... and {{count}} more',
                        count: jsonParsed.length - 10,
                      })}
                    </p>
                  )}
                </div>
              </div>
            )}

            <div className="mt-4 flex justify-end gap-3">
              <Button variant="ghost" onClick={onClose}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={jsonParsed.length === 0 || isRowsPending}
                onClick={() => handleImportParsed(jsonParsed)}
              >
                {isRowsPending
                  ? t('common.importing', { defaultValue: 'Importing...' })
                  : t('requirements.import_count', {
                      defaultValue: 'Import {{count}} requirements',
                      count: jsonParsed.length,
                    })}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Create Set Modal ─────────────────────────────────────────────────── */

function CreateSetModal({
  projectId,
  onClose,
  onCreated,
}: {
  projectId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');

  const mut = useMutation({
    mutationFn: () =>
      createRequirementSet({ project_id: projectId, name, description: desc }),
    onSuccess: () => {
      onCreated();
      onClose();
      addToast({
        type: 'success',
        title: t('requirements.set_created', { defaultValue: 'Requirement set created' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-xl bg-surface-primary p-6 shadow-xl border border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('requirements.new_set', { defaultValue: 'New Requirement Set' })}
          </h2>
          <button onClick={onClose} className="text-content-tertiary hover:text-content-primary">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('common.name', { defaultValue: 'Name' })} *
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('requirements.set_name_placeholder', {
                defaultValue: 'e.g. Structural Requirements Phase 1',
              })}
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('common.description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              rows={3}
              className={textareaCls}
            />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!name.trim() || mut.isPending}
            onClick={() => mut.mutate()}
          >
            {mut.isPending
              ? t('common.creating', { defaultValue: 'Creating...' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Expanded Row Detail ──────────────────────────────────────────────── */

function ExpandedRow({ req }: { req: Requirement }) {
  const { t } = useTranslation();
  // Pull pinned BIM elements out of metadata.bim_element_ids — the same
  // array linkRequirementToBIMElements writes via PATCH /bim-links.
  const bimIds = useMemo<string[]>(() => {
    const raw = (req.metadata as Record<string, unknown> | undefined)?.[
      'bim_element_ids'
    ];
    if (!Array.isArray(raw)) return [];
    return raw.filter((x): x is string => typeof x === 'string' && x.length > 0);
  }, [req.metadata]);

  return (
    <tr className="bg-surface-secondary/30">
      <td colSpan={11} className="px-6 py-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-1">
              {t('requirements.source_reference', { defaultValue: 'Source Reference' })}
            </p>
            <p className="text-content-primary">
              {req.source_ref || t('common.none', { defaultValue: 'None' })}
            </p>
          </div>
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-1">
              {t('requirements.linked_position', { defaultValue: 'Linked BOQ Position' })}
            </p>
            <p className="text-content-primary">
              {req.linked_position_id ? (
                <span className="inline-flex items-center gap-1">
                  <Link2 size={12} className="text-oe-blue" />
                  {req.linked_position_id}
                </span>
              ) : (
                t('requirements.not_linked', { defaultValue: 'Not linked' })
              )}
            </p>
          </div>
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-1">
              {t('requirements.linked_bim', { defaultValue: 'Pinned BIM elements' })}
            </p>
            {bimIds.length > 0 ? (
              <ViewInBIMButton
                elementIds={bimIds}
                className="inline-flex items-center gap-1 text-violet-700 dark:text-violet-300 hover:underline"
              />
            ) : (
              <span className="text-content-tertiary italic">
                {t('common.none', { defaultValue: 'None' })}
              </span>
            )}
          </div>
          {req.notes && (
            <div className="sm:col-span-3">
              <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-1">
                {t('requirements.notes', { defaultValue: 'Notes' })}
              </p>
              <p className="text-content-primary whitespace-pre-wrap">{req.notes}</p>
            </div>
          )}
        </div>
      </td>
    </tr>
  );
}

/* ── Main Page ────────────────────────────────────────────────────────── */

export function RequirementsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { confirm, ...confirmProps } = useConfirm();

  // State
  const [showCreateSet, setShowCreateSet] = useState(false);
  const [showAddReq, setShowAddReq] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [editingReq, setEditingReq] = useState<Requirement | null>(null);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterPriority, setFilterPriority] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [runningGate, setRunningGate] = useState<number | null>(null);
  const [activeSetId, setActiveSetId] = useState<string | null>(null);

  // Deep-link auto-expand: Cmd+Shift+K global search and the BIM viewer
  // both deep-link here with `?id=<requirement_id>`.  When that param
  // is present we look the requirement up across every set, switch to
  // the owning set, expand the row and clear the param.
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkReqId = searchParams.get('id');

  // Data queries
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';

  const { data: sets = [], isLoading: setsLoading } = useQuery({
    queryKey: ['requirement-sets', projectId],
    queryFn: () => fetchRequirementSets(projectId),
    enabled: !!projectId,
  });

  // Auto-select first set
  const currentSetId = activeSetId || sets[0]?.id || '';
  const currentSet = useMemo(
    () => sets.find((s) => s.id === currentSetId),
    [sets, currentSetId],
  );

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ['requirement-set-detail', currentSetId],
    queryFn: () => fetchRequirementSetDetail(currentSetId),
    enabled: !!currentSetId,
  });

  const { data: stats } = useQuery({
    queryKey: ['requirement-stats', projectId],
    queryFn: () => fetchRequirementStats(projectId),
    enabled: !!projectId,
  });

  const requirements = detail?.requirements || [];
  const gates = detail?.gate_results || [];

  // Resolve a deep-link `?id=` against the active set's requirements.
  // If the requirement belongs to a different set, switch to it; the
  // effect re-fires once the new detail loads and finally expands the
  // row.  We strip the param at the end so refresh doesn't reapply.
  useEffect(() => {
    if (!deepLinkReqId) return;
    // Pass 1: requirement is already in the loaded detail → expand it.
    const found = requirements.find((r) => r.id === deepLinkReqId);
    if (found) {
      setExpandedRowId(found.id);
      const next = new URLSearchParams(searchParams);
      next.delete('id');
      setSearchParams(next, { replace: true });
      return;
    }
    // Pass 2: requirement might live in a different set — fan out a
    // one-shot detail fetch over every set, switch the UI to the
    // owning set when found, and let the effect re-fire on Pass 1.
    if (sets.length === 0) return;
    let cancelled = false;
    (async () => {
      for (const s of sets) {
        if (cancelled) break;
        if (s.id === currentSetId) continue; // already searched
        try {
          const d = await fetchRequirementSetDetail(s.id);
          const hit = (d.requirements ?? []).find((r) => r.id === deepLinkReqId);
          if (hit) {
            setActiveSetId(s.id);
            return;
          }
        } catch {
          // ignore individual set failures
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    deepLinkReqId,
    requirements,
    sets,
    currentSetId,
    searchParams,
    setSearchParams,
  ]);

  // Filtered requirements
  const filteredReqs = useMemo(() => {
    let result = requirements;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (r) =>
          r.entity.toLowerCase().includes(q) ||
          r.attribute.toLowerCase().includes(q) ||
          r.constraint_value.toLowerCase().includes(q),
      );
    }
    if (filterCategory) result = result.filter((r) => r.category === filterCategory);
    if (filterPriority) result = result.filter((r) => r.priority === filterPriority);
    if (filterStatus) result = result.filter((r) => r.status === filterStatus);
    return result;
  }, [requirements, searchQuery, filterCategory, filterPriority, filterStatus]);

  // Invalidation helpers
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['requirement-sets'] });
    qc.invalidateQueries({ queryKey: ['requirement-set-detail'] });
    qc.invalidateQueries({ queryKey: ['requirement-stats'] });
  }, [qc]);

  // Mutations
  const addMut = useMutation({
    mutationFn: (data: AddRequirementPayload) => addRequirement(currentSetId, data),
    onSuccess: () => {
      invalidateAll();
      setShowAddReq(false);
      addToast({
        type: 'success',
        title: t('requirements.req_added', { defaultValue: 'Requirement added' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const editMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateRequirementPayload }) =>
      updateRequirement(currentSetId, id, data),
    onSuccess: () => {
      invalidateAll();
      setEditingReq(null);
      addToast({
        type: 'success',
        title: t('requirements.req_updated', { defaultValue: 'Requirement updated' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const delMut = useMutation({
    mutationFn: (reqId: string) => deleteRequirement(currentSetId, reqId),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('requirements.req_deleted', { defaultValue: 'Requirement deleted' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const delSetMut = useMutation({
    mutationFn: (setId: string) => deleteRequirementSet(setId),
    onSuccess: () => {
      invalidateAll();
      setActiveSetId(null);
      addToast({
        type: 'success',
        title: t('requirements.set_deleted', { defaultValue: 'Requirement set deleted' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const importMut = useMutation({
    mutationFn: (text: string) => importFromText(currentSetId, text),
    onSuccess: (result) => {
      invalidateAll();
      setShowImport(false);
      addToast({
        type: 'success',
        title: t('requirements.imported', {
          defaultValue: '{{count}} requirements imported',
          count: result?.requirements?.length ?? 0,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const bulkImportMut = useMutation({
    mutationFn: async (rows: AddRequirementPayload[]) => {
      const results = [];
      for (const row of rows) {
        results.push(await addRequirement(currentSetId, row));
      }
      return results;
    },
    onSuccess: (results) => {
      invalidateAll();
      setShowImport(false);
      addToast({
        type: 'success',
        title: t('requirements.imported', {
          defaultValue: '{{count}} requirements imported',
          count: results.length,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  // Run gate handler
  const handleRunGate = useCallback(
    async (gateNum: number) => {
      if (!currentSetId) return;
      setRunningGate(gateNum);
      try {
        const result = await runGate(currentSetId, gateNum);
        invalidateAll();
        addToast({
          type: result.status === 'pass' ? 'success' : result.status === 'fail' ? 'error' : result.status === 'warning' ? 'warning' : 'info',
          title: t('requirements.gate_result', {
            defaultValue: 'Gate {{num}}: {{status}}',
            num: gateNum,
            status: result.status,
          }),
          message:
            result.findings && result.findings.length > 0
              ? result.findings.slice(0, 3).map((f) => f.message || f.detail || JSON.stringify(f)).join('; ')
              : undefined,
        });
      } catch (e) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setRunningGate(null);
      }
    },
    [currentSetId, invalidateAll, addToast, t],
  );

  // Loading state
  const isLoading = setsLoading || detailLoading;

  return (
    <div className="mx-auto max-w-6xl px-6 py-6 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          {
            label: t('requirements.title', {
              defaultValue: 'Requirements & Quality Gates',
            }),
          },
        ]}
      />

      {/* ── Header: single compact row ─────────────────────────────────── */}
      <div className="mt-3 flex items-center justify-between gap-2 overflow-x-auto">
        {/* Left: title */}
        <h1 className="text-lg font-bold text-content-primary flex items-center gap-2 shrink-0 whitespace-nowrap">
          <ClipboardCheck size={18} className="text-oe-blue shrink-0" />
          <span className="hidden sm:inline">{t('requirements.title', { defaultValue: 'Requirements & Quality Gates' })}</span>
          <span className="sm:hidden">{t('requirements.title_short', { defaultValue: 'Requirements' })}</span>
        </h1>

        {/* Right: selectors + New Set */}
        <div className="flex items-center gap-2 shrink-0">
          {projects.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                const p = projects.find((p) => p.id === e.target.value);
                if (p) useProjectContextStore.getState().setActiveProject(p.id, p.name);
              }}
              className={inputCls + ' !h-8 !text-xs max-w-[180px]'}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          {sets.length > 0 && (
            <select
              value={currentSetId}
              onChange={(e) => setActiveSetId(e.target.value)}
              className={inputCls + ' !h-8 !text-xs max-w-[180px]'}
            >
              {sets.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          )}
          <Button variant="primary" size="sm" onClick={() => setShowCreateSet(true)} disabled={!projectId} className="shrink-0 whitespace-nowrap">
            <Plus size={14} className="mr-1 shrink-0" />
            <span className="whitespace-nowrap">{t('requirements.new_set', { defaultValue: 'New Set' })}</span>
          </Button>
        </div>
      </div>

      {/* No project selected */}
      {!projectId && (
        <div className="mt-6">
          <EmptyState
            icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
            title={t('requirements.no_project', { defaultValue: 'No project selected' })}
            description={t('requirements.no_project_desc', {
              defaultValue: 'Select a project from the dropdown above to view and manage requirements and quality gates.',
            })}
          />
        </div>
      )}

      {/* Gate Pipeline */}
      {projectId && currentSetId && (
        <div className="mt-6">
          <GatePipeline gates={gates} onRunGate={handleRunGate} runningGate={runningGate} />
        </div>
      )}

      {/* Stats */}
      {projectId && (
      <div className="mt-6">
        <StatsCards stats={stats} />
      </div>
      )}

      {/* Toolbar — single row, no wrapping */}
      {currentSetId && (
        <div className="mt-6 flex items-center gap-2 flex-nowrap overflow-x-auto">
          {/* Search */}
          <div className="relative flex-1 min-w-[180px] max-w-sm">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('requirements.search', {
                defaultValue: 'Search entity, attribute, value...',
              })}
              className={inputCls + ' pl-9'}
            />
          </div>

          {/* Filter toggle */}
          <Button
            variant={showFilters ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setShowFilters(!showFilters)}
            className="shrink-0 whitespace-nowrap"
          >
            <Filter size={14} className="mr-1.5 shrink-0" />
            <span className="whitespace-nowrap">{t('common.filters', { defaultValue: 'Filters' })}</span>
            {(filterCategory || filterPriority || filterStatus) && (
              <span className="ml-1 flex h-4 w-4 items-center justify-center rounded-full bg-oe-blue text-white text-2xs">
                {[filterCategory, filterPriority, filterStatus].filter(Boolean).length}
              </span>
            )}
          </Button>

          {/* Spacer */}
          <div className="flex-1 min-w-0" />

          {/* Action buttons: icon-only on mobile, icon+text on desktop */}
          <ExportDropdown
            setId={currentSetId}
            requirements={requirements}
            setName={currentSet?.name || 'requirements'}
          />
          <Button variant="ghost" size="sm" onClick={() => setShowImport(true)} className="shrink-0 whitespace-nowrap">
            <Upload size={14} className="mr-1.5 shrink-0" />
            <span className="whitespace-nowrap">{t('requirements.import', { defaultValue: 'Import' })}</span>
          </Button>
          <Button variant="primary" size="sm" onClick={() => setShowAddReq(true)} className="shrink-0 whitespace-nowrap">
            <Plus size={14} className="mr-1.5 shrink-0" />
            <span className="whitespace-nowrap">{t('requirements.add', { defaultValue: 'Add Requirement' })}</span>
          </Button>
        </div>
      )}

      {/* Filter bar */}
      {showFilters && (
        <div className="mt-3 flex flex-wrap items-center gap-3 animate-card-in">
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className={inputCls + ' max-w-[160px]'}
          >
            <option value="">
              {t('requirements.all_categories', { defaultValue: 'All Categories' })}
            </option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`requirements.cat_${c}`, { defaultValue: c.replace(/_/g, ' ') })}
              </option>
            ))}
          </select>
          <select
            value={filterPriority}
            onChange={(e) => setFilterPriority(e.target.value)}
            className={inputCls + ' max-w-[140px]'}
          >
            <option value="">
              {t('requirements.all_priorities', { defaultValue: 'All Priorities' })}
            </option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {t(`requirements.priority_${p}`, { defaultValue: p })}
              </option>
            ))}
          </select>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className={inputCls + ' max-w-[140px]'}
          >
            <option value="">
              {t('requirements.all_statuses', { defaultValue: 'All Statuses' })}
            </option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`requirements.status_${s}`, { defaultValue: s })}
              </option>
            ))}
          </select>
          {(filterCategory || filterPriority || filterStatus) && (
            <button
              onClick={() => {
                setFilterCategory('');
                setFilterPriority('');
                setFilterStatus('');
              }}
              className="text-xs text-content-tertiary hover:text-content-primary transition-colors underline"
            >
              {t('common.clear_all', { defaultValue: 'Clear all' })}
            </button>
          )}
        </div>
      )}

      {/* Requirements Table */}
      {projectId && (
      <div className="mt-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
          </div>
        ) : !currentSetId || sets.length === 0 ? (
          <Card>
            <EmptyState
              icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
              title={t('requirements.no_sets', {
                defaultValue: 'No requirement sets',
              })}
              description={t('requirements.no_sets_desc', {
                defaultValue:
                  'Create a requirement set to start defining project requirements and quality gates.',
              })}
              action={{
                label: t('requirements.new_set', {
                  defaultValue: 'New Requirement Set',
                }),
                onClick: () => setShowCreateSet(true),
              }}
            />
          </Card>
        ) : filteredReqs.length === 0 && requirements.length === 0 ? (
          <Card>
            <EmptyState
              icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
              title={t('requirements.empty', {
                defaultValue: 'No requirements yet',
              })}
              description={t('requirements.empty_desc', {
                defaultValue:
                  'Add requirements to define Entity-Attribute-Constraint triplets for your project.',
              })}
              action={{
                label: t('requirements.add', {
                  defaultValue: 'Add Requirement',
                }),
                onClick: () => setShowAddReq(true),
              }}
            />
          </Card>
        ) : filteredReqs.length === 0 ? (
          <Card className="p-8 text-center">
            <p className="text-sm text-content-tertiary">
              {t('requirements.no_match', {
                defaultValue: 'No requirements match your filters.',
              })}
            </p>
          </Card>
        ) : (
          <Card className="overflow-hidden animate-card-in">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-surface-secondary/50">
                    <th className="px-4 py-3 text-left font-medium text-content-secondary w-8" />
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('requirements.entity', { defaultValue: 'Entity' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('requirements.attribute', { defaultValue: 'Attribute' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('requirements.constraint', { defaultValue: 'Constraint' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('requirements.unit', { defaultValue: 'Unit' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('requirements.category', { defaultValue: 'Category' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('requirements.priority', { defaultValue: 'Priority' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('common.status', { defaultValue: 'Status' })}
                    </th>
                    <th className="px-4 py-3 text-center font-medium text-content-secondary">
                      {t('requirements.confidence', { defaultValue: 'Conf.' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('requirements.source', { defaultValue: 'Source' })}
                    </th>
                    <th className="px-4 py-3 w-20" />
                  </tr>
                </thead>
                <tbody>
                  {filteredReqs.map((req) => {
                    const isExpanded = expandedRowId === req.id;
                    return (
                      <RequirementRow
                        key={req.id}
                        req={req}
                        isExpanded={isExpanded}
                        onToggleExpand={() =>
                          setExpandedRowId(isExpanded ? null : req.id)
                        }
                        onEdit={() => setEditingReq(req)}
                        onDelete={() => delMut.mutate(req.id)}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>
            {/* Summary footer */}
            <div className="border-t border-border px-4 py-2.5 flex items-center justify-between text-xs text-content-tertiary bg-surface-secondary/30">
              <span>
                {t('requirements.showing', {
                  defaultValue: '{{count}} requirements',
                  count: filteredReqs.length,
                })}
                {filteredReqs.length !== requirements.length &&
                  ` ${t('requirements.of_total', { defaultValue: 'of {{total}}', total: requirements.length })}`}
              </span>
              {currentSet && (
                <button
                  onClick={async () => {
                    const ok = await confirm({
                      title: t('requirements.confirm_delete_set_title', { defaultValue: 'Delete requirement set?' }),
                      message: t('requirements.confirm_delete_set', { defaultValue: 'Delete this requirement set and all its requirements?' }),
                    });
                    if (ok) delSetMut.mutate(currentSetId);
                  }}
                  className="text-content-quaternary hover:text-semantic-error transition-colors"
                  title={t('requirements.delete_set', { defaultValue: 'Delete Set' })}
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          </Card>
        )}
      </div>
      )}

      {/* Modals */}
      {showCreateSet && projectId && (
        <CreateSetModal
          projectId={projectId}
          onClose={() => setShowCreateSet(false)}
          onCreated={invalidateAll}
        />
      )}

      {showAddReq && (
        <RequirementModal
          mode="add"
          onClose={() => setShowAddReq(false)}
          onSubmit={(data) => addMut.mutate(data)}
          isPending={addMut.isPending}
        />
      )}

      {editingReq && (
        <RequirementModal
          mode="edit"
          initial={{
            entity: editingReq.entity,
            attribute: editingReq.attribute,
            constraint_type: editingReq.constraint_type,
            constraint_value: editingReq.constraint_value,
            unit: editingReq.unit,
            category: editingReq.category,
            priority: editingReq.priority,
            source_ref: editingReq.source_ref,
            notes: editingReq.notes,
          }}
          onClose={() => setEditingReq(null)}
          onSubmit={(data) => editMut.mutate({ id: editingReq.id, data })}
          isPending={editMut.isPending}
        />
      )}

      {showImport && (
        <ImportModal
          onClose={() => setShowImport(false)}
          onImportText={(text) => importMut.mutate(text)}
          onImportRows={(rows) => bulkImportMut.mutate(rows)}
          isTextPending={importMut.isPending}
          isRowsPending={bulkImportMut.isPending}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Requirement Table Row ────────────────────────────────────────────── */

function RequirementRow({
  req,
  isExpanded,
  onToggleExpand,
  onEdit,
  onDelete,
}: {
  req: Requirement;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();

  return (
    <>
      <tr
        className="border-b border-border last:border-0 hover:bg-surface-secondary/30 cursor-pointer transition-colors"
        onClick={onToggleExpand}
      >
        {/* Expand chevron */}
        <td className="px-4 py-3">
          <ChevronDown
            size={14}
            className={clsx(
              'text-content-tertiary transition-transform duration-150',
              isExpanded && 'rotate-180',
            )}
          />
        </td>

        {/* Entity */}
        <td className="px-4 py-3 text-content-primary font-medium">
          {req.entity}
        </td>

        {/* Attribute */}
        <td className="px-4 py-3 text-content-secondary font-mono text-xs">
          {req.attribute}
        </td>

        {/* Constraint */}
        <td className="px-4 py-3 text-content-primary tabular-nums">
          <span className="text-2xs text-content-tertiary mr-1">
            {t(`requirements.ct_short_${req.constraint_type}`, {
              defaultValue:
                req.constraint_type === 'min'
                  ? '\u2265'
                  : req.constraint_type === 'max'
                    ? '\u2264'
                    : req.constraint_type === 'equals'
                      ? '='
                      : req.constraint_type === 'range'
                        ? '\u2194'
                        : req.constraint_type === 'regex'
                          ? '/./'
                          : '\u2283',
            })}
          </span>
          {req.constraint_value}
        </td>

        {/* Unit */}
        <td className="px-4 py-3 text-content-secondary text-xs">{req.unit}</td>

        {/* Category */}
        <td className="px-4 py-3">
          <Badge variant="neutral" size="sm">
            {t(`requirements.cat_${req.category}`, {
              defaultValue: req.category.replace(/_/g, ' '),
            })}
          </Badge>
        </td>

        {/* Priority */}
        <td className="px-4 py-3">
          <Badge variant={PRIORITY_COLORS[req.priority] || 'neutral'} size="sm">
            {t(`requirements.priority_${req.priority}`, {
              defaultValue: req.priority,
            })}
          </Badge>
        </td>

        {/* Status */}
        <td className="px-4 py-3">
          <Badge variant={STATUS_COLORS[req.status] || 'neutral'} size="sm" dot>
            {t(`requirements.status_${req.status}`, {
              defaultValue: req.status,
            })}
          </Badge>
        </td>

        {/* Confidence */}
        <td className="px-4 py-3 text-center">
          {req.confidence != null ? (
            <span
              className={clsx(
                'text-xs font-medium tabular-nums',
                req.confidence >= 0.8
                  ? 'text-[#15803d]'
                  : req.confidence >= 0.5
                    ? 'text-[#b45309]'
                    : 'text-semantic-error',
              )}
            >
              {Math.round(req.confidence * 100)}%
            </span>
          ) : (
            <span className="text-xs text-content-quaternary">-</span>
          )}
        </td>

        {/* Source */}
        <td className="px-4 py-3 text-content-tertiary text-xs max-w-[120px] truncate">
          {req.source_ref || '-'}
        </td>

        {/* Actions */}
        <td className="px-4 py-3">
          <div className="flex items-center gap-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
              className="text-content-tertiary hover:text-oe-blue transition-colors p-1"
              title={t('common.edit', { defaultValue: 'Edit' })}
            >
              <Edit3 size={14} />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="text-content-tertiary hover:text-semantic-error transition-colors p-1"
              title={t('common.delete', { defaultValue: 'Delete' })}
            >
              <Trash2 size={14} />
            </button>
          </div>
        </td>
      </tr>
      {isExpanded && <ExpandedRow req={req} />}
    </>
  );
}

export default RequirementsPage;
