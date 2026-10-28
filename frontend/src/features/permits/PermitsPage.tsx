// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Permits, mounted at /projects/:projectId/permits.
//
// The roadmap is the home view. A permit, an application or a condition
// opens in place and the URL remembers it (?requirement=, ?application=,
// ?condition=), so a link reopens the same record. The permit register, the
// condition register and the readiness checks sit behind tabs.

import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { ClipboardCheck, Compass, Download, FileCheck2, FileUp, ListChecks, Map as MapIcon, ShieldCheck } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import { downloadRegister, publishFrameDocument, type ExportRegister } from './api';
import { ApplicationPanel } from './ApplicationPanel';
import { isBinding } from './ChangeRequestField';
import { ChecksPanel, READINESS_GATE } from './ChecksPanel';
import { ConditionPanel } from './ConditionPanel';
import { ConditionsRegister } from './ConditionsRegister';
import {
  refusalText,
  useApplications,
  useConditions,
  useLabelContext,
  usePeopleNames,
  usePermitAction,
  usePermits,
  useReadiness,
  useRequirements,
  useRoadmap,
  useTimeline,
  useValidation,
  useViewerId,
} from './hooks';
import { READINESS_STATUS, typeName, vocab, type TFn } from './labels';
import { FormDialog, GatedButton, READINESS_TONE, RefusedActions, ToneBadge } from './PermitBits';
import { PermitsRegister } from './PermitsRegister';
import { RequirementPanel } from './RequirementPanel';
import { ProposeDialog, RequirementDialog, RoadmapSetupDialog } from './RoadmapDialogs';
import { RoadmapTable } from './RoadmapTable';
import { buildRoadmapRows, gate } from './rules';

type Tab = 'roadmap' | 'permits' | 'conditions' | 'checks';
type Dialog = 'setup' | 'propose' | 'add' | 'file' | null;

const EXPORT_OF_TAB: Record<Tab, ExportRegister | null> = {
  roadmap: 'roadmap',
  permits: 'permits',
  conditions: 'conditions',
  checks: null,
};

export function PermitsPage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const [params, setParams] = useSearchParams();
  const labels = useLabelContext();
  const personName = usePeopleNames(projectId);
  const viewerId = useViewerId();
  const addToast = useToastStore((s) => s.addToast);
  const projectName = useProjectContextStore((s) => s.activeProjectName);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [exporting, setExporting] = useState(false);

  const roadmapQ = useRoadmap(projectId);
  const has = !!roadmapQ.data;
  const requirementsQ = useRequirements(projectId, has);
  const timelineQ = useTimeline(projectId, has);
  const applicationsQ = useApplications(projectId, has);
  const permitsQ = usePermits(projectId, has);
  const conditionsQ = useConditions(projectId, has);
  const startQ = useReadiness(projectId, 'start', has);
  const handoverQ = useReadiness(projectId, 'handover', has);
  const registerQ = useReadiness(projectId, 'register', has);

  const asked = params.get('tab');
  const tab: Tab = asked === 'permits' || asked === 'conditions' || asked === 'checks' ? asked : 'roadmap';
  const validationQ = useValidation(projectId, has && tab === 'checks');
  const requirementId = params.get('requirement');
  const applicationId = params.get('application');
  const conditionId = params.get('condition');
  const go = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: false });
  };

  const rows = useMemo(
    () => buildRoadmapRows(requirementsQ.data ?? [], timelineQ.data ?? [], applicationsQ.data ?? []),
    [requirementsQ.data, timelineQ.data, applicationsQ.data],
  );
  const conditions = conditionsQ.data ?? [];
  const permits = permitsQ.data ?? [];
  const overdue = conditions.filter((c) => c.confirmed && c.overdue).length;

  const tabRegister = EXPORT_OF_TAB[tab] ?? 'roadmap';
  const file = usePermitAction(
    projectId,
    () => publishFrameDocument(projectId, tabRegister),
    () => {
      setDialog(null);
      addToast({
        type: 'success',
        title: t('permits.ui.file.done', { defaultValue: 'Stored as a new revision in the project documents.' }),
      });
    },
  );

  const exportRegister = async (register: ExportRegister, format: 'pdf' | 'xlsx') => {
    setExporting(true);
    try {
      await downloadRegister(projectId, register, format);
    } catch (err) {
      addToast({ type: 'error', title: refusalText(t as TFn, err) });
    } finally {
      setExporting(false);
    }
  };

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName || t('permits.ui.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('permits.ui.title', { defaultValue: 'Permits' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{t('permits.ui.title', { defaultValue: 'Permits' })}</h1>
        <p className="text-sm text-content-secondary">
          {t('permits.ui.subtitle', {
            defaultValue: 'Which permits the project needs, where each application stands, and what the permits ask of the site.',
          })}
        </p>
      </div>
      <CollapsibleSection
        storageKey="permits.how"
        icon={<Compass className="h-4 w-4" />}
        title={t('permits.ui.how_title', { defaultValue: 'How permits work here' })}
        subtitle={t('permits.ui.how_subtitle', { defaultValue: 'Roadmap, application, decision, conditions' })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{t('permits.ui.how_step_1', { defaultValue: 'List the permits the project needs on the roadmap, with the date each one is needed.' })}</li>
          <li>{t('permits.ui.how_step_2', { defaultValue: 'Open an application for a permit and record each step: prepared, submitted, questions from the authority.' })}</li>
          <li>{t('permits.ui.how_step_3', { defaultValue: 'The decision period is counted from the submission, so you see when the answer is due and whether it comes in time.' })}</li>
          <li>{t('permits.ui.how_step_4', { defaultValue: 'Record the decision with its conditions. Each condition gets an owner, evidence and a second person who checks it.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (roadmapQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <SkeletonTable rows={6} columns={6} />
      </div>
    );
  }
  if (roadmapQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <ErrorState
          title={t('permits.ui.load_failed', { defaultValue: 'The permits could not be loaded' })}
          hint={refusalText(t as TFn, roadmapQ.error)}
          onRetry={() => roadmapQ.refetch()}
        />
      </div>
    );
  }

  const roadmap = roadmapQ.data;
  if (!roadmap) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="permits-page">
        {header}
        <EmptyState
          icon={<MapIcon size={28} />}
          title={t('permits.ui.empty_roadmap_title', { defaultValue: 'No permit roadmap yet' })}
          description={t('permits.ui.empty_roadmap_body', {
            defaultValue:
              'The roadmap lists every permit this project needs, who applies for it and by when. Start it, and the permit types of your jurisdiction come with their decision periods.',
          })}
          action={{ label: t('permits.ui.setup.submit_new', { defaultValue: 'Start roadmap' }), onClick: () => setDialog('setup') }}
        />
        <RoadmapSetupDialog open={dialog === 'setup'} onClose={() => setDialog(null)} projectId={projectId} roadmap={null} labels={labels} />
      </div>
    );
  }

  const listQs = [requirementsQ, timelineQ, applicationsQ];
  const listsLoading = listQs.some((q) => q.isLoading);
  const listsError = listQs.find((q) => q.isError)?.error;
  const retryLists = () => listQs.forEach((q) => void q.refetch());
  const selectedRow = requirementId ? (rows.find((r) => r.requirement.id === requirementId) ?? null) : null;
  const applicationRow = applicationId ? (rows.find((r) => r.applications.some((a) => a.id === applicationId)) ?? null) : null;
  // A link to a permit that is gone falls back to the roadmap, with its tabs.
  const inRecord = !!(applicationId || conditionId || (requirementId && (listsLoading || selectedRow)));

  let body: ReactNode;
  if (applicationId) {
    const r = applicationRow?.requirement;
    body = (
      <ApplicationPanel
        projectId={projectId}
        applicationId={applicationId}
        requirementName={r ? r.title || typeName(labels, r.permit_type_code, r.name_key) : ''}
        permits={permits.filter((p) => p.requirement_id === r?.id)}
        conditions={conditions}
        labels={labels}
        personName={personName}
        internalReview={roadmap.internal_review}
        onBack={() => go({ application: null, requirement: r?.id ?? requirementId })}
      />
    );
  } else if (conditionId) {
    body = (
      <ConditionPanel
        key={conditionId}
        projectId={projectId}
        conditionId={conditionId}
        row={conditions.find((c) => c.id === conditionId) ?? null}
        personName={personName}
        onBack={() => go({ condition: null, tab: 'conditions' })}
      />
    );
  } else if (requirementId && (listsLoading || selectedRow)) {
    body = selectedRow ? (
      <RequirementPanel
        key={selectedRow.requirement.id}
        projectId={projectId}
        roadmap={roadmap}
        row={selectedRow}
        all={requirementsQ.data ?? []}
        permits={permits}
        conditions={conditions}
        labels={labels}
        personName={personName}
        onBack={() => go({ requirement: null })}
        onOpenApplication={(id) => go({ application: id })}
      />
    ) : (
      <SkeletonTable rows={4} columns={4} />
    );
  } else if (tab === 'checks') {
    body = <ChecksPanel readiness={{ start: startQ, handover: handoverQ, register: registerQ }} validation={validationQ} />;
  } else if (tab === 'conditions') {
    body = conditionsQ.isLoading ? (
      <SkeletonTable rows={4} columns={4} />
    ) : conditionsQ.isError ? (
      <ErrorState
        title={t('permits.ui.conditions.load_failed', { defaultValue: 'The conditions could not be loaded' })}
        hint={refusalText(t as TFn, conditionsQ.error)}
        onRetry={() => conditionsQ.refetch()}
      />
    ) : (
      <ConditionsRegister
        projectId={projectId}
        can={roadmap?.can}
        conditions={conditions}
        viewerId={viewerId}
        personName={personName}
        onOpen={(id) => go({ condition: id })}
        onShowPermits={() => go({ tab: 'permits' })}
      />
    );
  } else if (tab === 'permits') {
    body = permitsQ.isLoading ? (
      <SkeletonTable rows={4} columns={4} />
    ) : permitsQ.isError ? (
      <ErrorState
        title={t('permits.ui.permit.load_failed', { defaultValue: 'The permit register could not be loaded' })}
        hint={refusalText(t as TFn, permitsQ.error)}
        onRetry={() => permitsQ.refetch()}
      />
    ) : (
      <PermitsRegister
        projectId={projectId}
        permits={permits}
        requirements={requirementsQ.data ?? []}
        conditions={conditions}
        labels={labels}
        personName={personName}
        onOpenRequirement={(id) => go({ requirement: id, tab: null })}
        onShowConditions={() => go({ tab: 'conditions' })}
        onShowRoadmap={() => go({ tab: null })}
      />
    );
  } else if (listsLoading) {
    body = <SkeletonTable rows={6} columns={6} />;
  } else if (listsError) {
    body = (
      <ErrorState
        title={t('permits.ui.load_failed', { defaultValue: 'The permits could not be loaded' })}
        hint={refusalText(t as TFn, listsError)}
        onRetry={retryLists}
      />
    );
  } else {
    body = (
      <RoadmapTable
        rows={rows}
        binding={isBinding(roadmap)}
        can={roadmap?.can}
        gatesInUse={roadmap?.gates_in_use}
        labels={labels}
        onOpen={(id) => go({ requirement: id })}
        onAdd={() => setDialog('add')}
        onPropose={() => setDialog('propose')}
        onSettings={() => setDialog('setup')}
      />
    );
  }

  const exportTarget = inRecord ? null : EXPORT_OF_TAB[tab];

  return (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="permits-page">
      {header}
      {!inRecord && (
        <>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2" data-testid="readiness-strip">
            {([['start', startQ], ['handover', handoverQ]] as const).map(([gate, q]) =>
              q.isLoading ? (
                <span key={gate} className="inline-flex animate-pulse items-center gap-2 text-sm text-content-tertiary">
                  {vocab(t, READINESS_GATE, gate)}
                  <span className="h-5 w-16 rounded-full bg-surface-secondary" />
                </span>
              ) : q.isError ? (
                <button
                  key={gate}
                  type="button"
                  className="inline-flex items-center gap-2 text-sm text-content-secondary hover:text-content-primary"
                  onClick={() => go({ tab: 'checks' })}
                  data-testid={`readiness-chip-${gate}`}
                >
                  {vocab(t, READINESS_GATE, gate)}
                  <ToneBadge tone="neutral">{t('permits.ui.readiness.unavailable', { defaultValue: 'Not available' })}</ToneBadge>
                </button>
              ) : q.data ? (
                <button
                  key={gate}
                  type="button"
                  className="inline-flex items-center gap-2 text-sm text-content-secondary hover:text-content-primary"
                  onClick={() => go({ tab: 'checks' })}
                  data-testid={`readiness-chip-${gate}`}
                >
                  {vocab(t, READINESS_GATE, gate)}
                  <ToneBadge tone={READINESS_TONE[q.data.status]}>{vocab(t, READINESS_STATUS, q.data.status)}</ToneBadge>
                </button>
              ) : null,
            )}
            {exportTarget && (
              <span className="ml-auto flex items-center gap-1.5">
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Download size={14} />}
                  disabled={exporting}
                  onClick={() => exportRegister(exportTarget, 'pdf')}
                  data-testid="export-pdf"
                >
                  {t('permits.ui.export_pdf', { defaultValue: 'PDF' })}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Download size={14} />}
                  disabled={exporting}
                  onClick={() => exportRegister(exportTarget, 'xlsx')}
                  data-testid="export-xlsx"
                >
                  {t('permits.ui.export_xlsx', { defaultValue: 'Spreadsheet (.xlsx)' })}
                </Button>
                <GatedButton
                  // Without gates there is no frame document to store into, so the action is left out, not refused.
                  gate={{ ...gate(roadmap?.can?.publish_frame_document, true), ...(roadmap?.gates_in_use === false ? { show: false } : {}) }}
                  size="sm"
                  variant="ghost"
                  icon={<FileUp size={14} />}
                  onClick={() => {
                    file.reset();
                    setDialog('file');
                  }}
                  data-testid="file-register"
                >
                  {t('permits.ui.file.open', { defaultValue: 'Store in project documents' })}
                </GatedButton>
              </span>
            )}
          </div>
          <RefusedActions
            testId="file-refused"
            items={[
              !!exportTarget &&
                roadmap?.gates_in_use !== false && [
                t('permits.ui.file.open', { defaultValue: 'Store in project documents' }),
                gate(roadmap?.can?.publish_frame_document, true),
              ],
            ]}
          />
          <TabBar<Tab>
            ariaLabel={t('permits.ui.tabs', { defaultValue: 'Permit sections' })}
            activeId={tab}
            onChange={(id) => go({ tab: id === 'roadmap' ? null : id })}
            idPrefix="permits"
            tabs={[
              { id: 'roadmap', label: t('permits.ui.tab_roadmap', { defaultValue: 'Roadmap' }), icon: <ListChecks size={14} /> },
              {
                id: 'permits',
                label: t('permits.ui.tab_permits', { defaultValue: 'Permits granted' }),
                icon: <FileCheck2 size={14} />,
                badge: permits.length > 0 ? permits.length : undefined,
              },
              {
                id: 'conditions',
                label: t('permits.ui.tab_conditions', { defaultValue: 'Conditions' }),
                icon: <ClipboardCheck size={14} />,
                badge: overdue > 0 ? overdue : undefined,
              },
              { id: 'checks', label: t('permits.ui.tab_checks', { defaultValue: 'Readiness' }), icon: <ShieldCheck size={14} /> },
            ]}
          />
        </>
      )}
      {body}
      <RoadmapSetupDialog open={dialog === 'setup'} onClose={() => setDialog(null)} projectId={projectId} roadmap={roadmap} labels={labels} />
      <FormDialog
        open={dialog === 'file'}
        onClose={() => setDialog(null)}
        testId="file-register-dialog"
        title={t('permits.ui.file.title', { defaultValue: 'Store this register in the project documents' })}
        subtitle={t('permits.ui.file.subtitle', {
          defaultValue:
            'The register as it stands now is stored as a new revision of its governance document, so a gate can refer to exactly this state.',
        })}
        submitLabel={t('permits.ui.file.submit', { defaultValue: 'Store register' })}
        busy={file.busy}
        error={file.error}
        problems={[]}
        onSubmit={() => file.run(undefined)}
      >
        <p className="text-sm text-content-secondary">
          {t('permits.ui.file.body', {
            defaultValue: 'Nothing in the register changes. Once the document is binding, a new revision needs an approved change request.',
          })}
        </p>
      </FormDialog>
      <ProposeDialog open={dialog === 'propose'} onClose={() => setDialog(null)} projectId={projectId} roadmap={roadmap} labels={labels} />
      <RequirementDialog
        open={dialog === 'add'}
        onClose={() => setDialog(null)}
        projectId={projectId}
        roadmap={roadmap}
        requirement={null}
        labels={labels}
        personName={personName}
      />
    </div>
  );
}
