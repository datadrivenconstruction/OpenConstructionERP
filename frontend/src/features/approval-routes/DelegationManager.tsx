// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DelegationManager - out-of-office hand-off manager.
//
// Lets the signed-in user delegate their approvals to a colleague while
// they are away (and revoke that hand-off when they are back), wired to
// GET/POST/DELETE /approval-routes/delegations. The delegator is always
// the authenticated caller server-side, so this surface only ever shows
// and edits the caller's own hand-offs. An optional date window scopes
// when the hand-off is live; an optional project scopes it to one project
// (otherwise it is a blanket hand-off across every project).

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2, UserCheck, UserMinus } from 'lucide-react';

import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Skeleton,
  WideModal,
  WideModalSection,
} from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import {
  approvalRoutesKeys,
  createDelegation,
  listDelegations,
  revokeDelegation,
} from './api';
import type { ApprovalDelegation } from './types';
import { getIntlLocale } from '@/shared/lib/formatters';

interface UserResult {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

interface ProjectResult {
  id: string;
  name: string;
}

export interface DelegationManagerProps {
  open: boolean;
  onClose: () => void;
}

/** Convert an empty/blank datetime-local value to null, otherwise to an
 *  ISO-8601 string the backend accepts. ``datetime-local`` yields a value
 *  like ``2026-06-30T09:00`` (local, no zone); ``new Date(...)`` parses it
 *  as local time and ``toISOString`` normalises to UTC. */
function toIso(value: string): string | null {
  const v = value.trim();
  if (!v) return null;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

/**
 * Modal that lists the caller's active out-of-office delegations and lets
 * them create a new hand-off or revoke an existing one.
 */
export function DelegationManager({ open, onClose }: DelegationManagerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [delegateId, setDelegateId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [startsAt, setStartsAt] = useState('');
  const [endsAt, setEndsAt] = useState('');
  const [reason, setReason] = useState('');
  const [revokeTarget, setRevokeTarget] = useState<ApprovalDelegation | null>(
    null,
  );

  // Reset the create form whenever the modal opens.
  useEffect(() => {
    if (!open) return;
    setDelegateId('');
    setProjectId('');
    setStartsAt('');
    setEndsAt('');
    setReason('');
    setRevokeTarget(null);
  }, [open]);

  const delegationsQuery = useQuery({
    queryKey: approvalRoutesKeys.delegations('mine', false),
    queryFn: () => listDelegations({ role: 'mine', includeInactive: false }),
    enabled: open,
    staleTime: 15_000,
  });
  const delegations = delegationsQuery.data ?? [];

  // Same active-users source the route editor + reassign dialog use.
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserResult[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    enabled: open,
  });
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<ProjectResult[]>(),
    staleTime: 5 * 60_000,
    enabled: open,
  });

  const userName = useMemo(() => {
    const m = new Map<string, string>();
    for (const u of users) m.set(u.id, u.full_name || u.email);
    return m;
  }, [users]);
  const projectName = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of projects) m.set(p.id, p.name);
    return m;
  }, [projects]);

  const invalidate = () =>
    void qc.invalidateQueries({ queryKey: ['approval-routes', 'delegations'] });

  // Client-side mirror of the backend window guard (ends_at >= starts_at).
  const windowError = useMemo(() => {
    const s = toIso(startsAt);
    const e = toIso(endsAt);
    if (s && e && e < s) {
      return t('approvalRoutes.delegation_window_error', {
        defaultValue: 'The end date must not be before the start date.',
      });
    }
    return null;
  }, [startsAt, endsAt, t]);

  const createMut = useMutation({
    mutationFn: () =>
      createDelegation({
        delegate_user_id: delegateId,
        project_id: projectId || null,
        starts_at: toIso(startsAt),
        ends_at: toIso(endsAt),
        reason: reason.trim() || null,
      }),
    onSuccess: () => {
      invalidate();
      setDelegateId('');
      setProjectId('');
      setStartsAt('');
      setEndsAt('');
      setReason('');
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_delegation_created', {
          defaultValue: 'Delegation created',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const revokeMut = useMutation({
    mutationFn: (id: string) => revokeDelegation(id),
    onSuccess: () => {
      invalidate();
      setRevokeTarget(null);
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_delegation_revoked', {
          defaultValue: 'Delegation revoked',
        }),
      });
    },
    onError: (e: Error) => {
      setRevokeTarget(null);
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      });
    },
  });

  const busy = createMut.isPending || revokeMut.isPending;
  const canCreate = Boolean(delegateId) && !windowError && !createMut.isPending;

  const formatWindow = (d: ApprovalDelegation): string => {
    const fmt = (iso: string | null) =>
      iso ? new Date(iso).toLocaleDateString(getIntlLocale()) : null;
    const from = fmt(d.starts_at);
    const to = fmt(d.ends_at);
    if (from && to)
      return t('approvalRoutes.delegation_window_range', {
        defaultValue: '{{from}} - {{to}}',
        from,
        to,
      });
    if (from)
      return t('approvalRoutes.delegation_window_from', {
        defaultValue: 'From {{from}}',
        from,
      });
    if (to)
      return t('approvalRoutes.delegation_window_until', {
        defaultValue: 'Until {{to}}',
        to,
      });
    return t('approvalRoutes.delegation_window_always', {
      defaultValue: 'Always active',
    });
  };

  const inputCls =
    'h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('approvalRoutes.delegation_title', {
        defaultValue: 'Out-of-office delegation',
      })}
      subtitle={t('approvalRoutes.delegation_subtitle', {
        defaultValue:
          'Hand your approvals to a colleague while you are away. They can decide on your behalf until you revoke it or the window ends.',
      })}
      footer={
        <Button variant="ghost" size="md" onClick={onClose} disabled={busy}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      }
    >
      {/* -- Active delegations --------------------------------------- */}
      <WideModalSection
        title={t('approvalRoutes.delegation_active_title', {
          defaultValue: 'Active delegations',
        })}
        columns={1}
      >
        {delegationsQuery.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : delegations.length === 0 ? (
          <EmptyState
            icon={<UserCheck size={26} strokeWidth={1.5} />}
            title={t('approvalRoutes.delegation_empty_title', {
              defaultValue: 'No active delegations',
            })}
            description={t('approvalRoutes.delegation_empty_desc', {
              defaultValue:
                'You are not delegating any approvals right now. Create one below before you go out of office.',
            })}
          />
        ) : (
          <ul className="space-y-2" data-testid="delegation-list">
            {delegations.map((d) => (
              <li
                key={d.id}
                className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2"
              >
                <UserCheck
                  size={16}
                  className="shrink-0 text-oe-blue"
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-content-primary truncate">
                    {t('approvalRoutes.delegation_covering', {
                      defaultValue: 'Covered by {{name}}',
                      name:
                        userName.get(d.delegate_user_id) ?? d.delegate_user_id,
                    })}
                  </p>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-content-tertiary">
                    <span>{formatWindow(d)}</span>
                    <Badge variant={d.project_id ? 'neutral' : 'blue'} size="sm">
                      {d.project_id
                        ? (projectName.get(d.project_id) ??
                          t('approvalRoutes.scope_project', {
                            defaultValue: 'Project',
                          }))
                        : t('approvalRoutes.delegation_all_projects', {
                            defaultValue: 'All projects',
                          })}
                    </Badge>
                    {d.reason && (
                      <span className="truncate" title={d.reason}>
                        {d.reason}
                      </span>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setRevokeTarget(d)}
                  disabled={busy}
                  className="shrink-0 p-1.5 rounded-md text-semantic-error/70 hover:text-semantic-error hover:bg-surface-secondary disabled:opacity-40 transition-colors"
                  title={t('approvalRoutes.delegation_revoke', {
                    defaultValue: 'Revoke delegation',
                  })}
                  aria-label={t('approvalRoutes.delegation_revoke', {
                    defaultValue: 'Revoke delegation',
                  })}
                  data-testid={`delegation-revoke-${d.id}`}
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </WideModalSection>

      {/* -- Create a delegation -------------------------------------- */}
      <WideModalSection
        title={t('approvalRoutes.delegation_create_title', {
          defaultValue: 'Delegate my approvals',
        })}
        columns={2}
      >
        <div className="sm:col-span-2">
          <label
            htmlFor="delegation-user"
            className="block text-xs font-medium text-content-secondary mb-1"
          >
            {t('approvalRoutes.delegation_delegate', {
              defaultValue: 'Delegate to',
            })}
            <span className="text-semantic-error ml-0.5">*</span>
          </label>
          <select
            id="delegation-user"
            value={delegateId}
            onChange={(e) => setDelegateId(e.target.value)}
            className={`${inputCls} cursor-pointer`}
            data-testid="delegation-user-select"
          >
            <option value="">
              {t('approvalRoutes.pick_user', { defaultValue: 'Pick user…' })}
            </option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name || u.email}
              </option>
            ))}
          </select>
        </div>

        <div className="sm:col-span-2">
          <label
            htmlFor="delegation-project"
            className="block text-xs font-medium text-content-secondary mb-1"
          >
            {t('approvalRoutes.delegation_project', {
              defaultValue: 'Scope (optional)',
            })}
          </label>
          <select
            id="delegation-project"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className={`${inputCls} cursor-pointer`}
          >
            <option value="">
              {t('approvalRoutes.delegation_all_projects', {
                defaultValue: 'All projects',
              })}
            </option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="delegation-start"
            className="block text-xs font-medium text-content-secondary mb-1"
          >
            {t('approvalRoutes.delegation_starts', {
              defaultValue: 'Starts (optional)',
            })}
          </label>
          <input
            id="delegation-start"
            type="datetime-local"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            className={inputCls}
          />
        </div>

        <div>
          <label
            htmlFor="delegation-end"
            className="block text-xs font-medium text-content-secondary mb-1"
          >
            {t('approvalRoutes.delegation_ends', {
              defaultValue: 'Ends (optional)',
            })}
          </label>
          <input
            id="delegation-end"
            type="datetime-local"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
            className={inputCls}
          />
        </div>

        <div className="sm:col-span-2">
          <label
            htmlFor="delegation-reason"
            className="block text-xs font-medium text-content-secondary mb-1"
          >
            {t('approvalRoutes.delegation_reason', {
              defaultValue: 'Reason (optional)',
            })}
          </label>
          <textarea
            id="delegation-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            maxLength={500}
            placeholder={t('approvalRoutes.delegation_reason_placeholder', {
              defaultValue: 'e.g. Annual leave - back on the 8th.',
            })}
            className="w-full rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
          />
        </div>

        {windowError && (
          <p className="sm:col-span-2 text-xs text-semantic-error">
            {windowError}
          </p>
        )}

        <div className="sm:col-span-2 flex justify-end">
          <Button
            variant="primary"
            size="sm"
            onClick={() => createMut.mutate()}
            loading={createMut.isPending}
            disabled={!canCreate}
            icon={<UserMinus size={14} />}
            data-testid="delegation-create-button"
          >
            {t('approvalRoutes.delegation_create_button', {
              defaultValue: 'Create delegation',
            })}
          </Button>
        </div>
      </WideModalSection>

      <ConfirmDialog
        open={revokeTarget !== null}
        onConfirm={() => revokeTarget && revokeMut.mutate(revokeTarget.id)}
        onCancel={() => setRevokeTarget(null)}
        title={t('approvalRoutes.delegation_revoke_title', {
          defaultValue: 'Revoke delegation',
        })}
        message={t('approvalRoutes.delegation_revoke_message', {
          defaultValue:
            'The stand-in will no longer be able to approve on your behalf. This cannot be undone.',
        })}
        confirmLabel={t('approvalRoutes.delegation_revoke', {
          defaultValue: 'Revoke delegation',
        })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        loading={revokeMut.isPending}
      />
    </WideModal>
  );
}

export default DelegationManager;
