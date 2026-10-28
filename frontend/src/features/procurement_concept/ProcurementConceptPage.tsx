// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Procurement concept, mounted at /projects/:projectId/procurement-concept.
//
// The package board is the home view: one row per contract package with its
// value, threshold, procedure and award date. Prequalification, market
// sounding, the award schedule, the company's framework agreements and the
// concept record sit behind tabs, and the URL remembers the tab and the
// package (?tab=, ?package=), so a link reopens the same view.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useParams, useSearchParams } from 'react-router-dom';
import { Boxes, Calendar, ClipboardList, Compass, FileText, MessageSquare, Users } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';

import { AwardSchedule } from './AwardSchedule';
import { ConceptDialog } from './ConceptDialog';
import { ConceptRecord } from './ConceptRecord';
import { Frameworks } from './Frameworks';
import {
  refusalText,
  useCatalogues,
  useConcept,
  useFindings,
  useFrameworks,
  useInvalidateProcurement,
  useLabelContext,
  usePackages,
  usePinnedCatalogue,
  useProfiles,
  useProjectFrameworks,
  useSchedule,
  useSoundings,
} from './hooks';
import { CONCEPT_STATE, vocab } from './labels';
import { MarketSoundings } from './MarketSoundings';
import { PackageBoard } from './PackageBoard';
import { PermitLotRequirementsSection } from './PermitLotRequirementsSection';
import { PackageDialog } from './PackageDialog';
import { PrequalPanel } from './PrequalPanel';
import { CONCEPT_TONE, ToneBadge } from './ProcurementBits';
import { splitFindings } from './rules';

type Tab = 'packages' | 'prequalification' | 'market' | 'schedule' | 'frameworks' | 'record';
const TABS: Tab[] = ['packages', 'prequalification', 'market', 'schedule', 'frameworks', 'record'];

export function ProcurementConceptPage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const labels = useLabelContext();
  const invalidate = useInvalidateProcurement(projectId);
  const [conceptDialog, setConceptDialog] = useState(false);
  const [planning, setPlanning] = useState<string | null>(null);

  const conceptQ = useConcept(projectId);
  const has = !!conceptQ.data;
  const rawTab = params.get('tab') as Tab | null;
  const tab: Tab = rawTab && TABS.includes(rawTab) ? rawTab : 'packages';

  const packagesQ = usePackages(projectId, has);
  const findingsQ = useFindings(projectId, has);
  const catalogueQ = usePinnedCatalogue(projectId, has);
  const profilesQ = useProfiles(projectId, has);
  // The company's agreements for the Frameworks tab; the ones this project may call off for the package plan.
  const frameworksQ = useFrameworks(has && tab === 'frameworks');
  const callOffQ = useProjectFrameworks(projectId, has);
  const soundingsQ = useSoundings(projectId, has && tab === 'market');
  const scheduleQ = useSchedule(projectId, has && tab === 'schedule');
  const cataloguesQ = useCatalogues(conceptDialog);

  const go = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: false });
  };

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName || t('procurement_concept.ui.page.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('procurement_concept.nav.title', { defaultValue: 'Procurement concept' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">
          {t('procurement_concept.nav.title', { defaultValue: 'Procurement concept' })}
        </h1>
        <p className="text-sm text-content-secondary">
          {t('procurement_concept.ui.page.subtitle', {
            defaultValue: 'How each contract package is awarded: its value, the procedure, the bidders and the dates.',
          })}
        </p>
      </div>
      <CollapsibleSection
        storageKey="procurement_concept.how"
        icon={<Compass className="h-4 w-4" />}
        title={t('procurement_concept.ui.page.how_title', { defaultValue: 'How the procurement concept works' })}
        subtitle={t('procurement_concept.ui.page.how_subtitle', {
          defaultValue: 'Rules, package plan, bidders, dates, approval',
        })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{t('procurement_concept.ui.page.how_step_1', { defaultValue: 'Say which procurement law applies and what kind of client the project has. That fixes the thresholds and the procedures.' })}</li>
          <li>{t('procurement_concept.ui.page.how_step_2', { defaultValue: 'Give every contract package an estimated value, a procedure and the date it is needed on site. The value is tested against the thresholds as you go.' })}</li>
          <li>{t('procurement_concept.ui.page.how_step_3', { defaultValue: 'Sound out the market, collect candidates per package and confirm the short list once it meets the rules.' })}</li>
          <li>{t('procurement_concept.ui.page.how_step_4', { defaultValue: 'Confirm the award milestones, then submit the concept for the gate. The governance gate approves it, and each package then continues in tendering.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (conceptQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <SkeletonTable rows={6} columns={6} />
      </div>
    );
  }
  if (conceptQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <ErrorState
          title={t('procurement_concept.ui.page.load_failed', { defaultValue: 'The procurement concept could not be loaded' })}
          hint={refusalText(labels.t, conceptQ.error)}
          onRetry={() => conceptQ.refetch()}
        />
      </div>
    );
  }

  const concept = conceptQ.data ?? null;
  const conceptDialogNode = conceptDialog && (
    <ConceptDialog
      open
      onClose={() => setConceptDialog(false)}
      projectId={projectId}
      concept={concept}
      catalogues={cataloguesQ.data ?? []}
      cataloguesLoading={cataloguesQ.isLoading}
      labels={labels}
      onSaved={invalidate}
    />
  );

  if (!concept) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="procurement-concept-page">
        {header}
        <EmptyState
          icon={<ClipboardList size={28} />}
          title={t('procurement_concept.empty.no_concept', { defaultValue: 'No procurement concept yet.' })}
          description={t('procurement_concept.ui.page.empty_body', {
            defaultValue:
              'Start by choosing the rule catalogue, then say which procurement law applies and whether the client is a public body. The contract packages of the delivery model then appear here, ready to get a value, a procedure and a date.',
          })}
          action={
            <Button onClick={() => setConceptDialog(true)} data-testid="concept-start">
              {t('procurement_concept.ui.concept.start', { defaultValue: 'Start concept' })}
            </Button>
          }
        />
        {conceptDialogNode}
      </div>
    );
  }

  const packages = packagesQ.data ?? [];
  const blocking = splitFindings(findingsQ.data ?? []).blocking.length;
  const planningView = planning ? (packages.find((p) => p.contract_package.id === planning) ?? null) : null;
  const packageCodes = new Map(packages.map((p) => [p.contract_package.code, p.contract_package.title]));
  const refLabel = (ref: string) => {
    const title = packageCodes.get(ref);
    return title ? `${ref} ${title}` : ref;
  };

  const loading = (q: { isLoading: boolean }) => (q.isLoading ? <SkeletonTable rows={5} columns={5} /> : null);
  const failed = (q: { isError: boolean; error: unknown; refetch: () => unknown }, title: string) =>
    q.isError ? <ErrorState title={title} hint={refusalText(labels.t, q.error)} onRetry={() => q.refetch()} /> : null;
  const packagesFailed = t('procurement_concept.ui.page.packages_failed', { defaultValue: 'The packages could not be loaded' });

  let body: ReactNode;
  if (tab === 'record') {
    body = (
      <ConceptRecord
        projectId={projectId}
        concept={concept}
        findings={findingsQ.data ?? []}
        findingsLoading={findingsQ.isLoading}
        labels={labels}
        refLabel={refLabel}
        onEdit={() => setConceptDialog(true)}
        onChanged={invalidate}
      />
    );
  } else if (tab === 'frameworks') {
    body = loading(frameworksQ) ??
      failed(frameworksQ, t('procurement_concept.ui.page.frameworks_failed', { defaultValue: 'The framework agreements could not be loaded' })) ?? (
        <Frameworks frameworks={frameworksQ.data?.items ?? []} canCreate={frameworksQ.data?.can?.create} labels={labels} onChanged={invalidate} />
      );
  } else if (tab === 'market') {
    body = loading(soundingsQ) ??
      failed(soundingsQ, t('procurement_concept.ui.page.soundings_failed', { defaultValue: 'The market soundings could not be loaded' })) ?? (
        <MarketSoundings projectId={projectId} soundings={soundingsQ.data?.items ?? []} can={soundingsQ.data?.can} packages={packages} labels={labels} onChanged={invalidate} />
      );
  } else if (tab === 'schedule') {
    body =
      loading(scheduleQ) ??
      failed(scheduleQ, t('procurement_concept.ui.page.schedule_failed', { defaultValue: 'The award schedule could not be loaded' })) ??
      (scheduleQ.data ? (
        <AwardSchedule
          projectId={projectId}
          concept={concept}
          schedule={scheduleQ.data}
          labels={labels}
          onGoToPackages={() => go({ tab: null })}
          onChanged={invalidate}
        />
      ) : null);
  } else if (tab === 'prequalification') {
    body = loading(packagesQ) ?? failed(packagesQ, packagesFailed) ?? (
      <PrequalPanel
        projectId={projectId}
        concept={concept}
        packages={packages}
        profiles={profilesQ.data?.items ?? []}
        profileCreate={profilesQ.data?.can?.create}
        catalogue={catalogueQ.data ?? null}
        packageId={params.get('package')}
        labels={labels}
        onSelectPackage={(id) => go({ package: id })}
        onGoToPackages={() => go({ tab: null, package: null })}
        onChanged={invalidate}
      />
    );
  } else {
    body = loading(packagesQ) ?? failed(packagesQ, packagesFailed) ?? (
      <div className="space-y-4">
        <PackageBoard
          projectId={projectId}
          concept={concept}
          packages={packages}
          labels={labels}
          onPlan={setPlanning}
          onCandidates={(id) => go({ tab: 'prequalification', package: id })}
          onChanged={invalidate}
        />
        <PermitLotRequirementsSection projectId={projectId} />
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="procurement-concept-page">
      {header}
      <div className="flex flex-wrap items-center gap-3 text-sm" data-testid="concept-summary">
        <ToneBadge tone={CONCEPT_TONE[concept.state]} testId="concept-state-badge">
          {vocab(labels.t, CONCEPT_STATE, concept.state)}
        </ToneBadge>
        {findingsQ.data && (
          <button
            type="button"
            className={blocking > 0 ? 'text-semantic-error underline' : 'text-content-secondary underline'}
            onClick={() => go({ tab: 'record' })}
            data-testid="concept-blocking"
          >
            {blocking > 0
              ? t('procurement_concept.ui.page.blocking', { defaultValue: 'Blocking approval: {{n}}', n: blocking })
              : t('procurement_concept.ui.page.nothing_blocking', { defaultValue: 'Nothing blocks approval' })}
          </button>
        )}
      </div>
      <TabBar<Tab>
        ariaLabel={t('procurement_concept.ui.page.tabs', { defaultValue: 'Procurement concept sections' })}
        activeId={tab}
        onChange={(id) => go({ tab: id === 'packages' ? null : id })}
        idPrefix="procurement-concept"
        tabs={[
          { id: 'packages', label: t('procurement_concept.tabs.packages', { defaultValue: 'Packages' }), icon: <Boxes size={14} /> },
          { id: 'prequalification', label: t('procurement_concept.tabs.prequalification', { defaultValue: 'Prequalification' }), icon: <Users size={14} /> },
          { id: 'market', label: t('procurement_concept.tabs.market', { defaultValue: 'Market sounding' }), icon: <MessageSquare size={14} /> },
          { id: 'schedule', label: t('procurement_concept.tabs.schedule', { defaultValue: 'Award schedule' }), icon: <Calendar size={14} /> },
          { id: 'frameworks', label: t('procurement_concept.tabs.frameworks', { defaultValue: 'Frameworks' }), icon: <FileText size={14} /> },
          {
            id: 'record',
            label: t('procurement_concept.tabs.record', { defaultValue: 'Concept record' }),
            icon: <ClipboardList size={14} />,
            badge: blocking > 0 ? blocking : undefined,
          },
        ]}
      />
      {body}
      {planningView && (
        <PackageDialog
          key={`${planningView.contract_package.id}-${planningView.award ? 'planned' : 'new'}`}
          open
          onClose={() => setPlanning(null)}
          projectId={projectId}
          view={planningView}
          catalogue={catalogueQ.data ?? null}
          frameworks={callOffQ.data ?? []}
          profiles={profilesQ.data?.items ?? []}
          labels={labels}
          onSaved={(first) => {
            invalidate();
            // After the first save the dialog stays: the threshold check and the procedures it allows are now there.
            if (!first) setPlanning(null);
          }}
        />
      )}
      {conceptDialogNode}
    </div>
  );
}
