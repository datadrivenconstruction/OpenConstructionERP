// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The delivery model of a project, mounted at /projects/:projectId/delivery.
//
// Five tabs follow the order the work is done in: compare the forms, allocate
// the risks, cut the work into packages, list what the owner supplies itself,
// and read the decision record. The URL remembers the tab (?tab=), so a link
// reopens the same screen.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useParams, useSearchParams } from 'react-router-dom';
import { Boxes, Compass, FileSignature, FileText, Handshake, PackageOpen, Scale, ShieldAlert } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { getErrorMessage } from '@/shared/lib/api';

import { canChangeCatalogue } from './access';
import { ChangeCatalogueDialog, StartModel } from './CataloguePicker';
import { ComparisonPanel } from './ComparisonPanel';
import { DecisionRecordPanel } from './DecisionRecordPanel';
import { MODEL_TONE, ToneBadge } from './DeliveryBits';
import {
  useAllocations,
  useComparison,
  useConsistency,
  useDecisions,
  useDeliveryModel,
  useInvalidateDelivery,
  useLabelContext,
  useContractItems,
  useOfi,
  usePackages,
  usePersonName,
  usePinnedCatalogue,
  useReadiness,
  useViewer,
} from './hooks';
import { MODEL_STATUS, catalogueText, formName, vocab } from './labels';
import { ContractPanel } from './ContractPanel';
import { OfiPanel } from './OfiPanel';
import { PackagePlanPanel } from './PackagePlanPanel';
import { RiskMatrixPanel } from './RiskMatrixPanel';

type Tab = 'comparison' | 'risks' | 'packages' | 'ofi' | 'contracts' | 'decision';
const TABS: Tab[] = ['comparison', 'risks', 'packages', 'ofi', 'contracts', 'decision'];

export function DeliveryModelPage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const viewer = useViewer();
  const labels = useLabelContext();
  const personName = usePersonName();
  const invalidate = useInvalidateDelivery(projectId);
  const [changingCatalogue, setChangingCatalogue] = useState(false);

  const requested = params.get('tab') as Tab | null;
  const tab: Tab = requested && TABS.includes(requested) ? requested : 'comparison';
  const openTab = (next: Tab) => {
    const p = new URLSearchParams(params);
    if (next === 'comparison') p.delete('tab');
    else p.set('tab', next);
    setParams(p, { replace: false });
  };

  const modelQ = useDeliveryModel(projectId);
  const hasModel = !!modelQ.data;
  const catalogueQ = usePinnedCatalogue(projectId, hasModel);
  const comparisonQ = useComparison(projectId, hasModel && (tab === 'comparison' || tab === 'decision'));
  const allocationsQ = useAllocations(projectId, hasModel && tab === 'risks');
  const packagesQ = usePackages(projectId, hasModel);
  const consistencyQ = useConsistency(projectId, hasModel && tab === 'packages');
  const ofiQ = useOfi(projectId, hasModel && tab === 'ofi');
  const contractQ = useContractItems(projectId, hasModel && tab === 'contracts');
  const decisionsQ = useDecisions(projectId, hasModel && tab === 'decision');
  const readinessQ = useReadiness(projectId, hasModel && tab === 'decision');

  // Reading the model or the decisions lets the server catch up with
  // governance, so the status can move without anyone pressing a button here.
  // Everything read under the old status is then read again.
  const status = modelQ.data?.status;
  const seenStatus = useRef(status);
  useEffect(() => {
    if (seenStatus.current && status && seenStatus.current !== status) void invalidate();
    seenStatus.current = status;
  }, [status, invalidate]);
  const currentDecision = decisionsQ.data?.find((d) => d.is_current);
  const caughtUp = useRef<string | null>(null);
  useEffect(() => {
    if (!currentDecision || currentDecision.status !== 'approved' || status !== 'proposed') return;
    // once per decision, so a model that stays behind cannot loop the refetch
    if (caughtUp.current === currentDecision.id) return;
    caughtUp.current = currentDecision.id;
    void invalidate();
  }, [currentDecision, status, invalidate]);

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName || t('delivery_model.ui.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('delivery_model.ui.title', { defaultValue: 'Delivery model' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{t('delivery_model.ui.title', { defaultValue: 'Delivery model' })}</h1>
        <p className="text-sm text-content-secondary">
          {t('delivery_model.ui.subtitle', {
            defaultValue: 'How the project is contracted: who designs, who builds, who carries which risk and how the work is split into packages.',
          })}
        </p>
      </div>
      <CollapsibleSection
        storageKey="delivery_model.how"
        icon={<Compass className="h-4 w-4" />}
        title={t('delivery_model.ui.how_title', { defaultValue: 'How the delivery model works' })}
        subtitle={t('delivery_model.ui.how_subtitle', { defaultValue: 'Compare, decide, allocate risks, plan packages' })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{t('delivery_model.ui.how_step_1', { defaultValue: 'Add the forms the project could be delivered under and score each one against weighted criteria.' })}</li>
          <li>{t('delivery_model.ui.how_step_2', { defaultValue: 'Propose the form that fits best, with the reasons. It is approved in governance, at the gate of the frame document that carries it.' })}</li>
          <li>{t('delivery_model.ui.how_step_3', { defaultValue: 'Confirm who carries each risk. The usual split of the chosen form is the starting point.' })}</li>
          <li>{t('delivery_model.ui.how_step_4', { defaultValue: 'Cut the work into packages, link each one to its tender or contract, and list what the owner supplies itself.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (modelQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <SkeletonTable rows={6} columns={5} />
      </div>
    );
  }
  if (modelQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <ErrorState
          title={t('delivery_model.ui.load_failed', { defaultValue: 'The delivery model could not be loaded' })}
          hint={getErrorMessage(modelQ.error)}
          onRetry={() => modelQ.refetch()}
        />
      </div>
    );
  }

  const model = modelQ.data;
  if (!model) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="delivery-model-page">
        {header}
        <EmptyState
          icon={<Handshake size={28} />}
          title={t('delivery_model.ui.empty_model_title', { defaultValue: 'No delivery model yet' })}
          description={t('delivery_model.ui.empty_model_body', {
            defaultValue: 'Start by choosing the catalogue of delivery forms. After that you compare the forms and propose one for this project.',
          })}
        />
        <StartModel projectId={projectId} viewer={viewer} labels={labels} onDone={invalidate} />
      </div>
    );
  }

  const catalogue = catalogueQ.data ?? null;
  const packages = packagesQ.data ?? [];

  const loading = <SkeletonTable rows={6} columns={5} />;
  const failed = (error: unknown, retry: () => void) => (
    <ErrorState
      title={t('delivery_model.ui.section_failed', { defaultValue: 'This part of the delivery model could not be loaded' })}
      hint={getErrorMessage(error)}
      onRetry={retry}
    />
  );

  let body: ReactNode;
  if (tab === 'risks') {
    body = allocationsQ.isError ? (
      failed(allocationsQ.error, () => allocationsQ.refetch())
    ) : !allocationsQ.data ? (
      loading
    ) : (
      <RiskMatrixPanel
        projectId={projectId}
        model={model}
        matrix={allocationsQ.data}
        catalogue={catalogue}
        labels={labels}
        onChanged={invalidate}
      />
    );
  } else if (tab === 'packages') {
    body = packagesQ.isError ? (
      failed(packagesQ.error, () => packagesQ.refetch())
    ) : !packagesQ.data ? (
      loading
    ) : (
      <PackagePlanPanel
        projectId={projectId}
        model={model}
        packages={packages}
        consistency={consistencyQ.data ?? null}
        catalogue={catalogue}
        labels={labels}
        onChanged={invalidate}
      />
    );
  } else if (tab === 'ofi') {
    body = ofiQ.isError ? (
      failed(ofiQ.error, () => ofiQ.refetch())
    ) : !ofiQ.data ? (
      loading
    ) : (
      <OfiPanel projectId={projectId} model={model} items={ofiQ.data} packages={packages} labels={labels} onChanged={invalidate} />
    );
  } else if (tab === 'contracts') {
    body = contractQ.isError ? (
      failed(contractQ.error, () => contractQ.refetch())
    ) : !contractQ.data ? (
      loading
    ) : (
      <ContractPanel
        projectId={projectId}
        model={model}
        items={contractQ.data}
        packages={packages}
        catalogue={catalogue}
        labels={labels}
        onChanged={invalidate}
      />
    );
  } else if (tab === 'decision') {
    body = decisionsQ.isError ? (
      failed(decisionsQ.error, () => decisionsQ.refetch())
    ) : !decisionsQ.data ? (
      loading
    ) : (
      <DecisionRecordPanel
        projectId={projectId}
        model={model}
        decisions={decisionsQ.data}
        readiness={readinessQ.data ?? null}
        labels={labels}
        personName={personName}
        onChanged={invalidate}
        onOpenComparison={() => openTab('comparison')}
      />
    );
  } else {
    body = comparisonQ.isError ? (
      failed(comparisonQ.error, () => comparisonQ.refetch())
    ) : !comparisonQ.data ? (
      loading
    ) : (
      <ComparisonPanel
        projectId={projectId}
        model={model}
        comparison={comparisonQ.data}
        catalogue={catalogue}
        packages={packages}
        labels={labels}
        onChanged={invalidate}
      />
    );
  }

  const catalogueSummaryName = catalogue ? catalogueText(labels, { key: catalogue.name_key, texts: catalogue.labels, code: catalogue.id }) : '';

  return (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="delivery-model-page">
      {header}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-border bg-surface-elevated shadow-sm px-4 py-3" data-testid="model-strip">
        <ToneBadge tone={MODEL_TONE[model.status]} testId="model-status">
          {vocab(labels.t, MODEL_STATUS, model.status)}
        </ToneBadge>
        <span className="text-sm">
          <span className="text-content-tertiary">{t('delivery_model.ui.strip.form', { defaultValue: 'Delivery form' })}</span>{' '}
          <span className="font-medium text-content-primary" data-testid="model-form">
            {model.selected_form_code
              ? formName(labels, model.selected_form, model.selected_form_code)
              : t('delivery_model.ui.strip.no_form', { defaultValue: 'Not chosen yet' })}
          </span>
        </span>
        {catalogueSummaryName && (
          <span className="text-sm">
            <span className="text-content-tertiary">{t('delivery_model.ui.strip.catalogue', { defaultValue: 'Catalogue' })}</span>{' '}
            <span className="text-content-primary">{catalogueSummaryName}</span>
          </span>
        )}
        {!canChangeCatalogue(model) && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setChangingCatalogue(true)} data-testid="change-catalogue-button">
            {t('delivery_model.ui.catalogue.change_title', { defaultValue: 'Use another catalogue' })}
          </Button>
        )}
      </div>
      <TabBar<Tab>
        ariaLabel={t('delivery_model.ui.tabs', { defaultValue: 'Delivery model sections' })}
        activeId={tab}
        onChange={openTab}
        idPrefix="delivery-model"
        tabs={[
          { id: 'comparison', label: t('delivery_model.ui.tab.comparison', { defaultValue: 'Compare forms' }), icon: <Scale size={14} /> },
          { id: 'risks', label: t('delivery_model.ui.tab.risks', { defaultValue: 'Risk allocation' }), icon: <ShieldAlert size={14} /> },
          {
            id: 'packages',
            label: t('delivery_model.ui.tab.packages', { defaultValue: 'Package plan' }),
            icon: <Boxes size={14} />,
            badge: packages.length > 0 ? packages.length : undefined,
          },
          { id: 'ofi', label: t('delivery_model.ui.tab.ofi', { defaultValue: 'Owner-furnished items' }), icon: <PackageOpen size={14} /> },
          { id: 'contracts', label: t('delivery_model.ui.tab.contracts', { defaultValue: 'Contract side' }), icon: <FileText size={14} /> },
          { id: 'decision', label: t('delivery_model.ui.tab.decision', { defaultValue: 'Decision record' }), icon: <FileSignature size={14} /> },
        ]}
      />
      {body}
      {changingCatalogue && (
        <ChangeCatalogueDialog
          open
          onClose={() => setChangingCatalogue(false)}
          projectId={projectId}
          model={model}
          pinned={catalogue}
          labels={labels}
          onDone={invalidate}
        />
      )}
    </div>
  );
}
