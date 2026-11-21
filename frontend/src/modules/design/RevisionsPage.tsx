// Design module (ERP side of the design editor link).
/**
 * Design → Revisions: every model revision the editor shared with the project. A revision opens in the
 * shared 3D viewer; picking an element shows its table row; two revisions can be compared, and the viewer
 * colours what was added, removed and changed by `element_key`.
 */

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Boxes, FolderOpen, GitCompare } from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from '@/shared/ui';
import { BIMViewer, type BIMElementData } from '@/shared/ui/BIMViewer';
import { useModelViewerData } from '@/features/bim/useModelViewerData';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchImportedModels, fetchRevisions, importModel } from './api';
import {
  hasModel,
  isImported,
  upAxis,
  type Comparison,
  overlayFor,
  statusTone,
  toggleCompare,
  type RevisionView,
} from './data/revisions';
import { tr } from './BriefFields';
import { useQuietViewer, VIEWER_FRAME } from './useQuietViewer';
import { useIsoFrame } from './frameView';
import { useRevisionCompare } from './useRevisionCompare';
import GenerationPanel from './GenerationPanel';
import ModelPanel from './ModelPanel';
import { useProjectFromUrl } from './useProjectFromUrl';

export default function RevisionsPage() {
  const { t } = useTranslation();
  useProjectFromUrl();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  if (!projectId) {
    return (
      <EmptyState
        icon={<FolderOpen size={28} aria-hidden />}
        title={tr(t, 'design.brief.no_project')}
        description={tr(t, 'design.revisions.no_project_hint')}
      />
    );
  }
  return <Revisions key={projectId} projectId={projectId} />;
}

function Revisions({ projectId }: { projectId: string }) {
  useQuietViewer();
  const iso = useIsoFrame();
  const { t, i18n } = useTranslation();
  const list = useQuery({ queryKey: ['design-revisions', projectId], queryFn: () => fetchRevisions(projectId) });
  // ?rev=<revision id> opens that revision (the estimate page links here).
  const [params] = useSearchParams();
  const wanted = params.get('rev');
  const [openId, setOpenId] = useState<string | null>(wanted);
  const [seenWanted, setSeenWanted] = useState(wanted);
  if (wanted !== seenWanted) {
    setSeenWanted(wanted);
    if (wanted) setOpenId(wanted);
  }
  const [picked, setPicked] = useState<RevisionView[]>([]);
  const [side, setSide] = useState<'base' | 'head'>('head');
  const [selected, setSelected] = useState<BIMElementData | null>(null);

  const revisions = list.data ?? [];
  const comparing = picked.length === 2;
  const [base, head] = comparing ? picked : [null, null];
  const shown: RevisionView | null = comparing
    ? (side === 'head' ? head : base)
    : (revisions.find((r) => r.revision_id === openId) ?? null);
  const modelId = shown?.bim_model_id ?? null;

  const viewer = useModelViewerData(projectId, modelId);
  const { cmp, failed } = useRevisionCompare(comparing ? base : null, comparing ? head : null);
  const overlay = useMemo(() => (cmp ? overlayFor(cmp, side) : null), [cmp, side]);

  const open = (r: RevisionView) => {
    setOpenId(r.revision_id);
    setSelected(null);
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 animate-fade-in">
      <PageHeader srTitle={tr(t, 'design.revisions.title')} subtitle={tr(t, 'design.revisions.subtitle')} />
      {/* one way to build a revision: the parameter panel, or the plain build where it has nothing to show */}
      <ModelPanel projectId={projectId} fallback={<GenerationPanel projectId={projectId} />} />
      <ImportedModels projectId={projectId} />
      {list.isError ? (
        <ErrorState title={tr(t, 'design.revisions.load_failed')} hint={getErrorMessage(list.error)} onRetry={() => list.refetch()} />
      ) : list.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : revisions.length === 0 ? (
        <EmptyState
          icon={<Boxes size={28} aria-hidden />}
          title={tr(t, 'design.revisions.empty')}
          description={tr(t, 'design.revisions.empty_hint')}
          action={<Link className="text-sm text-oe-blue-text underline" to="/design/editor">{tr(t, 'design.editor.open')}</Link>}
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
          <Card padding="none" className="w-full shrink-0 overflow-auto lg:w-[360px]">
            <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.revisions.list')} subtitle={tr(t, 'design.revisions.compare_hint')} />
            <ul className="divide-y divide-border-light" data-testid="revision-list">
              {revisions.map((r) => {
                const isOpen = shown?.revision_id === r.revision_id;
                const inCompare = picked.some((p) => p.revision_id === r.revision_id);
                return (
                  <li key={r.revision_id} aria-current={isOpen ? 'true' : undefined} className={`flex items-start gap-3 px-4 py-3 ${isOpen ? 'bg-surface-secondary' : ''}`}>
                    <input
                      type="checkbox"
                      aria-label={tr(t, 'design.revisions.compare_pick', { number: r.number })}
                      checked={inCompare}
                      disabled={!hasModel(r)}
                      onChange={() => { setPicked((p) => toggleCompare(p, r)); setSelected(null); }}
                      className="mt-1"
                    />
                    <button type="button" className="min-w-0 flex-1 text-start" disabled={!hasModel(r)} onClick={() => open(r)}>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{tr(t, 'design.revisions.number', { number: r.number })}</span>
                        <Badge variant={statusTone(r.status)} size="sm">{tr(t, `design.revisions.status.${r.status}`)}</Badge>
                        {r.depth_level && <Badge size="sm">{r.depth_level}</Badge>}
                        {isImported(r) && <Badge size="sm" variant="blue">{tr(t, 'design.revisions.imported')}</Badge>}
                      </div>
                      <div className="truncate text-sm text-content-secondary">{r.message || tr(t, 'design.revisions.no_message')}</div>
                      <div className="text-xs text-content-tertiary">
                        {tr(t, `design.revisions.source.${r.source_kind}`)} · {new Date(r.created_at).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' })}
                        {!hasModel(r) && ` · ${tr(t, 'design.revisions.no_model')}`}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Card>

          <div className="flex min-w-0 flex-1 flex-col gap-3">
            {comparing && base && head && (
              <Card padding="none">
                <div className="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="compare-bar">
                  <GitCompare size={16} aria-hidden />
                  <span className="font-medium">
                    {tr(t, 'design.revisions.comparing', { base: base.number, head: head.number })}
                  </span>
                  {cmp ? (
                    <>
                      <Badge variant="success">{tr(t, 'design.revisions.added_n', { count: cmp.added.length })}</Badge>
                      <Badge variant="error">{tr(t, 'design.revisions.removed_n', { count: cmp.removed.length })}</Badge>
                      <Badge variant="warning">{tr(t, 'design.revisions.changed_n', { count: cmp.changed.length })}</Badge>
                      <span className="text-sm text-content-secondary">
                        {tr(t, 'design.revisions.unchanged_n', { count: cmp.unchanged })}
                      </span>
                    </>
                  ) : failed ? (
                    <span role="alert" className="text-sm text-semantic-error">{tr(t, 'design.revisions.compare_failed')}</span>
                  ) : (
                    <Skeleton className="h-5 w-48" />
                  )}
                  <div className="ms-auto flex gap-1" role="group" aria-label={tr(t, 'design.revisions.side')}>
                    {(['base', 'head'] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        aria-pressed={side === s}
                        onClick={() => { setSide(s); setSelected(null); }}
                        className={`rounded px-2 py-1 text-sm ${side === s ? 'bg-surface-secondary font-medium' : ''}`}
                      >
                        {tr(t, `design.revisions.show_${s}`, { number: s === 'base' ? base.number : head.number })}
                      </button>
                    ))}
                  </div>
                </div>
                {cmp && <ChangeList cmp={cmp} />}
              </Card>
            )}

            <div ref={iso.box} className={`relative min-h-[420px] flex-1 overflow-hidden rounded-lg border border-border-light ${VIEWER_FRAME}`}>
              {shown && modelId ? (
                <BIMViewer
                  key={modelId}
                  modelId={modelId}
                  projectId={projectId}
                  modelName={`#${shown.number}`}
                  modelMetadata={viewer.activeModel?.metadata ?? null}
                  elements={viewer.elements}
                  geometryUrl={viewer.geometryUrl}
                  isLoading={viewer.isLoadingElements}
                  glbUpAxis={upAxis(shown)}
                  diffChangeByStableId={overlay}
                  onSceneReady={iso.onSceneReady}
                  onGeometryLoaded={iso.onGeometryLoaded}
                  onSelectionChange={(_ids, els) => setSelected(els[0] ?? null)}
                  className="h-full"
                />
              ) : (
                <EmptyState
                  icon={<Boxes size={28} aria-hidden />}
                  title={tr(t, 'design.revisions.pick')}
                  description={tr(t, 'design.revisions.pick_hint')}
                />
              )}
            </div>

            {selected && (
              <Card padding="none">
                <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.revisions.element')} subtitle={selected.stable_id} />
                <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 px-4 pb-4 text-sm" data-testid="element-row">
                  <dt>{tr(t, 'design.revisions.el_name')}</dt><dd>{selected.name}</dd>
                  <dt>{tr(t, 'design.revisions.el_type')}</dt><dd>{selected.element_type}</dd>
                  <dt>{tr(t, 'design.revisions.el_storey')}</dt><dd>{selected.storey ?? '-'}</dd>
                  <dt>{tr(t, 'design.revisions.el_discipline')}</dt><dd>{selected.discipline}</dd>
                  {Object.entries(selected.quantities ?? {}).map(([k, v]) => (
                    <div key={k} className="contents"><dt>{tr(t, `design.revisions.qty.${k}`, { defaultValue: k })}</dt><dd>{Number(v).toLocaleString(i18n.language, { maximumFractionDigits: 3 })}</dd></div>
                  ))}
                </dl>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Converter models not yet in the chain; adding one makes it a revision awaiting acceptance. */
function ImportedModels({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const models = useQuery({ queryKey: ['design-imported', projectId], queryFn: () => fetchImportedModels(projectId) });
  const add = useMutation({
    mutationFn: (id: string) => importModel(projectId, id),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['design-imported', projectId] });
      qc.invalidateQueries({ queryKey: ['design-revisions', projectId] });
    },
  });
  const items = models.data ?? [];
  if (items.length === 0) return null;
  return (
    <Card padding="none">
      <div data-testid="imported-models">
        <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.revisions.imported_title')} subtitle={tr(t, 'design.revisions.imported_hint')} />
        {add.isError && <p role="alert" className="px-4 pb-2 text-sm text-semantic-error">{getErrorMessage(add.error)}</p>}
        <ul className="divide-y divide-border-light">
          {items.map((m) => (
            <li key={m.bim_model_id} className="flex items-center gap-3 px-4 py-2">
              <span className="min-w-0 flex-1 truncate">{m.name}</span>
              {m.model_format && <Badge size="sm">{m.model_format.toUpperCase()}</Badge>}
              <span className="text-xs text-content-tertiary">{tr(t, 'design.revisions.imported_elements', { count: m.element_count })}</span>
              <Button size="sm" variant="secondary" disabled={add.isPending} onClick={() => add.mutate(m.bim_model_id)}>
                {tr(t, 'design.revisions.imported_add')}
              </Button>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

const CAP = 50;

/** Keys behind the counts; removed elements are not in the head model, so this is where they can be read. */
function ChangeList({ cmp }: { cmp: Comparison }) {
  const { t } = useTranslation();
  const groups = [
    ['added', cmp.added],
    ['removed', cmp.removed],
    ['changed', cmp.changed],
  ] as const;
  if (groups.every(([, keys]) => keys.length === 0)) {
    return <p className="px-4 pb-3 text-sm text-content-secondary" data-testid="no-differences">{tr(t, 'design.revisions.no_differences')}</p>;
  }
  return (
    <div className="grid gap-2 px-4 pb-3 sm:grid-cols-3" data-testid="change-list">
      {groups.map(([kind, keys]) => keys.length > 0 && (
        <details key={kind} open={kind === 'removed'}>
          <summary className="cursor-pointer text-sm font-medium">{tr(t, `design.revisions.${kind}_n`, { count: keys.length })}</summary>
          <ul className="mt-1 max-h-40 overflow-auto font-mono text-xs">
            {keys.slice(0, CAP).map((k) => <li key={k} className="truncate" title={k}>{k}</li>)}
            {keys.length > CAP && <li>{tr(t, 'design.revisions.more_n', { count: keys.length - CAP })}</li>}
          </ul>
        </details>
      ))}
    </div>
  );
}
