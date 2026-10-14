// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project HSE frame, mounted at /projects/:projectId/hse-frame.
//
// The overview tab is the home view: which duties the project's facts trigger, where each gate criterion
// stands and what the neighbouring modules report. The register, the responsibilities and the checks sit
// behind tabs, and the URL remembers the tab. National duties come from the catalogue the project is pinned
// to; nothing on this page names a country.

import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { ClipboardList, HardHat, ListChecks, ShieldAlert, Users } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { getErrorMessage } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';

import { createFrame } from './api';
import {
  useCatalogue,
  useChecks,
  useFrame,
  useHseWrite,
  useItems,
  useReadiness,
  useRoles,
  useSummary,
} from './hooks';
import { OverviewPanel } from './OverviewPanel';
import { RegisterPanel } from './RegisterPanel';
import { RolesPanel } from './RolesPanel';

export const HSE_TABS = ['overview', 'register', 'roles', 'checks'] as const;
export type HseTab = (typeof HSE_TABS)[number];

export function HseFramePage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const [params, setParams] = useSearchParams();
  const canEdit = useHasPermission('hse_frame.edit');
  const canManage = useHasPermission('hse_frame.manage');
  const canApprove = useHasPermission('hse_frame.approve');

  const frameQ = useFrame(projectId);
  const hasFrame = !!frameQ.data?.frame;
  const catalogueQ = useCatalogue(projectId, hasFrame);
  const itemsQ = useItems(projectId, hasFrame);
  const rolesQ = useRoles(projectId, hasFrame);
  const readinessQ = useReadiness(projectId, hasFrame);
  const summaryQ = useSummary(projectId, hasFrame);
  const checksQ = useChecks(projectId, hasFrame);
  const write = useHseWrite(projectId);

  const requested = params.get('tab') as HseTab | null;
  const tab: HseTab = requested && HSE_TABS.includes(requested) ? requested : 'overview';
  const openTab = (next: HseTab) => {
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
          { label: t('hseFrame.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('hseFrame.title', { defaultValue: 'Health, safety and environment' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">
          {t('hseFrame.title', { defaultValue: 'Health, safety and environment' })}
        </h1>
        <p className="text-sm text-content-secondary">
          {t('hseFrame.subtitle', {
            defaultValue:
              'The requirements, clearances, permit conditions, responsibilities and plans that frame safe and environmentally sound construction.',
          })}
        </p>
      </div>
    </>
  );

  if (frameQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <SkeletonTable rows={6} columns={5} />
      </div>
    );
  }
  if (frameQ.isError || !frameQ.data) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <ErrorState
          title={t('hseFrame.load_failed', { defaultValue: 'The HSE frame could not be loaded' })}
          hint={getErrorMessage(frameQ.error)}
          onRetry={() => frameQ.refetch()}
        />
      </div>
    );
  }
  const frame = frameQ.data.frame;
  if (!frame) {
    return (
      <div className="space-y-5 animate-fade-in" data-testid="hse-frame-missing">
        {header}
        {write.refusal && <p className="text-sm text-semantic-error">{write.refusal}</p>}
        <EmptyState
          icon={<HardHat size={28} />}
          title={t('hseFrame.missing_title', { defaultValue: 'This project has no HSE frame yet' })}
          description={t('hseFrame.missing_body', {
            defaultValue:
              'The frame collects what the owner requires of designers and contractors, the environmental review, the site clearances, the permit conditions and the safety coordination. Create it, then enter the project facts so the catalogue can tell which duties apply.',
          })}
          action={
            canEdit
              ? {
                  label: t('hseFrame.create', { defaultValue: 'Create HSE frame' }),
                  onClick: () => write.send(() => createFrame(projectId)),
                }
              : undefined
          }
        />
      </div>
    );
  }
  const catalogue = catalogueQ.data;
  if (!catalogue) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <SkeletonTable rows={6} columns={5} />
      </div>
    );
  }

  // Rows, roles and facts change only while the frame is a draft or being revised.
  const open = frame.state === 'draft' || frame.state === 'revising';
  const failed = (checksQ.data ?? []).filter((c) => !c.passed);
  return (
    <div className="space-y-5 animate-fade-in" data-testid="hse-frame-page">
      {header}
      {write.refusal && (
        <p role="alert" className="rounded-lg border border-semantic-error/40 p-3 text-sm text-content-primary" data-testid="refusal">
          {write.refusal}
        </p>
      )}
      <TabBar<HseTab>
        ariaLabel={t('hseFrame.tabs.label', { defaultValue: 'HSE frame sections' })}
        activeId={tab}
        onChange={openTab}
        tabs={[
          { id: 'overview', label: t('hseFrame.tabs.overview', { defaultValue: 'Overview' }), icon: <ShieldAlert size={14} /> },
          { id: 'register', label: t('hseFrame.tabs.register', { defaultValue: 'Register' }), icon: <ClipboardList size={14} />, badge: itemsQ.data?.length },
          { id: 'roles', label: t('hseFrame.tabs.roles', { defaultValue: 'Responsibilities' }), icon: <Users size={14} /> },
          { id: 'checks', label: t('hseFrame.tabs.checks', { defaultValue: 'Checks' }), icon: <ListChecks size={14} />, badge: failed.length || undefined },
        ]}
      />
      {tab === 'overview' && (
        <OverviewPanel
          projectId={projectId}
          frame={frame}
          catalogue={catalogue}
          duties={frameQ.data.duties}
          readiness={readinessQ.data}
          summary={summaryQ.data}
          write={write}
          canEdit={canEdit && open}
          canManage={canManage}
          canApprove={canApprove}
        />
      )}
      {tab === 'register' && (
        <RegisterPanel
          projectId={projectId}
          items={itemsQ.data ?? []}
          catalogue={catalogue}
          write={write}
          canEdit={canEdit && open}
          canManage={canManage && open}
        />
      )}
      {tab === 'roles' && (
        <RolesPanel
          projectId={projectId}
          roles={rolesQ.data ?? []}
          catalogue={catalogue}
          duties={frameQ.data.duties}
          write={write}
          canEdit={canEdit && open}
        />
      )}
      {tab === 'checks' && (
        <ul className="space-y-2" data-testid="checks-list">
          {(checksQ.data ?? []).map((c, i) => (
            <li key={`${c.rule_id}:${c.element_ref ?? ''}:${i}`} className="text-sm" data-passed={c.passed}>
              <span className={c.passed ? 'text-content-secondary' : 'text-content-primary'}>{c.message}</span>
              {!c.passed && c.suggestion && <span className="text-content-secondary"> {c.suggestion}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
