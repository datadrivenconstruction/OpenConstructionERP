import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  FileCheck,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  Info,
  Edit3,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  DateDisplay,
  DismissibleInfo,
  IntroRichText,
  RecoveryCard,
  SkeletonTable,
  ConfirmDialog,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchSubmittals,
  createSubmittal,
  updateSubmittal,
  submitSubmittal,
  submitReviewDecision,
  type Submittal,
  type SubmittalStatus,
  type SubmittalType,
  type CreateSubmittalPayload,
  type UpdateSubmittalPayload,
  type ApproveSubmittalPayload,
} from './api';
import { SubmittalStatusPipeline } from './SubmittalStatusPipeline';
import { DueDateBadge } from './DueDateBadge';
import { DaysInCourtBadge } from './DaysInCourtBadge';
import {
  ApprovalInstanceCard,
  ApprovalTargetBadge,
} from '@/features/approval-routes';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const STATUS_CONFIG: Record<
  SubmittalStatus,
  { variant: 'neutral' | 'blue' | 'success' | 'error' | 'warning'; cls: string }
> = {
  draft: { variant: 'neutral', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  submitted: { variant: 'blue', cls: '' },
  under_review: { variant: 'warning', cls: '' },
  approved: { variant: 'success', cls: '' },
  approved_as_noted: {
    variant: 'success',
    cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  revise_and_resubmit: {
    variant: 'warning',
    cls: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  },
  rejected: { variant: 'error', cls: '' },
  closed: {
    variant: 'blue',
    cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
};

const TYPE_LABELS: Record<SubmittalType, string> = {
  shop_drawing: 'Shop Drawing',
  product_data: 'Product Data',
  sample: 'Sample',
  mock_up: 'Mock-Up',
  test_report: 'Test Report',
  certificate: 'Certificate',
  warranty: 'Warranty',
};

const STATUS_LABELS: Record<SubmittalStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  under_review: 'Under Review',
  approved: 'Approved',
  approved_as_noted: 'Approved as Noted',
  revise_and_resubmit: 'Revise & Resubmit',
  rejected: 'Rejected',
  closed: 'Closed',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Create Modal ─────────────────────────────────────────────────────── */

interface SubmittalFormData {
  title: string;
  spec_section: string;
  type: SubmittalType;
  date_required: string;
  description: string;
}

const EMPTY_FORM: SubmittalFormData = {
  title: '',
  spec_section: '',
  type: 'shop_drawing',
  date_required: '',
  description: '',
};

/**
 * SubmittalFormModal — unified create/edit form for submittals.
 *
 * Both modes share the same field list (title / spec_section / type /
 * date_required / description) and validation rules, so centralising
 * them here keeps create + edit in lock-step. The `mode` prop swaps the
 * heading, primary button label, and pre-fills the form from `existing`
 * when editing. Field IDs vary per-mode so create + edit can coexist
 * (e.g. via tests) without conflicting `htmlFor` references.
 */
function SubmittalFormModal({
  mode,
  existing,
  onClose,
  onSubmit,
  isPending,
}: {
  mode: 'create' | 'edit';
  existing?: Submittal;
  onClose: () => void;
  onSubmit: (data: SubmittalFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const isEdit = mode === 'edit';
  const idPrefix = isEdit ? 'edit-submittal' : 'submittal';

  const [form, setForm] = useState<SubmittalFormData>(() =>
    isEdit && existing
      ? {
          title: existing.title,
          spec_section: existing.spec_section ?? '',
          type: existing.type,
          date_required: existing.date_required ?? '',
          description: existing.description ?? '',
        }
      : EMPTY_FORM,
  );
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof SubmittalFormData>(key: K, value: SubmittalFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const titleError = touched && form.title.trim().length === 0;
  const specError = touched && form.spec_section.trim().length === 0;
  const canSubmit = form.title.trim().length > 0 && form.spec_section.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="lg"
      title={
        isEdit
          ? t('submittals.edit_submittal', { defaultValue: 'Edit Submittal' })
          : t('submittals.new_submittal', { defaultValue: 'New Submittal' })
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : !isEdit ? (
              <Plus size={16} className="mr-1.5 shrink-0" />
            ) : null}
            <span>
              {isEdit
                ? t('submittals.save_changes', { defaultValue: 'Save Changes' })
                : t('submittals.create_submittal', { defaultValue: 'Create Submittal' })}
            </span>
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('submittals.field_title', { defaultValue: 'Title' })}
          required
          span={2}
          htmlFor={`${idPrefix}-title`}
          error={
            titleError
              ? t('submittals.title_required', { defaultValue: 'Title is required' })
              : undefined
          }
        >
          <input
            id={`${idPrefix}-title`}
            value={form.title}
            onChange={(e) => {
              set('title', e.target.value);
              setTouched(true);
            }}
            placeholder={t('submittals.title_placeholder', {
              defaultValue: 'e.g. Structural Steel Shop Drawings - Level 3',
            })}
            className={clsx(
              inputCls,
              titleError &&
                'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
          />
        </WideModalField>

        <WideModalField
          label={t('submittals.field_spec_section', { defaultValue: 'Spec Section' })}
          required
          htmlFor={`${idPrefix}-spec-section`}
          error={
            specError
              ? t('submittals.spec_required', { defaultValue: 'Spec section is required' })
              : undefined
          }
        >
          <input
            id={`${idPrefix}-spec-section`}
            value={form.spec_section}
            onChange={(e) => {
              set('spec_section', e.target.value);
              setTouched(true);
            }}
            placeholder={t('submittals.spec_placeholder', {
              defaultValue: 'e.g. 05 12 00',
            })}
            className={clsx(
              inputCls,
              specError &&
                'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
          />
        </WideModalField>

        <WideModalField
          label={t('submittals.field_type', { defaultValue: 'Type' })}
          htmlFor={`${idPrefix}-type`}
        >
          <div className="relative">
            <select
              id={`${idPrefix}-type`}
              value={form.type}
              onChange={(e) => set('type', e.target.value as SubmittalType)}
              className={inputCls + ' appearance-none pr-9'}
            >
              {(Object.keys(TYPE_LABELS) as SubmittalType[]).map((tp) => (
                <option key={tp} value={tp}>
                  {t(`submittals.type_${tp}`, { defaultValue: TYPE_LABELS[tp] })}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </WideModalField>

        <WideModalField
          label={t('submittals.field_date_required', { defaultValue: 'Date Required' })}
          span={2}
          htmlFor={`${idPrefix}-date-required`}
        >
          <input
            id={`${idPrefix}-date-required`}
            type="date"
            value={form.date_required}
            onChange={(e) => set('date_required', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('submittals.field_description', { defaultValue: 'Description' })}
          span={2}
          htmlFor={`${idPrefix}-description`}
        >
          <textarea
            id={`${idPrefix}-description`}
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={
              !isEdit
                ? t('submittals.description_placeholder', {
                    defaultValue: 'Additional details about this submittal...',
                  })
                : undefined
            }
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Approve/Review Modal ──────────────────────────────────────────────── */

function ApproveModal({
  submittal,
  onClose,
  onSubmit,
  isPending,
}: {
  submittal: Submittal;
  onClose: () => void;
  onSubmit: (data: ApproveSubmittalPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [decision, setDecision] = useState<ApproveSubmittalPayload['status']>('approved');
  const [comments, setComments] = useState('');

  const handleSubmit = () => {
    onSubmit({ status: decision, comments: comments.trim() || undefined });
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
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4" role="dialog" aria-modal="true" aria-label={t('submittals.review_title', { defaultValue: 'Review {{number}}', number: submittal.submittal_number })}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('submittals.review_title', {
              defaultValue: 'Review {{number}}',
              number: submittal.submittal_number,
            })}
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
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary mb-1">
              {t('submittals.label_title', { defaultValue: 'Title' })}
            </p>
            <p className="text-sm text-content-primary">{submittal.title}</p>
          </div>

          {/* Decision */}
          <div>
            <label id="submittal-decision-label" className="block text-sm font-medium text-content-secondary mb-2">
              {t('submittals.field_decision', { defaultValue: 'Decision' })}
            </label>
            <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-labelledby="submittal-decision-label">
              {(
                [
                  'approved',
                  'approved_as_noted',
                  'revise_and_resubmit',
                  'rejected',
                ] as const
              ).map((s) => (
                <button
                  key={s}
                  role="radio"
                  aria-checked={decision === s}
                  onClick={() => setDecision(s)}
                  className={clsx(
                    'rounded-lg border px-3 py-2 text-xs font-medium transition-colors text-left',
                    decision === s
                      ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                      : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                  )}
                >
                  {t(`submittals.status_${s}`, { defaultValue: STATUS_LABELS[s] })}
                </button>
              ))}
            </div>
          </div>

          {/* Comments */}
          <div>
            <label htmlFor="submittal-review-comments" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('submittals.field_comments', { defaultValue: 'Comments' })}
            </label>
            <textarea
              id="submittal-review-comments"
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              rows={3}
              className={textareaCls}
              placeholder={t('submittals.comments_placeholder', {
                defaultValue: 'Review comments...',
              })}
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending}>
            {t('submittals.submit_review', { defaultValue: 'Submit Review' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Submittal Row (expandable) ──────────────────────────────────────── */

const SubmittalRow = React.memo(function SubmittalRow({
  submittal,
  projectId,
  onSubmit,
  onReview,
  onEdit,
}: {
  submittal: Submittal;
  projectId: string;
  onSubmit: (id: string) => void;
  onReview: (s: Submittal) => void;
  onEdit: (s: Submittal) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const statusCfg = STATUS_CONFIG[submittal.status] ?? STATUS_CONFIG.draft;

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

        {/* Submittal # */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-20 shrink-0">
          {submittal.submittal_number}
        </span>

        {/* Title */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {submittal.title}
        </span>

        {/* Spec Section */}
        <span className="text-xs text-content-tertiary w-20 shrink-0 hidden lg:block font-mono">
          {submittal.spec_section}
        </span>

        {/* Type badge */}
        <Badge variant="neutral" size="sm" className="hidden md:inline-flex">
          {t(`submittals.type_${submittal.type}`, { defaultValue: TYPE_LABELS[submittal.type] })}
        </Badge>

        {/* Status badge + pipeline. Stacked column so the dot-stepper
            never pushes the row width (matches the procurement pattern
            and keeps mobile layout intact). The pipeline mirrors the
            backend FSM in submittals/service.py. */}
        <div className="flex flex-col items-center gap-1 w-28 shrink-0">
          <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
            {t(`submittals.status_${submittal.status}`, {
              defaultValue: STATUS_LABELS[submittal.status],
            })}
          </Badge>
          <SubmittalStatusPipeline status={submittal.status} />
          {/* Pending-approval indicator (feature 06) — renders only while a
              routed sign-off is running on this submittal. */}
          <ApprovalTargetBadge targetKind="submittal" targetId={submittal.id} />
        </div>

        {/* Ball in Court + days-with-reviewer SLA chip. The chip only
            renders while the submittal is actively in the reviewer's
            court (submitted / under_review) and the elapsed time has
            crossed the neutral threshold — so most rows show just the
            name. */}
        <div className="w-24 shrink-0 hidden md:flex md:flex-col md:items-start md:gap-0.5">
          <span className="text-xs text-content-tertiary truncate w-full">
            {submittal.ball_in_court_name || submittal.ball_in_court || '-'}
          </span>
          <DaysInCourtBadge
            dateSubmitted={submittal.date_submitted}
            status={submittal.status}
          />
        </div>

        {/* Rev # */}
        <span className="text-xs text-content-tertiary w-10 text-center shrink-0 tabular-nums hidden sm:block">
          R{submittal.revision}
        </span>

        {/* Date Required + overdue countdown badge. Stacked column so
            the badge does not steal width from the date. */}
        <div className="text-xs w-20 shrink-0 hidden lg:flex lg:flex-col lg:items-start lg:gap-0.5">
          <DateDisplay value={submittal.date_required} className="text-xs text-content-tertiary" />
          <DueDateBadge
            dateRequired={submittal.date_required}
            status={submittal.status}
          />
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {submittal.description && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
                {t('submittals.label_description', { defaultValue: 'Description' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">
                {submittal.description}
              </p>
            </div>
          )}

          {submittal.review_notes && (
            <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
                {t('submittals.label_review_notes', { defaultValue: 'Reviewer comments' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">
                {submittal.review_notes}
              </p>
            </div>
          )}

          <div className="flex items-center gap-4 text-xs text-content-tertiary">
            <span>
              {t('submittals.label_submitted', { defaultValue: 'Submitted' })}:{' '}
              <DateDisplay value={submittal.date_submitted} className="text-xs" />
            </span>
            <span>
              {t('submittals.label_required', { defaultValue: 'Required' })}:{' '}
              <DateDisplay value={submittal.date_required} className="text-xs" />
            </span>
          </div>

          {/* Linked BOQ items */}
          {(() => {
            const ids = (submittal as unknown as { linked_boq_item_ids?: string[] }).linked_boq_item_ids;
            return ids && ids.length > 0 ? (
              <div className="text-xs text-content-tertiary">
                {t('submittals.linked_boq', {
                  defaultValue: 'Linked to {{count}} BOQ position(s)',
                  count: ids.length,
                })}
              </div>
            ) : null;
          })()}

          {/* Document reference */}
          <p className="text-2xs text-content-quaternary">
            {t('submittals.doc_reference_hint', {
              defaultValue:
                'Upload supporting documents in the Documents module, then reference them here.',
            })}
          </p>

          {/* Reviewer instruction when a resubmission is required so the
              submitter knows the next step instead of hitting a dead end. */}
          {submittal.status === 'revise_and_resubmit' && (
            <div className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 dark:border-orange-800 dark:bg-orange-950/20 p-3 text-xs text-orange-700 dark:text-orange-300">
              <Info size={14} className="mt-0.5 shrink-0" />
              <span>
                {t('submittals.resubmit_hint', {
                  defaultValue:
                    'The reviewer requested changes. Edit this submittal, then resubmit it to start a new revision (R{{next}}).',
                  next: submittal.revision + 1,
                })}
              </span>
            </div>
          )}

          {/* Routed approval workflow (feature 06). When the project has an
              active "submittal" approval route the picker lets a reviewer
              start a multi-step sign-off; each approver's decision drives the
              submittal FSM. Projects with no route configured keep the direct
              Submit / Review / Approve actions below. */}
          <div>
            <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
              {t('submittals.label_approval', { defaultValue: 'Approval workflow' })}
            </p>
            <ApprovalInstanceCard
              targetKind="submittal"
              targetId={submittal.id}
              projectId={projectId}
            />
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {submittal.status === 'draft' && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onSubmit(submittal.id);
                }}
              >
                {t('submittals.action_submit', { defaultValue: 'Submit' })}
              </Button>
            )}
            {submittal.status === 'revise_and_resubmit' && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onSubmit(submittal.id);
                }}
              >
                {t('submittals.action_resubmit', { defaultValue: 'Resubmit' })}
              </Button>
            )}
            {(submittal.status === 'submitted' || submittal.status === 'under_review') && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onReview(submittal);
                }}
              >
                {t('submittals.action_review', { defaultValue: 'Review' })}
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              icon={<Edit3 size={14} />}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(submittal);
              }}
            >
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function SubmittalsPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [reviewingSubmittal, setReviewingSubmittal] = useState<Submittal | null>(null);
  const [editingSubmittal, setEditingSubmittal] = useState<Submittal | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<SubmittalStatus | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  // Genuinely-selected project (route param or shared context) — used for
  // the breadcrumb so the trail never shows a first-project guess.
  const selectedProjectId = routeProjectId || activeProjectId || '';
  const projectName =
    projects.find((p) => p.id === selectedProjectId)?.name || '';

  const {
    data: submittals = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['submittals', projectId, statusFilter],
    queryFn: () =>
      fetchSubmittals({
        project_id: projectId,
        status: statusFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return submittals;
    const q = searchQuery.toLowerCase();
    return submittals.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.submittal_number.toLowerCase().includes(q) ||
        (s.spec_section?.toLowerCase().includes(q) ?? false) ||
        (s.ball_in_court_name?.toLowerCase().includes(q) ?? false),
    );
  }, [submittals, searchQuery]);

  // Stats
  const stats = useMemo(() => {
    const total = submittals.length;
    const pending = submittals.filter(
      (s) => s.status === 'submitted' || s.status === 'under_review',
    ).length;
    const approved = submittals.filter(
      (s) => s.status === 'approved' || s.status === 'approved_as_noted',
    ).length;
    const rejected = submittals.filter(
      (s) => s.status === 'rejected' || s.status === 'revise_and_resubmit',
    ).length;
    return { total, pending, approved, rejected };
  }, [submittals]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['submittals'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateSubmittalPayload) => createSubmittal(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('submittals.created', { defaultValue: 'Submittal created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const submitMut = useMutation({
    mutationFn: (id: string) => submitSubmittal(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('submittals.submitted', { defaultValue: 'Submittal submitted' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const approveMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: ApproveSubmittalPayload }) =>
      submitReviewDecision(id, data),
    onSuccess: () => {
      invalidateAll();
      setReviewingSubmittal(null);
      addToast({
        type: 'success',
        title: t('submittals.reviewed', { defaultValue: 'Review submitted' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateSubmittalPayload }) =>
      updateSubmittal(id, data),
    onSuccess: () => {
      invalidateAll();
      setEditingSubmittal(null);
      addToast({
        type: 'success',
        title: t('submittals.updated', { defaultValue: 'Submittal updated' }),
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
    (formData: SubmittalFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        description: formData.description || undefined,
        spec_section: formData.spec_section || undefined,
        submittal_type: formData.type,
        date_required: formData.date_required || undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const { confirm, ...confirmProps } = useConfirm();

  const handleSubmit = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('submittals.confirm_submit_title', { defaultValue: 'Submit for review?' }),
        message: t('submittals.confirm_submit_msg', { defaultValue: 'This submittal will be sent for review and cannot be edited until the review is complete.' }),
        confirmLabel: t('submittals.action_submit', { defaultValue: 'Submit' }),
        variant: 'warning',
      });
      if (ok) submitMut.mutate(id);
    },
    [submitMut, confirm, t],
  );

  const handleReview = useCallback((s: Submittal) => {
    setReviewingSubmittal(s);
  }, []);

  const handleApproveSubmit = useCallback(
    (data: ApproveSubmittalPayload) => {
      if (!reviewingSubmittal) return;
      approveMut.mutate({ id: reviewingSubmittal.id, data });
    },
    [approveMut, reviewingSubmittal],
  );

  const handleEdit = useCallback((s: Submittal) => {
    setEditingSubmittal(s);
  }, []);

  const handleEditSubmit = useCallback(
    (formData: SubmittalFormData) => {
      if (!editingSubmittal) return;
      updateMut.mutate({
        id: editingSubmittal.id,
        data: {
          title: formData.title,
          description: formData.description || undefined,
          spec_section: formData.spec_section || undefined,
          submittal_type: formData.type,
          date_required: formData.date_required || undefined,
        },
      });
    },
    [updateMut, editingSubmittal],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          ...(selectedProjectId && projectName
            ? [{ label: projectName, to: `/projects/${selectedProjectId}` }]
            : []),
          { label: t('submittals.title', { defaultValue: 'Submittals' }) },
        ]}
      />

      {/* Header */}
      <PageHeader
        subtitle={t('submittals.subtitle', {
          defaultValue: 'Track shop drawings, product data, and samples through review and approval',
        })}
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreateModal(true)}
            disabled={!projectId}
            title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
            className="shrink-0 whitespace-nowrap"
            icon={<Plus size={14} />}
          >
            {t('submittals.new_submittal', { defaultValue: 'New Submittal' })}
          </Button>
        }
      />

      {/* Canonical module info card \u2014 pain-named title + workflow body. */}
      <DismissibleInfo
        storageKey="submittals"
        title={t('submittals.intro_title', { defaultValue: 'No work installed without sign-off' })}
        more={
          t('submittals.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('submittals.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('boq.title', { defaultValue: 'Bill of Quantities' }),
            onClick: () => navigate('/boq'),
          },
          {
            label: t('transmittals.title', { defaultValue: 'Transmittals' }),
            onClick: () => navigate('/transmittals'),
          },
        ]}
      >
        {t('submittals.intro_body', {
          defaultValue:
            'Log each shop drawing, product data sheet, sample or certificate and move it through Draft, Submitted, Under Review, then Approved or Revise-and-resubmit, with a due-date and days-in-court badge so nothing stalls. Link a submittal to the BOQ positions it covers so you can see which items have approved documentation before they go to site.',
        })}
      </DismissibleInfo>

      {!projectId && <RequiresProject>{null}</RequiresProject>}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('submittals.stat_total', { defaultValue: 'Total' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-content-primary">
            {stats.total}
          </p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('submittals.stat_pending', { defaultValue: 'Pending Review' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-amber-500">{stats.pending}</p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('submittals.stat_approved', { defaultValue: 'Approved' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-semantic-success">
            {stats.approved}
          </p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('submittals.stat_rejected', { defaultValue: 'Rejected / Resubmit' })}
          </p>
          <p
            className={clsx(
              'text-lg font-semibold mt-1 tabular-nums',
              stats.rejected > 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
          >
            {stats.rejected}
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
            placeholder={t('submittals.search_placeholder', {
              defaultValue: 'Search submittals...',
            })}
            aria-label={t('submittals.search_placeholder', { defaultValue: 'Search submittals...' })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as SubmittalStatus | '')}
            aria-label={t('submittals.filter_all', { defaultValue: 'All Statuses' })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-48"
          >
            <option value="">
              {t('submittals.filter_all', { defaultValue: 'All Statuses' })}
            </option>
            {(Object.keys(STATUS_LABELS) as SubmittalStatus[]).map((s) => (
              <option key={s} value={s}>
                {t(`submittals.status_${s}`, { defaultValue: STATUS_LABELS[s] })}
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
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<FileCheck size={28} strokeWidth={1.5} />}
            title={
              searchQuery || statusFilter
                ? t('submittals.no_results', { defaultValue: 'No matching submittals' })
                : t('submittals.no_submittals', { defaultValue: 'No submittals yet' })
            }
            description={
              searchQuery || statusFilter
                ? t('submittals.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('submittals.no_submittals_hint', {
                    defaultValue: 'Create your first submittal to track document approvals',
                  })
            }
            action={
              !searchQuery && !statusFilter
                ? {
                    label: t('submittals.new_submittal', { defaultValue: 'New Submittal' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('submittals.showing_count', {
                defaultValue: '{{count}} submittals',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {/* Table header */}
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
                <span className="w-5" />
                <span className="w-20">#</span>
                <span className="flex-1">
                  {t('submittals.col_title', { defaultValue: 'Title' })}
                </span>
                <span className="w-20 hidden lg:block">
                  {t('submittals.col_spec', { defaultValue: 'Spec' })}
                </span>
                <span className="w-24 hidden md:block">
                  {t('submittals.col_type', { defaultValue: 'Type' })}
                </span>
                <span className="w-28 text-center">
                  {t('submittals.col_status', { defaultValue: 'Status' })}
                </span>
                <span className="sr-only">
                  {t('submittals.col_pipeline_sr', { defaultValue: 'Pipeline' })}
                </span>
                <span className="w-24 hidden md:block">
                  {t('submittals.col_bic', { defaultValue: 'Ball in Court' })}
                </span>
                <span className="w-10 text-center hidden sm:block">
                  {t('submittals.col_rev', { defaultValue: 'Rev' })}
                </span>
                <span className="w-20 hidden lg:block">
                  {t('submittals.col_date_required', { defaultValue: 'Required' })}
                </span>
              </div>

              {/* Rows */}
              {filtered.map((s) => (
                <SubmittalRow
                  key={s.id}
                  submittal={s}
                  projectId={projectId}
                  onSubmit={handleSubmit}
                  onReview={handleReview}
                  onEdit={handleEdit}
                />
              ))}
            </Card>
          </>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <SubmittalFormModal
          mode="create"
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
        />
      )}

      {/* Review Modal */}
      {reviewingSubmittal && (
        <ApproveModal
          submittal={reviewingSubmittal}
          onClose={() => setReviewingSubmittal(null)}
          onSubmit={handleApproveSubmit}
          isPending={approveMut.isPending}
        />
      )}

      {/* Edit Modal */}
      {editingSubmittal && (
        <SubmittalFormModal
          mode="edit"
          existing={editingSubmittal}
          onClose={() => setEditingSubmittal(null)}
          onSubmit={handleEditSubmit}
          isPending={updateMut.isPending}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
