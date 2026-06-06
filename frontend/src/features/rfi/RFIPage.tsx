import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router-dom';
import clsx from 'clsx';
import {
  HelpCircle,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  DollarSign,
  Clock,
  FileText,
  Download,
  Loader2,
  CalendarClock,
  Paperclip,
  UploadCloud,
  Check,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  ConfirmDialog,
  DismissibleInfo,
  IntroRichText,
  RecoveryCard,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { UserSearchInput } from '@/shared/ui/UserSearchInput';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useCreateShortcut } from '@/shared/hooks/useCreateShortcut';
import { apiGet, apiPost, triggerDownload, extractErrorMessageFromBody } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchRFIs,
  fetchRFIStats,
  createRFI,
  respondToRFI,
  closeRFI,
  RFI_DISCIPLINES,
  type RFI,
  type RFIStatus,
  type RFIPriority,
  type CreateRFIPayload,
  type RespondRFIPayload,
} from './api';
import { ApprovalTargetBadge } from '@/features/approval-routes';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

export const STATUS_CONFIG: Record<
  RFIStatus,
  { variant: 'neutral' | 'blue' | 'success' | 'error' | 'warning'; cls: string }
> = {
  draft: { variant: 'neutral', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  open: { variant: 'blue', cls: '' },
  answered: { variant: 'success', cls: '' },
  closed: { variant: 'neutral', cls: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300' },
  void: { variant: 'error', cls: '' },
};

/**
 * Priority → coloured-dot class. Rendered at the very left of every RFI
 * row so the operator can scan urgency without reading the status chip.
 *
 *   low      → gray
 *   normal   → blue
 *   high     → amber
 *   critical → red
 */
export const PRIORITY_DOT: Record<RFIPriority, string> = {
  low: 'bg-gray-400',
  normal: 'bg-blue-500',
  high: 'bg-amber-500',
  critical: 'bg-red-500',
};

/** Ordered list — keeps the chip row and the filter dropdown in sync. */
export const PRIORITY_VALUES: readonly RFIPriority[] = [
  'low',
  'normal',
  'high',
  'critical',
] as const;

/**
 * Decode the ``sub`` claim from the JWT so we can compute the
 * ball-in-court "side" badge ("With you" vs "With them") and the
 * "Awaiting my response" quick-filter chip. Same shape as the helper in
 * ChangeOrdersPage / file-manager hooks — kept local so the RFI module
 * does not couple to another feature's internals.
 */
function decodeUserIdFromToken(token: string | null): string | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json = JSON.parse(atob(padded)) as { sub?: string };
    return typeof json.sub === 'string' ? json.sub : null;
  } catch {
    return null;
  }
}

/**
 * Ball-in-court "side" — which party currently owes the next move.
 *
 *   - ``you``     — the RFI is in the current viewer's court (assigned_to /
 *                   ball_in_court matches the viewer's user id) and still
 *                   in an actionable status (draft/open).
 *   - ``them``    — someone else owes the response.
 *   - ``answered``— a response has landed but the RFI is not yet closed.
 *   - ``closed``  — terminal (closed / void).
 *
 * This is the headline collaboration signal — contractors scanning a
 * project dashboard need to spot "what's on my plate" in one glance.
 */
export type BallInCourtSide = 'you' | 'them' | 'answered' | 'closed';

export function ballInCourtSide(rfi: RFI, viewerId: string | null): BallInCourtSide {
  if (rfi.status === 'closed' || rfi.status === 'void') return 'closed';
  if (rfi.status === 'answered') return 'answered';
  // draft / open — somebody owes a response.
  if (!viewerId) return 'them';
  const court = rfi.ball_in_court || rfi.assigned_to;
  if (court && court === viewerId) return 'you';
  return 'them';
}

/** Visual config for the ball-in-court badge. */
export const BIC_SIDE_CFG: Record<
  BallInCourtSide,
  { cls: string; key: string; fallback: string }
> = {
  you: {
    cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 border border-amber-200 dark:border-amber-800',
    key: 'rfi.bic_with_you',
    fallback: 'With you',
  },
  them: {
    cls: 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border border-blue-200 dark:border-blue-800',
    key: 'rfi.bic_with_them',
    fallback: 'With them',
  },
  answered: {
    cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800',
    key: 'rfi.bic_answered',
    fallback: 'Answered',
  },
  closed: {
    cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 border border-border-light',
    key: 'rfi.bic_closed',
    fallback: 'Closed',
  },
};

/**
 * Calendar-days elapsed since the response_due_date. Positive = overdue,
 * negative = still has time, ``null`` if no due date is set.
 *
 * Calendar days (not business days) — matches the days_open counter the
 * row already shows so the operator can compare them apples-to-apples.
 */
export function daysOverdue(responseDueDate: string | null): number | null {
  if (!responseDueDate) return null;
  const due = new Date(responseDueDate);
  if (Number.isNaN(due.getTime())) return null;
  const now = new Date();
  // Round to midnight on both sides so a 4 PM due date doesn't read as
  // "1 day overdue" the moment the clock crosses midnight.
  const midnight = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.floor((midnight(now) - midnight(due)) / 86_400_000);
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Helpers ───────────────────────────────────────────────────────────── */

function daysOpen(createdAt: string, closedAt: string | null): number {
  const start = new Date(createdAt);
  const end = closedAt ? new Date(closedAt) : new Date();
  return Math.max(0, Math.floor((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)));
}

/* ── Create RFI Modal ──────────────────────────────────────────────────── */

interface RFIFormData {
  subject: string;
  question: string;
  ball_in_court: string;
  ball_in_court_name: string;
  assigned_to: string;
  assigned_to_name: string;
  due_date: string;
  cost_impact: boolean;
  cost_impact_value: string;
  schedule_impact: boolean;
  schedule_impact_days: string;
  priority: RFIPriority;
  /** Empty string = unset. Picker offers {@link RFI_DISCIPLINES}. */
  discipline: string;
  /**
   * Document UUIDs the user has either picked from the existing-documents
   * list-modal or just uploaded via the inline dropzone.
   */
  linked_drawing_ids: string[];
}

const EMPTY_FORM: RFIFormData = {
  subject: '',
  question: '',
  ball_in_court: '',
  ball_in_court_name: '',
  assigned_to: '',
  assigned_to_name: '',
  due_date: '',
  cost_impact: false,
  cost_impact_value: '',
  schedule_impact: false,
  schedule_impact_days: '',
  priority: 'normal',
  discipline: '',
  linked_drawing_ids: [],
};

/* ── Document picker types ─────────────────────────────────────────────── */

/**
 * Minimal shape of a document row we need to render the picker / chips.
 * Mirrors the relevant subset of the documents module's list response —
 * kept local so the RFI module does not couple to the documents module's
 * full API.
 */
interface DocumentPickerRow {
  id: string;
  filename: string;
  category: string;
  size_bytes: number;
}

interface DocumentsApiRow {
  id: string;
  filename?: string;
  name?: string;
  category?: string;
  size_bytes?: number;
}

function normalizeDocRow(raw: DocumentsApiRow): DocumentPickerRow {
  return {
    id: raw.id,
    filename: raw.filename ?? raw.name ?? '',
    category: raw.category ?? 'other',
    size_bytes: typeof raw.size_bytes === 'number' ? raw.size_bytes : 0,
  };
}

/* ── Document Picker Modal ─────────────────────────────────────────────── */

function DocumentPickerModal({
  documents,
  isLoading,
  selected,
  onClose,
  onApply,
}: {
  documents: DocumentPickerRow[];
  isLoading: boolean;
  selected: string[];
  onClose: () => void;
  onApply: (ids: string[]) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<Set<string>>(() => new Set(selected));

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return documents;
    return documents.filter(
      (d) =>
        d.filename.toLowerCase().includes(q) || d.category.toLowerCase().includes(q),
    );
  }, [documents, query]);

  const togglePick = (id: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[80vh] flex flex-col"
        role="dialog"
        aria-modal="true"
        aria-label={t('rfi.attach_drawings', { defaultValue: 'Attach drawings' })}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('rfi.attach_drawings', { defaultValue: 'Attach drawings' })}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={14} />
          </button>
        </div>

        <div className="px-5 py-3 border-b border-border-light">
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('rfi.doc_search_placeholder', {
                defaultValue: 'Search drawings & documents...',
              })}
              aria-label={t('rfi.doc_search_placeholder', {
                defaultValue: 'Search drawings & documents...',
              })}
              className={`${inputCls} pl-9`}
              autoFocus
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {isLoading ? (
            <SkeletonTable rows={6} columns={3} className="border-0 rounded-none" />
          ) : filtered.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-content-tertiary">
              {documents.length === 0
                ? t('rfi.no_docs_yet', {
                    defaultValue: 'This project has no documents yet.',
                  })
                : t('rfi.no_doc_matches', {
                    defaultValue: 'No documents match your search.',
                  })}
            </p>
          ) : (
            <ul className="divide-y divide-border-light">
              {filtered.map((d) => {
                const isPicked = picked.has(d.id);
                return (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => togglePick(d.id)}
                      className={clsx(
                        'flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-secondary transition-colors',
                        isPicked && 'bg-oe-blue/5',
                      )}
                      aria-pressed={isPicked}
                    >
                      <span
                        className={clsx(
                          'flex h-5 w-5 items-center justify-center rounded border shrink-0',
                          isPicked
                            ? 'border-oe-blue bg-oe-blue text-white'
                            : 'border-border bg-surface-primary',
                        )}
                      >
                        {isPicked && <Check size={12} strokeWidth={3} />}
                      </span>
                      <FileText size={14} className="text-content-tertiary shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-content-primary truncate">
                          {d.filename || '—'}
                        </p>
                        <p className="text-xs text-content-tertiary truncate">
                          {d.category}
                        </p>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 px-5 py-3 border-t border-border-light">
          <span className="text-xs text-content-tertiary">
            {t('rfi.n_selected', {
              defaultValue: '{{count}} selected',
              count: picked.size,
            })}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => onApply(Array.from(picked))}
            >
              {t('rfi.apply_selection', { defaultValue: 'Apply' })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CreateRFIModal({
  onClose,
  onSubmit,
  isPending,
  projectName,
  projectId,
}: {
  onClose: () => void;
  onSubmit: (data: RFIFormData) => void;
  isPending: boolean;
  projectName?: string;
  projectId: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<RFIFormData>(EMPTY_FORM);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showDocPicker, setShowDocPicker] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadInFlight, setUploadInFlight] = useState(0);
  const dropFileInputRef = useRef<HTMLInputElement>(null);

  /**
   * Document catalogue for the project — used both by the picker modal
   * and to resolve filename chips for whatever the user has already
   * attached. Fetched lazily so the create modal does not pay the cost
   * unless the user opens the dialog.
   */
  const { data: documents = [], isLoading: docsLoading } = useQuery({
    queryKey: ['rfi-doc-picker', projectId],
    queryFn: async () => {
      const params = new URLSearchParams({ project_id: projectId, limit: '200' });
      const rows = await apiGet<DocumentsApiRow[]>(`/v1/documents/?${params.toString()}`);
      return rows.map(normalizeDocRow);
    },
    enabled: Boolean(projectId),
    staleTime: 60_000,
  });

  const docById = useMemo(() => {
    const map = new Map<string, DocumentPickerRow>();
    for (const d of documents) map.set(d.id, d);
    return map;
  }, [documents]);

  /**
   * POST a single file to the documents upload endpoint and, on success,
   * append the returned id to ``linked_drawing_ids``. Mirrors the upload
   * shape used by the file-manager so the backend behaviour is identical.
   */
  const uploadFile = useCallback(
    async (file: File): Promise<void> => {
      const token = useAuthStore.getState().accessToken;
      const formData = new FormData();
      formData.append('file', file);
      const headers: Record<string, string> = { 'X-DDC-Client': 'OE/1.0' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(
        `/api/v1/documents/upload/?project_id=${encodeURIComponent(
          projectId,
        )}&category=other`,
        { method: 'POST', headers, body: formData },
      );
      if (!res.ok) {
        let detail = file.name;
        try {
          const body: unknown = await res.json();
          if (
            body &&
            typeof body === 'object' &&
            'detail' in body &&
            typeof (body as { detail: unknown }).detail === 'string'
          ) {
            detail = (body as { detail: string }).detail;
          }
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const created = (await res.json()) as { id?: string };
      if (!created.id) throw new Error('Upload returned no id');
      const newId = created.id;
      setForm((prev) => ({
        ...prev,
        linked_drawing_ids: prev.linked_drawing_ids.includes(newId)
          ? prev.linked_drawing_ids
          : [...prev.linked_drawing_ids, newId],
      }));
    },
    [projectId],
  );

  const handleFilesDropped = useCallback(
    async (files: FileList | File[]): Promise<void> => {
      const list = Array.from(files);
      if (list.length === 0) return;
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('requiresProject.title'),
        });
        return;
      }
      setUploadInFlight((n) => n + list.length);
      const results = await Promise.allSettled(list.map((f) => uploadFile(f)));
      const ok = results.filter((r) => r.status === 'fulfilled').length;
      const fail = results.length - ok;
      setUploadInFlight((n) => Math.max(0, n - list.length));
      if (ok > 0) {
        addToast({
          type: 'success',
          title: t('rfi.attachment_uploaded', {
            defaultValue: '{{count}} attachment(s) uploaded',
            count: ok,
          }),
        });
      }
      if (fail > 0) {
        addToast({
          type: 'error',
          title: t('rfi.attachment_failed', {
            defaultValue: '{{count}} upload(s) failed',
            count: fail,
          }),
        });
      }
    },
    [projectId, uploadFile, addToast, t],
  );

  const removeDrawing = useCallback((id: string) => {
    setForm((prev) => ({
      ...prev,
      linked_drawing_ids: prev.linked_drawing_ids.filter((d) => d !== id),
    }));
  }, []);

  const set = <K extends keyof RFIFormData>(key: K, value: RFIFormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors((prev) => { const next = { ...prev }; delete next[key]; return next; });
  };

  const canSubmit = form.subject.trim().length > 0 && form.question.trim().length > 0;

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!form.subject.trim()) e.subject = t('validation.required', { defaultValue: 'This field is required' });
    if (!form.question.trim()) e.question = t('validation.required', { defaultValue: 'This field is required' });
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = () => {
    if (!validate()) return;
    onSubmit(form);
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="xl"
      title={t('rfi.new_rfi', { defaultValue: 'New RFI' })}
      subtitle={
        projectName
          ? t('common.creating_in_project', {
              defaultValue: 'In {{project}}',
              project: projectName,
            })
          : undefined
      }
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
            <span>{t('rfi.create_rfi', { defaultValue: 'Create RFI' })}</span>
          </Button>
        </>
      }
    >
      {/* Document picker — list-modal lazily mounted */}
      {showDocPicker && (
        <DocumentPickerModal
          documents={documents}
          isLoading={docsLoading}
          selected={form.linked_drawing_ids}
          onClose={() => setShowDocPicker(false)}
          onApply={(ids) => {
            setForm((prev) => ({ ...prev, linked_drawing_ids: ids }));
            setShowDocPicker(false);
          }}
        />
      )}

      {/* ── Request Details ── */}
      <WideModalSection
        title={t('rfi.section_request', { defaultValue: 'Request Details' })}
        columns={2}
      >
        <WideModalField
          label={t('rfi.field_subject', { defaultValue: 'Subject' })}
          required
          span={2}
          htmlFor="rfi-subject"
          error={errors.subject}
        >
          <input
            id="rfi-subject"
            value={form.subject}
            onChange={(e) => set('subject', e.target.value)}
            placeholder={t('rfi.subject_placeholder', {
              defaultValue: 'e.g. Clarification on foundation depth at Grid Line A-3',
            })}
            className={clsx(
              'h-12 w-full rounded-lg border border-border bg-surface-primary px-3 text-base font-medium focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
              errors.subject &&
                'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
          />
        </WideModalField>

        <WideModalField
          label={t('rfi.field_question', { defaultValue: 'Question' })}
          required
          span={2}
          htmlFor="rfi-question"
          error={errors.question}
        >
          <textarea
            id="rfi-question"
            value={form.question}
            onChange={(e) => set('question', e.target.value)}
            rows={5}
            className={clsx(
              textareaCls,
              errors.question &&
                'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
            placeholder={t('rfi.question_placeholder', {
              defaultValue: 'Describe the information you need...',
            })}
          />
        </WideModalField>

        <WideModalField label={t('rfi.field_priority', { defaultValue: 'Priority' })}>
          <div
            role="radiogroup"
            aria-label={t('rfi.field_priority', { defaultValue: 'Priority' })}
            className="flex flex-wrap gap-1.5"
          >
            {PRIORITY_VALUES.map((p) => {
              const active = form.priority === p;
              return (
                <button
                  key={p}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => set('priority', p)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                    active
                      ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                      : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={clsx('inline-block h-2 w-2 rounded-full', PRIORITY_DOT[p])}
                  />
                  {t(`rfi.priority_${p}`, {
                    defaultValue: p.charAt(0).toUpperCase() + p.slice(1),
                  })}
                </button>
              );
            })}
          </div>
        </WideModalField>

        <WideModalField
          label={t('rfi.field_discipline', { defaultValue: 'Discipline' })}
          htmlFor="rfi-discipline"
        >
          <div className="relative">
            <select
              id="rfi-discipline"
              value={form.discipline}
              onChange={(e) => set('discipline', e.target.value)}
              className={clsx(inputCls, 'pr-9 appearance-none')}
            >
              <option value="">
                {t('rfi.discipline_none', { defaultValue: 'No discipline' })}
              </option>
              {RFI_DISCIPLINES.map((d) => (
                <option key={d} value={d}>
                  {t(`rfi.discipline_${d}`, {
                    defaultValue: d.charAt(0).toUpperCase() + d.slice(1),
                  })}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </WideModalField>
      </WideModalSection>

      {/* ── Assignment & Schedule ── */}
      <WideModalSection
        title={t('rfi.section_assignment', { defaultValue: 'Assignment & Schedule' })}
        columns={2}
      >
        <WideModalField
          label={t('rfi.field_ball_in_court', { defaultValue: 'Ball in Court' })}
          htmlFor="rfi-ball-in-court"
        >
          <UserSearchInput
            value={form.ball_in_court}
            displayValue={form.ball_in_court_name}
            onChange={(id, name) => {
              setForm((prev) => ({ ...prev, ball_in_court: id, ball_in_court_name: name }));
            }}
            placeholder={t('rfi.bic_placeholder', {
              defaultValue: 'Person responsible for response',
            })}
          />
        </WideModalField>

        <WideModalField
          label={t('rfi.field_assigned_to', { defaultValue: 'Assigned To' })}
          htmlFor="rfi-assigned-to"
        >
          <UserSearchInput
            value={form.assigned_to}
            displayValue={form.assigned_to_name}
            onChange={(id, name) => {
              setForm((prev) => ({ ...prev, assigned_to: id, assigned_to_name: name }));
            }}
            placeholder={t('rfi.assigned_to_placeholder', {
              defaultValue: 'Reviewer / coordinator',
            })}
          />
        </WideModalField>

        <WideModalField
          label={t('rfi.field_due_date', { defaultValue: 'Response Due Date' })}
          span={2}
          htmlFor="rfi-due-date"
          hint={t('rfi.response_due_date_hint', {
            defaultValue: 'Typical: 14 business days from submission',
          })}
        >
          <input
            id="rfi-due-date"
            type="date"
            value={form.due_date}
            onChange={(e) => set('due_date', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>

      {/* ── Impact Assessment ── */}
      <WideModalSection
        title={t('rfi.section_impact', { defaultValue: 'Impact Assessment' })}
        columns={2}
      >
        <WideModalField label={t('rfi.cost_impact', { defaultValue: 'Cost Impact' })}>
          <button
            type="button"
            onClick={() => set('cost_impact', !form.cost_impact)}
            className={clsx(
              'flex items-center gap-3 rounded-lg border-2 px-4 py-3 transition-all text-left w-full',
              form.cost_impact
                ? 'border-amber-400 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-600'
                : 'border-border bg-surface-primary hover:bg-surface-secondary',
            )}
          >
            <div
              className={clsx(
                'flex h-8 w-8 items-center justify-center rounded-full shrink-0',
                form.cost_impact
                  ? 'bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-400'
                  : 'bg-surface-tertiary text-content-quaternary',
              )}
            >
              <DollarSign size={16} />
            </div>
            <div>
              <p
                className={clsx(
                  'text-sm font-medium',
                  form.cost_impact ? 'text-amber-700 dark:text-amber-400' : 'text-content-secondary',
                )}
              >
                {t('rfi.cost_impact', { defaultValue: 'Cost Impact' })}
              </p>
              <p className="text-xs text-content-quaternary">
                {form.cost_impact
                  ? t('rfi.impact_yes', { defaultValue: 'Yes' })
                  : t('rfi.impact_no', { defaultValue: 'No' })}
              </p>
            </div>
          </button>
        </WideModalField>

        <WideModalField label={t('rfi.schedule_impact', { defaultValue: 'Schedule Impact' })}>
          <button
            type="button"
            onClick={() => set('schedule_impact', !form.schedule_impact)}
            className={clsx(
              'flex items-center gap-3 rounded-lg border-2 px-4 py-3 transition-all text-left w-full',
              form.schedule_impact
                ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-600'
                : 'border-border bg-surface-primary hover:bg-surface-secondary',
            )}
          >
            <div
              className={clsx(
                'flex h-8 w-8 items-center justify-center rounded-full shrink-0',
                form.schedule_impact
                  ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400'
                  : 'bg-surface-tertiary text-content-quaternary',
              )}
            >
              <CalendarClock size={16} />
            </div>
            <div>
              <p
                className={clsx(
                  'text-sm font-medium',
                  form.schedule_impact
                    ? 'text-blue-700 dark:text-blue-400'
                    : 'text-content-secondary',
                )}
              >
                {t('rfi.schedule_impact', { defaultValue: 'Schedule Impact' })}
              </p>
              <p className="text-xs text-content-quaternary">
                {form.schedule_impact
                  ? t('rfi.impact_yes', { defaultValue: 'Yes' })
                  : t('rfi.impact_no', { defaultValue: 'No' })}
              </p>
            </div>
          </button>
        </WideModalField>

        {form.cost_impact && (
          <WideModalField
            label={t('rfi.field_cost_impact_value', { defaultValue: 'Cost exposure' })}
            htmlFor="rfi-cost-value"
            hint={t('rfi.cost_value_hint', {
              defaultValue: 'Estimated impact in project currency (optional)',
            })}
          >
            <input
              id="rfi-cost-value"
              type="text"
              inputMode="decimal"
              value={form.cost_impact_value}
              onChange={(e) => set('cost_impact_value', e.target.value)}
              placeholder={t('rfi.cost_value_placeholder', { defaultValue: 'e.g. 15000' })}
              className={inputCls}
            />
          </WideModalField>
        )}

        {form.schedule_impact && (
          <WideModalField
            label={t('rfi.field_schedule_impact_days', { defaultValue: 'Schedule slip (days)' })}
            htmlFor="rfi-schedule-days"
            hint={t('rfi.schedule_days_hint', {
              defaultValue: 'Working days the response could delay the schedule',
            })}
          >
            <input
              id="rfi-schedule-days"
              type="number"
              min={0}
              step={1}
              value={form.schedule_impact_days}
              onChange={(e) => set('schedule_impact_days', e.target.value)}
              placeholder={t('rfi.schedule_days_placeholder', { defaultValue: 'e.g. 5' })}
              className={inputCls}
            />
          </WideModalField>
        )}
      </WideModalSection>

      {/* ── References / Linked Drawings ── */}
      <WideModalSection
        title={t('rfi.section_references', { defaultValue: 'References' })}
        columns={2}
      >
        {form.linked_drawing_ids.length > 0 && (
          <WideModalField label={t('rfi.attached_documents', { defaultValue: 'Attached documents' })} span={2}>
            <div className="flex flex-wrap gap-1.5">
              {form.linked_drawing_ids.map((id) => {
                const doc = docById.get(id);
                const label = doc?.filename || id;
                return (
                  <span
                    key={id}
                    className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 text-oe-blue px-2.5 py-1 text-xs font-medium"
                  >
                    <FileText size={11} />
                    <span className="max-w-[180px] truncate" title={label}>
                      {label}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeDrawing(id)}
                      aria-label={t('rfi.remove_attachment', {
                        defaultValue: 'Remove attachment',
                      })}
                      className="ml-0.5 rounded-full hover:bg-oe-blue/20 p-0.5"
                    >
                      <X size={11} />
                    </button>
                  </span>
                );
              })}
            </div>
          </WideModalField>
        )}

        <WideModalField label={t('rfi.attach_drawings', { defaultValue: 'Attach drawings' })}>
          <button
            type="button"
            onClick={() => setShowDocPicker(true)}
            disabled={!projectId}
            className="flex items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface-primary px-3 py-3 text-sm font-medium text-content-secondary hover:bg-surface-secondary hover:border-oe-blue/60 transition-colors disabled:opacity-50 disabled:cursor-not-allowed w-full"
          >
            <Paperclip size={14} />
            {t('rfi.attach_drawings', { defaultValue: 'Attach drawings' })}
          </button>
        </WideModalField>

        <WideModalField label={t('rfi.drop_or_browse', { defaultValue: 'Drop file or browse' })}>
          <div
            role="button"
            tabIndex={0}
            onClick={() => dropFileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                dropFileInputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setDragOver(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (e.dataTransfer.files.length > 0) {
                void handleFilesDropped(e.dataTransfer.files);
              }
            }}
            className={clsx(
              'flex items-center justify-center gap-2 rounded-lg border-2 border-dashed px-3 py-3 text-sm font-medium cursor-pointer transition-colors',
              dragOver
                ? 'border-oe-blue bg-oe-blue/5 text-oe-blue'
                : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary hover:border-oe-blue/60',
            )}
            aria-label={t('rfi.upload_attachment', { defaultValue: 'Upload an attachment' })}
          >
            {uploadInFlight > 0 ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <UploadCloud size={14} />
            )}
            {uploadInFlight > 0
              ? t('rfi.uploading', { defaultValue: 'Uploading…' })
              : t('rfi.drop_or_browse', { defaultValue: 'Drop file or browse' })}
          </div>
          <input
            ref={dropFileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                void handleFilesDropped(e.target.files);
                e.target.value = '';
              }
            }}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Respond Modal ─────────────────────────────────────────────────────── */

function RespondModal({
  rfi,
  onClose,
  onSubmit,
  isPending,
}: {
  rfi: RFI;
  onClose: () => void;
  onSubmit: (data: RespondRFIPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [response, setResponse] = useState('');

  const handleSubmit = () => {
    if (response.trim()) onSubmit({ official_response: response.trim() });
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
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4" role="dialog" aria-modal="true" aria-label={t('rfi.respond_title', { defaultValue: 'Respond to RFI #{{number}}', number: rfi.rfi_number })}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('rfi.respond_title', { defaultValue: 'Respond to RFI #{{number}}', number: rfi.rfi_number })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-4 space-y-3">
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary mb-1">{t('rfi.original_question', { defaultValue: 'Question' })}</p>
            <p className="text-sm text-content-primary">{rfi.question}</p>
          </div>
          <div>
            <label htmlFor="rfi-response" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('rfi.field_response', { defaultValue: 'Response' })}
            </label>
            <textarea
              id="rfi-response"
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              rows={4}
              className={textareaCls}
              placeholder={t('rfi.response_placeholder', { defaultValue: 'Enter your response...' })}
              autoFocus
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
            disabled={isPending || !response.trim()}
          >
            {t('rfi.submit_response', { defaultValue: 'Submit Response' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── RFI Row (expandable) ──────────────────────────────────────────────── */

const RFIRow = React.memo(function RFIRow({
  rfi,
  viewerId,
  onRespond,
  onClose,
  onCreateVariation,
}: {
  rfi: RFI;
  viewerId: string | null;
  onRespond: (rfi: RFI) => void;
  onClose: (id: string) => void;
  onCreateVariation: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const days = rfi.days_open ?? daysOpen(rfi.created_at, null);
  const isOverdue = rfi.is_overdue ?? (rfi.response_due_date && rfi.status === 'open' && new Date(rfi.response_due_date) < new Date());
  const statusCfg = STATUS_CONFIG[rfi.status] ?? STATUS_CONFIG.draft;
  const bicSide = ballInCourtSide(rfi, viewerId);
  const bicCfg = BIC_SIDE_CFG[bicSide];
  // ``daysOverdue`` returns positive when past-due. Only render the pill
  // when both flags agree (so a stale ``is_overdue=true`` on a row with
  // no due date does not flash an empty "0d overdue" chip).
  const overdueDelta = daysOverdue(rfi.response_due_date);
  const showOverduePill = isOverdue && overdueDelta !== null && overdueDelta > 0;

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
        {/* Priority dot — colour-coded at the very left of the row.
            Uses role="img" so the aria-label is permitted (axe-core's
            ``aria-prohibited-attr`` rule forbids aria-label on a bare
            span). */}
        <span
          role="img"
          className={clsx(
            'inline-block h-2 w-2 rounded-full shrink-0',
            rfi.priority ? PRIORITY_DOT[rfi.priority] : 'bg-transparent border border-border',
          )}
          aria-label={
            rfi.priority
              ? t('rfi.priority_aria', {
                  defaultValue: 'Priority: {{p}}',
                  p: t(`rfi.priority_${rfi.priority}`, {
                    defaultValue:
                      rfi.priority.charAt(0).toUpperCase() + rfi.priority.slice(1),
                  }),
                })
              : t('rfi.priority_none_aria', { defaultValue: 'No priority' })
          }
          title={
            rfi.priority
              ? t(`rfi.priority_${rfi.priority}`, {
                  defaultValue:
                    rfi.priority.charAt(0).toUpperCase() + rfi.priority.slice(1),
                })
              : '—'
          }
        />

        <ChevronRight
          size={14}
          className={clsx(
            'text-content-tertiary transition-transform shrink-0',
            expanded && 'rotate-90',
          )}
        />

        {/* RFI # — links to deep page */}
        <Link
          to={`/rfi/${rfi.id}`}
          onClick={(e) => e.stopPropagation()}
          className="text-sm font-mono font-semibold text-content-secondary hover:text-oe-blue hover:underline w-16 shrink-0"
        >
          #{rfi.rfi_number}
        </Link>

        {/* Subject */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {rfi.subject}
        </span>

        {/* Status badge */}
        <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
          {t(`rfi.status_${rfi.status}`, {
            defaultValue: rfi.status.charAt(0).toUpperCase() + rfi.status.slice(1),
          })}
        </Badge>

        {/* Pending-approval indicator (feature 06) — renders only while a
            routed sign-off is running on this RFI. */}
        <ApprovalTargetBadge targetKind="rfi" targetId={rfi.id} />

        {/* Discipline chip — hidden when null */}
        {rfi.discipline && (
          <span
            className="hidden lg:inline-flex items-center rounded-full bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-secondary border border-border-light shrink-0"
            title={t('rfi.field_discipline', { defaultValue: 'Discipline' })}
          >
            {t(`rfi.discipline_${rfi.discipline}`, {
              defaultValue:
                rfi.discipline.charAt(0).toUpperCase() + rfi.discipline.slice(1),
            })}
          </span>
        )}

        {/* Ball in Court — visual side badge */}
        <span
          className={clsx(
            'hidden md:inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-semibold w-28 justify-center shrink-0',
            bicCfg.cls,
          )}
          title={t(bicCfg.key, { defaultValue: bicCfg.fallback })}
        >
          {t(bicCfg.key, { defaultValue: bicCfg.fallback })}
        </span>

        {/* Days Open + overdue pill */}
        <span
          className={clsx(
            'flex items-center justify-end gap-1 w-20 shrink-0 tabular-nums hidden sm:flex text-xs',
            isOverdue ? 'text-semantic-error font-semibold' : 'text-content-tertiary',
          )}
        >
          {days}d
          {showOverduePill && (
            <span
              role="status"
              className="inline-flex items-center rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 px-1.5 py-0.5 text-2xs font-bold"
              aria-label={t('rfi.overdue_by_days', {
                defaultValue: 'Overdue by {{count}} days',
                count: overdueDelta!,
              })}
              title={t('rfi.overdue_by_days', {
                defaultValue: 'Overdue by {{count}} days',
                count: overdueDelta!,
              })}
            >
              +{overdueDelta}
            </span>
          )}
        </span>

        {/* Due Date */}
        <span
          className={clsx(
            'text-xs w-20 shrink-0 hidden lg:block',
            isOverdue ? 'text-semantic-error font-semibold' : 'text-content-tertiary',
          )}
        >
          {rfi.response_due_date
            ? new Date(rfi.response_due_date).toLocaleDateString(undefined, {
                month: 'short',
                day: 'numeric',
              })
            : '-'}
        </span>

        {/* Impact indicators */}
        <div className="flex items-center gap-1.5 w-14 shrink-0 justify-end">
          {rfi.cost_impact && (
            <span title={t('rfi.cost_impact', { defaultValue: 'Cost Impact' })}>
              <DollarSign size={13} className="text-amber-500" />
            </span>
          )}
          {rfi.schedule_impact && (
            <span title={t('rfi.schedule_impact', { defaultValue: 'Schedule Impact' })}>
              <Clock size={13} className="text-orange-500" />
            </span>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Question */}
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
              {t('rfi.label_question', { defaultValue: 'Question' })}
            </p>
            <p className="text-sm text-content-primary whitespace-pre-wrap">{rfi.question}</p>
          </div>

          {/* Response */}
          {rfi.official_response && (
            <div className="rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3">
              <p className="text-xs text-green-700 dark:text-green-400 mb-1 font-medium uppercase tracking-wide">
                {t('rfi.label_response', { defaultValue: 'Response' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">{rfi.official_response}</p>
              {rfi.responded_at && (
                <p className="text-xs text-content-tertiary mt-2">
                  {new Date(rfi.responded_at).toLocaleDateString(undefined, {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })}
                </p>
              )}
            </div>
          )}

          {/* Linked drawings — link through to the deep RFI page where the
              ids are resolved to real filenames, instead of dumping raw
              UUIDs the operator cannot act on. */}
          {rfi.linked_drawing_ids && rfi.linked_drawing_ids.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <FileText size={13} className="text-content-tertiary" />
              <span className="text-xs text-content-secondary">
                {t('rfi.attached_documents', { defaultValue: 'Attached documents' })}
              </span>
              <Badge variant="neutral" size="sm">
                {t('rfi.attached_documents_count', {
                  defaultValue: '{{count}} document(s)',
                  count: rfi.linked_drawing_ids.length,
                })}
              </Badge>
              <Link
                to={`/rfi/${rfi.id}`}
                onClick={(e) => e.stopPropagation()}
                className="text-xs font-medium text-oe-blue hover:underline"
              >
                {t('rfi.view_details', { defaultValue: 'View details' })}
              </Link>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {rfi.status === 'open' && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onRespond(rfi);
                }}
              >
                {t('rfi.action_respond', { defaultValue: 'Respond' })}
              </Button>
            )}
            {(rfi.status === 'answered' || rfi.status === 'open') && (
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(rfi.id);
                }}
              >
                {t('rfi.action_close', { defaultValue: 'Close RFI' })}
              </Button>
            )}
            {rfi.cost_impact && (rfi.status === 'answered' || rfi.status === 'closed') && (
              <Button
                variant="secondary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onCreateVariation(rfi.id);
                }}
              >
                <DollarSign size={14} className="mr-1" />
                {t('rfi.create_variation', { defaultValue: 'Create Variation' })}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Export helper ─────────────────────────────────────────────────────── */

async function downloadExcelExport(url: string, fallbackFilename: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`/api${url}`, { method: 'GET', headers });
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || fallbackFilename;
  triggerDownload(blob, filename);
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function RFIPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [respondingRfi, setRespondingRfi] = useState<RFI | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  /* Debounced copy of the search input that drives the backend `?search=`
     query. Keeps typing fluid (no fetch storm) but still hits the server
     so search reaches RFI rows past the current page. */
  const [debouncedSearch, setDebouncedSearch] = useState('');
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(searchQuery), 300);
    return () => clearTimeout(handle);
  }, [searchQuery]);
  const [statusFilter, setStatusFilter] = useState<RFIStatus | ''>('');
  const [priorityFilter, setPriorityFilter] = useState<RFIPriority | ''>('');
  const [disciplineFilter, setDisciplineFilter] = useState<string>('');
  /**
   * Saved-view chip. ``all`` is the no-op baseline; the other three are
   * the most-requested ball-in-court slices construction users mentioned
   * during validation interviews:
   *   - ``mine``     — RFIs the current viewer raised
   *   - ``awaiting`` — RFIs whose ball is in the viewer's court (assignee
   *                    or BIC field matches their user id) and still
   *                    open/draft
   *   - ``overdue``  — open RFIs past their response_due_date
   * Chips are mutually exclusive with each other but cumulative with the
   * status / priority / discipline dropdowns above.
   */
  const [quickView, setQuickView] = useState<'all' | 'mine' | 'awaiting' | 'overdue'>('all');

  // Decode JWT once per token rotation. Falls back to ``null`` for
  // anonymous viewers — quick-filter "Awaiting me" simply matches nothing
  // in that case rather than throwing.
  const accessToken = useAuthStore((s) => s.accessToken);
  const viewerId = useMemo(() => decodeUserIdFromToken(accessToken), [accessToken]);

  // "n" shortcut → open new RFI form
  useCreateShortcut(
    useCallback(() => setShowCreateModal(true), []),
    !showCreateModal,
  );

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';
  // Genuinely-selected project (route param or shared context) — used for
  // the breadcrumb so the trail never shows a first-project guess.
  const selectedProjectId = routeProjectId || activeProjectId || '';
  const breadcrumbProjectName =
    projects.find((p) => p.id === selectedProjectId)?.name || '';

  const {
    data: rfis = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['rfis', projectId, statusFilter, debouncedSearch],
    queryFn: () =>
      fetchRFIs({
        project_id: projectId,
        status: statusFilter || undefined,
        search: debouncedSearch || undefined,
        limit: 100,
      }),
    enabled: !!projectId,
  });

  /* Server already filters by ?status= / ?search= but priority + discipline
     are filtered client-side for now — the column list endpoint does not
     accept them as query params yet. Keeping the filtering close to the
     dropdown state means the toolbar reacts instantly when the user picks
     a chip. */
  const filtered = useMemo(() => {
    if (!priorityFilter && !disciplineFilter && quickView === 'all') return rfis;
    return rfis.filter((r) => {
      if (priorityFilter && r.priority !== priorityFilter) return false;
      if (disciplineFilter && r.discipline !== disciplineFilter) return false;
      if (quickView === 'mine') {
        if (!viewerId || r.raised_by !== viewerId) return false;
      } else if (quickView === 'awaiting') {
        // Ball-in-court is in the viewer's lap AND the RFI is still
        // actionable. Using the shared helper keeps this in lockstep
        // with the row badge — if the badge says "With you" the chip
        // counts it.
        if (ballInCourtSide(r, viewerId) !== 'you') return false;
      } else if (quickView === 'overdue') {
        if (!r.is_overdue) return false;
      }
      return true;
    });
  }, [rfis, priorityFilter, disciplineFilter, quickView, viewerId]);

  // "Awaiting me" counter — derived directly from the loaded page so the
  // chip badge stays in sync with what the user sees if they switch to it.
  const awaitingMeCount = useMemo(() => {
    if (!viewerId) return 0;
    return rfis.filter((r) => ballInCourtSide(r, viewerId) === 'you').length;
  }, [rfis, viewerId]);

  /* Real stats come from the dedicated /stats/ endpoint, which scans the
     full RFI table for the project — not just the loaded page. The
     in-memory rollup only stays as a fallback while the stats query is
     in flight or unavailable. */
  const { data: serverStats } = useQuery({
    queryKey: ['rfi-stats', projectId],
    queryFn: () => fetchRFIStats(projectId),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const stats = useMemo(() => {
    if (serverStats) {
      return {
        total: serverStats.total,
        open: serverStats.open,
        overdue: serverStats.overdue,
        avgDays: serverStats.avg_days_to_response
          ? Math.round(serverStats.avg_days_to_response)
          : 0,
      };
    }
    const total = rfis.length;
    const open = rfis.filter((r) => r.status === 'open').length;
    const overdue = rfis.filter(
      (r) => r.is_overdue ?? (r.status === 'open' && r.response_due_date && new Date(r.response_due_date) < new Date()),
    ).length;
    const avgDays =
      rfis.length > 0
        ? Math.round(rfis.reduce((sum, r) => sum + (r.days_open ?? daysOpen(r.created_at, null)), 0) / rfis.length)
        : 0;
    return { total, open, overdue, avgDays };
  }, [rfis, serverStats]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['rfis'] });
    qc.invalidateQueries({ queryKey: ['rfi-stats'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateRFIPayload) => createRFI(data),
    onSuccess: (newRfi) => {
      // Optimistically add the new RFI to the cache so it appears immediately,
      // then also invalidate to ensure eventual consistency with the server.
      qc.setQueryData<RFI[]>(
        ['rfis', projectId, statusFilter],
        (old) => (old ? [newRfi, ...old] : [newRfi]),
      );
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('rfi.created', { defaultValue: 'RFI created successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.create_failed', { defaultValue: 'Failed to create RFI' }),
        message: e.message,
      }),
  });

  const respondMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: RespondRFIPayload }) =>
      respondToRFI(id, data),
    onSuccess: () => {
      invalidateAll();
      setRespondingRfi(null);
      addToast({
        type: 'success',
        title: t('rfi.responded', { defaultValue: 'Response submitted successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.respond_failed', { defaultValue: 'Failed to submit response' }),
        message: e.message,
      }),
  });

  const closeMut = useMutation({
    mutationFn: (id: string) => closeRFI(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('rfi.closed', { defaultValue: 'RFI closed successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.close_failed', { defaultValue: 'Failed to close RFI' }),
        message: e.message,
      }),
  });

  const exportMut = useMutation({
    mutationFn: () =>
      downloadExcelExport(
        `/v1/rfi/export/?project_id=${projectId}`,
        'rfi_log.xlsx',
      ),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('rfi.export_success', { defaultValue: 'RFI log exported successfully' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.export_failed', { defaultValue: 'Failed to export RFI log' }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: RFIFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('requiresProject.title'), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      const scheduleDays = Number.parseInt(formData.schedule_impact_days, 10);
      createMut.mutate({
        project_id: projectId,
        subject: formData.subject,
        question: formData.question,
        ball_in_court: formData.ball_in_court || undefined,
        assigned_to: formData.assigned_to || undefined,
        response_due_date: formData.due_date || undefined,
        cost_impact: formData.cost_impact,
        cost_impact_value:
          formData.cost_impact && formData.cost_impact_value.trim()
            ? formData.cost_impact_value.trim()
            : undefined,
        schedule_impact: formData.schedule_impact,
        schedule_impact_days:
          formData.schedule_impact && Number.isFinite(scheduleDays) && scheduleDays >= 0
            ? scheduleDays
            : undefined,
        priority: formData.priority,
        discipline: formData.discipline || undefined,
        linked_drawing_ids:
          formData.linked_drawing_ids.length > 0
            ? formData.linked_drawing_ids
            : undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const handleRespond = useCallback(
    (rfi: RFI) => {
      setRespondingRfi(rfi);
    },
    [],
  );

  const handleRespondSubmit = useCallback(
    (data: RespondRFIPayload) => {
      if (!respondingRfi) return;
      respondMut.mutate({ id: respondingRfi.id, data });
    },
    [respondMut, respondingRfi],
  );

  const { confirm, ...confirmProps } = useConfirm();

  const handleClose = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('rfi.confirm_close_title', { defaultValue: 'Close RFI?' }),
        message: t('rfi.confirm_close_msg', { defaultValue: 'This RFI will be closed and no further responses can be added.' }),
        confirmLabel: t('rfi.action_close', { defaultValue: 'Close RFI' }),
        variant: 'warning',
      });
      if (ok) closeMut.mutate(id);
    },
    [closeMut, confirm, t],
  );

  const createVariationMut = useMutation({
    mutationFn: (rfiId: string) =>
      apiPost<{ change_order_id: string; code: string; title: string }>(
        // Route is POST /{rfi_id}/create-variation/ WITH a trailing slash
        // (router.py); with redirect_slashes=False the no-slash form 404s
        // and the Create Variation action silently fails.
        `/v1/rfi/${rfiId}/create-variation/`,
        {},
      ),
    onSuccess: (data) => {
      addToast(
        {
          type: 'success',
          title: t('rfi.variation_created', { defaultValue: 'Variation created' }),
          message: `${data.code}: ${data.title}`,
          action: {
            label: t('rfi.view_change_orders', { defaultValue: 'View Change Orders' }),
            onClick: () => {
              window.location.href = '/changeorders';
            },
          },
        },
        { duration: 8000 },
      );
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.variation_failed', { defaultValue: 'Failed to create variation from RFI' }),
        message: e.message,
      }),
  });

  const handleCreateVariation = useCallback(
    (id: string) => {
      createVariationMut.mutate(id);
    },
    [createVariationMut],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          ...(selectedProjectId && breadcrumbProjectName
            ? [{ label: breadcrumbProjectName, to: `/projects/${selectedProjectId}` }]
            : []),
          { label: t('rfi.title', { defaultValue: 'RFIs' }) },
        ]}
      />

      {/* Header */}
      <PageHeader
        subtitle={t('rfi.subtitle', { defaultValue: 'Submit, track, and resolve design and construction queries' })}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              icon={
                exportMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Download size={14} />
                )
              }
              onClick={() => exportMut.mutate()}
              disabled={exportMut.isPending || !projectId}
            >
              {t('rfi.export_rfi_log', { defaultValue: 'Export RFI Log' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowCreateModal(true)}
              disabled={!projectId}
              title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
              icon={<Plus size={14} />}
            >
              {t('rfi.new_rfi', { defaultValue: 'New RFI' })}
            </Button>
          </>
        }
      />

      {/* Canonical module info card — pain-named title + workflow body. */}
      <DismissibleInfo
        storageKey="rfi"
        title={t('rfi.intro_title', { defaultValue: 'Get a clear answer on the record' })}
        more={
          t('rfi.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('rfi.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.variations', { defaultValue: 'Variations' }),
            onClick: () => navigate('/variations'),
          },
          {
            label: t('submittals.title', { defaultValue: 'Submittals' }),
            onClick: () => navigate('/submittals'),
          },
          {
            label: t('correspondence.title', { defaultValue: 'Correspondence' }),
            onClick: () => navigate('/correspondence'),
          },
        ]}
      >
        {t('rfi.intro_body', {
          defaultValue:
            'Raise a question to the design team, set who owns the next move and a response due date, then track it from Open to Answered to Closed with a ball-in-court badge and an overdue counter. Attach the drawings in question from Documents, and when an answer carries cost you can spin it straight into a Variation. Export the full RFI log for the contract file.',
        })}
      </DismissibleInfo>

      {projectId ? (
      <>
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('rfi.stat_total', { defaultValue: 'Total RFIs' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-content-primary">
            {stats.total}
          </p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('rfi.stat_open', { defaultValue: 'Open' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-oe-blue">{stats.open}</p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('rfi.stat_overdue', { defaultValue: 'Overdue' })}
          </p>
          <p
            className={clsx(
              'text-lg font-semibold mt-1 tabular-nums',
              stats.overdue > 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
          >
            {stats.overdue}
          </p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('rfi.stat_avg_days', { defaultValue: 'Avg. Days Open' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-content-primary">
            {stats.avgDays}
          </p>
        </div>
      </div>

      {/* Quick-view chips — saved-view shortcuts for the most common
          "what's on my plate?" slices. Mutually exclusive, kept above
          the dropdown toolbar so the eye can land on them first. */}
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label={t('rfi.quick_views_aria', { defaultValue: 'Quick views' })}>
        {(
          [
            { key: 'all', label: t('rfi.quick_all', { defaultValue: 'All' }) },
            {
              key: 'awaiting',
              label: t('rfi.quick_awaiting', { defaultValue: 'Awaiting me' }),
              count: awaitingMeCount,
            },
            { key: 'mine', label: t('rfi.quick_mine', { defaultValue: 'Raised by me' }) },
            {
              key: 'overdue',
              label: t('rfi.quick_overdue', { defaultValue: 'Overdue' }),
              count: stats.overdue,
            },
          ] as const
        ).map((chip) => {
          const active = quickView === chip.key;
          return (
            <button
              key={chip.key}
              role="tab"
              type="button"
              aria-selected={active}
              onClick={() => setQuickView(chip.key)}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                active
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {chip.label}
              {'count' in chip && chip.count !== undefined && chip.count > 0 && (
                <span
                  className={clsx(
                    'inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full px-1 text-2xs font-semibold tabular-nums',
                    active
                      ? 'bg-oe-blue text-white'
                      : chip.key === 'overdue'
                        ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                        : 'bg-surface-tertiary text-content-secondary',
                  )}
                >
                  {chip.count}
                </span>
              )}
            </button>
          );
        })}
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
            placeholder={t('rfi.search_placeholder', {
              defaultValue: 'Search RFIs...',
            })}
            aria-label={t('rfi.search_placeholder', { defaultValue: 'Search RFIs...' })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as RFIStatus | '')}
            aria-label={t('rfi.filter_all', { defaultValue: 'All Statuses' })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
          >
            <option value="">
              {t('rfi.filter_all', { defaultValue: 'All Statuses' })}
            </option>
            {(['draft', 'open', 'answered', 'closed', 'void'] as RFIStatus[]).map((s) => (
              <option key={s} value={s}>
                {t(`rfi.status_${s}`, {
                  defaultValue: s.charAt(0).toUpperCase() + s.slice(1),
                })}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>

        {/* Priority filter */}
        <div className="relative">
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value as RFIPriority | '')}
            aria-label={t('rfi.filter_priority', { defaultValue: 'All priorities' })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
          >
            <option value="">
              {t('rfi.filter_priority', { defaultValue: 'All priorities' })}
            </option>
            {PRIORITY_VALUES.map((p) => (
              <option key={p} value={p}>
                {t(`rfi.priority_${p}`, {
                  defaultValue: p.charAt(0).toUpperCase() + p.slice(1),
                })}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>

        {/* Discipline filter */}
        <div className="relative">
          <select
            value={disciplineFilter}
            onChange={(e) => setDisciplineFilter(e.target.value)}
            aria-label={t('rfi.filter_discipline', {
              defaultValue: 'All disciplines',
            })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
          >
            <option value="">
              {t('rfi.filter_discipline', { defaultValue: 'All disciplines' })}
            </option>
            {RFI_DISCIPLINES.map((d) => (
              <option key={d} value={d}>
                {t(`rfi.discipline_${d}`, {
                  defaultValue: d.charAt(0).toUpperCase() + d.slice(1),
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
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<HelpCircle size={28} strokeWidth={1.5} />}
            title={
              quickView !== 'all'
                ? t(`rfi.no_quick_${quickView}`, {
                    defaultValue:
                      quickView === 'awaiting'
                        ? 'No RFIs in your court'
                        : quickView === 'mine'
                          ? 'You have not raised any RFIs yet'
                          : 'No overdue RFIs',
                  })
                : searchQuery || statusFilter
                  ? t('rfi.no_results', { defaultValue: 'No matching RFIs' })
                  : t('rfi.no_rfis', { defaultValue: 'No RFIs yet' })
            }
            description={
              quickView !== 'all'
                ? t('rfi.no_quick_hint', {
                    defaultValue: 'Clear the quick filter to see all RFIs for this project.',
                  })
                : searchQuery || statusFilter
                  ? t('rfi.no_results_hint', {
                      defaultValue: 'Try adjusting your search or filters to find what you are looking for.',
                    })
                  : t('rfi.no_rfis_hint', {
                      defaultValue: 'Create your first RFI to track design queries, clarifications, and responses between project stakeholders.',
                    })
            }
            action={
              quickView !== 'all'
                ? {
                    label: t('rfi.quick_clear', { defaultValue: 'Show all RFIs' }),
                    onClick: () => setQuickView('all'),
                  }
                : !searchQuery && !statusFilter
                  ? {
                      label: t('rfi.new_rfi', { defaultValue: 'New RFI' }),
                      onClick: () => setShowCreateModal(true),
                    }
                  : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('rfi.showing_count', {
                defaultValue: '{{count}} RFIs',
                count: filtered.length,
              })}
            </p>

            {/* Desktop table */}
            <div className="hidden md:block">
              <Card padding="none" className="overflow-x-auto">
                {/* Table header */}
                <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
                  <span className="w-5" /> {/* Chevron space */}
                  <span className="w-16">#</span>
                  <span className="flex-1">
                    {t('rfi.col_subject', { defaultValue: 'Subject' })}
                  </span>
                  <span className="w-20 text-center">
                    {t('rfi.col_status', { defaultValue: 'Status' })}
                  </span>
                  <span className="w-28 text-center">
                    {t('rfi.col_bic', { defaultValue: 'Ball in Court' })}
                  </span>
                  <span className="w-20 text-right">
                    {t('rfi.col_days', { defaultValue: 'Days' })}
                  </span>
                  <span className="w-20">
                    {t('rfi.col_due', { defaultValue: 'Due' })}
                  </span>
                  <span className="w-14 text-right">
                    {t('rfi.col_impact', { defaultValue: 'Impact' })}
                  </span>
                </div>

                {/* Rows */}
                {filtered.map((rfi) => (
                  <RFIRow
                    key={rfi.id}
                    rfi={rfi}
                    viewerId={viewerId}
                    onRespond={handleRespond}
                    onClose={handleClose}
                    onCreateVariation={handleCreateVariation}
                  />
                ))}
              </Card>
            </div>

            {/* Mobile card view */}
            <div className="md:hidden space-y-3">
              {filtered.map((rfi) => {
                const days = rfi.days_open ?? daysOpen(rfi.created_at, null);
                const isOverdue = rfi.is_overdue ?? (rfi.response_due_date && rfi.status === 'open' && new Date(rfi.response_due_date) < new Date());
                const statusCfg = STATUS_CONFIG[rfi.status] ?? STATUS_CONFIG.draft;
                const bicSide = ballInCourtSide(rfi, viewerId);
                const bicCfg = BIC_SIDE_CFG[bicSide];
                const overdueDelta = daysOverdue(rfi.response_due_date);
                return (
                  <Card key={rfi.id} className="p-4">
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="min-w-0 flex-1">
                        <span className="text-xs font-mono text-content-tertiary">#{rfi.rfi_number}</span>
                        <h4 className="text-sm font-semibold text-content-primary truncate">{rfi.subject}</h4>
                      </div>
                      <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
                        {t(`rfi.status_${rfi.status}`, { defaultValue: rfi.status.charAt(0).toUpperCase() + rfi.status.slice(1) })}
                      </Badge>
                    </div>
                    <div className="mb-2">
                      <span
                        className={clsx(
                          'inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-semibold',
                          bicCfg.cls,
                        )}
                      >
                        {t(bicCfg.key, { defaultValue: bicCfg.fallback })}
                      </span>
                    </div>
                    <div className="text-xs text-content-tertiary space-y-1">
                      {/* The ball-in-court party is already conveyed by the
                          "With you / With them" side badge above; rendering the
                          raw ball_in_court UUID here was unreadable to operators,
                          so it is intentionally omitted. */}
                      {isOverdue && overdueDelta !== null && overdueDelta > 0 && (
                        <div className="inline-flex items-center rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 px-1.5 py-0.5 text-2xs font-bold">
                          {t('rfi.overdue_by_days', { defaultValue: 'Overdue by {{count}} days', count: overdueDelta })}
                        </div>
                      )}
                      <div className="flex items-center gap-3">
                        <span className={isOverdue ? 'text-semantic-error font-semibold' : ''}>{days}d {t('rfi.col_days', { defaultValue: 'open' })}</span>
                        {rfi.response_due_date && (
                          <span className={isOverdue ? 'text-semantic-error font-semibold' : ''}>
                            {t('rfi.col_due', { defaultValue: 'Due' })}: {new Date(rfi.response_due_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        {rfi.cost_impact && (
                          <span className="flex items-center gap-0.5 text-amber-500"><DollarSign size={12} /> {t('rfi.cost_impact', { defaultValue: 'Cost' })}</span>
                        )}
                        {rfi.schedule_impact && (
                          <span className="flex items-center gap-0.5 text-orange-500"><Clock size={12} /> {t('rfi.schedule_impact', { defaultValue: 'Schedule' })}</span>
                        )}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          </>
        )}
      </div>
      </>
      ) : (
        <RequiresProject
          emptyHint={t('rfi.select_project_hint', { defaultValue: 'Select a project from the header to submit, track, and resolve requests for information.' })}
        >{null}</RequiresProject>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <CreateRFIModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
          projectName={projectName}
          projectId={projectId}
        />
      )}

      {/* Respond Modal */}
      {respondingRfi && (
        <RespondModal
          rfi={respondingRfi}
          onClose={() => setRespondingRfi(null)}
          onSubmit={handleRespondSubmit}
          isPending={respondMut.isPending}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
