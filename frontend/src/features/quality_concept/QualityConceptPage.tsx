// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project quality concept, mounted at /projects/:projectId/quality-concept.
//
// The concept tab is the home view: it says where the concept stands and what
// still stops it. Certification, proofs, commissioning stages, acceptance and
// evidence preservation sit behind tabs, and the URL remembers the tab.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useParams, useSearchParams } from 'react-router-dom';
import { Award, Camera, CheckCircle2, CircleAlert, ClipboardCheck, Compass, FileCheck2, Handshake, Layers } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';

import { AcceptancePanel } from './AcceptancePanel';
import { createConcept, isConceptMissing } from './api';
import { CertificationPanel } from './CertificationPanel';
import { ConceptPanel } from './ConceptPanel';
import {
  useCatalogue,
  useConcept,
  useLabelContext,
  usePeopleNames,
  useQcWrite,
  useReadiness,
  useValidation,
} from './hooks';
import { GATE_DETAIL, humanizeCode, vocab, type TFn } from './labels';
import { QC_TABS, type PanelProps, type QcTab } from './panel';
import { PreservationPanel } from './PreservationPanel';
import { ProofsPanel } from './ProofsPanel';
import { RefusalNote } from './QualityBits';
import { conceptEditable } from './rules';
import { StagesPanel } from './StagesPanel';

/** One fact of the readiness strip: met, or not yet. */
function Fact({ met, children, testId }: { met: boolean; children: ReactNode; testId: string }) {
  const Icon = met ? CheckCircle2 : CircleAlert;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-content-primary" data-testid={testId} data-met={met}>
      <Icon size={14} aria-hidden className={met ? 'text-semantic-success' : 'text-semantic-warning'} />
      {children}
    </span>
  );
}

/**
 * What the governance gate reads from this module: is the concept complete,
 * is it approved, and is evidence preservation planned for everything the
 * works can affect. Below it, the validation rules that currently fail.
 */
function ReadinessStrip({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const readiness = useReadiness(projectId);
  const validation = useValidation(projectId);
  const [open, setOpen] = useState(false);
  if (!readiness.data) return null;
  const r = readiness.data;
  const failed = (validation.data ?? []).filter((v) => !v.passed);

  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="readiness-strip">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <h2 className="text-xs font-semibold text-content-secondary">
          {t('qualityConcept.readiness.title', { defaultValue: 'Readiness' })}
        </h2>
        <Fact met={r.errors.length === 0} testId="ready-complete">
          {r.errors.length === 0
            ? t('qualityConcept.readiness.complete', { defaultValue: 'Concept complete' })
            : t('qualityConcept.readiness.incomplete', { defaultValue: 'Concept has open points: {{n}}', n: r.errors.length })}
        </Fact>
        <Fact met={r.approved} testId="ready-approved">
          {r.approved
            ? t('qualityConcept.readiness.approved', { defaultValue: 'Concept approved' })
            : t('qualityConcept.readiness.not_approved', { defaultValue: 'Concept not approved yet' })}
        </Fact>
        <Fact met={r.preservation_unplanned.length === 0} testId="ready-preservation">
          {r.preservation_unplanned.length === 0
            ? t('qualityConcept.readiness.preservation_ok', { defaultValue: 'Condition surveys planned' })
            : t('qualityConcept.readiness.preservation_open', {
                defaultValue: 'Subjects without a before survey: {{n}}',
                n: r.preservation_unplanned.length,
              })}
        </Fact>
        {failed.length > 0 && (
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setOpen((v) => !v)} aria-expanded={open} data-testid="checks-toggle">
            {t('qualityConcept.readiness.checks', { defaultValue: 'Checks that fail: {{n}}', n: failed.length })}
          </Button>
        )}
      </div>
      {r.gate_detail && (
        <p className="mt-2 text-sm text-content-primary" data-testid="gate-detail">
          {GATE_DETAIL[r.gate_detail]
            ? vocab(t as TFn, GATE_DETAIL, r.gate_detail)
            : t('qualityConcept.gate.other', {
                defaultValue: 'The governance gate cannot read this concept yet: {{reason}}',
                reason: humanizeCode(r.gate_detail),
              })}
        </p>
      )}
      {r.preservation_unplanned.length > 0 && (
        <p className="mt-2 text-sm text-content-primary" data-testid="unplanned-subjects">
          {t('qualityConcept.readiness.preservation_refs', {
            defaultValue: 'No before survey yet for: {{refs}}',
            refs: fmtList(r.preservation_unplanned),
          })}
        </p>
      )}
      {open && (
        <div className="mt-3 space-y-2">
          <ul className="space-y-1" data-testid="check-list">
            {failed.map((v, i) => (
              <li key={`${v.rule_id}:${v.element_ref ?? ''}:${i}`} className="text-sm">
                <span className="text-content-primary">{v.message}</span>
                {v.suggestion && <span className="text-content-secondary"> {v.suggestion}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export function QualityConceptPage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const labels = useLabelContext();
  const personName = usePeopleNames(projectId);

  const conceptQ = useConcept(projectId);
  const write = useQcWrite(projectId);
  const catalogueQ = useCatalogue(projectId, !!conceptQ.data);

  const requested = params.get('tab') as QcTab | null;
  const tab: QcTab = requested && QC_TABS.includes(requested) ? requested : 'concept';
  const openTab = (next: QcTab) => {
    const p = new URLSearchParams(params);
    if (next === 'concept') p.delete('tab');
    else p.set('tab', next);
    setParams(p, { replace: false });
  };

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName ?? t('qualityConcept.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('qualityConcept.title', { defaultValue: 'Quality concept' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">
          {t('qualityConcept.title', { defaultValue: 'Quality concept' })}
        </h1>
        <p className="text-sm text-content-secondary">
          {t('qualityConcept.subtitle', {
            defaultValue: 'What quality the project owes, how it is proven and how the works are accepted.',
          })}
        </p>
      </div>
      <CollapsibleSection
        storageKey="quality_concept.how"
        icon={<Compass className="h-4 w-4" />}
        title={t('qualityConcept.how_title', { defaultValue: 'How the quality concept works' })}
        subtitle={t('qualityConcept.how_subtitle', {
          defaultValue: 'Standards, proofs, commissioning stages, acceptance',
        })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>
            {t('qualityConcept.how_step_1', {
              defaultValue: 'Name the standards the works are built to and the work packages the concept covers.',
            })}
          </li>
          <li>
            {t('qualityConcept.how_step_2', {
              defaultValue:
                'Plan the proofs each package owes and link them to the records that deliver them: test results, checklists, documents.',
            })}
          </li>
          <li>
            {t('qualityConcept.how_step_3', {
              defaultValue:
                'Take every technical system through the commissioning stages. A stage is released at its hold point in construction control.',
            })}
          </li>
          <li>
            {t('qualityConcept.how_step_4', {
              defaultValue:
                'Plan the acceptances and, once the works are accepted, confirm what the acceptance sets in motion.',
            })}
          </li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (conceptQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <SkeletonTable rows={6} columns={5} />
      </div>
    );
  }
  if (conceptQ.isError && isConceptMissing(conceptQ.error)) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="quality-concept-missing">
        {header}
        <RefusalNote refusal={write.refusal} />
        <EmptyState
          icon={<FileCheck2 size={28} />}
          title={t('qualityConcept.missing_title', { defaultValue: 'This project has no quality concept yet' })}
          description={t('qualityConcept.missing_body', {
            defaultValue:
              'The quality concept says which standards apply, which proofs each work package owes, how the technical systems are commissioned and how the works are accepted. Create it, then start with the standards and the work packages. Until it exists, the governance gate counts the quality concept as not met.',
          })}
          action={{
            label: t('qualityConcept.create', { defaultValue: 'Create quality concept' }),
            onClick: () => write.send(() => createConcept(projectId)),
          }}
        />
      </div>
    );
  }
  if (conceptQ.isError || !conceptQ.data) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <ErrorState
          title={t('qualityConcept.load_failed', { defaultValue: 'The quality concept could not be loaded' })}
          hint={getErrorMessage(conceptQ.error)}
          onRetry={() => conceptQ.refetch()}
        />
      </div>
    );
  }

  const concept = conceptQ.data;
  const panel: PanelProps = {
    projectId,
    concept,
    catalogue: catalogueQ.data,
    labels,
    personName,
    editable: concept.can.edit_plan,
    manage: concept.can.manage,
    openTab,
  };
  const blocking = concept.findings.filter((f) => f.severity === 'error').length;

  let body: ReactNode;
  if (tab === 'certification') body = <CertificationPanel {...panel} />;
  else if (tab === 'proofs') body = <ProofsPanel {...panel} />;
  else if (tab === 'stages') body = <StagesPanel {...panel} />;
  else if (tab === 'acceptance') body = <AcceptancePanel {...panel} />;
  else if (tab === 'preservation') body = <PreservationPanel {...panel} />;
  else body = <ConceptPanel {...panel} />;

  return (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="quality-concept-page">
      {header}
      <ReadinessStrip projectId={projectId} />
      {!panel.editable && (
        <div role="status" data-testid="plan-locked" className="rounded-lg border border-border-light bg-surface-secondary px-4 py-2 text-sm text-content-primary">
          {conceptEditable(concept.state)
            ? t('qualityConcept.plan_manage_required', {
                defaultValue:
                  'Only a manager or the owner of the quality area can change the plan. You can still record progress on proofs, stages and acceptances.',
              })
            : t('qualityConcept.plan_locked', {
                defaultValue:
                  'The plan is closed for editing while the concept is in review or approved. Progress on proofs, stages and acceptances is still recorded.',
              })}
        </div>
      )}
      <TabBar<QcTab>
        ariaLabel={t('qualityConcept.tabs.label', { defaultValue: 'Quality concept sections' })}
        activeId={tab}
        onChange={openTab}
        idPrefix="quality-concept"
        tabs={[
          {
            id: 'concept',
            label: t('qualityConcept.tabs.concept', { defaultValue: 'Concept' }),
            icon: <FileCheck2 size={14} />,
            badge: blocking > 0 ? blocking : undefined,
          },
          { id: 'certification', label: t('qualityConcept.tabs.certification', { defaultValue: 'Certification' }), icon: <Award size={14} /> },
          { id: 'proofs', label: t('qualityConcept.tabs.proofs', { defaultValue: 'Proofs' }), icon: <ClipboardCheck size={14} /> },
          { id: 'stages', label: t('qualityConcept.tabs.stages', { defaultValue: 'Commissioning stages' }), icon: <Layers size={14} /> },
          { id: 'acceptance', label: t('qualityConcept.tabs.acceptance', { defaultValue: 'Acceptance' }), icon: <Handshake size={14} /> },
          { id: 'preservation', label: t('qualityConcept.tabs.preservation', { defaultValue: 'Evidence preservation' }), icon: <Camera size={14} /> },
        ]}
      />
      {body}
    </div>
  );
}
