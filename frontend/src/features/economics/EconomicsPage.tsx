// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The economics of a project, mounted at /projects/:projectId/economics.
//
// Three tabs follow the order the work is done in: the cost frame (what the
// project may cost, set against the estimate and the commitments), the business
// case (what it earns and whether it pays), and the financing (who pays and
// when). The plan is proposed as a whole and approved at the governance gate,
// or by hand on a project without gates. The URL remembers the tab (?tab=).

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { Banknote, Calculator, Landmark, Scale, ShieldCheck } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate } from '@/shared/lib/formatters';

import { runLifecycle, startPlan, type Approval, type Lifecycle, type PlanView, type PlanStatus } from './api';
import { ExportButtons } from './ExportButtons';
import { BusinessCasePanel } from './BusinessCasePanel';
import { CostFramePanel } from './CostFramePanel';
import { FindingList, Field, inputClass } from './EconomicsBits';
import { FinancingPanel } from './FinancingPanel';
import { RegistersPanel } from './RegistersPanel';
import { useBusinessCase, useCostFrame, useEconomicsAction, useEconomicsPlan, useFinancing, useRegisters } from './hooks';
import { BLOCK, PLAN_STATUS } from './labels';

type Tab = 'frame' | 'case' | 'financing' | 'records';
const TABS: Tab[] = ['frame', 'case', 'financing', 'records'];

const STATUS_VARIANT: Record<PlanStatus, 'neutral' | 'blue' | 'success' | 'warning'> = {
  draft: 'neutral',
  proposed: 'blue',
  approved: 'success',
  reopened: 'warning',
};

function LifecycleBar({ projectId, plan }: { projectId: string; plan: PlanView }) {
  const { t } = useTranslation();
  const [note, setNote] = useState('');
  const run = useEconomicsAction(projectId, ({ action, body }: { action: Lifecycle; body?: Record<string, unknown> }) =>
    runLifecycle(projectId, action, body),
  );
  const blocks = plan.blocks ?? {};
  const why = (key: string) => {
    const code = blocks[key];
    if (!code) return undefined;
    return BLOCK[code] ? t(BLOCK[code][0], { defaultValue: BLOCK[code][1] }) : code.replace(/_/g, ' ');
  };
  const open = (key: string) => !blocks[key] && !!plan.can.manage;
  const needsNote = open('propose') || open('reopen');

  const button = (key: string, action: Lifecycle, label: string, body?: Record<string, unknown>, variant: 'primary' | 'secondary' = 'secondary') => (
    <Button size="sm" variant={variant} disabled={!open(key)} title={why(key)} onClick={() => run({ action, body })}>
      {label}
    </Button>
  );

  return (
    <div className="flex flex-wrap items-end gap-3" data-testid="economics-lifecycle">
      {needsNote && (
        <Field label={t('economics.lifecycle.note', { defaultValue: 'Rationale or reason' })}>
          <input className={`${inputClass} w-72`} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      )}
      {button('propose', 'propose', t('economics.lifecycle.propose', { defaultValue: 'Propose' }), { rationale: note }, 'primary')}
      {button('withdraw', 'withdraw', t('economics.lifecycle.withdraw', { defaultValue: 'Withdraw the proposal' }))}
      {!plan.gates_in_use && button('approve', 'approve', t('economics.lifecycle.approve', { defaultValue: 'Approve' }))}
      {button('reopen', 'reopen', t('economics.lifecycle.reopen', { defaultValue: 'Reopen for a change' }), { reason: note })}
      {button('close_reopening', 'reopen/close', t('economics.lifecycle.close_reopening', { defaultValue: 'Close the reopening' }))}
    </div>
  );
}

/** Who proposed the plan and who approved it, when, and by which path: the gate decision or a manager by hand. */
function ApprovalSummary({ approval }: { approval: Approval }) {
  const { t } = useTranslation();
  const day = (iso: string | null) => (iso ? fmtDate(iso) : '');
  const approved = approval.status === 'approved' && !!approval.approved_at;
  const unknown = t('economics.approval.unknown_person', { defaultValue: 'an unknown person' });
  return (
    <div className="space-y-0.5 rounded-lg border border-border p-3 text-sm" data-testid="economics-approval">
      <div className="font-medium text-content-primary">
        {t('economics.approval.title', { defaultValue: 'Approval, version {{number}}', number: approval.number })}
      </div>
      <div className="text-content-secondary">
        {t('economics.approval.proposed', {
          defaultValue: 'Proposed by {{name}} on {{date}}',
          name: approval.proposed_by_name || unknown,
          date: day(approval.proposed_at),
        })}
      </div>
      <div className={approved ? 'text-semantic-success' : 'text-content-secondary'}>
        {approved
          ? approval.approval_source === 'gate'
            ? t('economics.approval.approved_gate', {
                defaultValue: 'Approved by {{name}} on {{date}} through the gate decision',
                name: approval.approved_by_name || unknown,
                date: day(approval.approved_at),
              })
            : t('economics.approval.approved_hand', {
                defaultValue: 'Approved by {{name}} on {{date}} by hand',
                name: approval.approved_by_name || unknown,
                date: day(approval.approved_at),
              })
          : t('economics.approval.pending', { defaultValue: 'Waiting for the decision' })}
      </div>
      {approval.rationale && (
        <div className="text-xs text-content-secondary">
          {t('economics.approval.rationale', { defaultValue: 'Rationale: {{text}}', text: approval.rationale })}
        </div>
      )}
    </div>
  );
}

export function EconomicsPage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab') as Tab | null;
  const tab: Tab = requested && TABS.includes(requested) ? requested : 'frame';
  const openTab = (next: Tab) => {
    const p = new URLSearchParams(params);
    if (next === 'frame') p.delete('tab');
    else p.set('tab', next);
    setParams(p, { replace: false });
  };

  const planQ = useEconomicsPlan(projectId);
  const exists = !!planQ.data?.exists;
  const frameQ = useCostFrame(projectId, exists && tab === 'frame');
  const caseQ = useBusinessCase(projectId, exists && tab === 'case');
  const financingQ = useFinancing(projectId, exists && tab === 'financing');
  const registersQ = useRegisters(projectId, exists && tab === 'records');
  const start = useEconomicsAction(projectId, () => startPlan(projectId));

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: t('economics.ui.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('economics.ui.title', { defaultValue: 'Economics' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{t('economics.ui.title', { defaultValue: 'Economics' })}</h1>
        <p className="text-sm text-content-secondary">
          {t('economics.ui.subtitle', {
            defaultValue: 'What the project may cost, whether it pays, and who finances it.',
          })}
        </p>
      </div>
      <CollapsibleSection
        storageKey="economics.how"
        icon={<Calculator className="h-4 w-4" />}
        title={t('economics.ui.how_title', { defaultValue: 'How the economics work' })}
        subtitle={t('economics.ui.how_subtitle', { defaultValue: 'Cost frame, business case, financing, approval' })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{t('economics.ui.how_step_1', { defaultValue: 'Set the cost frame by classification code. It is compared with the estimate of the bill and with what is already committed.' })}</li>
          <li>{t('economics.ui.how_step_2', { defaultValue: 'State the business case: revenue or benefit, operating cost and residual value over a horizon. The investment is the cost frame.' })}</li>
          <li>{t('economics.ui.how_step_3', { defaultValue: 'List the sources of finance and their tranches. Together they must cover the investment.' })}</li>
          <li>{t('economics.ui.how_step_4', { defaultValue: 'Propose the plan. It is approved at the governance gate of the frame document that carries it.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (planQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <SkeletonTable rows={6} columns={5} />
      </div>
    );
  }
  if (planQ.isError || !planQ.data) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <ErrorState
          title={t('economics.ui.load_failed', { defaultValue: 'The economics could not be loaded' })}
          hint={getErrorMessage(planQ.error)}
          onRetry={() => planQ.refetch()}
        />
      </div>
    );
  }
  const plan = planQ.data;
  if (!plan.exists) {
    return (
      <div className="space-y-5 animate-fade-in" data-testid="economics-page">
        {header}
        <EmptyState
          icon={<Banknote size={28} />}
          title={t('economics.ui.empty_title', { defaultValue: 'No economics plan yet' })}
          description={t('economics.ui.empty_body', {
            defaultValue: 'Start the plan to set the cost frame, the business case and the financing of this project.',
          })}
          action={
            plan.can.manage ? (
              <Button size="sm" onClick={() => start(undefined)}>
                {t('economics.ui.start', { defaultValue: 'Start the plan' })}
              </Button>
            ) : undefined
          }
        />
      </div>
    );
  }

  const editable = !!plan.can.edit;
  const status = plan.status ?? 'draft';
  const readiness = plan.readiness;
  const loading = <SkeletonTable rows={6} columns={5} />;
  const failed = (error: unknown, retry: () => void) => (
    <ErrorState
      title={t('economics.ui.section_failed', { defaultValue: 'This part of the plan could not be loaded' })}
      hint={getErrorMessage(error)}
      onRetry={retry}
    />
  );

  let body: ReactNode;
  if (tab === 'case') {
    body = caseQ.isError ? failed(caseQ.error, () => caseQ.refetch()) : !caseQ.data ? loading : (
      <BusinessCasePanel projectId={projectId} data={caseQ.data} editable={editable} />
    );
  } else if (tab === 'records') {
    body = registersQ.isError ? failed(registersQ.error, () => registersQ.refetch()) : !registersQ.data ? loading : (
      <RegistersPanel projectId={projectId} data={registersQ.data} canEdit={!!plan.can.records} currency={plan.currency ?? ''} />
    );
  } else if (tab === 'financing') {
    body = financingQ.isError ? failed(financingQ.error, () => financingQ.refetch()) : !financingQ.data ? loading : (
      <FinancingPanel projectId={projectId} data={financingQ.data} editable={editable} />
    );
  } else {
    body = frameQ.isError ? failed(frameQ.error, () => frameQ.refetch()) : !frameQ.data ? loading : (
      <CostFramePanel projectId={projectId} frame={frameQ.data} markupAllowance={plan.markup_allowance ?? '0'} editable={editable} />
    );
  }

  return (
    <div className="space-y-5 animate-fade-in" data-testid="economics-page">
      {header}
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={STATUS_VARIANT[status]}>{t(PLAN_STATUS[status][0], { defaultValue: PLAN_STATUS[status][1] })}</Badge>
        <span className="text-xs text-content-secondary">
          {plan.currency} {plan.classification_standard ? `- ${plan.classification_standard.toUpperCase()}` : ''}
        </span>
      </div>
      {plan.can.manage && <LifecycleBar projectId={projectId} plan={plan} />}
      {plan.approvals && plan.approvals[0] && <ApprovalSummary approval={plan.approvals[0]} />}
      {readiness && (readiness.errors.length > 0 || readiness.warnings.length > 0) && (
        <FindingList findings={[...readiness.errors, ...readiness.warnings]} />
      )}
      <TabBar
        ariaLabel={t('economics.ui.tabs', { defaultValue: 'Economics sections' })}
        activeId={tab}
        onChange={openTab}
        tabs={[
          { id: 'frame', label: t('economics.ui.tab_frame', { defaultValue: 'Cost frame' }), icon: <Scale className="h-4 w-4" /> },
          { id: 'case', label: t('economics.ui.tab_case', { defaultValue: 'Business case' }), icon: <Calculator className="h-4 w-4" /> },
          { id: 'financing', label: t('economics.ui.tab_financing', { defaultValue: 'Financing' }), icon: <Landmark className="h-4 w-4" /> },
          { id: 'records', label: t('economics.ui.tab_records', { defaultValue: 'Securities and processes' }), icon: <ShieldCheck className="h-4 w-4" /> },
        ]}
      />
      {tab !== 'records' && (
        <div className="flex justify-end">
          <ExportButtons projectId={projectId} what={tab === 'case' ? 'case' : tab === 'financing' ? 'financing' : 'frame'} />
        </div>
      )}
      {body}
    </div>
  );
}
