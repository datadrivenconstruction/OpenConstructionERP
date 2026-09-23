// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  Landmark,
  Plus,
  ChevronDown,
  ChevronRight,
  Trash2,
  Send,
  CheckCircle2,
  XCircle,
  Undo2,
  Clock,
  AlertTriangle,
  Radar,
  FileWarning,
  MessageSquarePlus,
  MessageSquareReply,
  Gavel,
  ScrollText,
  Scale,
  Pencil,
  Download,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  DateDisplay,
  DismissibleInfo,
  RecoveryCard,
  SkeletonTable,
  ConfirmDialog,
  WideModal,
  WideModalSection,
  WideModalField,
  ModuleGuideButton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildReviewAuthorityInsights } from './reviewAuthorityInsights';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { triggerDownload } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchCycles,
  fetchCycle,
  createCycle,
  updateCycle,
  deleteCycle,
  submitCycle,
  transitionCycle,
  fetchRemarks,
  addRemark,
  respondRemark,
  decideRemark,
  fetchStaleRemarks,
  fetchRepeatRadar,
  fetchDossier,
  AUTHORITY_KINDS,
  CYCLE_STATUSES,
  CYCLE_TRANSITIONS,
  CYCLE_TERMINAL_STATUSES,
  REMARK_SEVERITIES,
  REMARK_DECISIONS,
  type ReviewCycle,
  type Remark,
  type AuthorityKind,
  type CycleStatus,
  type RemarkSeverity,
  type RemarkDecision,
  type CreateCyclePayload,
  type UpdateCyclePayload,
  type RepeatRadarRow,
} from './api';
import { reviewAuthorityGuide } from './reviewAuthorityGuide';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const AUTHORITY_KIND_LABELS: Record<AuthorityKind, string> = {
  state_expertise: 'State expertise',
  building_control: 'Building control',
  ahj: 'Authority having jurisdiction',
  technical_review: 'Technical review board',
  other: 'Other',
};

const CYCLE_STATUS_LABELS: Record<CycleStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  under_review: 'Under review',
  remarks_issued: 'Remarks issued',
  responding: 'Responding',
  resubmitted: 'Resubmitted',
  approved: 'Approved',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
};

const cycleStatusVariant = (
  s: CycleStatus,
): 'blue' | 'warning' | 'success' | 'error' | 'neutral' => {
  switch (s) {
    case 'draft':
      return 'neutral';
    case 'submitted':
    case 'under_review':
    case 'resubmitted':
      return 'blue';
    case 'remarks_issued':
    case 'responding':
      return 'warning';
    case 'approved':
      return 'success';
    case 'rejected':
      return 'error';
    case 'withdrawn':
      return 'neutral';
    default:
      return 'neutral';
  }
};

const REMARK_SEVERITY_LABELS: Record<RemarkSeverity, string> = {
  blocking: 'Blocking',
  major: 'Major',
  minor: 'Minor',
  info: 'Info',
};

const severityVariant = (s: RemarkSeverity): 'error' | 'warning' | 'blue' | 'neutral' => {
  switch (s) {
    case 'blocking':
      return 'error';
    case 'major':
      return 'warning';
    case 'minor':
      return 'blue';
    default:
      return 'neutral';
  }
};

const REMARK_STATUS_LABELS: Record<string, string> = {
  open: 'Open',
  responded: 'Responded',
  accepted: 'Accepted',
  contested: 'Contested',
  withdrawn: 'Withdrawn',
};

const remarkStatusVariant = (s: string): 'blue' | 'warning' | 'success' | 'error' | 'neutral' => {
  switch (s) {
    case 'open':
      return 'warning';
    case 'responded':
      return 'blue';
    case 'accepted':
      return 'success';
    case 'contested':
      return 'error';
    case 'withdrawn':
      return 'neutral';
    default:
      return 'neutral';
  }
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Create Cycle Modal ────────────────────────────────────────────────── */

interface CycleFormData {
  authority_name: string;
  authority_kind: AuthorityKind;
  submission_ref: string;
  current_document_version: string;
  sla_days: number;
  jurisdiction: string;
  notes: string;
}

const EMPTY_CYCLE_FORM: CycleFormData = {
  authority_name: '',
  authority_kind: 'other',
  submission_ref: '',
  current_document_version: '',
  sla_days: 42,
  jurisdiction: '',
  notes: '',
};

function CreateCycleModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: CycleFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<CycleFormData>(EMPTY_CYCLE_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof CycleFormData>(key: K, value: CycleFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const nameError = touched && form.authority_name.trim().length === 0;
  const canSubmit = form.authority_name.trim().length > 0;

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
      title={t('review_authority.new_cycle', { defaultValue: 'New Review Cycle' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('review_authority.create_cycle', { defaultValue: 'Open Cycle' })}</span>
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('review_authority.section_authority', { defaultValue: 'Authority' })}
        columns={2}
      >
        <WideModalField
          label={t('review_authority.field_authority_name', { defaultValue: 'Authority name' })}
          required
          span={2}
          htmlFor="ra-authority-name"
          error={
            nameError
              ? t('review_authority.authority_name_required', {
                  defaultValue: 'Authority name is required',
                })
              : undefined
          }
        >
          <input
            id="ra-authority-name"
            value={form.authority_name}
            onChange={(e) => {
              set('authority_name', e.target.value);
              setTouched(true);
            }}
            placeholder={t('review_authority.authority_name_placeholder', {
              defaultValue: 'e.g. Regional Building Control Office',
            })}
            className={clsx(
              inputCls,
              nameError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_authority_kind', { defaultValue: 'Authority kind' })}
          htmlFor="ra-authority-kind"
        >
          <select
            id="ra-authority-kind"
            value={form.authority_kind}
            onChange={(e) => set('authority_kind', e.target.value as AuthorityKind)}
            className={inputCls}
          >
            {AUTHORITY_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`review_authority.authority_kind_${k}`, {
                  defaultValue: AUTHORITY_KIND_LABELS[k],
                })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_jurisdiction', { defaultValue: 'Jurisdiction' })}
          htmlFor="ra-jurisdiction"
          hint={t('review_authority.hint_jurisdiction', {
            defaultValue: 'Optional - free text, e.g. a region or code area.',
          })}
        >
          <input
            id="ra-jurisdiction"
            value={form.jurisdiction}
            onChange={(e) => set('jurisdiction', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('review_authority.section_submission', { defaultValue: 'Submission' })}
        columns={2}
      >
        <WideModalField
          label={t('review_authority.field_submission_ref', { defaultValue: 'Submission reference' })}
          htmlFor="ra-submission-ref"
        >
          <input
            id="ra-submission-ref"
            value={form.submission_ref}
            onChange={(e) => set('submission_ref', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_document_version', {
            defaultValue: 'Current document version',
          })}
          htmlFor="ra-doc-version"
          hint={t('review_authority.hint_document_version', {
            defaultValue: 'The live version; Submit freezes this as the pinned version reviewed.',
          })}
        >
          <input
            id="ra-doc-version"
            value={form.current_document_version}
            onChange={(e) => set('current_document_version', e.target.value)}
            placeholder="v1.0"
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_sla_days', { defaultValue: 'SLA (days)' })}
          htmlFor="ra-sla-days"
        >
          <input
            id="ra-sla-days"
            type="number"
            min={1}
            max={3650}
            value={form.sla_days}
            onChange={(e) => set('sla_days', Number(e.target.value) || 1)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_notes', { defaultValue: 'Notes' })}
          span={2}
          htmlFor="ra-notes"
        >
          <textarea
            id="ra-notes"
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            rows={3}
            className={textareaCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Edit Cycle Modal ──────────────────────────────────────────────────── */

function EditCycleModal({
  cycle,
  onClose,
  onSubmit,
  isPending,
}: {
  cycle: ReviewCycle;
  onClose: () => void;
  onSubmit: (data: CycleFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<CycleFormData>({
    authority_name: cycle.authority_name,
    authority_kind: cycle.authority_kind,
    submission_ref: cycle.submission_ref ?? '',
    current_document_version: cycle.current_document_version,
    sla_days: cycle.sla_days,
    jurisdiction: cycle.jurisdiction ?? '',
    notes: cycle.notes,
  });
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof CycleFormData>(key: K, value: CycleFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const nameError = touched && form.authority_name.trim().length === 0;
  const canSubmit = form.authority_name.trim().length > 0;

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
      title={t('review_authority.edit_cycle', { defaultValue: 'Edit Review Cycle' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Pencil size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('common.save', { defaultValue: 'Save' })}</span>
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('review_authority.section_authority', { defaultValue: 'Authority' })}
        columns={2}
      >
        <WideModalField
          label={t('review_authority.field_authority_name', { defaultValue: 'Authority name' })}
          required
          span={2}
          htmlFor="ra-edit-authority-name"
          error={
            nameError
              ? t('review_authority.authority_name_required', {
                  defaultValue: 'Authority name is required',
                })
              : undefined
          }
        >
          <input
            id="ra-edit-authority-name"
            value={form.authority_name}
            onChange={(e) => {
              set('authority_name', e.target.value);
              setTouched(true);
            }}
            className={clsx(
              inputCls,
              nameError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_authority_kind', { defaultValue: 'Authority kind' })}
          htmlFor="ra-edit-authority-kind"
        >
          <select
            id="ra-edit-authority-kind"
            value={form.authority_kind}
            onChange={(e) => set('authority_kind', e.target.value as AuthorityKind)}
            className={inputCls}
          >
            {AUTHORITY_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`review_authority.authority_kind_${k}`, {
                  defaultValue: AUTHORITY_KIND_LABELS[k],
                })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_jurisdiction', { defaultValue: 'Jurisdiction' })}
          htmlFor="ra-edit-jurisdiction"
          hint={t('review_authority.hint_jurisdiction', {
            defaultValue: 'Optional - free text, e.g. a region or code area.',
          })}
        >
          <input
            id="ra-edit-jurisdiction"
            value={form.jurisdiction}
            onChange={(e) => set('jurisdiction', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('review_authority.section_submission', { defaultValue: 'Submission' })}
        columns={2}
      >
        <WideModalField
          label={t('review_authority.field_submission_ref', { defaultValue: 'Submission reference' })}
          htmlFor="ra-edit-submission-ref"
        >
          <input
            id="ra-edit-submission-ref"
            value={form.submission_ref}
            onChange={(e) => set('submission_ref', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_document_version', {
            defaultValue: 'Current document version',
          })}
          htmlFor="ra-edit-doc-version"
          hint={t('review_authority.hint_document_version_edit', {
            defaultValue:
              'Advancing this past the pinned version is what surfaces stale remarks on this cycle.',
          })}
        >
          <input
            id="ra-edit-doc-version"
            value={form.current_document_version}
            onChange={(e) => set('current_document_version', e.target.value)}
            placeholder="v1.0"
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_sla_days', { defaultValue: 'SLA (days)' })}
          htmlFor="ra-edit-sla-days"
        >
          <input
            id="ra-edit-sla-days"
            type="number"
            min={1}
            max={3650}
            value={form.sla_days}
            onChange={(e) => set('sla_days', Number(e.target.value) || 1)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_notes', { defaultValue: 'Notes' })}
          span={2}
          htmlFor="ra-edit-notes"
        >
          <textarea
            id="ra-edit-notes"
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            rows={3}
            className={textareaCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Add Remark Modal ──────────────────────────────────────────────────── */

interface RemarkFormData {
  text: string;
  section: string;
  norm_reference: string;
  severity: RemarkSeverity;
}

function AddRemarkModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: RemarkFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<RemarkFormData>({
    text: '',
    section: '',
    norm_reference: '',
    severity: 'major',
  });
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof RemarkFormData>(key: K, value: RemarkFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const textError = touched && form.text.trim().length === 0;
  const canSubmit = form.text.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="md"
      title={t('review_authority.new_remark', { defaultValue: 'Add Remark' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <MessageSquarePlus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('review_authority.add_remark', { defaultValue: 'Add Remark' })}</span>
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('review_authority.field_remark_text', { defaultValue: 'Remark' })}
          required
          span={2}
          htmlFor="ra-remark-text"
          error={
            textError
              ? t('review_authority.remark_text_required', {
                  defaultValue: 'Remark text is required',
                })
              : undefined
          }
        >
          <textarea
            id="ra-remark-text"
            value={form.text}
            onChange={(e) => {
              set('text', e.target.value);
              setTouched(true);
            }}
            rows={3}
            className={clsx(
              textareaCls,
              textError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_section', { defaultValue: 'Section' })}
          htmlFor="ra-remark-section"
        >
          <input
            id="ra-remark-section"
            value={form.section}
            onChange={(e) => set('section', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_severity', { defaultValue: 'Severity' })}
          htmlFor="ra-remark-severity"
        >
          <select
            id="ra-remark-severity"
            value={form.severity}
            onChange={(e) => set('severity', e.target.value as RemarkSeverity)}
            className={inputCls}
          >
            {REMARK_SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {t(`review_authority.severity_${s}`, { defaultValue: REMARK_SEVERITY_LABELS[s] })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('review_authority.field_norm_reference', { defaultValue: 'Norm reference' })}
          span={2}
          htmlFor="ra-remark-norm"
          hint={t('review_authority.hint_norm_reference', {
            defaultValue:
              'Optional - the code clause the remark cites. Leave blank if the authority did not cite one; the remark is then flagged for a human to confirm whether it is contestable.',
          })}
        >
          <input
            id="ra-remark-norm"
            value={form.norm_reference}
            onChange={(e) => set('norm_reference', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Remark Row ────────────────────────────────────────────────────────── */

function RemarkRow({
  remark,
  onRespond,
  onDecide,
  isResponding,
  isDeciding,
}: {
  remark: Remark;
  onRespond: (remarkId: string, text: string) => void;
  onDecide: (remarkId: string, decision: RemarkDecision) => void;
  isResponding: boolean;
  isDeciding: boolean;
}) {
  const { t } = useTranslation();
  const [responseText, setResponseText] = useState('');
  const [showRespond, setShowRespond] = useState(false);

  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-3 space-y-2">
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-mono font-semibold text-content-secondary">
            #{remark.ordinal}
          </span>
          <Badge variant={severityVariant(remark.severity)} size="sm">
            {t(`review_authority.severity_${remark.severity}`, {
              defaultValue: REMARK_SEVERITY_LABELS[remark.severity],
            })}
          </Badge>
          <Badge variant={remarkStatusVariant(remark.status)} size="sm">
            {t(`review_authority.remark_status_${remark.status}`, {
              defaultValue: REMARK_STATUS_LABELS[remark.status] ?? remark.status,
            })}
          </Badge>
          {remark.classification === 'no_norm_ref_contestable' && (
            <span
              title={t('review_authority.no_norm_ref_title', {
                defaultValue: 'No norm cited - a human must confirm contestability.',
              })}
            >
            <Badge variant="warning" size="sm">
              <Gavel size={11} className="mr-1" />
              {t('review_authority.no_norm_ref', { defaultValue: 'No norm cited' })}
            </Badge>
            </span>
          )}
          {remark.is_stale && (
            <Badge variant="error" size="sm">
              <FileWarning size={11} className="mr-1" />
              {t('review_authority.stale', { defaultValue: 'Stale' })}
            </Badge>
          )}
          {remark.repeat_of_id && (
            <Badge variant="neutral" size="sm">
              <Radar size={11} className="mr-1" />
              {t('review_authority.repeat', { defaultValue: 'Repeat' })}
            </Badge>
          )}
        </div>
        {remark.section && (
          <span className="text-2xs text-content-tertiary shrink-0">{remark.section}</span>
        )}
      </div>

      <p className="text-sm text-content-primary whitespace-pre-wrap">{remark.text}</p>
      {remark.norm_reference && (
        <p className="text-xs text-content-tertiary">
          <ScrollText size={11} className="inline mr-1 -mt-0.5" />
          {remark.norm_reference}
        </p>
      )}

      {remark.response_text && (
        <div className="rounded-lg bg-surface-secondary p-2.5 mt-1">
          <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-1 font-medium">
            {t('review_authority.response', { defaultValue: 'Response' })}
          </p>
          <p className="text-sm text-content-primary whitespace-pre-wrap">{remark.response_text}</p>
        </div>
      )}

      {remark.status === 'open' && (
        <div className="pt-1">
          {showRespond ? (
            <div className="space-y-2">
              <textarea
                value={responseText}
                onChange={(e) => setResponseText(e.target.value)}
                rows={2}
                placeholder={t('review_authority.response_placeholder', {
                  defaultValue: 'Write the response to this remark...',
                })}
                className={textareaCls}
              />
              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  disabled={isResponding || responseText.trim().length === 0}
                  onClick={() => {
                    onRespond(remark.id, responseText.trim());
                    setResponseText('');
                    setShowRespond(false);
                  }}
                  icon={<MessageSquareReply size={13} />}
                >
                  {t('review_authority.submit_response', { defaultValue: 'Submit response' })}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setShowRespond(false)}>
                  {t('common.cancel', { defaultValue: 'Cancel' })}
                </Button>
              </div>
            </div>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              icon={<MessageSquareReply size={13} />}
              onClick={() => setShowRespond(true)}
            >
              {t('review_authority.respond', { defaultValue: 'Respond' })}
            </Button>
          )}
        </div>
      )}

      {remark.status === 'responded' && (
        <div className="flex items-center gap-2 pt-1 flex-wrap">
          {REMARK_DECISIONS.map((d) => (
            <Button
              key={d}
              variant="secondary"
              size="sm"
              disabled={isDeciding}
              onClick={() => onDecide(remark.id, d)}
              icon={
                d === 'accepted' ? (
                  <CheckCircle2 size={13} />
                ) : d === 'contested' ? (
                  <Scale size={13} />
                ) : (
                  <Undo2 size={13} />
                )
              }
            >
              {t(`review_authority.decide_${d}`, {
                defaultValue: d === 'accepted' ? 'Accept' : d === 'contested' ? 'Contest' : 'Withdraw',
              })}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Cycle Detail Panel ────────────────────────────────────────────────── */

function CycleDetailPanel({ cycleId }: { cycleId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [showAddRemark, setShowAddRemark] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showStale, setShowStale] = useState(false);
  const [showRadar, setShowRadar] = useState(false);
  const [isExportingDossier, setIsExportingDossier] = useState(false);

  const cycleQuery = useQuery({
    queryKey: ['review-authority-cycle', cycleId],
    queryFn: () => fetchCycle(cycleId),
  });

  const remarksQuery = useQuery({
    queryKey: ['review-authority-remarks', cycleId],
    queryFn: () => fetchRemarks(cycleId),
  });

  const staleQuery = useQuery({
    queryKey: ['review-authority-stale', cycleId],
    queryFn: () => fetchStaleRemarks(cycleId),
    enabled: showStale,
  });

  const radarQuery = useQuery({
    queryKey: ['review-authority-radar', cycleId],
    queryFn: () => fetchRepeatRadar(cycleId),
    enabled: showRadar,
  });

  const invalidateCycle = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['review-authority-cycle', cycleId] });
    qc.invalidateQueries({ queryKey: ['review-authority-cycles'] });
  }, [qc, cycleId]);

  const invalidateRemarks = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['review-authority-remarks', cycleId] });
    qc.invalidateQueries({ queryKey: ['review-authority-stale', cycleId] });
    qc.invalidateQueries({ queryKey: ['review-authority-radar', cycleId] });
  }, [qc, cycleId]);

  const onError = useCallback(
    (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
    [addToast, t],
  );

  const submitMut = useMutation({
    mutationFn: () => submitCycle(cycleId, {}),
    onSuccess: () => {
      invalidateCycle();
      addToast({
        type: 'success',
        title: t('review_authority.submitted', { defaultValue: 'Cycle submitted' }),
      });
    },
    onError,
  });

  const transitionMut = useMutation({
    mutationFn: (target: CycleStatus) => transitionCycle(cycleId, target),
    onSuccess: () => {
      invalidateCycle();
      addToast({
        type: 'success',
        title: t('review_authority.transitioned', { defaultValue: 'Cycle updated' }),
      });
    },
    onError,
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteCycle(cycleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-authority-cycles'] });
      addToast({
        type: 'success',
        title: t('review_authority.cycle_deleted', { defaultValue: 'Cycle deleted' }),
      });
    },
    onError,
  });

  const updateMut = useMutation({
    mutationFn: (data: UpdateCyclePayload) => updateCycle(cycleId, data),
    onSuccess: () => {
      invalidateCycle();
      invalidateRemarks();
      setShowEdit(false);
      addToast({
        type: 'success',
        title: t('review_authority.cycle_updated', { defaultValue: 'Cycle updated' }),
      });
    },
    onError,
  });

  const addRemarkMut = useMutation({
    mutationFn: (data: RemarkFormData) =>
      addRemark(cycleId, {
        text: data.text,
        section: data.section || undefined,
        norm_reference: data.norm_reference || undefined,
        severity: data.severity,
      }),
    onSuccess: () => {
      invalidateRemarks();
      setShowAddRemark(false);
      addToast({
        type: 'success',
        title: t('review_authority.remark_added', { defaultValue: 'Remark added' }),
      });
    },
    onError,
  });

  const respondMut = useMutation({
    mutationFn: ({ remarkId, text }: { remarkId: string; text: string }) =>
      respondRemark(remarkId, text),
    onSuccess: () => {
      invalidateRemarks();
      addToast({
        type: 'success',
        title: t('review_authority.responded', { defaultValue: 'Response recorded' }),
      });
    },
    onError,
  });

  const decideMut = useMutation({
    mutationFn: ({ remarkId, decision }: { remarkId: string; decision: RemarkDecision }) =>
      decideRemark(remarkId, decision),
    onSuccess: () => {
      invalidateRemarks();
      addToast({
        type: 'success',
        title: t('review_authority.decided', { defaultValue: 'Decision recorded' }),
      });
    },
    onError,
  });

  const handleDelete = useCallback(async () => {
    const cycle = cycleQuery.data;
    if (!cycle) return;
    const ok = await confirm({
      title: t('review_authority.confirm_delete_title', { defaultValue: 'Delete review cycle?' }),
      message: t('review_authority.confirm_delete_msg', {
        defaultValue: 'This permanently removes the cycle with "{{authority}}" and all its remarks.',
        authority: cycle.authority_name,
      }),
      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (ok) deleteMut.mutate();
  }, [cycleQuery.data, confirm, t, deleteMut]);

  const handleEditSubmit = useCallback(
    (data: CycleFormData) => {
      updateMut.mutate({
        authority_name: data.authority_name,
        authority_kind: data.authority_kind,
        submission_ref: data.submission_ref || undefined,
        current_document_version: data.current_document_version,
        sla_days: data.sla_days,
        jurisdiction: data.jurisdiction || undefined,
        notes: data.notes,
      });
    },
    [updateMut],
  );

  const handleExportDossier = useCallback(async () => {
    const cycle = cycleQuery.data;
    if (!cycle) return;
    setIsExportingDossier(true);
    try {
      const dossier = await fetchDossier(cycleId);
      const blob = new Blob([JSON.stringify(dossier, null, 2)], { type: 'application/json' });
      const ref = (cycle.submission_ref || cycle.id).replace(/[^\w.-]+/g, '_');
      triggerDownload(blob, `review-dossier-${ref}.json`);
      addToast({
        type: 'success',
        title: t('review_authority.dossier_exported', { defaultValue: 'Dossier exported' }),
      });
    } catch (e) {
      onError(e as Error);
    } finally {
      setIsExportingDossier(false);
    }
  }, [cycleQuery.data, cycleId, addToast, t, onError]);

  if (cycleQuery.isLoading) {
    return <SkeletonTable rows={4} columns={1} />;
  }
  if (cycleQuery.isError || !cycleQuery.data) {
    return <RecoveryCard error={cycleQuery.error} onRetry={() => cycleQuery.refetch()} />;
  }

  const cycle = cycleQuery.data;
  const remarks = remarksQuery.data ?? [];
  const nextStatuses = CYCLE_TRANSITIONS[cycle.status] ?? [];
  const isTerminal = (CYCLE_TERMINAL_STATUSES as readonly string[]).includes(cycle.status);

  return (
    <div className="space-y-4">
      {/* Cycle header */}
      <Card className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Landmark size={16} className="text-oe-blue shrink-0" />
              <h2 className="text-sm font-semibold text-content-primary truncate">
                {cycle.authority_name}
              </h2>
              <Badge variant={cycleStatusVariant(cycle.status)} size="sm">
                {t(`review_authority.cycle_status_${cycle.status}`, {
                  defaultValue: CYCLE_STATUS_LABELS[cycle.status],
                })}
              </Badge>
              {cycle.overdue && (
                <Badge variant="error" size="sm">
                  <AlertTriangle size={11} className="mr-1" />
                  {t('review_authority.overdue', { defaultValue: 'Overdue' })}
                </Badge>
              )}
            </div>
            <p className="mt-1 text-xs text-content-tertiary">
              {t(`review_authority.authority_kind_${cycle.authority_kind}`, {
                defaultValue: AUTHORITY_KIND_LABELS[cycle.authority_kind],
              })}
              {cycle.jurisdiction ? ` · ${cycle.jurisdiction}` : ''}
              {cycle.submission_ref ? ` · ${cycle.submission_ref}` : ''}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={13} />}
              disabled={isExportingDossier}
              onClick={handleExportDossier}
            >
              {isExportingDossier
                ? t('common.exporting', { defaultValue: 'Exporting…' })
                : t('review_authority.export_dossier', { defaultValue: 'Export dossier' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Pencil size={13} />}
              onClick={() => setShowEdit(true)}
            >
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              className="text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30"
              icon={<Trash2 size={13} />}
              onClick={handleDelete}
            >
              {t('common.delete', { defaultValue: 'Delete' })}
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4 text-xs text-content-tertiary">
          <span>
            {t('review_authority.opened', { defaultValue: 'Opened' })}:{' '}
            <DateDisplay value={cycle.opened_at} className="text-xs" />
          </span>
          <span>
            {t('review_authority.due', { defaultValue: 'Due' })}:{' '}
            <DateDisplay value={cycle.due_at} className="text-xs" />
          </span>
          {cycle.days_remaining !== null && (
            <span className={cycle.overdue ? 'text-semantic-error font-medium' : ''}>
              <Clock size={11} className="inline mr-1 -mt-0.5" />
              {cycle.days_remaining >= 0
                ? t('review_authority.days_remaining', {
                    defaultValue: '{{count}} days remaining',
                    count: cycle.days_remaining,
                  })
                : t('review_authority.days_overdue', {
                    defaultValue: '{{count}} days overdue',
                    count: Math.abs(cycle.days_remaining),
                  })}
            </span>
          )}
          <span>
            {t('review_authority.pinned_version', { defaultValue: 'Pinned version' })}:{' '}
            <span className="font-mono">{cycle.pinned_document_version || '—'}</span>
          </span>
          <span>
            {t('review_authority.current_version', { defaultValue: 'Current version' })}:{' '}
            <span className="font-mono">{cycle.current_document_version || '—'}</span>
          </span>
        </div>

        {cycle.notes && (
          <p className="text-sm text-content-secondary whitespace-pre-wrap border-t border-border-light pt-2">
            {cycle.notes}
          </p>
        )}

        {/* FSM actions */}
        <div className="flex flex-wrap items-center gap-2 border-t border-border-light pt-3">
          {cycle.status === 'draft' && (
            <Button
              variant="primary"
              size="sm"
              disabled={submitMut.isPending}
              onClick={() => submitMut.mutate()}
              icon={<Send size={13} />}
            >
              {t('review_authority.submit_cycle', { defaultValue: 'Submit' })}
            </Button>
          )}
          {nextStatuses
            .filter((s) => s !== 'withdrawn')
            .map((s) => (
              <Button
                key={s}
                variant="secondary"
                size="sm"
                disabled={transitionMut.isPending}
                onClick={() => transitionMut.mutate(s)}
                icon={
                  s === 'approved' ? (
                    <CheckCircle2 size={13} />
                  ) : s === 'rejected' ? (
                    <XCircle size={13} />
                  ) : (
                    <ChevronRight size={13} />
                  )
                }
              >
                {/* One key with the status interpolated, not nine keys with the status
                    welded into the key name. A language that inflects the status after
                    this preposition cannot reach it once the sentence arrives assembled,
                    and nine keys would freeze that shape in all 29 locales at once. The
                    status word is itself translated, through the same cycle_status_ keys
                    the badge above uses, so the two never disagree. */}
                {t('review_authority.move_to', {
                  defaultValue: 'Move to {{status}}',
                  status: t(`review_authority.cycle_status_${s}`, {
                    defaultValue: CYCLE_STATUS_LABELS[s],
                  }),
                })}
              </Button>
            ))}
          {nextStatuses.includes('withdrawn') && (
            <Button
              variant="ghost"
              size="sm"
              disabled={transitionMut.isPending}
              onClick={() => transitionMut.mutate('withdrawn')}
              icon={<Undo2 size={13} />}
              className="text-content-tertiary"
            >
              {t('review_authority.withdraw_cycle', { defaultValue: 'Withdraw' })}
            </Button>
          )}
          {isTerminal && (
            <span className="text-xs text-content-tertiary">
              {t('review_authority.cycle_terminal', { defaultValue: 'This cycle is closed.' })}
            </span>
          )}
        </div>
      </Card>

      {/* Insight badges: stale + repeat radar */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Card
          className="p-3 cursor-pointer hover:border-border-medium transition-colors"
          onClick={() => setShowStale((v) => !v)}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-sm font-medium text-content-primary">
              <FileWarning size={14} className="text-semantic-error" />
              {t('review_authority.stale_remarks_title', { defaultValue: 'Stale remarks' })}
            </span>
            <ChevronDown
              size={14}
              className={clsx('text-content-tertiary transition-transform', showStale && 'rotate-180')}
            />
          </div>
          <p className="mt-1 text-2xs text-content-tertiary">
            {t('review_authority.stale_remarks_desc', {
              defaultValue: 'Remarks raised against a document version the project has moved past.',
            })}
          </p>
          {showStale && (
            <div className="mt-2 space-y-1.5" onClick={(e) => e.stopPropagation()}>
              {staleQuery.isLoading ? (
                <p className="text-xs text-content-tertiary">
                  {t('common.loading', { defaultValue: 'Loading…' })}
                </p>
              ) : (staleQuery.data ?? []).length === 0 ? (
                <p className="text-xs text-content-quaternary">
                  {t('review_authority.no_stale_remarks', {
                    defaultValue: 'No stale remarks on this cycle.',
                  })}
                </p>
              ) : (
                (staleQuery.data ?? []).map((r) => (
                  <div key={r.id} className="text-xs text-content-secondary">
                    #{r.ordinal} - {r.text.slice(0, 80)}
                    {r.text.length > 80 ? '…' : ''}
                  </div>
                ))
              )}
            </div>
          )}
        </Card>

        <Card
          className="p-3 cursor-pointer hover:border-border-medium transition-colors"
          onClick={() => setShowRadar((v) => !v)}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-sm font-medium text-content-primary">
              <Radar size={14} className="text-oe-blue" />
              {t('review_authority.repeat_radar_title', { defaultValue: 'Repeat radar' })}
            </span>
            <ChevronDown
              size={14}
              className={clsx('text-content-tertiary transition-transform', showRadar && 'rotate-180')}
            />
          </div>
          <p className="mt-1 text-2xs text-content-tertiary">
            {t('review_authority.repeat_radar_desc', {
              defaultValue: 'Remarks that closely match one already accepted on this cycle.',
            })}
          </p>
          {showRadar && (
            <div className="mt-2 space-y-1.5" onClick={(e) => e.stopPropagation()}>
              {radarQuery.isLoading ? (
                <p className="text-xs text-content-tertiary">
                  {t('common.loading', { defaultValue: 'Loading…' })}
                </p>
              ) : (radarQuery.data ?? []).length === 0 ? (
                <p className="text-xs text-content-quaternary">
                  {t('review_authority.no_repeats', {
                    defaultValue: 'No repeat remarks detected.',
                  })}
                </p>
              ) : (
                (radarQuery.data as RepeatRadarRow[]).map((row) => (
                  <div key={row.remark_id} className="text-xs text-content-secondary">
                    #{row.ordinal}{' '}
                    {t('review_authority.repeat_of', {
                      defaultValue: 'echoes #{{prior}}',
                      prior: row.repeat_of_ordinal ?? '?',
                    })}
                    {row.similarity !== null && ` (${Math.round(row.similarity * 100)}%)`}
                  </div>
                ))
              )}
            </div>
          )}
        </Card>
      </div>

      {/* Remarks */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('review_authority.remarks_title', { defaultValue: 'Remarks' })}{' '}
            <span className="text-content-tertiary font-normal">({remarks.length})</span>
          </h3>
          <Button
            variant="secondary"
            size="sm"
            icon={<MessageSquarePlus size={13} />}
            onClick={() => setShowAddRemark(true)}
          >
            {t('review_authority.add_remark', { defaultValue: 'Add Remark' })}
          </Button>
        </div>

        {remarksQuery.isLoading ? (
          <SkeletonTable rows={3} columns={1} />
        ) : remarks.length === 0 ? (
          <EmptyState
            icon={<MessageSquarePlus size={24} strokeWidth={1.5} />}
            title={t('review_authority.no_remarks', { defaultValue: 'No remarks yet' })}
            description={t('review_authority.no_remarks_hint', {
              defaultValue: 'Log the remarks the authority raises against this submission.',
            })}
          />
        ) : (
          <div className="space-y-2">
            {remarks.map((r) => (
              <RemarkRow
                key={r.id}
                remark={r}
                isResponding={respondMut.isPending}
                isDeciding={decideMut.isPending}
                onRespond={(remarkId, text) => respondMut.mutate({ remarkId, text })}
                onDecide={(remarkId, decision) => decideMut.mutate({ remarkId, decision })}
              />
            ))}
          </div>
        )}
      </div>

      {showAddRemark && (
        <AddRemarkModal
          onClose={() => setShowAddRemark(false)}
          isPending={addRemarkMut.isPending}
          onSubmit={(data) => addRemarkMut.mutate(data)}
        />
      )}

      {showEdit && (
        <EditCycleModal
          cycle={cycle}
          onClose={() => setShowEdit(false)}
          isPending={updateMut.isPending}
          onSubmit={handleEditSubmit}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Cycle List Row ────────────────────────────────────────────────────── */

function CycleListRow({
  cycle,
  selected,
  onSelect,
}: {
  cycle: ReviewCycle;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onSelect}
      className={clsx(
        'w-full text-left rounded-lg border px-3 py-2.5 transition-colors',
        selected
          ? 'border-oe-blue bg-oe-blue/5 ring-1 ring-oe-blue/20'
          : 'border-border-light bg-surface-primary hover:border-border-medium',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-content-primary truncate">
          {cycle.authority_name}
        </span>
        <Badge variant={cycleStatusVariant(cycle.status)} size="sm">
          {t(`review_authority.cycle_status_${cycle.status}`, {
            defaultValue: CYCLE_STATUS_LABELS[cycle.status],
          })}
        </Badge>
      </div>
      <div className="mt-1 flex items-center gap-2 text-2xs text-content-tertiary">
        <span>
          {t(`review_authority.authority_kind_${cycle.authority_kind}`, {
            defaultValue: AUTHORITY_KIND_LABELS[cycle.authority_kind],
          })}
        </span>
        {cycle.overdue && (
          <span className="inline-flex items-center gap-0.5 text-semantic-error font-medium">
            <AlertTriangle size={10} />
            {t('review_authority.overdue', { defaultValue: 'Overdue' })}
          </span>
        )}
      </div>
    </button>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function ReviewAuthorityPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const qc = useQueryClient();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [statusFilter, setStatusFilter] = useState<CycleStatus | ''>('');
  const [authorityFilter, setAuthorityFilter] = useState<AuthorityKind | ''>('');
  const [selectedCycleId, setSelectedCycleId] = useState<string | null>(null);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const selectedProjectId = routeProjectId || activeProjectId || '';
  const projectName = projects.find((p) => p.id === selectedProjectId)?.name || '';

  const {
    data: cycles = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['review-authority-cycles', projectId, statusFilter, authorityFilter],
    queryFn: () =>
      fetchCycles({ project_id: projectId, status: statusFilter, authority_kind: authorityFilter }),
    enabled: !!projectId,
  });

  const activeCycleId = selectedCycleId ?? cycles[0]?.id ?? null;

  // Cycle level, not remark level: remarks are fetched per cycle inside
  // CycleDetailPanel, so a remark dataset would need a query this page does
  // not make.
  const insights = useModuleInsights('review-authority', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildReviewAuthorityInsights(cycles, t),
    [cycles, t],
  );

  const createMut = useMutation({
    mutationFn: (data: CreateCyclePayload) => createCycle(data),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['review-authority-cycles'] });
      setShowCreateModal(false);
      setSelectedCycleId(created.id);
      addToast({
        type: 'success',
        title: t('review_authority.cycle_created', { defaultValue: 'Cycle opened' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const handleCreateSubmit = useCallback(
    (formData: CycleFormData) => {
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: t('common.select_project_first', { defaultValue: 'Please select a project first' }),
        });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        authority_name: formData.authority_name,
        authority_kind: formData.authority_kind,
        submission_ref: formData.submission_ref || undefined,
        current_document_version: formData.current_document_version || undefined,
        sla_days: formData.sla_days,
        jurisdiction: formData.jurisdiction || undefined,
        notes: formData.notes || undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(selectedProjectId && projectName
            ? [{ label: projectName, to: `/projects/${selectedProjectId}` }]
            : []),
          { label: t('review_authority.title', { defaultValue: 'Review Authority' }) },
        ]}
      />

      <PageHeader
        srTitle={t('review_authority.title', { defaultValue: 'Review Authority' })}
        subtitle={t('review_authority.subtitle', {
          defaultValue: 'Track the review cycle a project runs with an external approving authority',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <ModuleGuideButton content={reviewAuthorityGuide} />
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowCreateModal(true)}
              disabled={!projectId}
              title={
                !projectId
                  ? t('common.select_project_first', { defaultValue: 'Please select a project first' })
                  : undefined
              }
              className="shrink-0 whitespace-nowrap"
              icon={<Plus size={14} />}
            >
              {t('review_authority.new_cycle', { defaultValue: 'New Review Cycle' })}
            </Button>
          </>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('review_authority.insights.title', { defaultValue: 'Review authority insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <DismissibleInfo
        storageKey="review-authority"
        title={t('review_authority.intro_title', {
          defaultValue: 'The evidence trail of your external review',
        })}
      >
        {t('review_authority.intro_body', {
          defaultValue:
            'Open a cycle for each submission to an external approving authority: state expertise, building control, an authority having jurisdiction, or a technical review board. Track the document version pinned at submission, log remarks with their severity and cited norm, respond, and record the final decision. Remarks without a cited norm are flagged for a human to confirm, remarks against an outdated version are flagged stale, and remarks that echo one already accepted are flagged by the repeat radar.',
        })}
      </DismissibleInfo>

      {!projectId && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_hint', { defaultValue: 'Select a project from the header to get started.' })}
        </div>
      )}

      {projectId && (
        <>
          {/* Filters */}
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="relative">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as CycleStatus | '')}
                aria-label={t('review_authority.filter_all_status', { defaultValue: 'All Statuses' })}
                className="h-10 appearance-none rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-44"
              >
                <option value="">
                  {t('review_authority.filter_all_status', { defaultValue: 'All Statuses' })}
                </option>
                {CYCLE_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t(`review_authority.cycle_status_${s}`, { defaultValue: CYCLE_STATUS_LABELS[s] })}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 end-0 flex items-center pe-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>

            <div className="relative">
              <select
                value={authorityFilter}
                onChange={(e) => setAuthorityFilter(e.target.value as AuthorityKind | '')}
                aria-label={t('review_authority.filter_all_authority', { defaultValue: 'All Authority Kinds' })}
                className="h-10 appearance-none rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-52"
              >
                <option value="">
                  {t('review_authority.filter_all_authority', { defaultValue: 'All Authority Kinds' })}
                </option>
                {AUTHORITY_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`review_authority.authority_kind_${k}`, { defaultValue: AUTHORITY_KIND_LABELS[k] })}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 end-0 flex items-center pe-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>
          </div>

          {isLoading ? (
            <SkeletonTable rows={4} columns={2} />
          ) : isError ? (
            <RecoveryCard error={error} onRetry={() => refetch()} />
          ) : cycles.length === 0 ? (
            <EmptyState
              icon={<Landmark size={28} strokeWidth={1.5} />}
              title={
                statusFilter || authorityFilter
                  ? t('review_authority.no_results', { defaultValue: 'No matching cycles' })
                  : t('review_authority.no_cycles', { defaultValue: 'No review cycles yet' })
              }
              description={
                statusFilter || authorityFilter
                  ? t('review_authority.no_results_hint', { defaultValue: 'Try adjusting your filters' })
                  : t('review_authority.no_cycles_hint', {
                      defaultValue: 'Open your first review cycle with an approving authority',
                    })
              }
              action={
                !statusFilter && !authorityFilter
                  ? {
                      label: t('review_authority.new_cycle', { defaultValue: 'New Review Cycle' }),
                      onClick: () => setShowCreateModal(true),
                    }
                  : undefined
              }
            />
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4 items-start">
              {/* List */}
              <div className="space-y-2">
                {cycles.map((c) => (
                  <CycleListRow
                    key={c.id}
                    cycle={c}
                    selected={c.id === activeCycleId}
                    onSelect={() => setSelectedCycleId(c.id)}
                  />
                ))}
              </div>

              {/* Detail */}
              <div>{activeCycleId && <CycleDetailPanel cycleId={activeCycleId} />}</div>
            </div>
          )}
        </>
      )}

      {showCreateModal && (
        <CreateCycleModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
        />
      )}
    </div>
  );
}
