// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ApprovalInstanceDetailDrawer — actionable instance-detail surface for
// the governance "Running & history" tab.
//
// The instances list used to be a read-only dead end: an admin who found
// a stuck pending workflow had no way to inspect or act on it (the only
// decision surface was the originating consumer page, which today only
// markups mounts). This drawer turns the tab into an actionable inbox:
//
//   * Opens for a clicked instance row, re-fetching the live instance via
//     getInstance() (the list query can be stale).
//   * Resolves the route template (getRoute) so we can render the full
//     step ladder — the same buildLadder()/StepRow building blocks the
//     consumer ApprovalInstanceCard uses.
//   * The active approver can approve/reject the current step, and any
//     authorised user can cancel a pending workflow, wired to
//     decideInstance()/cancelInstance(). The backend is the authority —
//     a 403 surfaces as an error toast.
//
// This is the single in-product place where workflows for the seven
// non-markup target kinds (submittal, RFI, change_order, …) can actually
// be decided, since those consumer pages do not yet mount the card.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { Ban, UserCog } from 'lucide-react';

import { Badge, Button, SideDrawer, Skeleton } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  approvalRoutesKeys,
  cancelInstance,
  decideInstance,
  getInstance,
  getRoute,
} from './api';
import {
  buildLadder,
  InstanceStatusBadge,
  StepRow,
} from './ApprovalInstanceCard';
import { kindLabel } from './labels';
import { ReassignDialog } from './ReassignDialog';
import type { StepDecision } from './types';
import { getIntlLocale } from '@/shared/lib/formatters';

interface MeResponse {
  id?: string;
  user_id?: string;
  email?: string;
  role?: string;
}

export interface ApprovalInstanceDetailDrawerProps {
  /** Instance id to inspect; null closes the drawer. */
  instanceId: string | null;
  onClose: () => void;
}

/**
 * Right-side slide-over showing the full step ladder for one running (or
 * closed) approval instance with decide / cancel actions.
 */
export function ApprovalInstanceDetailDrawer({
  instanceId,
  onClose,
}: ApprovalInstanceDetailDrawerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [comments, setComments] = useState<Record<string, string>>({});
  const [reassignOpen, setReassignOpen] = useState(false);

  const open = instanceId != null;

  // Live current-user lookup so we can decide whether to show the
  // approve/reject buttons (mirrors ApprovalInstanceCard).
  const { data: me } = useQuery({
    queryKey: ['me'],
    queryFn: () => apiGet<MeResponse>('/v1/users/me/'),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const currentUserId = me?.id ?? me?.user_id ?? null;

  // Re-fetch the instance fresh — the list query has a 15s staleTime so it
  // can lag behind a decision recorded elsewhere.
  const instanceQuery = useQuery({
    queryKey: instanceId
      ? approvalRoutesKeys.instance(instanceId)
      : ['approval-routes', 'instance', 'none'],
    queryFn: () => getInstance(instanceId!),
    enabled: open,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
  });
  const instance = instanceQuery.data;

  const routeQuery = useQuery({
    queryKey: instance
      ? approvalRoutesKeys.route(instance.route_id)
      : ['approval-routes', 'route', 'none'],
    queryFn: () => getRoute(instance!.route_id),
    enabled: Boolean(instance),
    staleTime: 60_000,
  });

  const invalidateInstance = () => {
    if (instanceId) {
      void qc.invalidateQueries({
        queryKey: approvalRoutesKeys.instance(instanceId),
      });
    }
    // Refresh every instances list flavour so the governance tab reflects
    // the new status/step immediately.
    void qc.invalidateQueries({ queryKey: ['approval-routes', 'instances'] });
  };

  const decideMut = useMutation({
    mutationFn: ({
      stepId,
      decision,
      comment,
    }: {
      stepId: string;
      decision: StepDecision;
      comment: string;
    }) =>
      decideInstance(instanceId!, {
        step_id: stepId,
        decision,
        comment: comment.trim() || null,
      }),
    onSuccess: (updated, vars) => {
      invalidateInstance();
      setComments((prev) => {
        const next = { ...prev };
        delete next[vars.stepId];
        return next;
      });
      addToast({
        type: 'success',
        title:
          updated.status === 'approved'
            ? t('approvalRoutes.toast_approved', { defaultValue: 'Approved' })
            : updated.status === 'rejected'
              ? t('approvalRoutes.toast_rejected', { defaultValue: 'Rejected' })
              : t('approvalRoutes.toast_recorded', {
                  defaultValue: 'Decision recorded',
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

  const cancelMut = useMutation({
    mutationFn: () => cancelInstance(instanceId!, {}),
    onSuccess: () => {
      invalidateInstance();
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_cancelled', {
          defaultValue: 'Approval cancelled',
        }),
      });
      onClose();
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const canListUsers = useHasPermission('users.list');
  const { data: userList = [] } = useQuery<{ id: string; email: string; full_name: string }[]>({
    queryKey: ['users-search'],
    queryFn: () => apiGet('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    enabled: canListUsers,
  });
  const userMap = useMemo(
    () => new Map(userList.map((u) => [u.id, u.full_name || u.email])),
    [userList],
  );

  const ladder = useMemo(
    () => (instance ? buildLadder(routeQuery.data, instance) : []),
    [instance, routeQuery.data],
  );

  const busy = decideMut.isPending || cancelMut.isPending;

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      busy={busy}
      title={
        routeQuery.data?.name ||
        t('approvalRoutes.instance_detail_title', {
          defaultValue: 'Approval workflow',
        })
      }
      subtitle={
        instance
          ? `${kindLabel(t, instance.target_kind)} · ${instance.target_id.slice(0, 8)}…`
          : undefined
      }
    >
      <div className="p-5 space-y-3">
        {instanceQuery.isLoading ? (
          <>
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </>
        ) : instanceQuery.isError || !instance ? (
          <p className="text-sm text-semantic-error">
            {t('approvalRoutes.load_error', {
              defaultValue: 'Failed to load approval workflow.',
            })}
          </p>
        ) : (
          <>
            <div className="flex items-center gap-2 flex-wrap">
              <InstanceStatusBadge status={instance.status} />
              {instance.status === 'pending' && (
                <Badge variant="blue" size="sm">
                  {t('approvalRoutes.step_n_of_m', {
                    defaultValue: 'Step {{n}}/{{m}}',
                    n: instance.current_step_ordinal,
                    m: routeQuery.data?.steps.length ?? instance.current_step_ordinal,
                  })}
                </Badge>
              )}
              {instance.status === 'pending' &&
                instance.current_assignee_user_id && (
                  <Badge variant="warning" size="sm">
                    {t('approvalRoutes.reassigned_badge', {
                      defaultValue: 'Reassigned',
                    })}
                  </Badge>
                )}
              <span className="text-2xs text-content-tertiary ml-auto">
                {t('approvalRoutes.started_on', {
                  defaultValue: 'Started {{date}}',
                  date: new Date(instance.started_at).toLocaleDateString(getIntlLocale()),
                })}
              </span>
            </div>

            <div className="space-y-2">
              {routeQuery.isLoading ? (
                <Skeleton className="h-16 w-full" />
              ) : ladder.length === 0 ? (
                <p className="text-xs text-content-tertiary">
                  {t('approvalRoutes.no_steps', {
                    defaultValue: 'This route has no steps.',
                  })}
                </p>
              ) : (
                ladder.map((rung, idx) => (
                  <StepRow
                    key={rung.step.id}
                    rung={rung}
                    index={idx}
                    total={ladder.length}
                    currentUserId={currentUserId}
                    userMap={userMap}
                    comment={comments[rung.step.id] ?? ''}
                    onCommentChange={(value) =>
                      setComments((p) => ({ ...p, [rung.step.id]: value }))
                    }
                    onDecide={(decision) =>
                      decideMut.mutate({
                        stepId: rung.step.id,
                        decision,
                        comment: comments[rung.step.id] ?? '',
                      })
                    }
                    deciding={
                      decideMut.isPending &&
                      decideMut.variables?.stepId === rung.step.id
                    }
                  />
                ))
              )}
            </div>

            {instance.status === 'pending' && (
              <div className="flex items-center justify-end gap-2 pt-1 border-t border-border-light">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setReassignOpen(true)}
                  disabled={busy}
                  icon={<UserCog size={13} />}
                  data-testid="instance-reassign-button"
                >
                  {t('approvalRoutes.reassign', {
                    defaultValue: 'Reassign',
                  })}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => cancelMut.mutate()}
                  loading={cancelMut.isPending}
                  disabled={busy}
                  icon={<Ban size={13} />}
                >
                  {t('approvalRoutes.cancel', {
                    defaultValue: 'Cancel workflow',
                  })}
                </Button>
              </div>
            )}
          </>
        )}
      </div>

      {instance && instance.status === 'pending' && (
        <ReassignDialog
          open={reassignOpen}
          onClose={() => setReassignOpen(false)}
          instance={instance}
        />
      )}
    </SideDrawer>
  );
}
