// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Permissions Matrix — RBAC governance + edit surface.
 *
 * Rows are roles (Viewer / Editor / Manager / Admin), columns are
 * permission keys grouped under each module. Each cell renders one of
 * three states:
 *
 *   • check  — role has the permission (role-level ≥ min_role).
 *   • cross  — role is below the permission's min_role.
 *   • lock   — admin-only by design (min_role is admin).
 *
 * Admins can click a cell to flip the permission's ``min_role`` —
 * clicking on (role=editor, perm=projects.delete) sets ``min_role``
 * to *editor* so editors-and-up can call it. The backend audit-logs
 * every change. Non-admin viewers fall back to the read-only matrix
 * (per the brief — RBAC failures must never break the page).
 *
 * Visual language: glass cards over a soft gradient backdrop with
 * radial glow blobs — mirrors ``CoordinationHubPage``.
 *
 * Backend: ``GET /api/v1/admin/permissions/matrix`` (audit.view),
 *          ``PATCH /api/v1/admin/permissions/{key}`` (admin),
 *          ``POST  /api/v1/admin/permissions/preset/{name}`` (admin).
 */

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Check,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Download,
  Loader2,
  Lock,
  MinusSquare,
  RotateCcw,
  Search,
  ShieldCheck,
  Square,
  X as XIcon,
} from 'lucide-react';
import { EmptyState } from '@/shared/ui';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { useAuthStore } from '@/stores/useAuthStore';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { NoAccessState } from '@/shared/ui/NoAccessState';
import { useToastStore } from '@/stores/useToastStore';
import {
  applyPermissionPreset,
  cellState,
  fetchPermissionsMatrix,
  updatePermissionMinRole,
  type MatrixCellState,
  type MatrixPermission,
  type MatrixRole,
  type PermissionsMatrix,
} from './api';

/** Lowercase-and-trim normaliser so the search filter is forgiving. */
function normalise(s: string): string {
  return s.trim().toLowerCase();
}

/** Title-Case a permission module slug for human-readable group headers.
 *  `bim_hub` → `Bim Hub`, `costs` → `Costs`, `system.settings` → keeps
 *  only the first segment (the registry groups by first dotted segment,
 *  but a slug may itself contain underscores / hyphens). */
function titleCaseSlug(slug: string): string {
  return slug
    .split(/[._\-\s]+/)
    .filter(Boolean)
    .map((w) => (w.length <= 2 ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(' ');
}

/**
 * Resolve a friendly, localized label for a module group.
 *
 * We reuse the existing `nav.{slug}` i18n strings when a *real*
 * translation exists (so the header reads "Bill of Quantities" instead
 * of "Boq"), and otherwise fall back to a Title-Cased slug. The key-echo
 * guard (`label !== key`) means an untranslated/unknown slug never leaks
 * the raw `nav.*` key onto the screen — it Title-Cases instead.
 */
function humanizeModule(slug: string, t: ReturnType<typeof useTranslation>['t']): string {
  const key = `nav.${slug}`;
  const label = t(key, { defaultValue: '' });
  if (label && label !== key) return label;
  return titleCaseSlug(slug);
}

/** Split a `module.action` permission key into its action tail (the part
 *  after the FIRST dot). `projects.create` → `create`,
 *  `system.settings.write` → `settings.write`. Falls back to the whole
 *  key when there is no dot. */
function permissionAction(key: string): string {
  const idx = key.indexOf('.');
  return idx === -1 ? key : key.slice(idx + 1);
}

/** Permissions that the admin must never demote — clicking these cells
 *  pops a "cannot lock yourself out" explanation instead of mutating. */
function isAdminLockout(permissionKey: string, newMinRole: MatrixRole): boolean {
  if (permissionKey === 'permissions.admin') return newMinRole !== 'admin';
  if (permissionKey.startsWith('system.permissions.')) return newMinRole !== 'admin';
  return false;
}

/** Build a CSV blob from the current matrix snapshot — useful for
 *  compliance evidence and offline review. */
function buildCsv(data: PermissionsMatrix): string {
  const header = ['module', 'permission', 'min_role', ...data.roles].join(',');
  const lines = [header];
  for (const m of data.modules) {
    for (const p of m.permissions) {
      const cells = data.roles.map((r) => cellState(r, p.min_role, data.role_hierarchy));
      lines.push([m.name, p.key, p.min_role, ...cells].join(','));
    }
  }
  return lines.join('\n');
}

interface CellProps {
  state: MatrixCellState;
  role: MatrixRole;
  minRole: MatrixRole;
  permissionKey: string;
  tooltip: string;
  editable: boolean;
  pending: boolean;
  onToggle: (role: MatrixRole, permissionKey: string, currentMinRole: MatrixRole) => void;
}

function MatrixCell({
  state,
  role,
  minRole,
  permissionKey,
  tooltip,
  editable,
  pending,
  onToggle,
}: CellProps) {
  const className = clsx(
    'flex items-center justify-center w-9 h-9 mx-auto rounded-md transition-colors relative',
    state === 'allowed' && 'text-emerald-600 bg-emerald-50 hover:bg-emerald-100',
    state === 'denied' && 'text-rose-500 bg-rose-50 hover:bg-rose-100',
    state === 'admin-bypass' && 'text-amber-700 bg-amber-50 hover:bg-amber-100',
    editable && 'cursor-pointer hover:ring-2 hover:ring-accent-primary/50 focus:outline-none focus:ring-2 focus:ring-accent-primary',
    !editable && 'cursor-default',
    pending && 'opacity-60',
  );
  const icon =
    state === 'allowed' ? (
      <Check size={16} aria-hidden />
    ) : state === 'admin-bypass' ? (
      <Lock size={14} aria-hidden />
    ) : (
      <XIcon size={16} aria-hidden />
    );
  if (editable) {
    return (
      <button
        type="button"
        className={className}
        title={tooltip}
        data-testid={`cell-${role}-${permissionKey}`}
        data-state={state}
        aria-label={tooltip}
        disabled={pending}
        onClick={() => onToggle(role, permissionKey, minRole)}
      >
        {pending ? (
          <Loader2 size={14} className="animate-spin" aria-hidden />
        ) : (
          icon
        )}
      </button>
    );
  }
  return (
    <div
      className={className}
      title={tooltip}
      data-testid={`cell-${role}-${permissionKey}`}
      data-state={state}
      aria-label={tooltip}
    >
      {icon}
    </div>
  );
}

interface ModuleRowsProps {
  module: PermissionsMatrix['modules'][number];
  /** The module's COMPLETE permission list (before the denied-only role
   *  filter narrows the displayed rows). Used so the "X / Y granted"
   *  count and the tri-state checkbox describe the whole module for the
   *  selected role, not just the currently-listed rows. */
  fullPermissions: MatrixPermission[];
  roles: MatrixRole[];
  hierarchy: Record<string, number>;
  hoveredRole: MatrixRole | null;
  query: string;
  collapsed: boolean;
  onToggle: () => void;
  editable: boolean;
  /** The role the per-group "grant all / none" checkbox acts on. Null
   *  when the role filter is "All roles" — the checkbox then renders
   *  disabled (you must pick a role to bulk-grant a whole module). */
  selectedRole: MatrixRole | null;
  pendingKey: string | null;
  /** True while a bulk grant/revoke for THIS module is in flight. */
  bulkPending: boolean;
  onCellToggle: (role: MatrixRole, permissionKey: string, currentMinRole: MatrixRole) => void;
  /** Bulk grant (grant=true) or revoke (grant=false) every permission in
   *  this module for `selectedRole`. */
  onBulkToggle: (moduleName: string, grant: boolean) => void;
  t: ReturnType<typeof useTranslation>['t'];
}

/** Tri-state of a module group for one role: are ALL / SOME / NONE of the
 *  module's permissions allowed for that role. Drives the header
 *  checkbox (checked / indeterminate / unchecked). */
type GroupCheckState = 'all' | 'some' | 'none';

function ModuleRows({
  module,
  fullPermissions,
  roles,
  hierarchy,
  hoveredRole,
  query,
  collapsed,
  onToggle,
  editable,
  selectedRole,
  pendingKey,
  bulkPending,
  onCellToggle,
  onBulkToggle,
  t,
}: ModuleRowsProps) {
  // Reusable matcher: a permission matches the search when the query hits
  // the action tail, the full dotted key, the raw slug OR the humanized
  // label (so "Bill of Quantities" finds boq.* rows).
  const matchPerm = useMemo(() => {
    const q = normalise(query);
    const label = normalise(humanizeModule(module.name, t));
    const slug = normalise(module.name);
    return (p: MatrixPermission) =>
      !q ||
      normalise(p.key).includes(q) ||
      normalise(permissionAction(p.key)).includes(q) ||
      slug.includes(q) ||
      label.includes(q);
  }, [module.name, query, t]);

  // Displayed rows: the (role-filtered) module permissions that match the
  // search query.
  const filteredPerms = useMemo(
    () => module.permissions.filter(matchPerm),
    [module.permissions, matchPerm],
  );

  // Count base: the COMPLETE module (search-filtered) — so "X / Y granted"
  // describes the whole module for the selected role even when the
  // denied-only role filter hides the granted rows below.
  const countPerms = useMemo(
    () => fullPermissions.filter(matchPerm),
    [fullPermissions, matchPerm],
  );

  // How many of the module's permissions are allowed for the selected
  // role — powers the "X / Y granted" count and the tri-state checkbox.
  const grantedCount = useMemo(() => {
    if (!selectedRole) return 0;
    return countPerms.filter(
      (p) => cellState(selectedRole, p.min_role, hierarchy) === 'allowed',
    ).length;
  }, [countPerms, selectedRole, hierarchy]);

  const groupState: GroupCheckState = !selectedRole
    ? 'none'
    : grantedCount === 0
      ? 'none'
      : grantedCount === countPerms.length
        ? 'all'
        : 'some';

  // Hide the whole group when neither the displayed rows nor (for the
  // count) the full module match the search.
  if (countPerms.length === 0) return null;

  const friendlyName = humanizeModule(module.name, t);
  const headerId = `module-group-${module.name}`;
  // The per-group checkbox is only actionable in edit mode with a chosen
  // role; otherwise it is shown disabled so the affordance is discoverable.
  const checkboxActionable = editable && !!selectedRole && !bulkPending;
  const CheckIcon =
    groupState === 'all' ? CheckSquare : groupState === 'some' ? MinusSquare : Square;

  return (
    <>
      {/* Module header row — clickable to expand/collapse */}
      <tr className="bg-surface-secondary/60 sticky-col-group">
        <th
          scope="rowgroup"
          colSpan={roles.length + 1}
          className="px-3 py-2 text-left text-sm font-semibold text-text-primary"
        >
          <div className="flex items-center gap-2">
            {/* Per-group tri-state "grant all / none" for the selected role */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (!checkboxActionable) return;
                // Toggle semantics: if everything is granted, revoke all;
                // otherwise grant all (covers the "some" partial case too).
                onBulkToggle(module.name, groupState !== 'all');
              }}
              disabled={!checkboxActionable}
              aria-checked={groupState === 'all' ? 'true' : groupState === 'some' ? 'mixed' : 'false'}
              role="checkbox"
              aria-label={t('admin.permissions.bulk_aria', {
                defaultValue: 'Grant or revoke all {{module}} permissions',
                module: friendlyName,
              })}
              data-testid={`module-selectall-${module.name}`}
              title={
                !editable
                  ? t('admin.permissions.bulk_needs_edit', {
                      defaultValue: 'Enable edit mode to grant a whole module at once',
                    })
                  : !selectedRole
                    ? t('admin.permissions.bulk_needs_role', {
                        defaultValue: 'Pick a role above to grant / revoke this whole module',
                      })
                    : groupState === 'all'
                      ? t('admin.permissions.bulk_revoke_all', {
                          defaultValue: 'Revoke all "{{module}}" permissions from {{role}}',
                          module: friendlyName,
                          role: selectedRole,
                        })
                      : t('admin.permissions.bulk_grant_all', {
                          defaultValue: 'Grant all "{{module}}" permissions to {{role}}',
                          module: friendlyName,
                          role: selectedRole,
                        })
              }
              className={clsx(
                'flex items-center justify-center rounded p-0.5 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary',
                checkboxActionable
                  ? 'text-accent-primary hover:bg-accent-primary/10 cursor-pointer'
                  : 'text-text-quaternary cursor-not-allowed opacity-60',
              )}
            >
              {bulkPending ? (
                <Loader2 size={16} className="animate-spin" aria-hidden />
              ) : (
                <CheckIcon size={16} aria-hidden />
              )}
            </button>

            <button
              type="button"
              onClick={onToggle}
              id={headerId}
              className="flex flex-1 items-center gap-2 hover:text-accent-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary rounded text-left"
              data-testid={`module-toggle-${module.name}`}
              aria-expanded={!collapsed}
            >
              {collapsed ? (
                <ChevronRight size={16} aria-hidden />
              ) : (
                <ChevronDown size={16} aria-hidden />
              )}
              <span className="font-semibold">{friendlyName}</span>
              <span className="font-mono text-[11px] font-normal text-text-tertiary">
                {module.name}
              </span>
              <span className="ml-auto text-xs text-text-tertiary font-normal tabular-nums">
                {selectedRole
                  ? t('admin.permissions.group_granted_count', {
                      defaultValue: '{{granted}} / {{total}} granted',
                      granted: grantedCount,
                      total: countPerms.length,
                    })
                  : t('admin.permissions.module_count', {
                      count: filteredPerms.length,
                      defaultValue_one: '{{count}} permission',
                      defaultValue_other: '{{count}} permissions',
                    })}
              </span>
            </button>
          </div>
        </th>
      </tr>

      {/* Permission rows */}
      {!collapsed &&
        filteredPerms.map((perm) => (
          <tr
            key={perm.key}
            className="border-b border-border-light last:border-0 hover:bg-surface-secondary/30"
          >
            <th
              scope="row"
              className={clsx(
                'sticky left-0 z-10 bg-surface-elevated px-3 py-2 pl-9 text-left text-sm text-text-secondary',
                'border-r border-border-light',
              )}
            >
              {/* Action is the primary, readable label; the full dotted
                  key is muted, monospaced secondary text. */}
              <span className="block truncate max-w-[280px] font-medium text-text-primary" title={permissionAction(perm.key)}>
                {permissionAction(perm.key)}
              </span>
              <span className="block truncate max-w-[280px] font-mono text-[10px] text-text-tertiary" title={perm.key}>
                {perm.key}
                <span className="ml-1.5 uppercase tracking-wider">
                  · {t('admin.permissions.min_role_label', { defaultValue: 'min' })}: {perm.min_role}
                </span>
              </span>
              {/* Plain-language description — resolved from a per-permission
                  i18n key, with a deterministic humanized fallback so every
                  row is described (no stubs / no undescribed rows). */}
              {(() => {
                const desc = t(`perm_desc.${perm.key}`, {
                  defaultValue: t('perm_desc.fallback', {
                    action: permissionAction(perm.key),
                    module: friendlyName,
                    defaultValue: 'Allows {{action}} in {{module}}',
                  }),
                });
                return (
                  <span
                    className="mt-0.5 block max-w-[280px] text-[11px] leading-snug text-text-tertiary line-clamp-2 font-normal normal-case"
                    title={desc}
                  >
                    {desc}
                  </span>
                );
              })()}
            </th>
            {roles.map((role) => {
              const state = cellState(role, perm.min_role, hierarchy);
              const tooltip =
                state === 'allowed'
                  ? t('admin.permissions.tooltip_allowed', {
                      defaultValue: '{{role}} can {{key}} (min role: {{min}})',
                      role,
                      key: perm.key,
                      min: perm.min_role,
                    })
                  : state === 'admin-bypass'
                  ? t('admin.permissions.tooltip_admin_bypass', {
                      defaultValue: 'Admin-only by design - {{key}} requires admin',
                      key: perm.key,
                    })
                  : t('admin.permissions.tooltip_denied', {
                      defaultValue: '{{role}} cannot {{key}} (min role: {{min}})',
                      role,
                      key: perm.key,
                      min: perm.min_role,
                    });
              return (
                <td
                  key={role}
                  className={clsx(
                    'px-2 py-2 text-center transition-colors',
                    hoveredRole === role && 'bg-accent-primary/10',
                  )}
                >
                  <MatrixCell
                    state={state}
                    role={role}
                    minRole={perm.min_role}
                    permissionKey={perm.key}
                    tooltip={tooltip}
                    editable={editable}
                    pending={pendingKey === perm.key}
                    onToggle={onCellToggle}
                  />
                </td>
              );
            })}
          </tr>
        ))}

      {/* When the denied-only role filter hides every row in an expanded
          module (i.e. the role already has everything here), show a short
          note instead of an empty, confusing gap. */}
      {!collapsed && filteredPerms.length === 0 && countPerms.length > 0 && (
        <tr className="border-b border-border-light last:border-0">
          <td
            colSpan={roles.length + 1}
            className="px-3 py-2 pl-9 text-left text-xs italic text-text-tertiary"
          >
            {selectedRole
              ? t('admin.permissions.group_all_granted', {
                  defaultValue: '{{role}} already has all {{count}} permissions in this module.',
                  role: selectedRole,
                  count: countPerms.length,
                })
              : t('admin.permissions.group_no_matches', {
                  defaultValue: 'No permissions match the current filter.',
                })}
          </td>
        </tr>
      )}
    </>
  );
}

export function PermissionsMatrixPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const userRole = useAuthStore((s) => s.userRole);
  const isAdmin = userRole === 'admin' || userRole === 'superuser' || userRole === 'owner';
  // Reading the matrix needs audit.view (manager and above). Below that the
  // page says so up front instead of firing the call and toasting its 403.
  const canViewMatrix = useHasPermission('audit.view');

  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<MatrixRole | 'all'>('all');
  // Groups are COLLAPSED by default — we track the set of *expanded*
  // module names so a fresh page shows a compact, scannable list of
  // module headers instead of ~500 permission rows at once. A search
  // query force-expands any group with matches (see `isExpanded`).
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [hoveredRole, setHoveredRole] = useState<MatrixRole | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  // Module name whose bulk grant/revoke is currently in flight (null = none).
  const [bulkModule, setBulkModule] = useState<string | null>(null);
  // Pending confirmation for a destructive change (cell toggle or
  // preset apply). Null when no modal is open.
  const [confirmState, setConfirmState] = useState<
    | { kind: 'toggle'; permissionKey: string; newMinRole: MatrixRole; currentMinRole: MatrixRole }
    | { kind: 'preset'; preset: string }
    | { kind: 'lockout'; permissionKey: string }
    | {
        kind: 'bulk';
        moduleName: string;
        role: MatrixRole;
        grant: boolean;
        /** Permission keys that will actually change min_role. */
        keys: string[];
        /** Target min_role to write to every key above. */
        target: MatrixRole;
      }
    | null
  >(null);
  // Per-role "edit mode": when the caller can edit the matrix, this
  // surface remains *read-only by default* (we want a deliberate click
  // to open the edit affordances). The brief calls this out: keep the
  // read-only fallback always reachable.
  const [editMode, setEditMode] = useState(false);

  const {
    data,
    isLoading,
    error,
    isError,
  } = useQuery<PermissionsMatrix>({
    queryKey: ['admin', 'permissions-matrix'],
    queryFn: fetchPermissionsMatrix,
    retry: false,
    staleTime: 60_000,
    enabled: canViewMatrix,
  });

  // Surface fetch errors as a toast (single fire per error message).
  useEffect(() => {
    if (!isError) return;
    const message =
      error instanceof Error
        ? error.message
        : t('admin.permissions.error_unknown', { defaultValue: 'Failed to load permissions matrix' });
    addToast(
      {
        type: 'error',
        title: t('admin.permissions.error_title', { defaultValue: 'Permissions matrix' }),
        message,
      },
      { duration: 6000 },
    );
  }, [isError, error, addToast, t]);

  // ── Mutations ──────────────────────────────────────────────────────

  const toggleMutation = useMutation({
    // Opt out of the global "Operation failed" toast in main.tsx — the
    // local onError below surfaces a contextual "Update failed" toast,
    // and the user was seeing both stacked on a single click.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: ({ permissionKey, newMinRole }: { permissionKey: string; newMinRole: MatrixRole }) =>
      updatePermissionMinRole(permissionKey, newMinRole),
    // Optimistic update: rewrite the cached matrix immediately, roll
    // back on error. React Query handles the rollback if we return
    // the previous snapshot from onMutate.
    onMutate: async ({ permissionKey, newMinRole }) => {
      setPendingKey(permissionKey);
      await queryClient.cancelQueries({ queryKey: ['admin', 'permissions-matrix'] });
      const prev = queryClient.getQueryData<PermissionsMatrix>(['admin', 'permissions-matrix']);
      if (prev) {
        queryClient.setQueryData<PermissionsMatrix>(['admin', 'permissions-matrix'], {
          ...prev,
          modules: prev.modules.map((m) => ({
            ...m,
            permissions: m.permissions.map((p) =>
              p.key === permissionKey ? { ...p, min_role: newMinRole } : p,
            ),
          })),
        });
      }
      return { prev };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(['admin', 'permissions-matrix'], ctx.prev);
      }
      const message =
        err instanceof Error
          ? err.message
          : t('admin.permissions.toggle_error', { defaultValue: 'Could not update permission' });
      addToast(
        {
          type: 'error',
          title: t('admin.permissions.toggle_error_title', { defaultValue: 'Update failed' }),
          message,
        },
        { duration: 6000 },
      );
    },
    onSuccess: (_data, vars) => {
      addToast(
        {
          type: 'success',
          title: t('admin.permissions.toggle_success_title', { defaultValue: 'Permission updated' }),
          message: t('admin.permissions.toggle_success_message', {
            defaultValue: '{{key}} → {{role}}',
            key: vars.permissionKey,
            role: vars.newMinRole,
          }),
        },
        { duration: 4000 },
      );
    },
    onSettled: () => {
      setPendingKey(null);
      queryClient.invalidateQueries({ queryKey: ['admin', 'permissions-matrix'] });
    },
  });

  const presetMutation = useMutation({
    // Same rationale as ``toggleMutation``: keep the "Preset failed"
    // toast below as the single visible message.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: (preset: string) => applyPermissionPreset(preset),
    onSuccess: (result) => {
      addToast(
        {
          type: 'success',
          title: t('admin.permissions.preset_success_title', { defaultValue: 'Preset applied' }),
          message: t('admin.permissions.preset_success_message', {
            defaultValue: '{{count}} permission(s) updated to "{{preset}}"',
            count: result.permissions_changed,
            preset: result.preset,
          }),
        },
        { duration: 4500 },
      );
      queryClient.invalidateQueries({ queryKey: ['admin', 'permissions-matrix'] });
    },
    onError: (err) => {
      const message =
        err instanceof Error
          ? err.message
          : t('admin.permissions.preset_error', { defaultValue: 'Preset failed' });
      addToast(
        {
          type: 'error',
          title: t('admin.permissions.preset_error_title', { defaultValue: 'Preset failed' }),
          message,
        },
        { duration: 6000 },
      );
    },
  });

  // Bulk grant / revoke a whole module for one role. The backend has no
  // batch endpoint, so we fan out one ``updatePermissionMinRole`` PATCH
  // per changed key with ``Promise.allSettled`` (partial failures are
  // tolerated and reported). We optimistically rewrite the cached matrix
  // up-front and reconcile on settle via an invalidate.
  const bulkMutation = useMutation({
    meta: { suppressGlobalErrorToast: true },
    mutationFn: async ({ keys, target }: { moduleName: string; keys: string[]; target: MatrixRole }) => {
      const results = await Promise.allSettled(
        keys.map((key) => updatePermissionMinRole(key, target)),
      );
      const failed = results.filter((r) => r.status === 'rejected').length;
      return { total: keys.length, failed };
    },
    onMutate: async ({ moduleName, keys, target }) => {
      setBulkModule(moduleName);
      await queryClient.cancelQueries({ queryKey: ['admin', 'permissions-matrix'] });
      const prev = queryClient.getQueryData<PermissionsMatrix>(['admin', 'permissions-matrix']);
      if (prev) {
        const keySet = new Set(keys);
        queryClient.setQueryData<PermissionsMatrix>(['admin', 'permissions-matrix'], {
          ...prev,
          modules: prev.modules.map((m) => ({
            ...m,
            permissions: m.permissions.map((p) =>
              keySet.has(p.key) ? { ...p, min_role: target } : p,
            ),
          })),
        });
      }
      return { prev };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['admin', 'permissions-matrix'], ctx.prev);
      const message =
        err instanceof Error
          ? err.message
          : t('admin.permissions.bulk_error', { defaultValue: 'Could not update the module' });
      addToast(
        {
          type: 'error',
          title: t('admin.permissions.bulk_error_title', { defaultValue: 'Bulk update failed' }),
          message,
        },
        { duration: 6000 },
      );
    },
    onSuccess: (result) => {
      if (result.failed > 0) {
        addToast(
          {
            type: 'warning',
            title: t('admin.permissions.bulk_partial_title', { defaultValue: 'Partially updated' }),
            message: t('admin.permissions.bulk_partial_message', {
              defaultValue: '{{ok}} of {{total}} permissions updated - {{failed}} failed.',
              ok: result.total - result.failed,
              total: result.total,
              failed: result.failed,
            }),
          },
          { duration: 6000 },
        );
      } else {
        addToast(
          {
            type: 'success',
            title: t('admin.permissions.bulk_success_title', { defaultValue: 'Module updated' }),
            message: t('admin.permissions.bulk_success_message', {
              defaultValue: '{{count}} permission(s) updated.',
              count: result.total,
            }),
          },
          { duration: 4000 },
        );
      }
    },
    onSettled: () => {
      setBulkModule(null);
      queryClient.invalidateQueries({ queryKey: ['admin', 'permissions-matrix'] });
    },
  });

  // ── Handlers ──────────────────────────────────────────────────────

  const handleCellToggle = (
    role: MatrixRole,
    permissionKey: string,
    currentMinRole: MatrixRole,
  ) => {
    // Clicking (role, perm) means "set min_role to <role>" — the
    // most-intuitive mapping per the brief: cell click = "the lowest
    // role that may call this is <clicked role>".
    if (role === currentMinRole) {
      // No-op — clicking the existing min_role would be a redundant
      // call. We still surface a small toast so the user knows the
      // click was received.
      addToast(
        {
          type: 'info',
          title: t('admin.permissions.noop_title', { defaultValue: 'No change' }),
          message: t('admin.permissions.noop_message', {
            defaultValue: '{{key}} is already minimum {{role}}',
            key: permissionKey,
            role,
          }),
        },
        { duration: 3000 },
      );
      return;
    }
    if (isAdminLockout(permissionKey, role)) {
      setConfirmState({ kind: 'lockout', permissionKey });
      return;
    }
    setConfirmState({
      kind: 'toggle',
      permissionKey,
      newMinRole: role,
      currentMinRole,
    });
  };

  // Bulk grant/revoke the whole module for the role currently chosen in
  // the role filter. Grant → set min_role to that role; revoke → raise
  // min_role one level above that role (or to admin when it is already
  // the highest non-admin role). Admin-lockout permissions are never
  // touched. We pre-compute the exact set of keys that change so the
  // confirm dialog can show an accurate count and the no-op case is
  // skipped silently.
  const handleBulkToggle = (moduleName: string, grant: boolean) => {
    if (!data || roleFilter === 'all') return;
    const role = roleFilter as MatrixRole;
    const module = data.modules.find((m) => m.name === moduleName);
    if (!module) return;

    // Roles are ordered lowest→highest; "next up" is used for revoke.
    const roleIdx = data.roles.indexOf(role);
    const nextUp = data.roles[roleIdx + 1] ?? 'admin';
    const target: MatrixRole = grant ? role : nextUp;

    const keys = module.permissions
      .filter((p) => {
        // Never touch permissions that must stay admin-only.
        if (isAdminLockout(p.key, target)) return false;
        const allowed = cellState(role, p.min_role, data.role_hierarchy) === 'allowed';
        // Grant: only flip the ones the role can't already do.
        // Revoke: only flip the ones the role currently can do.
        return grant ? !allowed : allowed;
      })
      .map((p) => p.key);

    if (keys.length === 0) {
      addToast(
        {
          type: 'info',
          title: t('admin.permissions.noop_title', { defaultValue: 'No change' }),
          message: grant
            ? t('admin.permissions.bulk_noop_grant', {
                defaultValue: '{{role}} already has every "{{module}}" permission.',
                role,
                module: humanizeModule(moduleName, t),
              })
            : t('admin.permissions.bulk_noop_revoke', {
                defaultValue: '{{role}} has no "{{module}}" permissions to revoke.',
                role,
                module: humanizeModule(moduleName, t),
              }),
        },
        { duration: 3000 },
      );
      return;
    }

    setConfirmState({ kind: 'bulk', moduleName, role, grant, keys, target });
  };

  const handleConfirm = () => {
    if (!confirmState) return;
    if (confirmState.kind === 'toggle') {
      toggleMutation.mutate({
        permissionKey: confirmState.permissionKey,
        newMinRole: confirmState.newMinRole,
      });
    } else if (confirmState.kind === 'preset') {
      presetMutation.mutate(confirmState.preset);
    } else if (confirmState.kind === 'bulk') {
      bulkMutation.mutate({
        moduleName: confirmState.moduleName,
        keys: confirmState.keys,
        target: confirmState.target,
      });
    }
    // 'lockout' modal has no confirm path — the user can only close.
    setConfirmState(null);
  };

  const handleExportCsv = () => {
    if (!data) return;
    const csv = buildCsv(data);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = `permissions-matrix-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // Visible modules + permission counts after applying the search query
  // and the role filter.
  const visibleData = useMemo<PermissionsMatrix | null>(() => {
    if (!data) return null;
    if (roleFilter === 'all') return data;
    // Filter: show only permissions where role-filter is below min_role
    // (i.e. the rows where the selected role is *denied*). Useful for
    // "what is the viewer NOT allowed to do?" review flows.
    const filteredModules = data.modules
      .map((m) => ({
        ...m,
        permissions: m.permissions.filter((p) => {
          const lvl = data.role_hierarchy[roleFilter] ?? -1;
          const minLvl = data.role_hierarchy[p.min_role] ?? Number.POSITIVE_INFINITY;
          return lvl < minLvl;
        }),
      }))
      .filter((m) => m.permissions.length > 0);
    return { ...data, modules: filteredModules };
  }, [data, roleFilter]);

  const visibleStats = useMemo(() => {
    if (!visibleData) return { modules: 0, permissions: 0 };
    const q = normalise(query);
    let modules = 0;
    let permissions = 0;
    for (const m of visibleData.modules) {
      const matches = q
        ? m.permissions.filter(
            (p) => normalise(p.key).includes(q) || normalise(m.name).includes(q),
          ).length
        : m.permissions.length;
      if (matches > 0) {
        modules += 1;
        permissions += matches;
      }
    }
    return { modules, permissions };
  }, [visibleData, query]);

  // Edit mode is only available to admins — fall back silently if the
  // caller is not admin (per the brief, never break the page).
  const canEdit = isAdmin && editMode;

  // The role the per-group tri-state checkbox + granted counts act on.
  // Reuses the existing role dropdown: "All roles" → null (counts show
  // plain permission totals; the bulk checkbox is shown disabled).
  const selectedRole: MatrixRole | null = roleFilter === 'all' ? null : (roleFilter as MatrixRole);

  // Does a permission match the active search query? (Same matcher the
  // group headers use, hoisted so the page-level stats agree with the
  // per-group counts.) Memoized so typing in search stays smooth across
  // ~512 rows.
  const permMatchesQuery = useMemo(() => {
    const q = normalise(query);
    return (moduleName: string, key: string) => {
      if (!q) return true;
      const label = normalise(humanizeModule(moduleName, t));
      return (
        normalise(key).includes(q) ||
        normalise(permissionAction(key)).includes(q) ||
        normalise(moduleName).includes(q) ||
        label.includes(q)
      );
    };
  }, [query, t]);

  // Module names that currently have at least one search match — used to
  // drive Expand-all / Collapse-all and the "auto-expand on search"
  // behaviour. Computed from the full matrix (counts span the whole
  // module, not just the denied-only rows).
  const matchingModuleNames = useMemo(() => {
    if (!data) return [] as string[];
    return data.modules
      .filter((m) => m.permissions.some((p) => permMatchesQuery(m.name, p.key)))
      .map((m) => m.name);
  }, [data, permMatchesQuery]);

  // Whole-matrix "granted" summary for the selected role. When no role is
  // picked we fall back to the module/permission totals. Memoized.
  const grantSummary = useMemo(() => {
    if (!data) return { total: 0, granted: 0 };
    let total = 0;
    let granted = 0;
    for (const m of data.modules) {
      for (const p of m.permissions) {
        if (!permMatchesQuery(m.name, p.key)) continue;
        total += 1;
        if (selectedRole && cellState(selectedRole, p.min_role, data.role_hierarchy) === 'allowed') {
          granted += 1;
        }
      }
    }
    return { total, granted };
  }, [data, selectedRole, permMatchesQuery]);

  // A search query force-expands any group with matches; otherwise the
  // group obeys the explicit per-group expand state (collapsed default).
  const hasQuery = normalise(query).length > 0;
  const isExpanded = (moduleName: string) =>
    hasQuery ? true : Boolean(expandedGroups[moduleName]);

  // Are *all* matching groups currently expanded? Drives the global
  // Expand-all / Collapse-all toggle label + icon.
  const allExpanded =
    matchingModuleNames.length > 0 &&
    (hasQuery || matchingModuleNames.every((name) => expandedGroups[name]));

  const handleToggleAll = () => {
    if (allExpanded) {
      setExpandedGroups({});
    } else {
      const next: Record<string, boolean> = {};
      for (const name of matchingModuleNames) next[name] = true;
      setExpandedGroups(next);
    }
  };

  // Per-module denied-only display perms (the existing role-filter
  // semantic, kept verbatim) — extracted so we can render over the FULL
  // module list (so fully-allowed modules stay reachable for bulk-revoke)
  // while individual rows still honour "show only what the role can't do".
  const displayPermsFor = (m: PermissionsMatrix['modules'][number]): MatrixPermission[] => {
    if (!data || !selectedRole) return m.permissions;
    const lvl = data.role_hierarchy[selectedRole] ?? -1;
    return m.permissions.filter((p) => {
      const minLvl = data.role_hierarchy[p.min_role] ?? Number.POSITIVE_INFINITY;
      return lvl < minLvl;
    });
  };

  if (!canViewMatrix) {
    return (
      <div className="p-4">
        <NoAccessState />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-4" data-testid="permissions-matrix-loading">
        <SkeletonTable rows={8} columns={5} />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<ShieldCheck className="text-rose-500" size={48} aria-hidden />}
          title={t('admin.permissions.error_title', {
            defaultValue: 'Could not load permissions matrix',
          })}
          description={
            error instanceof Error
              ? error.message
              : t('admin.permissions.error_unknown', {
                  defaultValue: 'Unknown error',
                })
          }
        />
      </div>
    );
  }

  // Genuine empty state = the backend registered no permissions at all.
  // (We deliberately check `data`, not the role-filtered `visibleData`,
  // so a fully-privileged role doesn't trip the "nothing registered"
  // screen — those modules still render via the full module list below.)
  if (!data || data.modules.length === 0 || !visibleData) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<ShieldCheck size={48} aria-hidden />}
          title={t('admin.permissions.empty_title', {
            defaultValue: 'No permissions registered',
          })}
          description={t('admin.permissions.empty_description', {
            defaultValue:
              'No modules have registered permissions yet. They appear here as soon as a module loads.',
          })}
        />
      </div>
    );
  }

  // Compute confirmation modal text outside the JSX for clarity.
  let confirmTitle = '';
  let confirmMessage = '';
  let confirmLabel: string | undefined;
  let confirmVariant: 'danger' | 'warning' = 'warning';
  if (confirmState?.kind === 'toggle') {
    confirmTitle = t('admin.permissions.confirm_toggle_title', {
      defaultValue: 'Change permission?',
    });
    confirmMessage = t('admin.permissions.confirm_toggle_message', {
      defaultValue: 'Set "{{key}}" minimum role from {{from}} to {{to}}? This is audit-logged.',
      key: confirmState.permissionKey,
      from: confirmState.currentMinRole,
      to: confirmState.newMinRole,
    });
    confirmLabel = t('admin.permissions.confirm_toggle_confirm', { defaultValue: 'Change' });
  } else if (confirmState?.kind === 'preset') {
    confirmTitle = t('admin.permissions.confirm_preset_title', {
      defaultValue: 'Apply preset?',
    });
    confirmMessage = t('admin.permissions.confirm_preset_message', {
      defaultValue: 'Reset every permission to the "{{preset}}" baseline? This rewrites the entire matrix and is audit-logged.',
      preset: confirmState.preset,
    });
    confirmLabel = t('admin.permissions.confirm_preset_confirm', { defaultValue: 'Apply preset' });
    confirmVariant = 'danger';
  } else if (confirmState?.kind === 'lockout') {
    confirmTitle = t('admin.permissions.lockout_title', {
      defaultValue: 'Cannot demote admin permission',
    });
    confirmMessage = t('admin.permissions.lockout_message', {
      defaultValue: '"{{key}}" must remain admin-only - lowering it would let non-admins edit the permissions matrix and lock you out.',
      key: confirmState.permissionKey,
    });
    confirmLabel = t('admin.permissions.lockout_dismiss', { defaultValue: 'Got it' });
  } else if (confirmState?.kind === 'bulk') {
    const moduleLabel = humanizeModule(confirmState.moduleName, t);
    if (confirmState.grant) {
      confirmTitle = t('admin.permissions.confirm_bulk_grant_title', {
        defaultValue: 'Grant module to {{role}}?',
        role: confirmState.role,
      });
      confirmMessage = t('admin.permissions.confirm_bulk_grant_message', {
        defaultValue:
          'Grant {{count}} "{{module}}" permission(s) to {{role}} (sets each minimum role to {{role}})? This is audit-logged.',
        count: confirmState.keys.length,
        module: moduleLabel,
        role: confirmState.role,
      });
      confirmLabel = t('admin.permissions.confirm_bulk_grant_confirm', { defaultValue: 'Grant all' });
    } else {
      confirmTitle = t('admin.permissions.confirm_bulk_revoke_title', {
        defaultValue: 'Revoke module from {{role}}?',
        role: confirmState.role,
      });
      confirmMessage = t('admin.permissions.confirm_bulk_revoke_message', {
        defaultValue:
          'Revoke {{count}} "{{module}}" permission(s) from {{role}} (raises each minimum role to {{target}})? This is audit-logged.',
        count: confirmState.keys.length,
        module: moduleLabel,
        role: confirmState.role,
        target: confirmState.target,
      });
      confirmLabel = t('admin.permissions.confirm_bulk_revoke_confirm', { defaultValue: 'Revoke all' });
      confirmVariant = 'danger';
    }
  }

  return (
    <div
      className="relative min-h-full overflow-hidden"
      data-testid="permissions-matrix-page"
    >
      {/* Page-level gradient backdrop (mirrors CoordinationHubPage). */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-br from-sky-50 via-white to-emerald-50/40 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 -left-40 -z-10 h-96 w-96 rounded-full bg-gradient-radial from-sky-400/15 to-transparent blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 -right-40 -z-10 h-96 w-96 rounded-full bg-gradient-radial from-emerald-400/15 to-transparent blur-3xl"
      />

      <div className="space-y-5 px-4 py-5 lg:px-6 lg:py-6">
        {/* Hero header — glass pill */}
        <header className="relative overflow-hidden rounded-2xl border border-white/40 bg-white/60 px-5 py-4 backdrop-blur-xl shadow-lg shadow-slate-900/[0.04] dark:border-white/5 dark:bg-slate-900/40">
          <div
            aria-hidden
            className="pointer-events-none absolute -top-16 right-1/4 h-40 w-40 rounded-full bg-gradient-radial from-sky-400/20 to-transparent blur-3xl"
          />
          <div className="relative flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-md shadow-sky-500/25">
                <ShieldCheck size={22} />
              </div>
              <div>
                <h1 className="text-lg font-bold tracking-tight text-content-primary">
                  {t('admin.permissions.title', { defaultValue: 'Permissions Matrix' })}
                </h1>
                <p className="mt-0.5 text-sm text-content-secondary max-w-3xl">
                  {canEdit
                    ? t('admin.permissions.subtitle_edit', {
                        defaultValue:
                          'Click any cell to set the minimum role for that permission. Changes apply immediately and are audit-logged.',
                      })
                    : t('admin.permissions.subtitle', {
                        defaultValue:
                          'Every permission registered by every module, and which roles can use it. Admin always passes - locked cells indicate admin-only by design.',
                      })}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={handleExportCsv}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/40 bg-white/70 px-3 py-1.5 text-sm font-medium text-text-secondary hover:bg-white/90 focus:outline-none focus:ring-2 focus:ring-accent-primary"
                data-testid="permissions-matrix-export-csv"
              >
                <Download size={14} aria-hidden />
                {t('admin.permissions.export_csv', { defaultValue: 'Export CSV' })}
              </button>
              {isAdmin && (
                <button
                  type="button"
                  onClick={() => setEditMode((v) => !v)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-accent-primary',
                    canEdit
                      ? 'bg-amber-500 text-white hover:bg-amber-600'
                      : 'border border-white/40 bg-white/70 text-text-secondary hover:bg-white/90',
                  )}
                  data-testid="permissions-matrix-edit-toggle"
                  aria-pressed={canEdit}
                >
                  {canEdit
                    ? t('admin.permissions.edit_off', { defaultValue: 'Done editing' })
                    : t('admin.permissions.edit_on', { defaultValue: 'Enable edit mode' })}
                </button>
              )}
            </div>
          </div>
        </header>

        {/* Filter bar — glass card */}
        <div className="relative overflow-hidden rounded-2xl border border-white/40 bg-white/60 px-4 py-3 backdrop-blur-xl">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[240px] max-w-md">
              <Search
                size={16}
                className="absolute start-3 top-1/2 -translate-y-1/2 text-text-tertiary pointer-events-none"
                aria-hidden
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('admin.permissions.search_placeholder', {
                  defaultValue: 'Filter by module or permission key',
                })}
                aria-label={t('admin.permissions.search_label', {
                  defaultValue: 'Search permissions',
                })}
                data-testid="permissions-matrix-search"
                className="w-full ps-9 pe-3 py-2 text-sm border border-border-light rounded-md bg-white/80 focus:outline-none focus:ring-2 focus:ring-accent-primary"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-text-secondary">
              <span className="text-xs uppercase tracking-wider text-text-tertiary">
                {t('admin.permissions.role_filter_label', { defaultValue: 'Role' })}
              </span>
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value as MatrixRole | 'all')}
                data-testid="permissions-matrix-role-filter"
                className="px-2 py-1.5 text-sm border border-border-light rounded-md bg-white/80 focus:outline-none focus:ring-2 focus:ring-accent-primary"
              >
                <option value="all">
                  {t('admin.permissions.role_filter_all', { defaultValue: 'All roles' })}
                </option>
                {data?.roles.map((r) => (
                  <option key={r} value={r}>
                    {t('admin.permissions.role_filter_denied_to', {
                      defaultValue: 'Denied to {{role}}',
                      role: r,
                    })}
                  </option>
                ))}
              </select>
            </label>
            {canEdit && data?.presets && data.presets.length > 0 && (
              <div className="flex items-center gap-1.5 ml-auto">
                <span className="text-xs uppercase tracking-wider text-text-tertiary">
                  {t('admin.permissions.preset_label', { defaultValue: 'Reset to preset' })}
                </span>
                {data.presets.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setConfirmState({ kind: 'preset', preset })}
                    disabled={presetMutation.isPending}
                    className="inline-flex items-center gap-1 rounded-md border border-border-light bg-white/80 px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-white disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent-primary"
                    data-testid={`permissions-matrix-preset-${preset}`}
                  >
                    <RotateCcw size={11} aria-hidden />
                    {preset}
                  </button>
                ))}
              </div>
            )}
            <div className="ml-auto flex items-center gap-3">
              {/* Global Expand all / Collapse all */}
              <button
                type="button"
                onClick={handleToggleAll}
                disabled={matchingModuleNames.length === 0 || hasQuery}
                data-testid="permissions-matrix-toggle-all"
                aria-expanded={allExpanded}
                title={
                  hasQuery
                    ? t('admin.permissions.toggle_all_search_hint', {
                        defaultValue: 'Groups auto-expand while searching',
                      })
                    : undefined
                }
                className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-white/80 px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-white disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent-primary"
              >
                {allExpanded ? (
                  <ChevronsDownUp size={13} aria-hidden />
                ) : (
                  <ChevronsUpDown size={13} aria-hidden />
                )}
                {allExpanded
                  ? t('admin.permissions.collapse_all', { defaultValue: 'Collapse all' })
                  : t('admin.permissions.expand_all', { defaultValue: 'Expand all' })}
              </button>

              {/* Summary — "N of M granted" for the selected role, else
                  the module/permission totals. */}
              <div className="text-xs text-text-tertiary tabular-nums" data-testid="permissions-matrix-summary">
                {selectedRole
                  ? t('admin.permissions.summary_granted', {
                      defaultValue: '{{granted}} of {{total}} permissions granted',
                      granted: grantSummary.granted,
                      total: grantSummary.total,
                    })
                  : t('admin.permissions.summary', {
                      defaultValue: '{{modules}} modules · {{permissions}} permissions',
                      modules: visibleStats.modules,
                      permissions: visibleStats.permissions,
                    })}
              </div>
            </div>
          </div>
        </div>

        {/* Matrix table — glass card */}
        <div className="relative overflow-hidden rounded-2xl border border-white/40 bg-white/60 backdrop-blur-xl shadow-lg shadow-slate-900/[0.04]">
          <div className="overflow-x-auto">
            <table
              className="w-full text-sm border-collapse"
              data-testid="permissions-matrix-table"
            >
              <thead>
                <tr className="bg-surface-secondary border-b border-border-light">
                  <th
                    scope="col"
                    className="sticky left-0 z-20 bg-surface-secondary px-3 py-2 text-left text-xs uppercase tracking-wider text-text-tertiary border-r border-border-light min-w-[260px]"
                  >
                    {t('admin.permissions.col_permission', {
                      defaultValue: 'Permission',
                    })}
                  </th>
                  {visibleData.roles.map((role) => (
                    <th
                      key={role}
                      scope="col"
                      className={clsx(
                        'px-3 py-2 text-center text-xs uppercase tracking-wider transition-colors cursor-default',
                        hoveredRole === role
                          ? 'bg-accent-primary/10 text-accent-primary'
                          : 'text-text-tertiary',
                      )}
                      onMouseEnter={() => setHoveredRole(role)}
                      onMouseLeave={() => setHoveredRole(null)}
                      onFocus={() => setHoveredRole(role)}
                      onBlur={() => setHoveredRole(null)}
                      data-testid={`role-header-${role}`}
                      tabIndex={0}
                    >
                      {t(`admin.permissions.role_${role}`, {
                        defaultValue: role,
                      })}
                      <div className="text-[10px] font-normal normal-case text-text-tertiary">
                        {role}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.modules.map((module) => (
                  <ModuleRows
                    key={module.name}
                    module={{ ...module, permissions: displayPermsFor(module) }}
                    fullPermissions={module.permissions}
                    roles={data.roles}
                    hierarchy={data.role_hierarchy}
                    hoveredRole={hoveredRole}
                    query={query}
                    collapsed={!isExpanded(module.name)}
                    onToggle={() =>
                      setExpandedGroups((prev) => ({
                        ...prev,
                        [module.name]: !prev[module.name],
                      }))
                    }
                    editable={canEdit}
                    selectedRole={selectedRole}
                    pendingKey={pendingKey}
                    bulkPending={bulkModule === module.name}
                    onCellToggle={handleCellToggle}
                    onBulkToggle={handleBulkToggle}
                    t={t}
                  />
                ))}
                {matchingModuleNames.length === 0 && (
                  <tr>
                    <td
                      colSpan={data.roles.length + 1}
                      className="px-3 py-8 text-center text-sm text-text-tertiary"
                      data-testid="permissions-matrix-no-results"
                    >
                      {t('admin.permissions.no_results', {
                        defaultValue: 'No permissions match "{{query}}".',
                        query,
                      })}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <footer className="text-xs text-text-tertiary flex items-center gap-4 flex-wrap">
          <span className="inline-flex items-center gap-1">
            <Check size={14} className="text-emerald-600" aria-hidden />
            {t('admin.permissions.legend_allowed', { defaultValue: 'allowed' })}
          </span>
          <span className="inline-flex items-center gap-1">
            <XIcon size={14} className="text-rose-500" aria-hidden />
            {t('admin.permissions.legend_denied', { defaultValue: 'denied' })}
          </span>
          <span className="inline-flex items-center gap-1">
            <Lock size={12} className="text-amber-700" aria-hidden />
            {t('admin.permissions.legend_admin_bypass', {
              defaultValue: 'admin-only by design',
            })}
          </span>
          {!isAdmin && (
            <span className="ml-auto inline-flex items-center gap-1 text-amber-700">
              <Lock size={12} aria-hidden />
              {t('admin.permissions.read_only_notice', {
                defaultValue: 'Read-only: admin role required to edit',
              })}
            </span>
          )}
        </footer>
      </div>

      <ConfirmDialog
        open={confirmState !== null}
        onConfirm={handleConfirm}
        onCancel={() => setConfirmState(null)}
        title={confirmTitle}
        message={confirmMessage}
        confirmLabel={confirmLabel}
        variant={confirmState?.kind === 'lockout' ? 'warning' : confirmVariant}
        loading={toggleMutation.isPending || presetMutation.isPending || bulkMutation.isPending}
      />
    </div>
  );
}

export default PermissionsMatrixPage;
