// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Commitments and releases, mounted at /projects/:projectId/commitments.
//
// The matrix is the home view. An item opens in place and the URL remembers
// it (?item=), so a link reopens the same item. Abort exposure and the
// approval setup sit behind tabs.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useParams, useSearchParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { Compass, Download, Grid3x3, Plus, ShieldAlert, Stamp, Users } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { downloadMatrix, type Finding } from './api';
import { projectVerdict } from './access';
import { ReasonedButton } from './CommitmentBits';
import { CommitmentGrid } from './CommitmentGrid';
import { ExposurePanel } from './ExposurePanel';
import {
  useCommitmentItems,
  useCommitmentMatrix,
  useFindings,
  useInvalidateCommitments,
  useLabelContext,
  usePeopleNames,
  useCapabilities,
} from './hooks';
import { ItemDialog } from './ItemDialog';
import { ItemPanel } from './ItemPanel';
import { ENFORCEMENT, vocab } from './labels';
import { MatrixSettings, SetupPanel } from './SetupPanel';

type Tab = 'matrix' | 'exposure' | 'setup';

/** What the module's own checks found: over-release, passed decision dates, missing abort terms. */
export function FindingsList({ findings }: { findings: Finding[] }) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  return (
    <section className="rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg p-3" data-testid="findings">
      <h3 className="text-sm font-semibold text-content-primary">
        {t('commitment.findings.title', { defaultValue: 'To look at' })}
      </h3>
      <ul className="mt-1 space-y-1 text-sm">
        {findings.map((f, i) => (
          <li key={`${f.rule_id}-${f.element_ref ?? ''}-${i}`} data-testid="finding-row">
            <p className="text-content-primary">{f.message}</p>
            {f.suggestion && <p className="text-xs text-content-secondary">{f.suggestion}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function CommitmentReleasePage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const capsQ = useCapabilities(projectId);
  // Still loading reads as "checking"; a failed request reads as no answer, with a retry below.
  const can = capsQ.isError ? null : capsQ.data?.can;
  const labels = useLabelContext();
  const personName = usePeopleNames(projectId);
  const invalidate = useInvalidateCommitments(projectId);
  const addToast = useToastStore((s) => s.addToast);
  const [adding, setAdding] = useState(false);

  const matrixQ = useCommitmentMatrix(projectId);
  const hasMatrix = !!matrixQ.data;
  const itemsQ = useCommitmentItems(projectId, hasMatrix);
  const findingsQ = useFindings(projectId, hasMatrix);

  const tab = (params.get('tab') as Tab | null) ?? 'matrix';
  const itemId = params.get('item');
  const go = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: false });
  };

  const exportFile = useMutation({
    mutationFn: (format: 'pdf' | 'xlsx') => downloadMatrix(projectId, format),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName || t('commitment.page.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('commitment.page.title', { defaultValue: 'Commitments and releases' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">
          {t('commitment.page.title', { defaultValue: 'Commitments and releases' })}
        </h1>
        <p className="text-sm text-content-secondary">
          {t('commitment.page.subtitle', {
            defaultValue: 'What the project will commit money to, what is released so far, who approves and what an abort would cost.',
          })}
        </p>
      </div>
      <CollapsibleSection
        storageKey="commitment_release.how"
        icon={<Compass className="h-4 w-4" />}
        title={t('commitment.page.how_title', { defaultValue: 'How commitments and releases work' })}
        subtitle={t('commitment.page.how_subtitle', {
          defaultValue: 'Plan the item, request a release, the right tier approves, then award or sign',
        })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{t('commitment.page.how_step_1', { defaultValue: 'Add an item for each thing the project will commit money to: a works package, a long-lead order, a design appointment.' })}</li>
          <li>{t('commitment.page.how_step_2', { defaultValue: 'Request a release for the whole amount or for a first tranche. The amount and the type decide which tier has to approve.' })}</li>
          <li>{t('commitment.page.how_step_3', { defaultValue: 'The approver of that tier opens the item and approves or rejects the request. The item then shows the released amount.' })}</li>
          <li>{t('commitment.page.how_step_4', { defaultValue: 'Link the contract or order once it exists. An award or signing above the released amount is warned about or blocked, as set on the Approval setup tab.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (matrixQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <SkeletonTable rows={5} columns={7} />
      </div>
    );
  }
  if (matrixQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <ErrorState
          title={t('commitment.page.load_failed', { defaultValue: 'The commitments could not be loaded' })}
          hint={getErrorMessage(matrixQ.error)}
          onRetry={() => matrixQ.refetch()}
        />
      </div>
    );
  }

  const matrix = matrixQ.data;
  if (!matrix) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="commitment-release-page">
        {header}
        <EmptyState
          icon={<Stamp size={28} />}
          title={t('commitment.page.empty_matrix_title', { defaultValue: 'No commitment matrix yet' })}
          description={t('commitment.page.empty_matrix_body', {
            defaultValue: 'First choose who may approve up to which amount. After that you add the items the project will commit money to.',
          })}
        />
        {capsQ.isError && (
          <ErrorState
            compact
            title={t('commitment.page.capabilities_failed', {
              defaultValue: 'What you may do here could not be loaded, so every action is off',
            })}
            hint={getErrorMessage(capsQ.error)}
            onRetry={() => capsQ.refetch()}
          />
        )}
        <MatrixSettings projectId={projectId} matrix={null} can={can} labels={labels} onSaved={invalidate} />
      </div>
    );
  }

  const items = itemsQ.data?.items ?? [];
  const selected = itemId ? items.find((i) => i.id === itemId) ?? null : null;
  const addV = projectVerdict(can, 'add_item');

  let body: ReactNode;
  if (itemId) {
    body = itemsQ.isLoading ? (
      <SkeletonTable rows={4} columns={5} />
    ) : itemsQ.isError ? (
      <ErrorState
        title={t('commitment.page.load_failed', { defaultValue: 'The commitments could not be loaded' })}
        hint={getErrorMessage(itemsQ.error)}
        onRetry={() => itemsQ.refetch()}
      />
    ) : selected ? (
      <ItemPanel
        key={selected.id}
        projectId={projectId}
        item={selected}
        matrix={matrix}
        otherItems={items.filter((i) => i.id !== selected.id)}
        labels={labels}
        personName={personName}
        onBack={() => go({ item: null })}
        onOpenItem={(id) => go({ item: id })}
        onChanged={invalidate}
      />
    ) : (
      <EmptyState
        icon={<Grid3x3 size={28} />}
        title={t('commitment.page.item_missing_title', { defaultValue: 'This item is not in the matrix' })}
        description={t('commitment.page.item_missing_body', {
          defaultValue: 'It may have been removed, or the link belongs to another project.',
        })}
        action={{
          label: t('commitment.item.back', { defaultValue: 'All commitments' }),
          onClick: () => go({ item: null }),
        }}
      />
    );
  } else if (tab === 'setup') {
    body = (
      <SetupPanel
        projectId={projectId}
        matrix={matrix}
        can={can}
        labels={labels}
        personName={personName}
        onSaved={invalidate}
      />
    );
  } else if (tab === 'exposure') {
    body = <ExposurePanel projectId={projectId} items={items} can={can} onOpenItem={(id) => go({ item: id })} />;
  } else if (itemsQ.isLoading) {
    body = <SkeletonTable rows={5} columns={7} />;
  } else if (itemsQ.isError) {
    body = (
      <ErrorState
        title={t('commitment.page.load_failed', { defaultValue: 'The commitments could not be loaded' })}
        hint={getErrorMessage(itemsQ.error)}
        onRetry={() => itemsQ.refetch()}
      />
    );
  } else if (items.length === 0) {
    body = (
      <EmptyState
        icon={<Grid3x3 size={28} />}
        title={t('commitment.grid.empty', { defaultValue: 'No commitment items yet' })}
        description={t('commitment.page.empty_items_body', {
          defaultValue: 'Add the first thing the project will commit money to, for example the main works package. You then request its release from here.',
        })}
        action={
          addV
            ? undefined
            : { label: t('commitment.item_form.add', { defaultValue: 'Add item' }), onClick: () => setAdding(true) }
        }
      />
    );
  } else {
    body = (
      <>
        {findingsQ.isError && (
          <ErrorState
            compact
            title={t('commitment.findings.load_failed', { defaultValue: 'The checks of the matrix could not be loaded' })}
            hint={getErrorMessage(findingsQ.error)}
            onRetry={() => findingsQ.refetch()}
          />
        )}
        <FindingsList findings={findingsQ.data ?? []} />
        <CommitmentGrid
          items={items}
          totals={itemsQ.data!.totals}
          matrix={matrix}
          labels={labels}
          onOpenItem={(id) => go({ item: id })}
        />
      </>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="commitment-release-page">
      {header}
      {!itemId && (
        <div className="flex flex-wrap items-end justify-between gap-3">
          <TabBar<Tab>
            ariaLabel={t('commitment.page.tabs', { defaultValue: 'Commitment sections' })}
            activeId={tab}
            onChange={(id) => go({ tab: id === 'matrix' ? null : id })}
            idPrefix="commitment-release"
            tabs={[
              { id: 'matrix', label: t('commitment.nav.tab', { defaultValue: 'Commitments' }), icon: <Grid3x3 size={14} /> },
              {
                id: 'exposure',
                label: t('commitment.drawer.exposure', { defaultValue: 'Abort exposure' }),
                icon: <ShieldAlert size={14} />,
              },
              { id: 'setup', label: t('commitment.page.tab_setup', { defaultValue: 'Approval setup' }), icon: <Users size={14} /> },
            ]}
          />
          {tab === 'matrix' && (
            <div className="flex flex-wrap items-start gap-2">
              <span className="self-center text-xs text-content-tertiary" data-testid="enforcement-mode">
                {t('commitment.page.enforcement', {
                  defaultValue: 'Awards above the release: {{mode}}',
                  mode: vocab(t, ENFORCEMENT, matrix.enforcement),
                })}
              </span>
              {items.length > 0 && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Download size={14} />}
                    loading={exportFile.isPending && exportFile.variables === 'pdf'}
                    onClick={() => exportFile.mutate('pdf')}
                    data-testid="export-pdf"
                  >
                    {t('commitment.page.export_pdf', { defaultValue: 'PDF' })}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Download size={14} />}
                    loading={exportFile.isPending && exportFile.variables === 'xlsx'}
                    onClick={() => exportFile.mutate('xlsx')}
                    data-testid="export-xlsx"
                  >
                    {t('commitment.page.export_xlsx', { defaultValue: 'Excel' })}
                  </Button>
                </>
              )}
              <ReasonedButton
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                verdict={addV}
                onClick={() => setAdding(true)}
                data-testid="item-add"
              >
                {t('commitment.item_form.add', { defaultValue: 'Add item' })}
              </ReasonedButton>
            </div>
          )}
        </div>
      )}
      {capsQ.isError && (
        <ErrorState
          compact
          title={t('commitment.page.capabilities_failed', {
            defaultValue: 'What you may do here could not be loaded, so every action is off',
          })}
          hint={getErrorMessage(capsQ.error)}
          onRetry={() => capsQ.refetch()}
        />
      )}
      {body}
      {adding && (
        <ItemDialog
          open
          onClose={() => setAdding(false)}
          projectId={projectId}
          matrix={matrix}
          item={null}
          ownerVerdict={projectVerdict(can, 'manage')}
          labels={labels}
          personName={personName}
          onSaved={(saved) => {
            invalidate();
            go({ item: saved.id });
          }}
        />
      )}
    </div>
  );
}
