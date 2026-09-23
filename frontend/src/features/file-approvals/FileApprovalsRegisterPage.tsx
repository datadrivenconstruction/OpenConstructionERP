// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// FileApprovalsRegisterPage — a project-wide register of every file
// submitted for approval, with a one-click "Export to Excel" action that
// produces the compliance artifact (backend: GET /v1/file-approvals/export/).
//
// The list is the same data the per-file ApprovalDrawer shows, rolled up to
// the project so the whole approval trail is auditable in one place. The
// export trigger mirrors the RFI log export (authenticated binary GET +
// client-side save + success/error toast).

import { Fragment, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowRight,
  ClipboardCheck,
  Download,
  FileCheck2,
  GitBranch,
  Loader2,
  Send,
  ShieldCheck,
  Stamp,
} from 'lucide-react';

import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  EmptyState,
  RecoveryCard,
  SkeletonTable,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import { downloadApprovalRegister } from './api';
import { buildFileApprovalsInsights } from './fileApprovalsInsights';
import { useApprovals } from './hooks';
import type { ApprovalWorkflow, WorkflowStatus } from './types';

const WORKFLOW_STATUSES: WorkflowStatus[] = [
  'in_review',
  'approved',
  'rejected',
  'withdrawn',
];

const STATUS_VARIANT: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  in_review: 'blue',
  approved: 'success',
  rejected: 'error',
  withdrawn: 'neutral',
};

/** First still-pending step = the actionable "ball in court", derived the
 *  same way the drawer highlights it. Empty for terminal workflows. */
function currentStepLabel(w: ApprovalWorkflow): string {
  const pending = [...w.steps]
    .sort((a, b) => a.sort_order - b.sort_order)
    .find((s) => s.decision === 'pending');
  if (!pending) return '';
  const who = pending.role_label || pending.approver_id.slice(0, 8);
  return `#${pending.sort_order + 1}: ${who}`;
}

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer: what the approvals register is and how it connects.
 *
 * The table shows a status column but never says that the workflow is an
 * ordered chain, that the first still-pending step is who the file is actually
 * waiting on, or that a rejection stops the chain rather than passing it along.
 * Those are what make the "waiting on which approver" chart mean anything.
 */
function HowApprovalsWork() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Send size={14} className="text-oe-blue" />,
      title: t('files.approvals.flow_1_title', { defaultValue: 'Submit a file' }),
      desc: t('files.approvals.flow_1_desc', {
        defaultValue:
          'Send a drawing, model, report or document for approval from wherever it lives, and it enters the register as in review.',
      }),
    },
    {
      icon: <GitBranch size={14} className="text-oe-blue" />,
      title: t('files.approvals.flow_2_title', { defaultValue: 'Steps in order' }),
      desc: t('files.approvals.flow_2_desc', {
        defaultValue:
          'The workflow carries an ordered list of approvers. The first step still pending is who the file is waiting on right now.',
      }),
    },
    {
      icon: <Stamp size={14} className="text-oe-blue" />,
      title: t('files.approvals.flow_3_title', { defaultValue: 'Each approver decides' }),
      desc: t('files.approvals.flow_3_desc', {
        defaultValue:
          'Approve, reject or delegate. A rejection stops the chain and sends the file back for revision rather than passing it on.',
      }),
    },
    {
      icon: <FileCheck2 size={14} className="text-oe-blue" />,
      title: t('files.approvals.flow_4_title', { defaultValue: 'Approved and recorded' }),
      desc: t('files.approvals.flow_4_desc', {
        defaultValue:
          'Once the last step approves, the decision and its date stay against the file as the audit trail for handover.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="files.approvals.how"
      icon={<ShieldCheck size={15} className="text-oe-blue" />}
      title={t('files.approvals.flow_title', {
        defaultValue: 'How file approvals fit together',
      })}
    >
      <p className="text-xs text-content-tertiary">
        {t('files.approvals.flow_intro', {
          defaultValue:
            'A record of who signed off which file and when. A file is submitted into a chain of approval steps, each approver takes a decision in turn, and the file is only approved once the last step is cleared.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('files.approvals.flow_connects', { defaultValue: 'Connects with:' })}
          </span>{' '}
          <ModLink to="/plan-room">
            {t('files.approvals.mod_planroom', { defaultValue: 'Plan Room' })}
          </ModLink>{' '}
          · <ModLink to="/files">{t('nav.documents', { defaultValue: 'Documents' })}</ModLink>{' '}
          ·{' '}
          <ModLink to="/closeout">
            {t('files.approvals.mod_closeout', { defaultValue: 'Handover' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

export function FileApprovalsRegisterPage() {
  return (
    <RequiresProject>
      <RegisterInner />
    </RequiresProject>
  );
}

function RegisterInner() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<{ id: string; name: string }[]>(),
    staleTime: 5 * 60_000,
  });
  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | ''>('');

  const {
    data: workflows = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useApprovals(projectId, statusFilter || undefined);

  const insights = useModuleInsights('file-approvals', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildFileApprovalsInsights(workflows, t),
    [workflows, t],
  );

  const exportMut = useMutation({
    mutationFn: () => downloadApprovalRegister(projectId),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('files.approvals.export_success', {
          defaultValue: 'Approvals register exported',
        }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('files.approvals.export_failed', {
          defaultValue: 'Failed to export approvals register',
        }),
        message: e.message,
      }),
  });

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(projectId && projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          {
            label: t('files.approvals.register_title', {
              defaultValue: 'Approvals register',
            }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('files.approvals.register_title', {
          defaultValue: 'Approvals register',
        })}
        subtitle={t('files.approvals.register_subtitle', {
          defaultValue:
            'Every file submitted for approval, with its current approver, status and decision trail.',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <Button
              variant="secondary"
              size="sm"
              icon={
                exportMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Download size={14} />
                )
              }
              onClick={() => exportMut.mutate()}
              disabled={exportMut.isPending || !projectId || workflows.length === 0}
              data-guide="file-approvals-export"
            >
              {t('files.approvals.export', { defaultValue: 'Export to Excel' })}
            </Button>
          </>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('files.approvals.insights.title', { defaultValue: 'Approval insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <HowApprovalsWork />

      <div className="flex items-center gap-2">
        <label className="text-xs text-content-secondary">
          {t('files.approvals.filter_status', { defaultValue: 'Status' })}
        </label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as WorkflowStatus | '')}
          className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer"
          aria-label={t('files.approvals.filter_status', { defaultValue: 'Status' })}
        >
          <option value="">
            {t('files.approvals.all_statuses', { defaultValue: 'All statuses' })}
          </option>
          {WORKFLOW_STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`files.approvals.status.${s}`, {
                defaultValue:
                  s.charAt(0).toUpperCase() + s.slice(1).replace('_', ' '),
              })}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <SkeletonTable rows={5} columns={5} />
      ) : isError ? (
        <RecoveryCard error={error as Error} onRetry={() => void refetch()} />
      ) : workflows.length === 0 ? (
        <EmptyState
          icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
          title={t('files.approvals.empty_register_title', {
            defaultValue: 'No approvals yet',
          })}
          description={t('files.approvals.empty_hint', {
            defaultValue:
              'Send a file for approval from the Plan Room or the Files register and it will appear here with its approval chain.',
          })}
        />
      ) : (
        <Card padding="none" className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[760px]">
              <thead>
                <tr className="border-b border-border-light bg-surface-secondary/40">
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                    {t('files.approvals.col_file', { defaultValue: 'File' })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[120px]">
                    {t('files.approvals.col_kind', { defaultValue: 'Type' })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[140px]">
                    {t('files.approvals.col_submitted', {
                      defaultValue: 'Submitted',
                    })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[120px]">
                    {t('files.approvals.col_status', { defaultValue: 'Status' })}
                  </th>
                  <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                    {t('files.approvals.col_current_step', {
                      defaultValue: 'Current step',
                    })}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {workflows.map((w) => {
                  const step = currentStepLabel(w);
                  return (
                    <tr
                      key={w.id}
                      className="hover:bg-surface-secondary/30 transition-colors"
                    >
                      <td className="px-3 py-2.5">
                        <span className="text-sm font-medium text-content-primary break-all">
                          {w.file_id}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-content-secondary">
                        {t(`files.approvals.kind_${w.file_kind}`, {
                          defaultValue:
                            String(w.file_kind).charAt(0).toUpperCase() +
                            String(w.file_kind).slice(1).replace(/_/g, ' '),
                        })}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-content-tertiary">
                        <DateDisplay value={w.submitted_at} />
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge
                          variant={STATUS_VARIANT[w.status] ?? 'neutral'}
                          size="sm"
                        >
                          {t(`files.approvals.status.${w.status}`, {
                            defaultValue:
                              w.status.charAt(0).toUpperCase() +
                              w.status.slice(1).replace('_', ' '),
                          })}
                        </Badge>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-content-secondary">
                        {step || (
                          <span className="text-content-tertiary">
                            {t('files.approvals.no_current_step', {
                              defaultValue: 'Complete',
                            })}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
