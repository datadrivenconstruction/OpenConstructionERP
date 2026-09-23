// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  Boxes,
  AlertTriangle,
  Download,
  Plus,
  X,
  ArrowRight,
  Search,
  Trash2,
  Calendar,
  FileText,
  ShieldCheck,
  Clock,
  CheckCircle2,
  Coins,
  Link2,
  Unlink,
} from 'lucide-react';
import {
  Button,
  Badge,
  EmptyState,
  Breadcrumb,
  DateDisplay,
  ConfirmDialog,
  RecoveryCard,
  SkeletonTable,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo } from '@/shared/ui/DismissibleInfo';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildPrefabInsights } from './prefabInsights';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchPrefabBoard,
  fetchPrefabStats,
  fetchUnitEvents,
  createPrefabUnit,
  advancePrefabUnit,
  deletePrefabUnit,
  linkPrefabUnit,
  fetchProjectBoqs,
  fetchBoqPositions,
  fetchProjectAssemblies,
  nextStage,
  STAGE_ORDER,
  POST_QA_STAGES,
  UNIT_TYPES,
  type PrefabUnit,
  type PrefabStage,
  type PrefabUnitType,
  type PrefabBoardColumn,
  type CreatePrefabUnitPayload,
  type LinkPrefabUnitPayload,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  /** Optional here because this page only needs it to format prefab cost. */
  currency?: string;
}

interface StageMeta {
  label: string;
  dot: string;
  badge: string;
  column: string;
}

const STAGE_META: Record<PrefabStage, StageMeta> = {
  design: {
    label: 'Design',
    dot: 'bg-slate-400',
    badge: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
    column: 'border-slate-300 dark:border-slate-700',
  },
  approved_for_production: {
    label: 'Approved for production',
    dot: 'bg-indigo-400',
    badge: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300',
    column: 'border-indigo-300 dark:border-indigo-800',
  },
  in_production: {
    label: 'In production',
    dot: 'bg-amber-400',
    badge: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
    column: 'border-amber-300 dark:border-amber-800',
  },
  qa: {
    label: 'QA',
    dot: 'bg-purple-400',
    badge: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
    column: 'border-purple-300 dark:border-purple-800',
  },
  dispatched: {
    label: 'Dispatched',
    dot: 'bg-blue-400',
    badge: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
    column: 'border-blue-300 dark:border-blue-800',
  },
  delivered: {
    label: 'Delivered',
    dot: 'bg-teal-400',
    badge: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300',
    column: 'border-teal-300 dark:border-teal-800',
  },
  installed: {
    label: 'Installed',
    dot: 'bg-green-500',
    badge: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
    column: 'border-green-300 dark:border-green-800',
  },
};

const DEFAULT_STAGE_META: StageMeta = {
  label: 'Unknown',
  dot: 'bg-gray-400',
  badge: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  column: 'border-gray-300 dark:border-gray-700',
};

const UNIT_TYPE_LABELS: Record<PrefabUnitType, string> = {
  pod: 'Pod',
  panel: 'Panel',
  module: 'Module',
  skid: 'Skid',
  volumetric: 'Volumetric',
  other: 'Other',
};

function stageMeta(stage: string): StageMeta {
  return (STAGE_META as Record<string, StageMeta>)[stage] ?? DEFAULT_STAGE_META;
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── Install-date risk helpers ─────────────────────────────────────────── */

const DAY_MS = 24 * 60 * 60 * 1000;
/** Upcoming window (calendar days) for the "due soon" lookahead. */
const LOOKAHEAD_DAYS = 14;
/**
 * Production lead time. A unit still in production or QA whose install date
 * falls within this many days is "at risk": it must yet clear QA, dispatch,
 * delivery and install before it can go up on site.
 */
const LEAD_TIME_DAYS = 21;

type RiskFilter = 'all' | 'overdue' | 'due_soon' | 'at_risk';

/** Parse a `YYYY-MM-DD` (or ISO) string to local midnight, or null if unusable. */
function parseInstallDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
}

/** Whole days from today to the install date; negative = past. Null if unset. */
function daysUntilInstall(value: string | null | undefined): number | null {
  const target = parseInstallDate(value);
  if (!target) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today.getTime()) / DAY_MS);
}

/** Dated, not-yet-installed unit whose install date is already in the past. */
function isUnitOverdue(unit: PrefabUnit): boolean {
  if (unit.status === 'installed') return false;
  const days = daysUntilInstall(unit.target_install_date);
  return days != null && days < 0;
}

/** Not-yet-installed unit due today or within the lookahead window. */
function isUnitDueSoon(unit: PrefabUnit): boolean {
  if (unit.status === 'installed') return false;
  const days = daysUntilInstall(unit.target_install_date);
  return days != null && days >= 0 && days <= LOOKAHEAD_DAYS;
}

/** Still in production or QA yet due within the production lead time. */
function isUnitAtRisk(unit: PrefabUnit): boolean {
  if (unit.status !== 'in_production' && unit.status !== 'qa') return false;
  const days = daysUntilInstall(unit.target_install_date);
  return days != null && days <= LEAD_TIME_DAYS;
}

/** Ascending install-date comparator; undated units sort to the bottom. */
function compareByInstallDate(a: PrefabUnit, b: PrefabUnit): number {
  const da = parseInstallDate(a.target_install_date);
  const db = parseInstallDate(b.target_install_date);
  if (da && db) return da.getTime() - db.getTime();
  if (da) return -1;
  if (db) return 1;
  return 0;
}

function matchesRiskFilter(unit: PrefabUnit, filter: RiskFilter): boolean {
  switch (filter) {
    case 'overdue':
      return isUnitOverdue(unit);
    case 'due_soon':
      return isUnitDueSoon(unit);
    case 'at_risk':
      return isUnitAtRisk(unit);
    default:
      return true;
  }
}

/** A compact count tile in the risk strip that doubles as a board filter. */
function RiskTile({
  active,
  count,
  onToggle,
  icon,
  label,
  tone,
  hint,
}: {
  active: boolean;
  count: number;
  onToggle: () => void;
  icon: React.ReactNode;
  label: string;
  tone: 'danger' | 'warning';
  hint?: string;
}) {
  const zero = count === 0;
  const toneActive =
    tone === 'danger'
      ? 'border-red-400 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300'
      : 'border-amber-400 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300';
  const toneIdle =
    tone === 'danger' ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400';
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={zero}
      aria-pressed={active}
      title={hint}
      className={clsx(
        'inline-flex items-center gap-2 rounded-xl border px-3 py-2 shadow-xs transition-colors',
        active ? toneActive : 'border-border-light bg-surface-elevated/90 hover:border-oe-blue/40',
        zero && 'cursor-default opacity-50 hover:border-border-light',
      )}
    >
      <span className={active ? undefined : toneIdle}>{icon}</span>
      <span className="text-lg font-bold tabular-nums">{count}</span>
      <span
        className={clsx(
          'text-2xs font-medium uppercase tracking-wide',
          !active && 'text-content-tertiary',
        )}
      >
        {label}
      </span>
    </button>
  );
}

/* ── Create Unit Modal ─────────────────────────────────────────────────── */

interface UnitFormData {
  ref: string;
  unit_type: PrefabUnitType;
  target_install_date: string;
  drawing_ref: string;
  notes: string;
}

const EMPTY_FORM: UnitFormData = {
  ref: '',
  unit_type: 'module',
  target_install_date: '',
  drawing_ref: '',
  notes: '',
};

function CreateUnitModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: UnitFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<UnitFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof UnitFormData>(key: K, value: UnitFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const refError = touched && form.ref.trim().length === 0;
  const canSubmit = form.ref.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
      <div
        className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto"
        role="dialog"
        aria-label={t('prefab.new_unit', { defaultValue: 'New Unit' })}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('prefab.new_unit', { defaultValue: 'New Unit' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('prefab.field_ref', { defaultValue: 'Unit reference' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                value={form.ref}
                onChange={(e) => {
                  set('ref', e.target.value);
                  setTouched(true);
                }}
                placeholder={t('prefab.ref_placeholder', { defaultValue: 'e.g. POD-L03-14' })}
                className={clsx(
                  inputCls,
                  refError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
                )}
                autoFocus
              />
              {refError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('prefab.ref_required', { defaultValue: 'A unit reference is required' })}
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('prefab.field_type', { defaultValue: 'Unit type' })}
              </label>
              <select
                value={form.unit_type}
                onChange={(e) => set('unit_type', e.target.value as PrefabUnitType)}
                className={inputCls + ' appearance-none'}
              >
                {UNIT_TYPES.map((ty) => (
                  <option key={ty} value={ty}>
                    {t(`prefab.type_${ty}`, { defaultValue: UNIT_TYPE_LABELS[ty] })}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('prefab.field_target_install', { defaultValue: 'Target install date' })}
              </label>
              <input
                type="date"
                value={form.target_install_date}
                onChange={(e) => set('target_install_date', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('prefab.field_drawing_ref', { defaultValue: 'Drawing reference' })}
              </label>
              <input
                value={form.drawing_ref}
                onChange={(e) => set('drawing_ref', e.target.value)}
                placeholder={t('prefab.drawing_placeholder', { defaultValue: 'e.g. A-201 Rev C' })}
                className={inputCls}
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('prefab.field_notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={form.notes}
              onChange={(e) => set('notes', e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('prefab.notes_placeholder', {
                defaultValue: 'Optional notes for this unit...',
              })}
            />
          </div>

          <p className="text-2xs text-content-tertiary">
            {t('prefab.create_starts_in_design', {
              defaultValue:
                'New units start in Design. Move them forward stage by stage from the board.',
            })}
          </p>
        </div>

        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('prefab.create_unit', { defaultValue: 'Create unit' })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Unit Card ─────────────────────────────────────────────────────────── */

const UnitCard = React.memo(function UnitCard({
  unit,
  onOpen,
}: {
  unit: PrefabUnit;
  onOpen: (u: PrefabUnit) => void;
}) {
  const { t } = useTranslation();
  const typeLabel = t(`prefab.type_${unit.unit_type}`, {
    defaultValue: (UNIT_TYPE_LABELS as Record<string, string>)[unit.unit_type] ?? unit.unit_type,
  });
  const overdue = isUnitOverdue(unit);
  const dueSoon = !overdue && isUnitDueSoon(unit);
  const days = daysUntilInstall(unit.target_install_date);
  return (
    <button
      onClick={() => onOpen(unit)}
      className={clsx(
        'w-full text-left rounded-lg border p-3 shadow-xs transition-all hover:shadow-sm',
        overdue
          ? 'border-red-300 bg-red-50/50 hover:border-red-400 dark:border-red-900/50 dark:bg-red-950/15'
          : 'border-border-light bg-surface-primary hover:border-oe-blue/40',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-mono font-semibold text-content-primary truncate">
          {unit.ref}
        </span>
        <Badge variant="neutral" size="sm">
          {typeLabel}
        </Badge>
      </div>
      {unit.notes && (
        <p className="mt-1 text-2xs text-content-tertiary line-clamp-2">{unit.notes}</p>
      )}
      <div className="mt-2 flex items-center gap-3 text-2xs text-content-tertiary">
        {unit.target_install_date && (
          <span
            className={clsx(
              'inline-flex items-center gap-1',
              overdue && 'font-medium text-semantic-error',
              dueSoon && 'font-medium text-amber-600 dark:text-amber-400',
            )}
          >
            {overdue ? <AlertTriangle size={11} /> : <Calendar size={11} />}
            <DateDisplay value={unit.target_install_date} />
          </span>
        )}
        {unit.drawing_ref && (
          <span className="inline-flex items-center gap-1 truncate">
            <FileText size={11} />
            {unit.drawing_ref}
          </span>
        )}
      </div>
      {(overdue || dueSoon) && (
        <div className="mt-2">
          {overdue ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-red-50 px-1.5 py-0.5 text-2xs font-medium text-red-700 dark:bg-red-900/20 dark:text-red-300">
              <AlertTriangle size={11} className="shrink-0" />
              {days != null
                ? t('prefab.overdue_by_days', {
                    defaultValue: 'Overdue by {{count}}d',
                    count: Math.abs(days),
                  })
                : t('prefab.overdue', { defaultValue: 'Overdue' })}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-2xs font-medium text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
              <Clock size={11} className="shrink-0" />
              {days === 0
                ? t('prefab.due_today', { defaultValue: 'Due today' })
                : t('prefab.due_in_days', {
                    defaultValue: 'Due in {{count}}d',
                    count: days ?? 0,
                  })}
            </span>
          )}
        </div>
      )}
      {unit.cost_basis != null && (
        <div className="mt-2 inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-2xs font-medium text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300">
          <Coins size={11} className="shrink-0" />
          <span className="tabular-nums">{unit.cost_basis}</span>
          {unit.earned_value != null && (
            <span className="text-emerald-600/70 dark:text-emerald-400/70">
              {t('prefab.earned_short', { defaultValue: 'earned {{value}}', value: unit.earned_value })}
            </span>
          )}
        </div>
      )}
    </button>
  );
});

/* ── Cost Link Section (link a unit to a BOQ position / assembly) ───────── */

function LinkCostSection({
  unit,
  projectId,
  onLink,
  isLinking,
}: {
  unit: PrefabUnit;
  projectId: string;
  onLink: (payload: LinkPrefabUnitPayload) => void;
  isLinking: boolean;
}) {
  const { t } = useTranslation();
  const isLinked = unit.cost_basis != null || unit.boq_position_id != null || unit.assembly_id != null;
  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<'boq' | 'assembly'>('boq');
  const [boqId, setBoqId] = useState('');
  const [positionId, setPositionId] = useState('');
  const [assemblyId, setAssemblyId] = useState('');

  const { data: boqs = [] } = useQuery({
    queryKey: ['prefab-link-boqs', projectId],
    queryFn: () => fetchProjectBoqs(projectId),
    enabled: editing && mode === 'boq' && !!projectId,
  });
  const { data: positions = [], isLoading: positionsLoading } = useQuery({
    queryKey: ['prefab-link-positions', boqId],
    queryFn: () => fetchBoqPositions(boqId),
    enabled: editing && mode === 'boq' && !!boqId,
  });
  const { data: assemblies = [] } = useQuery({
    queryKey: ['prefab-link-assemblies', projectId],
    queryFn: () => fetchProjectAssemblies(projectId),
    enabled: editing && mode === 'assembly' && !!projectId,
  });

  // Collapse the editor once a link change lands (the unit prop updates).
  useEffect(() => {
    setEditing(false);
  }, [unit.boq_position_id, unit.assembly_id]);

  const pct = Math.round((unit.completed_fraction ?? 0) * 100);
  const sourceLabel =
    unit.cost_source === 'assembly'
      ? t('prefab.cost_from_assembly', { defaultValue: 'from assembly' })
      : t('prefab.cost_from_boq', { defaultValue: 'from BOQ position' });

  const canLink = mode === 'boq' ? !!positionId : !!assemblyId;
  const applyLink = () => {
    if (mode === 'boq' && positionId) onLink({ boq_position_id: positionId });
    else if (mode === 'assembly' && assemblyId) onLink({ assembly_id: assemblyId });
  };

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-2 inline-flex items-center gap-1">
        <Coins size={12} className="shrink-0" />
        {t('prefab.cost_link', { defaultValue: 'Cost link' })}
      </p>

      {/* Current cost view */}
      {isLinked && unit.cost_basis != null ? (
        <div className="mb-3 space-y-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-2xs text-content-tertiary">
              {t('prefab.cost_basis', { defaultValue: 'Cost basis' })}
            </span>
            <span className="text-sm font-semibold tabular-nums text-content-primary">
              {unit.cost_basis}
              <span className="ml-1 text-2xs font-normal text-content-tertiary">{sourceLabel}</span>
            </span>
          </div>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-2xs text-content-tertiary">
              {t('prefab.earned_value', { defaultValue: 'Earned value' })}
            </span>
            <span className="text-sm font-semibold tabular-nums text-emerald-700 dark:text-emerald-300">
              {unit.earned_value ?? '-'}
              <span className="ml-1 text-2xs font-normal text-content-tertiary">({pct}%)</span>
            </span>
          </div>
          {/* Progress bar - earned vs basis */}
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-tertiary">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
            />
          </div>
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={() => {
                setEditing((v) => !v);
                setMode(unit.cost_source === 'assembly' ? 'assembly' : 'boq');
              }}
              className="text-2xs font-medium text-oe-blue hover:underline"
            >
              {t('prefab.change_link', { defaultValue: 'Change' })}
            </button>
            <button
              onClick={() => onLink({ boq_position_id: null, assembly_id: null })}
              disabled={isLinking}
              className="inline-flex items-center gap-1 text-2xs font-medium text-semantic-error hover:underline disabled:opacity-50"
            >
              <Unlink size={11} className="shrink-0" />
              {t('prefab.unlink', { defaultValue: 'Unlink' })}
            </button>
          </div>
        </div>
      ) : (
        !editing && (
          <p className="mb-2 text-xs text-content-tertiary">
            {t('prefab.not_linked_hint', {
              defaultValue:
                'Not linked to any cost. Link a BOQ position or assembly to reflect real cost and earned value.',
            })}
          </p>
        )
      )}

      {/* Link editor */}
      {editing ? (
        <div className="space-y-2 rounded-md border border-border-light bg-surface-primary/60 p-2">
          <div className="flex gap-1">
            <button
              onClick={() => setMode('boq')}
              className={clsx(
                'flex-1 rounded-md px-2 py-1 text-2xs font-medium transition-colors',
                mode === 'boq'
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
              )}
            >
              {t('prefab.link_boq_tab', { defaultValue: 'BOQ position' })}
            </button>
            <button
              onClick={() => setMode('assembly')}
              className={clsx(
                'flex-1 rounded-md px-2 py-1 text-2xs font-medium transition-colors',
                mode === 'assembly'
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
              )}
            >
              {t('prefab.link_assembly_tab', { defaultValue: 'Assembly' })}
            </button>
          </div>

          {mode === 'boq' ? (
            <>
              <select
                value={boqId}
                onChange={(e) => {
                  setBoqId(e.target.value);
                  setPositionId('');
                }}
                className={inputCls + ' h-9 appearance-none text-xs'}
              >
                <option value="">{t('prefab.pick_boq', { defaultValue: 'Select a BOQ...' })}</option>
                {boqs.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
              {boqId && (
                <select
                  value={positionId}
                  onChange={(e) => setPositionId(e.target.value)}
                  disabled={positionsLoading}
                  className={inputCls + ' h-9 appearance-none text-xs'}
                >
                  <option value="">
                    {positionsLoading
                      ? t('common.loading', { defaultValue: 'Loading...' })
                      : t('prefab.pick_position', { defaultValue: 'Select a position...' })}
                  </option>
                  {positions.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.ordinal} - {p.description.slice(0, 48)} ({p.unit_rate}/{p.unit})
                    </option>
                  ))}
                </select>
              )}
            </>
          ) : (
            <select
              value={assemblyId}
              onChange={(e) => setAssemblyId(e.target.value)}
              className={inputCls + ' h-9 appearance-none text-xs'}
            >
              <option value="">
                {t('prefab.pick_assembly', { defaultValue: 'Select an assembly...' })}
              </option>
              {assemblies.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} - {a.name.slice(0, 48)} ({a.total_rate}/{a.unit})
                </option>
              ))}
            </select>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            {isLinked && (
              <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            )}
            <Button variant="primary" size="sm" onClick={applyLink} disabled={!canLink || isLinking}>
              <Link2 size={13} className="mr-1 shrink-0" />
              {t('prefab.link_action', { defaultValue: 'Link' })}
            </Button>
          </div>
        </div>
      ) : (
        !isLinked && (
          <Button variant="secondary" size="sm" onClick={() => setEditing(true)} className="w-full">
            <Link2 size={13} className="mr-1.5 shrink-0" />
            {t('prefab.link_to_cost', { defaultValue: 'Link to BOQ / assembly' })}
          </Button>
        )
      )}
    </div>
  );
}

/* ── Unit Detail Drawer (timeline + advance control) ───────────────────── */

function UnitDetailDrawer({
  unit,
  projectId,
  onClose,
  onAdvance,
  onDelete,
  onLink,
  isAdvancing,
  isLinking,
}: {
  unit: PrefabUnit;
  projectId: string;
  onClose: () => void;
  onAdvance: (note: string) => void;
  onDelete: () => void;
  onLink: (payload: LinkPrefabUnitPayload) => void;
  isAdvancing: boolean;
  isLinking: boolean;
}) {
  const { t } = useTranslation();
  const [note, setNote] = useState('');

  const { data: events = [], isLoading: eventsLoading } = useQuery({
    queryKey: ['prefab-events', unit.id],
    queryFn: () => fetchUnitEvents(unit.id),
  });

  const meta = stageMeta(unit.status);
  const next = nextStage(unit.status);
  const nextMeta = next ? stageMeta(next) : null;
  const hasPassedQa = POST_QA_STAGES.includes(unit.status as PrefabStage) || unit.status === 'qa';

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 animate-fade-in" onClick={onClose}>
      <div
        className="h-full w-full max-w-md bg-surface-primary shadow-2xl border-l border-border flex flex-col animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-border shrink-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-mono font-semibold text-content-primary truncate">
                {unit.ref}
              </span>
              <Badge variant="neutral" size="sm" className={meta.badge}>
                {t(`prefab.stage_${unit.status}`, { defaultValue: meta.label })}
              </Badge>
            </div>
            <p className="text-2xs text-content-tertiary mt-0.5">
              {t(`prefab.type_${unit.unit_type}`, {
                defaultValue:
                  (UNIT_TYPE_LABELS as Record<string, string>)[unit.unit_type] ?? unit.unit_type,
              })}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="p-1 rounded hover:bg-surface-secondary shrink-0"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Facts */}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-2xs uppercase tracking-wide text-content-tertiary">
                {t('prefab.field_target_install', { defaultValue: 'Target install date' })}
              </p>
              <p className="text-content-primary">
                {unit.target_install_date ? (
                  <DateDisplay value={unit.target_install_date} />
                ) : (
                  '-'
                )}
              </p>
            </div>
            <div>
              <p className="text-2xs uppercase tracking-wide text-content-tertiary">
                {t('prefab.field_drawing_ref', { defaultValue: 'Drawing reference' })}
              </p>
              <p className="text-content-primary truncate">{unit.drawing_ref || '-'}</p>
            </div>
          </div>
          {unit.notes && (
            <div>
              <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-1">
                {t('prefab.field_notes', { defaultValue: 'Notes' })}
              </p>
              <p className="text-sm text-content-secondary whitespace-pre-wrap">{unit.notes}</p>
            </div>
          )}

          {/* QA gate hint */}
          {hasPassedQa ? (
            <div className="flex items-start gap-2 rounded-lg border border-green-300/40 bg-green-50 dark:bg-green-900/15 px-3 py-2 text-xs text-green-700 dark:text-green-300">
              <ShieldCheck size={15} className="mt-0.5 shrink-0" />
              <span>
                {t('prefab.qa_passed_hint', {
                  defaultValue: 'QA passed. This unit is cleared for dispatch, delivery and install.',
                })}
              </span>
            </div>
          ) : (
            <div className="flex items-start gap-2 rounded-lg border border-amber-300/40 bg-amber-50 dark:bg-amber-900/15 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
              <ShieldCheck size={15} className="mt-0.5 shrink-0" />
              <span>
                {t('prefab.qa_pending_hint', {
                  defaultValue:
                    'This unit must pass QA before it can be dispatched, delivered or installed.',
                })}
              </span>
            </div>
          )}

          {/* Cost link (BOQ position / assembly) */}
          <LinkCostSection
            unit={unit}
            projectId={projectId}
            onLink={onLink}
            isLinking={isLinking}
          />

          {/* Advance control */}
          <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
            <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-2">
              {t('prefab.advance_stage', { defaultValue: 'Advance stage' })}
            </p>
            {next && nextMeta ? (
              <>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={2}
                  className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none mb-2"
                  placeholder={t('prefab.advance_note_placeholder', {
                    defaultValue: 'Optional note for the audit trail...',
                  })}
                />
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => onAdvance(note.trim())}
                  disabled={isAdvancing}
                  className="w-full"
                >
                  {isAdvancing ? (
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
                  ) : (
                    <ArrowRight size={14} className="mr-1.5 shrink-0" />
                  )}
                  {t('prefab.advance_to', {
                    defaultValue: 'Advance to {{stage}}',
                    stage: t(`prefab.stage_${next}`, { defaultValue: nextMeta.label }),
                  })}
                </Button>
              </>
            ) : (
              <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-300">
                <CheckCircle2 size={16} className="shrink-0" />
                {t('prefab.fully_installed', {
                  defaultValue: 'This unit is installed - the lifecycle is complete.',
                })}
              </div>
            )}
          </div>

          {/* Production event timeline */}
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-2">
              {t('prefab.timeline', { defaultValue: 'Production timeline' })}
            </p>
            {eventsLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-10 animate-pulse rounded bg-surface-tertiary" />
                ))}
              </div>
            ) : events.length === 0 ? (
              <p className="text-xs text-content-quaternary">
                {t('prefab.no_events', { defaultValue: 'No production events yet.' })}
              </p>
            ) : (
              <ol className="relative border-l border-border-light ml-1.5 space-y-3">
                {events.map((ev) => {
                  const evMeta = stageMeta(ev.stage);
                  return (
                    <li key={ev.id} className="ml-4">
                      <span
                        className={clsx(
                          'absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface-primary',
                          evMeta.dot,
                        )}
                      />
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="neutral" size="sm" className={evMeta.badge}>
                          {t(`prefab.stage_${ev.stage}`, { defaultValue: evMeta.label })}
                        </Badge>
                        <span className="inline-flex items-center gap-1 text-2xs text-content-tertiary">
                          <Clock size={11} />
                          <DateDisplay value={ev.at} format="datetime" />
                        </span>
                      </div>
                      {ev.note && (
                        <p className="mt-1 text-xs text-content-secondary">{ev.note}</p>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-border shrink-0">
          <Button variant="ghost" size="sm" onClick={onDelete} className="text-semantic-error">
            <Trash2 size={14} className="mr-1" />
            {t('common.delete', { defaultValue: 'Delete' })}
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function PrefabPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<PrefabUnit | null>(null);
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('all');

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const {
    data: board,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['prefab-board', projectId],
    queryFn: () => fetchPrefabBoard(projectId),
    enabled: !!projectId,
  });

  const { data: stats } = useQuery({
    queryKey: ['prefab-stats', projectId],
    queryFn: () => fetchPrefabStats(projectId),
    enabled: !!projectId,
  });

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['prefab-board', projectId] });
    qc.invalidateQueries({ queryKey: ['prefab-stats', projectId] });
  }, [qc, projectId]);

  const createMut = useMutation({
    mutationFn: (data: CreatePrefabUnitPayload) => createPrefabUnit(data),
    onSuccess: (created) => {
      setShowCreate(false);
      invalidate();
      addToast({
        type: 'success',
        title: t('prefab.created', { defaultValue: 'Unit created' }),
        message: created?.ref,
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('prefab.create_failed', { defaultValue: 'Could not create unit' }),
        message: e.message,
      });
    },
  });

  const advanceMut = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      advancePrefabUnit(id, note ? { note } : {}),
    onSuccess: (updated) => {
      invalidate();
      qc.invalidateQueries({ queryKey: ['prefab-events', updated.id] });
      setSelected(updated);
      addToast({
        type: 'success',
        title: t('prefab.advanced', { defaultValue: 'Stage advanced' }),
        message: t(`prefab.stage_${updated.status}`, {
          defaultValue: stageMeta(updated.status).label,
        }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('prefab.advance_failed', { defaultValue: 'Could not advance stage' }),
        message: e.message,
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePrefabUnit(id),
    onSuccess: () => {
      invalidate();
      setSelected(null);
      addToast({ type: 'success', title: t('prefab.deleted', { defaultValue: 'Unit deleted' }) });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('prefab.delete_failed', { defaultValue: 'Could not delete unit' }),
        message: e.message,
      });
    },
  });

  const linkMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: LinkPrefabUnitPayload }) =>
      linkPrefabUnit(id, payload),
    onSuccess: (updated) => {
      invalidate();
      setSelected(updated);
      addToast({
        type: 'success',
        title:
          updated.cost_basis != null
            ? t('prefab.linked', { defaultValue: 'Cost link updated' })
            : t('prefab.unlinked', { defaultValue: 'Cost link removed' }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('prefab.link_failed', { defaultValue: 'Could not update cost link' }),
        message: e.message,
      });
    },
  });

  const { confirm, ...confirmProps } = useConfirm();

  const handleCreate = useCallback(
    (formData: UnitFormData) => {
      if (!projectId) return;
      createMut.mutate({
        project_id: projectId,
        ref: formData.ref.trim(),
        unit_type: formData.unit_type,
        target_install_date: formData.target_install_date || undefined,
        drawing_ref: formData.drawing_ref.trim() || undefined,
        notes: formData.notes.trim() || undefined,
      });
    },
    [createMut, projectId],
  );

  const handleDelete = useCallback(
    async (unit: PrefabUnit) => {
      const ok = await confirm({
        title: t('prefab.confirm_delete_title', { defaultValue: 'Delete unit?' }),
        message: t('prefab.confirm_delete_msg', {
          defaultValue: 'This permanently removes {{ref}} and its production history.',
          ref: unit.ref,
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(unit.id);
    },
    [confirm, deleteMut, t],
  );

  // Flat list of every unit on the board, for board-level risk KPIs + export.
  const allUnits = useMemo<PrefabUnit[]>(
    () => (board?.columns ?? []).flatMap((c) => c.units),
    [board],
  );

  // Prefab is one of the few registers with real money on the record:
  // cost_basis comes from the linked BOQ position or assembly, and
  // earned_value is that basis times the stage machine's completed fraction.
  const projectCurrency = projects.find((p) => p.id === projectId)?.currency || 'EUR';
  const insights = useModuleInsights('prefab', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildPrefabInsights(allUnits, projectCurrency, t),
    [allUnits, projectCurrency, t],
  );

  // Board-level risk tallies, computed from the full register (never narrowed
  // by the search box) so the tiles stay stable, trustworthy KPIs.
  const riskCounts = useMemo(() => {
    let overdue = 0;
    let dueSoon = 0;
    let atRisk = 0;
    for (const u of allUnits) {
      if (isUnitOverdue(u)) overdue += 1;
      if (isUnitDueSoon(u)) dueSoon += 1;
      if (isUnitAtRisk(u)) atRisk += 1;
    }
    return { overdue, dueSoon, atRisk };
  }, [allUnits]);

  // Export the whole register as a CSV, sorted by soonest install date.
  const handleExportCsv = useCallback(() => {
    if (!allUnits.length) return;
    const headers = [
      t('prefab.csv_ref', { defaultValue: 'Reference' }),
      t('prefab.csv_type', { defaultValue: 'Type' }),
      t('prefab.csv_stage', { defaultValue: 'Stage' }),
      t('prefab.csv_install_date', { defaultValue: 'Target install date' }),
      t('prefab.csv_days_to_install', { defaultValue: 'Days to install' }),
      t('prefab.csv_risk', { defaultValue: 'Risk' }),
      t('prefab.csv_cost_basis', { defaultValue: 'Cost basis' }),
      t('prefab.csv_earned_value', { defaultValue: 'Earned value' }),
    ];
    const esc = (v: string) => `"${v.replace(/"/g, '""')}"`;
    const rows = [...allUnits].sort(compareByInstallDate).map((u) => {
      const days = daysUntilInstall(u.target_install_date);
      const risk = isUnitOverdue(u)
        ? t('prefab.risk_overdue', { defaultValue: 'Overdue' })
        : isUnitDueSoon(u)
          ? t('prefab.risk_due_soon', { defaultValue: 'Due soon' })
          : isUnitAtRisk(u)
            ? t('prefab.risk_at_risk', { defaultValue: 'At risk' })
            : t('prefab.risk_on_track', { defaultValue: 'On track' });
      // cost_basis / earned_value are Decimal strings - emitted verbatim, never
      // parsed or re-formatted, so no precision is lost and no float math runs.
      return [
        esc(u.ref),
        esc(
          t(`prefab.type_${u.unit_type}`, {
            defaultValue:
              (UNIT_TYPE_LABELS as Record<string, string>)[u.unit_type] ?? String(u.unit_type),
          }),
        ),
        esc(t(`prefab.stage_${u.status}`, { defaultValue: stageMeta(u.status).label })),
        u.target_install_date ?? '',
        days == null ? '' : String(days),
        esc(risk),
        u.cost_basis ?? '',
        u.earned_value ?? '',
      ].join(',');
    });
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `prefab_register_${(projectName || 'project').replace(/[^\w.-]+/g, '_')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [allUnits, projectName, t]);

  // Filter columns by the search box + active risk filter, then sort each
  // column by soonest target install date (undated units sink to the bottom).
  const columns = useMemo<PrefabBoardColumn[]>(() => {
    const src: PrefabBoardColumn[] =
      board?.columns ?? STAGE_ORDER.map((stage) => ({ stage, count: 0, units: [] }));
    const q = search.trim().toLowerCase();
    return src.map((col) => {
      let units = col.units;
      if (q) {
        units = units.filter(
          (u) =>
            u.ref.toLowerCase().includes(q) ||
            Boolean(u.drawing_ref && u.drawing_ref.toLowerCase().includes(q)) ||
            Boolean(u.notes && u.notes.toLowerCase().includes(q)),
        );
      }
      if (riskFilter !== 'all') {
        units = units.filter((u) => matchesRiskFilter(u, riskFilter));
      }
      units = [...units].sort(compareByInstallDate);
      return { ...col, units, count: units.length };
    });
  }, [board, search, riskFilter]);

  const total = stats?.total ?? board?.total ?? 0;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('prefab.title', { defaultValue: 'Off-site / Prefab' }) },
        ]}
      />

      <PageHeader
        srTitle={t('prefab.title', { defaultValue: 'Off-site / Prefab' })}
        subtitle={t('prefab.subtitle', {
          defaultValue:
            'Track every off-site unit from design to installation, with a hard quality gate before anything ships.',
        })}
        actions={
          <div className="flex items-center gap-2">
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <Button
              variant="secondary"
              size="sm"
              onClick={handleExportCsv}
              disabled={!projectId || allUnits.length === 0}
              className="shrink-0 whitespace-nowrap"
            >
              <Download size={14} className="mr-1 shrink-0" />
              <span>{t('prefab.export_register', { defaultValue: 'Export register (CSV)' })}</span>
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                if (!projectId) {
                  addToast({
                    type: 'info',
                    title: t('prefab.select_project_first_title', {
                      defaultValue: 'Select a project first',
                    }),
                    message: t('prefab.select_project_first', {
                      defaultValue: 'Pick a project from the top bar, then add a unit.',
                    }),
                  });
                  return;
                }
                setShowCreate(true);
              }}
              className="shrink-0 whitespace-nowrap"
            >
              <Plus size={14} className="mr-1 shrink-0" />
              <span>{t('prefab.new_unit', { defaultValue: 'New Unit' })}</span>
            </Button>
          </div>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('prefab.insights.title', { defaultValue: 'Prefab insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <DismissibleInfo
        storageKey="prefab"
        title={t('prefab.intro_title', {
          defaultValue: 'One register for everything made off-site',
        })}
      >
        {t('prefab.intro_body', {
          defaultValue:
            'Design for Manufacture and Assembly: register pods, panels, volumetric modules and skids, then move each one along the production line - design, approved, in production, QA, dispatched, delivered, installed. A unit can never be dispatched, delivered or installed until it has passed QA, and every stage change is recorded.',
        })}
      </DismissibleInfo>

      {/* Summary cards */}
      {projectId && total > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
          <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('prefab.stat_total', { defaultValue: 'Total' })}
            </span>
            <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
              {total}
            </span>
          </div>
          {STAGE_ORDER.map((stage) => (
            <div
              key={stage}
              className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs"
            >
              <span className="inline-flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                <span className={clsx('h-2 w-2 rounded-full', stageMeta(stage).dot)} />
                <span className="truncate">
                  {t(`prefab.stage_${stage}`, { defaultValue: stageMeta(stage).label })}
                </span>
              </span>
              <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
                {stats?.by_status?.[stage] ?? 0}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Risk strip: overdue / due-soon / at-risk tallies that double as
          one-click board filters. Counts come from the full register. */}
      {projectId && total > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <RiskTile
            active={riskFilter === 'overdue'}
            count={riskCounts.overdue}
            onToggle={() => setRiskFilter((f) => (f === 'overdue' ? 'all' : 'overdue'))}
            icon={<AlertTriangle size={14} className="shrink-0" />}
            label={t('prefab.risk_overdue', { defaultValue: 'Overdue' })}
            tone="danger"
            hint={t('prefab.overdue_hint', {
              defaultValue: 'Past target install date and not yet installed',
            })}
          />
          <RiskTile
            active={riskFilter === 'due_soon'}
            count={riskCounts.dueSoon}
            onToggle={() => setRiskFilter((f) => (f === 'due_soon' ? 'all' : 'due_soon'))}
            icon={<Clock size={14} className="shrink-0" />}
            label={t('prefab.due_soon_window', { defaultValue: 'Due soon (2 wks)' })}
            tone="warning"
            hint={t('prefab.due_soon_hint', {
              defaultValue: 'Not yet installed and due within {{count}} days',
              count: LOOKAHEAD_DAYS,
            })}
          />
          <RiskTile
            active={riskFilter === 'at_risk'}
            count={riskCounts.atRisk}
            onToggle={() => setRiskFilter((f) => (f === 'at_risk' ? 'all' : 'at_risk'))}
            icon={<ShieldCheck size={14} className="shrink-0" />}
            label={t('prefab.at_risk_tile', { defaultValue: 'At risk in production' })}
            tone="warning"
            hint={t('prefab.at_risk_hint', {
              defaultValue:
                'Still in production or QA and due within the {{count}}-day lead time',
              count: LEAD_TIME_DAYS,
            })}
          />
          {riskFilter !== 'all' && (
            <button
              type="button"
              onClick={() => setRiskFilter('all')}
              className="px-2 py-1 text-2xs font-medium text-oe-blue hover:underline"
            >
              {t('prefab.clear_filter', { defaultValue: 'Clear filter' })}
            </button>
          )}
        </div>
      )}

      {/* Search */}
      {projectId && (
        <div className="relative max-w-sm">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('prefab.search_placeholder', { defaultValue: 'Search units...' })}
            className={inputCls + ' pl-9'}
          />
        </div>
      )}

      {/* Board */}
      {!projectId ? (
        <RequiresProject>{null}</RequiresProject>
      ) : isLoading ? (
        <SkeletonTable rows={4} columns={4} />
      ) : isError ? (
        <RecoveryCard error={error} onRetry={() => refetch()} />
      ) : total === 0 ? (
        <EmptyState
          icon={<Boxes size={28} strokeWidth={1.5} />}
          title={t('prefab.no_units', { defaultValue: 'No units yet' })}
          description={t('prefab.no_units_hint', {
            defaultValue: 'Register your first off-site unit to start tracking production.',
          })}
          action={{
            label: t('prefab.new_unit', { defaultValue: 'New Unit' }),
            onClick: () => setShowCreate(true),
          }}
        />
      ) : (
        <div className="overflow-x-auto pb-2">
          <div className="flex gap-3 min-w-max">
            {columns.map((col) => {
              const meta = stageMeta(col.stage);
              const isGate = col.stage === 'dispatched';
              return (
                <React.Fragment key={col.stage}>
                  {isGate && (
                    <div
                      className="flex flex-col items-center gap-1 px-1 pt-8"
                      title={t('prefab.qa_gate_tooltip', {
                        defaultValue: 'Quality gate: units must pass QA before this point',
                      })}
                    >
                      <ShieldCheck size={16} className="text-purple-400 shrink-0" />
                      <div className="flex-1 w-px border-l-2 border-dashed border-purple-300 dark:border-purple-700" />
                    </div>
                  )}
                  <div className="w-64 shrink-0">
                    <div
                      className={clsx(
                        'flex items-center justify-between rounded-t-lg border-t-2 bg-surface-secondary/40 px-3 py-2',
                        meta.column,
                      )}
                    >
                      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-content-primary">
                        <span className={clsx('h-2 w-2 rounded-full', meta.dot)} />
                        {t(`prefab.stage_${col.stage}`, { defaultValue: meta.label })}
                      </span>
                      <span className="text-2xs tabular-nums px-1.5 py-0.5 rounded-full bg-surface-tertiary text-content-tertiary">
                        {col.count}
                      </span>
                    </div>
                    <div className="rounded-b-lg border border-t-0 border-border-light bg-surface-secondary/20 p-2 space-y-2 min-h-[120px]">
                      {col.units.length === 0 ? (
                        <p className="text-2xs text-content-quaternary text-center py-6">
                          {t('prefab.empty_stage', { defaultValue: 'Nothing here' })}
                        </p>
                      ) : (
                        col.units.map((u) => (
                          <UnitCard key={u.id} unit={u} onOpen={setSelected} />
                        ))
                      )}
                    </div>
                  </div>
                </React.Fragment>
              );
            })}
          </div>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <CreateUnitModal
          onClose={() => setShowCreate(false)}
          onSubmit={handleCreate}
          isPending={createMut.isPending}
        />
      )}

      {/* Detail drawer */}
      {selected && (
        <UnitDetailDrawer
          unit={selected}
          projectId={projectId}
          onClose={() => setSelected(null)}
          onAdvance={(note) => advanceMut.mutate({ id: selected.id, note })}
          onDelete={() => handleDelete(selected)}
          onLink={(payload) => linkMut.mutate({ id: selected.id, payload })}
          isAdvancing={advanceMut.isPending}
          isLinking={linkMut.isPending}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
