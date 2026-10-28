// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SettingsTeamPanel - Team, Members and License/Plan surfaces for the
 * Settings page.
 *
 * This panel SURFACES existing platform capabilities rather than rebuilding
 * auth. It reuses the users-module endpoints:
 *   - GET   /v1/users/        (list members, gated by users.list = admin/manager)
 *   - PATCH /v1/users/{id}    (change role / active, gated by users.update = admin)
 *   - GET   /v1/users/me/     (current user + role, for the read-only fallback)
 * and the public system endpoint:
 *   - GET   /api/health       (version, build, env - for the License & Plan card)
 *
 * The product is open-source and self-hosted (AGPL-3.0), so the "Billing"
 * surface is an honest License & Plan info panel: it shows the community
 * (AGPL) edition plainly and links to the commercial license request. There
 * is no payment flow and no fake plan tier - none exists server-side.
 *
 * Tenant scoping: every list/read here goes through the users service, which
 * applies multi-tenant isolation at the service layer. A viewer/editor who
 * lacks users.list simply gets a 403; we catch it and fall back to a
 * read-only "your membership" card built from /v1/users/me/, so the panel
 * never shows controls that would post nowhere.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Users,
  Crown,
  ShieldCheck,
  Edit3,
  Eye,
  Building2,
  BadgeCheck,
  ExternalLink,
  ArrowUpRight,
  UserPlus,
  Mail,
  Lock,
  Info,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Badge, Button, Skeleton } from '@/shared/ui';
import { apiGet, ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { fetchUsers, type User, type UserRole } from '@/features/users/api';

// Commercial license request page on the marketing site. The product is
// AGPL-3.0; this is the honest upgrade path (no in-app payment flow).
const LICENSE_REQUEST_URL = 'https://openconstructionerp.com/license-request.html';
const AGPL_URL = 'https://www.gnu.org/licenses/agpl-3.0.html';

// ── Role display config (icon + badge variant). The human labels are read
// from the SAME i18n keys the User Management page uses (users.roles.*), so
// no new role strings are introduced and DE/RU/etc. stay translated. ──────
const ROLE_META: Record<UserRole, { icon: typeof Crown; variant: 'error' | 'warning' | 'blue' | 'neutral' }> = {
  admin: { icon: Crown, variant: 'error' },
  manager: { icon: ShieldCheck, variant: 'warning' },
  editor: { icon: Edit3, variant: 'blue' },
  viewer: { icon: Eye, variant: 'neutral' },
};

const ROLE_ORDER: UserRole[] = ['admin', 'manager', 'editor', 'viewer'];

function RoleChip({ role }: { role: UserRole }) {
  const { t } = useTranslation();
  const meta = ROLE_META[role] ?? ROLE_META.viewer;
  const Icon = meta.icon;
  return (
    <Badge variant={meta.variant} size="sm">
      <span className="inline-flex items-center gap-1">
        <Icon size={11} />
        {t(`users.roles.${role}`, { defaultValue: role })}
      </span>
    </Badge>
  );
}

// ── Health (version / edition) ──────────────────────────────────────────────

interface HealthInfo {
  status?: string;
  version?: string;
  env?: string;
  build?: string;
  modules_loaded?: number;
}

// ── Main panel ───────────────────────────────────────────────────────────────

export function SettingsTeamPanel() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const role = useAuthStore((s) => s.userRole);
  const isAdmin = role === 'admin';
  // users.list is granted to admin + manager (see RequirePermission in the
  // users router). Anyone else gets a 403 and the read-only self card.
  const canListMembers = role === 'admin' || role === 'manager';

  // Member list - reuses GET /v1/users/. Only attempt it when the role can
  // read it; otherwise we'd guarantee a 403. Kept retry:false so a genuine
  // 403 (e.g. role drift) falls through to the self card immediately.
  const membersQuery = useQuery({
    queryKey: ['settings-team', 'members'],
    queryFn: () => fetchUsers({ limit: 200 }),
    enabled: canListMembers,
    retry: false,
  });

  // Current user - the always-available fallback identity (read-only card)
  // and the row we mark as "you" in the member list.
  const meQuery = useQuery({
    queryKey: ['settings-team', 'me'],
    queryFn: () => apiGet<User>('/v1/users/me/'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  // System health - public endpoint, drives the License & Plan card.
  const healthQuery = useQuery({
    queryKey: ['settings-team', 'health'],
    queryFn: () => apiGet<HealthInfo>('/health'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const members = membersQuery.data ?? [];
  const currentUserId = meQuery.data?.id ?? null;

  // A 403 means the role cannot list members; treat it as "no permission"
  // (read-only self card), not as an error banner.
  const listForbidden =
    membersQuery.isError && membersQuery.error instanceof ApiError && membersQuery.error.status === 403;

  const stats = useMemo(() => {
    const counts: Record<UserRole, number> = { admin: 0, manager: 0, editor: 0, viewer: 0 };
    let active = 0;
    for (const m of members) {
      if (m.role in counts) counts[m.role] += 1;
      if (m.is_active) active += 1;
    }
    return { total: members.length, active, counts };
  }, [members]);

  return (
    <div className="lg:col-span-2 space-y-5">
      {/* ── Team / Workspace card ───────────────────────────────────────── */}
      <Card>
        <CardHeader
          title={t('settings.team_title', { defaultValue: 'Team & workspace' })}
          subtitle={t('settings.team_subtitle', {
            defaultValue: 'Who shares this workspace and how access is organised',
          })}
          action={<Building2 size={20} className="text-oe-blue" aria-hidden="true" />}
        />
        <CardContent>
          {canListMembers ? (
            membersQuery.isPending ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full rounded-lg" />
                ))}
              </div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3">
                    <div className="flex items-center gap-2 text-content-tertiary">
                      <Users size={14} />
                      <span className="text-2xs uppercase tracking-wide">
                        {t('settings.team_members', { defaultValue: 'Members' })}
                      </span>
                    </div>
                    <div className="mt-1 text-lg font-semibold text-content-primary">{stats.total}</div>
                  </div>
                  <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3">
                    <div className="flex items-center gap-2 text-content-tertiary">
                      <BadgeCheck size={14} />
                      <span className="text-2xs uppercase tracking-wide">
                        {t('settings.team_active', { defaultValue: 'Active' })}
                      </span>
                    </div>
                    <div className="mt-1 text-lg font-semibold text-content-primary">{stats.active}</div>
                  </div>
                  <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3">
                    <div className="flex items-center gap-2 text-content-tertiary">
                      <Crown size={14} />
                      <span className="text-2xs uppercase tracking-wide">
                        {t('users.admins', { defaultValue: 'Admins' })}
                      </span>
                    </div>
                    <div className="mt-1 text-lg font-semibold text-content-primary">{stats.counts.admin}</div>
                  </div>
                  <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3">
                    <div className="flex items-center gap-2 text-content-tertiary">
                      <ShieldCheck size={14} />
                      <span className="text-2xs uppercase tracking-wide">
                        {t('users.managers', { defaultValue: 'Managers' })}
                      </span>
                    </div>
                    <div className="mt-1 text-lg font-semibold text-content-primary">{stats.counts.manager}</div>
                  </div>
                </div>

                {/* Role breakdown chips */}
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-content-tertiary">
                    {t('settings.team_roles_label', { defaultValue: 'Roles in this workspace:' })}
                  </span>
                  {ROLE_ORDER.filter((r) => stats.counts[r] > 0).map((r) => (
                    <span key={r} className="inline-flex items-center gap-1.5">
                      <RoleChip role={r} />
                      <span className="text-xs text-content-secondary">{stats.counts[r]}</span>
                    </span>
                  ))}
                </div>
              </>
            )
          ) : (
            // Read-only membership summary for users without users.list.
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3">
              {meQuery.isPending ? (
                <Skeleton className="h-5 w-48" />
              ) : meQuery.data ? (
                <div className="flex flex-wrap items-center gap-2 text-sm text-content-secondary">
                  <span>{t('settings.team_your_membership', { defaultValue: 'You are a member of this workspace as' })}</span>
                  <RoleChip role={meQuery.data.role} />
                </div>
              ) : (
                <p className="text-sm text-content-secondary">
                  {t('settings.team_no_access', {
                    defaultValue: 'Workspace membership details are managed by your administrator.',
                  })}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Members card ────────────────────────────────────────────────── */}
      <Card>
        <CardHeader
          title={t('settings.members_title', { defaultValue: 'Members' })}
          subtitle={t('settings.members_subtitle', {
            defaultValue: 'People with access to this workspace and their role',
          })}
          action={
            isAdmin ? (
              <Button
                variant="primary"
                size="sm"
                icon={<UserPlus size={14} />}
                onClick={() => navigate('/users')}
              >
                {t('users.invite_user', { defaultValue: 'Invite User' })}
              </Button>
            ) : undefined
          }
        />
        <CardContent>
          {!canListMembers ? (
            // Honest read-only state: no users.list permission, so we show the
            // caller's own membership only and point to the admin.
            <div className="flex items-start gap-2.5 rounded-lg border border-border-light bg-surface-secondary/30 px-4 py-3">
              <Info size={15} className="mt-0.5 shrink-0 text-content-tertiary" />
              <div className="min-w-0 text-sm">
                <p className="text-content-primary font-medium">
                  {t('settings.members_readonly_title', { defaultValue: 'Member list is admin-only' })}
                </p>
                <p className="mt-0.5 text-content-secondary">
                  {t('settings.members_readonly_desc', {
                    defaultValue:
                      'Only administrators and managers can see the full member list. Contact your workspace administrator to change who has access.',
                  })}
                </p>
                {meQuery.data && (
                  <div className="mt-2 flex items-center gap-2">
                    <Mail size={12} className="text-content-quaternary" />
                    <span className="text-content-secondary">{meQuery.data.email}</span>
                    <RoleChip role={meQuery.data.role} />
                  </div>
                )}
              </div>
            </div>
          ) : listForbidden ? (
            <p className="text-sm text-content-secondary">
              {t('settings.members_readonly_desc', {
                defaultValue:
                  'Only administrators and managers can see the full member list. Contact your workspace administrator to change who has access.',
              })}
            </p>
          ) : membersQuery.isPending ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          ) : members.length === 0 ? (
            <p className="text-sm text-content-secondary">
              {t('users.no_users', { defaultValue: 'No users found' })}
            </p>
          ) : (
            <>
              <ul className="divide-y divide-border-light rounded-xl border border-border-light overflow-hidden">
                {members.map((m) => {
                  const isSelf = m.id === currentUserId;
                  return (
                    <li
                      key={m.id}
                      className="flex items-center gap-3 bg-surface-elevated px-4 py-2.5"
                    >
                      <div
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${
                          m.is_active ? 'bg-oe-blue' : 'bg-content-quaternary'
                        }`}
                        aria-hidden="true"
                      >
                        {m.full_name?.[0]?.toUpperCase() || '?'}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-content-primary">
                            {m.full_name || m.email}
                          </span>
                          {isSelf && (
                            <span className="text-2xs font-medium text-oe-blue">
                              {t('settings.members_you', { defaultValue: 'You' })}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 text-xs text-content-tertiary">
                          <Mail size={11} />
                          <span className="truncate">{m.email}</span>
                        </div>
                      </div>
                      <RoleChip role={m.role} />
                      <Badge variant={m.is_active ? 'success' : 'neutral'} size="sm">
                        {m.is_active
                          ? t('users.active', { defaultValue: 'Active' })
                          : t('users.inactive', { defaultValue: 'Inactive' })}
                      </Badge>
                    </li>
                  );
                })}
              </ul>
              {isAdmin && (
                <div className="mt-3 flex items-center justify-between gap-3">
                  <p className="text-xs text-content-tertiary">
                    {t('settings.members_manage_hint', {
                      defaultValue: 'Change roles, set per-module access and deactivate members in User Management.',
                    })}
                  </p>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<ArrowUpRight size={14} />}
                    iconPosition="right"
                    onClick={() => navigate('/users')}
                  >
                    {t('settings.members_open_management', { defaultValue: 'Manage users' })}
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* ── License & Plan card ─────────────────────────────────────────── */}
      <Card>
        <CardHeader
          title={t('settings.license_title', { defaultValue: 'License & plan' })}
          subtitle={t('settings.license_subtitle', {
            defaultValue: 'Your edition, version and commercial licensing options',
          })}
          action={<BadgeCheck size={20} className="text-oe-blue" aria-hidden="true" />}
        />
        <CardContent>
          {/* Edition + version row */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-content-primary">
                  {t('settings.license_edition_community', { defaultValue: 'Community Edition' })}
                </span>
                <Badge variant="blue" size="sm">
                  AGPL-3.0
                </Badge>
              </div>
              <p className="mt-1 max-w-prose text-xs leading-relaxed text-content-secondary">
                {t('settings.license_community_desc', {
                  defaultValue:
                    'This is the free, open-source build. You can use it for any purpose, including commercial, self-host it on your own hardware, and modify it. In return, network users must be able to get the source under the same AGPL-3.0 license.',
                })}
              </p>
            </div>
            <a
              href={AGPL_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
            >
              {t('settings.license_read_agpl', { defaultValue: 'Read the AGPL-3.0 license' })}
              <ExternalLink size={11} />
            </a>
          </div>

          {/* Version / build facts from /api/health */}
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3 sm:grid-cols-3">
            <div>
              <dt className="text-2xs uppercase tracking-wider text-content-tertiary">
                {t('settings.license_version', { defaultValue: 'Version' })}
              </dt>
              <dd className="mt-0.5 font-mono text-sm text-content-primary">
                {healthQuery.data?.version ? `v${healthQuery.data.version}` : '-'}
              </dd>
            </div>
            <div>
              <dt className="text-2xs uppercase tracking-wider text-content-tertiary">
                {t('settings.license_environment', { defaultValue: 'Environment' })}
              </dt>
              <dd className="mt-0.5 font-mono text-sm text-content-primary">
                {healthQuery.data?.env ?? '-'}
              </dd>
            </div>
            <div>
              <dt className="text-2xs uppercase tracking-wider text-content-tertiary">
                {t('settings.license_modules', { defaultValue: 'Modules loaded' })}
              </dt>
              <dd className="mt-0.5 font-mono text-sm text-content-primary">
                {typeof healthQuery.data?.modules_loaded === 'number' ? healthQuery.data.modules_loaded : '-'}
              </dd>
            </div>
          </dl>

          {/* Commercial upgrade path - honest, no in-app payment flow */}
          <div className="mt-4 rounded-lg border border-oe-blue/20 bg-oe-blue/[0.04] px-4 py-3.5">
            <div className="flex items-start gap-3">
              <Lock size={16} className="mt-0.5 shrink-0 text-oe-blue" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-content-primary">
                  {t('settings.license_commercial_title', { defaultValue: 'Need a commercial license?' })}
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">
                  {t('settings.license_commercial_desc', {
                    defaultValue:
                      'If you cannot meet the AGPL source-sharing obligations, or you want an enterprise agreement with support and an SLA, request a commercial license. This opens a form on our website - there is no payment or subscription inside the app.',
                  })}
                </p>
                <a
                  href={LICENSE_REQUEST_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2.5 inline-flex items-center gap-1.5 rounded-full border border-oe-blue/30 bg-surface-elevated px-4 py-2 text-sm font-medium text-oe-blue transition-colors hover:bg-oe-blue/10"
                >
                  {t('settings.license_request_cta', { defaultValue: 'Request a commercial license' })}
                  <ExternalLink size={13} />
                </a>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
