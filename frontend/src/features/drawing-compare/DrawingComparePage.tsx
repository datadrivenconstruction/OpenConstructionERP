// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Drawing revision compare page.
 *
 * Left: the project's stored compares and "New comparison". Right: the open
 * compare (viewer and change list) or the new-compare panel. Deep links:
 * `?from=<old takeoff doc>&to=<new takeoff doc>` opens a new PDF compare with
 * both revisions picked (used by the takeoff compare drawer and the BOQ
 * drawing references); `?id=<comparison>` opens a stored one.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { FolderOpen, GitCompare, Plus } from 'lucide-react';

import { Badge, EmptyState, Skeleton } from '@/shared/ui';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { PageHeader } from '@/shared/ui/PageHeader';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { drawingCompareApi, type Comparison } from './api';
import { ComparisonView } from './components/ComparisonView';
import { NewComparePanel } from './components/NewComparePanel';

/** Roles that satisfy ``drawing_compare.update`` (EDITOR and above); the server still decides. */
const WRITE_ROLES = new Set(['admin', 'manager', 'editor', 'estimator', 'quantity_surveyor', 'qs', 'user', 'superuser', 'owner']);
/** Roles that satisfy ``drawing_compare.delete`` (MANAGER and above). */
const DELETE_ROLES = new Set(['admin', 'manager', 'superuser', 'owner']);

export function DrawingComparePage() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectId = useProjectContextStore((s) => s.activeProjectId) || '';
  const projectName = useProjectContextStore((s) => s.activeProjectName) || '';
  const role = (useAuthStore((s) => s.userRole) || '').toLowerCase();
  const canWrite = WRITE_ROLES.has(role);
  const canDelete = DELETE_ROLES.has(role);

  const fromParam = searchParams.get('from');
  const toParam = searchParams.get('to');
  const [selected, setSelected] = useState<string | 'new' | null>(
    searchParams.get('id') ?? (fromParam || toParam ? 'new' : null),
  );

  const listQuery = useQuery({
    queryKey: ['drawing-compare', 'list', projectId],
    queryFn: () => drawingCompareApi.list(projectId),
    enabled: !!projectId,
  });
  const comparisons = useMemo(() => listQuery.data ?? [], [listQuery.data]);

  useEffect(() => {
    if (selected === null && listQuery.isSuccess) setSelected(comparisons[0]?.id ?? 'new');
  }, [selected, listQuery.isSuccess, comparisons]);

  const detailQuery = useQuery({
    queryKey: ['drawing-compare', 'comparison', selected],
    queryFn: () => drawingCompareApi.get(selected as string),
    enabled: !!selected && selected !== 'new',
  });

  const open = (id: string | 'new') => {
    setSelected(id);
    const next = new URLSearchParams(searchParams);
    next.delete('from');
    next.delete('to');
    if (id === 'new') next.delete('id');
    else next.set('id', id);
    setSearchParams(next, { replace: true });
  };

  const onSaved = (cmp: Comparison) => {
    qc.setQueryData(['drawing-compare', 'comparison', cmp.id], cmp);
    void qc.invalidateQueries({ queryKey: ['drawing-compare', 'list', projectId] });
    open(cmp.id);
  };

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(getIntlLocale(), { dateStyle: 'medium' }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [i18n.language],
  );

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        items={[
          ...(projectId && projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('nav.drawing_compare', { defaultValue: 'Revision compare' }) },
        ]}
      />
      <PageHeader
        srTitle={t('nav.drawing_compare', { defaultValue: 'Revision compare' })}
        subtitle={t('drawing_compare.subtitle', {
          defaultValue: 'Lay two revisions of a drawing over each other and work through what changed.',
        })}
      />

      <CollapsibleSection
        storageKey="drawing_compare.how"
        defaultCollapsed={comparisons.length > 0}
        icon={<GitCompare size={15} className="text-oe-blue" />}
        title={t('drawing_compare.how_title', { defaultValue: 'How it works' })}
      >
        <p className="mb-2 text-sm text-content-secondary">
          {t('drawing_compare.how_intro', {
            defaultValue: 'A new revision rarely says everything that moved. This page finds it for you and keeps the record.',
          })}
        </p>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-content-secondary">
          <li>{t('drawing_compare.how_step1', { defaultValue: 'Pick the older and the newer revision: two PDF sheets from Takeoff or two DWG/DXF versions.' })}</li>
          <li>{t('drawing_compare.how_step2', { defaultValue: 'Align them automatically by frame and title block, or click the same two marks on both.' })}</li>
          <li>{t('drawing_compare.how_step3', { defaultValue: 'Review each changed region in the overlay (old red, new blue) or side by side.' })}</li>
          <li>{t('drawing_compare.how_step4', { defaultValue: 'Mark what matters, raise an RFI or a cloud, flag the quantities inside for re-measure, export the report.' })}</li>
        </ol>
        <p className="mt-2 flex flex-wrap gap-3 text-xs">
          <button type="button" className="text-oe-blue underline" onClick={() => navigate('/takeoff')}>
            {t('nav.takeoff', { defaultValue: 'PDF Takeoff' })}
          </button>
          <button type="button" className="text-oe-blue underline" onClick={() => navigate('/dwg-takeoff')}>
            {t('nav.dwg_takeoff', { defaultValue: 'DWG Takeoff' })}
          </button>
          <button type="button" className="text-oe-blue underline" onClick={() => navigate('/rfi')}>
            {t('rfi.title', { defaultValue: 'RFIs' })}
          </button>
          <button type="button" className="text-oe-blue underline" onClick={() => navigate('/markups')}>
            {t('nav.markups', { defaultValue: 'Markups' })}
          </button>
        </p>
      </CollapsibleSection>

      {!projectId ? (
        <EmptyState
          icon={<FolderOpen size={24} />}
          title={t('drawing_compare.no_project_title', { defaultValue: 'Pick a project first' })}
          description={t('drawing_compare.no_project_desc', { defaultValue: 'Revision compares belong to a project. Select one to see and start compares.' })}
          action={{ label: t('projects.title', { defaultValue: 'Projects' }), onClick: () => navigate('/projects') }}
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="flex flex-col gap-2" aria-label={t('drawing_compare.list_label', { defaultValue: 'Stored comparisons' })}>
            <button
              type="button"
              onClick={() => open('new')}
              disabled={!canWrite}
              className={clsx(
                'flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium',
                selected === 'new' ? 'border-oe-blue bg-oe-blue/10 text-oe-blue' : 'border-dashed border-border',
                !canWrite && 'cursor-not-allowed opacity-50',
              )}
              data-testid="drawing-compare-new-button"
            >
              <Plus size={15} />
              {t('drawing_compare.new', { defaultValue: 'New comparison' })}
            </button>
            {listQuery.isLoading && <Skeleton className="h-16 w-full" />}
            {comparisons.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => open(c.id)}
                className={clsx(
                  'rounded-lg border px-3 py-2 text-left text-sm',
                  selected === c.id ? 'border-oe-blue bg-oe-blue/5' : 'border-border hover:bg-surface-secondary',
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium">{c.name}</span>
                  <Badge size="sm" variant={c.source_kind === 'pdf' ? 'neutral' : 'purple'}>
                    {c.source_kind === 'pdf' ? 'PDF' : 'DWG'}
                  </Badge>
                </div>
                <div className="mt-0.5 text-xs text-content-secondary">
                  {t('drawing_compare.list_meta', {
                    defaultValue: 'Changes: {{n}} · {{date}}',
                    n: c.summary.total ?? 0,
                    date: dateFmt.format(new Date(c.created_at)),
                  })}
                </div>
              </button>
            ))}
          </aside>
          <section className="min-w-0">
            {selected === 'new' ? (
              <NewComparePanel projectId={projectId} initialOld={fromParam} initialNew={toParam} onSaved={onSaved} />
            ) : detailQuery.data ? (
              <ComparisonView
                key={detailQuery.data.id}
                comparison={detailQuery.data}
                canWrite={canWrite}
                canDelete={canDelete}
                onDeleted={() => {
                  void qc.invalidateQueries({ queryKey: ['drawing-compare', 'list', projectId] });
                  open('new');
                }}
              />
            ) : detailQuery.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}
