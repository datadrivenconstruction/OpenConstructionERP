// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ClashGroupActionDialog - turn one clash cluster into a single tracked
// work item (a punch item or a coordination task), with a link back to the
// run + cluster + member clashes.
//
// AI proposes, human confirms: the backend drafts a title, body, priority,
// assignee and a 0..1 confidence score from the cluster's geometry + triage
// state; this dialog shows that draft (with the confidence chip + the
// standard AI disclaimer), lets the coordinator edit any field and the
// target module, then POSTs the confirmation. Nothing is auto-applied.
//
// Idempotent: a cluster that already produced a work item shows the existing
// link and disables the confirm button instead of spawning a duplicate.

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';
import { AIDisclaimerBanner } from '@/shared/ui/AIDisclaimerBanner';
import { useToastStore } from '@/stores/useToastStore';

import {
  clashApi,
  type ClashActionTarget,
  type ClashGroupActionProposal,
} from './api';
import {
  canCreateAction,
  confidenceChipClass,
  confidenceLabel,
  summarizeProposal,
  targetNoun,
} from './clashGroupAction';

export interface ClashGroupActionDialogProps {
  projectId: string;
  runId: string;
  clusterId: number;
  open: boolean;
  onClose: () => void;
  /** Notified after a successful create so the parent can refresh / toast. */
  onCreated?: (actionId: string, target: ClashActionTarget) => void;
}

const PRIORITIES = ['low', 'medium', 'high', 'critical'] as const;

export function ClashGroupActionDialog({
  projectId,
  runId,
  clusterId,
  open,
  onClose,
  onCreated,
}: ClashGroupActionDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [target, setTarget] = useState<ClashActionTarget>('punchlist');
  // Coordinator overrides. `null` means "use the proposal value"; once the
  // user edits a field we hold their value so a proposal refetch never
  // clobbers their edit.
  const [title, setTitle] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [priority, setPriority] = useState<
    'low' | 'medium' | 'high' | 'critical' | null
  >(null);
  const [advanceStatus, setAdvanceStatus] = useState(true);

  const proposalQuery = useQuery<ClashGroupActionProposal>({
    queryKey: ['clash', projectId, runId, 'cluster-action', clusterId, target],
    queryFn: () => clashApi.clusterActionProposal(projectId, runId, clusterId, target),
    enabled: open && !!projectId && !!runId && Number.isFinite(clusterId),
  });
  const proposal = proposalQuery.data ?? null;

  // Reset the per-cluster edits whenever the dialog (re)opens or the target
  // changes - the new proposal supplies fresh defaults.
  useEffect(() => {
    if (!open) return;
    setTitle(null);
    setDescription(null);
    setPriority(null);
  }, [open, clusterId, target]);

  const createMut = useMutation({
    mutationFn: () =>
      clashApi.createClusterAction(projectId, runId, clusterId, {
        target,
        title: title ?? undefined,
        description: description ?? undefined,
        priority: priority ?? undefined,
        advance_status: advanceStatus,
      }),
    onSuccess: (res) => {
      if (res.created) {
        addToast({
          type: 'success',
          title: t('clash.groupAction.created', {
            defaultValue: 'Work item created from clash group',
          }),
          message: t('clash.groupAction.createdDetail', {
            defaultValue: '{{linked}} clashes linked, {{advanced}} moved to reviewed.',
            linked: res.results_linked,
            advanced: res.results_advanced,
          }),
        });
      } else {
        addToast({
          type: 'info',
          title: t('clash.groupAction.alreadyLinked', {
            defaultValue: 'This group already has a linked work item',
          }),
        });
      }
      // Results / clusters / proposal all change after a create.
      void queryClient.invalidateQueries({ queryKey: ['clash', projectId, runId] });
      onCreated?.(res.action_id, res.action_target);
      onClose();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const effTitle = title ?? proposal?.title ?? '';
  const effDescription = description ?? proposal?.description ?? '';
  const effPriority = priority ?? proposal?.priority ?? 'medium';
  const disabled =
    createMut.isPending || !canCreateAction(proposal) || effTitle.trim().length === 0;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={createMut.isPending}
      size="md"
      title={t('clash.groupAction.title', {
        defaultValue: 'Create work item from clash group',
      })}
      subtitle={
        proposal ? summarizeProposal(proposal) : undefined
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={createMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => createMut.mutate()}
            loading={createMut.isPending}
            disabled={disabled}
          >
            {t('clash.groupAction.confirm', {
              defaultValue: 'Create {{noun}}',
              noun: targetNoun(target),
            })}
          </Button>
        </>
      }
    >
      {proposalQuery.isLoading ? (
        <p className="text-sm text-content-secondary py-8 text-center">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      ) : proposalQuery.isError ? (
        <p className="text-sm text-semantic-error py-8 text-center">
          {(proposalQuery.error as Error)?.message ||
            t('clash.groupAction.loadError', {
              defaultValue: 'Could not load the group proposal.',
            })}
        </p>
      ) : !proposal ? null : (
        <>
          <AIDisclaimerBanner variant="compact" className="mb-4" />

          {/* AI confidence + already-linked notice */}
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <span
              className={clsx(
                'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium',
                confidenceChipClass(proposal.confidence),
              )}
              title={t('clash.groupAction.confidenceHint', {
                defaultValue: 'How well-formed this AI draft is. Always review before confirming.',
              })}
            >
              {t('clash.groupAction.confidence', {
                defaultValue: 'AI confidence {{pct}}',
                pct: confidenceLabel(proposal.confidence),
              })}
            </span>
            {proposal.already_linked && (
              <span className="inline-flex items-center rounded-full bg-surface-tertiary px-2.5 py-0.5 text-xs text-content-secondary">
                {t('clash.groupAction.linkedChip', {
                  defaultValue: 'Already linked to a {{noun}}',
                  noun: targetNoun(proposal.existing_action_target ?? target),
                })}
              </span>
            )}
          </div>

          <WideModalSection columns={2}>
            <WideModalField
              label={t('clash.groupAction.target', { defaultValue: 'Create as' })}
              span={1}
            >
              <select
                value={target}
                onChange={(e) => setTarget(e.target.value as ClashActionTarget)}
                disabled={createMut.isPending}
                className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
              >
                <option value="punchlist">
                  {t('clash.groupAction.targetPunch', { defaultValue: 'Punch item' })}
                </option>
                <option value="task">
                  {t('clash.groupAction.targetTask', { defaultValue: 'Task' })}
                </option>
              </select>
            </WideModalField>

            <WideModalField
              label={t('clash.groupAction.priority', { defaultValue: 'Priority' })}
              span={1}
            >
              <select
                value={effPriority}
                onChange={(e) =>
                  setPriority(e.target.value as 'low' | 'medium' | 'high' | 'critical')
                }
                disabled={createMut.isPending}
                className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
              >
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </WideModalField>

            <WideModalField
              label={t('clash.groupAction.titleField', { defaultValue: 'Title' })}
              required
              span={2}
            >
              <input
                type="text"
                value={effTitle}
                maxLength={255}
                onChange={(e) => setTitle(e.target.value)}
                disabled={createMut.isPending}
                className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm"
              />
            </WideModalField>

            <WideModalField
              label={t('clash.groupAction.description', { defaultValue: 'Description' })}
              span={2}
            >
              <textarea
                value={effDescription}
                rows={6}
                maxLength={5000}
                onChange={(e) => setDescription(e.target.value)}
                disabled={createMut.isPending}
                className="rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm font-mono"
              />
            </WideModalField>
          </WideModalSection>

          <label className="mt-1 flex items-center gap-2 text-sm text-content-secondary">
            <input
              type="checkbox"
              checked={advanceStatus}
              onChange={(e) => setAdvanceStatus(e.target.checked)}
              disabled={createMut.isPending}
            />
            {t('clash.groupAction.advance', {
              defaultValue: 'Move new clashes in this group to "reviewed"',
            })}
          </label>
        </>
      )}
    </WideModal>
  );
}
