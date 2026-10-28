// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Stakeholders, mounted at /projects/:projectId/stakeholders.
//
// The register is the home view. The analysis, the communication plan, the
// commitments and the project organisation sit behind tabs, and the URL
// remembers the tab and the open stakeholder (?tab=, ?stakeholder=), so a
// link reopens the same view. Notifications link to a section by path
// (/stakeholders/communication, /stakeholders/commitments).

import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useParams, useSearchParams } from 'react-router-dom';
import { CalendarClock, Compass, Grid3x3, Handshake, Network, Settings2, Users } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { getErrorMessage } from '@/shared/lib/api';

import { AnalysisGrid } from './AnalysisGrid';
import { ChecksPanel } from './ChecksPanel';
import { CommitmentsPanel } from './CommitmentsPanel';
import { ExportBar, FrameworkSettings } from './FrameworkSettings';
import { OrganisationPanel } from './OrganisationPanel';
import { PlanPanel } from './PlanPanel';
import { RegisterPanel } from './RegisterPanel';
import { StakeholderDetail } from './StakeholderDetail';
import { StakeholderDialog } from './StakeholderDialog';
import {
  useCommitments,
  useDue,
  useEvents,
  useInvalidateStakeholders,
  useLabelContext,
  usePeopleNames,
  usePlanItems,
  useReadiness,
  useRegister,
  useStakeholderSettings,
} from './hooks';
import type { Screen } from './screen';

type Tab = 'register' | 'analysis' | 'plan' | 'commitments' | 'organisation' | 'settings';

const TABS: Tab[] = ['register', 'analysis', 'plan', 'commitments', 'organisation', 'settings'];

/** The path sections the server links to, and the tab each one opens. */
const SECTION_TAB: Record<string, Tab> = {
  communication: 'plan',
  commitments: 'commitments',
  organisation: 'organisation',
};

export function StakeholdersPage() {
  const { t } = useTranslation();
  const { projectId = '', section = '' } = useParams<{ projectId: string; section: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const labels = useLabelContext();
  const personName = usePeopleNames(projectId);
  const invalidate = useInvalidateStakeholders(projectId);
  const [adding, setAdding] = useState(false);

  const settingsQ = useStakeholderSettings(projectId);
  const settings = settingsQ.data?.settings ?? null;
  const ready = !!settings;
  const registerQ = useRegister(projectId, ready);
  const readinessQ = useReadiness(projectId, ready);
  const planQ = usePlanItems(projectId, ready);
  const dueQ = useDue(projectId, ready);
  const eventsQ = useEvents(projectId, ready);
  const commitmentsQ = useCommitments(projectId, ready);

  const rawTab = params.get('tab') as Tab | null;
  const tab: Tab = rawTab && TABS.includes(rawTab) ? rawTab : (SECTION_TAB[section] ?? 'register');
  const stakeholderId = params.get('stakeholder');
  const method = params.get('method') ?? settings?.analysis_method ?? '';
  const go = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: false });
  };

  const screen = useMemo<Screen | null>(
    () => (settings ? { projectId, settings, labels, personName, onChanged: invalidate } : null),
    [settings, projectId, labels, personName, invalidate],
  );

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName || t('stakeholders.ui.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('stakeholders.ui.title', { defaultValue: 'Stakeholders' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{t('stakeholders.ui.title', { defaultValue: 'Stakeholders' })}</h1>
        <p className="text-sm text-content-secondary">
          {t('stakeholders.ui.subtitle', {
            defaultValue: 'Who the project affects, how you keep them engaged, what you promised them, and who decides.',
          })}
        </p>
      </div>
      <CollapsibleSection
        storageKey="stakeholders.how"
        icon={<Compass className="h-4 w-4" />}
        title={t('stakeholders.ui.how_title', { defaultValue: 'How stakeholder management works' })}
        subtitle={t('stakeholders.ui.how_subtitle', { defaultValue: 'Register, assess, plan, keep promises, name who decides' })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{t('stakeholders.ui.how_step_1', { defaultValue: 'List everyone the project affects or depends on, and assess each one: how much they can affect the project and how engaged they need to be.' })}</li>
          <li>{t('stakeholders.ui.how_step_2', { defaultValue: 'Plan the communication: who hears what, how often, through which channel and from whom. Record each one once it took place.' })}</li>
          <li>{t('stakeholders.ui.how_step_3', { defaultValue: 'Write down every promise made to a stakeholder as a commitment with an owner and a due date, and close it once they were told the outcome.' })}</li>
          <li>{t('stakeholders.ui.how_step_4', { defaultValue: 'Name who holds each project role and who decides each kind of decision. The next phase gate checks all of this.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  const frame = (body: ReactNode) => (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="stakeholders-page">
      {header}
      {body}
    </div>
  );

  if (settingsQ.isLoading) return frame(<SkeletonTable rows={6} columns={5} />);
  if (settingsQ.isError) {
    return frame(
      <ErrorState
        title={t('stakeholders.ui.load_failed', { defaultValue: 'The stakeholders could not be loaded' })}
        hint={getErrorMessage(settingsQ.error)}
        onRetry={() => settingsQ.refetch()}
      />,
    );
  }
  if (!screen) {
    return frame(
      <>
        <EmptyState
          icon={<Users size={28} />}
          title={t('stakeholders.ui.empty_settings_title', { defaultValue: 'Stakeholder management is not set up yet' })}
          description={t('stakeholders.ui.empty_settings_body', {
            defaultValue: 'Choose the framework this project works with. It brings the stakeholder categories, the project roles and a first mandate matrix. The register opens right after.',
          })}
        />
        <FrameworkSettings
          projectId={projectId}
          settings={null}
          canPin={settingsQ.data?.can?.manage_organisation ?? true}
          labels={labels}
          onSaved={invalidate}
        />
      </>,
    );
  }

  const stakeholders = registerQ.data ?? [];
  const selected = stakeholderId ? (stakeholders.find((s) => s.id === stakeholderId) ?? null) : null;
  const failure = (title: string, error: unknown) => <ErrorState title={title} hint={getErrorMessage(error)} onRetry={invalidate} />;

  let body: ReactNode;
  if (stakeholderId && registerQ.isLoading) {
    body = <SkeletonTable rows={4} columns={4} />;
  } else if (stakeholderId && selected) {
    body = <StakeholderDetail key={selected.id} screen={screen} stakeholder={selected} stakeholders={stakeholders} onBack={() => go({ stakeholder: null })} />;
  } else if (stakeholderId && registerQ.isError) {
    body = failure(t('stakeholders.ui.load_failed', { defaultValue: 'The stakeholders could not be loaded' }), registerQ.error);
  } else if (stakeholderId) {
    // A link to a stakeholder that was removed, or that belongs to another project.
    body = (
      <EmptyState
        icon={<Users size={28} />}
        title={t('stakeholders.ui.stakeholder.missing_title', { defaultValue: 'This stakeholder is not in the register' })}
        description={t('stakeholders.ui.stakeholder.missing_body', {
          defaultValue: 'It may have been removed, or the link belongs to another project. The register lists everyone this project keeps.',
        })}
        action={
          <Button variant="secondary" onClick={() => go({ stakeholder: null })} data-testid="stakeholder-missing-back">
            {t('stakeholders.ui.back_to_register', { defaultValue: 'Back to the register' })}
          </Button>
        }
      />
    );
  } else if (tab === 'settings') {
    body = <FrameworkSettings projectId={projectId} settings={screen.settings} labels={labels} onSaved={invalidate} />;
  } else if (tab === 'organisation') {
    body = (
      <div className="space-y-6">
        <OrganisationPanel screen={screen} onOpenSettings={() => go({ tab: 'settings' })} />
        <ExportBar projectId={projectId} settings={screen.settings} document="organisation" />
      </div>
    );
  } else if (registerQ.isLoading) {
    body = <SkeletonTable rows={6} columns={5} />;
  } else if (registerQ.isError) {
    body = failure(t('stakeholders.ui.load_failed', { defaultValue: 'The stakeholders could not be loaded' }), registerQ.error);
  } else if (tab === 'analysis') {
    body = (
      <AnalysisGrid
        screen={screen}
        method={method}
        onMethod={(code) => go({ method: code })}
        onOpen={(id) => go({ stakeholder: id })}
      />
    );
  } else if (tab === 'plan') {
    const error = planQ.error ?? dueQ.error ?? eventsQ.error;
    body =
      planQ.isLoading || dueQ.isLoading || eventsQ.isLoading ? (
        <SkeletonTable rows={5} columns={4} />
      ) : error ? (
        failure(t('stakeholders.ui.plan.load_failed', { defaultValue: 'The communication plan could not be loaded' }), error)
      ) : (
        <PlanPanel
          screen={screen}
          items={planQ.data ?? []}
          due={dueQ.data ?? []}
          events={eventsQ.data ?? []}
          stakeholders={stakeholders}
          focusItemId={params.get('item')}
        />
      );
  } else if (tab === 'commitments') {
    body = commitmentsQ.isLoading ? (
      <SkeletonTable rows={5} columns={4} />
    ) : commitmentsQ.isError ? (
      failure(t('stakeholders.ui.commitment.load_failed', { defaultValue: 'The commitments could not be loaded' }), commitmentsQ.error)
    ) : (
      <CommitmentsPanel
        screen={screen}
        commitments={commitmentsQ.data ?? []}
        stakeholders={stakeholders}
        events={eventsQ.data ?? []}
        focusId={params.get('commitment')}
      />
    );
  } else {
    body = (
      <div className="space-y-6">
        <RegisterPanel
          screen={screen}
          stakeholders={stakeholders}
          readiness={readinessQ.data}
          onOpen={(id) => go({ stakeholder: id })}
          onAdd={() => setAdding(true)}
        />
        {stakeholders.length > 0 && <ChecksPanel projectId={projectId} />}
        {stakeholders.length > 0 && <ExportBar projectId={projectId} settings={screen.settings} document="register" />}
      </div>
    );
  }

  const overdueCommitments = (commitmentsQ.data ?? []).filter((c) => c.overdue).length;
  const overdueDue = (dueQ.data ?? []).filter((d) => d.overdue && !d.done).length;
  const reviewDue = stakeholders.filter((s) => s.review_due && s.status !== 'archived').length;

  return frame(
    <>
      {!stakeholderId && (
        <TabBar<Tab>
          ariaLabel={t('stakeholders.ui.tabs', { defaultValue: 'Stakeholder sections' })}
          activeId={tab}
          onChange={(id) => go({ tab: id === 'register' && !SECTION_TAB[section] ? null : id })}
          idPrefix="stakeholders"
          tabs={[
            {
              id: 'register',
              label: t('stakeholders.ui.tab_register', { defaultValue: 'Register' }),
              icon: <Users size={14} />,
              badge: reviewDue > 0 ? reviewDue : undefined,
            },
            { id: 'analysis', label: t('stakeholders.ui.tab_analysis', { defaultValue: 'Analysis' }), icon: <Grid3x3 size={14} /> },
            {
              id: 'plan',
              label: t('stakeholders.ui.tab_plan', { defaultValue: 'Communication plan' }),
              icon: <CalendarClock size={14} />,
              badge: overdueDue > 0 ? overdueDue : undefined,
            },
            {
              id: 'commitments',
              label: t('stakeholders.ui.tab_commitments', { defaultValue: 'Commitments' }),
              icon: <Handshake size={14} />,
              badge: overdueCommitments > 0 ? overdueCommitments : undefined,
            },
            {
              id: 'organisation',
              label: t('stakeholders.ui.tab_organisation', { defaultValue: 'Organisation and mandates' }),
              icon: <Network size={14} />,
            },
            { id: 'settings', label: t('stakeholders.ui.tab_settings', { defaultValue: 'Settings' }), icon: <Settings2 size={14} /> },
          ]}
        />
      )}
      {body}
      {adding && (
        <StakeholderDialog
          screen={screen}
          stakeholder={null}
          stakeholders={registerQ.data ?? []}
          onClose={() => setAdding(false)}
          onSaved={(saved) => {
            setAdding(false);
            invalidate();
            go({ stakeholder: saved.id });
          }}
        />
      )}
    </>,
  );
}
