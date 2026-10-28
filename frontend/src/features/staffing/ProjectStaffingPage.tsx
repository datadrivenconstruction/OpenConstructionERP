// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Project staffing, mounted at /projects/:projectId/staffing.
//
// The staffing plan is the home view. The organisation chart, the people
// with a personnel file, the compliance matrix, what is coming up and
// planned against booked time sit behind tabs (?tab=). One personnel file
// opens at /projects/:projectId/staffing/files/:fileId, the address the
// document-expiry notification links to.

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { CalendarClock, ClipboardList, Compass, FolderLock, Network, ShieldCheck, Timer, Users } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';

import {
  useCompliance,
  useHandovers,
  useInvalidateStaffing,
  useLabelContext,
  useOrgChart,
  usePeopleNames,
  usePersonnelFiles,
  usePinnedCatalogue,
  usePlanFindings,
  usePlannedVsActual,
  usePositions,
  useStaffingPlan,
  useUpcoming,
} from './hooks';
import { refusalText } from './labels';
import { PeoplePanel } from './PeoplePanel';
import { PersonnelFilePanel } from './PersonnelFilePanel';
import { PlanSetup } from './PlanDialogs';
import { PlanPanel } from './PlanPanel';
import { ComplianceView, OrgChartView, PlannedVsActualView, UpcomingView } from './ReadViews';

type Tab = 'plan' | 'org_chart' | 'people' | 'compliance' | 'upcoming' | 'planned_vs_actual';
const TABS: Tab[] = ['plan', 'org_chart', 'people', 'compliance', 'upcoming', 'planned_vs_actual'];

export function ProjectStaffingPage() {
  const { t } = useTranslation();
  const { projectId = '', fileId } = useParams<{ projectId: string; fileId?: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const labels = useLabelContext();
  const personName = usePeopleNames(projectId);
  const invalidate = useInvalidateStaffing(projectId);

  const requested = params.get('tab') as Tab | null;
  const tab: Tab = requested && TABS.includes(requested) ? requested : 'plan';
  const base = `/projects/${projectId}/staffing`;
  const openFile = (id: string) => navigate(`${base}/files/${id}`);

  const planQ = useStaffingPlan(projectId);
  const hasPlan = !!planQ.data;
  const on = (which: Tab) => hasPlan && !fileId && tab === which;
  const catalogueQ = usePinnedCatalogue(projectId, hasPlan);
  const positionsQ = usePositions(projectId, on('plan') || on('planned_vs_actual'));
  const handoversQ = useHandovers(projectId, on('plan'));
  const findingsQ = usePlanFindings(projectId, on('plan'));
  const orgChartQ = useOrgChart(projectId, on('org_chart'));
  const filesQ = usePersonnelFiles(projectId, on('people'));
  const complianceQ = useCompliance(projectId, on('compliance'));
  const upcomingQ = useUpcoming(projectId, on('upcoming'));
  const pvaQ = usePlannedVsActual(projectId, on('planned_vs_actual'));

  const title = t('staffing.title', { defaultValue: 'Staffing' });
  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName || t('staffing.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          ...(fileId
            ? [{ label: title, to: `${base}?tab=people` }, { label: t('staffing.file.title', { defaultValue: 'Personnel file' }) }]
            : [{ label: title }]),
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{t('staffing.title', { defaultValue: 'Staffing' })}</h1>
        <p className="text-sm text-content-secondary">
          {t('staffing.subtitle', {
            defaultValue: 'Which roles the project needs in each phase, who fills them, and whether each person is cleared to start.',
          })}
        </p>
      </div>
      {!fileId && (
        <CollapsibleSection
          storageKey="staffing.how"
          icon={<Compass className="h-4 w-4" />}
          title={t('staffing.how_title', { defaultValue: 'How staffing works' })}
          subtitle={t('staffing.how_subtitle', { defaultValue: 'Roles, people, documents, approval' })}
        >
          <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
            <li>{t('staffing.how_step_1', { defaultValue: 'Pick a staffing catalogue. It brings the usual roles per phase and the documents each role needs.' })}</li>
            <li>{t('staffing.how_step_2', { defaultValue: 'Add the positions the project needs and put people from the project team on them.' })}</li>
            <li>{t('staffing.how_step_3', { defaultValue: 'Open a personnel file per person and record the required documents. A person with nothing missing or expired is cleared to work.' })}</li>
            <li>{t('staffing.how_step_4', { defaultValue: 'Submit the plan for review. It is approved at the governance gate of the personnel area.' })}</li>
          </ol>
        </CollapsibleSection>
      )}
    </>
  );

  const failed = (error: unknown, retry: () => void) => (
    <ErrorState
      title={t('staffing.load_failed', { defaultValue: 'Staffing could not be loaded' })}
      hint={refusalText(labels.t, error)}
      onRetry={retry}
    />
  );

  if (planQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <SkeletonTable rows={6} columns={5} />
      </div>
    );
  }
  if (planQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        {failed(planQ.error, () => planQ.refetch())}
      </div>
    );
  }

  const plan = planQ.data;
  if (!plan) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="project-staffing-page">
        {header}
        <EmptyState
          icon={<Users size={28} />}
          title={t('staffing.plan.empty_title', { defaultValue: 'No staffing plan yet' })}
          description={t('staffing.plan.empty_body', {
            defaultValue: 'The staffing plan lists the roles this project needs in each phase and who fills them. Pick a catalogue below to start; you can add and change roles afterwards.',
          })}
        />
        <PlanSetup projectId={projectId} labels={labels} onDone={invalidate} />
      </div>
    );
  }

  const catalogue = catalogueQ.data ?? null;
  const loading = <SkeletonTable rows={6} columns={5} />;

  let body: ReactNode;
  if (catalogueQ.isLoading) {
    body = loading;
  } else if (catalogueQ.isError || !catalogue) {
    body = failed(catalogueQ.error, () => catalogueQ.refetch());
  } else if (fileId) {
    body = (
      <PersonnelFilePanel
        key={fileId}
        projectId={projectId}
        fileId={fileId}
        catalogue={catalogue}
        labels={labels}
        personName={personName}
        onBack={() => navigate(`${base}?tab=people`)}
      />
    );
  } else if (tab === 'org_chart') {
    body = orgChartQ.isLoading ? loading : orgChartQ.isError || !orgChartQ.data ? failed(orgChartQ.error, () => orgChartQ.refetch()) : (
      <OrgChartView projectId={projectId} catalogue={catalogue} labels={labels} chart={orgChartQ.data} />
    );
  } else if (tab === 'people') {
    body = filesQ.isLoading ? loading : filesQ.isError ? failed(filesQ.error, () => filesQ.refetch()) : (
      <PeoplePanel
        projectId={projectId}
        files={filesQ.data?.files ?? []}
        candidates={filesQ.data?.candidates ?? []}
        catalogue={catalogue} labels={labels} onOpen={openFile} onChanged={invalidate} />
    );
  } else if (tab === 'compliance') {
    body = complianceQ.isLoading ? loading : complianceQ.isError || !complianceQ.data ? failed(complianceQ.error, () => complianceQ.refetch()) : (
      <ComplianceView projectId={projectId} catalogue={catalogue} labels={labels} compliance={complianceQ.data} onOpenFile={openFile} />
    );
  } else if (tab === 'upcoming') {
    body = upcomingQ.isLoading ? loading : upcomingQ.isError || !upcomingQ.data ? failed(upcomingQ.error, () => upcomingQ.refetch()) : (
      <UpcomingView catalogue={catalogue} labels={labels} upcoming={upcomingQ.data} onOpenFile={openFile} />
    );
  } else if (tab === 'planned_vs_actual') {
    body = pvaQ.isLoading || positionsQ.isLoading ? loading : pvaQ.isError ? failed(pvaQ.error, () => pvaQ.refetch()) : (
      <PlannedVsActualView catalogue={catalogue} labels={labels} rows={pvaQ.data ?? []} positions={positionsQ.data ?? []} />
    );
  } else if (positionsQ.isLoading || handoversQ.isLoading) {
    body = loading;
  } else if (positionsQ.isError || handoversQ.isError || findingsQ.isError) {
    // A list that failed to load must not read as an empty one: no handovers, nothing blocking.
    body = failed(positionsQ.error ?? handoversQ.error ?? findingsQ.error, invalidate);
  } else {
    body = (
      <PlanPanel
        projectId={projectId}
        plan={plan}
        catalogue={catalogue}
        positions={positionsQ.data ?? []}
        handovers={handoversQ.data ?? []}
        findings={findingsQ.data?.findings ?? []}
        restrictedPeople={findingsQ.data?.restrictedPeople ?? 0}
        labels={labels}
        personName={personName}
        onChanged={invalidate}
      />
    );
  }

  return (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="project-staffing-page">
      {header}
      {!fileId && (
        <TabBar<Tab>
          ariaLabel={t('staffing.tabs.label', { defaultValue: 'Staffing sections' })}
          activeId={tab}
          onChange={(id) => {
            const next = new URLSearchParams(params);
            if (id === 'plan') next.delete('tab');
            else next.set('tab', id);
            setParams(next, { replace: false });
          }}
          idPrefix="project-staffing"
          tabs={[
            { id: 'plan', label: t('staffing.tabs.plan', { defaultValue: 'Staffing plan' }), icon: <ClipboardList size={14} /> },
            { id: 'org_chart', label: t('staffing.tabs.org_chart', { defaultValue: 'Organisation chart' }), icon: <Network size={14} /> },
            { id: 'people', label: t('staffing.tabs.people', { defaultValue: 'People' }), icon: <FolderLock size={14} /> },
            { id: 'compliance', label: t('staffing.tabs.compliance', { defaultValue: 'Compliance' }), icon: <ShieldCheck size={14} /> },
            { id: 'upcoming', label: t('staffing.tabs.upcoming', { defaultValue: 'Upcoming' }), icon: <CalendarClock size={14} /> },
            { id: 'planned_vs_actual', label: t('staffing.tabs.planned_vs_actual', { defaultValue: 'Planned vs actual' }), icon: <Timer size={14} /> },
          ]}
        />
      )}
      {body}
    </div>
  );
}
