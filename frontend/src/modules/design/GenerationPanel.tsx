// Design module (ERP side of the design editor link).
/**
 * Revisions page: "Generate revision" from the confirmed brief on the server (card R13), with the job status.
 * Shown only to a project manager; says why when the server has no generator or the brief is not confirmed yet.
 */

import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Cpu } from 'lucide-react';
import { Badge, Button, Card, CardHeader } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { cancelGeneration, fetchAccess, fetchBrief, fetchGeneration, startGeneration } from './api';
import { noWorkerText, tr } from './BriefFields';

const ACTIVE = ['queued', 'running'];

export default function GenerationPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const access = useQuery({ queryKey: ['design-access', projectId], queryFn: () => fetchAccess(projectId) });
  const brief = useQuery({ queryKey: ['design-brief', projectId], queryFn: () => fetchBrief(projectId) });
  const state = useQuery({
    queryKey: ['design-generation', projectId],
    queryFn: () => fetchGeneration(projectId),
    refetchInterval: (q) => (q.state.data?.job && ACTIVE.includes(q.state.data.job.status) ? 2000 : false),
  });
  const job = state.data?.job ?? null;
  const active = !!job && ACTIVE.includes(job.status);

  // A job that finishes while this page is open brings a new revision: refresh the list once.
  const wasActive = useRef(false);
  useEffect(() => {
    if (active) wasActive.current = true;
    else if (wasActive.current && job) {
      wasActive.current = false;
      void queryClient.invalidateQueries({ queryKey: ['design-revisions', projectId] });
    }
  }, [active, job, projectId, queryClient]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['design-generation', projectId] });
  const start = useMutation({
    mutationFn: () => startGeneration(projectId, brief.data!.version),
    onSuccess: () => void refresh(),
    onError: (err) => addToast({ type: 'error', title: tr(t, 'design.generate.start_failed'), message: noWorkerText(err, t) ?? getErrorMessage(err) }),
  });
  const cancel = useMutation({
    mutationFn: () => cancelGeneration(job!.job_id),
    onSuccess: () => void refresh(),
    onError: (err) => addToast({ type: 'error', title: tr(t, 'design.generate.cancel_failed'), message: getErrorMessage(err) }),
  });

  if (state.isLoading || access.isLoading || brief.isLoading) return null;
  if (!access.data?.can_accept) return null;
  const doc = brief.data ?? null;
  const confirmed = !!doc && Object.values(doc.provenance ?? {}).every((e) => e.status === 'confirmed');
  const blocked = !state.data?.enabled
    ? (state.data?.reason ?? tr(t, 'design.generate.unavailable'))
    : !doc || !confirmed
      ? tr(t, 'design.generate.brief_needed')
      : access.data.lock && !active
        ? tr(t, 'design.generate.locked', { name: access.data.lock.held_by })
        : null;

  return (
    <Card data-testid="generation-panel">
      <CardHeader title={tr(t, 'design.generate.title')} subtitle={tr(t, 'design.generate.hint')} />
      <div className="flex flex-col gap-3 px-4 pb-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button icon={<Cpu size={16} aria-hidden />} loading={start.isPending} disabled={active || blocked !== null}
            onClick={() => start.mutate()}>
            {tr(t, 'design.generate.button')}
          </Button>
          {active && (
            <Button variant="secondary" loading={cancel.isPending} onClick={() => cancel.mutate()}>
              {tr(t, 'design.generate.cancel')}
            </Button>
          )}
          {job && (
            <Badge variant={job.status === 'done' ? 'success' : job.status === 'failed' ? 'error' : 'neutral'} size="sm">
              {tr(t, `design.generate.status.${job.status}`)}
            </Badge>
          )}
        </div>
        {blocked && !active && <p className="text-sm text-content-secondary" data-testid="generation-blocked">{blocked}</p>}
        {job && active && (
          <progress className="h-2 w-full" max={1} value={job.progress} aria-label={tr(t, 'design.generate.progress')} />
        )}
        {job?.status === 'failed' && job.error && <p role="alert" className="text-sm text-semantic-error">{job.error}</p>}
        {job && job.log_tail.length > 0 && (
          <details open={job.status === 'failed'} className="text-xs text-content-secondary">
            <summary className="cursor-pointer select-none">{tr(t, 'design.generate.log')}</summary>
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-surface-secondary p-2" aria-label={tr(t, 'design.generate.log')}>
              {job.log_tail.slice(-12).join('\n')}
            </pre>
          </details>
        )}
      </div>
    </Card>
  );
}
