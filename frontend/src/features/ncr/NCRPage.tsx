// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useNavigate, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertOctagon,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  DollarSign,
  CheckCircle2,
  ClipboardCheck,
  Package,
  Wrench,
  PenTool,
  FileText,
  ShieldAlert,
  AlertCircle,
  AlertTriangle,
  Info,
  MapPin,
  ListChecks,
  Link2,
  Network,
  ArrowRight,
  Pencil,
  Undo2,
  Ban,
  Save,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, RecoveryCard, SkeletonTable, IntroRichText, ModuleGuideButton, MoneyDisplay, CollapsibleSection } from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { SectionIntro } from '@/features/validation';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiPost } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { fetchAllPages } from '@/shared/lib/apiHelpers';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchNCRs,
  createNCR,
  closeNCR,
  updateNCR,
  type NCR,
  type NCRType,
  type NCRSeverity,
  type NCRStatus,
  type CreateNCRPayload,
  type UpdateNCRPayload,
} from './api';
import { NCR_STAGES, ncrStageIndex, ncrNextMoves } from './ncrFsm';
import { ncrGuide } from './ncrGuide';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildNCRInsights } from './ncrInsights';
import { IssueHubLink } from '@/features/issues/IssueHubLink';
import { RaiseBackCharge } from '@/features/cost-recovery/RaiseBackCharge';

// English fallbacks for the computed `ncr.severity_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const NCR_SEVERITY_LABELS: Record<string, string> = {
  critical: 'Critical', major: 'Major', minor: 'Minor', observation: 'Observation'
};


/* -- Constants ------------------------------------------------------------- */

interface Project {
  id: string;
  name: string;
  currency?: string;
}

const NCR_TYPE_COLORS: Record<
  NCRType,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  material: 'blue',
  workmanship: 'warning',
  design: 'neutral',
  documentation: 'neutral',
  safety: 'error',
};

const SEVERITY_CONFIG: Record<
  NCRSeverity,
  { variant: 'neutral' | 'blue' | 'success' | 'error' | 'warning'; cls: string }
> = {
  critical: { variant: 'error', cls: '' },
  major: { variant: 'warning', cls: '' },
  minor: {
    variant: 'warning',
    cls: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300',
  },
  observation: {
    variant: 'neutral',
    cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  },
};

const STATUS_CONFIG: Record<
  NCRStatus,
  { variant: 'neutral' | 'blue' | 'success' | 'error' | 'warning'; cls: string }
> = {
  identified: { variant: 'error', cls: '' },
  under_review: { variant: 'warning', cls: '' },
  corrective_action: { variant: 'blue', cls: '' },
  verification: { variant: 'blue', cls: '' },
  closed: { variant: 'success', cls: '' },
  void: {
    variant: 'neutral',
    cls: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  },
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

const NCR_TYPES: NCRType[] = ['material', 'workmanship', 'design', 'documentation', 'safety'];

const NCR_SEVERITIES: NCRSeverity[] = ['critical', 'major', 'minor', 'observation'];

const NCR_TYPE_CARD_CONFIG: Record<NCRType, { icon: React.ElementType; color: string }> = {
  material: { icon: Package, color: 'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950/30 dark:border-blue-800' },
  workmanship: { icon: Wrench, color: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800' },
  design: { icon: PenTool, color: 'text-purple-600 bg-purple-50 border-purple-200 dark:text-purple-400 dark:bg-purple-950/30 dark:border-purple-800' },
  documentation: { icon: FileText, color: 'text-gray-600 bg-gray-50 border-gray-200 dark:text-gray-400 dark:bg-gray-800/50 dark:border-gray-700' },
  safety: { icon: ShieldAlert, color: 'text-red-600 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800' },
};

const SEVERITY_CARD_CONFIG: Record<NCRSeverity, { icon: React.ElementType; color: string; ringColor: string }> = {
  critical: { icon: AlertOctagon, color: 'text-red-700 bg-red-50 border-red-300 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800', ringColor: 'ring-red-300' },
  major: { icon: AlertCircle, color: 'text-orange-600 bg-orange-50 border-orange-200 dark:text-orange-400 dark:bg-orange-950/30 dark:border-orange-800', ringColor: 'ring-orange-300' },
  minor: { icon: AlertTriangle, color: 'text-yellow-600 bg-yellow-50 border-yellow-200 dark:text-yellow-400 dark:bg-yellow-950/30 dark:border-yellow-800', ringColor: 'ring-yellow-300' },
  observation: { icon: Info, color: 'text-gray-500 bg-gray-50 border-gray-200 dark:text-gray-400 dark:bg-gray-800/50 dark:border-gray-700', ringColor: 'ring-gray-300' },
};

const NCR_STATUSES: NCRStatus[] = [
  'identified',
  'under_review',
  'corrective_action',
  'verification',
  'closed',
  'void',
];

/* -- Create NCR Modal ------------------------------------------------------ */

interface NCRFormData {
  title: string;
  ncr_type: NCRType;
  severity: NCRSeverity;
  description: string;
  location: string;
  root_cause: string;
}

const EMPTY_FORM: NCRFormData = {
  title: '',
  ncr_type: 'material',
  severity: 'minor',
  description: '',
  location: '',
  root_cause: '',
};

function CreateNCRModal({
  onClose,
  onSubmit,
  isPending,
  projectName,
}: {
  onClose: () => void;
  onSubmit: (data: NCRFormData) => void;
  isPending: boolean;
  projectName?: string;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<NCRFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof NCRFormData>(key: K, value: NCRFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const titleError = touched && form.title.trim().length === 0;
  const descError = touched && form.description.trim().length === 0;
  const canSubmit = form.title.trim().length > 0 && form.description.trim().length > 0;

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
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-modal="true" aria-label={t('ncr.new_ncr', { defaultValue: 'New NCR' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('ncr.new_ncr', { defaultValue: 'New NCR' })}
            </h2>
            {projectName && (
              <p className="text-xs text-content-tertiary mt-0.5">
                {t('common.creating_in_project', {
                  defaultValue: 'In {{project}}',
                  project: projectName,
                })}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-5">
          {/* ── NCR Type ── */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('ncr.field_type', { defaultValue: 'Non-Conformance Type' })}
            </label>
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
              {NCR_TYPES.map((nt) => {
                const cfg = NCR_TYPE_CARD_CONFIG[nt];
                const TypeIcon = cfg.icon;
                const selected = form.ncr_type === nt;
                return (
                  <button
                    key={nt}
                    type="button"
                    onClick={() => set('ncr_type', nt)}
                    className={clsx(
                      'flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-2.5 text-center transition-all',
                      selected
                        ? cfg.color + ' ring-2 ring-oe-blue/30'
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <TypeIcon size={18} />
                    <span className="text-2xs font-medium leading-tight">
                      {t(`ncr.type_${nt}`, {
                        defaultValue: nt.charAt(0).toUpperCase() + nt.slice(1),
                      })}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Severity ── */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('ncr.field_severity', { defaultValue: 'Severity' })}
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {NCR_SEVERITIES.map((sev) => {
                const cfg = SEVERITY_CARD_CONFIG[sev];
                const SevIcon = cfg.icon;
                const selected = form.severity === sev;
                return (
                  <button
                    key={sev}
                    type="button"
                    onClick={() => set('severity', sev)}
                    className={clsx(
                      'flex items-center gap-2 rounded-lg border-2 px-3 py-2.5 transition-all text-left',
                      selected
                        ? cfg.color + ' ring-2 ' + cfg.ringColor
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <SevIcon size={16} className="shrink-0" />
                    <span className="text-xs font-semibold">
                      {t(`ncr.severity_${sev}`, {
                        defaultValue: NCR_SEVERITY_LABELS[sev] ?? sev.charAt(0).toUpperCase() + sev.slice(1),
                      })}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Details Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <AlertOctagon size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('ncr.section_details', { defaultValue: 'NCR Details' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Title */}
          <div>
            <label htmlFor="ncr-title" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('ncr.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              id="ncr-title"
              value={form.title}
              onChange={(e) => {
                set('title', e.target.value);
                setTouched(true);
              }}
              placeholder={t('ncr.title_placeholder', {
                defaultValue: 'e.g. Concrete strength below specification at Column C3',
              })}
              className={clsx(
                inputCls,
                titleError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('ncr.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          {/* Description */}
          <div>
            <label htmlFor="ncr-description" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('ncr.field_description', { defaultValue: 'Description' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <textarea
              id="ncr-description"
              value={form.description}
              onChange={(e) => {
                set('description', e.target.value);
                setTouched(true);
              }}
              rows={5}
              className={clsx(
                textareaCls,
                descError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              placeholder={t('ncr.description_placeholder', {
                defaultValue: 'Describe the non-conformance in detail: what was observed, where, and what specification was not met...',
              })}
            />
            {descError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('ncr.description_required', { defaultValue: 'Description is required' })}
              </p>
            )}
          </div>

          {/* ── Location Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <MapPin size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('ncr.section_location', { defaultValue: 'Location' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          <div>
            <label htmlFor="ncr-location" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('ncr.field_location', { defaultValue: 'Location' })}
            </label>
            <input
              id="ncr-location"
              value={form.location}
              onChange={(e) => set('location', e.target.value)}
              className={inputCls}
              placeholder={t('ncr.location_placeholder', {
                defaultValue: 'e.g. Building A, Level 2, Zone C',
              })}
            />
          </div>

          {/* Root Cause */}
          <div>
            <label htmlFor="ncr-root-cause" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('ncr.field_root_cause', { defaultValue: 'Root Cause (if known)' })}
            </label>
            <textarea
              id="ncr-root-cause"
              value={form.root_cause}
              onChange={(e) => set('root_cause', e.target.value)}
              rows={3}
              className={textareaCls}
              placeholder={t('ncr.root_cause_placeholder', {
                defaultValue: 'Preliminary analysis of why the non-conformance occurred...',
              })}
            />
          </div>
        </div>

        {/* Footer */}
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
            <span>{t('ncr.create_ncr', { defaultValue: 'Create NCR' })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- NCR Row (expandable) -------------------------------------------------- */

const NCRRow = React.memo(function NCRRow({
  ncr,
  currency,
  onClose,
  onCreateVariation,
  onUpdate,
  onVoid,
  busy,
  highlight,
}: {
  ncr: NCR;
  /** Active project's ISO-4217 currency, so cost impact renders in the right
   *  currency instead of a hardcoded dollar symbol. */
  currency?: string;
  onClose: (id: string) => void;
  onCreateVariation: (id: string) => void;
  /** Patch descriptive fields or move the NCR one legal step along its
   *  lifecycle (any transition except the final close, which routes through
   *  onClose so the corrective-action guard fires). */
  onUpdate: (id: string, data: UpdateNCRPayload) => void;
  /** Void the NCR (confirmed at the page level). */
  onVoid: (id: string) => void;
  /** True while any NCR mutation is in flight, so the row disables its actions
   *  instead of firing overlapping transitions. */
  busy?: boolean;
  /** When set (from a ?highlight deep-link) the row auto-expands, scrolls into
   *  view and flashes a highlight ring. */
  highlight?: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);
  const [flash, setFlash] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<UpdateNCRPayload>({});

  // Terminal NCRs are read-only; only draft/in-flight ones can be edited or
  // moved. Mirrors the backend guard (update_ncr rejects closed/void).
  const isTerminal = ncr.status === 'closed' || ncr.status === 'void';
  const moves = ncrNextMoves(ncr.status);
  const stageIdx = ncrStageIndex(ncr.status);

  const beginEdit = useCallback(() => {
    setDraft({
      severity: ncr.severity,
      root_cause: ncr.root_cause ?? '',
      root_cause_category: ncr.root_cause_category ?? '',
      corrective_action: ncr.corrective_action ?? '',
      preventive_action: ncr.preventive_action ?? '',
      cost_impact: ncr.cost_impact != null ? String(ncr.cost_impact) : '',
    });
    setEditing(true);
  }, [ncr]);

  const saveEdit = useCallback(() => {
    onUpdate(ncr.id, draft);
    setEditing(false);
  }, [draft, ncr.id, onUpdate]);

  useEffect(() => {
    if (!highlight) return;
    setExpanded(true);
    setFlash(true);
    rowRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const timer = window.setTimeout(() => setFlash(false), 2400);
    return () => window.clearTimeout(timer);
  }, [highlight]);

  const statusCfg = STATUS_CONFIG[ncr.status] ?? STATUS_CONFIG.identified;
  const typeCfg = NCR_TYPE_COLORS[ncr.ncr_type] ?? 'neutral';
  const severityCfg = SEVERITY_CONFIG[ncr.severity] ?? SEVERITY_CONFIG.minor;
  // Deep-link to the exact originating inspection (scoped to the NCR's project
  // and highlighting the linked inspection row). Falls back to the project
  // route even when the inspection number is unknown.
  const inspectionDeepLink = ncr.linked_inspection_id
    ? `/projects/${ncr.project_id}/inspections?highlight=${ncr.linked_inspection_id}`
    : '/inspections';

  return (
    <div
      ref={rowRef}
      className={clsx(
        'border-b border-border-light last:border-b-0 scroll-mt-24 transition-colors duration-500',
        flash && 'bg-oe-blue/10 ring-2 ring-inset ring-oe-blue/40',
      )}
    >
      {/* Main row */}
      <div
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        onClick={() => setExpanded((prev) => !prev)}
      >
        <ChevronRight
          size={14}
          className={clsx(
            'text-content-tertiary transition-transform shrink-0',
            expanded && 'rotate-90',
          )}
        />

        {/* NCR # */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-20 shrink-0">
          NCR-{String(ncr.ncr_number).padStart(3, '0')}
        </span>

        {/* Title */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {ncr.title}
        </span>

        {/* Origin badge - auto-raised from a clash */}
        {ncr.metadata?.source === 'clash' && (
          <Badge variant="error" size="sm" className="shrink-0">
            {t('ncr.source_clash', { defaultValue: 'From clash' })}
          </Badge>
        )}

        {/* Origin badge - auto-raised from blocking validation errors */}
        {ncr.metadata?.source === 'validation' && (
          <Badge variant="warning" size="sm" className="shrink-0">
            {t('ncr.source_validation', { defaultValue: 'From validation' })}
          </Badge>
        )}

        {/* Type badge */}
        <Badge variant={typeCfg} size="sm">
          {t(`ncr.type_${ncr.ncr_type}`, {
            defaultValue: ncr.ncr_type.charAt(0).toUpperCase() + ncr.ncr_type.slice(1),
          })}
        </Badge>

        {/* Severity badge */}
        <Badge variant={severityCfg.variant} size="sm" className={severityCfg.cls}>
          {t(`ncr.severity_${ncr.severity}`, {
            defaultValue: NCR_SEVERITY_LABELS[ncr.severity] ?? ncr.severity.charAt(0).toUpperCase() + ncr.severity.slice(1),
          })}
        </Badge>

        {/* Cost Impact */}
        <span className="text-xs text-content-tertiary w-20 text-right shrink-0 hidden md:block tabular-nums">
          {ncr.cost_impact != null && ncr.cost_impact > 0 ? (
            <MoneyDisplay
              amount={ncr.cost_impact}
              currency={currency}
              compact
              className="text-amber-500 font-medium"
            />
          ) : (
            '\u2014'
          )}
        </span>

        {/* Status badge */}
        <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
          {t(`ncr.status_${ncr.status}`, {
            defaultValue: ncr.status.replace(/_/g, ' '),
          })}
        </Badge>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Description */}
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
              {t('ncr.label_description', { defaultValue: 'Description' })}
            </p>
            <p className="text-sm text-content-primary whitespace-pre-wrap">{ncr.description}</p>
          </div>

          {/* Root Cause */}
          {ncr.root_cause && (
            <div className="rounded-lg bg-orange-50 dark:bg-orange-950/20 border border-orange-200 dark:border-orange-800 p-3">
              <p className="text-xs text-orange-700 dark:text-orange-400 mb-1 font-medium uppercase tracking-wide">
                {t('ncr.label_root_cause', { defaultValue: 'Root Cause' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">{ncr.root_cause}</p>
            </div>
          )}

          {/* Corrective Action */}
          {ncr.corrective_action && (
            <div className="rounded-lg bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 p-3">
              <p className="text-xs text-blue-700 dark:text-blue-400 mb-1 font-medium uppercase tracking-wide">
                {t('ncr.label_corrective_action', { defaultValue: 'Corrective Action' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">
                {ncr.corrective_action}
              </p>
            </div>
          )}

          {/* Preventive Action */}
          {ncr.preventive_action && (
            <div className="rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3">
              <p className="text-xs text-green-700 dark:text-green-400 mb-1 font-medium uppercase tracking-wide">
                {t('ncr.label_preventive_action', { defaultValue: 'Preventive Action' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">
                {ncr.preventive_action}
              </p>
            </div>
          )}

          {/* Linked Inspection — the INS badge deep-links straight to the
              originating inspection so the user lands on the exact failed
              check, not the full register. */}
          {ncr.linked_inspection_number != null && (
            <div className="flex items-center gap-2">
              <ClipboardCheck size={13} className="text-content-tertiary" />
              <span className="text-xs text-content-tertiary">
                {t('ncr.linked_inspection', { defaultValue: 'Linked Inspection' })}:
              </span>
              {ncr.linked_inspection_id ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate(inspectionDeepLink);
                  }}
                  className="rounded-md transition-opacity hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                  title={t('ncr.view_inspection', { defaultValue: 'View Inspection' })}
                >
                  <Badge variant="blue" size="sm">
                    INS-{String(ncr.linked_inspection_number).padStart(3, '0')}
                  </Badge>
                </button>
              ) : (
                <Badge variant="neutral" size="sm">
                  INS-{String(ncr.linked_inspection_number).padStart(3, '0')}
                </Badge>
              )}
            </div>
          )}

          {/* Change Order traceability banner */}
          {ncr.change_order_id && (
            <div
              className="flex items-center gap-2.5 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-3.5 py-2.5 cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-950/30 transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                navigate('/changeorders');
              }}
              role="link"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.stopPropagation();
                  navigate('/changeorders');
                }
              }}
            >
              <Link2 size={15} className="text-blue-600 dark:text-blue-400 shrink-0" />
              <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                {t('ncr.linked_change_order', { defaultValue: 'Linked to Change Order' })}
              </span>
              <Badge variant="blue" size="sm">
                {ncr.change_order_id.slice(0, 8)}
              </Badge>
              <ChevronRight size={14} className="ml-auto text-blue-400 dark:text-blue-500" />
            </div>
          )}

          {/* Location + Dates */}
          <div className="flex items-center gap-4 text-xs text-content-tertiary flex-wrap">
            {ncr.location && (
              <span>
                {t('ncr.label_location', { defaultValue: 'Location' })}: {ncr.location}
              </span>
            )}
            <span>
              {t('ncr.label_created', { defaultValue: 'Created' })}:{' '}
              <DateDisplay value={ncr.created_at} />
            </span>
            {ncr.closed_at && (
              <span>
                {t('ncr.label_closed', { defaultValue: 'Closed' })}:{' '}
                <DateDisplay value={ncr.closed_at} />
              </span>
            )}
          </div>

          {/* Lifecycle stepper - the current stage plus every stage already
              passed, so the reviewer can see at a glance where the NCR sits on
              its path to closure. Voided NCRs leave the linear track. */}
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary mb-2 font-medium uppercase tracking-wide">
              {t('ncr.lifecycle', { defaultValue: 'Lifecycle' })}
            </p>
            {ncr.status === 'void' ? (
              <div className="flex items-center gap-1.5">
                <Ban size={14} className="text-red-500" />
                <span className="text-sm font-medium text-red-600 dark:text-red-400">
                  {t('ncr.status_void', { defaultValue: 'Void' })}
                </span>
              </div>
            ) : (
              <div className="flex items-center flex-wrap gap-1">
                {NCR_STAGES.map((stage, i) => {
                  const done = i < stageIdx;
                  const current = i === stageIdx;
                  return (
                    <React.Fragment key={stage}>
                      {i > 0 && (
                        <ChevronRight size={12} className="text-content-quaternary shrink-0" />
                      )}
                      <span
                        className={clsx(
                          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium whitespace-nowrap',
                          current && 'bg-oe-blue/15 text-oe-blue-text ring-1 ring-inset ring-oe-blue/30',
                          done && 'text-emerald-600 dark:text-emerald-400',
                          !done && !current && 'text-content-quaternary',
                        )}
                      >
                        {done && <CheckCircle2 size={11} />}
                        {t(`ncr.status_${stage}`, { defaultValue: stage.replace(/_/g, ' ') })}
                      </span>
                    </React.Fragment>
                  );
                })}
              </div>
            )}
          </div>

          {/* Inline edit form - lets the reviewer record the analysis (root
              cause, corrective and preventive action) that closure requires,
              without a separate modal. Open/void NCRs only. */}
          {editing && !isTerminal && (
            <div
              className="rounded-lg border border-border-light bg-surface-primary p-3 space-y-3"
              onClick={(e) => e.stopPropagation()}
            >
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                  {t('ncr.label_severity', { defaultValue: 'Severity' })}
                </label>
                <select
                  value={draft.severity ?? ncr.severity}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, severity: e.target.value as NCRSeverity }))
                  }
                  className={inputCls}
                >
                  {(['critical', 'major', 'minor', 'observation'] as NCRSeverity[]).map((s) => (
                    <option key={s} value={s}>
                      {t(`ncr.severity_${s}`, { defaultValue: NCR_SEVERITY_LABELS[s] ?? s.charAt(0).toUpperCase() + s.slice(1) })}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                  {t('ncr.label_root_cause', { defaultValue: 'Root Cause' })}
                </label>
                <textarea
                  value={draft.root_cause ?? ''}
                  onChange={(e) => setDraft((d) => ({ ...d, root_cause: e.target.value }))}
                  rows={2}
                  className={textareaCls}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                  {t('ncr.label_root_cause_category', { defaultValue: 'Root cause category' })}
                </label>
                <input
                  value={draft.root_cause_category ?? ''}
                  onChange={(e) => setDraft((d) => ({ ...d, root_cause_category: e.target.value }))}
                  className={inputCls}
                  placeholder={t('ncr.root_cause_category_placeholder', {
                    defaultValue: 'e.g. workmanship, material, supervision',
                  })}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                  {t('ncr.label_corrective_action', { defaultValue: 'Corrective Action' })}
                </label>
                <textarea
                  value={draft.corrective_action ?? ''}
                  onChange={(e) => setDraft((d) => ({ ...d, corrective_action: e.target.value }))}
                  rows={2}
                  className={textareaCls}
                  placeholder={t('ncr.corrective_action_placeholder', {
                    defaultValue: 'What was done to correct the non-conformance...',
                  })}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                  {t('ncr.label_preventive_action', { defaultValue: 'Preventive Action' })}
                </label>
                <textarea
                  value={draft.preventive_action ?? ''}
                  onChange={(e) => setDraft((d) => ({ ...d, preventive_action: e.target.value }))}
                  rows={2}
                  className={textareaCls}
                  placeholder={t('ncr.preventive_action_placeholder', {
                    defaultValue: 'How recurrence will be prevented...',
                  })}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                  {t('ncr.label_cost_impact', { defaultValue: 'Cost impact' })}
                </label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={draft.cost_impact ?? ''}
                  onChange={(e) => setDraft((d) => ({ ...d, cost_impact: e.target.value }))}
                  className={inputCls}
                  placeholder="0.00"
                />
              </div>
              <div className="flex items-center gap-2">
                <Button variant="primary" size="sm" onClick={saveEdit} disabled={busy}>
                  <Save size={14} className="mr-1.5" />
                  {t('ncr.save_details', { defaultValue: 'Save changes' })}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setEditing(false)} disabled={busy}>
                  {t('common.cancel', { defaultValue: 'Cancel' })}
                </Button>
              </div>
            </div>
          )}

          {/* Actions - edit toggle plus the legal lifecycle moves. Forward moves
              (except the final close) PATCH the status; closing routes through
              the dedicated endpoint so the corrective-action guard fires. Every
              move offered here is one ncrFsm reports the backend will accept. */}
          {!isTerminal && (
            <div className="flex items-center flex-wrap gap-2 pt-1">
              {!editing && (
                <Button variant="secondary" size="sm" onClick={beginEdit} disabled={busy}>
                  <Pencil size={14} className="mr-1.5" />
                  {t('ncr.edit_details', { defaultValue: 'Edit details' })}
                </Button>
              )}
              {moves.forward.map((next) =>
                next === 'closed' ? (
                  <Button
                    key={next}
                    variant="primary"
                    size="sm"
                    disabled={busy || !ncr.corrective_action}
                    onClick={(e) => {
                      e.stopPropagation();
                      onClose(ncr.id);
                    }}
                    title={
                      ncr.corrective_action
                        ? undefined
                        : t('ncr.corrective_action_required_hint', {
                            defaultValue:
                              'Record a corrective action before this NCR can be closed.',
                          })
                    }
                  >
                    <CheckCircle2 size={14} className="mr-1.5" />
                    {t('ncr.action_close', { defaultValue: 'Close NCR' })}
                  </Button>
                ) : (
                  <Button
                    key={next}
                    variant="primary"
                    size="sm"
                    disabled={busy}
                    onClick={(e) => {
                      e.stopPropagation();
                      onUpdate(ncr.id, { status: next });
                    }}
                  >
                    <ArrowRight size={14} className="mr-1.5" />
                    {t('ncr.action_advance', { defaultValue: 'Advance' })}:{' '}
                    {t(`ncr.status_${next}`, { defaultValue: next.replace(/_/g, ' ') })}
                  </Button>
                ),
              )}
              {moves.backward.map((prev) => (
                <Button
                  key={prev}
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={(e) => {
                    e.stopPropagation();
                    onUpdate(ncr.id, { status: prev });
                  }}
                >
                  <Undo2 size={14} className="mr-1.5" />
                  {t('ncr.action_send_back', { defaultValue: 'Send back' })}:{' '}
                  {t(`ncr.status_${prev}`, { defaultValue: prev.replace(/_/g, ' ') })}
                </Button>
              ))}
              {moves.canVoid && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  className="text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/20"
                  onClick={(e) => {
                    e.stopPropagation();
                    onVoid(ncr.id);
                  }}
                >
                  <Ban size={14} className="mr-1.5" />
                  {t('ncr.action_void', { defaultValue: 'Void' })}
                </Button>
              )}
              {ncr.cost_impact != null && ncr.cost_impact > 0 && (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={(e) => {
                    e.stopPropagation();
                    onCreateVariation(ncr.id);
                  }}
                >
                  <DollarSign size={14} className="mr-1" />
                  {t('ncr.create_variation', { defaultValue: 'Create Change Order' })}
                </Button>
              )}
            </div>
          )}

          {/* Closure gate hint - the Close button above is disabled until a
              corrective action exists; spell out why. */}
          {!isTerminal && ncr.status === 'verification' && !ncr.corrective_action && (
            <p className="text-2xs text-amber-600 dark:text-amber-400">
              {t('ncr.corrective_action_required_hint', {
                defaultValue: 'Record a corrective action before this NCR can be closed.',
              })}
            </p>
          )}

          {ncr.cost_impact != null && ncr.cost_impact > 0 && (
            <div className="mt-2" onClick={(e) => e.stopPropagation()}>
              <RaiseBackCharge projectId={ncr.project_id} source={{ kind: 'ncr', id: ncr.id }} />
            </div>
          )}

          {/* Related cross-links */}
          <div className="flex flex-wrap gap-1.5 mt-3 pt-3 border-t border-border-light">
            <span className="text-2xs text-content-quaternary">
              {t('ncr.related', { defaultValue: 'Related' })}:
            </span>
            {ncr.linked_inspection_id && (
              <Button
                variant="ghost"
                size="sm"
                className="text-2xs"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(inspectionDeepLink);
                }}
              >
                <ClipboardCheck size={11} className="mr-1" />
                {t('ncr.view_inspection', { defaultValue: 'View Inspection' })}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="text-2xs"
              onClick={(e) => {
                e.stopPropagation();
                navigate('/changeorders');
              }}
            >
              <DollarSign size={11} className="mr-1" />
              {t('ncr.view_change_orders', { defaultValue: 'View Change Orders' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-2xs"
              onClick={(e) => {
                e.stopPropagation();
                navigate('/punchlist');
              }}
            >
              <ListChecks size={11} className="mr-1" />
              {t('ncr.view_punchlist', { defaultValue: 'View Punch List' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
});

/* -- Main Page ------------------------------------------------------------- */

/* ── How it works + module connections ─────────────────────────────────── */

/** Compact inline link to a sibling module, keeping the connections readable. */
function ModLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * At-a-glance card: what the NCR module does, the stages of running a
 * non-conformance from raise to close, and the sibling modules it links to.
 * Keeps the quality-to-cost trail obvious without expanding the SectionIntro.
 */
function HowNcrWork() {
  const { t } = useTranslation();

  const steps: { icon: React.ReactNode; title: string; desc: string }[] = [
    {
      icon: <AlertOctagon size={14} className="text-oe-blue" />,
      title: t('ncr.how_step1_title', { defaultValue: 'Raise' }),
      desc: t('ncr.how_step1_desc', {
        defaultValue: 'Classify the defect by type and severity and describe what breaches the spec.',
      }),
    },
    {
      icon: <Search size={14} className="text-oe-blue" />,
      title: t('ncr.how_step2_title', { defaultValue: 'Fix the cause' }),
      desc: t('ncr.how_step2_desc', {
        defaultValue: 'Record the root cause, the corrective action and a preventive action.',
      }),
    },
    {
      icon: <DollarSign size={14} className="text-oe-blue" />,
      title: t('ncr.how_step3_title', { defaultValue: 'Escalate cost' }),
      desc: t('ncr.how_step3_desc', {
        defaultValue: 'If the defect carries a cost, escalate it to a Change Order.',
      }),
    },
    {
      icon: <CheckCircle2 size={14} className="text-oe-blue" />,
      title: t('ncr.how_step4_title', { defaultValue: 'Close' }),
      desc: t('ncr.how_step4_desc', {
        defaultValue: 'Verify the fix and close the report, leaving a dated record of the cycle.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="ncr.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('ncr.how_title', { defaultValue: 'How NCRs fit together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('ncr.how_intro', {
          defaultValue:
            'Log work that fails specification as a numbered report, fix the root cause and keep the cost trail attached. Start by raising an NCR for the non-conforming work.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <React.Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-primary/70 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle">
                  {s.icon}
                </span>
                <span className="text-xs font-semibold text-content-primary">{s.title}</span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </React.Fragment>
        ))}
      </ol>

      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('ncr.how_connects', { defaultValue: 'Connects with:' })}
        </span>{' '}
        <ModLink to="/inspections">
          {t('ncr.mod_inspections', { defaultValue: 'Inspections' })}
        </ModLink>
        {' · '}
        <ModLink to="/qms">{t('ncr.mod_qms', { defaultValue: 'QMS overview' })}</ModLink>
        {' · '}
        <ModLink to="/changeorders">
          {t('ncr.mod_changeorders', { defaultValue: 'Change Orders' })}
        </ModLink>
        {' · '}
        <ModLink to="/moc">{t('ncr.mod_moc', { defaultValue: 'Management of Change' })}</ModLink>
        {' · '}
        <ModLink to="/closeout">
          {t('ncr.mod_closeout', { defaultValue: 'Handover & Closeout' })}
        </ModLink>
      </div>
    </CollapsibleSection>
  );
}

/* -- Main Page (card) ------------------------------------------------------ */

export function NCRPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Deep-link target (e.g. from an inspection's "Open NCR" toast). The matching
  // row auto-expands, scrolls into view and flashes once the data has loaded.
  const highlightId = searchParams.get('highlight');
  // Subcontractor name passed from the rating "Quality NCRs" cross-link
  // (CONN-44). Seeds the search box once so the register opens filtered to that
  // firm; the user can then clear or refine it like any other search.
  const subParam = searchParams.get('sub');

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState(() => subParam ?? '');
  const [statusFilter, setStatusFilter] = useState<NCRStatus | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const activeProject = projects.find((p) => p.id === projectId);
  const projectName = activeProject?.name || '';
  // Active project's currency, so cost impact renders in the project's own
  // currency rather than a hardcoded dollar symbol (matches Risk Register).
  const projectCurrency = activeProject?.currency || 'EUR';
  // Genuinely-selected project (route param or shared context) — used for
  // the breadcrumb so the trail never shows a first-project guess.
  const selectedProjectId = routeProjectId || activeProjectId || '';
  const breadcrumbProjectName =
    projects.find((p) => p.id === selectedProjectId)?.name || '';

  // Read every page rather than the first one. The route caps `limit` at 100
  // and defaults to 50, and the four tiles below are reduced over whatever
  // came back - the first of them is labelled "Total". On a project past the
  // cap that tile stated the page size and called it the register. The same
  // rows also feed the Insights panel, so a short read would have understated
  // every chart on the page with nothing on screen saying so.
  const {
    data: ncrsPage,
    isLoading,
    isError: ncrsError,
    error: ncrsErrorValue,
    refetch: refetchNcrs,
  } = useQuery({
    queryKey: ['ncrs', projectId, statusFilter],
    queryFn: () =>
      fetchAllPages<NCR>((offset, limit) =>
        fetchNCRs({ project_id: projectId, status: statusFilter || undefined, offset, limit }),
      ),
    enabled: !!projectId,
  });
  const ncrs = useMemo(() => ncrsPage?.items ?? [], [ncrsPage]);

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return ncrs;
    const q = searchQuery.toLowerCase();
    return ncrs.filter(
      (n) =>
        n.title.toLowerCase().includes(q) ||
        String(n.ncr_number).includes(q) ||
        n.description.toLowerCase().includes(q),
    );
  }, [ncrs, searchQuery]);

  // Stats
  const stats = useMemo(() => {
    const total = ncrs.length;
    const open = ncrs.filter((n) => n.status === 'identified').length;
    const underReview = ncrs.filter((n) => n.status === 'under_review').length;
    const closed = ncrs.filter((n) => n.status === 'closed').length;
    return { total, open, underReview, closed };
  }, [ncrs]);

  // Module Insights - the toggleable visualization panel for this module. Built
  // client-side from the NCRs already loaded; when the project has none the
  // panel draws nothing rather than inventing rows to fill it. Declared with
  // the other top-of-component hooks so the hook order stays stable.
  const insights = useModuleInsights('ncr', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildNCRInsights(ncrs, projectCurrency, t),
    [ncrs, projectCurrency, t],
  );

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['ncrs'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateNCRPayload) => createNCR(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('ncr.created', { defaultValue: 'NCR created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const closeMut = useMutation({
    mutationFn: (id: string) => closeNCR(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('ncr.closed', { defaultValue: 'NCR closed' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  // Edit descriptive fields or walk the NCR one legal step along its lifecycle.
  // The backend validates each status transition against its FSM, so an illegal
  // move surfaces as a plain error toast rather than a silent no-op.
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateNCRPayload }) => updateNCR(id, data),
    onSuccess: (_res, vars) => {
      invalidateAll();
      addToast({
        type: 'success',
        title:
          vars.data.status === 'void'
            ? t('ncr.voided', { defaultValue: 'NCR voided' })
            : t('ncr.updated', { defaultValue: 'NCR updated' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const createVariationMut = useMutation({
    mutationFn: (ncrId: string) =>
      apiPost<{ change_order_id: string; code: string; title: string }>(
        `/v1/ncr/${ncrId}/create-variation/`,
        {},
      ),
    onSuccess: (data) => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('ncr.variation_created', { defaultValue: 'Change order created' }),
        message: `${data.code}: ${data.title}`,
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: NCRFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        ncr_type: formData.ncr_type,
        severity: formData.severity,
        description: formData.description,
        location_description: formData.location || undefined,
        root_cause: formData.root_cause || undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const { confirm, ...confirmProps } = useConfirm();

  const handleClose = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('ncr.confirm_close_title', { defaultValue: 'Close NCR?' }),
        message: t('ncr.confirm_close_msg', { defaultValue: 'This non-conformance report will be closed.' }),
        confirmLabel: t('ncr.action_close', { defaultValue: 'Close NCR' }),
        variant: 'warning',
      });
      if (ok) closeMut.mutate(id);
    },
    [closeMut, confirm, t],
  );

  const handleCreateVariation = useCallback(
    (id: string) => {
      createVariationMut.mutate(id);
    },
    [createVariationMut],
  );

  const handleUpdate = useCallback(
    (id: string, data: UpdateNCRPayload) => {
      updateMut.mutate({ id, data });
    },
    [updateMut],
  );

  const handleVoid = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('ncr.confirm_void_title', { defaultValue: 'Void this NCR?' }),
        message: t('ncr.confirm_void_msg', {
          defaultValue:
            'A voided NCR is closed without a corrective action and cannot be reopened.',
        }),
        confirmLabel: t('ncr.action_void', { defaultValue: 'Void' }),
        variant: 'warning',
      });
      if (ok) updateMut.mutate({ id, data: { status: 'void' } });
    },
    [updateMut, confirm, t],
  );

  const rowBusy = updateMut.isPending || closeMut.isPending || createVariationMut.isPending;

  // The ?sub seed has been copied into searchQuery on first render; drop the
  // param (replace, preserving other params) so the search becomes a normal,
  // user-editable filter and a refresh does not re-pin it.
  useEffect(() => {
    if (!subParam) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('sub');
        return next;
      },
      { replace: true },
    );
  }, [subParam, setSearchParams]);

  // Once the highlighted NCR is present, let the row flash then drop the
  // ?highlight param (replace, preserving other params) so a refresh or
  // back-navigation does not re-trigger the highlight.
  useEffect(() => {
    if (!highlightId) return;
    if (!ncrs.some((n) => n.id === highlightId)) return;
    const timer = window.setTimeout(() => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('highlight');
          return next;
        },
        { replace: true },
      );
    }, 2600);
    return () => window.clearTimeout(timer);
  }, [highlightId, ncrs, setSearchParams]);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          ...(selectedProjectId && breadcrumbProjectName
            ? [{ label: breadcrumbProjectName, to: `/projects/${selectedProjectId}` }]
            : []),
          { label: t('ncr.title', { defaultValue: 'NCR' }) },
        ]}
      />

      {/* Header */}
      <PageHeader
        srTitle={t('ncr.title', { defaultValue: 'NCR' })}
        subtitle={t('ncr.subtitle', {
          defaultValue: 'Document non-conforming work, root causes, and corrective actions',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <ModuleGuideButton content={ncrGuide} />
            <IssueHubLink />
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowCreateModal(true)}
              disabled={!projectId}
              title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
              icon={<Plus size={14} />}
            >
              {t('ncr.new_ncr', { defaultValue: 'New NCR' })}
            </Button>
          </>
        }
      />

      {/* Module Insights panel - toggled by the header button. Placed high so
          its charts are visible the moment the register opens. */}
      <InsightsPanel
        open={insights.open}
        title={t('ncr.insights.title', { defaultValue: 'NCR insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <SectionIntro
        storageKey="ncr"
        title={t('ncr.intro_title', {
          defaultValue: 'Catch defective work, fix the cause',
        })}
        more={
          <IntroRichText
            text={t('ncr.intro_more', {
              defaultValue:
                'A non-conformance is work that does not meet the specification: concrete below strength, a duct run that clashes, a missing test certificate, a safety breach. Left as a verbal "we will sort it out", these turn into disputes, rejected work and arguments over who pays. A Non-Conformance Report makes the defect a formal record with a number, a severity and an owner, so it cannot quietly disappear and the cause gets fixed rather than just the symptom.\n\n**You put in:**\n- The non-conformance type (material, workmanship, design, documentation or safety) and a severity from observation up to critical\n- A clear title and description of what was observed, where, and which specification was not met\n- The location on site and, if known, a preliminary root cause\n- Corrective and preventive actions as the investigation progresses\n\n**You get out:**\n- A numbered NCR register with status from identified through review, corrective action and verification to closed\n- At-a-glance counts of total, open, under-review and closed NCRs\n- Traceability badges when an NCR was auto-raised from a clash or a blocking validation error\n- A one-click Variation when the defect carries a cost, linking the quality record to the commercial one\n\n**How it works day to day:**\n1. Raise the NCR, classify it and describe the defect against the spec it breaches.\n2. Investigate the root cause and record the corrective action that fixes this instance.\n3. Add a preventive action so the same failure does not recur on the next pour or run.\n4. If the fix costs money, create a Variation straight from the NCR to capture the commercial impact.\n5. Verify the work and close the NCR, leaving a dated record of the whole cycle.\n\nNCRs are frequently raised straight from a failed Inspection, which pre-fills the defect from the checklist. Minor snags that just need a re-check belong on the Punch List instead, while genuine non-conformances that need root-cause analysis stay here. When there is a cost, the trail runs on to Change Orders so quality and money never separate.',
            })}
          />
        }
        links={[
          {
            label: t('ncr.intro_link_inspections', { defaultValue: 'Inspections' }),
            onClick: () => navigate('/inspections'),
          },
          {
            label: t('ncr.intro_link_changeorders', { defaultValue: 'Change Orders' }),
            onClick: () => navigate('/changeorders'),
          },
          {
            label: t('ncr.intro_link_punch', { defaultValue: 'Punch List' }),
            onClick: () => navigate('/punchlist'),
          },
        ]}
      >
        {t('ncr.intro_body', {
          defaultValue:
            'Document work that does not meet specification (material, workmanship, design, documentation or safety), record the root cause and the corrective and preventive actions. NCRs are often raised straight from a failed Inspection, and when a defect carries a cost impact you can escalate it to a Change Order so the money and the quality trail stay connected.',
        })}
      </SectionIntro>

      <HowNcrWork />

      {projectId ? (
      <>
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('ncr.stat_total', { defaultValue: 'Total' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-content-primary">{stats.total}</p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('ncr.stat_open', { defaultValue: 'Open' })}
          </p>
          <p
            className={clsx(
              'text-lg font-semibold mt-1 tabular-nums',
              stats.open > 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
          >
            {stats.open}
          </p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('ncr.stat_under_review', { defaultValue: 'Under Review' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-amber-500">{stats.underReview}</p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('ncr.stat_closed', { defaultValue: 'Closed' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-semantic-success">
            {stats.closed}
          </p>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('ncr.search_placeholder', {
              defaultValue: 'Search NCRs...',
            })}
            aria-label={t('ncr.search_placeholder', { defaultValue: 'Search NCRs...' })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as NCRStatus | '')}
            aria-label={t('ncr.filter_all_statuses', { defaultValue: 'All Statuses' })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
          >
            <option value="">
              {t('ncr.filter_all_statuses', { defaultValue: 'All Statuses' })}
            </option>
            {NCR_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`ncr.status_${s}`, {
                  defaultValue: s.replace(/_/g, ' '),
                })}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 end-0 flex items-center pe-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>
      </div>

      {/* Table */}
      <div>
        {isLoading ? (
          <SkeletonTable rows={5} columns={6} />
        ) : ncrsError ? (
          <RecoveryCard error={ncrsErrorValue} onRetry={() => refetchNcrs()} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<AlertOctagon size={28} strokeWidth={1.5} />}
            title={
              searchQuery || statusFilter
                ? t('ncr.no_results', { defaultValue: 'No matching NCRs' })
                : t('ncr.no_ncrs', { defaultValue: 'No NCRs yet' })
            }
            description={
              searchQuery || statusFilter
                ? t('ncr.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('ncr.no_ncrs_hint', {
                    defaultValue: 'Create your first Non-Conformance Report',
                  })
            }
            action={
              !searchQuery && !statusFilter
                ? {
                    label: t('ncr.new_ncr', { defaultValue: 'New NCR' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('ncr.showing_count', {
                defaultValue: '{{count}} NCRs',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {/* Table header */}
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
                <span className="w-5" />
                <span className="w-20">#</span>
                <span className="flex-1">
                  {t('ncr.col_title', { defaultValue: 'Title' })}
                </span>
                <span className="w-24 text-center">
                  {t('ncr.col_type', { defaultValue: 'Type' })}
                </span>
                <span className="w-20 text-center">
                  {t('ncr.col_severity', { defaultValue: 'Severity' })}
                </span>
                <span className="w-20 text-right hidden md:block">
                  {t('ncr.col_cost_impact', { defaultValue: 'Cost Impact' })}
                </span>
                <span className="w-28 text-center">
                  {t('ncr.col_status', { defaultValue: 'Status' })}
                </span>
              </div>

              {/* Rows */}
              {filtered.map((ncr) => (
                <NCRRow
                  key={ncr.id}
                  ncr={ncr}
                  currency={projectCurrency}
                  onClose={handleClose}
                  onCreateVariation={handleCreateVariation}
                  onUpdate={handleUpdate}
                  onVoid={handleVoid}
                  busy={rowBusy}
                  highlight={highlightId === ncr.id}
                />
              ))}
            </Card>
          </>
        )}
      </div>
      </>
      ) : (
        <RequiresProject
          emptyHint={t('ncr.select_project', { defaultValue: 'Open a project first to view and manage NCRs.' })}
        >{null}</RequiresProject>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <CreateNCRModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
          projectName={projectName}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
