// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Generic client / partner portal landing (magic-link surface).
 *
 * The single role-appropriate destination for a portal magic link. Previously
 * EVERY role's magic URL pointed at /portal/payments (the subcontractor payment
 * portal), so a client / investor / consultant landed on a page that was not
 * theirs. This page consumes the token, then either:
 *
 *   - navigates to the inviter-chosen `redirect_path` when the link carried one
 *     (the inviter was deliberate), or
 *   - renders a role-aware landing: every role sees their accessible projects
 *     and progress reports; clients / investors / consultants also see executed
 *     change orders; building users also see the tickets they filed.
 *
 * Subcontractors / suppliers are routed straight to /portal/payments (their
 * magic URL defaults there and is unaffected); if one lands here anyway, a
 * shortcut takes them to the payment portal.
 *
 * Auth model mirrors PortalPaymentsPage: magic-link SESSION token (NOT the
 * internal JWT), kept in sessionStorage. Renders WITHOUT the internal app shell
 * since it is reachable by external parties.
 */

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Loader2,
  AlertCircle,
  KeyRound,
  ArrowLeft,
  FileText,
  FolderOpen,
  GitPullRequestArrow,
  LifeBuoy,
  Receipt,
  ExternalLink,
  Download,
  Boxes,
  X,
} from 'lucide-react';
import { Badge, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { openInNewTab } from '@/shared/lib/desktop';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { BIMViewer } from '@/shared/ui/BIMViewer';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { PortalProgressReportsTab } from './PortalProgressReportsTab';
import {
  consumePortalMagicLink,
  getPortalSessionToken,
  getMyPortalProfile,
  listMyChangeOrders,
  listMyInvoices,
  listMyTickets,
  listMyDocuments,
  fetchMyDocumentBlob,
  listMyBimModels,
  fetchMyBimElements,
  myBimGeometryUrl,
  type PortalChangeOrder,
  type PortalInvoice,
  type PortalTicket,
  type PortalSharedDocument,
  type PortalBimModel,
} from './api';
import { PORTAL_PAYMENTS_PATH } from './portalLanding';

type Tab = 'progress' | 'change_orders' | 'invoices' | 'tickets' | 'model' | 'documents';

// Roles that see executed change orders on their landing.
const CHANGE_ORDER_ROLES = new Set(['client', 'investor', 'consultant']);
// Roles that see issued invoices on their landing.
const INVOICE_ROLES = new Set(['client', 'investor', 'consultant']);
// Roles that see the tickets they filed on their landing.
const TICKET_ROLES = new Set(['client', 'building_user']);
// Roles that see shared BIM/CAD models (view-only 3D viewer) on their landing.
const MODEL_ROLES = new Set(['client', 'investor', 'consultant']);

export function PortalHomePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const magicToken = params.get('token');

  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const escapeTo = isAuthenticated ? '/' : '/login';

  const [authed, setAuthed] = useState<boolean>(() => !!getPortalSessionToken());
  const [authError, setAuthError] = useState<string | null>(null);
  const [consuming, setConsuming] = useState<boolean>(!!magicToken);

  // Guards the one-time consume against StrictMode's double-invoke / any
  // remount - mirrors PortalPaymentsPage. The first call consumes the link and
  // opens the session; a duplicate would get "already consumed" and flip the
  // UI to a false error even though a valid session token was just stored.
  const consumedTokenRef = useRef<string | null>(null);

  useEffect(() => {
    if (!magicToken) return;
    if (consumedTokenRef.current === magicToken) return;
    consumedTokenRef.current = magicToken;
    setConsuming(true);
    setAuthError(null);
    consumePortalMagicLink(magicToken)
      .then((res) => {
        setAuthed(true);
        // An explicit, inviter-chosen redirect wins: drop the user straight on
        // the page meant for them. Strip the token first so it never rides in
        // history. Guard against an open-redirect by only honouring same-origin
        // app paths ("/..." but not "//host" or a full URL).
        const target = res.redirect_path?.trim();
        if (target && target.startsWith('/') && !target.startsWith('//')) {
          navigate(target, { replace: true });
        }
      })
      .catch((err: unknown) => {
        // A valid session token already landed (duplicate consume where the
        // first succeeded) - trust it rather than show the loser's error.
        if (getPortalSessionToken()) {
          setAuthed(true);
          return;
        }
        setAuthError(err instanceof Error ? err.message : 'Sign-in failed');
      })
      .finally(() => {
        setConsuming(false);
        const next = new URLSearchParams(params);
        next.delete('token');
        setParams(next, { replace: true });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [magicToken]);

  if (consuming) {
    return (
      <CenteredShell>
        <Card padding="lg" className="flex flex-col items-center gap-3 text-center">
          <Loader2 className="animate-spin text-oe-blue" size={28} />
          <p className="text-sm text-content-secondary">
            {t('homeportal.signing_in', { defaultValue: 'Signing you in...' })}
          </p>
        </Card>
      </CenteredShell>
    );
  }

  if (!authed) {
    return (
      <CenteredShell>
        <Card padding="none" className="w-full max-w-md">
          <EmptyState
            icon={authError ? <AlertCircle size={22} /> : <KeyRound size={22} />}
            title={
              authError
                ? t('homeportal.signin_failed', { defaultValue: 'Sign-in failed' })
                : t('homeportal.signin_title', {
                    defaultValue: 'Sign in to your portal',
                  })
            }
            description={
              authError ??
              t('homeportal.signin_prompt', {
                defaultValue: 'Open the secure link from your invitation email to continue.',
              })
            }
          />
        </Card>
        <Link
          to={escapeTo}
          className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue transition-colors hover:underline"
        >
          <ArrowLeft size={14} />
          {t('homeportal.back_to_app', { defaultValue: 'Back to OpenConstructionERP' })}
        </Link>
      </CenteredShell>
    );
  }

  return (
    <CenteredShell>
      <PortalHomeContent />
    </CenteredShell>
  );
}

function PortalHomeContent() {
  const { t } = useTranslation();

  const profileQ = useQuery({
    queryKey: ['portal-home', 'me'],
    queryFn: () => getMyPortalProfile(),
    staleTime: 60_000,
  });

  const role = profileQ.data?.portal_role ?? '';
  const showChangeOrders = CHANGE_ORDER_ROLES.has(role);
  const showInvoices = INVOICE_ROLES.has(role);
  const showTickets = TICKET_ROLES.has(role);
  const modelsRoleEligible = MODEL_ROLES.has(role);

  // Documents are shared with any role, so the tab always shows. This lightweight
  // query drives the tab count and, sharing DocumentsTab's cache key, doubles as
  // its prefetch (React Query dedupes the two into a single request).
  const documentsQ = useQuery({
    queryKey: ['portal-home', 'documents'],
    queryFn: () => listMyDocuments(),
    staleTime: 60_000,
  });

  const invoicesQ = useQuery({
    queryKey: ['portal-home', 'invoices'],
    queryFn: () => listMyInvoices({ limit: 100 }),
    enabled: showInvoices,
    staleTime: 60_000,
  });

  // BIM/CAD models shared for view-only viewing. Self-hiding: even for an
  // eligible role, the tab only appears once at least one model has
  // actually been shared (no point showing an always-empty tab).
  const modelsQ = useQuery({
    queryKey: ['portal-home', 'models'],
    queryFn: () => listMyBimModels({ limit: 100 }),
    enabled: modelsRoleEligible,
    staleTime: 60_000,
  });
  const showModels = modelsRoleEligible && (modelsQ.data?.total ?? 0) > 0;

  const tabs = (
    [
      {
        id: 'progress' as Tab,
        label: t('homeportal.tab_progress', { defaultValue: 'Progress Reports' }),
        icon: FileText,
        show: true,
      },
      {
        id: 'change_orders' as Tab,
        label: t('homeportal.tab_change_orders', { defaultValue: 'Change Orders' }),
        icon: GitPullRequestArrow,
        show: showChangeOrders,
      },
      {
        id: 'invoices' as Tab,
        label: t('homeportal.tab_invoices', { defaultValue: 'Invoices' }),
        icon: Receipt,
        show: showInvoices,
        count: invoicesQ.data?.total,
      },
      {
        id: 'tickets' as Tab,
        label: t('homeportal.tab_tickets', { defaultValue: 'My Tickets' }),
        icon: LifeBuoy,
        show: showTickets,
      },
      {
        id: 'model' as Tab,
        label: t('homeportal.tab_models', { defaultValue: 'BIM Models' }),
        icon: Boxes,
        show: showModels,
        count: modelsQ.data?.total,
      },
      {
        id: 'documents' as Tab,
        label: t('homeportal.documents_tab', { defaultValue: 'Documents' }),
        icon: FolderOpen,
        show: true,
        count: documentsQ.data?.total,
      },
    ] as { id: Tab; label: string; icon: React.ElementType; show: boolean; count?: number }[]
  ).filter((it) => it.show);

  const [tab, setTab] = useState<Tab>('progress');

  if (profileQ.isLoading) {
    return (
      <Card padding="lg" className="flex w-full max-w-2xl flex-col items-center gap-3 text-center">
        <Loader2 className="animate-spin text-oe-blue" size={24} />
        <p className="text-sm text-content-secondary">
          {t('homeportal.loading_profile', { defaultValue: 'Loading your portal...' })}
        </p>
      </Card>
    );
  }
  if (profileQ.isError) {
    return (
      <Card padding="none" className="w-full max-w-2xl">
        <EmptyState
          icon={<AlertCircle size={22} />}
          title={t('homeportal.profile_error', { defaultValue: 'Could not load your portal' })}
          description={t('homeportal.profile_error_desc', {
            defaultValue: 'Please refresh the page or reopen your invitation link.',
          })}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => {
              void profileQ.refetch();
            },
          }}
        />
      </Card>
    );
  }

  return (
    <div className="w-full max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-content-primary">
          {t('homeportal.title', { defaultValue: 'Your portal' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('homeportal.subtitle', {
            defaultValue: 'Everything shared with you, in one place.',
          })}
        </p>
      </div>

      {/* Subcontractors / suppliers belong on the payment portal; if one lands
          here, offer a one-click shortcut. */}
      {(role === 'subcontractor' || role === 'supplier') && (
        <Card padding="sm" className="border-oe-blue/30 bg-oe-blue-subtle/40">
          <Link
            to={PORTAL_PAYMENTS_PATH}
            className="inline-flex items-center gap-2 text-sm font-medium text-oe-blue hover:underline"
          >
            <Receipt size={16} />
            {t('homeportal.go_to_payments', {
              defaultValue: 'Go to your payment applications',
            })}
          </Link>
        </Card>
      )}

      {tabs.length > 1 ? (
        <nav className="flex gap-1 border-b border-border-light">
          {tabs.map((it) => {
            const Icon = it.icon;
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => setTab(it.id)}
                className={clsx(
                  '-mb-px flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                  tab === it.id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {it.label}
                {typeof it.count === 'number' && it.count > 0 ? (
                  <span
                    className={clsx(
                      'ml-0.5 rounded-full px-1.5 text-2xs font-semibold',
                      tab === it.id
                        ? 'bg-oe-blue-subtle text-oe-blue-text'
                        : 'bg-surface-secondary text-content-tertiary',
                    )}
                  >
                    {it.count}
                  </span>
                ) : null}
              </button>
            );
          })}
        </nav>
      ) : null}

      {/* Default to progress reports for any role whose active tab is not
          available (e.g. a one-tab role). */}
      {tab === 'change_orders' && showChangeOrders ? (
        <ChangeOrdersTab />
      ) : tab === 'invoices' && showInvoices ? (
        <InvoicesTab />
      ) : tab === 'tickets' && showTickets ? (
        <TicketsTab />
      ) : tab === 'model' && showModels ? (
        <ModelsTab />
      ) : tab === 'documents' ? (
        <DocumentsTab />
      ) : (
        <PortalProgressReportsTab />
      )}
    </div>
  );
}

function CenteredShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-surface-secondary px-4 py-6">
      <div className="mx-auto flex w-full max-w-2xl flex-col items-center">{children}</div>
    </div>
  );
}

/* ── Change orders ─────────────────────────────────────────────────────────*/

const CO_STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'warning' | 'success' | 'error'> = {
  approved: 'success',
  executed: 'success',
  rejected: 'error',
  closed: 'neutral',
};

function money(amount: string | null, currency: string): string {
  if (amount === null) return '-';
  return currency ? `${currency} ${amount}` : amount;
}

function ChangeOrdersTab() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['portal-home', 'change-orders'],
    queryFn: () => listMyChangeOrders({ limit: 100 }),
  });
  const items = q.data?.items ?? [];

  if (q.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={3} />
      </Card>
    );
  }
  if (q.error) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<AlertCircle size={22} />}
          title={t('homeportal.co_load_failed', {
            defaultValue: 'Could not load change orders',
          })}
          description={q.error instanceof Error ? q.error.message : ''}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void q.refetch(),
          }}
        />
      </Card>
    );
  }
  if (items.length === 0) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<GitPullRequestArrow size={22} />}
          title={t('homeportal.co_empty', { defaultValue: 'No change orders shared yet' })}
          description={t('homeportal.co_empty_desc', {
            defaultValue: 'Executed change orders shared with you will appear here.',
          })}
        />
      </Card>
    );
  }
  return (
    <ul className="space-y-3">
      {items.map((co) => (
        <ChangeOrderCard key={co.id} co={co} />
      ))}
    </ul>
  );
}

function ChangeOrderCard({ co }: { co: PortalChangeOrder }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-xl border border-border bg-surface-primary p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="font-mono text-2xs text-content-tertiary">{co.code}</span>
          <p className="truncate text-sm font-medium text-content-primary">{co.title}</p>
        </div>
        <Badge variant={CO_STATUS_VARIANT[co.status] ?? 'neutral'} dot>
          {t(`homeportal.co_status_${co.status}`, { defaultValue: co.status })}
        </Badge>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('homeportal.co_amount', { defaultValue: 'Approved amount' })}
          </dt>
          <dd className="font-medium text-content-primary">
            {money(co.approved_amount, co.currency)}
          </dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('homeportal.co_time', { defaultValue: 'Time impact' })}
          </dt>
          <dd className="text-content-secondary">
            {co.approved_time_days !== null
              ? t('homeportal.co_days', {
                  defaultValue: '{{count}} days',
                  count: co.approved_time_days,
                })
              : '-'}
          </dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('homeportal.co_approved_at', { defaultValue: 'Approved' })}
          </dt>
          <dd className="text-content-secondary">
            {co.approved_at ? <DateDisplay value={co.approved_at} /> : '-'}
          </dd>
        </div>
      </dl>
    </li>
  );
}

/* ── Invoices ──────────────────────────────────────────────────────────────*/

const INVOICE_STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'warning' | 'success' | 'error'> =
  {
    issued: 'blue',
    sent: 'blue',
    partial: 'warning',
    overdue: 'error',
    paid: 'success',
    cancelled: 'neutral',
  };

function InvoicesTab() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['portal-home', 'invoices'],
    queryFn: () => listMyInvoices({ limit: 100 }),
  });
  const items = q.data?.items ?? [];

  if (q.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={3} />
      </Card>
    );
  }
  if (q.error) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<AlertCircle size={22} />}
          title={t('homeportal.inv_load_failed', { defaultValue: 'Could not load invoices' })}
          description={q.error instanceof Error ? q.error.message : ''}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void q.refetch(),
          }}
        />
      </Card>
    );
  }
  if (items.length === 0) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<Receipt size={22} />}
          title={t('homeportal.inv_empty', { defaultValue: 'No invoices shared yet' })}
          description={t('homeportal.inv_empty_desc', {
            defaultValue: 'Invoices shared with you will appear here.',
          })}
        />
      </Card>
    );
  }
  return (
    <ul className="space-y-3">
      {items.map((inv) => (
        <InvoiceCard key={inv.id} inv={inv} />
      ))}
    </ul>
  );
}

function InvoiceCard({ inv }: { inv: PortalInvoice }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-xl border border-border bg-surface-primary p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="font-mono text-2xs text-content-tertiary">{inv.invoice_number}</span>
          <p className="truncate text-sm font-medium text-content-primary">
            {money(inv.amount_total, inv.currency_code)}
          </p>
        </div>
        <Badge variant={INVOICE_STATUS_VARIANT[inv.status] ?? 'neutral'} dot>
          {t(`homeportal.inv_status_${inv.status}`, { defaultValue: inv.status })}
        </Badge>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('homeportal.inv_date', { defaultValue: 'Invoice date' })}
          </dt>
          <dd className="text-content-secondary">
            {inv.invoice_date ? <DateDisplay value={inv.invoice_date} /> : '-'}
          </dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('homeportal.inv_due', { defaultValue: 'Due' })}
          </dt>
          <dd className="text-content-secondary">
            {inv.due_date ? <DateDisplay value={inv.due_date} /> : '-'}
          </dd>
        </div>
      </dl>
    </li>
  );
}

/* ── Tickets ───────────────────────────────────────────────────────────────*/

const TICKET_STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'warning' | 'success' | 'error'> = {
  new: 'blue',
  in_progress: 'warning',
  resolved: 'success',
  closed: 'neutral',
};

function TicketsTab() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['portal-home', 'tickets'],
    queryFn: () => listMyTickets({ limit: 100 }),
  });
  const items = q.data?.items ?? [];

  if (q.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={3} />
      </Card>
    );
  }
  if (q.error) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<AlertCircle size={22} />}
          title={t('homeportal.tk_load_failed', { defaultValue: 'Could not load tickets' })}
          description={q.error instanceof Error ? q.error.message : ''}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void q.refetch(),
          }}
        />
      </Card>
    );
  }
  if (items.length === 0) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<LifeBuoy size={22} />}
          title={t('homeportal.tk_empty', { defaultValue: 'No tickets yet' })}
          description={t('homeportal.tk_empty_desc', {
            defaultValue: 'Service tickets you file will appear here.',
          })}
        />
      </Card>
    );
  }
  return (
    <ul className="space-y-3">
      {items.map((tk) => (
        <TicketCard key={tk.id} ticket={tk} />
      ))}
    </ul>
  );
}

function TicketCard({ ticket }: { ticket: PortalTicket }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-xl border border-border bg-surface-primary p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="font-mono text-2xs text-content-tertiary">{ticket.ticket_number}</span>
          <p className="truncate text-sm font-medium text-content-primary">{ticket.title}</p>
        </div>
        <Badge variant={TICKET_STATUS_VARIANT[ticket.status] ?? 'neutral'} dot>
          {t(`homeportal.tk_status_${ticket.status}`, { defaultValue: ticket.status })}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-content-tertiary">
        <span>
          {t('homeportal.tk_reported', { defaultValue: 'Reported' })}:{' '}
          <DateDisplay value={ticket.reported_at} />
        </span>
        {ticket.sla_due_at ? (
          <span>
            {t('homeportal.tk_sla', { defaultValue: 'SLA due' })}:{' '}
            <DateDisplay value={ticket.sla_due_at} />
          </span>
        ) : null}
      </div>
    </li>
  );
}

/* ── Documents ─────────────────────────────────────────────────────────────*/

// Common mime types mapped to a short, upper-case format tag. Anything not
// here falls back to a derived subtype tag or a translated "File" label.
const MIME_SHORT_LABELS: Record<string, string> = {
  'application/pdf': 'PDF',
  'application/zip': 'ZIP',
  'application/json': 'JSON',
  'application/xml': 'XML',
  'text/xml': 'XML',
  'text/csv': 'CSV',
  'text/plain': 'TXT',
  'text/html': 'HTML',
  'application/msword': 'DOC',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
  'application/vnd.ms-excel': 'XLS',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'XLSX',
  'application/vnd.ms-powerpoint': 'PPT',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPTX',
};

/**
 * A short upper-case format tag for a mime type (e.g. "PDF", "PNG"), or null
 * when only a generic word fits - the caller supplies the translated fallback.
 */
function shortMimeLabel(mimeType: string): string | null {
  const mime = mimeType.trim().toLowerCase();
  if (!mime) return null;
  const mapped = MIME_SHORT_LABELS[mime];
  if (mapped) return mapped;
  const subtype = mime.split('/')[1] ?? '';
  const beforeSuffix = subtype.split('+')[0] ?? subtype;
  const token = beforeSuffix.split('.').pop() ?? '';
  if (token.length >= 2 && token.length <= 5 && /^[a-z0-9]+$/.test(token)) {
    return token.toUpperCase();
  }
  return null;
}

/** Human-readable byte size (e.g. "2.4 MB"); a plain dash when unknown. */
function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[unit] ?? 'B'}`;
}

function DocumentsTab() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['portal-home', 'documents'],
    queryFn: () => listMyDocuments(),
    staleTime: 60_000,
  });
  const items = q.data?.items ?? [];

  if (q.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={3} />
      </Card>
    );
  }
  if (q.error) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<AlertCircle size={22} />}
          title={t('homeportal.documents_load_failed', { defaultValue: 'Could not load documents' })}
          description={q.error instanceof Error ? q.error.message : ''}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void q.refetch(),
          }}
        />
      </Card>
    );
  }
  if (items.length === 0) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<FolderOpen size={22} />}
          title={t('homeportal.documents_empty', {
            defaultValue: 'No documents shared with you yet',
          })}
          description={t('homeportal.documents_empty_desc', {
            defaultValue: 'Documents shared with you will appear here.',
          })}
        />
      </Card>
    );
  }
  return (
    <ul className="space-y-3">
      {items.map((doc) => (
        <DocumentCard key={doc.id} doc={doc} />
      ))}
    </ul>
  );
}

function DocumentCard({ doc }: { doc: PortalSharedDocument }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState<'open' | 'download' | null>(null);
  const typeLabel =
    shortMimeLabel(doc.mime_type) ?? t('homeportal.documents_type_file', { defaultValue: 'File' });

  // The content endpoint rides the session token, so a link cannot carry the
  // Authorization header: fetch the bytes as a Blob and hand them to `use`,
  // which turns them into a short-lived object URL for open / download.
  const withBlob = async (use: (blob: Blob) => void): Promise<void> => {
    try {
      const blob = await fetchMyDocumentBlob(doc.id);
      if (blob === null) {
        addToast({
          type: 'error',
          title: t('homeportal.documents_gone', {
            defaultValue: 'This document is no longer available.',
          }),
        });
        return;
      }
      use(blob);
    } catch (err) {
      addToast({
        type: 'error',
        title:
          err instanceof Error
            ? err.message
            : t('homeportal.documents_open_failed', { defaultValue: 'Could not open the document.' }),
      });
    }
  };

  const onOpen = async () => {
    setBusy('open');
    await withBlob((blob) => {
      const url = URL.createObjectURL(blob);
      openInNewTab(url);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    });
    setBusy(null);
  };

  const onDownload = async () => {
    setBusy('download');
    await withBlob((blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = doc.name || 'document';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
    setBusy(null);
  };

  return (
    <li className="rounded-xl border border-border bg-surface-primary p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <FileText size={16} className="shrink-0 text-content-tertiary" />
          <span className="truncate text-sm font-medium text-content-primary">{doc.name}</span>
        </div>
        <Badge variant="neutral" size="sm">
          {typeLabel}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-content-tertiary">
        <span>{formatFileSize(doc.file_size)}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy !== null}
          onClick={onOpen}
          className="inline-flex items-center gap-1 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === 'open' ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <ExternalLink size={12} />
          )}
          {t('homeportal.documents_open', { defaultValue: 'Open' })}
        </button>
        <button
          type="button"
          disabled={busy !== null}
          onClick={onDownload}
          className="inline-flex items-center gap-1 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === 'download' ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Download size={12} />
          )}
          {t('homeportal.documents_download', { defaultValue: 'Download' })}
        </button>
      </div>
    </li>
  );
}

/* ── BIM/CAD models (view-only) ────────────────────────────────────────────*/

function ModelsTab() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['portal-home', 'models'],
    queryFn: () => listMyBimModels({ limit: 100 }),
    staleTime: 60_000,
  });
  const items = q.data?.items ?? [];
  const [openModel, setOpenModel] = useState<PortalBimModel | null>(null);

  if (q.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={3} />
      </Card>
    );
  }
  if (q.error) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<AlertCircle size={22} />}
          title={t('homeportal.models_load_failed', { defaultValue: 'Could not load models' })}
          description={q.error instanceof Error ? q.error.message : ''}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void q.refetch(),
          }}
        />
      </Card>
    );
  }
  if (items.length === 0) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<Boxes size={22} />}
          title={t('homeportal.models_empty', { defaultValue: 'No 3D models shared with you yet' })}
          description={t('homeportal.models_empty_desc', {
            defaultValue: 'BIM/CAD models shared with you will appear here for view-only viewing.',
          })}
        />
      </Card>
    );
  }
  return (
    <>
      <ul className="space-y-3">
        {items.map((model) => (
          <ModelCard key={model.id} model={model} onOpen={() => setOpenModel(model)} />
        ))}
      </ul>
      {openModel && (
        <ModelViewerModal model={openModel} onClose={() => setOpenModel(null)} />
      )}
    </>
  );
}

function ModelCard({
  model,
  onOpen,
}: {
  model: PortalBimModel;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li className="rounded-xl border border-border bg-surface-primary p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Boxes size={16} className="shrink-0 text-content-tertiary" />
          <span className="truncate text-sm font-medium text-content-primary">{model.name}</span>
        </div>
        {model.discipline ? (
          <Badge variant="neutral" size="sm">
            {model.discipline}
          </Badge>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-content-tertiary">
        <span>
          {t('homeportal.models_element_count', {
            defaultValue: '{{count}} elements',
            count: model.element_count,
          })}
        </span>
        {model.model_format ? <span>{model.model_format.toUpperCase()}</span> : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex items-center gap-1 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue"
        >
          <ExternalLink size={12} />
          {t('homeportal.models_open', { defaultValue: 'View 3D model' })}
        </button>
      </div>
    </li>
  );
}

/**
 * Full-screen, view-only 3D viewer for one shared BIM/CAD model. The
 * BIMViewer itself is rendered with `readOnly` so no measure / section /
 * walk-mode tools or authoring actions are available - the client can only
 * look around, isolate/hide elements and inspect the read-only properties
 * panel. Elements load in skeleton mode (no BOQ links, no cost data) and
 * geometry streams from the dedicated portal geometry endpoint, which
 * authenticates via the session token carried on the URL (the browser's
 * glTF/COLLADA loader cannot send an Authorization header).
 *
 * It is also rendered with `portal` so the viewer suppresses every panel and
 * overlay that reads from an internal-JWT-gated endpoint (scan-vs-design
 * deviation, the CWICR Match tab, the on-demand Parquet properties fetch). A
 * portal client holds only the magic-link session token, so any such request
 * would 401 and the shared API client would react by hard-redirecting the
 * whole page to /login - which is exactly the "opening a shared model bounces
 * me to the login page" defect this guards against.
 */
function ModelViewerModal({
  model,
  onClose,
}: {
  model: PortalBimModel;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  const elementsQ = useQuery({
    queryKey: ['portal-home', 'model-elements', model.id],
    queryFn: () => fetchMyBimElements(model.id),
    staleTime: 60_000,
  });
  const elements = elementsQ.data?.items ?? [];
  const geometryUrl = myBimGeometryUrl(model.id);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handler, { capture: true });
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex flex-col bg-surface-primary"
    >
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border-light px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Boxes size={16} className="shrink-0 text-content-tertiary" />
          <h2 className="truncate text-sm font-semibold text-content-primary">{model.name}</h2>
          <Badge variant="neutral" size="sm">
            {t('homeportal.models_view_only', { defaultValue: 'View only' })}
          </Badge>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close', { defaultValue: 'Close' })}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-secondary transition-colors hover:bg-surface-secondary hover:text-content-primary"
        >
          <X size={18} />
        </button>
      </header>
      <div className="relative flex-1 overflow-hidden">
        <BIMViewer
          modelId={model.id}
          projectId={model.project_id}
          modelName={model.name}
          elements={elements}
          isLoading={elementsQ.isLoading}
          error={
            elementsQ.error
              ? t('homeportal.models_elements_failed', {
                  defaultValue: 'Failed to load model elements.',
                })
              : null
          }
          geometryUrl={geometryUrl}
          readOnly
          portal
        />
      </div>
    </div>,
    document.body,
  );
}
