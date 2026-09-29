// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ReassignDialog - one-tap hand-off of a running instance's current step
// to another user.
//
// The route template pins each step to a role or a specific user, but a
// real approval often needs to be handed to a colleague mid-flight (the
// named approver is out, or the wrong person was pinned). This modal lets
// an authorised user pin a different decider for the LIVE step only,
// without editing the shared template, wired to POST
// /instances/{id}/reassign. The backend stores it as
// current_assignee_user_id on the instance.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useHasPermission } from '@/shared/lib/permissionGates';

import { Button, WideModal, WideModalSection } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { approvalRoutesKeys, reassignInstance } from './api';
import type { ApprovalInstance } from './types';

interface UserResult {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

export interface ReassignDialogProps {
  open: boolean;
  onClose: () => void;
  /** The running instance whose current step is being handed off. */
  instance: ApprovalInstance;
}

/**
 * Modal picker that reassigns the current step of one pending instance to
 * a chosen user. Reuses the same active-users <select> source the route
 * editor uses so the two never drift.
 */
export function ReassignDialog({ open, onClose, instance }: ReassignDialogProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [toUserId, setToUserId] = useState('');
  const [reason, setReason] = useState('');

  // Re-seed the form each time the modal opens (or the target changes).
  useEffect(() => {
    if (!open) return;
    setToUserId(instance.current_assignee_user_id ?? '');
    setReason('');
  }, [open, instance.current_assignee_user_id]);

  // Same source the RouteEditor uses for its user picker - active users
  // only, shared ['users-search'] cache.
  const canListUsers = useHasPermission('users.list');
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserResult[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    enabled: open && canListUsers,
  });

  const reassignMut = useMutation({
    mutationFn: () =>
      reassignInstance(instance.id, {
        to_user_id: toUserId,
        reason: reason.trim() || null,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: approvalRoutesKeys.instance(instance.id),
      });
      void qc.invalidateQueries({ queryKey: ['approval-routes', 'instances'] });
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_reassigned', {
          defaultValue: 'Step reassigned',
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

  const currentName = useMemo(() => {
    const id = instance.current_assignee_user_id;
    if (!id) return null;
    const u = users.find((x) => x.id === id);
    return u?.full_name || u?.email || id;
  }, [instance.current_assignee_user_id, users]);

  const canSubmit = Boolean(toUserId) && !reassignMut.isPending;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={reassignMut.isPending}
      size="md"
      title={t('approvalRoutes.reassign_title', {
        defaultValue: 'Reassign current step',
      })}
      subtitle={t('approvalRoutes.reassign_subtitle', {
        defaultValue:
          'Pin a different decider for the live step only. The route template is left unchanged.',
      })}
      footer={
        <>
          <Button
            variant="ghost"
            size="md"
            onClick={onClose}
            disabled={reassignMut.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={() => reassignMut.mutate()}
            loading={reassignMut.isPending}
            disabled={!canSubmit}
          >
            {t('approvalRoutes.reassign_confirm', { defaultValue: 'Reassign' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('approvalRoutes.reassign_section', {
          defaultValue: 'New assignee',
        })}
        columns={1}
      >
        {currentName && (
          <p className="text-xs text-content-tertiary">
            {t('approvalRoutes.reassign_current', {
              defaultValue: 'Currently assigned to {{name}}.',
              name: currentName,
            })}
          </p>
        )}
        <div>
          <label
            htmlFor="reassign-user"
            className="block text-xs font-medium text-content-secondary mb-1"
          >
            {t('approvalRoutes.reassign_user', { defaultValue: 'Assign to' })}
            <span className="text-semantic-error ml-0.5">*</span>
          </label>
          <select
            id="reassign-user"
            value={toUserId}
            onChange={(e) => setToUserId(e.target.value)}
            className="h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer"
            data-testid="reassign-user-select"
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
        <div>
          <label
            htmlFor="reassign-reason"
            className="block text-xs font-medium text-content-secondary mb-1"
          >
            {t('approvalRoutes.reassign_reason', {
              defaultValue: 'Reason (optional)',
            })}
          </label>
          <textarea
            id="reassign-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            maxLength={500}
            placeholder={t('approvalRoutes.reassign_reason_placeholder', {
              defaultValue: 'e.g. Primary approver is on leave this week.',
            })}
            className="w-full rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
          />
        </div>
      </WideModalSection>
    </WideModal>
  );
}

export default ReassignDialog;
