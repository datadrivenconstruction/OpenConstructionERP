// Design module (ERP side of the design editor link).
/**
 * The project, module by module: what the design feeds (estimate BOQ, schedule, tender packages, drawings, BIM
 * links, change orders, review tasks), how far each one is, and one step to take next. Every row opens the ERP
 * module that holds it; a row not set up yet opens the design page where a person sets it up. Counts only, from
 * the server; nothing here is estimated.
 */
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowRight, Check, FolderOpen, PencilRuler } from 'lucide-react';
import { Button, EmptyState, ErrorState, PageHeader, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchAccess } from './api';
import { tr } from './BriefFields';
import { fetchOverview, syncLinks } from './linksApi';
import { CORE_STEPS as CORE, ICON, stepState, stepText } from './overviewSteps';
import { useProjectFromUrl } from './useProjectFromUrl';
import { ProjectStart } from './ProjectStart';
import { AddendumDrafts } from './AddendumDrafts';

export { stepState } from './overviewSteps';

export default function OverviewPage() {
  const { t } = useTranslation();
  useProjectFromUrl();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  if (!projectId) {
    return (
      <EmptyState icon={<FolderOpen size={28} aria-hidden />} title={tr(t, 'design.brief.no_project')}
        description={tr(t, 'design.overview.no_project_hint')} />
    );
  }
  return <ProjectOverview key={projectId} projectId={projectId} />;
}

export function ProjectOverview({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['design-overview', projectId], queryFn: () => fetchOverview(projectId) });
  const access = useQuery({ queryKey: ['design-access', projectId], queryFn: () => fetchAccess(projectId), retry: false });
  const relink = useMutation({
    mutationFn: () => syncLinks(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['design-overview', projectId] }),
  });

  const steps = q.data?.steps ?? [];
  const core = steps.filter((s) => CORE.includes(s.id));
  const doneCore = core.filter((s) => s.done).length;
  const next = core.find((s) => !s.done) ?? null;
  const waiting = q.data?.waiting_revision_id;
  // Until there is a model the project is still starting: the start screen leads, the steps follow below it.
  const starting = !!q.data && !waiting && !steps.find((s) => s.id === 'model')?.done;

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <h1 className="text-xl font-semibold text-content-primary">{tr(t, 'design.overview.title')}</h1>
      <PageHeader subtitle={tr(t, 'design.overview.subtitle')} />
      {q.isError ? (
        <ErrorState title={tr(t, 'design.overview.load_failed')} hint={getErrorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : q.isLoading ? (
        <Skeleton className="h-80 w-full" />
      ) : (
        <>
          {starting && <ProjectStart projectId={projectId} steps={steps} />}
          {!starting && <section aria-labelledby="ov-progress" className="rounded-xl border border-border-light bg-surface-primary p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h2 id="ov-progress" className="text-sm font-semibold text-content-primary">
                  {tr(t, 'design.overview.progress', { done: doneCore, total: core.length })}
                </h2>
                <p className="text-sm text-content-secondary">
                  {next ? tr(t, `design.overview.next.${next.id}`) : tr(t, 'design.overview.all_linked')}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {waiting && (
                  <Link to={`/design/acceptance?revision=${waiting}`} data-testid="overview-review"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">
                    {tr(t, 'design.overview.review')} <ArrowRight size={14} aria-hidden />
                  </Link>
                )}
                {next && !waiting && (
                  <Link to={next.url} data-testid="overview-next"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">
                    {tr(t, `design.overview.action.${next.id}`)} <ArrowRight size={14} aria-hidden />
                  </Link>
                )}
                <Link to="/design/start" data-testid="overview-start"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-content-primary hover:bg-surface-secondary">
                  {tr(t, 'design.start.open')}
                </Link>
                {next?.id !== 'brief' && next?.id !== 'model' && (
                  <Link to="/design/editor" className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-content-primary hover:bg-surface-secondary">
                    <PencilRuler size={14} aria-hidden /> {tr(t, 'design.editor.open')}
                  </Link>
                )}
              </div>
            </div>
            <div className="mt-3 flex gap-1" aria-hidden>
              {core.map((s) => (
                <span key={s.id} className={clsx('h-1.5 flex-1 rounded-full', s.done ? 'bg-semantic-success' : 'bg-surface-secondary')} />
              ))}
            </div>
          </section>}

          {!starting && <AddendumDrafts projectId={projectId} />}
          <ol className="flex flex-col divide-y divide-border-light overflow-hidden rounded-xl border border-border-light bg-surface-primary"
            data-testid="overview-steps">
            {steps.map((s) => {
              const Icon = ICON[s.id];
              const state = stepState(s);
              return (
                <li key={s.id} data-testid={`step-${s.id}`} data-state={state}>
                  <Link to={s.url}
                    className="group flex items-center gap-3 px-4 py-3 hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-oe-blue">
                    <span className={clsx('flex h-8 w-8 shrink-0 items-center justify-center rounded-full',
                      state === 'done' ? 'bg-semantic-success/15 text-semantic-success'
                        : state === 'waiting' ? 'bg-semantic-warning/15 text-semantic-warning'
                          : 'bg-surface-secondary text-content-tertiary')}>
                      {state === 'done' ? <Check size={16} aria-hidden /> : <Icon size={16} aria-hidden />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-content-primary">{tr(t, `design.overview.step.${s.id}`)}</span>
                      <span className="block truncate text-xs text-content-secondary">{stepText(t, s, steps)}</span>
                    </span>
                    <span className="sr-only">{tr(t, `design.overview.status.${state}`)}</span>
                    <span className="hidden shrink-0 text-xs text-oe-blue-text group-hover:underline sm:inline">
                      {tr(t, state === 'todo' ? 'design.overview.set_up' : 'design.overview.open')}
                    </span>
                    <ArrowRight size={14} aria-hidden className="shrink-0 text-content-tertiary" />
                  </Link>
                </li>
              );
            })}
          </ol>
          {access.data?.can_accept && (
            <div className="flex flex-wrap items-center gap-3 text-sm text-content-secondary">
              <span>{tr(t, 'design.overview.relink_hint')}</span>
              <Button variant="secondary" size="sm" loading={relink.isPending} onClick={() => relink.mutate()}
                data-testid="overview-relink">{tr(t, 'design.overview.relink')}</Button>
              {relink.isSuccess && (
                <span role="status">{tr(t, 'design.overview.relinked', { count: relink.data.element_links })}</span>
              )}
              {relink.isError && <span role="alert" className="text-semantic-error">{getErrorMessage(relink.error)}</span>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
