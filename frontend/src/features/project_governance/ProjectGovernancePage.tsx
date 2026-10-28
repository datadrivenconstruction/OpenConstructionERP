// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Project governance, mounted at /projects/:projectId/governance.
//
// The matrix is the home view. A gate or an area opens in place and the URL
// remembers it (?gate=, ?area=), so a link reopens the same gate. The
// conditions register and the phase model sit behind tabs.

import { useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ClipboardList, Compass, Grid3x3, Layers } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { getErrorMessage } from '@/shared/lib/api';

import { AreaPanel } from './AreaPanel';
import { ConditionsRegister } from './ConditionsRegister';
import { GatePanel } from './GatePanel';
import { GovernanceMatrix } from './GovernanceMatrix';
import { ModelPicker } from './ModelPicker';
import {
  useChangeRequests,
  useConditions,
  useGovernanceMatrix,
  useGovernanceAreas,
  useGovernanceDocuments,
  useCanSetModel,
  useGovernanceModel,
  useInvalidateGovernance,
  useLabelContext,
  usePeopleNames,
  useViewer,
} from './hooks';
import { catalogueNames } from './labels';
import { buildMatrix } from './matrix';

type Tab = 'matrix' | 'conditions' | 'model';

export function ProjectGovernancePage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const viewer = useViewer();
  const baseLabels = useLabelContext();
  const personName = usePeopleNames(projectId);
  const invalidate = useInvalidateGovernance(projectId);

  const modelQ = useGovernanceModel(projectId);
  const canSetModel = useCanSetModel(projectId);
  const hasModel = !!modelQ.data;
  const areasQ = useGovernanceAreas(projectId, hasModel);
  const docsQ = useGovernanceDocuments(projectId, hasModel);
  const crQ = useChangeRequests(projectId, hasModel);
  const conditionsQ = useConditions(projectId, hasModel);
  const matrixQ = useGovernanceMatrix(projectId, hasModel);
  const next = useMemo(() => {
    const id = matrixQ.data?.next_gate?.id;
    return id ? (matrixQ.data?.gates.find((g) => g.id === id) ?? null) : null;
  }, [matrixQ.data]);

  const tab = (params.get('tab') as Tab | null) ?? 'matrix';
  const gateId = params.get('gate');
  const areaId = params.get('area');
  const go = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: false });
  };

  // Rows that carry only a code (conditions, blockers, at-risk areas) are named from the labels
  // the API sent with the model's phases, gates, areas and document types.
  const labels = useMemo(
    () => ({
      ...baseLabels,
      names: catalogueNames({
        phase: modelQ.data?.phases,
        gate: matrixQ.data?.gates,
        area: areasQ.data,
        doc: (areasQ.data ?? []).flatMap((a) => a.document_types ?? []),
      }),
    }),
    [baseLabels, modelQ.data, matrixQ.data, areasQ.data],
  );

  const matrix = useMemo(
    () =>
      modelQ.data && matrixQ.data
        ? buildMatrix({
            phases: modelQ.data.phases,
            currentPhase: modelQ.data.current_phase,
            matrix: matrixQ.data,
          })
        : null,
    [modelQ.data, matrixQ.data],
  );

  const openConditions = (conditionsQ.data ?? []).filter((c) => c.status === 'open' || c.status === 'overdue').length;

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName || t('governance.project.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('governance.project.title', { defaultValue: 'Project governance' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">
          {t('governance.project.title', { defaultValue: 'Project governance' })}
        </h1>
        <p className="text-sm text-content-secondary">
          {t('governance.project.subtitle', {
            defaultValue: 'Phases, gates, frame documents and who owns each management area.',
          })}
        </p>
      </div>
      <CollapsibleSection
        storageKey="project_governance.how"
        icon={<Compass className="h-4 w-4" />}
        title={t('governance.project.how_title', { defaultValue: 'How project governance works' })}
        subtitle={t('governance.project.how_subtitle', {
          defaultValue: 'Phase model, owners, frame documents, gate decision',
        })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{t('governance.project.how_step_1', { defaultValue: 'Choose the phase model the project runs through. It brings the phases, the gates between them and the management areas.' })}</li>
          <li>{t('governance.project.how_step_2', { defaultValue: 'Name an owner for every area. The owner keeps its frame documents in the CDE and confirms readiness at each gate.' })}</li>
          <li>{t('governance.project.how_step_3', { defaultValue: 'Prepare the next gate and submit it for review once the blockers are cleared.' })}</li>
          <li>{t('governance.project.how_step_4', { defaultValue: 'The entitled decider records go, go with conditions, hold, recycle or stop. Approved documents become binding and change only through a change request.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (modelQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <SkeletonTable rows={6} columns={6} />
      </div>
    );
  }
  if (modelQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <ErrorState
          title={t('governance.project.load_failed', { defaultValue: 'Project governance could not be loaded' })}
          hint={getErrorMessage(modelQ.error)}
          onRetry={() => modelQ.refetch()}
        />
      </div>
    );
  }

  const model = modelQ.data;
  if (!model) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <EmptyState
          icon={<Layers size={28} />}
          title={t('governance.project.empty_model_title', { defaultValue: 'No phase model yet' })}
          description={t('governance.project.empty_model_body', {
            defaultValue: 'Choose the phase model this project runs through. Its phases, gates and management areas appear here right after.',
          })}
        />
        <ModelPicker projectId={projectId} model={null} canSet={canSetModel} gates={[]} labels={labels} onDone={invalidate} />
      </div>
    );
  }

  const listsLoading = matrixQ.isLoading;
  const listsError = matrixQ.error;
  const selectedArea = areaId ? (areasQ.data ?? []).find((a) => a.id === areaId) ?? null : null;

  let body: ReactNode;
  if (gateId) {
    body = (
      <GatePanel
        projectId={projectId}
        gateId={gateId}
        model={model}
        viewer={viewer}
        labels={labels}
        personName={personName}
        onBack={() => go({ gate: null })}
        onOpenArea={(id) => go({ gate: null, area: id })}
        onOpenModel={() => go({ gate: null, tab: 'model' })}
      />
    );
  } else if (areaId && selectedArea) {
    body = (
      <AreaPanel
        key={selectedArea.id}
        projectId={projectId}
        area={selectedArea}
        model={model}
        documents={docsQ.data ?? []}
        documentsLoading={docsQ.isLoading}
        documentsError={docsQ.isError ? docsQ.error : null}
        onRetryDocuments={() => docsQ.refetch()}
        changeRequests={crQ.data ?? []}
        gates={matrixQ.data?.gates ?? []}
        labels={labels}
        personName={personName}
        onBack={() => go({ area: null })}
      />
    );
  } else if (areaId) {
    // The link names an area that has not arrived, could not be loaded or is not in this project.
    const back = (
      <Button size="sm" variant="ghost" icon={<ArrowLeft size={14} />} onClick={() => go({ area: null })}>
        {t('governance.project.back_to_matrix', { defaultValue: 'Back to matrix' })}
      </Button>
    );
    body = (
      <div className="space-y-4" data-testid="area-unavailable">
        {back}
        {areasQ.isLoading ? (
          <SkeletonTable rows={4} columns={2} />
        ) : areasQ.isError ? (
          <ErrorState
            title={t('governance.project.area.load_failed', { defaultValue: 'The management area could not be loaded' })}
            hint={getErrorMessage(areasQ.error)}
            onRetry={() => areasQ.refetch()}
          />
        ) : (
          <EmptyState
            icon={<Grid3x3 size={28} />}
            title={t('governance.project.area.not_found_title', { defaultValue: 'This management area is not part of the project' })}
            description={t('governance.project.area.not_found_body', {
              defaultValue: 'It may belong to an earlier phase model. Go back to the matrix and open an area from there.',
            })}
          />
        )}
      </div>
    );
  } else if (tab === 'model') {
    body = (
      <ModelPicker
        projectId={projectId}
        model={model}
        gates={matrixQ.data?.gates ?? []}
        labels={labels}
        onDone={invalidate}
      />
    );
  } else if (tab === 'conditions') {
    body = conditionsQ.isLoading ? (
      <SkeletonTable rows={4} columns={4} />
    ) : conditionsQ.isError ? (
      <ErrorState
        title={t('governance.project.conditions.load_failed', { defaultValue: 'The conditions could not be loaded' })}
        hint={getErrorMessage(conditionsQ.error)}
        onRetry={() => conditionsQ.refetch()}
      />
    ) : (
      <ConditionsRegister
        projectId={projectId}
        conditions={conditionsQ.data ?? []}
        catalogueId={model.catalogue_id}
        labels={labels}
        personName={personName}
        onChanged={invalidate}
      />
    );
  } else if (listsLoading) {
    body = <SkeletonTable rows={6} columns={6} />;
  } else if (listsError) {
    body = (
      <ErrorState
        title={t('governance.project.load_failed', { defaultValue: 'Project governance could not be loaded' })}
        hint={getErrorMessage(listsError)}
        onRetry={invalidate}
      />
    );
  } else if (!matrix || matrix.rows.length === 0) {
    body = (
      <EmptyState
        icon={<Grid3x3 size={28} />}
        title={t('governance.project.empty_areas_title', { defaultValue: 'No management areas yet' })}
        description={t('governance.project.empty_areas_body', {
          defaultValue: 'The phase model brings no management areas for this project. Choose a phase model that defines them on the Phase model tab.',
        })}
        action={{
          label: t('governance.project.tab_model', { defaultValue: 'Phase model' }),
          onClick: () => go({ tab: 'model' }),
        }}
      />
    );
  } else {
    body = (
      <GovernanceMatrix
        data={matrix}
        catalogueId={model.catalogue_id}
        next={next}
        blockerCount={matrixQ.data?.next_gate?.blocker_count ?? 0}
        labels={labels}
        personName={personName}
        onOpenGate={(id) => go({ gate: id })}
        onOpenArea={(id) => go({ area: id })}
      />
    );
  }

  return (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="project-governance-page">
      {header}
      {model.stopped && (
        <div role="status" className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-4 py-2 text-sm text-content-primary">
          {t('governance.project.stopped_banner', {
            defaultValue: 'This project was stopped at a gate. Its frame documents are read-only.',
          })}
        </div>
      )}
      {!gateId && !areaId && (
        <TabBar<Tab>
          ariaLabel={t('governance.project.tabs', { defaultValue: 'Project governance sections' })}
          activeId={tab}
          onChange={(id) => go({ tab: id === 'matrix' ? null : id })}
          idPrefix="project-governance"
          tabs={[
            { id: 'matrix', label: t('governance.project.tab_matrix', { defaultValue: 'Matrix' }), icon: <Grid3x3 size={14} /> },
            {
              id: 'conditions',
              label: t('governance.project.tab_conditions', { defaultValue: 'Conditions' }),
              icon: <ClipboardList size={14} />,
              badge: openConditions > 0 ? openConditions : undefined,
            },
            { id: 'model', label: t('governance.project.tab_model', { defaultValue: 'Phase model' }), icon: <Layers size={14} /> },
          ]}
        />
      )}
      {body}
    </div>
  );
}
