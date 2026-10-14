// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Design management, mounted at /projects/:projectId/design.
//
// The overview is the home view: what still blocks each design phase. The
// other tabs follow the work: the design schedule, the drawing register,
// issuing, reviews, reports, the permit package, then who is on the design
// team, the work breakdown and the setup. The URL remembers the tab (?tab=),
// so a link reopens the same list.

import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Compass } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { getErrorMessage } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';

import { listDeliverables, listDrawings, listRoles, listWbs } from './api';
import { DesignAccessContext, type DesignContext } from './DesignBits';
import { DrawingsPanel } from './DrawingsPanel';
import { useDesignList, useDesignSetup, useInvalidateDesign, useLabelContext, usePeopleNames } from './hooks';
import { IssuePanel } from './IssuePanel';
import { ui, type TFn } from './labels';
import { OverviewPanel } from './OverviewPanel';
import { PermitsPanel } from './PermitsPanel';
import { ReportsPanel } from './ReportsPanel';
import { ReviewsPanel } from './ReviewsPanel';
import { SchedulePanel } from './SchedulePanel';
import { SetupPanel, SetupStart } from './SetupPanel';
import { TeamPanel } from './TeamPanel';
import { UI, type UiKey } from './text';
import { WbsPanel } from './WbsPanel';

const TABS = ['overview', 'schedule', 'drawings', 'issue', 'reviews', 'reports', 'permit', 'team', 'wbs', 'setup'] as const;
type Tab = (typeof TABS)[number];

const TAB_LABEL: Record<Tab, UiKey> = {
  overview: 'design.ui.tab.overview',
  schedule: 'design.ui.tab.schedule',
  drawings: 'design.ui.tab.drawings',
  issue: 'design.ui.tab.issue',
  reviews: 'design.ui.tab.reviews',
  reports: 'design.ui.tab.reports',
  permit: 'design.ui.tab.permit',
  team: 'design.ui.tab.team',
  wbs: 'design.ui.tab.wbs',
  setup: 'design.ui.tab.setup',
};

export function DesignManagementPage() {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const { projectId = '' } = useParams<{ projectId: string }>();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const labels = useLabelContext();
  const personName = usePeopleNames(projectId);
  const invalidate = useInvalidateDesign(projectId);
  const access = { canEdit: useHasPermission('design.edit'), canManage: useHasPermission('design.manage') };

  const setupQ = useDesignSetup(projectId);
  const ready = !!setupQ.data;
  const rolesQ = useDesignList(projectId, 'roles', listRoles, ready);
  const wbsQ = useDesignList(projectId, 'wbs', listWbs, ready);
  const linesQ = useDesignList(projectId, 'deliverables', listDeliverables, ready);
  const drawingsQ = useDesignList(projectId, 'drawings', listDrawings, ready);

  const wanted = params.get('tab') as Tab | null;
  const tab: Tab = wanted && TABS.includes(wanted) ? wanted : 'overview';
  const setTab = (next: Tab) => {
    const p = new URLSearchParams(params);
    if (next === 'overview') p.delete('tab');
    else p.set('tab', next);
    setParams(p, { replace: false });
  };

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: ui(t, 'design.ui.project'), to: `/projects/${projectId}` },
          { label: ui(t, 'design.ui.title') },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{t('design.ui.title', { defaultValue: UI['design.ui.title'] })}</h1>
        <p className="text-sm text-content-secondary">{ui(t, 'design.ui.subtitle')}</p>
      </div>
      <CollapsibleSection
        storageKey="design_management.how"
        icon={<Compass className="h-4 w-4" />}
        title={ui(t, 'design.ui.how_title')}
        subtitle={ui(t, 'design.ui.how_subtitle')}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{ui(t, 'design.ui.how_step_1')}</li>
          <li>{ui(t, 'design.ui.how_step_2')}</li>
          <li>{ui(t, 'design.ui.how_step_3')}</li>
          <li>{ui(t, 'design.ui.how_step_4')}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (setupQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <SkeletonTable rows={6} columns={6} />
      </div>
    );
  }
  if (setupQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <ErrorState title={ui(t, 'design.ui.load_failed')} hint={getErrorMessage(setupQ.error)} onRetry={() => setupQ.refetch()} />
      </div>
    );
  }

  const setup = setupQ.data;
  if (!setup) {
    return (
      <div className="space-y-5 animate-fade-in" data-testid="design-management-page">
        {header}
        <DesignAccessContext.Provider value={access}>
          <SetupStart projectId={projectId} labels={labels} onDone={invalidate} />
        </DesignAccessContext.Provider>
      </div>
    );
  }

  const shared = [rolesQ, wbsQ, linesQ, drawingsQ];
  const sharedError = shared.find((q) => q.isError)?.error;
  let body: ReactNode;
  if (shared.some((q) => q.isLoading)) {
    body = <SkeletonTable rows={6} columns={6} />;
  } else if (sharedError) {
    body = <ErrorState title={ui(t, 'design.ui.load_failed')} hint={getErrorMessage(sharedError)} onRetry={invalidate} />;
  } else {
    const ctx: DesignContext = {
      projectId,
      setup,
      labels,
      roles: rolesQ.data ?? [],
      wbs: wbsQ.data ?? [],
      deliverables: linesQ.data ?? [],
      drawings: drawingsQ.data ?? [],
      personName,
      onChanged: invalidate,
    };
    const panels: Record<Tab, ReactNode> = {
      overview: <OverviewPanel ctx={ctx} onOpenGovernance={() => navigate(`/projects/${projectId}/governance`)} />,
      schedule: <SchedulePanel ctx={ctx} />,
      drawings: <DrawingsPanel ctx={ctx} />,
      issue: <IssuePanel ctx={ctx} />,
      reviews: <ReviewsPanel ctx={ctx} />,
      reports: <ReportsPanel ctx={ctx} />,
      permit: <PermitsPanel ctx={ctx} />,
      team: <TeamPanel ctx={ctx} />,
      wbs: <WbsPanel ctx={ctx} />,
      setup: <SetupPanel ctx={ctx} />,
    };
    body = panels[tab];
  }

  return (
    <DesignAccessContext.Provider value={access}>
      <div className="space-y-5 animate-fade-in" data-testid="design-management-page">
        {header}
        <TabBar<Tab>
          ariaLabel={ui(t, 'design.ui.tabs')}
          activeId={tab}
          onChange={setTab}
          idPrefix="design-management"
          tabs={TABS.map((id) => ({
            id,
            label: ui(t, TAB_LABEL[id]),
            badge: id === 'drawings' && (drawingsQ.data ?? []).length > 0 ? (drawingsQ.data ?? []).length : undefined,
          }))}
        />
        {body}
      </div>
    </DesignAccessContext.Provider>
  );
}
