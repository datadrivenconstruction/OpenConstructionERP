import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  Users,
  ShieldCheck,
  FileSearch,
  Plus,
  Search,
  X,
  Copy,
  Send,
  Ban,
  RotateCcw,
  FileText,
  ExternalLink,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
  DismissibleInfo,
  IntroRichText,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { projectsApi } from '@/features/projects/api';
import { fetchDocuments } from '@/features/documents/api';
import { listTickets } from '@/features/service/api';
import { copyToClipboard } from '@/shared/lib/browser';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listPortalUsers,
  listDocumentAccessLog,
  listAccessRules,
  invitePortalUser,
  resendInvite,
  suspendPortalUser,
  reactivatePortalUser,
  grantAccess,
  revokeAccess,
  type PortalUser,
  type PortalRole,
  type PortalUserStatus,
  type DocumentAccessLogEntry,
  type AccessRule,
  type AccessPermission,
} from './api';
import { ProgressReportsTab } from './ProgressReportsTab';

type Tab = 'users' | 'access_rules' | 'audit_log' | 'progress_reports';

const ROLES: PortalRole[] = [
  'client',
  'investor',
  'consultant',
  'subcontractor',
  'supplier',
  'building_user',
];

const PERMISSIONS: AccessPermission[] = ['view', 'comment', 'submit', 'sign'];

const STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  invited: 'blue',
  active: 'success',
  suspended: 'error',
  expired: 'neutral',
};

const ACTION_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  view: 'neutral',
  download: 'blue',
  sign: 'warning',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

// Legacy labelCls removed — modals migrated to <WideModalField>.

/**
 * CONN-53: map a granted resource (or an audited document) to its in-app route
 * so the admin can jump from an access rule / audit row to the thing it covers,
 * instead of reading a bare UUID. Returns null for types we cannot route to
 * (the caller then renders the id as plain text). All targets are real routes
 * registered in App.tsx (/projects/:id, /files, /service, /finance,
 * /property-dev).
 */
function portalResourceLink(type: string, id: string): string | null {
  if (!id) return null;
  switch (type) {
    case 'project':
      return `/projects/${id}`;
    case 'development':
      return '/property-dev';
    case 'document':
      return '/files';
    case 'ticket':
      return '/service';
    case 'invoice':
      return '/finance';
    default:
      return null;
  }
}

/* ─── Page ─── */

export function PortalPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>('users');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [selectedUser, setSelectedUser] = useState<PortalUser | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [grantOpen, setGrantOpen] = useState(false);

  // CONN-54 consumer: a Subcontractor's "Invite to portal" pill deep-links here
  // with ?invite=1 (plus optional name/email/role) to open the invite modal
  // pre-filled. Read once, then clear the params (replace) so a refresh or back
  // navigation does not re-open the modal.
  const [invitePrefill, setInvitePrefill] = useState<{
    email: string;
    full_name: string;
    portal_role: PortalRole;
  } | null>(null);
  useEffect(() => {
    if (searchParams.get('invite') !== '1') return;
    const role = searchParams.get('role');
    setInvitePrefill({
      email: searchParams.get('email') ?? '',
      full_name: searchParams.get('name') ?? '',
      portal_role: (ROLES as string[]).includes(role ?? '')
        ? (role as PortalRole)
        : 'client',
    });
    setInviteOpen(true);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('invite');
        next.delete('role');
        next.delete('email');
        next.delete('name');
        return next;
      },
      { replace: true },
    );
  }, [searchParams, setSearchParams]);
  const [lastInviteLink, setLastInviteLink] = useState<{
    token: string;
    expires_at: string;
    email: string;
  } | null>(null);

  const usersQ = useQuery({
    queryKey: ['portal', 'users', statusFilter],
    queryFn: () =>
      listPortalUsers({
        limit: 200,
        status: statusFilter || undefined,
      }),
  });

  const auditQ = useQuery({
    queryKey: ['portal', 'audit', selectedUser?.id],
    queryFn: () =>
      listDocumentAccessLog({
        portal_user_id: selectedUser?.id,
        limit: 200,
      }),
    enabled: tab === 'audit_log' || !!selectedUser,
  });

  const rulesQ = useQuery({
    queryKey: ['portal', 'access-rules'],
    queryFn: () => listAccessRules({ limit: 500 }),
    enabled: tab === 'access_rules',
  });

  const filteredUsers = useMemo(() => {
    const items = usersQ.data?.items ?? [];
    const s = search.toLowerCase();
    return items.filter((u) => {
      if (!s) return true;
      return (
        u.email.toLowerCase().includes(s) ||
        (u.full_name || '').toLowerCase().includes(s) ||
        u.portal_role.toLowerCase().includes(s)
      );
    });
  }, [usersQ.data, search]);

  const filteredAudit = useMemo(() => {
    const items = auditQ.data ?? [];
    const s = search.toLowerCase();
    return items.filter((e) => {
      if (!s) return true;
      return (
        e.document_type.toLowerCase().includes(s) ||
        e.action.toLowerCase().includes(s) ||
        e.document_id.toLowerCase().includes(s)
      );
    });
  }, [auditQ.data, search]);

  const isLoading =
    (tab === 'users' && usersQ.isLoading) ||
    (tab === 'audit_log' && auditQ.isLoading) ||
    (tab === 'access_rules' && rulesQ.isLoading);

  // Surface fetch failures explicitly. Without this, a failed users/audit
  // request falls through to the "No portal users yet" empty state, which
  // misleads the operator into thinking the portal is empty rather than
  // that the request failed.
  const activeError =
    tab === 'users'
      ? usersQ.error
      : tab === 'audit_log'
        ? auditQ.error
        : tab === 'access_rules'
          ? rulesQ.error
          : null;

  return (
    <div className="space-y-5">
      <Breadcrumb
        items={[{ label: t('nav.portal', { defaultValue: 'Customer / Buyer Portal' }) }]}
      />

      <PageHeader
        srTitle={t('portal.title', { defaultValue: 'Customer / Buyer Portal' })}
        subtitle={t('portal.subtitle', {
          defaultValue:
            'Invite external customers and buyers, manage scoped access to documents, and audit who saw what.',
        })}
        actions={
          <>
            {tab === 'access_rules' && (
              <Button
                variant="secondary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setGrantOpen(true)}
              >
                {t('portal.grant_access', { defaultValue: 'Grant Access' })}
              </Button>
            )}
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setInviteOpen(true)}
            >
              {t('portal.invite_user', { defaultValue: 'Invite User' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="portal"
        title={t('portal.intro_title', {
          defaultValue: 'Give outsiders exactly what they need - nothing more',
        })}
        more={
          t('portal.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('portal.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('portal.intro_link_subs', { defaultValue: 'Subcontractors' }),
            onClick: () => navigate('/subcontractors'),
          },
          {
            label: t('portal.intro_link_files', { defaultValue: 'Project documents' }),
            onClick: () => navigate('/files'),
          },
          {
            label: t('portal.intro_link_progress_claims', {
              defaultValue: 'Progress claims (Contracts)',
            }),
            onClick: () => navigate('/contracts'),
          },
        ]}
      >
        {t('portal.intro_body', {
          defaultValue:
            'Invite a client, investor or subcontractor with a magic link, then Grant Access - one rule per resource (a single project, document or invoice) and one permission (view, comment, submit or sign). Every view, download and signature they make is recorded in the audit log with IP and timestamp. Revoke access any time; nothing is visible until you explicitly grant it.',
        })}
      </DismissibleInfo>

      {lastInviteLink && (
        <MagicLinkBanner
          email={lastInviteLink.email}
          token={lastInviteLink.token}
          expiresAt={lastInviteLink.expires_at}
          onDismiss={() => setLastInviteLink(null)}
        />
      )}

      {/* Tabs */}
      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px">
          {(
            [
              { id: 'users', label: t('portal.users', { defaultValue: 'Users' }), icon: Users },
              {
                id: 'access_rules',
                label: t('portal.access_rules', { defaultValue: 'Access Rules' }),
                icon: ShieldCheck,
              },
              {
                id: 'audit_log',
                label: t('portal.audit_log', { defaultValue: 'Audit Log' }),
                icon: FileSearch,
              },
              {
                id: 'progress_reports',
                label: t('portal.progress_reports', {
                  defaultValue: 'Progress Reports',
                }),
                icon: FileText,
              },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((tabItem) => {
            const Icon = tabItem.icon;
            return (
              <button
                key={tabItem.id}
                type="button"
                onClick={() => {
                  setTab(tabItem.id);
                  setSearch('');
                  setStatusFilter('');
                }}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                  tab === tabItem.id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {tabItem.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Filters (progress-reports has its own project picker) */}
      {tab !== 'progress_reports' && (
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>
        {tab === 'users' && (
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className={clsx(inputCls, 'max-w-[200px]')}
          >
            <option value="">
              {t('common.all_statuses', { defaultValue: 'All statuses' })}
            </option>
            {(['invited', 'active', 'suspended', 'expired'] as PortalUserStatus[]).map((s) => (
              <option key={s} value={s}>
                {t(`portal.status.${s}`, { defaultValue: s })}
              </option>
            ))}
          </select>
        )}
      </div>
      )}

      {/* Body */}
      {tab === 'progress_reports' ? (
        <Card padding="md">
          <ProgressReportsTab />
        </Card>
      ) : (
      <Card padding="none">
        {isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={5} />
          </div>
        ) : activeError ? (
          <EmptyState
            icon={<X size={22} />}
            title={t('portal.load_failed', {
              defaultValue: 'Could not load portal data',
            })}
            description={getErrorMessage(activeError)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => {
                if (tab === 'users') void usersQ.refetch();
                else if (tab === 'audit_log') void auditQ.refetch();
                else if (tab === 'access_rules') void rulesQ.refetch();
              },
            }}
          />
        ) : tab === 'users' ? (
          <UserTable
            rows={filteredUsers}
            onSelect={setSelectedUser}
            onInvite={() => setInviteOpen(true)}
          />
        ) : tab === 'access_rules' ? (
          <AccessRuleTable
            rows={rulesQ.data?.items ?? []}
            users={usersQ.data?.items ?? []}
            onGrant={() => setGrantOpen(true)}
          />
        ) : (
          <AuditLogTable rows={filteredAudit} users={usersQ.data?.items ?? []} />
        )}
      </Card>
      )}

      {/* Detail Drawer */}
      {selectedUser && (
        <UserDrawer
          user={selectedUser}
          auditEntries={(auditQ.data ?? []).filter(
            (e) => e.portal_user_id === selectedUser.id,
          )}
          onClose={() => setSelectedUser(null)}
          onResent={(link) => {
            setLastInviteLink({
              email: selectedUser.email,
              token: link.token,
              expires_at: link.expires_at,
            });
          }}
        />
      )}

      {/* Invite modal */}
      {inviteOpen && (
        <InviteModal
          initial={invitePrefill ?? undefined}
          onClose={() => {
            setInviteOpen(false);
            setInvitePrefill(null);
          }}
          onInvited={(email, token, expires_at) => {
            setLastInviteLink({ email, token, expires_at });
          }}
        />
      )}

      {/* Grant modal */}
      {grantOpen && (
        <GrantAccessModal
          users={usersQ.data?.items ?? []}
          onClose={() => setGrantOpen(false)}
        />
      )}
    </div>
  );
}

/* ─── Banner: magic-link shown once ─── */

function MagicLinkBanner({
  email,
  token,
  expiresAt,
  onDismiss,
}: {
  email: string;
  token: string;
  expiresAt: string;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const copy = async () => {
    try {
      await copyToClipboard(token);
      addToast({
        type: 'success',
        title: t('portal.link_copied', { defaultValue: 'Magic link copied' }),
      });
    } catch {
      addToast({
        type: 'error',
        title: t('portal.copy_failed', { defaultValue: 'Could not copy to clipboard' }),
      });
    }
  };
  return (
    <Card padding="sm" className="border-oe-blue/30 bg-oe-blue-subtle/40">
      <div className="flex items-start gap-3">
        <Send size={18} className="mt-0.5 text-oe-blue" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-content-primary">
            {t('portal.magic_link_for', { defaultValue: 'Magic link for' })}{' '}
            <span className="font-mono">{email}</span>
          </p>
          <p className="mt-0.5 text-xs text-content-secondary">
            {t('portal.magic_link_warning', {
              defaultValue:
                'Shown once - copy and send to the user manually. Email delivery is not wired up yet.',
            })}{' '}
            ·{' '}
            {t('portal.expires_at', { defaultValue: 'Expires' })}{' '}
            <DateDisplay value={expiresAt} />
          </p>
          <code className="mt-2 block w-full truncate rounded bg-surface-secondary px-2 py-1.5 font-mono text-xs">
            {token}
          </code>
        </div>
        <div className="flex flex-col gap-1">
          <Button size="sm" variant="secondary" icon={<Copy size={12} />} onClick={copy}>
            {t('common.copy', { defaultValue: 'Copy' })}
          </Button>
          <Button size="sm" variant="ghost" onClick={onDismiss}>
            {t('common.dismiss', { defaultValue: 'Dismiss' })}
          </Button>
        </div>
      </div>
    </Card>
  );
}

/* ─── Tables ─── */

function UserTable({
  rows,
  onSelect,
  onInvite,
}: {
  rows: PortalUser[];
  onSelect: (u: PortalUser) => void;
  onInvite: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Users size={22} />}
        title={t('portal.empty_users', { defaultValue: 'No portal users yet' })}
        description={t('portal.empty_users_desc', {
          defaultValue:
            'Invite a customer, investor or subcontractor to give them scoped read access to project documents.',
        })}
        action={{
          label: t('portal.invite_user', { defaultValue: 'Invite User' }),
          onClick: onInvite,
        }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('portal.email', { defaultValue: 'Email' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.full_name', { defaultValue: 'Name' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.role', { defaultValue: 'Role' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.last_login', { defaultValue: 'Last login' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr
              key={u.id}
              onClick={() => onSelect(u)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary truncate max-w-[260px]">
                {u.email}
              </td>
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[200px]">
                {u.full_name || '—'}
              </td>
              <td className="px-4 py-2 text-xs">
                <Badge variant="neutral">
                  {t(`portal.roles.${u.portal_role}`, { defaultValue: u.portal_role })}
                </Badge>
              </td>
              <td className="px-4 py-2">
                <Badge variant={STATUS_VARIANT[u.status] ?? 'neutral'} dot>
                  {t(`portal.status.${u.status}`, { defaultValue: u.status })}
                </Badge>
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {u.last_login_at ? <DateDisplay value={u.last_login_at} /> : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AccessRuleTable({
  rows,
  users,
  onGrant,
}: {
  rows: AccessRule[];
  users: PortalUser[];
  onGrant: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userById = useMemo(() => {
    const m = new Map<string, PortalUser>();
    for (const u of users) m.set(u.id, u);
    return m;
  }, [users]);

  const revokeMut = useMutation({
    mutationFn: (ruleId: string) => revokeAccess(ruleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portal', 'access-rules'] });
      addToast({
        type: 'success',
        title: t('portal.access_revoked', { defaultValue: 'Access rule revoked' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck size={22} />}
        title={t('portal.empty_rules', { defaultValue: 'No access rules granted yet' })}
        description={t('portal.empty_rules_desc', {
          defaultValue:
            'Grant a portal user view / comment / submit / sign permission on a specific document, project or development.',
        })}
        action={{
          label: t('portal.grant_access', { defaultValue: 'Grant Access' }),
          onClick: onGrant,
        }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('portal.user', { defaultValue: 'User' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.resource_type', { defaultValue: 'Resource Type' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.resource_id', { defaultValue: 'Resource ID' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.permission', { defaultValue: 'Permission' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.expires', { defaultValue: 'Expires' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('common.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const u = userById.get(r.portal_user_id);
            return (
              <tr key={r.id} className="border-t border-border-light">
                <td className="px-4 py-2 font-mono text-xs text-content-secondary truncate max-w-[220px]">
                  {u?.email ?? r.portal_user_id.slice(0, 8)}
                </td>
                <td className="px-4 py-2 text-xs">
                  <Badge variant="neutral">
                    {t(`portal.resource_types.${r.resource_type}`, {
                      defaultValue: r.resource_type,
                    })}
                  </Badge>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-content-secondary truncate max-w-[200px]">
                  {(() => {
                    const to = portalResourceLink(r.resource_type, r.resource_id);
                    return to ? (
                      <Link
                        to={to}
                        className="inline-flex items-center gap-1 text-oe-blue hover:underline"
                        title={t('portal.open_resource', {
                          defaultValue: 'Open this resource',
                        })}
                      >
                        <span className="truncate">{r.resource_id}</span>
                        <ExternalLink size={11} className="shrink-0" />
                      </Link>
                    ) : (
                      r.resource_id
                    );
                  })()}
                </td>
                <td className="px-4 py-2">
                  <Badge variant="blue">
                    {t(`portal.permissions.${r.permission}`, { defaultValue: r.permission })}
                  </Badge>
                </td>
                <td className="px-4 py-2 text-xs text-content-secondary">
                  {r.expires_at ? <DateDisplay value={r.expires_at} /> : '—'}
                </td>
                <td className="px-4 py-2 text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Ban size={12} />}
                    loading={revokeMut.isPending && revokeMut.variables === r.id}
                    onClick={() => revokeMut.mutate(r.id)}
                  >
                    {t('common.revoke', { defaultValue: 'Revoke' })}
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AuditLogTable({
  rows,
  users,
}: {
  rows: DocumentAccessLogEntry[];
  users: PortalUser[];
}) {
  const { t } = useTranslation();
  const userById = useMemo(() => {
    const m = new Map<string, PortalUser>();
    for (const u of users) m.set(u.id, u);
    return m;
  }, [users]);
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<FileSearch size={22} />}
        title={t('portal.empty_audit', { defaultValue: 'No document access yet' })}
        description={t('portal.empty_audit_desc', {
          defaultValue:
            'Every view, download and signature event from invited portal users will be recorded here, with IP and timestamp.',
        })}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('portal.user', { defaultValue: 'User' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.document_type', { defaultValue: 'Document Type' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.document_id', { defaultValue: 'Document ID' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.action', { defaultValue: 'Action' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.ip', { defaultValue: 'IP' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.when', { defaultValue: 'When' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const u = userById.get(e.portal_user_id);
            return (
              <tr key={e.id} className="border-t border-border-light">
                <td className="px-4 py-2 font-mono text-xs text-content-secondary truncate max-w-[220px]">
                  {u?.email ?? e.portal_user_id.slice(0, 8)}
                </td>
                <td className="px-4 py-2 text-xs">
                  <Badge variant="neutral">
                    {t(`portal.document_types.${e.document_type}`, {
                      defaultValue: e.document_type,
                    })}
                  </Badge>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-content-secondary truncate max-w-[180px]">
                  {(() => {
                    const to = portalResourceLink(e.document_type, e.document_id);
                    return to ? (
                      <Link
                        to={to}
                        className="inline-flex items-center gap-1 text-oe-blue hover:underline"
                        title={t('portal.open_resource', {
                          defaultValue: 'Open this resource',
                        })}
                      >
                        <span className="truncate">{e.document_id}</span>
                        <ExternalLink size={11} className="shrink-0" />
                      </Link>
                    ) : (
                      e.document_id
                    );
                  })()}
                </td>
                <td className="px-4 py-2">
                  <Badge variant={ACTION_VARIANT[e.action] ?? 'neutral'}>
                    {t(`portal.actions.${e.action}`, { defaultValue: e.action })}
                  </Badge>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-content-secondary">
                  {e.ip_address ?? '—'}
                </td>
                <td className="px-4 py-2 text-xs text-content-secondary">
                  {e.occurred_at ? <DateDisplay value={e.occurred_at} /> : <DateDisplay value={e.created_at} />}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ─── User detail drawer ─── */

function UserDrawer({
  user,
  auditEntries,
  onClose,
  onResent,
}: {
  user: PortalUser;
  auditEntries: DocumentAccessLogEntry[];
  onClose: () => void;
  onResent: (link: { token: string; expires_at: string }) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Escape closes the drawer — matches the dialog/drawer a11y pattern used
  // elsewhere in the app (CommentDrawer, AssetDetailDrawer).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const resendMut = useMutation({
    mutationFn: () => resendInvite(user.id),
    onSuccess: (data) => {
      addToast({
        type: 'success',
        title: t('portal.invite_resent', { defaultValue: 'Invite resent' }),
      });
      onResent({
        token: data.magic_link_token,
        expires_at: data.magic_link_expires_at,
      });
      qc.invalidateQueries({ queryKey: ['portal', 'users'] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const suspendMut = useMutation({
    mutationFn: () => suspendPortalUser(user.id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('portal.suspended', { defaultValue: 'User suspended' }),
      });
      qc.invalidateQueries({ queryKey: ['portal', 'users'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const reactivateMut = useMutation({
    mutationFn: () => reactivatePortalUser(user.id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('portal.reactivated', { defaultValue: 'User reactivated' }),
      });
      qc.invalidateQueries({ queryKey: ['portal', 'users'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('portal.user_detail', {
          defaultValue: 'Portal user details',
        })}
        className="relative h-full w-full max-w-lg overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <h2 className="text-base font-semibold truncate">{user.email}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field
              label={t('portal.full_name', { defaultValue: 'Name' })}
              value={user.full_name || '—'}
            />
            <Field
              label={t('portal.role', { defaultValue: 'Role' })}
              value={
                <Badge variant="neutral">
                  {t(`portal.roles.${user.portal_role}`, { defaultValue: user.portal_role })}
                </Badge>
              }
            />
            <Field
              label={t('portal.status', { defaultValue: 'Status' })}
              value={
                <Badge variant={STATUS_VARIANT[user.status] ?? 'neutral'} dot>
                  {t(`portal.status.${user.status}`, { defaultValue: user.status })}
                </Badge>
              }
            />
            <Field
              label={t('portal.language', { defaultValue: 'Language' })}
              value={user.language}
            />
            <Field
              label={t('portal.timezone', { defaultValue: 'Timezone' })}
              value={user.timezone}
            />
            <Field
              label={t('portal.invited_at', { defaultValue: 'Invited' })}
              value={user.invited_at ? <DateDisplay value={user.invited_at} /> : '—'}
            />
            <Field
              label={t('portal.last_login', { defaultValue: 'Last login' })}
              value={
                user.last_login_at ? <DateDisplay value={user.last_login_at} /> : '—'
              }
            />
            <Field
              label={t('portal.failed_logins', { defaultValue: 'Failed logins' })}
              value={user.failed_login_count}
            />
          </div>

          <div className="flex flex-wrap gap-2 border-t border-border-light pt-4">
            <Button
              variant="secondary"
              icon={<Send size={14} />}
              loading={resendMut.isPending}
              onClick={() => resendMut.mutate()}
            >
              {t('portal.resend_invite', { defaultValue: 'Resend invite' })}
            </Button>
            {user.status === 'suspended' ? (
              <Button
                variant="secondary"
                icon={<RotateCcw size={14} />}
                loading={reactivateMut.isPending}
                onClick={() => reactivateMut.mutate()}
              >
                {t('portal.reactivate', { defaultValue: 'Reactivate' })}
              </Button>
            ) : (
              <Button
                variant="danger"
                icon={<Ban size={14} />}
                loading={suspendMut.isPending}
                onClick={() => suspendMut.mutate()}
              >
                {t('portal.suspend', { defaultValue: 'Suspend' })}
              </Button>
            )}
          </div>

          {auditEntries.length > 0 && (
            <div className="border-t border-border-light pt-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                {t('portal.recent_access', { defaultValue: 'Recent document access' })}
              </p>
              <ul className="space-y-1.5">
                {auditEntries.slice(0, 8).map((e) => (
                  <li key={e.id} className="flex items-center gap-2 text-xs">
                    <Badge variant={ACTION_VARIANT[e.action] ?? 'neutral'} size="sm">
                      {t(`portal.actions.${e.action}`, { defaultValue: e.action })}
                    </Badge>
                    <span className="font-mono text-content-secondary">
                      {t(`portal.document_types.${e.document_type}`, {
                        defaultValue: e.document_type,
                      })}
                    </span>
                    <span className="font-mono text-content-tertiary truncate">
                      {e.document_id.slice(0, 8)}
                    </span>
                    <span className="ml-auto text-content-tertiary">
                      <DateDisplay value={e.occurred_at ?? e.created_at} />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

/* ─── Invite modal ─── */

function InviteModal({
  initial,
  onClose,
  onInvited,
}: {
  initial?: { email?: string; full_name?: string; portal_role?: PortalRole };
  onClose: () => void;
  onInvited: (email: string, token: string, expires_at: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<{
    email: string;
    full_name: string;
    portal_role: PortalRole;
    language: string;
    timezone: string;
    redirect_path: string;
  }>({
    email: initial?.email ?? '',
    full_name: initial?.full_name ?? '',
    portal_role: initial?.portal_role ?? 'client',
    language: 'en',
    timezone: 'UTC',
    redirect_path: '',
  });

  const inviteMut = useMutation({
    mutationFn: () =>
      invitePortalUser({
        email: form.email,
        full_name: form.full_name || undefined,
        portal_role: form.portal_role,
        language: form.language,
        timezone: form.timezone,
        redirect_path: form.redirect_path || null,
      }),
    onSuccess: (data) => {
      addToast({
        type: 'success',
        title: t('portal.invited_ok', { defaultValue: 'User invited' }),
      });
      onInvited(form.email, data.magic_link_token, data.magic_link_expires_at);
      qc.invalidateQueries({ queryKey: ['portal', 'users'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSubmit = form.email.trim().length > 3 && form.email.includes('@');

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('portal.invite_user', { defaultValue: 'Invite a portal user' })}
      subtitle={t('portal.invite_subtitle', {
        defaultValue:
          'Send a magic-link invite to a client, investor, consultant or other external party. They will set up their own password on first login.',
      })}
      size="lg"
      busy={inviteMut.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={inviteMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!canSubmit}
            loading={inviteMut.isPending}
            icon={<Send size={14} />}
            onClick={() => inviteMut.mutate()}
          >
            {t('portal.send_invite', { defaultValue: 'Send invite' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('portal.email', { defaultValue: 'Email' })}
          required
        >
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className={inputCls}
            placeholder="customer@example.com"
            autoFocus
          />
        </WideModalField>
        <WideModalField
          label={t('portal.full_name', { defaultValue: 'Full name' })}
          hint={t('portal.full_name_hint', {
            defaultValue: 'Optional - used in the email salutation.',
          })}
        >
          <input
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('portal.role', { defaultValue: 'Role' })}
          required
          hint={t('portal.role_hint', {
            defaultValue: 'Drives default permissions & UI scope.',
          })}
          span={2}
        >
          <div className="flex flex-wrap gap-1.5">
            {ROLES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setForm({ ...form, portal_role: r })}
                className={clsx(
                  'rounded-full border px-3 py-1 text-xs transition-colors',
                  form.portal_role === r
                    ? 'border-oe-blue bg-oe-blue text-content-inverse'
                    : 'border-border bg-surface-primary text-content-secondary hover:border-oe-blue/50',
                )}
              >
                {t(`portal.roles.${r}`, { defaultValue: r })}
              </button>
            ))}
          </div>
        </WideModalField>
        <WideModalField
          label={t('portal.language', { defaultValue: 'Language' })}
          hint={t('portal.language_hint', {
            defaultValue: '2-letter ISO code (en, de, ru, …)',
          })}
        >
          <input
            value={form.language}
            onChange={(e) => setForm({ ...form, language: e.target.value })}
            className={inputCls}
            maxLength={10}
            placeholder="en"
          />
        </WideModalField>
        <WideModalField
          label={t('portal.timezone', { defaultValue: 'Timezone' })}
          hint={t('portal.timezone_hint', {
            defaultValue: 'IANA TZ ID, e.g. "Europe/Berlin".',
          })}
        >
          <input
            value={form.timezone}
            onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            className={inputCls}
            placeholder="UTC"
          />
        </WideModalField>
        <WideModalField
          label={t('portal.redirect_path', { defaultValue: 'Redirect path' })}
          hint={t('portal.redirect_path_hint', {
            defaultValue:
              'Optional - page to open after the user signs in. Defaults to the portal dashboard.',
          })}
          span={2}
        >
          <input
            value={form.redirect_path}
            onChange={(e) => setForm({ ...form, redirect_path: e.target.value })}
            className={inputCls}
            placeholder="/projects/abc/documents"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Grant access modal ─── */

function GrantAccessModal({
  users,
  onClose,
}: {
  users: PortalUser[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    portal_user_id: users[0]?.id ?? '',
    resource_type: 'project',
    resource_id: '',
    permission: 'view' as AccessPermission,
    expires_at: '',
  });

  // CONN-53: when granting access to a document we first need a project to
  // scope the document list (documents are project-scoped). Tickets are listed
  // org-wide. Both pickers submit the selected UUID to the backend so the
  // inviter never pastes a raw id.
  const [docProjectId, setDocProjectId] = useState('');

  const grantMut = useMutation({
    mutationFn: () =>
      grantAccess({
        portal_user_id: form.portal_user_id,
        resource_type: form.resource_type,
        resource_id: form.resource_id,
        permission: form.permission,
        expires_at: form.expires_at || null,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('portal.access_granted', { defaultValue: 'Access granted' }),
      });
      qc.invalidateQueries({ queryKey: ['portal', 'access-rules'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSubmit =
    form.portal_user_id && form.resource_type && form.resource_id.length > 8;

  // Load projects so we can show a friendly project picker when the
  // resource type is "project". This addresses the user's complaint
  // ("нужно давать понять к какому проекту даётся доступ"): instead of
  // pasting a UUID, the inviter picks the project by name and we still
  // submit the UUID to the backend.
  const projectsQ = useQuery({
    queryKey: ['portal-grant', 'projects'],
    queryFn: () => projectsApi.list(),
    // Load projects for the project picker AND the document picker (which needs
    // a project to scope its list).
    enabled: form.resource_type === 'project' || form.resource_type === 'document',
    staleTime: 60_000,
  });

  // CONN-53: document picker — scoped to the chosen project.
  const documentsQ = useQuery({
    queryKey: ['portal-grant', 'documents', docProjectId],
    queryFn: () => fetchDocuments(docProjectId),
    enabled: form.resource_type === 'document' && !!docProjectId,
    staleTime: 60_000,
  });

  // CONN-53: service-ticket picker — org-wide, the portal admin surface is not
  // project-scoped.
  const ticketsQ = useQuery({
    queryKey: ['portal-grant', 'tickets'],
    queryFn: () => listTickets({ limit: 200 }),
    enabled: form.resource_type === 'ticket',
    staleTime: 60_000,
  });

  const selectedPortalUser = users.find((u) => u.id === form.portal_user_id);

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('portal.grant_access', { defaultValue: 'Grant access' })}
      subtitle={t('portal.grant_access_subtitle', {
        defaultValue:
          'Pick a portal user, choose what they should be able to see, and select the resource. We will create a row in the access-rules table and the user will see it on their next login.',
      })}
      size="lg"
      busy={grantMut.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={grantMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!canSubmit}
            loading={grantMut.isPending}
            icon={<Plus size={14} />}
            onClick={() => grantMut.mutate()}
          >
            {t('portal.grant', { defaultValue: 'Grant access' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('portal.grant_who_section', { defaultValue: 'Who' })}
        columns={2}
      >
        <WideModalField
          label={t('portal.user', { defaultValue: 'Portal user' })}
          required
          hint={selectedPortalUser
            ? t('portal.grant_who_hint_selected', {
                defaultValue: 'Role: {{role}} - {{status}}',
                role: t(`portal.roles.${selectedPortalUser.portal_role}`, {
                  defaultValue: selectedPortalUser.portal_role,
                }),
                status: t(`portal.status.${selectedPortalUser.status}`, {
                  defaultValue: selectedPortalUser.status,
                }),
              })
            : t('portal.grant_who_hint', {
                defaultValue: 'External party that will receive the link.',
              })}
          span={2}
        >
          <select
            value={form.portal_user_id}
            onChange={(e) => setForm({ ...form, portal_user_id: e.target.value })}
            className={inputCls}
          >
            <option value="">— {t('common.select', { defaultValue: 'Select' })} —</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.email} ({t(`portal.roles.${u.portal_role}`, { defaultValue: u.portal_role })})
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('portal.grant_what_section', { defaultValue: 'What' })}
        description={t('portal.grant_what_desc', {
          defaultValue:
            'Each rule covers ONE resource. To grant access to multiple projects, create multiple rules.',
        })}
        columns={2}
      >
        <WideModalField
          label={t('portal.resource_type', { defaultValue: 'Resource type' })}
          required
        >
          <select
            value={form.resource_type}
            onChange={(e) => {
              // Clear the resource id when switching types so we do not
              // submit a stale project id under e.g. "invoice".
              setForm({ ...form, resource_type: e.target.value, resource_id: '' });
              setDocProjectId('');
            }}
            className={inputCls}
          >
            <option value="project">{t('portal.rt_project', { defaultValue: 'Project' })}</option>
            <option value="development">{t('portal.rt_development', { defaultValue: 'Development' })}</option>
            <option value="document">{t('portal.rt_document', { defaultValue: 'Document' })}</option>
            <option value="ticket">{t('portal.rt_ticket', { defaultValue: 'Service ticket' })}</option>
            <option value="invoice">{t('portal.rt_invoice', { defaultValue: 'Invoice' })}</option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('portal.permission', { defaultValue: 'Permission' })}
          hint={t('portal.permission_hint', {
            defaultValue:
              'View - read only. Comment - read + add comments. Submit - upload responses. Sign - apply legal e-signature.',
          })}
        >
          <select
            value={form.permission}
            onChange={(e) =>
              setForm({ ...form, permission: e.target.value as AccessPermission })
            }
            className={inputCls}
          >
            {PERMISSIONS.map((p) => (
              <option key={p} value={p}>
                {t(`portal.permissions.${p}`, { defaultValue: p })}
              </option>
            ))}
          </select>
        </WideModalField>
        {form.resource_type === 'project' ? (
          <WideModalField
            label={t('portal.project', { defaultValue: 'Project' })}
            required
            hint={t('portal.project_hint', {
              defaultValue: 'The portal user will only see the data inside this project.',
            })}
            span={2}
          >
            <select
              value={form.resource_id}
              onChange={(e) => setForm({ ...form, resource_id: e.target.value })}
              className={inputCls}
              disabled={projectsQ.isLoading}
            >
              <option value="">— {t('common.select', { defaultValue: 'Select' })} —</option>
              {(projectsQ.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </WideModalField>
        ) : form.resource_type === 'document' ? (
          <>
            <WideModalField
              label={t('portal.doc_project', { defaultValue: 'Project' })}
              required
              hint={t('portal.doc_project_hint', {
                defaultValue: 'Pick the project that holds the document.',
              })}
              span={2}
            >
              <select
                value={docProjectId}
                onChange={(e) => {
                  setDocProjectId(e.target.value);
                  setForm({ ...form, resource_id: '' });
                }}
                className={inputCls}
                disabled={projectsQ.isLoading}
              >
                <option value="">— {t('common.select', { defaultValue: 'Select' })} —</option>
                {(projectsQ.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('portal.document', { defaultValue: 'Document' })}
              required
              hint={t('portal.document_hint', {
                defaultValue: 'Only this document will be visible to the portal user.',
              })}
              span={2}
            >
              <select
                value={form.resource_id}
                onChange={(e) => setForm({ ...form, resource_id: e.target.value })}
                className={inputCls}
                disabled={!docProjectId || documentsQ.isLoading}
              >
                <option value="">
                  {!docProjectId
                    ? t('portal.pick_project_first', {
                        defaultValue: 'Pick a project first',
                      })
                    : `— ${t('common.select', { defaultValue: 'Select' })} —`}
                </option>
                {(documentsQ.data ?? []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </WideModalField>
          </>
        ) : form.resource_type === 'ticket' ? (
          <WideModalField
            label={t('portal.ticket', { defaultValue: 'Service ticket' })}
            required
            hint={t('portal.ticket_hint', {
              defaultValue: 'The portal user will only see this ticket.',
            })}
            span={2}
          >
            <select
              value={form.resource_id}
              onChange={(e) => setForm({ ...form, resource_id: e.target.value })}
              className={inputCls}
              disabled={ticketsQ.isLoading}
            >
              <option value="">— {t('common.select', { defaultValue: 'Select' })} —</option>
              {(ticketsQ.data ?? []).map((tk) => (
                <option key={tk.id} value={tk.id}>
                  {tk.ticket_number} - {tk.title}
                </option>
              ))}
            </select>
          </WideModalField>
        ) : (
          <WideModalField
            label={t('portal.resource_id', { defaultValue: 'Resource ID' })}
            required
            hint={t('portal.resource_id_hint', {
              defaultValue: 'Open the resource in the app and copy the UUID from the URL.',
            })}
            span={2}
          >
            <input
              value={form.resource_id}
              onChange={(e) => setForm({ ...form, resource_id: e.target.value })}
              className={inputCls}
              placeholder="00000000-0000-0000-0000-000000000000"
            />
          </WideModalField>
        )}
        <WideModalField
          label={t('portal.expires', { defaultValue: 'Expires' })}
          hint={t('portal.expires_hint', {
            defaultValue: 'Leave empty for an open-ended grant.',
          })}
          span={2}
        >
          <input
            type="datetime-local"
            value={form.expires_at}
            onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
