// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, useSearchParams, Link } from 'react-router-dom';
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
  Send,
  CheckCircle2,
  Link2,
  Network,
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
  ModuleGuideButton,
  CollapsibleSection,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RecordPdfButton } from '@/shared/ui/RegisterExport';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { fetchProjectList } from '@/shared/lib/projectList';
import { matchesSearch } from '@/shared/lib/highlightMatch';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchSubmittals,
  createSubmittal,
  updateSubmittal,
  submitSubmittal,
  submitReviewDecision,
  fetchSubmittalSummary,
  downloadSubmittalPdf,
  type Submittal,
  type SubmittalStatus,
  SUBMITTAL_TYPES,
  type SubmittalType,
  type SubmittalVocabulary,
  type CreateSubmittalPayload,
  type UpdateSubmittalPayload,
  type ApproveSubmittalPayload,
} from './api';
import { SubmittalStatusPipeline } from './SubmittalStatusPipeline';
import { DueDateBadge } from './DueDateBadge';
import {
  ApprovalNeededBy,
  DisciplineBadge,
  LongLeadMark,
  ReviewClock,
  ReviewCodeChip,
  SortableHeader,
  outcomeHint,
} from './registerCells';
import {
  NO_FILTERS,
  applyClientCut,
  hasActiveFilter,
  hasServerFilter,
  isServerSortable,
  toListFilters,
  useSubmittalVocabulary,
  vocabularyEntry,
  type RegisterFilters,
  type RegisterSort,
} from './registerView';
import {
  EMPTY_PROCUREMENT_FORM,
  SubmittalProcurementFields,
  buildProcurementCreate,
  buildProcurementPatch,
  hasProcurementErrors,
  procurementFormData,
  type ProcurementFormData,
} from './SubmittalProcurementFields';
import { SubmittalRegisterDetail } from './SubmittalRegisterDetail';
import { SubmittalRegisterExport } from './SubmittalRegisterExport';
import { SubmittalRegisterFilters, SubmittalTypeTabs } from './SubmittalRegisterFilters';
import { SubmittalRegisterSummary } from './SubmittalRegisterSummary';
import {
  ApprovalInstanceCard,
  ApprovalTargetBadge,
} from '@/features/approval-routes';
import { submittalsGuide } from './submittalsGuide';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildSubmittalsInsights } from './submittalsInsights';

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
  calculation: 'Calculation',
  method_statement: 'Method Statement',
  certificate: 'Certificate',
  warranty: 'Warranty',
};

/* type is a free string column, so imported data can carry values outside the
   vocabulary the pickers offer. Humanize anything unknown so a missing label
   never falls through to a raw i18n key in the UI. */
const prettySubmittalType = (tp: string): string =>
  tp.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
const submittalTypeLabel = (tp: string | null | undefined): string =>
  (tp ? (TYPE_LABELS as Record<string, string>)[tp] : undefined) ?? prettySubmittalType(tp || 'shop_drawing');

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

interface SubmittalFormData extends ProcurementFormData {
  title: string;
  spec_section: string;
  type: SubmittalType;
  date_required: string;
  description: string;
}

/** The fields whose errors wait until the user has left them. */
type TouchedField = 'title' | 'spec_section' | 'type' | 'date_required' | 'description';

const EMPTY_FORM: SubmittalFormData = {
  title: '',
  spec_section: '',
  type: 'shop_drawing',
  date_required: '',
  description: '',
  ...EMPTY_PROCUREMENT_FORM,
};

/**
 * The form state a submittal opens with.
 *
 * Pure and exported so the edit handler can rebuild the same baseline the
 * modal started from and send only what the user actually changed. Prefilling
 * from a row and then PATCHing every field back overwrites edits made by
 * somebody else in between, on fields the user never opened.
 *
 * `description` is read back out of the backend `metadata` blob by
 * `normaliseSubmittal()` rather than from a dedicated column, so it is already
 * a flat string here and the form never has to know about the metadata shape.
 */
export function submittalFormData(existing?: Submittal): SubmittalFormData {
  if (!existing) return EMPTY_FORM;
  return {
    title: existing.title,
    spec_section: existing.spec_section ?? '',
    type: existing.type,
    date_required: existing.date_required ?? '',
    description: existing.description ?? '',
    ...procurementFormData(existing),
  };
}

/**
 * The body of an edit save: only the fields the user actually changed.
 *
 * Everything on the form used to go back on every save, so correcting a spec
 * section also rewrote the description exactly as it stood when the list was
 * last read, quietly undoing anyone else's edit to it. The update route dumps
 * with `exclude_unset=True`, so a field left out of the body is left alone in
 * the database, which is what makes omission the right tool here.
 *
 * Clearing is still a change, and it has to be expressed as something the wire
 * can carry. `undefined` cannot: `JSON.stringify` drops the key and the old
 * value simply survives, which is why emptying the description or the date
 * used to have no effect at all. An emptied date goes as `null` specifically,
 * because the backend pattern rejects an empty string.
 */
export function buildSubmittalPatch(
  form: SubmittalFormData,
  base: SubmittalFormData,
): UpdateSubmittalPayload {
  const data: UpdateSubmittalPayload = {};
  if (form.title !== base.title) data.title = form.title;
  if (form.description !== base.description) data.description = form.description;
  if (form.spec_section !== base.spec_section) data.spec_section = form.spec_section;
  if (form.type !== base.type) data.submittal_type = form.type;
  if (form.date_required !== base.date_required) {
    data.date_required = form.date_required || null;
  }
  // The register columns follow the same rule: only what was changed.
  return { ...data, ...buildProcurementPatch(form, base) };
}

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
  vocabulary,
}: {
  mode: 'create' | 'edit';
  existing?: Submittal;
  onClose: () => void;
  onSubmit: (data: SubmittalFormData) => void;
  isPending: boolean;
  /** The codes the pickers offer; `null` until the vocabulary route answers. */
  vocabulary: SubmittalVocabulary | null;
}) {
  const { t } = useTranslation();
  const isEdit = mode === 'edit';
  const idPrefix = isEdit ? 'edit-submittal' : 'submittal';

  const [form, setForm] = useState<SubmittalFormData>(() =>
    submittalFormData(isEdit ? existing : undefined),
  );
  // Per-field touched tracking so validation surfaces as the user leaves each
  // field (onBlur) instead of only after a submit attempt. Submitting marks
  // every field touched so any still-empty required field lights up.
  const [touched, setTouched] = useState<Record<TouchedField, boolean>>({
    title: false,
    spec_section: false,
    type: false,
    date_required: false,
    description: false,
  });

  const set = <K extends keyof SubmittalFormData>(key: K, value: SubmittalFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  // The same setter, typed to the register group's own keys for its component.
  const setProcurement = <K extends keyof ProcurementFormData>(key: K, value: ProcurementFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const markTouched = (key: TouchedField) =>
    setTouched((prev) => (prev[key] ? prev : { ...prev, [key]: true }));

  const titleError = touched.title && form.title.trim().length === 0;
  const specError = touched.spec_section && form.spec_section.trim().length === 0;
  const canSubmit =
    form.title.trim().length > 0 && form.spec_section.trim().length > 0 && !hasProcurementErrors(form);

  const handleSubmit = () => {
    setTouched({
      title: true,
      spec_section: true,
      type: true,
      date_required: true,
      description: true,
    });
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
            onChange={(e) => set('title', e.target.value)}
            onBlur={() => markTouched('title')}
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
            onChange={(e) => set('spec_section', e.target.value)}
            onBlur={() => markTouched('spec_section')}
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
              {SUBMITTAL_TYPES.map((tp) => (
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
          hint={t('submittals.date_required_hint', {
            defaultValue: 'The date the review answer is needed by.',
          })}
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

      <SubmittalProcurementFields
        idPrefix={idPrefix}
        form={form}
        type={form.type}
        onChange={setProcurement}
        vocabulary={vocabulary}
        existing={isEdit ? existing : undefined}
      />
    </WideModal>
  );
}

/* ── Approve/Review Modal ──────────────────────────────────────────────── */

function ApproveModal({
  submittal,
  onClose,
  onSubmit,
  isPending,
  vocabulary,
}: {
  submittal: Submittal;
  onClose: () => void;
  onSubmit: (data: ApproveSubmittalPayload) => void;
  isPending: boolean;
  /** Serves the default mark of each decision; `null` until it answers. */
  vocabulary: SubmittalVocabulary | null;
}) {
  const { t } = useTranslation();
  const [decision, setDecision] = useState<ApproveSubmittalPayload['status']>('approved');
  const [comments, setComments] = useState('');
  // The mark as the reviewer stamped it. Left empty, the server records the
  // default letter for the decision, which is what the placeholder shows.
  const [code, setCode] = useState('');
  const [resubmitForRecord, setResubmitForRecord] = useState(false);
  const defaultCode = vocabularyEntry(vocabulary?.outcomes, decision)?.short_code ?? '';
  const decisionHint = outcomeHint(t, decision);

  const handleSubmit = () => {
    onSubmit({
      status: decision,
      comments: comments.trim() || undefined,
      code: code.trim() || undefined,
      resubmit_for_record: decision === 'approved_as_noted' && resubmitForRecord ? true : undefined,
    });
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
            {/* What the chosen decision means for ordering, before it is recorded. */}
            {decisionHint && (
              <p className="mt-2 text-xs text-content-tertiary" data-testid="submittal-decision-hint">
                {decisionHint}
              </p>
            )}
          </div>

          {/* The mark on the stamp, and the corrected copy an approval as noted may still owe. */}
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label htmlFor="submittal-review-code" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('submittals.field_review_code', { defaultValue: 'Review code' })}
              </label>
              <input
                id="submittal-review-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                maxLength={20}
                placeholder={defaultCode}
                className={inputCls + ' w-24'}
              />
            </div>
            {decision === 'approved_as_noted' && (
              <label className="flex h-10 cursor-pointer items-center gap-2 text-sm text-content-primary">
                <input
                  id="submittal-resubmit-for-record"
                  type="checkbox"
                  checked={resubmitForRecord}
                  onChange={(e) => setResubmitForRecord(e.target.checked)}
                  className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                />
                <span>
                  {t('submittals.field_resubmit_for_record', {
                    defaultValue: 'Corrected copy to be resubmitted for record',
                  })}
                </span>
              </label>
            )}
          </div>
          <p className="-mt-2 text-xs text-content-tertiary">
            {t('submittals.review_code_hint', {
              defaultValue: 'The mark on the stamp. Leave empty to record the default letter for the decision.',
            })}
          </p>

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
  onOpenBoqPosition,
  vocabulary,
  showDiscipline,
  showApprovalBy,
}: {
  submittal: Submittal;
  projectId: string;
  onSubmit: (id: string) => void;
  onReview: (s: Submittal) => void;
  onEdit: (s: Submittal) => void;
  onOpenBoqPosition: (positionId: string) => void;
  vocabulary: SubmittalVocabulary | null;
  /** The two columns that only exist once some row of the list fills them. */
  showDiscipline: boolean;
  showApprovalBy: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  // Maker and model as one line under the title; absent on a row without them.
  const product = [submittal.manufacturer, submittal.model_reference].filter(Boolean).join(' / ');
  const statusCfg = STATUS_CONFIG[submittal.status] ?? STATUS_CONFIG.draft;
  const downloadPdf = useCallback(
    (locale: string) => downloadSubmittalPdf(submittal.id, locale, submittal.submittal_number),
    [submittal.id, submittal.submittal_number],
  );

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

        {/* Title, with the long-lead flag and the product under it when recorded.
            A row with neither renders the bare title span it always did. */}
        {submittal.long_lead || product ? (
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-content-primary truncate min-w-0">{submittal.title}</span>
              <LongLeadMark submittal={submittal} />
            </div>
            {product && (
              <p className="text-2xs text-content-tertiary truncate" title={product}>
                {product}
              </p>
            )}
          </div>
        ) : (
          <span className="text-sm text-content-primary truncate flex-1 min-w-0">
            {submittal.title}
          </span>
        )}

        {/* Discipline */}
        {showDiscipline && (
          <span className="w-10 shrink-0 hidden md:block">
            <DisciplineBadge discipline={submittal.discipline} vocabulary={vocabulary} />
          </span>
        )}

        {/* Spec Section */}
        <span className="text-xs text-content-tertiary w-20 shrink-0 hidden lg:block font-mono">
          {submittal.spec_section}
        </span>

        {/* Type badge */}
        <Badge variant="neutral" size="sm" className="hidden md:inline-flex">
          {t(`submittals.type_${submittal.type}`, { defaultValue: submittalTypeLabel(submittal.type) })}
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

        {/* The reviewer's code on the current revision; empty until there is one. */}
        <span className="w-9 shrink-0 flex justify-center">
          <ReviewCodeChip code={submittal.review_code} outcome={submittal.review_outcome} />
        </span>

        {/* Ball in Court + the review clock. A submittal with a review
            period shows the server's days in review and turns red once the
            server counts it past that period. One without keeps the chip the
            register always showed, which only appears while the submittal is
            with the reviewer and past the neutral threshold. */}
        <div className="w-24 shrink-0 hidden md:flex md:flex-col md:items-start md:gap-0.5">
          <span className="text-xs text-content-tertiary truncate w-full">
            {submittal.ball_in_court_name || submittal.ball_in_court || '-'}
          </span>
          <ReviewClock submittal={submittal} />
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

        {/* Approval needed by: required on site less the lead time. */}
        {showApprovalBy && (
          <div className="text-xs w-24 shrink-0 hidden lg:flex lg:flex-col lg:items-start lg:gap-0.5">
            <ApprovalNeededBy submittal={submittal} />
          </div>
        )}
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

          {/* What the reviewer stamped, the product and its dates, the
              revision chain and the checks. Each block is absent when it has
              nothing to say. */}
          <SubmittalRegisterDetail submittal={submittal} vocabulary={vocabulary} />

          {/* Linked BOQ items — each id is a live pill that deep-links to
              the BOQ position it covers, closing CONN-13. */}
          {submittal.linked_boq_item_ids.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-content-tertiary">
                {t('submittals.linked_boq_label', {
                  defaultValue: 'Linked BOQ positions:',
                })}
              </span>
              {submittal.linked_boq_item_ids.map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenBoqPosition(id);
                  }}
                  title={t('submittals.open_linked_boq_hint', {
                    defaultValue: 'Open this BOQ position',
                  })}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium text-oe-blue bg-oe-blue-subtle border border-oe-blue/30 hover:bg-oe-blue/10 transition-colors max-w-[140px]"
                >
                  <FileCheck size={11} className="shrink-0" />
                  <span className="truncate font-mono">{id.slice(0, 8)}</span>
                </button>
              ))}
            </div>
          )}

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
            {/* The printed form, for any status: a reviewer prints a draft
                as readily as an approved one. Open to every reader. */}
            <RecordPdfButton download={downloadPdf} testId={`submittal-pdf-${submittal.id}`} />
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Main Page ─────────────────────────────────────────────────────────── */

/** Compact inline link to a sibling module (keeps the connects row readable). */
function ModLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance orientation card: what a submittal is for, the stages of moving
 * one through approval, and the neighbouring modules it connects to. Every
 * linked module is a real, clickable route.
 */
function SubmittalsHowItWorks() {
  const { t } = useTranslation();

  const steps: { icon: React.ReactNode; title: string; desc: string }[] = [
    {
      icon: <FileCheck size={14} className="text-oe-blue" />,
      title: t('submittals.flow_1_title', { defaultValue: 'Log the item' }),
      desc: t('submittals.flow_1_desc', {
        defaultValue:
          'Register each shop drawing, product data sheet, sample or certificate against its spec section.',
      }),
    },
    {
      icon: <Send size={14} className="text-oe-blue" />,
      title: t('submittals.flow_2_title', { defaultValue: 'Submit for review' }),
      desc: t('submittals.flow_2_desc', {
        defaultValue: 'Move it from Draft to Submitted so the reviewer gets the ball, with a due date.',
      }),
    },
    {
      icon: <CheckCircle2 size={14} className="text-oe-blue" />,
      title: t('submittals.flow_3_title', { defaultValue: 'Reviewer decides' }),
      desc: t('submittals.flow_3_desc', {
        defaultValue: 'Approved, Approved as noted, or Revise and resubmit, each with comments.',
      }),
    },
    {
      icon: <Link2 size={14} className="text-oe-blue" />,
      title: t('submittals.flow_4_title', { defaultValue: 'Link to the works' }),
      desc: t('submittals.flow_4_desc', {
        defaultValue: 'Tie the approved submittal to the BOQ positions it covers before work starts.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="submittals.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('submittals.flow_title', { defaultValue: 'How submittals work and connect' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('submittals.flow_intro', {
          defaultValue:
            'A submittal proves the materials and shop drawings were approved before they reach site. Start by logging an item, then move it through review.',
        })}
      </p>

      <ol className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((s) => (
          <li
            key={s.title}
            className="rounded-lg border border-border-light bg-surface-primary/60 p-3"
          >
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
                {s.icon}
              </span>
              <span className="text-xs font-semibold text-content-primary">{s.title}</span>
            </div>
            <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
          </li>
        ))}
      </ol>

      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('submittals.flow_connects', { defaultValue: 'Connects with' })}
        </span>
        <ModLink to="/rfi">{t('rfi.title', { defaultValue: 'RFIs' })}</ModLink>
        <span aria-hidden="true">·</span>
        <ModLink to="/inspections">
          {t('submittals.link_inspections', { defaultValue: 'Inspections' })}
        </ModLink>
        <span aria-hidden="true">·</span>
        <ModLink to="/transmittals">
          {t('transmittals.title', { defaultValue: 'Transmittals' })}
        </ModLink>
        <span aria-hidden="true">·</span>
        <ModLink to="/qms">{t('submittals.link_qms', { defaultValue: 'Quality management' })}</ModLink>
      </div>
    </CollapsibleSection>
  );
}

export function SubmittalsPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Deep-link from the CDE container row: ?create=true&container_id=<id>
  // opens the create flow prefilled so the CDE -> Submittal document-control
  // hand-off is one click (CONN-14). The source container id is carried into
  // the create payload metadata so the link is recorded server-side.
  const autoCreate = searchParams.get('create') === 'true';
  const sourceContainerId = searchParams.get('container_id') || '';

  // State
  const [showCreateModal, setShowCreateModal] = useState(autoCreate);
  const [reviewingSubmittal, setReviewingSubmittal] = useState<Submittal | null>(null);
  const [editingSubmittal, setEditingSubmittal] = useState<Submittal | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  // The cut the register is showing (type tab, filters, summary shortcut) and
  // the order. Every part but `awaiting` travels to the server.
  const [filters, setFilters] = useState<RegisterFilters>(NO_FILTERS);
  const [sort, setSort] = useState<RegisterSort | null>(null);
  const statusFilter = filters.status;
  const filtersActive = hasActiveFilter(filters);
  const vocabulary = useSubmittalVocabulary();

  // Strip the deep-link params once consumed so a reload / back-button does
  // not re-open the create modal. Keeps the source container id in a ref so
  // the create handler can still read it after the URL is cleaned.
  const sourceContainerIdRef = useRef(sourceContainerId);
  const hasCleanedParams = useRef(false);
  useEffect(() => {
    if (hasCleanedParams.current) return;
    hasCleanedParams.current = true;
    if (autoCreate) {
      sourceContainerIdRef.current = sourceContainerId;
      const next = new URLSearchParams(searchParams);
      next.delete('create');
      next.delete('container_id');
      setSearchParams(next, { replace: true });
    }
  }, [autoCreate, sourceContainerId, searchParams, setSearchParams]);

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
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
    queryKey: ['submittals', projectId, toListFilters(projectId, filters, sort)],
    queryFn: () => fetchSubmittals(toListFilters(projectId, filters, sort)),
    enabled: !!projectId,
    refetchOnWindowFocus: true,
    // A filter or a sort click asks the server again. The rows on screen stay
    // until the answer arrives, so the table (and the heading just clicked)
    // is not swapped for a skeleton. Another project's rows are never kept.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === projectId ? previous : undefined,
  });

  // The counts above the register, for the whole project as of today. Keyed
  // under ['submittals'] so every save, submission and review refreshes them
  // with the list. `null` (no answer, or not a summary) falls back to the
  // four tiles counted from the rows on screen.
  const { data: summary = null } = useQuery({
    queryKey: ['submittals', 'summary', projectId],
    queryFn: () => fetchSubmittalSummary(projectId),
    enabled: !!projectId,
    refetchOnWindowFocus: true,
  });

  // "Empty" is about the project's register, not about the cut on screen: a
  // filter that matches nothing must not disable the export of the rest.
  const registerEmpty = summary
    ? summary.total === 0
    : !hasServerFilter(filters) && !isLoading && !isError && submittals.length === 0;

  // The one cut the list route has no parameter for (see registerView.ts).
  const cutRows = useMemo(() => applyClientCut(submittals, filters, sort), [submittals, filters, sort]);

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return cutRows;
    return cutRows.filter((s) =>
      matchesSearch(
        searchQuery,
        s.title,
        s.submittal_number,
        s.spec_section,
        s.ball_in_court_name,
        s.manufacturer,
        s.model_reference,
        s.supplier_name,
      ),
    );
  }, [cutRows, searchQuery]);

  // The discipline and approval-deadline columns appear once a row of the
  // list fills them, so a register that never used them keeps its old shape.
  const showDiscipline = useMemo(() => submittals.some((s) => !!s.discipline), [submittals]);
  const showApprovalBy = useMemo(
    () => submittals.some((s) => !!s.approval_needed_by || s.long_lead),
    [submittals],
  );

  const typeLabel = useCallback(
    (type: string) => t(`submittals.type_${type}`, { defaultValue: submittalTypeLabel(type) }),
    [t],
  );

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

  // Module Insights - KPIs and charts over the loaded submittals. When the
  // project has none the panel draws nothing rather than inventing rows to fill
  // it. Declared with the top-level hooks, above the single return, so the hook
  // order stays stable.
  const insights = useModuleInsights('submittals', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildSubmittalsInsights(submittals, '', t),
    [submittals, t],
  );

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['submittals'] });
  }, [qc]);

  // Resolve a submittal id to its human-facing number for error toasts, so a
  // failed submit/review/save names the specific row even after rapid actions.
  // Falls back to a short id slice when the row is no longer in the list.
  const submittalLabelById = useCallback(
    (id: string): string => {
      const row = submittals.find((s) => s.id === id);
      return row?.submittal_number || id.slice(0, 8);
    },
    [submittals],
  );

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
    // Surface the title the user was creating so a failed create is
    // traceable even after the toast is gone from the screen.
    onError: (e: Error, vars) =>
      addToast({
        type: 'error',
        title: t('submittals.create_failed', {
          defaultValue: 'Failed to create "{{title}}"',
          title: vars.title,
        }),
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
    // `vars` is the submittal id passed to mutate(); recover the row so the
    // failure names the specific submittal number, not a generic "Error".
    onError: (e: Error, id) =>
      addToast({
        type: 'error',
        title: t('submittals.submit_failed', {
          defaultValue: 'Failed to submit {{number}}',
          number: submittalLabelById(id),
        }),
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
    onError: (e: Error, vars) =>
      addToast({
        type: 'error',
        title: t('submittals.review_failed', {
          defaultValue: 'Failed to review {{number}}',
          number: submittalLabelById(vars.id),
        }),
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
    onError: (e: Error, vars) =>
      addToast({
        type: 'error',
        title: t('submittals.update_failed', {
          defaultValue: 'Failed to save {{number}}',
          number: submittalLabelById(vars.id),
        }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: SubmittalFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      // When the create flow was opened from a CDE container, record the
      // source container id so the document-control loop is traceable.
      const containerId = sourceContainerIdRef.current;
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        description: formData.description || undefined,
        spec_section: formData.spec_section || undefined,
        submittal_type: formData.type,
        date_required: formData.date_required || undefined,
        ...buildProcurementCreate(formData),
        ...(containerId && { metadata: { cde_container_id: containerId } }),
      });
      sourceContainerIdRef.current = '';
    },
    [createMut, projectId, addToast, t],
  );

  // Deep-link a linked-BOQ pill to the BOQ position it covers (CONN-13).
  const handleOpenBoqPosition = useCallback(
    (positionId: string) => {
      navigate(`/boq?positionId=${encodeURIComponent(positionId)}`);
    },
    [navigate],
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
      // Rebuild the baseline the modal started from, so the save carries only
      // what the user actually edited. See `buildSubmittalPatch`.
      const data = buildSubmittalPatch(formData, submittalFormData(editingSubmittal));

      updateMut.mutate({ id: editingSubmittal.id, data });
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
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <ModuleGuideButton content={submittalsGuide} />
            <SubmittalRegisterExport projectId={projectId} filters={filters} empty={registerEmpty} />
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
          </>
        }
      />

      {/* Module Insights panel - toggled by the header button, placed high so
          its charts show the moment the register opens. */}
      <InsightsPanel
        open={insights.open}
        title={t('submittals.insights.title', { defaultValue: 'Submittal insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
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
            label: t('rfi.title', { defaultValue: 'RFIs' }),
            onClick: () => navigate('/rfi'),
          },
          {
            label: t('cde.title', { defaultValue: 'Common Data Environment' }),
            onClick: () => navigate('/cde'),
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

      <SubmittalsHowItWorks />

      {!projectId && <RequiresProject>{null}</RequiresProject>}

      {/* The register header: the summary route's counts, each a shortcut
          into the rows behind it. Without a summary the four tiles counted
          from the list stand in. */}
      {summary ? (
        <SubmittalRegisterSummary
          summary={summary}
          vocabulary={vocabulary}
          filters={filters}
          onFilters={setFilters}
        />
      ) : (
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
      )}

      {/* One register, cut by type: the shop drawing register, the material
          approvals and the method statements are tabs, not pages. */}
      <SubmittalTypeTabs filters={filters} onFilters={setFilters} summary={summary} typeLabel={typeLabel} />

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-center gap-3">
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
            onChange={(e) =>
              setFilters((prev) => ({
                ...prev,
                status: e.target.value as SubmittalStatus | '',
                // A status and the awaiting-review cut answer the same question.
                awaiting: false,
              }))
            }
            aria-label={t('submittals.filter_all', { defaultValue: 'All Statuses' })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-48"
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
          <div className="pointer-events-none absolute inset-y-0 end-0 flex items-center pe-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>

        <SubmittalRegisterFilters
          filters={filters}
          onFilters={setFilters}
          vocabulary={vocabulary}
          summary={summary}
          typeLabel={typeLabel}
        />
      </div>

      {/* Table */}
      <div
        role="tabpanel"
        id={`submittals-type-panel-${filters.type || 'all'}`}
        aria-labelledby={`submittals-type-tab-${filters.type || 'all'}`}
      >
        {isLoading ? (
          <SkeletonTable rows={5} columns={6} />
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<FileCheck size={28} strokeWidth={1.5} />}
            title={
              searchQuery || filtersActive
                ? t('submittals.no_results', { defaultValue: 'No matching submittals' })
                : t('submittals.no_submittals', { defaultValue: 'No submittals yet' })
            }
            description={
              searchQuery || filtersActive
                ? t('submittals.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('submittals.no_submittals_hint', {
                    defaultValue: 'Create your first submittal to track document approvals',
                  })
            }
            action={
              !searchQuery && !filtersActive
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
                <SortableHeader
                  label="#"
                  field="submittal_number"
                  sortable={isServerSortable(vocabulary, 'submittal_number')}
                  sort={sort}
                  onSort={setSort}
                  className="w-20"
                />
                <SortableHeader
                  label={t('submittals.col_title', { defaultValue: 'Title' })}
                  field="title"
                  sortable={isServerSortable(vocabulary, 'title')}
                  sort={sort}
                  onSort={setSort}
                  className="flex-1"
                />
                {showDiscipline && (
                  <SortableHeader
                    label={t('submittals.col_discipline_short', { defaultValue: 'Disc.' })}
                    field="discipline"
                    sortable={isServerSortable(vocabulary, 'discipline')}
                    sort={sort}
                    onSort={setSort}
                    className="w-10 hidden md:block"
                  />
                )}
                <span className="w-20 hidden lg:block">
                  {t('submittals.col_spec', { defaultValue: 'Spec' })}
                </span>
                <span className="w-24 hidden md:block">
                  {t('submittals.col_type', { defaultValue: 'Type' })}
                </span>
                <SortableHeader
                  label={t('submittals.col_status', { defaultValue: 'Status' })}
                  field="status"
                  sortable={isServerSortable(vocabulary, 'status')}
                  sort={sort}
                  onSort={setSort}
                  className="w-28 text-center"
                />
                <span className="sr-only">
                  {t('submittals.col_pipeline_sr', { defaultValue: 'Pipeline' })}
                </span>
                <span
                  className="w-9 text-center"
                  title={t('submittals.col_review_code', { defaultValue: 'Review code' })}
                >
                  {t('submittals.col_review_code_short', { defaultValue: 'Code' })}
                </span>
                <span className="w-24 hidden md:block">
                  {t('submittals.col_bic', { defaultValue: 'Ball in Court' })}
                </span>
                <span className="w-10 text-center hidden sm:block">
                  {t('submittals.col_rev', { defaultValue: 'Rev' })}
                </span>
                <SortableHeader
                  label={t('submittals.col_date_required', { defaultValue: 'Required' })}
                  field="date_required"
                  sortable={isServerSortable(vocabulary, 'date_required')}
                  sort={sort}
                  onSort={setSort}
                  className="w-20 hidden lg:block"
                />
                {showApprovalBy && (
                  <SortableHeader
                    label={t('submittals.col_approval_needed_by', { defaultValue: 'Approval needed by' })}
                    field="required_on_site_date"
                    sortable={isServerSortable(vocabulary, 'required_on_site_date')}
                    sort={sort}
                    onSort={setSort}
                    className="w-24 hidden lg:block"
                  />
                )}
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
                  onOpenBoqPosition={handleOpenBoqPosition}
                  vocabulary={vocabulary}
                  showDiscipline={showDiscipline}
                  showApprovalBy={showApprovalBy}
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
          vocabulary={vocabulary}
        />
      )}

      {/* Review Modal */}
      {reviewingSubmittal && (
        <ApproveModal
          submittal={reviewingSubmittal}
          onClose={() => setReviewingSubmittal(null)}
          onSubmit={handleApproveSubmit}
          isPending={approveMut.isPending}
          vocabulary={vocabulary}
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
          vocabulary={vocabulary}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
