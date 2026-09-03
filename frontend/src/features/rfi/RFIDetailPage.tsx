// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RFIDetailPage — Deep page for a single RFI.
 *
 * Route: /rfi/:rfiId
 *
 * Sections (top → bottom):
 *   1. Breadcrumb     RFIs > #{rfi_number}
 *   2. Hero           subject (h1), status chip, days-open, due-date, overdue
 *   3. Two-column     left: question + official response
 *                     right: meta panel (raised_by / assigned_to / BIC / dates / impact)
 *   4. Actions        Respond (status=open), Close (status=answered)
 */

import { useState, useMemo, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  History,
  Loader2,
  MessageSquare,
  Paperclip,
  Pencil,
  Send,
  User,
  X,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
} from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet, type Page } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  closeRFI,
  fetchRFIActivity,
  getRFI,
  respondToRFI,
  updateRFI,
  type RespondRFIPayload,
} from './api';
import {
  BIC_SIDE_CFG,
  CreateRFIModal,
  PRIORITY_DOT,
  STATUS_CONFIG,
  ballInCourtSide,
  buildRfiPatch,
  daysOverdue,
  formFromRfi,
  type RFIFormData,
} from './RFIPage';
import { ApprovalInstanceCard } from '@/features/approval-routes';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useRegisterLinks } from '@/modules/comms-intelligence/useRegisterLinks';
import { RegisterChip } from '@/modules/comms-intelligence/RegisterChip';

// English fallbacks for the computed `rfi.status_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const RFI_STATUS_LABELS: Record<string, string> = {
  draft: 'Draft', open: 'Open', answered: 'Answered', closed: 'Closed', void: 'Void'
};


/**
 * Decode the ``sub`` claim from the JWT — duplicated locally so the
 * detail page does not depend on RFIPage internals (RFIPage re-exports
 * only the pure helpers, not the token decoder, to keep coupling clean).
 */
function decodeUserIdFromTokenLocal(token: string | null): string | null {
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

interface UserResult {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

/**
 * Minimal document shape needed by the attachments list. Mirrors the
 * subset of the documents-module list response we actually consume.
 */
interface AttachmentDoc {
  id: string;
  filename: string;
  category: string;
}

interface AttachmentApiRow {
  id: string;
  filename?: string;
  name?: string;
  category?: string;
}

function normaliseAttachment(raw: AttachmentApiRow): AttachmentDoc {
  return {
    id: raw.id,
    filename: raw.filename ?? raw.name ?? '',
    category: raw.category ?? 'other',
  };
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[10px] uppercase tracking-wider text-content-quaternary">
        {label}
      </dt>
      <dd className="text-sm text-content-primary break-words">{children}</dd>
    </div>
  );
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleDateString(getIntlLocale(), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return '—';
  }
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString(getIntlLocale(), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '—';
  }
}

/* ── Inline Respond Form ──────────────────────────────────────────────── */

function InlineRespondForm({
  isPending,
  onSubmit,
  onCancel,
}: {
  isPending: boolean;
  onSubmit: (data: RespondRFIPayload) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [response, setResponse] = useState('');

  const handleSubmit = () => {
    if (response.trim()) onSubmit({ official_response: response.trim() });
  };

  return (
    <div className="space-y-3 mt-3">
      <textarea
        value={response}
        onChange={(e) => setResponse(e.target.value)}
        rows={5}
        placeholder={t('rfi.response_placeholder', {
          defaultValue: 'Enter your response...',
        })}
        aria-label={t('rfi.field_response', { defaultValue: 'Response' })}
        className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
        autoFocus
      />
      <div className="flex items-center gap-2 justify-end">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handleSubmit}
          disabled={isPending || !response.trim()}
        >
          {isPending ? (
            <Loader2 size={14} className="mr-1.5 animate-spin" />
          ) : (
            <MessageSquare size={14} className="mr-1.5" />
          )}
          {t('rfi.submit_response', { defaultValue: 'Submit Response' })}
        </Button>
      </div>
    </div>
  );
}

/* ── Activity journal (item #13) ──────────────────────────────────────── */

/**
 * Render one lifecycle status as a coloured badge, reusing the same
 * `STATUS_CONFIG` palette as the hero chip and the list rows so the three
 * surfaces read with one eye-pattern. A null status (a create-type row) shows
 * a neutral "Created" token, mirroring the projects StatusHistoryTimeline.
 */
function ActivityStatusToken({ status }: { status: string | null }) {
  const { t } = useTranslation();
  if (!status) {
    return (
      <Badge variant="neutral" size="sm">
        {t('rfi.history_created', { defaultValue: 'Created' })}
      </Badge>
    );
  }
  const cfg =
    STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.draft;
  return (
    <Badge variant={cfg.variant} size="sm" className={cfg.cls}>
      {t(`rfi.status_${status}`, {
        defaultValue: RFI_STATUS_LABELS[status] ?? status.charAt(0).toUpperCase() + status.slice(1),
      })}
    </Badge>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function RFIDetailPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { rfiId } = useParams<{ rfiId: string }>();
  const [responding, setResponding] = useState(false);
  const [editing, setEditing] = useState(false);

  const {
    data: rfi,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['rfi', rfiId],
    queryFn: () => getRFI(rfiId as string),
    enabled: !!rfiId,
  });

  // Was this RFI raised through the registers? Narrowed to this one id;
  // an RFI created natively simply has no chip.
  const registerLinks = useRegisterLinks(rfi?.project_id, 'rfi', rfiId ? [rfiId] : undefined);
  const registerLink = rfiId ? registerLinks.get(rfiId) : undefined;

  // Lookup users so we can resolve raised_by / assigned_to / ball_in_court
  // to display names where possible. Falls back to the raw id when unknown.
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserResult[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
  });

  // Activity journal (item #13) — the RFI's lifecycle history from
  // oe_activity_log (respond / close / reopen transitions). Read-only; the
  // backend already records these rows in the same transaction as each write.
  const activityQuery = useQuery({
    queryKey: ['rfi-activity', rfiId],
    queryFn: () => fetchRFIActivity(rfiId as string),
    enabled: !!rfiId,
    staleTime: 30_000,
  });
  // The journal comes back oldest first and the endpoint caps `limit` at 100,
  // so on a long-running RFI the entries this page does NOT have are the most
  // recent ones. `total` is what lets the section admit that.
  const activityEntries = activityQuery.data?.items ?? [];
  const activityTotal = activityQuery.data?.total ?? activityEntries.length;

  // Resolve the owning project's currency so the cost-exposure figure
  // carries its ISO code (the amount lives in the project's currency,
  // which may be EUR/BRL/GBP/… — never assume USD).
  const { data: project } = useQuery({
    queryKey: ['project', rfi?.project_id ?? null],
    queryFn: () =>
      apiGet<{ id: string; name: string; currency: string }>(
        `/v1/projects/${rfi?.project_id}`,
      ),
    enabled: !!rfi?.project_id,
    staleTime: 5 * 60_000,
  });
  const projectCurrency = (project?.currency || '').trim().toUpperCase();

  // Resolve linked_drawing_ids to filenames. One GET per attached id is
  // acceptable today — RFIs typically reference a handful of drawings.
  // Each query is keyed independently so React Query memoises and dedupes
  // when the same id appears across multiple RFIs.
  const linkedIds = rfi?.linked_drawing_ids ?? [];
  const attachmentsQuery = useQuery({
    queryKey: ['rfi-attachments', rfi?.project_id ?? null, linkedIds.join(',')],
    queryFn: async (): Promise<AttachmentDoc[]> => {
      const projectId = rfi?.project_id;
      if (!projectId || linkedIds.length === 0) return [];
      const params = new URLSearchParams({ project_id: projectId, limit: '200' });
      // We pull the full project document list (capped at 200) and then
      // filter to the linked ids. Cheaper than one-GET-per-id when the
      // user attached more than a couple of drawings.
      const page = await apiGet<Page<AttachmentApiRow>>(
        `/v1/documents/?${params.toString()}`,
      );
      const wanted = new Set(linkedIds);
      return page.items
        .filter((r) => wanted.has(r.id))
        .map(normaliseAttachment);
    },
    enabled: !!rfi && linkedIds.length > 0,
    staleTime: 60_000,
  });

  const attachments = attachmentsQuery.data ?? [];
  // Fallback: render the raw ids if the documents-list call returned a
  // subset (e.g. some attachments are outside the page-200 cap) so the
  // user never sees fewer chips than they actually attached.
  const attachmentsResolved = useMemo<AttachmentDoc[]>(() => {
    if (linkedIds.length === 0) return [];
    const byId = new Map(attachments.map((a) => [a.id, a]));
    return linkedIds.map(
      (id: string) => byId.get(id) ?? { id, filename: id, category: 'other' },
    );
  }, [linkedIds, attachments]);

  const userById = useMemo(() => {
    const map = new Map<string, string>();
    for (const u of users) {
      map.set(u.id, u.full_name || u.email);
    }
    return map;
  }, [users]);

  const displayUser = useCallback(
    (id: string | null | undefined): string => {
      if (!id) return '—';
      return userById.get(id) ?? id;
    },
    [userById],
  );

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['rfi', rfiId] });
    qc.invalidateQueries({ queryKey: ['rfis'] });
    qc.invalidateQueries({ queryKey: ['rfi-stats'] });
    // Refresh the activity journal so a fresh respond/close row appears
    // without a manual reload.
    qc.invalidateQueries({ queryKey: ['rfi-activity', rfiId] });
  }, [qc, rfiId]);

  const respondMut = useMutation({
    mutationFn: (data: RespondRFIPayload) =>
      respondToRFI(rfiId as string, data),
    onSuccess: () => {
      invalidate();
      setResponding(false);
      addToast({
        type: 'success',
        title: t('rfi.responded', {
          defaultValue: 'Response submitted successfully',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.respond_failed', {
          defaultValue: 'Failed to submit response',
        }),
        message: e.message,
      }),
  });

  const updateMut = useMutation({
    mutationFn: (data: RFIFormData) =>
      updateRFI(
        rfiId as string,
        // Rebuild the baseline the modal was seeded from, so the save carries
        // only what the user actually edited. The modal cannot open before the
        // RFI has loaded, so there is always a baseline here; an empty patch is
        // the safe no-op if that ever stops being true.
        rfi ? buildRfiPatch(data, formFromRfi(rfi)) : {},
      ),
    onSuccess: () => {
      invalidate();
      setEditing(false);
      addToast({
        type: 'success',
        title: t('rfi.updated', { defaultValue: 'RFI updated successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.update_failed', { defaultValue: 'Failed to update RFI' }),
        message: e.message,
      }),
  });

  const closeMut = useMutation({
    mutationFn: () => closeRFI(rfiId as string),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('rfi.closed', { defaultValue: 'RFI closed successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.close_failed', {
          defaultValue: 'Failed to close RFI',
        }),
        message: e.message,
      }),
  });

  // Publish a drafted RFI: draft -> open. The backend validates the
  // transition, so this affordance is only shown while status === 'draft'.
  const openMut = useMutation({
    mutationFn: () => updateRFI(rfiId as string, { status: 'open' }),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('rfi.opened', { defaultValue: 'RFI opened' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.open_failed', { defaultValue: 'Failed to open RFI' }),
        message: e.message,
      }),
  });

  const { confirm, ...confirmProps } = useConfirm();

  const handleClose = useCallback(async () => {
    const ok = await confirm({
      title: t('rfi.confirm_close_title', { defaultValue: 'Close RFI?' }),
      message: t('rfi.confirm_close_msg', {
        defaultValue:
          'This RFI will be closed and no further responses can be added.',
      }),
      confirmLabel: t('rfi.action_close', { defaultValue: 'Close RFI' }),
      variant: 'warning',
    });
    if (ok) closeMut.mutate();
  }, [closeMut, confirm, t]);

  // ESC closes the inline respond form
  useEffect(() => {
    if (!responding) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setResponding(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [responding]);

  /* ── Render states ─────────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-oe-blue" />
      </div>
    );
  }

  if (isError || !rfi) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb
          items={[
            { label: t('rfi.title', { defaultValue: 'RFIs' }), to: '/rfi' },
            { label: t('common.not_found', { defaultValue: 'Not found' }) },
          ]}
        />
        <EmptyState
          icon={<AlertTriangle size={28} strokeWidth={1.5} />}
          title={t('rfi.not_found', { defaultValue: 'RFI not found' })}
          description={
            error instanceof Error
              ? error.message
              : t('rfi.not_found_hint', {
                  defaultValue:
                    'The RFI you are looking for does not exist or you do not have access to it.',
                })
          }
          action={{
            label: t('rfi.back_to_list', { defaultValue: 'Back to RFIs' }),
            onClick: () => navigate('/rfi'),
          }}
        />
      </div>
    );
  }

  const statusCfg = STATUS_CONFIG[rfi.status] ?? STATUS_CONFIG.draft;
  const isOverdue =
    rfi.is_overdue ??
    !!(
      rfi.response_due_date &&
      rfi.status === 'open' &&
      new Date(rfi.response_due_date) < new Date()
    );
  // Compute ball-in-court side relative to the viewer so the hero shows
  // a "With you / With them / Answered / Closed" pill — matches the row
  // chip on the list page, helping the operator instantly know whether
  // they need to take action on this RFI.
  const accessToken = useAuthStore.getState().accessToken;
  const viewerId = decodeUserIdFromTokenLocal(accessToken);
  const bicSide = ballInCourtSide(rfi, viewerId);
  const bicCfg = BIC_SIDE_CFG[bicSide];
  const overdueDelta = daysOverdue(rfi.response_due_date);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          ...(rfi.project_id && project?.name
            ? [{ label: project.name, to: `/projects/${rfi.project_id}` }]
            : []),
          { label: t('rfi.title', { defaultValue: 'RFIs' }), to: '/rfi' },
          { label: `#${rfi.rfi_number}` },
        ]}
      />

      {/* Hero */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3 mb-2 flex-wrap">
            <span className="text-sm font-mono font-semibold text-content-tertiary">
              #{rfi.rfi_number}
            </span>
            <Badge
              variant={statusCfg.variant}
              size="md"
              className={statusCfg.cls}
            >
              {t(`rfi.status_${rfi.status}`, {
                defaultValue:
                  RFI_STATUS_LABELS[rfi.status] ?? rfi.status.charAt(0).toUpperCase() + rfi.status.slice(1),
              })}
            </Badge>
            {isOverdue && (
              <Badge variant="error" size="md">
                <AlertTriangle size={12} className="mr-1 inline" />
                {overdueDelta !== null && overdueDelta > 0
                  ? t('rfi.overdue_by_days', {
                      defaultValue: 'Overdue by {{count}} days',
                      count: overdueDelta,
                    })
                  : t('rfi.overdue', { defaultValue: 'Overdue' })}
              </Badge>
            )}
            {/* Ball-in-court hero pill — same colour system as the list
                row badge so the contractor scans both surfaces with the
                same eye-pattern. */}
            <span
              className={clsx(
                'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
                bicCfg.cls,
              )}
            >
              {t(bicCfg.key, { defaultValue: bicCfg.fallback })}
            </span>
          </div>
          <h1 className="text-2xl font-bold text-content-primary break-words">
            {rfi.subject}
          </h1>
          {registerLink && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
              <span>{t('rfi.raised_from_register', { defaultValue: 'Raised from register' })}</span>
              <RegisterChip item={registerLink} />
              {registerLink.title && (
                <span className="truncate text-content-secondary">{registerLink.title}</span>
              )}
            </div>
          )}
          <div className="mt-2 flex items-center gap-4 text-xs text-content-tertiary flex-wrap">
            <span className="inline-flex items-center gap-1">
              <Clock size={12} />
              {t('rfi.days_open_count', {
                defaultValue: '{{count}} days open',
                count: rfi.days_open,
              })}
            </span>
            {rfi.response_due_date && (
              <span
                className={clsx(
                  'inline-flex items-center gap-1',
                  isOverdue && 'text-semantic-error font-semibold',
                )}
              >
                <CalendarClock size={12} />
                {t('rfi.due_on', {
                  defaultValue: 'Due {{date}}',
                  date: formatDate(rfi.response_due_date),
                })}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/rfi')}
            icon={<ArrowLeft size={14} />}
          >
            {t('rfi.back_to_list', { defaultValue: 'Back to RFIs' })}
          </Button>
          {/* Edit - the PATCH endpoint refuses edits once an RFI is closed
              / void (400), so the affordance is hidden for those states. */}
          {rfi.status !== 'closed' && rfi.status !== 'void' && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEditing(true)}
              icon={<Pencil size={14} />}
            >
              {t('rfi.action_edit', { defaultValue: 'Edit' })}
            </Button>
          )}
          {rfi.status === 'draft' && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => openMut.mutate()}
              disabled={openMut.isPending}
              icon={
                openMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Send size={14} />
                )
              }
            >
              {t('rfi.action_open', { defaultValue: 'Open RFI' })}
            </Button>
          )}
          {rfi.status === 'open' && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setResponding(true)}
              icon={<MessageSquare size={14} />}
            >
              {t('rfi.action_respond', { defaultValue: 'Respond' })}
            </Button>
          )}
          {rfi.status === 'answered' && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleClose}
              disabled={closeMut.isPending}
              icon={
                closeMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <CheckCircle2 size={14} />
                )
              }
            >
              {t('rfi.action_close', { defaultValue: 'Close RFI' })}
            </Button>
          )}
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left column (2/3 on desktop) */}
        <div className="lg:col-span-2 space-y-4">
          {/* Question */}
          <Card className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <MessageSquare size={14} className="text-content-tertiary" />
              <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('rfi.label_question', { defaultValue: 'Question' })}
              </span>
            </div>
            <p className="text-sm text-content-primary whitespace-pre-wrap leading-relaxed">
              {rfi.question}
            </p>
          </Card>

          {/* Official Response */}
          <Card
            className={clsx(
              'p-4',
              rfi.official_response &&
                'border-green-200 bg-green-50/40 dark:bg-green-950/10 dark:border-green-900',
            )}
          >
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-2">
                <CheckCircle2
                  size={14}
                  className={
                    rfi.official_response
                      ? 'text-green-600 dark:text-green-400'
                      : 'text-content-tertiary'
                  }
                />
                <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('rfi.label_official_response', { defaultValue: 'Official response' })}
                </span>
              </div>
              {rfi.responded_at && (
                <span className="text-xs text-content-tertiary">
                  {formatDateTime(rfi.responded_at)}
                </span>
              )}
            </div>
            {rfi.official_response ? (
              <>
                <p className="text-sm text-content-primary whitespace-pre-wrap leading-relaxed">
                  {rfi.official_response}
                </p>
                {rfi.responded_by && (
                  <p className="mt-3 text-xs text-content-tertiary">
                    {t('rfi.responded_by', {
                      defaultValue: 'Responded by {{name}}',
                      name: displayUser(rfi.responded_by),
                    })}
                  </p>
                )}
              </>
            ) : responding ? (
              <InlineRespondForm
                isPending={respondMut.isPending}
                onSubmit={(data) => respondMut.mutate(data)}
                onCancel={() => setResponding(false)}
              />
            ) : (
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm text-content-tertiary italic">
                  {t('rfi.no_response_yet', {
                    defaultValue: 'No response yet.',
                  })}
                </p>
                {rfi.status === 'open' && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => setResponding(true)}
                    icon={<MessageSquare size={14} />}
                  >
                    {t('rfi.action_respond', { defaultValue: 'Respond' })}
                  </Button>
                )}
              </div>
            )}
          </Card>

          {/* Attachments — resolved from linked_drawing_ids */}
          {linkedIds.length > 0 && (
            <Card className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <Paperclip size={14} className="text-content-tertiary" />
                <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('rfi.section_attachments', { defaultValue: 'Attachments' })}
                </span>
                <span className="text-2xs text-content-quaternary">
                  ({linkedIds.length})
                </span>
              </div>
              {attachmentsQuery.isLoading ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="h-4 w-4 animate-spin text-oe-blue" />
                </div>
              ) : (
                <ul className="divide-y divide-border-light">
                  {attachmentsResolved.map((doc) => (
                    <li key={doc.id}>
                      <Link
                        to={`/projects/${rfi.project_id}/files?file=${encodeURIComponent(doc.id)}`}
                        className="flex items-center gap-3 py-2 hover:bg-surface-secondary/60 transition-colors rounded-md px-2 -mx-2 group"
                      >
                        <FileText size={14} className="text-content-tertiary shrink-0" />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm text-content-primary truncate">
                            {doc.filename || '—'}
                          </p>
                          <p className="text-xs text-content-tertiary truncate">
                            {doc.category}
                          </p>
                        </div>
                        <ExternalLink
                          size={12}
                          className="text-content-quaternary opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                        />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          {/* Activity journal (item #13) — RFI lifecycle history sourced
              from oe_activity_log via GET /v1/rfi/{id}/activity/. Renders
              each status transition as a "from -> to by {actor} at {time}"
              row, reusing the shared Card/Badge primitives and the page's
              existing user-name resolution (mirrors the projects
              StatusHistoryTimeline pattern, kept inside the rfi feature). */}
          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <History size={14} className="text-content-tertiary" />
              <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('rfi.section_history', { defaultValue: 'History' })}
              </span>
            </div>
            {activityQuery.isLoading ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="h-4 w-4 animate-spin text-oe-blue" />
              </div>
            ) : activityQuery.isError ? (
              <p className="text-sm text-content-tertiary">
                {t('rfi.history_error', {
                  defaultValue: 'Could not load the activity history.',
                })}
              </p>
            ) : activityEntries.length === 0 ? (
              <p className="text-sm text-content-tertiary italic">
                {t('rfi.history_empty', {
                  defaultValue: 'No activity recorded yet.',
                })}
              </p>
            ) : (
              <ol className="space-y-2.5">
                {activityEntries.map((entry) => {
                  const actor = displayUser(entry.actor_id);
                  return (
                    <li
                      key={entry.id}
                      className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2"
                    >
                      <div className="flex items-center gap-1.5">
                        <ActivityStatusToken status={entry.from_status} />
                        <ArrowRight
                          size={13}
                          className="shrink-0 text-content-tertiary"
                          aria-label={t('rfi.history_changed_to', {
                            defaultValue: 'changed to',
                          })}
                        />
                        <ActivityStatusToken status={entry.to_status} />
                      </div>
                      <div className="ml-auto flex flex-wrap items-center gap-x-2 text-xs text-content-tertiary">
                        {actor && actor !== '—' && (
                          <span className="text-content-secondary">
                            {t('rfi.history_by', {
                              defaultValue: 'by {{name}}',
                              name: actor,
                            })}
                          </span>
                        )}
                        <span className="whitespace-nowrap">
                          {formatDateTime(entry.created_at)}
                        </span>
                      </div>
                      {entry.reason && (
                        <p className="w-full text-xs text-content-secondary">
                          {entry.reason}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
            <TruncationNotice
              page={{ items: activityEntries, total: activityTotal }}
              className="mt-2"
            />
          </Card>

          {/* Bottom actions when answered, in case user scrolled */}
          {rfi.status === 'answered' && (
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={handleClose}
                disabled={closeMut.isPending}
                icon={
                  closeMut.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <CheckCircle2 size={14} />
                  )
                }
              >
                {t('rfi.action_close', { defaultValue: 'Close RFI' })}
              </Button>
            </div>
          )}
        </div>

        {/* Right column — meta panel */}
        <div className="space-y-4">
          {/* Routed approval workflow (feature 06). When the project has an
              active "rfi" approval route the picker lets a manager start a
              multi-step sign-off on the RFI; an approved chain re-affirms the
              answer, a rejection reopens it. Projects with no route configured
              keep the direct Respond / Close actions. */}
          <ApprovalInstanceCard
            targetKind="rfi"
            targetId={rfi.id}
            projectId={rfi.project_id}
          />

          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <User size={14} className="text-content-tertiary" />
              <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('rfi.meta_people', { defaultValue: 'People' })}
              </span>
            </div>
            <dl className="space-y-3">
              <Row label={t('rfi.field_raised_by', { defaultValue: 'Raised by' })}>
                {displayUser(rfi.raised_by)}
              </Row>
              <Row
                label={t('rfi.field_assigned_to', {
                  defaultValue: 'Assigned To',
                })}
              >
                {displayUser(rfi.assigned_to)}
              </Row>
              <Row
                label={t('rfi.field_ball_in_court', {
                  defaultValue: 'Ball in Court',
                })}
              >
                {displayUser(rfi.ball_in_court)}
              </Row>
            </dl>
          </Card>

          {/* Classification — priority + discipline */}
          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('rfi.meta_classification', {
                  defaultValue: 'Classification',
                })}
              </span>
            </div>
            <dl className="space-y-3">
              <Row label={t('rfi.field_priority', { defaultValue: 'Priority' })}>
                {rfi.priority ? (
                  <span className="inline-flex items-center gap-2">
                    <span
                      className={clsx(
                        'inline-block h-2 w-2 rounded-full',
                        PRIORITY_DOT[rfi.priority],
                      )}
                      aria-hidden="true"
                    />
                    {t(`rfi.priority_${rfi.priority}`, {
                      defaultValue:
                        rfi.priority.charAt(0).toUpperCase() + rfi.priority.slice(1),
                    })}
                  </span>
                ) : (
                  '—'
                )}
              </Row>
              <Row label={t('rfi.field_discipline', { defaultValue: 'Discipline' })}>
                {rfi.discipline
                  ? t(`rfi.discipline_${rfi.discipline}`, {
                      defaultValue:
                        rfi.discipline.charAt(0).toUpperCase() +
                        rfi.discipline.slice(1),
                    })
                  : '—'}
              </Row>
            </dl>
          </Card>

          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <CalendarClock size={14} className="text-content-tertiary" />
              <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('rfi.meta_schedule', { defaultValue: 'Schedule' })}
              </span>
            </div>
            <dl className="space-y-3">
              <Row
                label={t('rfi.field_due_date', {
                  defaultValue: 'Response Due Date',
                })}
              >
                <span
                  className={
                    isOverdue ? 'text-semantic-error font-semibold' : undefined
                  }
                >
                  {formatDate(rfi.response_due_date)}
                </span>
              </Row>
              <Row
                label={t('rfi.field_date_required', {
                  defaultValue: 'Date required',
                })}
              >
                {formatDate(rfi.date_required)}
              </Row>
              <Row label={t('common.created_at', { defaultValue: 'Created' })}>
                {formatDateTime(rfi.created_at)}
              </Row>
              <Row label={t('common.updated_at', { defaultValue: 'Updated' })}>
                {formatDateTime(rfi.updated_at)}
              </Row>
            </dl>
          </Card>

          {(rfi.cost_impact || rfi.schedule_impact) && (
            <Card className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle size={14} className="text-content-tertiary" />
                <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('rfi.meta_impact', { defaultValue: 'Impact' })}
                </span>
              </div>
              <dl className="space-y-3">
                {rfi.cost_impact && (
                  <Row
                    label={t('rfi.field_cost_impact_value', {
                      defaultValue: 'Cost exposure',
                    })}
                  >
                    <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400 font-medium">
                      <AlertTriangle size={12} />
                      {rfi.cost_impact_value
                        ? `${rfi.cost_impact_value}${projectCurrency ? ` ${projectCurrency}` : ''}`
                        : '—'}
                    </span>
                  </Row>
                )}
                {rfi.schedule_impact && (
                  <Row
                    label={t('rfi.field_schedule_impact_days', {
                      defaultValue: 'Schedule slip (days)',
                    })}
                  >
                    <span className="inline-flex items-center gap-1 text-orange-600 dark:text-orange-400 font-medium">
                      <Clock size={12} />
                      {rfi.schedule_impact_days ?? '—'}
                    </span>
                  </Row>
                )}
              </dl>
            </Card>
          )}

          {rfi.change_order_id && (
            <Card className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('rfi.meta_linked', { defaultValue: 'Linked' })}
                </span>
              </div>
              <Link
                to="/changeorders"
                className="text-sm text-oe-blue hover:underline"
              >
                {t('rfi.linked_change_order', {
                  defaultValue: 'View linked change order',
                })}
              </Link>
            </Card>
          )}
        </div>
      </div>

      {/* Mobile-friendly close button if responding overlay open on small viewport */}
      {responding && (
        <button
          type="button"
          aria-label={t('common.close', { defaultValue: 'Close' })}
          onClick={() => setResponding(false)}
          className="sr-only"
        >
          <X size={14} />
        </button>
      )}

      {/* Edit modal - reuses the create form seeded from this RFI, wired to
          the PATCH endpoint. Keyed on the RFI id so it re-seeds cleanly. */}
      {editing && (
        <CreateRFIModal
          key={rfi.id}
          editing={rfi}
          onClose={() => setEditing(false)}
          onSubmit={(data) => updateMut.mutate(data)}
          isPending={updateMut.isPending}
          projectName={project?.name}
          projectId={rfi.project_id}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

export default RFIDetailPage;
