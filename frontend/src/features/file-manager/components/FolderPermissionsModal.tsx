/** Modal for managing per-folder permissions.
 *
 * Opens from the gear icon on a folder card (owner-only). Lists the
 * existing viewer/editor/owner grants on this ``(kind, path)`` and
 * provides a small sub-form to grant access to any project member.
 *
 * Empty state surfaces "All members can access this folder" so the
 * default contract is obvious — folders are only restricted once at
 * least one grant exists.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Loader2,
  Lock,
  ShieldCheck,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet } from '@/shared/lib/api';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import {
  grantFolderPermission,
  listFolderPermissions,
  revokeFolderPermission,
} from '../api';
import type {
  FileKind,
  FolderPermissionCreatePayload,
  FolderPermissionRow,
  FolderRole,
} from '../types';

const ROLES: ReadonlyArray<{ value: FolderRole; labelKey: string; defaultLabel: string }> = [
  {
    value: 'viewer',
    labelKey: 'files.permissions.role.viewer',
    defaultLabel: 'Viewer — read only',
  },
  {
    value: 'editor',
    labelKey: 'files.permissions.role.editor',
    defaultLabel: 'Editor — upload + delete own',
  },
  {
    value: 'owner',
    labelKey: 'files.permissions.role.owner',
    defaultLabel: 'Owner — full control',
  },
];

interface ProjectMember {
  user_id: string;
  email: string;
  full_name: string;
  is_owner: boolean;
}

export interface FolderPermissionsModalProps {
  open: boolean;
  projectId: string | null;
  scopeKind: FileKind | null;
  scopePath?: string | null;
  /** Folder display label — used for the modal subtitle. */
  folderLabel?: string;
  onClose: () => void;
}

export function FolderPermissionsModal({
  open,
  projectId,
  scopeKind,
  scopePath,
  folderLabel,
  onClose,
}: FolderPermissionsModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [selectedUserId, setSelectedUserId] = useState<string>('');
  const [selectedRole, setSelectedRole] = useState<FolderRole>('viewer');
  const [granting, setGranting] = useState(false);
  const [grantError, setGrantError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  // Permissions for this exact (kind, path).
  const { data: grants = [], isLoading: grantsLoading } = useQuery<
    FolderPermissionRow[]
  >({
    queryKey: [
      'folder-permissions',
      projectId ?? null,
      scopeKind ?? null,
      scopePath ?? null,
    ],
    queryFn: () => {
      if (!projectId || !scopeKind) return Promise.resolve([] as FolderPermissionRow[]);
      return listFolderPermissions(projectId, {
        scope_kind: scopeKind,
        scope_path: scopePath ?? undefined,
      });
    },
    enabled: open && !!projectId && !!scopeKind,
    staleTime: 5_000,
  });

  // Project members — used for the "grant access" picker.
  const { data: members = [] } = useQuery<ProjectMember[]>({
    queryKey: ['project-members', projectId],
    queryFn: () => apiGet<ProjectMember[]>(`/v1/projects/${projectId}/members/`),
    enabled: open && !!projectId,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!open) {
      setSelectedUserId('');
      setSelectedRole('viewer');
      setGranting(false);
      setGrantError(null);
      setRevokingId(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const invalidate = useCallback(() => {
    if (!projectId) return;
    queryClient.invalidateQueries({
      queryKey: ['folder-permissions', projectId],
    });
    queryClient.invalidateQueries({
      queryKey: ['folder-permission-counts', projectId],
    });
  }, [queryClient, projectId]);

  // Filter out members who already have a grant on this folder so the
  // picker can't generate a guaranteed 409.
  const grantedUserIds = useMemo(
    () => new Set(grants.map((g) => g.user_id)),
    [grants],
  );
  const grantableMembers = useMemo(
    () => members.filter((m) => !m.is_owner && !grantedUserIds.has(m.user_id)),
    [members, grantedUserIds],
  );

  async function handleGrant() {
    if (!projectId || !scopeKind || !selectedUserId) return;
    setGranting(true);
    setGrantError(null);
    try {
      const payload: FolderPermissionCreatePayload = {
        user_id: selectedUserId,
        scope_kind: scopeKind,
        scope_path: scopePath ?? null,
        role: selectedRole,
      };
      await grantFolderPermission(projectId, payload);
      setSelectedUserId('');
      setSelectedRole('viewer');
      invalidate();
      addToast({
        type: 'success',
        title: t('files.permissions.grant', { defaultValue: 'Grant access' }),
      });
    } catch (e) {
      const msg = (e as Error).message;
      // Common errors: 409 duplicate, 400 bad role, 403 not owner.
      const isDuplicate = /409|already/i.test(msg);
      const friendly = isDuplicate
        ? t('files.permissions.error_duplicate', {
            defaultValue: 'This member already has access at this level.',
          })
        : t('files.permissions.error_grant', {
            defaultValue: 'Could not grant access.',
          });
      setGrantError(friendly);
    } finally {
      setGranting(false);
    }
  }

  async function handleRevoke(row: FolderPermissionRow) {
    if (!projectId) return;
    const name = row.user_full_name || row.user_email || row.user_id;
    const ok = await confirm({
      title: t('files.permissions.revoke_title', {
        defaultValue: 'Revoke access?',
      }),
      message: t('files.permissions.revoke_confirm', {
        defaultValue: 'Revoke access for {{name}}?',
        name,
      }),
      confirmLabel: t('files.permissions.revoke', { defaultValue: 'Revoke' }),
      variant: 'danger',
    });
    if (!ok) return;
    setRevokingId(row.id);
    try {
      await revokeFolderPermission(projectId, row.id);
      invalidate();
    } catch {
      addToast({
        type: 'error',
        title: t('files.permissions.error_revoke', {
          defaultValue: 'Could not revoke access.',
        }),
      });
    } finally {
      setRevokingId(null);
    }
  }

  if (!open) return null;

  const displayLabel = folderLabel || scopeKind || '';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="folder-permissions-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl bg-surface-elevated shadow-2xl border border-border-light"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-border-light px-6 py-4">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-50 dark:bg-amber-950/30">
              <Lock size={16} className="text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <h2
                id="folder-permissions-title"
                className="text-base font-semibold text-content-primary"
              >
                {t('files.permissions.title', { defaultValue: 'Folder access' })}
              </h2>
              <p className="mt-0.5 text-xs text-content-tertiary">
                {t('files.permissions.subtitle', {
                  defaultValue: 'Restrict who can see and edit files in {{folder}}.',
                  folder: displayLabel,
                })}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 -mt-1 rounded-lg p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={16} />
          </button>
        </header>

        <div className="px-6 py-5 space-y-6">
          {/* Current grants list */}
          <section data-testid="folder-permissions-list">
            <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              <Users size={12} />
              {t('files.permissions.list_title', { defaultValue: 'Current access' })}
            </h3>

            {grantsLoading ? (
              <div className="flex items-center gap-2 text-xs text-content-tertiary py-3">
                <Loader2 size={12} className="animate-spin" />
                {t('files.share.creating', { defaultValue: 'Loading…' })}
              </div>
            ) : grants.length === 0 ? (
              <p
                data-testid="folder-permissions-empty"
                className="rounded-lg border border-dashed border-border-light bg-surface-secondary/40 px-3 py-4 text-center text-xs text-content-secondary"
              >
                {t('files.permissions.empty', {
                  defaultValue: 'All project members can access this folder.',
                })}
              </p>
            ) : (
              <ul className="space-y-1.5">
                {grants.map((row) => (
                  <li
                    key={row.id}
                    data-testid={`folder-permission-row-${row.id}`}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border-light bg-surface-primary px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-content-primary">
                        {row.user_full_name || row.user_email || row.user_id}
                      </p>
                      <p className="truncate text-[10px] text-content-tertiary">
                        {row.user_email}
                      </p>
                    </div>
                    <span
                      className={clsx(
                        'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
                        row.role === 'viewer' && 'bg-sky-50 text-sky-700 dark:bg-sky-950/30 dark:text-sky-300',
                        row.role === 'editor' && 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300',
                        row.role === 'owner' && 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300',
                      )}
                    >
                      <ShieldCheck size={10} />
                      {row.role}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRevoke(row)}
                      disabled={revokingId === row.id}
                      data-testid={`folder-permission-revoke-${row.id}`}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-content-tertiary hover:bg-rose-50 hover:text-rose-700 dark:hover:bg-rose-950/30 dark:hover:text-rose-300 transition-colors disabled:opacity-50"
                    >
                      {revokingId === row.id ? (
                        <Loader2 size={10} className="animate-spin" />
                      ) : (
                        <Trash2 size={10} />
                      )}
                      {t('files.permissions.revoke', { defaultValue: 'Revoke' })}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Grant access sub-form */}
          <section data-testid="folder-permissions-grant">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('files.permissions.grant_title', { defaultValue: 'Grant access' })}
            </h3>

            <div className="space-y-2.5">
              <label className="block text-[11px] font-medium text-content-secondary">
                {t('files.permissions.user_label', { defaultValue: 'Member' })}
                <select
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(e.target.value)}
                  data-testid="folder-permissions-user-picker"
                  className="mt-1 w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                >
                  <option value="">
                    {t('files.permissions.user_placeholder', {
                      defaultValue: 'Choose a project member',
                    })}
                  </option>
                  {grantableMembers.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name || m.email}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block text-[11px] font-medium text-content-secondary">
                {t('files.permissions.role_label', { defaultValue: 'Role' })}
                <select
                  value={selectedRole}
                  onChange={(e) => setSelectedRole(e.target.value as FolderRole)}
                  data-testid="folder-permissions-role-picker"
                  className="mt-1 w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {t(r.labelKey, { defaultValue: r.defaultLabel })}
                    </option>
                  ))}
                </select>
              </label>

              {grantError && (
                <p className="flex items-start gap-1.5 rounded-md bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-700 dark:bg-rose-950/30 dark:text-rose-300">
                  <AlertTriangle size={11} className="mt-0.5 shrink-0" />
                  {grantError}
                </p>
              )}

              <button
                type="button"
                onClick={handleGrant}
                disabled={!selectedUserId || granting}
                data-testid="folder-permissions-grant-button"
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-oe-blue px-3 py-2 text-xs font-semibold text-white hover:bg-oe-blue-hover transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              >
                {granting ? (
                  <>
                    <Loader2 size={12} className="animate-spin" />
                    {t('files.permissions.granting', { defaultValue: 'Granting…' })}
                  </>
                ) : (
                  t('files.permissions.grant', { defaultValue: 'Grant access' })
                )}
              </button>
            </div>
          </section>
        </div>
      </div>
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
