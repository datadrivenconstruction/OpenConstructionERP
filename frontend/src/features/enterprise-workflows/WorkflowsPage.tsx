// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  GitBranch,
  Clock,
  CheckCircle2,
  XCircle,
  Plus,
  Trash2,
  ToggleLeft,
  ToggleRight,
  ClipboardCheck,
  Send,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { getIntlLocale } from '@/shared/lib/formatters';
import { Badge, CollapsibleSection, EmptyState, StatCard, TabBar, tabIds } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchWorkflows,
  createWorkflow,
  updateWorkflow,
  deleteWorkflow,
  fetchApprovalRequests,
  approveRequest,
  rejectRequest,
  OFFERED_ACTION_TYPES,
  WORKFLOW_ACTION_TYPES,
  WORKFLOW_STEP_ROLES,
  fetchPendingApprovalCount,
  type Workflow,
  type WorkflowActionType,
  type WorkflowStep,
  type CreateWorkflowBody,
  type ApprovalRequest,
  type ApprovalStatus,
} from './api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type TabId = 'workflows' | 'requests';

const TAB_IDS = tabIds('ew');

const STATUS_BADGE: Record<ApprovalStatus, { variant: BadgeVariant; dot: boolean }> = {
  pending: { variant: 'warning', dot: true },
  approved: { variant: 'success', dot: true },
  rejected: { variant: 'error', dot: true },
  cancelled: { variant: 'neutral', dot: false },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(iso: string, t: (k: string, o?: Record<string, unknown>) => string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return t('common.just_now', { defaultValue: 'just now' });
  if (diff < 3_600_000) return t('common.minutes_ago', { defaultValue: '{{count}}m ago', count: Math.floor(diff / 60_000) });
  if (diff < 86_400_000) return t('common.hours_ago', { defaultValue: '{{count}}h ago', count: Math.floor(diff / 3_600_000) });
  return new Date(iso).toLocaleDateString(getIntlLocale(), {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

type TFn = (k: string, o?: Record<string, unknown>) => string;

function roleLabel(role: string, t: TFn): string {
  return t(`users.roles.${role}`, { defaultValue: role.charAt(0).toUpperCase() + role.slice(1) });
}

function actionLabel(action: WorkflowActionType, t: TFn): string {
  switch (action) {
    case 'approve':
      return t('enterprise_workflows.approve', { defaultValue: 'Approve' });
    case 'review':
      return t('enterprise_workflows.action_review', { defaultValue: 'Review' });
    case 'sign_off':
      return t('enterprise_workflows.action_sign_off', { defaultValue: 'Sign-off' });
    case 'notify':
      return t('enterprise_workflows.action_notify', { defaultValue: 'Notify' });
  }
}

/** "1. Manager · Approve" for a stored step; a step without a role is open to anyone. */
function describeStep(step: WorkflowStep, index: number, t: TFn): string {
  const who = step.role
    ? roleLabel(step.role, t)
    : t('enterprise_workflows.any_role', { defaultValue: 'Any role' });
  const known = (WORKFLOW_ACTION_TYPES as readonly string[]).includes(step.action_type ?? '');
  const action = actionLabel(known ? (step.action_type as WorkflowActionType) : 'approve', t);
  return `${index + 1}. ${who} · ${action}`;
}

interface StepDraft {
  role: string;
  action_type: WorkflowActionType;
}

const EMPTY_STEP: StepDraft = { role: '', action_type: 'approve' };

// ---------------------------------------------------------------------------
// Create Workflow Dialog
// ---------------------------------------------------------------------------

function CreateWorkflowDialog({
  open,
  onClose,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (body: CreateWorkflowBody) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [entityType, setEntityType] = useState('');
  const [steps, setSteps] = useState<StepDraft[]>([EMPTY_STEP]);

  const updateStep = useCallback((index: number, patch: Partial<StepDraft>) => {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }, []);

  const handleSubmit = useCallback(() => {
    if (!name.trim() || !entityType.trim()) return;
    onSubmit({
      name: name.trim(),
      description: description.trim() || null,
      entity_type: entityType.trim(),
      // The keys the approval engine reads. A step with no role leaves the key
      // out, which the engine treats as open to anyone.
      steps: steps.map((s) =>
        s.role ? { role: s.role, action_type: s.action_type } : { action_type: s.action_type },
      ),
      is_active: true,
    });
    setName('');
    setDescription('');
    setEntityType('');
    setSteps([EMPTY_STEP]);
  }, [name, description, entityType, steps, onSubmit]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="mx-4 w-full max-w-md rounded-xl border border-border-light bg-surface-primary p-6 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('enterprise_workflows.create_workflow', { defaultValue: 'Create Workflow' })}
          </h2>
          <button onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })}>
            <X className="h-5 w-5 text-content-tertiary hover:text-content-secondary" aria-hidden />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label htmlFor="ew-create-name" className="mb-1 block text-xs font-medium text-content-secondary">
              {t('enterprise_workflows.workflow_name', { defaultValue: 'Workflow Name' })}
            </label>
            <input
              id="ew-create-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('enterprise_workflows.name_placeholder', {
                defaultValue: 'e.g. Change Order Approval',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
                text-content-primary placeholder:text-content-tertiary
                focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>

          <div>
            <label htmlFor="ew-create-entity" className="mb-1 block text-xs font-medium text-content-secondary">
              {t('enterprise_workflows.entity_type', { defaultValue: 'Entity Type' })}
            </label>
            <input
              id="ew-create-entity"
              type="text"
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
              placeholder={t('enterprise_workflows.entity_type_placeholder', {
                defaultValue: 'e.g. change_order, variation, invoice',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
                text-content-primary placeholder:text-content-tertiary
                focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">
              {t('enterprise_workflows.description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder={t('enterprise_workflows.description_placeholder', {
                defaultValue: 'Optional description of this workflow',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
                text-content-primary placeholder:text-content-tertiary resize-none
                focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>

          <fieldset>
            <legend className="mb-1 block text-xs font-medium text-content-secondary">
              {t('enterprise_workflows.steps_label', { defaultValue: 'Approval steps' })}
            </legend>
            <ol className="space-y-2">
              {steps.map((step, i) => {
                const stepName = t('enterprise_workflows.step', { defaultValue: 'Step {{n}}', n: i + 1 });
                return (
                  <li key={i} className="flex items-center gap-2">
                    <span className="w-14 shrink-0 text-xs text-content-tertiary">{stepName}</span>
                    <select
                      value={step.role}
                      onChange={(e) => updateStep(i, { role: e.target.value })}
                      aria-label={`${stepName} ${t('enterprise_workflows.step_role', { defaultValue: 'Required role' })}`}
                      className="min-w-0 flex-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm
                        text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
                    >
                      <option value="">{t('enterprise_workflows.any_role', { defaultValue: 'Any role' })}</option>
                      {WORKFLOW_STEP_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {roleLabel(r, t)}
                        </option>
                      ))}
                    </select>
                    <select
                      value={step.action_type}
                      onChange={(e) => updateStep(i, { action_type: e.target.value as WorkflowActionType })}
                      aria-label={`${stepName} ${t('enterprise_workflows.step_action', { defaultValue: 'Action' })}`}
                      className="min-w-0 flex-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm
                        text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
                    >
                      {OFFERED_ACTION_TYPES.map((a) => (
                        <option key={a} value={a}>
                          {actionLabel(a, t)}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => setSteps((prev) => prev.filter((_, j) => j !== i))}
                      disabled={steps.length <= 1}
                      aria-label={`${t('common.remove', { defaultValue: 'Remove' })} ${stepName}`}
                      className="shrink-0 rounded-md p-1.5 text-content-tertiary hover:bg-semantic-error-bg
                        hover:text-semantic-error disabled:opacity-30"
                    >
                      <X className="h-4 w-4" aria-hidden />
                    </button>
                  </li>
                );
              })}
            </ol>
            <button
              type="button"
              onClick={() => setSteps((prev) => [...prev, EMPTY_STEP])}
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-oe-blue-text hover:underline"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
              {t('enterprise_workflows.add_step', { defaultValue: 'Add step' })}
            </button>
          </fieldset>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-border-light px-4 py-2 text-sm font-medium text-content-secondary
              hover:bg-surface-secondary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            onClick={handleSubmit}
            disabled={!name.trim() || !entityType.trim() || isPending}
            className="rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white
              hover:bg-oe-blue/90 disabled:opacity-40"
          >
            {isPending
              ? t('common.saving', { defaultValue: 'Saving...' })
              : t('common.create', { defaultValue: 'Create' })}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workflow row
// ---------------------------------------------------------------------------

function WorkflowRow({
  workflow,
  onToggleActive,
  onDelete,
  isToggling,
}: {
  workflow: Workflow;
  onToggleActive: (wf: Workflow) => void;
  onDelete: (id: string) => void;
  isToggling: boolean;
}) {
  const { t } = useTranslation();
  const ActiveIcon = workflow.is_active ? ToggleRight : ToggleLeft;

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary px-4 py-3
      transition-colors hover:bg-surface-secondary">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-oe-blue/10">
        <GitBranch className="h-4 w-4 text-oe-blue-text" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-content-primary">
            {workflow.name}
          </span>
          <Badge variant={workflow.is_active ? 'success' : 'neutral'} size="sm" dot>
            {workflow.is_active
              ? t('enterprise_workflows.active', { defaultValue: 'Active' })
              : t('enterprise_workflows.inactive', { defaultValue: 'Inactive' })}
          </Badge>
        </div>
        <div className="mt-0.5 flex items-center gap-3 text-xs text-content-tertiary">
          <span>{workflow.entity_type}</span>
          {workflow.description && (
            <>
              <span aria-hidden>·</span>
              <span className="truncate">{workflow.description}</span>
            </>
          )}
          <span aria-hidden>·</span>
          <span>
            {t('enterprise_workflows.steps_count', {
              defaultValue: '{{count}} step(s)',
              count: workflow.steps.length,
            })}
          </span>
        </div>
        {workflow.steps.length > 0 && (
          <ol className="mt-1 flex flex-wrap gap-1.5 text-2xs text-content-secondary">
            {workflow.steps.map((step, i) => (
              <li key={i} className="rounded bg-surface-secondary px-1.5 py-0.5">
                {describeStep(step, i, t)}
              </li>
            ))}
          </ol>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          onClick={() => onToggleActive(workflow)}
          disabled={isToggling}
          className="rounded-md p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary
            disabled:opacity-40"
          title={workflow.is_active
            ? t('enterprise_workflows.deactivate', { defaultValue: 'Deactivate' })
            : t('enterprise_workflows.activate', { defaultValue: 'Activate' })}
          aria-label={workflow.is_active
            ? t('enterprise_workflows.deactivate', { defaultValue: 'Deactivate' })
            : t('enterprise_workflows.activate', { defaultValue: 'Activate' })}
        >
          <ActiveIcon className="h-4 w-4" aria-hidden />
        </button>
        <button
          onClick={() => onDelete(workflow.id)}
          className="rounded-md p-1.5 text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error"
          title={t('common.delete', { defaultValue: 'Delete' })}
          aria-label={t('common.delete', { defaultValue: 'Delete' })}
        >
          <Trash2 className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <div className="shrink-0 text-xs text-content-tertiary">
        {relativeTime(workflow.updated_at, t)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Approval request row
// ---------------------------------------------------------------------------

function ApprovalRequestRow({
  request,
  onApprove,
  onReject,
  isActing,
}: {
  request: ApprovalRequest;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  isActing: boolean;
}) {
  const { t } = useTranslation();
  const badge = STATUS_BADGE[request.status] ?? STATUS_BADGE.cancelled;

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary px-4 py-3
      transition-colors hover:bg-surface-secondary">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-secondary">
        <ClipboardCheck className="h-4 w-4 text-content-tertiary" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-content-primary">
            {request.entity_type}
          </span>
          <span className="font-mono text-xs text-content-tertiary">
            {request.entity_id.slice(0, 8)}
          </span>
          <Badge variant={badge.variant} size="sm" dot={badge.dot}>
            {t(`enterprise_workflows.status_${request.status}`, {
              defaultValue: request.status.charAt(0).toUpperCase() + request.status.slice(1),
            })}
          </Badge>
        </div>
        <div className="mt-0.5 flex items-center gap-3 text-xs text-content-tertiary">
          <span>
            {t('enterprise_workflows.step', { defaultValue: 'Step {{n}}', n: request.current_step })}
          </span>
          {request.decision_notes && (
            <>
              <span aria-hidden>·</span>
              <span className="truncate">{request.decision_notes}</span>
            </>
          )}
        </div>
      </div>

      {request.status === 'pending' && (
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            onClick={() => onApprove(request.id)}
            disabled={isActing}
            className="inline-flex items-center gap-1 rounded-lg bg-semantic-success/10 px-3 py-1.5 text-xs font-medium
              text-semantic-success hover:bg-semantic-success/20 disabled:opacity-40"
            aria-label={t('enterprise_workflows.approve', { defaultValue: 'Approve' })}
          >
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
            {t('enterprise_workflows.approve', { defaultValue: 'Approve' })}
          </button>
          <button
            onClick={() => onReject(request.id)}
            disabled={isActing}
            className="inline-flex items-center gap-1 rounded-lg bg-semantic-error-bg px-3 py-1.5 text-xs font-medium
              text-semantic-error hover:bg-semantic-error/20 disabled:opacity-40"
            aria-label={t('enterprise_workflows.reject', { defaultValue: 'Reject' })}
          >
            <XCircle className="h-3.5 w-3.5" aria-hidden />
            {t('enterprise_workflows.reject', { defaultValue: 'Reject' })}
          </button>
        </div>
      )}

      {request.status !== 'pending' && request.decided_at && (
        <div className="shrink-0 text-xs text-content-tertiary">
          {relativeTime(request.decided_at, t)}
        </div>
      )}

      <div className="shrink-0 text-xs text-content-tertiary">
        {relativeTime(request.created_at, t)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Explainer
// ---------------------------------------------------------------------------

function WorkflowsExplainer() {
  const { t } = useTranslation();

  const steps = [
    {
      num: 1,
      title: t('enterprise_workflows.flow_step_1', { defaultValue: 'Define a workflow' }),
      desc: t('enterprise_workflows.flow_step_1_desc', {
        defaultValue:
          'Name the workflow, choose the entity type it governs (change orders, variations, invoices, etc.) and add approval steps with the required approvers.',
      }),
    },
    {
      num: 2,
      title: t('enterprise_workflows.flow_step_2', { defaultValue: 'Activate and assign' }),
      desc: t('enterprise_workflows.flow_step_2_desc', {
        defaultValue:
          'Toggle the workflow to active so it starts receiving requests. Inactive workflows are paused without being deleted.',
      }),
    },
    {
      num: 3,
      title: t('enterprise_workflows.flow_step_3', { defaultValue: 'Review requests' }),
      desc: t('enterprise_workflows.flow_step_3_desc', {
        defaultValue:
          'When a record triggers an approval, it appears in the Approval Requests tab. Approve or reject each step, and the request advances or stops.',
      }),
    },
    {
      num: 4,
      title: t('enterprise_workflows.flow_step_4', { defaultValue: 'Track outcomes' }),
      desc: t('enterprise_workflows.flow_step_4_desc', {
        defaultValue:
          'Filter requests by status to see what is pending, approved or rejected. The audit trail records who decided and when.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="enterprise_workflows.how"
      icon={<GitBranch size={15} className="text-oe-blue" />}
      title={t('enterprise_workflows.flow_title', { defaultValue: 'How enterprise workflows work' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('enterprise_workflows.flow_intro', {
          defaultValue:
            'Set up multi-step approval routes for any entity type, then track every request from submission through to a final decision.',
        })}
      </p>
      <ol className="mt-3 space-y-2">
        {steps.map((s) => (
          <li key={s.num} className="flex gap-3 text-xs">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[10px] font-bold text-oe-blue-text">
              {s.num}
            </span>
            <div>
              <span className="font-medium text-content-primary">{s.title}</span>
              <span className="text-content-tertiary"> - {s.desc}</span>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('enterprise_workflows.flow_related', { defaultValue: 'Related:' })}
        </span>{' '}
        <Link to="/variations" className="font-medium text-oe-blue-text hover:underline">
          {t('enterprise_workflows.mod_variations', { defaultValue: 'Variations' })}
        </Link>
        {' · '}
        <Link to="/contracts" className="font-medium text-oe-blue-text hover:underline">
          {t('enterprise_workflows.mod_contracts', { defaultValue: 'Contracts' })}
        </Link>
        {' · '}
        <Link to="/timeline" className="font-medium text-oe-blue-text hover:underline">
          {t('enterprise_workflows.mod_timeline', { defaultValue: 'Timeline' })}
        </Link>
      </div>
    </CollapsibleSection>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function WorkflowsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [activeTab, setActiveTab] = useState<TabId>('workflows');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [statusFilter, setStatusFilter] = useState<ApprovalStatus | ''>('');

  // ------- Queries (all hooks BEFORE any early return) ---------

  const workflowsQuery = useQuery({
    queryKey: ['enterprise-workflows'],
    queryFn: () => fetchWorkflows(),
    staleTime: 30_000,
  });

  const requestsQuery = useQuery({
    queryKey: ['enterprise-workflow-requests', statusFilter || undefined],
    queryFn: () =>
      fetchApprovalRequests(statusFilter ? { status: statusFilter as ApprovalStatus } : undefined),
    staleTime: 30_000,
  });

  const pendingCountQuery = useQuery({
    queryKey: ['enterprise-workflow-requests', 'pending-count'],
    queryFn: fetchPendingApprovalCount,
    staleTime: 30_000,
  });

  // ------- Derived data --------

  const workflows = workflowsQuery.data ?? [];
  const requests = requestsQuery.data ?? [];

  const stats = useMemo(() => {
    const totalWorkflows = workflows.length;
    const activeWorkflows = workflows.filter((w) => w.is_active).length;
    // From the envelope's total, not from the page the list below happens to
    // hold, which is filtered and capped at 50 rows.
    const pendingApprovals = pendingCountQuery.data ?? 0;
    return { totalWorkflows, activeWorkflows, pendingApprovals };
  }, [workflows, pendingCountQuery.data]);

  // ------- Mutations --------

  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['enterprise-workflows'] });
    qc.invalidateQueries({ queryKey: ['enterprise-workflow-requests'] });
  }, [qc]);

  const createMut = useMutation({
    mutationFn: (body: CreateWorkflowBody) => createWorkflow(body),
    onSuccess: () => {
      invalidateAll();
      setShowCreateDialog(false);
      addToast({
        type: 'success',
        title: t('enterprise_workflows.workflow_created', { defaultValue: 'Workflow created' }),
      });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('enterprise_workflows.create_error', {
          defaultValue: 'Failed to create workflow',
        }),
      });
    },
  });

  const toggleActiveMut = useMutation({
    mutationFn: (wf: Workflow) => updateWorkflow(wf.id, { is_active: !wf.is_active }),
    onSuccess: (_data, wf) => {
      invalidateAll();
      addToast({
        type: 'success',
        title: wf.is_active
          ? t('enterprise_workflows.workflow_deactivated', { defaultValue: 'Workflow deactivated' })
          : t('enterprise_workflows.workflow_activated', { defaultValue: 'Workflow activated' }),
      });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('enterprise_workflows.toggle_error', {
          defaultValue: 'Failed to update workflow status',
        }),
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteWorkflow(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('enterprise_workflows.workflow_deleted', { defaultValue: 'Workflow deleted' }),
      });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('enterprise_workflows.delete_error', {
          defaultValue: 'Failed to delete workflow',
        }),
      });
    },
  });

  const approveMut = useMutation({
    mutationFn: (id: string) => approveRequest(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('enterprise_workflows.request_approved', { defaultValue: 'Request approved' }),
      });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('enterprise_workflows.approve_error', {
          defaultValue: 'Failed to approve request',
        }),
      });
    },
  });

  const rejectMut = useMutation({
    mutationFn: (id: string) => rejectRequest(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('enterprise_workflows.request_rejected', { defaultValue: 'Request rejected' }),
      });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('enterprise_workflows.reject_error', {
          defaultValue: 'Failed to reject request',
        }),
      });
    },
  });

  // ------- Tabs config --------

  const tabs = useMemo(
    () => [
      {
        id: 'workflows' as TabId,
        label: t('enterprise_workflows.tab_workflows', { defaultValue: 'Workflows' }),
        icon: <GitBranch className="h-4 w-4" />,
        badge: workflows.length > 0 ? (
          <Badge variant="neutral" size="sm">{workflows.length}</Badge>
        ) : undefined,
      },
      {
        id: 'requests' as TabId,
        label: t('enterprise_workflows.tab_requests', { defaultValue: 'Approval Requests' }),
        icon: <ClipboardCheck className="h-4 w-4" />,
        badge: stats.pendingApprovals > 0 ? (
          <Badge variant="warning" size="sm">{stats.pendingApprovals}</Badge>
        ) : undefined,
      },
    ],
    [t, workflows.length, stats.pendingApprovals],
  );

  // ------- Loading / error states --------

  const isLoading = workflowsQuery.isLoading || requestsQuery.isLoading;
  const hasError = workflowsQuery.error || requestsQuery.error;

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-4 py-6">
      <PageHeader
        srTitle={t('enterprise_workflows.title', { defaultValue: 'Enterprise Workflows' })}
        subtitle={t('enterprise_workflows.subtitle', {
          defaultValue: 'Configure approval workflows and manage pending requests across your projects.',
        })}
        actions={
          <button
            onClick={() => setShowCreateDialog(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-2 text-sm font-medium
              text-white hover:bg-oe-blue/90"
          >
            <Plus className="h-4 w-4" aria-hidden />
            {t('enterprise_workflows.new_workflow', { defaultValue: 'New Workflow' })}
          </button>
        }
      />

      {/* Statistics cards */}
      {!isLoading && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard
            label={t('enterprise_workflows.stat_total', { defaultValue: 'Total Workflows' })}
            value={stats.totalWorkflows}
            icon={GitBranch}
            tone="blue"
          />
          <StatCard
            label={t('enterprise_workflows.stat_active', { defaultValue: 'Active' })}
            value={stats.activeWorkflows}
            icon={CheckCircle2}
            tone="success"
            tintValue
          />
          <StatCard
            label={t('enterprise_workflows.stat_pending', { defaultValue: 'Pending Approvals' })}
            value={stats.pendingApprovals}
            icon={Clock}
            tone={stats.pendingApprovals > 0 ? 'warning' : 'default'}
            tintValue={stats.pendingApprovals > 0}
          />
        </div>
      )}

      <WorkflowsExplainer />

      {/* Tab strip */}
      <TabBar<TabId>
        tabs={tabs}
        activeId={activeTab}
        onChange={setActiveTab}
        ariaLabel={t('enterprise_workflows.tabs_label', { defaultValue: 'Workflow sections' })}
        idPrefix="ew"
      />

      {/* Loading */}
      {isLoading && (
        <div className="py-16 text-center text-content-tertiary">
          <Clock className="mx-auto mb-2 h-6 w-6 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}

      {/* Error */}
      {hasError && !isLoading && (
        <div className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-4 text-sm text-semantic-error">
          {t('enterprise_workflows.load_error', { defaultValue: 'Could not load workflow data.' })}
        </div>
      )}

      {/* ----- Workflows tab ----- */}
      {!isLoading && !hasError && activeTab === 'workflows' && (
        <div
          role="tabpanel"
          id={TAB_IDS.panelId('workflows')}
          aria-labelledby={TAB_IDS.tabId('workflows')}
        >
          {workflows.length === 0 ? (
            <EmptyState
              icon={<GitBranch className="h-12 w-12" />}
              title={t('enterprise_workflows.no_workflows', { defaultValue: 'No workflows yet' })}
              description={t('enterprise_workflows.no_workflows_desc', {
                defaultValue: 'Create your first workflow to set up approval processes.',
              })}
              action={{
                label: t('enterprise_workflows.new_workflow', { defaultValue: 'New Workflow' }),
                onClick: () => setShowCreateDialog(true),
              }}
            />
          ) : (
            <div className="space-y-2">
              {workflows.map((wf) => (
                <WorkflowRow
                  key={wf.id}
                  workflow={wf}
                  onToggleActive={(w) => toggleActiveMut.mutate(w)}
                  onDelete={(id) => deleteMut.mutate(id)}
                  isToggling={toggleActiveMut.isPending}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ----- Approval Requests tab ----- */}
      {!isLoading && !hasError && activeTab === 'requests' && (
        <div
          role="tabpanel"
          id={TAB_IDS.panelId('requests')}
          aria-labelledby={TAB_IDS.tabId('requests')}
        >
          {/* Status filter for requests */}
          <div className="mb-4 flex items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ApprovalStatus | '')}
              className="rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
                text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
            >
              <option value="">
                {t('enterprise_workflows.all_statuses', { defaultValue: 'All statuses' })}
              </option>
              <option value="pending">
                {t('enterprise_workflows.status_pending', { defaultValue: 'Pending' })}
              </option>
              <option value="approved">
                {t('enterprise_workflows.status_approved', { defaultValue: 'Approved' })}
              </option>
              <option value="rejected">
                {t('enterprise_workflows.status_rejected', { defaultValue: 'Rejected' })}
              </option>
              <option value="cancelled">
                {t('enterprise_workflows.status_cancelled', { defaultValue: 'Cancelled' })}
              </option>
            </select>
            {statusFilter && (
              <button
                onClick={() => setStatusFilter('')}
                className="rounded-lg border border-border-light px-3 py-2 text-sm text-content-tertiary
                  hover:bg-surface-secondary"
              >
                {t('common.clear', { defaultValue: 'Clear' })}
              </button>
            )}
          </div>

          {requests.length === 0 ? (
            <EmptyState
              icon={<Send className="h-12 w-12" />}
              title={t('enterprise_workflows.no_requests', { defaultValue: 'No approval requests' })}
              description={t('enterprise_workflows.no_requests_desc', {
                defaultValue: 'Approval requests will appear here when submitted.',
              })}
            />
          ) : (
            <div className="space-y-2">
              {requests.map((req) => (
                <ApprovalRequestRow
                  key={req.id}
                  request={req}
                  onApprove={(id) => approveMut.mutate(id)}
                  onReject={(id) => rejectMut.mutate(id)}
                  isActing={approveMut.isPending || rejectMut.isPending}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Create workflow dialog */}
      <CreateWorkflowDialog
        open={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        onSubmit={(body) => createMut.mutate(body)}
        isPending={createMut.isPending}
      />
    </div>
  );
}
