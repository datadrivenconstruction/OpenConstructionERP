// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { Fragment, useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  Database,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  ArrowRight,
  Send,
  Link2,
  FileText,
  FileCheck,
  Check,
  File,
  Network,
  Archive,
  Users,
  Gauge,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, DateDisplay, ConfirmDialog, RecoveryCard, SkeletonTable, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo, IntroRichText } from '@/shared/ui/DismissibleInfo';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchCDEContainers,
  createCDEContainer,
  transitionContainer,
  fetchContainerRevisions,
  createContainerRevision,
  fetchSuitabilityCodes,
  fetchFunctionalRoles,
  fetchCDEReadiness,
  fetchCDEStats,
  type CDEContainer,
  type CDEState,
  type CDEDiscipline,
  type CDERevision,
  type CreateCDEContainerPayload,
  type TransitionPayload,
} from './api';
import { CDEHistoryDrawer } from './CDEHistoryDrawer';
import { CDETransmittalsBadge } from './CDETransmittalsBadge';
import { cdeGuide } from './cdeGuide';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

/** Helper to read the CDE state from a container (backend returns `cde_state`). */
function getContainerState(c: CDEContainer): CDEState {
  return (c.cde_state ?? 'wip') as CDEState;
}

/** Helper to read the discipline from a container (backend returns `discipline_code`). */
function getContainerDiscipline(c: CDEContainer): CDEDiscipline {
  return (c.discipline_code ?? 'other') as CDEDiscipline;
}

const STATE_CONFIG: Record<
  CDEState,
  { variant: 'neutral' | 'blue' | 'success' | 'warning'; cls: string; label: string }
> = {
  wip: {
    variant: 'warning',
    cls: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    label: 'WIP',
  },
  shared: { variant: 'blue', cls: '', label: 'Shared' },
  published: { variant: 'success', cls: '', label: 'Published' },
  archived: {
    variant: 'neutral',
    cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    label: 'Archived',
  },
};

const STATE_ORDER: CDEState[] = ['wip', 'shared', 'published', 'archived'];

/**
 * Mirror of the backend ISO 19650 gate roles (see
 * backend/app/modules/cde/service.py + core/cde_states.py). Promoting a
 * container crosses a gate that requires a minimum role:
 *   Gate A (wip → shared)        : manager / admin
 *   Gate B (shared → published)  : manager / admin
 *   Gate C (published → archived): admin only
 * Editors and viewers can never promote, so we hide the action for them
 * rather than letting the click 400.
 */
function normalizeRole(role: string | null | undefined): string {
  const r = (role ?? 'viewer').trim().toLowerCase();
  const aliases: Record<string, string> = {
    estimator: 'editor',
    quantity_surveyor: 'editor',
    qs: 'editor',
    user: 'editor',
    superuser: 'admin',
    owner: 'admin',
    readonly: 'viewer',
    guest: 'viewer',
  };
  return aliases[r] ?? r;
}

function canRoleCrossGate(role: string | null | undefined, fromState: CDEState): boolean {
  const r = normalizeRole(role);
  if (fromState === 'published') return r === 'admin'; // Gate C — archive
  if (fromState === 'wip' || fromState === 'shared') return r === 'admin' || r === 'manager';
  return false; // archived has no onward gate
}

const DISCIPLINE_LABELS: Record<CDEDiscipline, string> = {
  architecture: 'Architecture',
  structural: 'Structural',
  mep: 'MEP',
  civil: 'Civil',
  landscape: 'Landscape',
  interior: 'Interior',
  other: 'Other',
};

const DISCIPLINE_COLORS: Record<CDEDiscipline, string> = {
  architecture: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  structural: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  mep: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  civil: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  landscape: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  interior: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  other: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── Create Modal ─────────────────────────────────────────────────────── */

interface CDEFormData {
  container_code: string;
  title: string;
  discipline: CDEDiscipline;
  suitability_code: string;
  classification: string;
  cde_state: CDEState;
}

const EMPTY_FORM: CDEFormData = {
  container_code: '',
  title: '',
  discipline: 'architecture',
  suitability_code: '',
  classification: '',
  cde_state: 'wip',
};

function CreateCDEModal({
  onClose,
  onSubmit,
  isPending,
  errorMessage,
}: {
  onClose: () => void;
  onSubmit: (data: CDEFormData) => void;
  isPending: boolean;
  errorMessage?: string | null;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<CDEFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  // ISO 19650 suitability codes (RFC 33 §3.1) — filtered by the chosen state.
  const { data: suitabilityCodes } = useQuery({
    queryKey: ['cde-suitability-codes'],
    queryFn: fetchSuitabilityCodes,
    staleTime: Infinity,
  });
  const availableCodes = suitabilityCodes?.by_state?.[form.cde_state] ?? [];

  // If the user changes the state and the current code is no longer valid,
  // reset it so we never submit an invalid combo (which would 422 anyway).
  useEffect(() => {
    if (
      form.suitability_code &&
      availableCodes.length > 0 &&
      !availableCodes.some((c) => c.code === form.suitability_code)
    ) {
      setForm((prev) => ({ ...prev, suitability_code: '' }));
    }
  }, [form.cde_state, availableCodes, form.suitability_code]);

  const set = <K extends keyof CDEFormData>(key: K, value: CDEFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const codeError = touched && form.container_code.trim().length === 0;
  const titleError = touched && form.title.trim().length === 0;
  const canSubmit = form.container_code.trim().length > 0 && form.title.trim().length > 0;

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
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('cde.new_container', { defaultValue: 'New Container' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('cde.new_container', { defaultValue: 'New Container' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-4">
          {errorMessage && (
            <div
              className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error/5 px-3 py-2 text-sm text-semantic-error"
              data-testid="cde-create-error"
              role="alert"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="mt-0.5 shrink-0" aria-hidden="true">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
                <path d="M12 8v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <circle cx="12" cy="16" r="1" fill="currentColor" />
              </svg>
              <span className="leading-snug">{errorMessage}</span>
            </div>
          )}
          {/* Two-column: Code + Discipline */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('cde.field_code', { defaultValue: 'Container Code' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                value={form.container_code}
                onChange={(e) => {
                  set('container_code', e.target.value);
                  setTouched(true);
                }}
                placeholder={t('cde.code_placeholder', {
                  defaultValue: 'e.g. PRJ-ARC-DWG-001',
                })}
                className={clsx(
                  inputCls,
                  codeError &&
                    'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
                )}
                autoFocus
              />
              {codeError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('cde.code_required', { defaultValue: 'Container code is required' })}
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('cde.field_discipline', { defaultValue: 'Discipline' })}
              </label>
              <div className="relative">
                <select
                  value={form.discipline}
                  onChange={(e) => set('discipline', e.target.value as CDEDiscipline)}
                  className={inputCls + ' appearance-none pr-9'}
                >
                  {(Object.keys(DISCIPLINE_LABELS) as CDEDiscipline[]).map((d) => (
                    <option key={d} value={d}>
                      {t(`cde.discipline_${d}`, { defaultValue: DISCIPLINE_LABELS[d] })}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
          </div>

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('cde.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.title}
              onChange={(e) => {
                set('title', e.target.value);
                setTouched(true);
              }}
              placeholder={t('cde.title_placeholder', {
                defaultValue: 'e.g. Ground Floor Plan - General Arrangement',
              })}
              className={clsx(
                inputCls,
                titleError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('cde.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          {/* Two-column: State + Suitability Code (state-aware dropdown) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('cde.field_state', { defaultValue: 'State' })}
              </label>
              <div className="relative">
                <select
                  value={form.cde_state}
                  onChange={(e) => set('cde_state', e.target.value as CDEState)}
                  className={inputCls + ' appearance-none pr-9'}
                  aria-label={t('cde.field_state', { defaultValue: 'State' })}
                >
                  {STATE_ORDER.map((s) => (
                    <option key={s} value={s}>
                      {t(`cde.state_${s}`, { defaultValue: STATE_CONFIG[s].label })}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
            <div>
              <label
                htmlFor="cde-suitability-select"
                className="block text-sm font-medium text-content-primary mb-1.5"
              >
                {t('cde.field_suitability', { defaultValue: 'Suitability Code' })}
              </label>
              <div className="relative">
                <select
                  id="cde-suitability-select"
                  value={form.suitability_code}
                  onChange={(e) => set('suitability_code', e.target.value)}
                  className={inputCls + ' appearance-none pr-9'}
                  aria-label={t('cde.field_suitability', { defaultValue: 'Suitability Code' })}
                >
                  <option value="">
                    {t('cde.suitability_none', { defaultValue: '- None -' })}
                  </option>
                  {availableCodes.map((entry) => (
                    <option key={entry.code} value={entry.code}>
                      {entry.code} — {t(`cde.suitability_${entry.code}`, { defaultValue: entry.label })}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
          </div>

          {/* Classification */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('cde.field_classification', { defaultValue: 'Classification' })}
            </label>
            <input
              value={form.classification}
              onChange={(e) => set('classification', e.target.value)}
              placeholder={t('cde.classification_placeholder', {
                defaultValue: 'e.g. Uniclass Ss_20_05',
              })}
              className={inputCls}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('cde.create_container', { defaultValue: 'Create Container' })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Approval Signature Modal (Gate B) ─────────────────────────────────── */

function ApprovalSignatureModal({
  container,
  onClose,
  onSubmit,
  isPending,
}: {
  container: CDEContainer;
  onClose: () => void;
  onSubmit: (payload: TransitionPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [signature, setSignature] = useState('');
  const [comments, setComments] = useState('');
  const [touched, setTouched] = useState(false);

  const sigError = touched && signature.trim().length === 0;
  const canSubmit = signature.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({
      target_state: 'published',
      approver_signature: signature.trim(),
      approval_comments: comments.trim() || undefined,
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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      role="dialog"
      aria-label={t('cde.approval_modal_title', { defaultValue: 'Gate B approval signature' })}
    >
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('cde.approval_modal_title', { defaultValue: 'Gate B approval signature' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <p className="text-sm text-content-secondary">
            {t('cde.approval_modal_body', {
              defaultValue:
                'Promoting {{code}} from SHARED to PUBLISHED requires a signed approval (ISO 19650). Your signature and comments are recorded in the audit log.',
              code: container.container_code,
            })}
          </p>
          <div>
            <label
              htmlFor="cde-approval-sig"
              className="block text-sm font-medium text-content-primary mb-1.5"
            >
              {t('cde.approval_field_signature', { defaultValue: 'Signature' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              id="cde-approval-sig"
              value={signature}
              onChange={(e) => {
                setSignature(e.target.value);
                setTouched(true);
              }}
              placeholder={t('cde.approval_signature_placeholder', {
                defaultValue: 'Full name / initials',
              })}
              className={clsx(
                inputCls,
                sigError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {sigError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('cde.approval_signature_required', {
                  defaultValue: 'Signature is required',
                })}
              </p>
            )}
          </div>
          <div>
            <label
              htmlFor="cde-approval-comments"
              className="block text-sm font-medium text-content-primary mb-1.5"
            >
              {t('cde.approval_field_comments', { defaultValue: 'Comments' })}
            </label>
            <textarea
              id="cde-approval-comments"
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('cde.approval_comments_placeholder', {
                defaultValue: 'Optional notes for the audit trail...',
              })}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={isPending || !canSubmit}
          >
            {isPending && (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            )}
            {t('cde.approval_submit', { defaultValue: 'Sign and publish' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Link Document Modal ─────────────────────────────────────────────── */

interface DocItem {
  id: string;
  name: string;
  file_name?: string;
  file_size: number | null;
  mime_type: string | null;
  category: string | null;
  created_at: string;
}

function LinkDocumentModal({
  container,
  projectId,
  onClose,
  onLinked,
}: {
  container: CDEContainer;
  projectId: string;
  onClose: () => void;
  onLinked: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<DocItem[]>([]);
  const [linking, setLinking] = useState(false);

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['documents-for-link', projectId],
    queryFn: () =>
      apiGet<DocItem[] | { items: DocItem[] }>(
        `/v1/documents/?project_id=${projectId}&limit=100`,
      ).then((res) => (Array.isArray(res) ? res : (res as { items: DocItem[] }).items ?? [])),
  });

  const filtered = useMemo(() => {
    if (!search) return docs;
    const q = search.toLowerCase();
    return docs.filter((d) => (d.name || '').toLowerCase().includes(q));
  }, [docs, search]);

  const toggle = (doc: DocItem) => {
    setSelected((prev) =>
      prev.some((d) => d.id === doc.id) ? prev.filter((d) => d.id !== doc.id) : [...prev, doc],
    );
  };

  const handleLink = async () => {
    if (selected.length === 0) return;
    setLinking(true);

    // Attempt every selected document independently so one failure no longer
    // aborts the rest (the old for-await loop stopped at the first error and
    // left the user unsure which documents were linked).
    const docsToLink = selected;
    const results = await Promise.allSettled(
      docsToLink.map((doc) =>
        createContainerRevision(container.id, {
          file_name: doc.name || doc.file_name || 'document',
          change_summary: t('cde.linked_from_documents', {
            defaultValue: 'Linked from Documents',
          }),
          mime_type: doc.mime_type || undefined,
          file_size: doc.file_size ? String(doc.file_size) : undefined,
          // Link mode: reference the existing Document so its real file is
          // reused — never duplicate the row with a broken file path.
          document_id: doc.id,
        }),
      ),
    );

    const succeeded: DocItem[] = [];
    const failed: { doc: DocItem; reason: string }[] = [];
    results.forEach((res, i) => {
      const doc = docsToLink[i];
      if (!doc) return;
      if (res.status === 'fulfilled') {
        succeeded.push(doc);
      } else {
        failed.push({
          doc,
          reason:
            res.reason instanceof Error
              ? res.reason.message
              : String(res.reason ?? ''),
        });
      }
    });

    // Keep exactly the documents that still need linking selected, so the
    // "keep open to retry" branches below actually have something to retry
    // (the Link button is disabled when nothing is selected). On full success
    // `failed` is empty, so this clears the selection as before. Refresh
    // revisions for the documents that actually linked.
    setSelected(failed.map((f) => f.doc));
    if (succeeded.length > 0) onLinked();

    const firstFailure = failed[0];
    const failDetail = firstFailure
      ? t('cde.link_failed_detail', {
          defaultValue: 'Document "{{name}}" failed: {{reason}}',
          name: firstFailure.doc.name || firstFailure.doc.file_name || 'document',
          reason: firstFailure.reason || t('common.error', { defaultValue: 'Error' }),
        })
      : '';

    if (failed.length === 0) {
      // Full success — notify and close.
      addToast({
        type: 'success',
        title: t('cde.documents_linked', {
          defaultValue: '{{count}} document(s) linked',
          count: succeeded.length,
        }),
      });
      setLinking(false);
      onClose();
      return;
    }

    if (succeeded.length === 0) {
      // Total failure — keep the modal open so the user can retry.
      addToast({
        type: 'error',
        title: t('cde.link_failed', { defaultValue: 'Could not link documents' }),
        message: failDetail,
      });
    } else {
      // Partial success — report both counts and keep the modal open.
      addToast({
        type: 'warning',
        title: t('cde.link_partial', {
          defaultValue: '{{linked}} linked, {{failed}} failed',
          linked: succeeded.length,
          failed: failed.length,
        }),
        message: failDetail,
      });
    }
    setLinking(false);
  };

  const formatSize = (bytes: number | null) => {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      onClick={onClose}
    >
      <div
        className="bg-surface-primary rounded-xl shadow-2xl border border-border w-full max-w-lg mx-4 max-h-[80vh] flex flex-col animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div>
            <div className="flex items-center gap-2">
              <Link2 size={18} className="text-oe-blue" />
              <h3 className="text-base font-semibold">
                {t('cde.link_documents', { defaultValue: 'Link Documents' })}
              </h3>
            </div>
            <p className="text-xs text-content-secondary mt-0.5">
              {container.container_code} — {container.title}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="p-1 rounded hover:bg-surface-secondary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b border-border shrink-0">
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-content-quaternary"
            />
            <input
              className="h-9 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              placeholder={t('cde.search_documents', {
                defaultValue: 'Search documents...',
              })}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
            />
          </div>
          {selected.length > 0 && (
            <div className="mt-2 text-xs text-oe-blue font-medium">
              {selected.length} {t('cde.selected', { defaultValue: 'selected' })}
            </div>
          )}
        </div>

        {/* Document list */}
        <div className="flex-1 overflow-y-auto px-2 py-2">
          {isLoading ? (
            <div className="space-y-2 px-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded-lg bg-surface-secondary" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-8 text-content-tertiary text-sm">
              <FileText size={24} className="mx-auto mb-2 opacity-30" />
              <p>
                {docs.length === 0
                  ? t('cde.no_documents_in_project', {
                      defaultValue: 'No documents in this project. Upload documents first.',
                    })
                  : t('cde.no_matching_documents', {
                      defaultValue: 'No matching documents',
                    })}
              </p>
            </div>
          ) : (
            filtered.map((doc) => {
              const isSelected = selected.some((d) => d.id === doc.id);
              return (
                <button
                  key={doc.id}
                  onClick={() => toggle(doc)}
                  className={clsx(
                    'flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-left transition-all mb-0.5',
                    isSelected
                      ? 'bg-oe-blue/5 ring-1 ring-oe-blue/20'
                      : 'hover:bg-surface-secondary',
                  )}
                >
                  <div
                    className={clsx(
                      'w-5 h-5 rounded border flex items-center justify-center shrink-0 transition-colors',
                      isSelected
                        ? 'bg-oe-blue border-oe-blue text-white'
                        : 'border-border',
                    )}
                  >
                    {isSelected && <Check size={12} />}
                  </div>
                  <File
                    size={16}
                    className={clsx(
                      'shrink-0',
                      isSelected ? 'text-oe-blue' : 'text-content-tertiary',
                    )}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{doc.name || doc.file_name}</p>
                    <p className="text-2xs text-content-quaternary">
                      {doc.category || t('cde.category_document', { defaultValue: 'Document' })}
                      {doc.file_size ? ` · ${formatSize(doc.file_size)}` : ''}
                    </p>
                  </div>
                </button>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-border shrink-0">
          <span className="text-xs text-content-tertiary">
            {filtered.length} {t('cde.documents_available', { defaultValue: 'documents available' })}
          </span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleLink}
              disabled={selected.length === 0 || linking}
            >
              <Link2 size={14} className="mr-1" />
              {linking
                ? t('cde.linking', { defaultValue: 'Linking...' })
                : `${t('cde.link_selected', { defaultValue: 'Link' })} ${selected.length} ${t('cde.documents', { defaultValue: 'Document(s)' })}`}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Container Row (expandable with revision history) ─────────────────── */

const ContainerRow = React.memo(function ContainerRow({
  container,
  userRole,
  onPromote,
  onLinkDocument,
  onShowHistory,
}: {
  container: CDEContainer;
  userRole: string | null;
  onPromote: (c: CDEContainer) => void;
  onLinkDocument: (c: CDEContainer) => void;
  onShowHistory: (c: CDEContainer) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const containerState = getContainerState(container);
  const containerDiscipline = getContainerDiscipline(container);
  const stateCfg = STATE_CONFIG[containerState] ?? STATE_CONFIG.wip;
  const disciplineCls =
    DISCIPLINE_COLORS[containerDiscipline] ?? DISCIPLINE_COLORS.other;

  // Fetch revisions on expand
  const { data: revisions = [], isLoading: revisionsLoading } = useQuery({
    queryKey: ['cde-revisions', container.id],
    queryFn: () => fetchContainerRevisions(container.id),
    enabled: expanded,
  });

  // Can promote only when there is a next state AND the current user's role
  // can actually pass the next gate (mirrors the backend gate roles). Showing
  // the button to editors/viewers who always get a 400 is a dead control.
  const hasNextGate = containerState !== 'archived';
  const canPromote = hasNextGate && canRoleCrossGate(userRole, containerState);
  const nextState = STATE_ORDER[STATE_ORDER.indexOf(containerState) + 1] as
    | CDEState
    | undefined;

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

        {/* Container Code */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-36 shrink-0 truncate">
          {container.container_code}
        </span>

        {/* Title + description */}
        <span className="flex-1 min-w-0">
          <span className="block text-sm text-content-primary truncate">
            {container.title}
          </span>
          {container.description && (
            <span className="block text-2xs text-content-tertiary truncate">
              {container.description}
            </span>
          )}
        </span>

        {/* Discipline badge */}
        <Badge variant="neutral" size="sm" className={clsx(disciplineCls, 'hidden md:inline-flex')}>
          {t(`cde.discipline_${containerDiscipline}`, {
            defaultValue: DISCIPLINE_LABELS[containerDiscipline] ?? containerDiscipline,
          })}
        </Badge>

        {/* CDE State badge */}
        <span title={t('cde.iso19650_states_tooltip', { defaultValue: 'ISO 19650 document states: WIP = Work in Progress (being authored), Shared = shared with team for review, Published = formally approved and issued, Archived = superseded or no longer current' })}>
          <Badge variant={stateCfg.variant} size="sm" className={stateCfg.cls}>
            {t(`cde.state_${containerState}`, { defaultValue: stateCfg.label })}
          </Badge>
        </span>

        {/* Suitability Code */}
        <span className="text-xs text-content-tertiary w-12 text-center shrink-0 hidden lg:block font-mono">
          {container.suitability_code || '-'}
        </span>

        {/* Revision count — exact once expanded (revisions fetched), else
            a presence indicator derived from current_revision_id. */}
        <span
          className="text-xs text-content-tertiary w-12 text-center shrink-0 tabular-nums hidden sm:block"
          title={t('cde.revision_count_tooltip', {
            defaultValue: 'Number of document revisions in this container',
          })}
        >
          {expanded
            ? revisions.length
            : container.current_revision_id
              ? '1+'
              : '0'}
        </span>

        {/* Classification */}
        <span className="text-xs text-content-tertiary w-28 truncate shrink-0 hidden lg:block">
          {container.classification_code || '-'}
        </span>
      </div>

      {/* Expanded detail: revision history */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Actions row */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Promote action */}
            {canPromote && nextState && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onPromote(container);
                }}
              >
                <ArrowRight size={14} className="mr-1" />
                {t('cde.action_promote', {
                  defaultValue: 'Promote to {{state}}',
                  state: t(`cde.state_${nextState}`, {
                    defaultValue: STATE_CONFIG[nextState].label,
                  }),
                })}
              </Button>
            )}
            {/* Link Document button */}
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onLinkDocument(container);
              }}
            >
              <Link2 size={14} className="mr-1" />
              {t('cde.link_document', { defaultValue: 'Link Document' })}
            </Button>
            {/* Send via Transmittal */}
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                navigate(`/transmittals?create=true&container_id=${container.id}`);
              }}
            >
              <Send size={13} className="mr-1" />
              {t('cde.send_transmittal', { defaultValue: 'Send via Transmittal' })}
            </Button>
            {/* Submit for approval — hands the container off into the
                Submittals review workflow with the create flow prefilled,
                closing the CDE -> Submittal -> Transmittal loop. */}
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                navigate(`/submittals?create=true&container_id=${container.id}`);
              }}
              title={t('cde.submit_for_approval_hint', {
                defaultValue: 'Raise a submittal for this container',
              })}
            >
              <FileCheck size={13} className="mr-1" />
              {t('cde.submit_for_approval', { defaultValue: 'Submit for approval' })}
            </Button>
            {/* History drawer */}
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onShowHistory(container);
              }}
              title={t('cde.view_history', { defaultValue: 'View state transition history' })}
            >
              {t('cde.view_history', { defaultValue: 'History' })}
            </Button>
            {/* Transmittal backlink badge — only renders when there are links */}
            <CDETransmittalsBadge containerId={container.id} />
          </div>

          {/* Revision history / Documents in container */}
          <div>
            <p className="text-xs text-content-tertiary mb-2 font-medium uppercase tracking-wide">
              {t('cde.label_revisions', { defaultValue: 'Revisions' })}
            </p>
            {revisionsLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 2 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-10 animate-pulse rounded bg-surface-tertiary"
                  />
                ))}
              </div>
            ) : revisions.length === 0 ? (
              <div className="px-4 py-3 bg-surface-secondary/30 rounded-lg">
                <p className="text-xs text-content-quaternary">
                  {t('cde.no_revisions_hint', { defaultValue: 'No revisions yet. Upload documents and link them to this container.' })}
                </p>
              </div>
            ) : (
              <div className="space-y-1">
                {revisions.map((rev) => (
                  <RevisionItem key={rev.id} revision={rev} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

    </div>
  );
});

function RevisionItem({ revision }: { revision: CDERevision }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-3 rounded-lg bg-surface-secondary p-2.5 text-sm">
      <span className="font-mono font-semibold text-content-secondary w-12 shrink-0">
        {revision.revision_code}
      </span>
      <DateDisplay value={revision.created_at} className="text-xs text-content-tertiary w-24 shrink-0" />
      <Badge variant="neutral" size="sm">
        {t(`cde.revision_status_${revision.status}`, { defaultValue: revision.status })}
      </Badge>
      {revision.file_name && (
        <span className="text-xs text-content-tertiary truncate">{revision.file_name}</span>
      )}
      {revision.change_summary && (
        <span className="text-xs text-content-tertiary truncate flex-1">
          {revision.change_summary}
        </span>
      )}
    </div>
  );
}

/* ── How-it-works flow + module integrations ───────────────────────────── */

/** A compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer of what a CDE is and how it connects: it is the agreed
 * single source of truth for documents, moving each revision through the ISO
 * 19650 states and out to review and distribution. Every connected module is a
 * link so the workflow is obvious.
 */
function HowCdeWorks() {
  const { t } = useTranslation();

  const steps: { icon: React.ReactNode; title: string; desc: string }[] = [
    {
      icon: <Database size={14} className="text-oe-blue" />,
      title: t('cde.flow_1_title', { defaultValue: 'Create container' }),
      desc: t('cde.flow_1_desc', {
        defaultValue: 'Register a document container with its code, discipline and suitability.',
      }),
    },
    {
      icon: <Link2 size={14} className="text-oe-blue" />,
      title: t('cde.flow_2_title', { defaultValue: 'Link documents' }),
      desc: t('cde.flow_2_desc', {
        defaultValue: "Attach file revisions from the project's Files to the container.",
      }),
    },
    {
      icon: <FileCheck size={14} className="text-oe-blue" />,
      title: t('cde.flow_3_title', { defaultValue: 'Share & approve' }),
      desc: t('cde.flow_3_desc', {
        defaultValue: 'Promote through WIP, Shared and Published; Published needs a signed approval.',
      }),
    },
    {
      icon: <Send size={14} className="text-oe-blue" />,
      title: t('cde.flow_4_title', { defaultValue: 'Distribute' }),
      desc: t('cde.flow_4_desc', {
        defaultValue: 'Issue a container as a transmittal or raise a submittal for review.',
      }),
    },
    {
      icon: <Archive size={14} className="text-oe-blue" />,
      title: t('cde.flow_5_title', { defaultValue: 'Archive' }),
      desc: t('cde.flow_5_desc', {
        defaultValue: 'Supersede old revisions so only current documents stay in use.',
      }),
    },
  ];

  return (
    <Card padding="md">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <Network size={15} className="text-oe-blue" />
        {t('cde.flow_title', { defaultValue: 'How the CDE fits together' })}
      </h2>
      <p className="mt-1 text-xs text-content-tertiary">
        {t('cde.flow_intro', {
          defaultValue:
            'A common data environment is the agreed single source of truth for project documents. Files are organised into ISO 19650 containers, moved through the review states, and issued to the team, so everyone always works off the right version.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
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
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('cde.flow_connects', { defaultValue: 'Connects with:' })}
          </span>{' '}
          <ModLink to="/files">
            {t('cde.mod_files', { defaultValue: 'Files' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/submittals">
            {t('cde.mod_submittals', { defaultValue: 'Submittals' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/transmittals">
            {t('cde.mod_transmittals', { defaultValue: 'Transmittals' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/rfi">{t('cde.mod_rfi', { defaultValue: 'RFIs' })}</ModLink>
        </span>
      </div>
    </Card>
  );
}

/* ── Functional roles (ISO 19650) ──────────────────────────────────────── */

/** Accent per functional role, following the workflow (author -> reviewer ->
 *  approver, viewer throughout). Initial-badge colours, no extra icon imports. */
const ROLE_ACCENT: Record<string, string> = {
  author: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  reviewer: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  approver: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  viewer: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

/**
 * The four ISO 19650 functional roles (Author / Reviewer / Approver / Viewer)
 * and what each one does at every CDE state. Agreeing these responsibilities
 * once, up front, is what keeps a CDE a live source of truth instead of a dead
 * document dump - so the model is shown here as reference, driven by
 * GET /v1/cde/functional-roles. Static reference data (no project needed).
 */
function CdeFunctionalRoles() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['cde-functional-roles'],
    queryFn: fetchFunctionalRoles,
    staleTime: Infinity,
  });
  if (!data) return null;
  const { roles, states, matrix } = data;

  return (
    <Card padding="md">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <Users size={15} className="text-oe-blue" />
        {t('cde.roles_title', { defaultValue: 'Roles and responsibilities' })}
      </h2>
      <p className="mt-1 text-xs text-content-tertiary">
        {t('cde.roles_intro', {
          defaultValue:
            'ISO 19650 organises information work around four functional roles. Agree who does what once and reuse it on every discipline - the same person can author their own package and only view another.',
        })}
      </p>

      {/* Role cards */}
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {roles.map((role) => {
          const name = t(`cde.role_${role.key}_name`, { defaultValue: role.name });
          return (
            <div
              key={role.key}
              className="rounded-lg border border-border-light bg-surface-secondary/40 p-3"
            >
              <div className="flex items-center gap-2">
                <span
                  className={clsx(
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-2xs font-bold',
                    ROLE_ACCENT[role.key] ?? ROLE_ACCENT.viewer,
                  )}
                  aria-hidden="true"
                >
                  {name.charAt(0)}
                </span>
                <span className="text-xs font-semibold text-content-primary">{name}</span>
                {role.gate && (
                  <Badge variant="blue" size="sm" className="ml-auto">
                    {t('cde.roles_gate', { defaultValue: 'Gate {{gate}}', gate: role.gate })}
                  </Badge>
                )}
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">
                {t(`cde.role_${role.key}_summary`, { defaultValue: role.summary })}
              </p>
            </div>
          );
        })}
      </div>

      {/* Responsibility matrix: what each role does in each state */}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[34rem] border-collapse text-2xs">
          <thead>
            <tr className="text-content-tertiary">
              <th className="px-2 py-1.5 text-left font-medium uppercase tracking-wide">
                {t('cde.roles_matrix_state', { defaultValue: 'State' })}
              </th>
              {roles.map((role) => (
                <th key={role.key} className="px-2 py-1.5 text-left font-medium">
                  {t(`cde.role_${role.key}_name`, { defaultValue: role.name })}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {states.map((state) => {
              const cfg = STATE_CONFIG[state] ?? STATE_CONFIG.wip;
              return (
                <tr key={state} className="border-t border-border-light">
                  <td className="px-2 py-1.5">
                    <Badge variant={cfg.variant} size="sm" className={cfg.cls}>
                      {t(`cde.state_${state}`, { defaultValue: cfg.label })}
                    </Badge>
                  </td>
                  {roles.map((role) => {
                    const action = matrix[state]?.[role.key] ?? '-';
                    const idle = action === '-';
                    return (
                      <td
                        key={role.key}
                        className={clsx(
                          'px-2 py-1.5',
                          idle ? 'text-content-quaternary' : 'text-content-secondary',
                        )}
                      >
                        {idle ? '·' : action}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ── Go-live readiness (ISO 19650) ─────────────────────────────────────── */

type ReadinessLevel = 'not_started' | 'forming' | 'operational' | 'mature';

/** Level -> badge tone, progress-bar fill and default English label. Keeps the
 *  scorecard's colour language consistent with the rest of the module (neutral
 *  -> amber -> blue -> green mirrors the WIP -> Shared -> Published lifecycle). */
const READINESS_LEVEL: Record<
  ReadinessLevel,
  { variant: 'neutral' | 'blue' | 'success' | 'warning'; bar: string; label: string }
> = {
  not_started: { variant: 'neutral', bar: 'bg-gray-300 dark:bg-gray-600', label: 'Not started' },
  forming: { variant: 'warning', bar: 'bg-amber-400', label: 'Forming' },
  operational: { variant: 'blue', bar: 'bg-oe-blue', label: 'Operational' },
  mature: { variant: 'success', bar: 'bg-green-500', label: 'Mature' },
};

/**
 * A project's CDE go-live readiness: how far the team has got from "switched on"
 * to "actually running the ISO 19650 workflow you can trust". Standing a CDE up
 * is more than turning it on - containers have to be created, named and
 * classified, work has to move out of WIP into Shared and on to Published, gate
 * crossings have to be signed and revisions versioned. The score, level and the
 * next few things to fix come straight from the project's real container and
 * transition state via GET /v1/cde/readiness, so this is a live checklist, not
 * a brochure. Only renders once a project is in context.
 */
function CdeReadiness({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['cde-readiness', projectId],
    queryFn: () => fetchCDEReadiness(projectId),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  if (!projectId) return null;

  if (isLoading || !data) {
    return (
      <Card padding="md">
        <div className="h-5 w-48 animate-pulse rounded bg-surface-secondary" />
        <div className="mt-3 h-2 w-full animate-pulse rounded-full bg-surface-secondary" />
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-8 animate-pulse rounded-lg bg-surface-secondary" />
          ))}
        </div>
      </Card>
    );
  }

  const level = (data.level as ReadinessLevel) ?? 'not_started';
  const cfg = READINESS_LEVEL[level] ?? READINESS_LEVEL.not_started;
  const done = data.signals.filter((s) => s.done).length;

  return (
    <Card padding="md">
      {/* Header + score */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
            <Gauge size={15} className="text-oe-blue" />
            {t('cde.readiness_title', { defaultValue: 'Go-live readiness' })}
          </h2>
          <p className="mt-1 max-w-xl text-xs text-content-tertiary">
            {t('cde.readiness_intro', {
              defaultValue:
                'Standing up a CDE is more than switching it on. This scores how far this project has actually run the ISO 19650 workflow - naming, classification, the move through Shared and Published, signed gates and versioned revisions - and points at the next few things to fix.',
            })}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <div className="text-right">
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-bold tabular-nums leading-none text-content-primary">
                {data.score}
              </span>
              <span className="text-sm font-medium text-content-tertiary">/100</span>
            </div>
            <div className="mt-1 flex items-center justify-end gap-1.5">
              <Badge variant={cfg.variant} size="sm">
                {t(`cde.readiness_level_${level}`, { defaultValue: cfg.label })}
              </Badge>
            </div>
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mt-3">
        <div
          className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary"
          role="progressbar"
          aria-valuenow={data.score}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={t('cde.readiness_title', { defaultValue: 'Go-live readiness' })}
        >
          <div
            className={clsx('h-full rounded-full transition-[width] duration-500 ease-oe', cfg.bar)}
            style={{ width: `${Math.max(2, data.score)}%` }}
          />
        </div>
        <div className="mt-1.5 flex items-center justify-between text-2xs text-content-tertiary">
          <span>
            {t('cde.readiness_milestones_met', {
              defaultValue: '{{done}} of {{total}} milestones met',
              done,
              total: data.signals.length,
            })}
          </span>
          <span className="tabular-nums">
            {t('cde.readiness_across_containers', {
              defaultValue: '{{count}} container(s)',
              count: data.total_containers,
            })}
          </span>
        </div>
      </div>

      {/* Signal checklist */}
      <ul className="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {data.signals.map((s) => {
          const label = t(`cde.readiness_signal_${s.key}`, { defaultValue: s.label });
          const hint = t(`cde.readiness_hint_${s.key}`, { defaultValue: s.hint });
          return (
            <li
              key={s.key}
              className={clsx(
                'flex items-center gap-2 rounded-lg border px-2.5 py-1.5',
                s.done
                  ? 'border-green-200 bg-green-50/60 dark:border-green-900/40 dark:bg-green-900/10'
                  : 'border-border-light bg-surface-secondary/40',
              )}
              title={hint}
            >
              <span
                className={clsx(
                  'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                  s.done
                    ? 'border-green-500 bg-green-500 text-white'
                    : 'border-border text-transparent',
                )}
                aria-hidden="true"
              >
                {s.done && <Check size={11} strokeWidth={3} />}
              </span>
              <span
                className={clsx(
                  'flex-1 truncate text-xs',
                  s.done ? 'text-content-secondary' : 'text-content-tertiary',
                )}
              >
                {label}
              </span>
            </li>
          );
        })}
      </ul>

      {/* Next actions nudge */}
      {data.next_actions.length > 0 && (
        <div className="mt-3 flex flex-col gap-1 border-t border-border-light pt-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2">
          <span className="text-2xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('cde.readiness_next', { defaultValue: 'Next' })}
          </span>
          {data.next_actions.map((a, i) => (
            <Fragment key={a.key}>
              {i > 0 && <span className="hidden text-content-quaternary sm:inline">·</span>}
              <span className="text-2xs text-content-tertiary" title={t(`cde.readiness_hint_${a.key}`, { defaultValue: a.hint })}>
                {t(`cde.readiness_signal_${a.key}`, { defaultValue: a.label })}
              </span>
            </Fragment>
          ))}
        </div>
      )}
    </Card>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function CDEPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  // Authoritative role drives which container actions are offered (the
  // backend gates promotions by role — see canRoleCrossGate).
  const userRole = useAuthStore((s) => s.userRole);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [stateFilter, setStateFilter] = useState<CDEState | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const {
    data: containers = [],
    isLoading,
    isError: containersError,
    error: containersErrorValue,
    refetch: refetchContainers,
  } = useQuery({
    queryKey: ['cde-containers', projectId, stateFilter],
    queryFn: () =>
      fetchCDEContainers({
        project_id: projectId,
        state: stateFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Aggregate stats — drives the summary cards. Keyed by project so the
  // ['cde-stats'] invalidation fired after create/promote actually refreshes
  // a live query (it previously invalidated a cache that did not exist).
  const { data: stats } = useQuery({
    queryKey: ['cde-stats', projectId],
    queryFn: () => fetchCDEStats(projectId),
    enabled: !!projectId,
  });

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return containers;
    const q = searchQuery.toLowerCase();
    return containers.filter(
      (c) =>
        c.container_code.toLowerCase().includes(q) ||
        c.title.toLowerCase().includes(q) ||
        (c.classification_code && c.classification_code.toLowerCase().includes(q)),
    );
  }, [containers, searchQuery]);

  // State counts for filter tabs
  const stateCounts = useMemo(() => {
    const counts: Record<string, number> = { all: containers.length };
    for (const s of STATE_ORDER) {
      counts[s] = containers.filter((c) => getContainerState(c) === s).length;
    }
    return counts;
  }, [containers]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['cde-containers'] });
    qc.invalidateQueries({ queryKey: ['cde-revisions'] });
    qc.invalidateQueries({ queryKey: ['cde-stats'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationKey: ['cde-containers', 'create'],
    mutationFn: (data: CreateCDEContainerPayload) => createCDEContainer(data),
    onSuccess: (created) => {
      // Close + notify FIRST so user always sees feedback even if the
      // background list refetch later fails. Previously the success handler
      // awaited invalidateQueries — a refetch rejection (stale JWT, transient
      // network) left the modal open with no new row and no error toast,
      // producing the "nothing happens" symptom.
      setShowCreateModal(false);

      // Flip the active state-filter tab to the created container's own
      // state so it's always visible post-create. Previous fix only
      // flipped when ``stateFilter`` was non-empty — but a stale
      // in-flight fetch plus the backend's 15-18 s create latency could
      // leave the list showing the pre-create snapshot for a beat, and
      // the user reads that as "ничего не создаётся". Reset to empty
      // ("All") so the new row is visible regardless of which tab the
      // user was on.
      setStateFilter('');

      addToast({
        type: 'success',
        title: t('cde.created', { defaultValue: 'Container created' }),
        message: created?.container_code
          ? t('cde.created_msg', {
              defaultValue: '{{code}} - {{title}}',
              code: created.container_code,
              title: created.title,
            })
          : undefined,
      });

      // Optimistically inject the new container into every cached
      // containers list for this project so the row appears instantly —
      // invalidateQueries below still triggers the authoritative refetch,
      // but on a slow CDE create (18 s backend) the user was staring at
      // an unchanged list long enough to assume nothing happened.
      if (created && projectId) {
        qc.setQueriesData<CDEContainer[]>(
          { queryKey: ['cde-containers', projectId] },
          (prev) => {
            if (!prev) return prev;
            if (prev.some((c) => c.id === created.id)) return prev;
            return [created, ...prev];
          },
        );
      }

      // Fire-and-forget invalidation. A failing refetch cannot hide the
      // successful write — the optimistic insert above keeps the row
      // visible until the refetch completes.
      qc.invalidateQueries({ queryKey: ['cde-containers'] }).catch(() => {});
      qc.invalidateQueries({ queryKey: ['cde-revisions'] }).catch(() => {});
      qc.invalidateQueries({ queryKey: ['cde-stats'] }).catch(() => {});
    },
    onError: (e: Error) => {
      // Surface the actual server/client error rather than a generic "Error"
      // with an empty message. Always console.error so users reporting the
      // problem can share the payload without a DEV rebuild.
      // eslint-disable-next-line no-console
      console.error('[CDE] Create container failed:', e, (e as { body?: unknown }).body);
      const detail =
        e.message?.trim() ||
        t('cde.create_failed_generic', {
          defaultValue:
            'Container could not be created. Check that a project is selected and the code/title are unique.',
        });
      addToast({
        type: 'error',
        title: t('cde.create_failed', { defaultValue: 'Failed to create container' }),
        message: detail,
      });
    },
  });

  const transitionMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: TransitionPayload }) =>
      transitionContainer(id, payload),
    onSuccess: () => {
      invalidateAll();
      qc.invalidateQueries({ queryKey: ['cde-history'] });
      addToast({
        type: 'success',
        title: t('cde.promoted', { defaultValue: 'Container promoted' }),
      });
    },
    onError: (e: Error) => {
      // Don't forward the backend's raw English "Insufficient role: ..." —
      // surface a translated, user-facing message instead. Other backend
      // errors (e.g. already-in-state) are passed through as a fallback.
      const raw = e.message?.trim() ?? '';
      const isRoleGate = /insufficient role/i.test(raw);
      addToast({
        type: 'error',
        title: t('cde.promote_failed', { defaultValue: 'Could not promote container' }),
        message: isRoleGate
          ? t('cde.promote_insufficient_role', {
              defaultValue:
                'Your role cannot promote this container to the next state. A project manager or admin is required.',
            })
          : raw ||
            t('cde.promote_failed_generic', {
              defaultValue: 'The state transition could not be completed.',
            }),
      });
    },
  });

  const handleCreateSubmit = useCallback(
    (formData: CDEFormData) => {
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: t('cde.select_project_first', { defaultValue: 'Please select a project first' }),
        });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        container_code: formData.container_code,
        title: formData.title,
        discipline_code: formData.discipline,
        suitability_code: formData.suitability_code || undefined,
        classification_code: formData.classification || undefined,
        cde_state: formData.cde_state,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const { confirm, ...confirmProps } = useConfirm();
  const [linkTarget, setLinkTarget] = useState<CDEContainer | null>(null);
  // Gate B approval modal target (SHARED -> PUBLISHED requires signature).
  const [approvalTarget, setApprovalTarget] = useState<CDEContainer | null>(null);
  // Right-drawer audit log target.
  const [historyTarget, setHistoryTarget] = useState<CDEContainer | null>(null);

  const handleLinkDocument = useCallback((container: CDEContainer) => {
    setLinkTarget(container);
  }, []);

  const handleShowHistory = useCallback((container: CDEContainer) => {
    setHistoryTarget(container);
  }, []);

  const handlePromote = useCallback(
    async (container: CDEContainer) => {
      const currentState = getContainerState(container);
      const nextIdx = STATE_ORDER.indexOf(currentState) + 1;
      const nextState = STATE_ORDER[nextIdx];
      if (!nextState) return;

      // Gate B (SHARED -> PUBLISHED) requires an approver signature — open
      // the dedicated modal instead of a simple confirm.
      const isGateB = currentState === 'shared' && nextState === 'published';
      if (isGateB) {
        setApprovalTarget(container);
        return;
      }

      const ok = await confirm({
        title: t('cde.confirm_promote_title', { defaultValue: 'Promote container?' }),
        message: t('cde.confirm_promote_msg', {
          defaultValue: 'This will move the container to the "{{state}}" state.',
          state: nextState,
        }),
        confirmLabel: t('cde.action_promote', { defaultValue: 'Promote' }),
        variant: 'warning',
      });
      if (ok) {
        transitionMut.mutate({
          id: container.id,
          payload: { target_state: nextState },
        });
      }
    },
    [transitionMut, confirm, t],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          ...(projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('cde.title', { defaultValue: 'Common Data Environment' }) },
        ]}
      />

      {/* Header */}
      <PageHeader
        srTitle={t('cde.title', { defaultValue: 'Common Data Environment' })}
        subtitle={t('cde.subtitle', {
          defaultValue:
            'Organise project documents into ISO 19650 containers and move them through WIP, Shared, Published and Archived.',
        })}
        actions={
          <>
          <ModuleGuideButton content={cdeGuide} />
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              if (!projectId) {
                addToast({
                  type: 'info',
                  title: t('cde.select_project_first_title', {
                    defaultValue: 'Select a project first',
                  }),
                  message: t('cde.select_project_first', {
                    defaultValue:
                      'Pick a project from the top bar, then click New Container.',
                  }),
                });
                return;
              }
              setShowCreateModal(true);
            }}
            title={
              !projectId
                ? t('cde.select_project_first', {
                    defaultValue: 'Please select a project first',
                  })
                : undefined
            }
            className="shrink-0 whitespace-nowrap"
          >
            <Plus size={14} className="mr-1 shrink-0" />
            <span>{t('cde.new_container', { defaultValue: 'New Container' })}</span>
          </Button>
          </>
        }
      />

      {/* Info card (canonical, pain-named copy from MODULE_INTRO_COPY) */}
      <DismissibleInfo
        storageKey="cde"
        title={t('cde.intro_title', {
          defaultValue: 'One agreed source of truth for documents',
        })}
        more={t('cde.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('cde.intro_more')} /> : undefined}
        links={[
          {
            label: t('nav.project_files', { defaultValue: 'Files' }),
            onClick: () => navigate('/files'),
          },
          {
            label: t('submittals.title', { defaultValue: 'Submittals' }),
            onClick: () => navigate('/submittals'),
          },
          {
            label: t('files.transmittals.open_log', { defaultValue: 'Transmittal log' }),
            onClick: () => navigate('/files/transmittals'),
          },
        ]}
      >
        {t('cde.intro_body', {
          defaultValue:
            'Organise project documents into ISO 19650 containers and move each revision through Work in Progress, Shared, Published and Archived, so everyone works off the right version. Upload first, organise here, then distribute. Promotions are gated by your role and the history is kept per container.',
        })}
      </DismissibleInfo>

      <HowCdeWorks />

      <CdeFunctionalRoles />

      {/* Go-live readiness scorecard — the project's live ISO 19650 status and
          the next few things to fix, so a CDE never quietly becomes a dead
          document dump. Renders whenever a project is in context. */}
      {projectId && <CdeReadiness projectId={projectId} />}

      {/* Summary cards — fed by the /cde/stats aggregate endpoint. Shows the
          full ISO 19650 lifecycle (Total + every state) so users can see how
          many containers sit in WIP, Shared, Published and Archived at a
          glance. */}
      {projectId && stats && stats.total > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('cde.stat_total', { defaultValue: 'Total containers' })}
            </span>
            <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
              {stats.total}
            </span>
          </div>
          <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('cde.state_wip', { defaultValue: 'WIP' })}
            </span>
            <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
              {stats.by_state?.wip ?? 0}
            </span>
          </div>
          <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('cde.state_shared', { defaultValue: 'Shared' })}
            </span>
            <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
              {stats.by_state?.shared ?? 0}
            </span>
          </div>
          <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('cde.state_published', { defaultValue: 'Published' })}
            </span>
            <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
              {stats.by_state?.published ?? 0}
            </span>
          </div>
          <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('cde.state_archived', { defaultValue: 'Archived' })}
            </span>
            <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
              {stats.by_state?.archived ?? 0}
            </span>
          </div>
        </div>
      )}

      {/* State filter tabs */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1" title={t('cde.iso19650_states_tooltip', { defaultValue: 'ISO 19650 document states: WIP = Work in Progress (being authored), Shared = shared with team for review, Published = formally approved and issued, Archived = superseded or no longer current' })}>
        {[
          {
            key: '' as CDEState | '',
            label: t('cde.tab_all', { defaultValue: 'All' }),
            count: stateCounts.all,
          },
          ...STATE_ORDER.map((s) => ({
            key: s as CDEState | '',
            label: t(`cde.state_${s}`, { defaultValue: STATE_CONFIG[s].label }),
            count: stateCounts[s] ?? 0,
          })),
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setStateFilter(tab.key)}
            className={clsx(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap',
              stateFilter === tab.key
                ? 'bg-oe-blue-subtle text-oe-blue-text'
                : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
            )}
          >
            {tab.label}
            <span
              className={clsx(
                'text-2xs tabular-nums px-1.5 py-0.5 rounded-full',
                stateFilter === tab.key
                  ? 'bg-oe-blue/10 text-oe-blue'
                  : 'bg-surface-tertiary text-content-tertiary',
              )}
            >
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
        />
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t('cde.search_placeholder', {
            defaultValue: 'Search containers...',
          })}
          className={inputCls + ' pl-9'}
        />
      </div>

      {/* Table */}
      <div>
        {!projectId ? (
          <RequiresProject>{null}</RequiresProject>
        ) : isLoading ? (
          <SkeletonTable rows={5} columns={5} />
        ) : containersError ? (
          <RecoveryCard error={containersErrorValue} onRetry={() => refetchContainers()} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Database size={28} strokeWidth={1.5} />}
            title={
              searchQuery || stateFilter
                ? t('cde.no_results', { defaultValue: 'No matching containers' })
                : t('cde.no_containers', { defaultValue: 'No containers yet' })
            }
            description={
              searchQuery || stateFilter
                ? t('cde.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('cde.no_containers_hint', {
                    defaultValue:
                      'Create your first information container following ISO 19650',
                  })
            }
            action={
              !searchQuery && !stateFilter
                ? {
                    label: t('cde.new_container', { defaultValue: 'New Container' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('cde.showing_count', {
                defaultValue: '{{count}} containers',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {/* Table header */}
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
                <span className="w-5" />
                <span className="w-36">
                  {t('cde.col_code', { defaultValue: 'Code' })}
                </span>
                <span className="flex-1">
                  {t('cde.col_title', { defaultValue: 'Title' })}
                </span>
                <span className="w-24 hidden md:block">
                  {t('cde.col_discipline', { defaultValue: 'Discipline' })}
                </span>
                <span className="w-20 text-center">
                  {t('cde.col_state', { defaultValue: 'State' })}
                </span>
                <span className="w-12 text-center hidden lg:block">
                  {t('cde.col_suitability', { defaultValue: 'Suit.' })}
                </span>
                <span className="w-12 text-center hidden sm:block">
                  {t('cde.col_revision', { defaultValue: 'Rev' })}
                </span>
                <span className="w-28 hidden lg:block">
                  {t('cde.col_classification', { defaultValue: 'Classification' })}
                </span>
              </div>

              {/* Rows */}
              {filtered.map((c) => (
                <ContainerRow
                  key={c.id}
                  container={c}
                  userRole={userRole}
                  onPromote={handlePromote}
                  onLinkDocument={handleLinkDocument}
                  onShowHistory={handleShowHistory}
                />
              ))}
            </Card>
          </>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <CreateCDEModal
          onClose={() => {
            createMut.reset();
            setShowCreateModal(false);
          }}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
          errorMessage={createMut.error?.message ?? null}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />

      {/* Link Document Modal — rendered at page level for correct z-index */}
      {linkTarget && projectId && (
        <LinkDocumentModal
          container={linkTarget}
          projectId={projectId}
          onClose={() => setLinkTarget(null)}
          onLinked={() => {
            qc.invalidateQueries({ queryKey: ['cde-revisions', linkTarget.id] });
            setLinkTarget(null);
          }}
        />
      )}

      {/* Gate B approval signature modal */}
      {approvalTarget && (
        <ApprovalSignatureModal
          container={approvalTarget}
          onClose={() => setApprovalTarget(null)}
          onSubmit={(payload) => {
            transitionMut.mutate(
              { id: approvalTarget.id, payload },
              { onSuccess: () => setApprovalTarget(null) },
            );
          }}
          isPending={transitionMut.isPending}
        />
      )}

      {/* State transition history drawer */}
      {historyTarget && (
        <CDEHistoryDrawer
          containerId={historyTarget.id}
          containerCode={historyTarget.container_code}
          onClose={() => setHistoryTarget(null)}
        />
      )}
    </div>
  );
}
