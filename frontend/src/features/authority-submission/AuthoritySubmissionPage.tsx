// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  FileStack,
  Search,
  Plus,
  ChevronRight,
  Pencil,
  Trash2,
  ShieldCheck,
  FileCode2,
  Send,
  AlertTriangle,
  CheckCircle2,
  ArrowRight,
  Network,
  Workflow,
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
  CollapsibleSection,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchSubmissions,
  fetchSubmissionMeta,
  fetchProfiles,
  createSubmission,
  updateSubmission,
  deleteSubmission,
  validateSubmission,
  generateSubmissionXml,
  renderSubmission,
  submitSubmission,
  type Submission,
  type SubmissionStatus,
  type SubmissionProfile,
  type CreateSubmissionPayload,
} from './api';
import { authoritySubmissionGuide } from './authoritySubmissionGuide';
import { fmtList, fmtFixed } from '@/shared/lib/formatters';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const STATUS_ORDER: SubmissionStatus[] = [
  'draft',
  'validated',
  'signed_pending',
  'submitted',
  'accepted',
  'rejected',
];

const STATUS_LABELS: Record<SubmissionStatus, string> = {
  draft: 'Draft',
  validated: 'Validated',
  signed_pending: 'Awaiting signature',
  submitted: 'Submitted',
  accepted: 'Accepted',
  rejected: 'Rejected',
};

const statusVariant = (
  s: SubmissionStatus,
): 'blue' | 'warning' | 'success' | 'error' | 'neutral' => {
  switch (s) {
    case 'validated':
      return 'blue';
    case 'signed_pending':
      return 'warning';
    case 'submitted':
      return 'blue';
    case 'accepted':
      return 'success';
    case 'rejected':
      return 'error';
    default:
      return 'neutral';
  }
};

/** Turns a submission title into a filesystem-safe filename fragment. */
const safeFileSlug = (s: string): string => s.trim().replace(/[^\w.-]+/g, '_') || 'submission';

/* Mirrors the backend's _ALLOWED_TRANSITIONS map (service.py) so the UI only
   ever offers a move the API will actually accept. */
const ALLOWED_TRANSITIONS: Record<SubmissionStatus, SubmissionStatus[]> = {
  draft: [],
  validated: ['signed_pending', 'draft'],
  signed_pending: ['validated', 'draft'],
  submitted: ['accepted', 'rejected'],
  accepted: [],
  rejected: ['draft'],
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-y';

/* ── Create / Edit Modal ───────────────────────────────────────────────── */

interface SubmissionFormData {
  profile_id: string;
  title: string;
  payloadText: string;
}

const EMPTY_FORM: SubmissionFormData = {
  profile_id: '',
  title: '',
  payloadText: '{}',
};

function CreateSubmissionModal({
  onClose,
  onSubmit,
  isPending,
  initialData,
  isEdit,
  profiles,
}: {
  onClose: () => void;
  onSubmit: (data: SubmissionFormData) => void;
  isPending: boolean;
  initialData?: SubmissionFormData | null;
  isEdit?: boolean;
  profiles: SubmissionProfile[];
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<SubmissionFormData>(initialData ?? EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof SubmissionFormData>(key: K, value: SubmissionFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const selectedProfile = profiles.find((p) => p.id === form.profile_id);

  const payloadError = useMemo(() => {
    try {
      const parsed: unknown = JSON.parse(form.payloadText || '{}');
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return t('authority_submission.payload_must_be_object', {
          defaultValue: 'The payload must be a JSON object.',
        });
      }
      return null;
    } catch {
      return t('authority_submission.payload_invalid_json', {
        defaultValue: 'This is not valid JSON.',
      });
    }
  }, [form.payloadText, t]);

  const titleError = touched && form.title.trim().length === 0;
  const profileError = touched && !isEdit && form.profile_id.trim().length === 0;
  const canSubmit =
    form.title.trim().length > 0 && (isEdit || form.profile_id.trim().length > 0) && !payloadError;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  const loadFieldSpecTemplate = () => {
    if (!selectedProfile) return;
    const template: Record<string, unknown> = {};
    for (const f of selectedProfile.field_spec) {
      if (f.type === 'array') template[f.name] = [];
      else if (f.type === 'object') template[f.name] = {};
      else if (f.type === 'boolean') template[f.name] = false;
      else if (f.type === 'number' || f.type === 'integer') template[f.name] = 0;
      else template[f.name] = '';
    }
    set('payloadText', JSON.stringify(template, null, 2));
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="xl"
      title={
        isEdit
          ? t('authority_submission.edit_submission', { defaultValue: 'Edit Submission' })
          : t('authority_submission.new_submission', { defaultValue: 'New Submission' })
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
                ? t('authority_submission.save_submission', { defaultValue: 'Save Changes' })
                : t('authority_submission.create_submission', { defaultValue: 'Create Submission' })}
            </span>
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('authority_submission.section_details', { defaultValue: 'Submission Details' })}
        columns={2}
      >
        {!isEdit && (
          <WideModalField
            label={t('authority_submission.field_profile', { defaultValue: 'Profile' })}
            required
            span={2}
            htmlFor="sub-profile"
            hint={t('authority_submission.field_profile_hint', {
              defaultValue: 'The schema this submission is built against (field set and root element).',
            })}
            error={
              profileError
                ? t('authority_submission.profile_required', { defaultValue: 'Choose a profile' })
                : undefined
            }
          >
            <select
              id="sub-profile"
              value={form.profile_id}
              onChange={(e) => {
                set('profile_id', e.target.value);
                setTouched(true);
              }}
              className={inputCls}
            >
              <option value="">
                {t('authority_submission.select_profile', { defaultValue: 'Select a profile...' })}
              </option>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.jurisdiction ? ` (${p.jurisdiction})` : ''}
                </option>
              ))}
            </select>
          </WideModalField>
        )}

        <WideModalField
          label={t('authority_submission.field_title', { defaultValue: 'Title' })}
          required
          span={2}
          htmlFor="sub-title"
          error={
            titleError
              ? t('authority_submission.title_required', { defaultValue: 'Title is required' })
              : undefined
          }
        >
          <input
            id="sub-title"
            value={form.title}
            onChange={(e) => {
              set('title', e.target.value);
              setTouched(true);
            }}
            placeholder={t('authority_submission.title_placeholder', {
              defaultValue: 'e.g. Foundation works tender exchange',
            })}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('authority_submission.field_payload', { defaultValue: 'Payload (JSON)' })}
          span={2}
          htmlFor="sub-payload"
          hint={t('authority_submission.field_payload_hint', {
            defaultValue: 'Data matching the profile field set. Editing this later resets the submission to Draft.',
          })}
          error={payloadError ?? undefined}
        >
          <div className="space-y-1.5">
            {!isEdit && selectedProfile && (
              <Button variant="secondary" size="sm" onClick={loadFieldSpecTemplate} type="button">
                {t('authority_submission.load_template', {
                  defaultValue: 'Load empty template from profile',
                })}
              </Button>
            )}
            <textarea
              id="sub-payload"
              value={form.payloadText}
              onChange={(e) => set('payloadText', e.target.value)}
              rows={10}
              spellCheck={false}
              className={clsx(
                textareaCls,
                payloadError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
            />
          </div>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Validation report card ────────────────────────────────────────────── */

function ValidationReportCard({ report }: { report: Submission['validation_report'] }) {
  const { t } = useTranslation();
  if (!report) return null;
  const passed = report.status === 'passed';
  return (
    <div
      className={clsx(
        'rounded-lg border p-3 text-xs space-y-2',
        passed
          ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30'
          : 'border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950/30',
      )}
    >
      <div className="flex items-center gap-1.5 font-semibold">
        {passed ? (
          <CheckCircle2 size={13} className="text-emerald-600 dark:text-emerald-400" />
        ) : (
          <AlertTriangle size={13} className="text-red-600 dark:text-red-400" />
        )}
        <span className={passed ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-700 dark:text-red-300'}>
          {passed
            ? t('authority_submission.validation_passed', { defaultValue: 'Validation passed' })
            : t('authority_submission.validation_failed', {
                defaultValue: '{{count}} validation error(s)',
                count: report.errors,
              })}
        </span>
        <span className="text-content-tertiary font-normal">
          {t('authority_submission.validation_score', {
            defaultValue: 'score {{score}}',
            score: fmtFixed(report.score, 2),
          })}
        </span>
      </div>
      {report.missing_required.length > 0 && (
        <p className="text-content-secondary">
          {t('authority_submission.missing_required', { defaultValue: 'Missing required:' })}{' '}
          {fmtList(report.missing_required)}
        </p>
      )}
      {report.type_mismatches.length > 0 && (
        <ul className="list-disc pl-4 text-content-secondary space-y-0.5">
          {report.type_mismatches.map((m, i) => (
            <li key={`${m.field}-${i}`}>
              {m.field}: {t('authority_submission.type_mismatch', {
                defaultValue: 'expected {{expected}}, got {{got}}',
                expected: m.expected,
                got: m.got,
              })}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── Submission Row (expandable) ──────────────────────────────────────── */

const SubmissionRow = React.memo(function SubmissionRow({
  item,
  profileName,
  onEdit,
  onDelete,
  onValidate,
  onGenerateXml,
  onSubmit,
  onSetStatus,
  isBusy,
}: {
  item: Submission;
  profileName: string;
  onEdit: (item: Submission) => void;
  onDelete: (item: Submission) => void;
  onValidate: (item: Submission) => void;
  onGenerateXml: (item: Submission) => void;
  onSubmit: (item: Submission) => void;
  onSetStatus: (item: Submission, status: SubmissionStatus) => void;
  isBusy: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const { data: rendered, isFetching: renderLoading } = useQuery({
    queryKey: ['authority-submission-render', item.id],
    queryFn: () => renderSubmission(item.id),
    enabled: expanded,
    staleTime: 30_000,
  });

  const canSubmit =
    (item.status === 'validated' || item.status === 'signed_pending') &&
    item.validation_report?.status === 'passed';

  const nextStatuses = ALLOWED_TRANSITIONS[item.status] ?? [];

  return (
    <div className="border-b border-border-light last:border-b-0">
      <div
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setExpanded((prev) => !prev);
          }
        }}
      >
        <ChevronRight
          size={14}
          className={clsx('text-content-tertiary transition-transform shrink-0', expanded && 'rotate-90')}
        />
        <span className="text-sm text-content-primary truncate flex-1 min-w-0 font-medium">{item.title}</span>
        <Badge variant="neutral" size="sm" className="hidden md:inline-flex shrink-0">
          {profileName}
        </Badge>
        <Badge variant={statusVariant(item.status)} size="sm" className="shrink-0">
          {t(`authority_submission.status_${item.status}`, { defaultValue: STATUS_LABELS[item.status] })}
        </Badge>
        <span className="text-xs w-24 shrink-0 hidden sm:block">
          <DateDisplay value={item.updated_at} className="text-xs text-content-tertiary" />
        </span>
      </div>

      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          <ValidationReportCard report={item.validation_report} />

          {item.generated_xml && (
            <details className="rounded-lg border border-border-light bg-surface-secondary/40 p-2.5">
              <summary className="cursor-pointer text-xs font-medium text-content-secondary flex items-center justify-between gap-2">
                <span>{t('authority_submission.generated_xml', { defaultValue: 'Generated XML' })}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Download size={12} />}
                  onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    const blob = new Blob([item.generated_xml ?? ''], {
                      type: 'application/xml;charset=utf-8',
                    });
                    triggerDownload(blob, `${safeFileSlug(item.title)}-${item.id.slice(0, 8)}.xml`);
                  }}
                >
                  {t('authority_submission.action_download_xml', { defaultValue: 'Download XML' })}
                </Button>
              </summary>
              <pre className="mt-2 max-h-64 overflow-auto rounded bg-surface-primary p-2 text-2xs whitespace-pre-wrap break-all">
                {item.generated_xml}
              </pre>
            </details>
          )}

          <details className="rounded-lg border border-border-light bg-surface-secondary/40 p-2.5" open>
            <summary className="cursor-pointer text-xs font-medium text-content-secondary flex items-center justify-between gap-2">
              <span>{t('authority_submission.human_review', { defaultValue: 'Human review' })}</span>
              {rendered && (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Download size={12} />}
                  onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    const blob = new Blob([rendered.text], { type: 'text/plain;charset=utf-8' });
                    triggerDownload(blob, `${safeFileSlug(item.title)}-${item.id.slice(0, 8)}-review.txt`);
                  }}
                >
                  {t('authority_submission.action_download_review', { defaultValue: 'Download' })}
                </Button>
              )}
            </summary>
            {renderLoading ? (
              <p className="mt-2 text-xs text-content-tertiary">
                {t('common.loading', { defaultValue: 'Loading…' })}
              </p>
            ) : rendered ? (
              <pre className="mt-2 max-h-64 overflow-auto rounded bg-surface-primary p-2 text-2xs whitespace-pre-wrap">
                {rendered.text}
              </pre>
            ) : null}
          </details>

          {/* Actions */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              variant="secondary"
              size="sm"
              icon={<ShieldCheck size={13} />}
              disabled={isBusy}
              onClick={(e) => {
                e.stopPropagation();
                onValidate(item);
              }}
            >
              {t('authority_submission.action_validate', { defaultValue: 'Validate' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<FileCode2 size={13} />}
              disabled={isBusy}
              onClick={(e) => {
                e.stopPropagation();
                onGenerateXml(item);
              }}
            >
              {t('authority_submission.action_generate_xml', { defaultValue: 'Generate XML' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<Send size={13} />}
              disabled={isBusy || !canSubmit}
              title={
                !canSubmit
                  ? t('authority_submission.submit_disabled_hint', {
                      defaultValue: 'Validate cleanly first (status must be Validated or Awaiting signature).',
                    })
                  : undefined
              }
              onClick={(e) => {
                e.stopPropagation();
                onSubmit(item);
              }}
            >
              {t('authority_submission.action_submit', { defaultValue: 'Submit' })}
            </Button>

            {nextStatuses.map((target) => (
              <Button
                key={target}
                variant="ghost"
                size="sm"
                disabled={isBusy}
                onClick={(e) => {
                  e.stopPropagation();
                  onSetStatus(item, target);
                }}
              >
                {t('authority_submission.action_move_to', {
                  defaultValue: 'Mark {{status}}',
                  status: t(`authority_submission.status_${target}`, { defaultValue: STATUS_LABELS[target] }),
                })}
              </Button>
            ))}

            <span className="flex-1" />

            <Button
              variant="secondary"
              size="sm"
              icon={<Pencil size={13} />}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(item);
              }}
            >
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              className="text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30"
              icon={<Trash2 size={13} />}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(item);
              }}
            >
              {t('common.delete', { defaultValue: 'Delete' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
});

/* ── How-it-works ──────────────────────────────────────────────────────── */

function HowAuthoritySubmissionWorks() {
  const { t } = useTranslation();

  const steps: { icon: React.ReactNode; title: string; desc: string }[] = [
    {
      icon: <FileStack size={14} className="text-oe-blue" />,
      title: t('authority_submission.how_step1_title', { defaultValue: 'Pick a profile' }),
      desc: t('authority_submission.how_step1_desc', {
        defaultValue: 'Choose a jurisdiction-neutral profile: its schema fixes the field set and root element.',
      }),
    },
    {
      icon: <ShieldCheck size={14} className="text-oe-blue" />,
      title: t('authority_submission.how_step2_title', { defaultValue: 'Validate' }),
      desc: t('authority_submission.how_step2_desc', {
        defaultValue: 'Check the payload against the profile before anything is generated or sent.',
      }),
    },
    {
      icon: <FileCode2 size={14} className="text-oe-blue" />,
      title: t('authority_submission.how_step3_title', { defaultValue: 'Generate & review' }),
      desc: t('authority_submission.how_step3_desc', {
        defaultValue: 'One payload drives both the machine XML and the human-readable review.',
      }),
    },
    {
      icon: <Send size={14} className="text-oe-blue" />,
      title: t('authority_submission.how_step4_title', { defaultValue: 'Submit' }),
      desc: t('authority_submission.how_step4_desc', {
        defaultValue: 'Only a cleanly validated submission can be sent to the authority.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="authority_submission.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('authority_submission.how_title', { defaultValue: 'How the submission factory fits together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('authority_submission.how_intro', {
          defaultValue:
            'Build the structured document an authority expects, validate it against its profile, then generate the machine XML and submit once the checks are clean.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <React.Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-primary p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
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
    </CollapsibleSection>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function AuthoritySubmissionPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingItem, setEditingItem] = useState<Submission | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<SubmissionStatus | ''>('');
  const { confirm, ...confirmProps } = useConfirm();

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const selectedProjectId = routeProjectId || activeProjectId || '';
  const projectName = projects.find((p) => p.id === selectedProjectId)?.name || '';

  const { data: meta } = useQuery({
    queryKey: ['authority-submission-meta'],
    queryFn: fetchSubmissionMeta,
    staleTime: 10 * 60_000,
  });

  const { data: profiles = [] } = useQuery({
    queryKey: ['authority-submission-profiles'],
    queryFn: () => fetchProfiles(),
    staleTime: 5 * 60_000,
  });
  const profileName = useCallback(
    (profileId: string) => profiles.find((p) => p.id === profileId)?.name ?? profileId.slice(0, 8),
    [profiles],
  );

  const {
    data: items = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['authority-submissions', projectId, statusFilter],
    queryFn: () => fetchSubmissions({ project_id: projectId, status: statusFilter || undefined }),
    enabled: !!projectId,
  });

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return items;
    const q = searchQuery.toLowerCase();
    return items.filter((s) => s.title.toLowerCase().includes(q));
  }, [items, searchQuery]);

  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['authority-submissions'] });
  }, [qc]);

  const invalidateOne = useCallback(
    (id: string) => {
      invalidateAll();
      qc.invalidateQueries({ queryKey: ['authority-submission-render', id] });
    },
    [invalidateAll, qc],
  );

  const showError = useCallback(
    (e: unknown) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      }),
    [addToast, t],
  );

  const createMut = useMutation({
    mutationFn: (data: CreateSubmissionPayload) => createSubmission(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('authority_submission.created', { defaultValue: 'Submission created' }),
      });
    },
    onError: showError,
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateSubmission>[1] }) =>
      updateSubmission(id, data),
    onSuccess: () => {
      invalidateAll();
      setEditingItem(null);
      addToast({
        type: 'success',
        title: t('authority_submission.updated', { defaultValue: 'Submission updated' }),
      });
    },
    onError: showError,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSubmission(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('authority_submission.deleted', { defaultValue: 'Submission deleted' }),
      });
    },
    onError: showError,
  });

  const validateMut = useMutation({
    mutationFn: (id: string) => validateSubmission(id),
    onSuccess: (report, id) => {
      invalidateOne(id);
      addToast({
        type: report.status === 'passed' ? 'success' : 'warning',
        title:
          report.status === 'passed'
            ? t('authority_submission.validation_passed', { defaultValue: 'Validation passed' })
            : t('authority_submission.validation_failed', {
                defaultValue: '{{count}} validation error(s)',
                count: report.errors,
              }),
      });
    },
    onError: showError,
  });

  const generateXmlMut = useMutation({
    mutationFn: (id: string) => generateSubmissionXml(id),
    onSuccess: (_res, id) => {
      invalidateOne(id);
      addToast({
        type: 'success',
        title: t('authority_submission.xml_generated', { defaultValue: 'XML generated' }),
      });
    },
    onError: showError,
  });

  const submitMut = useMutation({
    mutationFn: (id: string) => submitSubmission(id),
    onSuccess: (_res, id) => {
      invalidateOne(id);
      addToast({
        type: 'success',
        title: t('authority_submission.submitted', { defaultValue: 'Submission sent' }),
      });
    },
    onError: showError,
  });

  const setStatusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: SubmissionStatus }) =>
      updateSubmission(id, { status: status as 'draft' | 'signed_pending' | 'accepted' | 'rejected' }),
    onSuccess: (_res, { id }) => {
      invalidateOne(id);
      addToast({
        type: 'success',
        title: t('authority_submission.updated', { defaultValue: 'Submission updated' }),
      });
    },
    onError: showError,
  });

  const isBusy =
    validateMut.isPending || generateXmlMut.isPending || submitMut.isPending || setStatusMut.isPending;

  const handleCreateSubmit = useCallback(
    (formData: { profile_id: string; title: string; payloadText: string }) => {
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: t('common.select_project_first', { defaultValue: 'Please select a project first' }),
        });
        return;
      }
      let payload: Record<string, unknown> = {};
      try {
        payload = JSON.parse(formData.payloadText || '{}') as Record<string, unknown>;
      } catch {
        /* form-level validation already blocks submit on invalid JSON */
      }
      createMut.mutate({
        project_id: projectId,
        profile_id: formData.profile_id,
        title: formData.title,
        payload,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const handleEditSubmit = useCallback(
    (formData: { profile_id: string; title: string; payloadText: string }) => {
      if (!editingItem) return;
      let payload: Record<string, unknown> | undefined;
      try {
        payload = JSON.parse(formData.payloadText || '{}') as Record<string, unknown>;
      } catch {
        payload = undefined;
      }
      updateMut.mutate({ id: editingItem.id, data: { title: formData.title, payload } });
    },
    [updateMut, editingItem],
  );

  const formDataFromItem = useCallback(
    (s: Submission) => ({
      profile_id: s.profile_id,
      title: s.title,
      payloadText: JSON.stringify(s.payload ?? {}, null, 2),
    }),
    [],
  );

  const handleDelete = useCallback(
    async (item: Submission) => {
      const ok = await confirm({
        title: t('authority_submission.confirm_delete_title', { defaultValue: 'Delete submission?' }),
        message: t('authority_submission.confirm_delete_msg', {
          defaultValue: 'This permanently removes the submission "{{title}}".',
          title: item.title,
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(item.id);
    },
    [deleteMut, confirm, t],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(selectedProjectId && projectName
            ? [{ label: projectName, to: `/projects/${selectedProjectId}` }]
            : []),
          { label: t('authority_submission.title', { defaultValue: 'Authority Submissions' }) },
        ]}
      />

      <PageHeader
        srTitle={t('authority_submission.title', { defaultValue: 'Authority Submissions' })}
        subtitle={t('authority_submission.subtitle', {
          defaultValue: 'Build, validate and send the structured documents an authority expects',
        })}
        actions={
          <>
            <ModuleGuideButton content={authoritySubmissionGuide} />
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowCreateModal(true)}
              disabled={!projectId}
              title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
              className="shrink-0 whitespace-nowrap"
              icon={<Plus size={14} />}
            >
              {t('authority_submission.new_submission', { defaultValue: 'New Submission' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="authority_submission"
        title={t('authority_submission.intro_title', {
          defaultValue: 'One payload, one validated document, one submission',
        })}
      >
        {t('authority_submission.intro_body', {
          defaultValue:
            'A generic engine for the structured documents a delivery must hand to an authority: tender exchanges, expertise packages, asset handover registers. Pick a jurisdiction-neutral profile, fill the payload, validate it against the profile field set, generate the deterministic XML and review it as a human before you submit. A new format is a new profile, not new code.',
        })}
      </DismissibleInfo>

      <HowAuthoritySubmissionWorks />

      {!projectId && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_hint', { defaultValue: 'Select a project from the header to get started.' })}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('authority_submission.search_placeholder', { defaultValue: 'Search submissions...' })}
            aria-label={t('authority_submission.search_placeholder', { defaultValue: 'Search submissions...' })}
            className={inputCls + ' pl-9'}
          />
        </div>

        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as SubmissionStatus | '')}
            aria-label={t('authority_submission.filter_all_status', { defaultValue: 'All Statuses' })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-44"
          >
            <option value="">
              {t('authority_submission.filter_all_status', { defaultValue: 'All Statuses' })}
            </option>
            {(meta?.statuses ?? STATUS_ORDER.map((s) => ({ code: s, label: STATUS_LABELS[s] }))).map((s) => (
              <option key={s.code} value={s.code}>
                {t(`authority_submission.status_${s.code}`, { defaultValue: s.label })}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* List */}
      <div>
        {isLoading ? (
          <SkeletonTable rows={5} columns={4} />
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Workflow size={28} strokeWidth={1.5} />}
            title={
              searchQuery || statusFilter
                ? t('authority_submission.no_results', { defaultValue: 'No matching submissions' })
                : t('authority_submission.no_submissions', { defaultValue: 'No submissions yet' })
            }
            description={
              searchQuery || statusFilter
                ? t('authority_submission.no_results_hint', { defaultValue: 'Try adjusting your search or filters' })
                : t('authority_submission.no_submissions_hint', {
                    defaultValue: 'Start your first submission from a profile',
                  })
            }
            action={
              !searchQuery && !statusFilter
                ? {
                    label: t('authority_submission.new_submission', { defaultValue: 'New Submission' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('authority_submission.showing_count', {
                defaultValue: '{{count}} submissions',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[560px]">
                <span className="w-5" />
                <span className="flex-1">{t('authority_submission.col_title', { defaultValue: 'Title' })}</span>
                <span className="w-32 hidden md:block">
                  {t('authority_submission.col_profile', { defaultValue: 'Profile' })}
                </span>
                <span className="w-32">{t('authority_submission.col_status', { defaultValue: 'Status' })}</span>
                <span className="w-24 hidden sm:block">
                  {t('authority_submission.col_updated', { defaultValue: 'Updated' })}
                </span>
              </div>
              {filtered.map((s) => (
                <SubmissionRow
                  key={s.id}
                  item={s}
                  profileName={profileName(s.profile_id)}
                  onEdit={(item) => setEditingItem(item)}
                  onDelete={handleDelete}
                  onValidate={(item) => validateMut.mutate(item.id)}
                  onGenerateXml={(item) => generateXmlMut.mutate(item.id)}
                  onSubmit={(item) => submitMut.mutate(item.id)}
                  onSetStatus={(item, status) => setStatusMut.mutate({ id: item.id, status })}
                  isBusy={isBusy}
                />
              ))}
            </Card>
          </>
        )}
      </div>

      {showCreateModal && (
        <CreateSubmissionModal
          profiles={profiles}
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
        />
      )}

      {editingItem && (
        <CreateSubmissionModal
          isEdit
          profiles={profiles}
          initialData={formDataFromItem(editingItem)}
          onClose={() => setEditingItem(null)}
          onSubmit={handleEditSubmit}
          isPending={updateMut.isPending}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
