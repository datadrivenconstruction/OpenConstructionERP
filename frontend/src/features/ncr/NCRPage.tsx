import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
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
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, SkeletonTable } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchNCRs,
  createNCR,
  closeNCR,
  type NCR,
  type NCRType,
  type NCRSeverity,
  type NCRStatus,
  type CreateNCRPayload,
} from './api';

/* -- Constants ------------------------------------------------------------- */

interface Project {
  id: string;
  name: string;
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
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
                        defaultValue: sev.charAt(0).toUpperCase() + sev.slice(1),
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
  onClose,
  onCreateVariation,
}: {
  ncr: NCR;
  onClose: (id: string) => void;
  onCreateVariation: (id: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const statusCfg = STATUS_CONFIG[ncr.status] ?? STATUS_CONFIG.identified;
  const typeCfg = NCR_TYPE_COLORS[ncr.ncr_type] ?? 'neutral';
  const severityCfg = SEVERITY_CONFIG[ncr.severity] ?? SEVERITY_CONFIG.minor;

  return (
    <div className="border-b border-border-light last:border-b-0">
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

        {/* Type badge */}
        <Badge variant={typeCfg} size="sm">
          {t(`ncr.type_${ncr.ncr_type}`, {
            defaultValue: ncr.ncr_type.charAt(0).toUpperCase() + ncr.ncr_type.slice(1),
          })}
        </Badge>

        {/* Severity badge */}
        <Badge variant={severityCfg.variant} size="sm" className={severityCfg.cls}>
          {t(`ncr.severity_${ncr.severity}`, {
            defaultValue: ncr.severity.charAt(0).toUpperCase() + ncr.severity.slice(1),
          })}
        </Badge>

        {/* Cost Impact */}
        <span className="text-xs text-content-tertiary w-20 text-right shrink-0 hidden md:block tabular-nums">
          {ncr.cost_impact != null && ncr.cost_impact > 0 ? (
            <span className="flex items-center justify-end gap-0.5 text-amber-500 font-medium">
              <DollarSign size={12} />
              {ncr.cost_impact.toLocaleString()}
            </span>
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

          {/* Linked Inspection */}
          {ncr.linked_inspection_number != null && (
            <div className="flex items-center gap-2">
              <ClipboardCheck size={13} className="text-content-tertiary" />
              <span className="text-xs text-content-tertiary">
                {t('ncr.linked_inspection', { defaultValue: 'Linked Inspection' })}:
              </span>
              <Badge variant="neutral" size="sm">
                INS-{String(ncr.linked_inspection_number).padStart(3, '0')}
              </Badge>
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

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {ncr.status !== 'closed' && ncr.status !== 'void' && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(ncr.id);
                }}
              >
                <CheckCircle2 size={14} className="mr-1.5" />
                {t('ncr.action_close', { defaultValue: 'Close NCR' })}
              </Button>
            )}
            {ncr.cost_impact != null && ncr.cost_impact > 0 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onCreateVariation(ncr.id);
                }}
              >
                <DollarSign size={14} className="mr-1" />
                {t('ncr.create_variation', { defaultValue: 'Create Variation' })}
              </Button>
            )}
          </div>

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
                  navigate('/inspections');
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

export function NCRPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<NCRStatus | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: ncrs = [], isLoading } = useQuery({
    queryKey: ['ncrs', projectId, statusFilter],
    queryFn: () =>
      fetchNCRs({
        project_id: projectId,
        status: statusFilter || undefined,
      }),
    enabled: !!projectId,
  });

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

  const createVariationMut = useMutation({
    mutationFn: (ncrId: string) =>
      apiPost<{ change_order_id: string; code: string; title: string }>(
        `/v1/ncr/${ncrId}/create-variation`,
        {},
      ),
    onSuccess: (data) => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('ncr.variation_created', { defaultValue: 'Variation created' }),
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

  return (
    <div className="w-full animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          ...(projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('ncr.title', { defaultValue: 'NCR' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('ncr.page_title', { defaultValue: 'Non-Conformance Reports' })}
        </h1>

        <div className="flex items-center gap-2 shrink-0">
          {!routeProjectId && projects.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                const p = projects.find((pr) => pr.id === e.target.value);
                if (p) {
                  useProjectContextStore.getState().setActiveProject(p.id, p.name);
                }
              }}
              aria-label={t('ncr.select_project', { defaultValue: 'Project...' })}
              className={inputCls + ' !h-8 !text-xs max-w-[180px]'}
            >
              <option value="" disabled>
                {t('ncr.select_project', { defaultValue: 'Project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
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
        </div>
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 px-4 py-3">
          <AlertTriangle size={18} className="text-amber-600 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-800 dark:text-amber-300">{t('common.no_project_selected', { defaultValue: 'No project selected' })}</p>
            <p className="text-xs text-amber-600 dark:text-amber-400">{t('common.select_project_hint', { defaultValue: 'Select a project from the header to view and manage items.' })}</p>
          </div>
        </div>
      )}

      {projectId ? (
      <>
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('ncr.stat_total', { defaultValue: 'Total' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-content-primary">{stats.total}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('ncr.stat_open', { defaultValue: 'Open' })}
          </p>
          <p
            className={clsx(
              'text-2xl font-bold mt-1 tabular-nums',
              stats.open > 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
          >
            {stats.open}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('ncr.stat_under_review', { defaultValue: 'Under Review' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-amber-500">{stats.underReview}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('ncr.stat_closed', { defaultValue: 'Closed' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-semantic-success">
            {stats.closed}
          </p>
        </Card>
      </div>

      {/* Toolbar */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center gap-3">
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
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
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
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>
      </div>

      {/* Table */}
      <div>
        {isLoading ? (
          <SkeletonTable rows={5} columns={6} />
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
                <NCRRow key={ncr.id} ncr={ncr} onClose={handleClose} onCreateVariation={handleCreateVariation} />
              ))}
            </Card>
          </>
        )}
      </div>
      </>
      ) : (
        <EmptyState
          icon={<AlertOctagon size={28} strokeWidth={1.5} />}
          title={t('ncr.no_project', { defaultValue: 'No project selected' })}
          description={t('ncr.select_project', { defaultValue: 'Open a project first to view and manage NCRs.' })}
        />
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
