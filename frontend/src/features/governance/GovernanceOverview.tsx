// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// GovernanceOverview - the persistent "how it fits" + "posture at a glance"
// band that sits above the Governance tab strip. Two pieces:
//
//   1. IntegrationRail - an always-visible integration map (norm-expansion
//      "Pulls from / Feeds" style). It survives when the collapsible intro
//      card is dismissed, so the fact that Governance DRIVES sign-off in
//      Submittals / RFI / Markups (and works with Users, Validation, the
//      Audit Log) is one click away, not one sentence. Only modules that
//      embed the shared ApprovalInstanceCard are listed here: Change Orders
//      run a separate, self-contained approval chain (configured on the CO
//      itself, not via this tab), so linking them here would be misleading.
//
//   2. SummaryStats - three clickable stat shortcuts (roles, active approval
//      routes, validation rule sets). Each stat re-issues the *identical*
//      React Query the delegated tab page already runs, so React Query
//      dedupes the fetch and shares the cache: no extra backend work, an
//      instant governance-posture read on landing, and a one-tap jump into
//      the matching tab.
//
// i18n: every user-facing string is inline via t(key, { defaultValue }); no
// locale file is touched. Design tokens only. All array access is guarded
// (length / filter / reduce, never bracket indexing) for
// noUncheckedIndexedAccess.

import { type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { Network, ScrollText, ShieldCheck, Workflow, type LucideIcon } from 'lucide-react';
import { Card } from '@/shared/ui';
import { fetchPermissionsMatrix } from '@/features/admin/api';
import { approvalRoutesKeys, listRoutes } from '@/features/approval-routes/api';
import { listValidationRuleSets } from '@/features/property-dev/api';

/** Tab ids this overview can jump to - kept in lock-step with GovernancePage. */
export type GovernanceTabId = 'permissions' | 'approvals' | 'validation';

/** A compact inline link to a sibling module (keeps the rail copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/* ── Integration rail (persistent, survives intro collapse) ─────────────── */

/**
 * Always-visible integration map. The top line is the high-value DOWNSTREAM
 * link set - the modules whose sign-off badges Governance's approval routes
 * actually drive. The second line is the UPSTREAM / sibling admin surfaces
 * Governance works with. Every route here is confirmed present in App.tsx.
 */
function IntegrationRail() {
  const { t } = useTranslation();
  return (
    <Card padding="sm" className="animate-card-in">
      <nav
        aria-label={t('governance.rail_aria', {
          defaultValue: 'How Governance connects to other modules',
        })}
        className="flex flex-col gap-2 text-xs"
      >
        {/* Downstream - what the three controls enforce elsewhere. */}
        <div className="flex flex-col gap-x-2 gap-y-1 sm:flex-row sm:flex-wrap sm:items-baseline">
          <span className="inline-flex items-center gap-1.5 font-semibold text-content-secondary">
            <Network size={14} className="text-oe-blue" aria-hidden />
            {t('governance.rail_drives', { defaultValue: 'Drives sign-off in:' })}
          </span>
          <span className="text-content-tertiary">
            <ModLink to="/submittals">
              {t('governance.mod_submittals', { defaultValue: 'Submittals' })}
            </ModLink>
            {' · '}
            <ModLink to="/rfi">{t('governance.mod_rfi', { defaultValue: 'RFI' })}</ModLink>
            {' · '}
            <ModLink to="/markups">
              {t('governance.mod_markups', { defaultValue: 'Markups' })}
            </ModLink>
          </span>
        </div>

        {/* Upstream / sibling admin surfaces. */}
        <div className="flex flex-col gap-x-2 gap-y-1 border-t border-border-light pt-2 sm:flex-row sm:flex-wrap sm:items-baseline">
          <span className="font-semibold text-content-secondary">
            {t('governance.rail_works_with', { defaultValue: 'Works with:' })}
          </span>
          <span className="text-content-tertiary">
            <ModLink to="/users">{t('governance.mod_users', { defaultValue: 'Users' })}</ModLink>
            {' · '}
            <ModLink to="/validation">
              {t('governance.mod_validation', { defaultValue: 'Validation' })}
            </ModLink>
            {' · '}
            <ModLink to="/admin/audit-log">
              {t('governance.mod_audit', { defaultValue: 'Audit Log' })}
            </ModLink>
          </span>
        </div>
      </nav>
    </Card>
  );
}

/* ── Summary stats (clickable shortcuts, shared React Query cache) ──────── */

function StatButton({
  icon: Icon,
  value,
  label,
  sub,
  loading,
  actionHint,
  onClick,
}: {
  icon: LucideIcon;
  /** The headline count. `undefined` = not available (loading / error / no access). */
  value: number | undefined;
  label: string;
  sub: string;
  loading: boolean;
  /** Screen-reader-only action hint appended to the accessible name. */
  actionHint: string;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex items-center gap-3 rounded-xl border border-border-light bg-surface-elevated p-4 text-left shadow-xs transition-all duration-normal ease-oe hover:-translate-y-0.5 hover:border-oe-blue/40 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
        <Icon size={18} aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="block text-2xl font-semibold leading-tight tabular-nums text-content-primary">
          {loading ? (
            <span
              className="inline-block h-7 w-10 animate-pulse rounded bg-surface-tertiary align-middle"
              aria-hidden
            />
          ) : value == null ? (
            <>
              <span className="text-content-quaternary" aria-hidden>
                -
              </span>
              <span className="sr-only">
                {t('governance.stat_unavailable', { defaultValue: 'Not available' })}
              </span>
            </>
          ) : (
            value
          )}
        </span>
        <span className="block truncate text-sm font-medium text-content-primary">{label}</span>
        <span className="block truncate text-xs text-content-tertiary">{sub}</span>
      </span>
      <span className="sr-only">{actionHint}</span>
    </button>
  );
}

function SummaryStats({ onJump }: { onJump: (tab: GovernanceTabId) => void }) {
  const { t } = useTranslation();

  // Each query is byte-for-byte the same key + fetcher the delegated tab page
  // already runs, so React Query dedupes the request and shares the cache.
  // The matrix needs audit.view (manager and above). Below that the roles
  // tile shows no count rather than firing a call that is refused.
  const canViewMatrix = useHasPermission('audit.view');
  const permQuery = useQuery({
    queryKey: ['admin', 'permissions-matrix'],
    queryFn: fetchPermissionsMatrix,
    retry: false,
    staleTime: 60_000,
    enabled: canViewMatrix,
  });
  const routesQuery = useQuery({
    queryKey: approvalRoutesKeys.routes(null, null),
    queryFn: () => listRoutes({ targetKind: null, includeInactive: true }),
    staleTime: 30_000,
  });
  const ruleSetsQuery = useQuery({
    queryKey: ['validation', 'rule-sets'],
    queryFn: listValidationRuleSets,
    staleTime: 5 * 60_000,
  });

  const rolesCount = permQuery.data?.roles.length;
  const activeRoutes = routesQuery.data
    ? routesQuery.data.filter((r) => r.is_active).length
    : undefined;
  const ruleSetsCount = ruleSetsQuery.data?.length;
  const totalRules = ruleSetsQuery.data
    ? ruleSetsQuery.data.reduce((sum, rs) => sum + rs.rule_count, 0)
    : undefined;

  return (
    <div className="grid grid-cols-1 gap-3 animate-card-in sm:grid-cols-3">
      <StatButton
        icon={ShieldCheck}
        value={rolesCount}
        label={t('governance.stat_roles', { defaultValue: 'Roles' })}
        sub={t('governance.stat_roles_sub', { defaultValue: 'Permissions per role' })}
        loading={permQuery.isLoading}
        actionHint={t('governance.stat_roles_aria', {
          defaultValue: 'Open the Permissions tab',
        })}
        onClick={() => onJump('permissions')}
      />
      <StatButton
        icon={Workflow}
        value={activeRoutes}
        label={t('governance.stat_routes', { defaultValue: 'Active routes' })}
        sub={t('governance.stat_routes_sub', { defaultValue: 'Approval sign-off' })}
        loading={routesQuery.isLoading}
        actionHint={t('governance.stat_routes_aria', {
          defaultValue: 'Open the Approval Routes tab',
        })}
        onClick={() => onJump('approvals')}
      />
      <StatButton
        icon={ScrollText}
        value={ruleSetsCount}
        label={t('governance.stat_rulesets', { defaultValue: 'Rule sets' })}
        sub={
          totalRules == null
            ? t('governance.stat_rules_sub_empty', { defaultValue: 'Validation checks' })
            : t('governance.stat_rules_sub', {
                defaultValue: '{{count}} rules',
                count: totalRules,
              })
        }
        loading={ruleSetsQuery.isLoading}
        actionHint={t('governance.stat_rulesets_aria', {
          defaultValue: 'Open the Validation Rules tab',
        })}
        onClick={() => onJump('validation')}
      />
    </div>
  );
}

/* ── Public component ───────────────────────────────────────────────────── */

/**
 * Persistent Governance overview band: the integration rail plus the three
 * posture stats. Rendered directly inside GovernancePage's `space-y-6`
 * container, so the fragment's two children pick up consistent vertical
 * spacing from their siblings.
 */
export function GovernanceOverview({ onJump }: { onJump: (tab: GovernanceTabId) => void }) {
  return (
    <>
      <IntegrationRail />
      <SummaryStats onJump={onJump} />
    </>
  );
}
