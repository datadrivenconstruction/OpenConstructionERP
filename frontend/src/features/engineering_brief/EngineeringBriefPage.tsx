// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The engineering brief of a project, mounted at /projects/:projectId/engineering-brief.
//
// The head shows the status, the operating proof and what blocks submission.
// The requirements, the technical concept, the programme and the framework
// schedule sit behind tabs (?tab=). Fields are read-only when the server's
// capability flags say so.

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { CalendarClock, ClipboardList, FileText, FlaskConical, LayoutGrid, Ruler } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';

import { ApprovalPanel, BriefSetup } from './ApprovalPanel';
import { ConceptTab } from './ConceptTab';
import {
  useBrief,
  useBriefFindings,
  useConcepts,
  useInvalidateBrief,
  useMilestones,
  usePinnedCatalogue,
  useProgramme,
  useRequirements,
  useSpecification,
  useStudies,
} from './hooks';
import { itemLabel, refusalText, type LabelContext, type TFn } from './labels';
import { ProgrammeTab } from './ProgrammeTab';
import { RequirementsTab } from './RequirementsTab';
import { ScheduleTab } from './ScheduleTab';
import { SpecificationPanel } from './SpecificationPanel';
import { StudiesTab } from './StudiesTab';

type Tab = 'requirements' | 'concept' | 'programme' | 'schedule' | 'studies';
const TABS: Tab[] = ['requirements', 'concept', 'programme', 'schedule', 'studies'];

export function EngineeringBriefPage() {
  const { t, i18n } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const [params, setParams] = useSearchParams();
  const invalidate = useInvalidateBrief(projectId);
  const labels: LabelContext = { t: t as TFn, language: i18n?.language ?? 'en' };

  const requested = params.get('tab') as Tab | null;
  const tab: Tab = requested && TABS.includes(requested) ? requested : 'requirements';

  const briefQ = useBrief(projectId);
  const hasBrief = !!briefQ.data;
  const catalogueQ = usePinnedCatalogue(projectId, hasBrief);
  const findingsQ = useBriefFindings(projectId, hasBrief);
  const on = (which: Tab) => hasBrief && tab === which;
  // The concept dialog links requirements, so that tab needs them as well.
  const requirementsQ = useRequirements(projectId, on('requirements') || on('concept'));
  const conceptQ = useConcepts(projectId, on('concept'));
  const programmeQ = useProgramme(projectId, on('programme'));
  const milestonesQ = useMilestones(projectId, on('schedule'));
  const studiesQ = useStudies(projectId, on('studies'));
  const specificationQ = useSpecification(projectId, on('requirements'));

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: t('engineeringBrief.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('engineeringBrief.title', { defaultValue: 'Engineering brief' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{t('engineeringBrief.title', { defaultValue: 'Engineering brief' })}</h1>
        <p className="text-sm text-content-secondary">
          {t('engineeringBrief.subtitle', {
            defaultValue: 'What the client needs, how the building will meet it, the room programme and the dates that frame the project.',
          })}
        </p>
      </div>
    </>
  );

  const failed = (error: unknown, retry: () => void) => (
    <ErrorState
      title={t('engineeringBrief.load_failed', { defaultValue: 'The engineering brief could not be loaded' })}
      hint={refusalText(t as TFn, error)}
      onRetry={retry}
    />
  );
  const loading = <SkeletonTable rows={6} columns={5} />;

  if (briefQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in" data-testid="engineering-brief-page">
        {header}
        {loading}
      </div>
    );
  }
  if (briefQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in" data-testid="engineering-brief-page">
        {header}
        {failed(briefQ.error, () => briefQ.refetch())}
      </div>
    );
  }

  const brief = briefQ.data;
  if (!brief) {
    return (
      <div className="space-y-5 animate-fade-in" data-testid="engineering-brief-page">
        {header}
        <EmptyState
          icon={<FileText size={28} />}
          title={t('engineeringBrief.empty_title', { defaultValue: 'No engineering brief yet' })}
          description={t('engineeringBrief.empty_body', {
            defaultValue: 'The brief collects the requirements of the client, the technical concept, the programme and the framework schedule. Pick a catalogue to start.',
          })}
        />
        <BriefSetup projectId={projectId} labels={labels} onDone={invalidate} />
      </div>
    );
  }

  const catalogue = catalogueQ.data ?? null;
  const edit = brief.can.edit;
  // The edit permission, apart from the state lock: studies and the specification are not locked by review.
  const canWrite = edit.allowed || edit.reason !== 'edit_permission_required';
  let body: ReactNode;
  if (catalogueQ.isLoading) {
    body = loading;
  } else if (catalogueQ.isError || !catalogue) {
    body = failed(catalogueQ.error, () => catalogueQ.refetch());
  } else if (tab === 'concept') {
    body =
      conceptQ.isLoading || requirementsQ.isLoading ? loading : conceptQ.isError || requirementsQ.isError ? failed(conceptQ.error ?? requirementsQ.error, invalidate) : (
        <ConceptTab projectId={projectId} items={conceptQ.data ?? []} requirements={requirementsQ.data ?? []} catalogue={catalogue} labels={labels} edit={edit} onChanged={invalidate} />
      );
  } else if (tab === 'programme') {
    body = programmeQ.isLoading ? loading : programmeQ.isError ? failed(programmeQ.error, () => programmeQ.refetch()) : (
      <ProgrammeTab projectId={projectId} lines={programmeQ.data ?? []} catalogue={catalogue} labels={labels} edit={edit} onChanged={invalidate} />
    );
  } else if (tab === 'schedule') {
    body = milestonesQ.isLoading ? loading : milestonesQ.isError ? failed(milestonesQ.error, () => milestonesQ.refetch()) : (
      <ScheduleTab projectId={projectId} milestones={milestonesQ.data ?? []} catalogue={catalogue} labels={labels} edit={edit} publish={brief.can.publish} onChanged={invalidate} />
    );
  } else if (tab === 'studies') {
    body = studiesQ.isLoading ? loading : studiesQ.isError ? failed(studiesQ.error, () => studiesQ.refetch()) : (
      <StudiesTab projectId={projectId} studies={studiesQ.data ?? []} canWrite={canWrite} onChanged={invalidate} />
    );
  } else {
    body = requirementsQ.isLoading ? loading : requirementsQ.isError ? failed(requirementsQ.error, () => requirementsQ.refetch()) : (
      <div className="space-y-4">
        {specificationQ.data ? (
          <SpecificationPanel projectId={projectId} status={brief.status} spec={specificationQ.data} canWrite={canWrite} onChanged={invalidate} />
        ) : null}
        <RequirementsTab projectId={projectId} requirements={requirementsQ.data ?? []} catalogue={catalogue} labels={labels} edit={edit} onChanged={invalidate} />
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in" data-testid="engineering-brief-page">
      {header}
      <ApprovalPanel
        projectId={projectId}
        brief={brief}
        findings={findingsQ.data ?? []}
        catalogueName={catalogue ? itemLabel(labels, { code: catalogue.id, name_key: catalogue.name_key, labels: catalogue.labels }, catalogue.id) : brief.catalogue_id}
        onChanged={invalidate}
      />
      <TabBar<Tab>
        ariaLabel={t('engineeringBrief.tabs.label', { defaultValue: 'Engineering brief sections' })}
        activeId={tab}
        onChange={(id) => {
          const next = new URLSearchParams(params);
          if (id === 'requirements') next.delete('tab');
          else next.set('tab', id);
          setParams(next, { replace: false });
        }}
        idPrefix="engineering-brief"
        tabs={[
          { id: 'requirements', label: t('engineeringBrief.tabs.requirements', { defaultValue: 'Requirements' }), icon: <ClipboardList size={14} /> },
          { id: 'concept', label: t('engineeringBrief.tabs.concept', { defaultValue: 'Concept' }), icon: <LayoutGrid size={14} /> },
          { id: 'programme', label: t('engineeringBrief.tabs.programme', { defaultValue: 'Programme' }), icon: <Ruler size={14} /> },
          { id: 'schedule', label: t('engineeringBrief.tabs.schedule', { defaultValue: 'Framework schedule' }), icon: <CalendarClock size={14} /> },
          { id: 'studies', label: t('engineeringBrief.tabs.studies', { defaultValue: 'Studies' }), icon: <FlaskConical size={14} /> },
        ]}
      />
      {body}
    </div>
  );
}
