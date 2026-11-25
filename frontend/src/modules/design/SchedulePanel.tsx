// Design module (ERP side of the design editor link).
/**
 * Schedule delta beside the estimate delta on the acceptance screen: finish now and after, the activities that
 * change, durations a person set (kept), and the trades without a sourced productivity rate (not in the delta).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, CardHeader, ErrorState, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchScheduleImpact, setupSchedule } from './scheduleApi';
import { changedRows, day, signedDays, type ScheduleRow } from './data/schedule';
import { tr } from './BriefFields';
import { fmtList } from '@/shared/lib/formatters';

export function SchedulePanel({ projectId, revisionId, canManage, locale }: {
  projectId: string; revisionId: string; canManage: boolean; locale: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ['design-schedule-impact', revisionId], queryFn: () => fetchScheduleImpact(revisionId) });
  const setup = useMutation({
    mutationFn: () => setupSchedule(projectId),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['design-schedule-impact'] }),
  });
  const title = tr(t, 'design.schedule.title');
  if (q.isError) {
    return <ErrorState title={tr(t, 'design.schedule.failed')} hint={getErrorMessage(q.error)} onRetry={() => q.refetch()} />;
  }
  if (q.isLoading || !q.data) return <Skeleton className="h-40 w-full" />;
  const imp = q.data;
  if (!imp.schedule || !imp.totals) {
    return (
      <Card padding="none" data-testid="schedule-panel">
        <CardHeader className="px-4 pt-4 pb-3" title={title} />
        <div className="flex flex-col gap-2 px-4 pb-4 text-sm text-content-secondary">
          <p data-testid="no-schedule">{tr(t, 'design.schedule.none')}</p>
          {canManage ? (
            <div>
              <Button variant="secondary" onClick={() => setup.mutate()} disabled={setup.isPending} data-testid="schedule-setup">
                {tr(t, 'design.schedule.setup')}
              </Button>
            </div>
          ) : (
            <p className="text-xs">{tr(t, 'design.schedule.setup_by_manager')}</p>
          )}
          {setup.isError && (
            <p role="alert" className="text-semantic-error">{tr(t, 'design.schedule.setup_failed')} {getErrorMessage(setup.error)}</p>
          )}
        </div>
      </Card>
    );
  }
  const totals = imp.totals;
  const rows = changedRows(imp.rows ?? []);
  const missing = imp.rate_missing ?? [];
  const tone = totals.delta_days > 0 ? 'text-semantic-error' : totals.delta_days < 0 ? 'text-semantic-success' : 'text-content-tertiary';
  return (
    <Card padding="none" data-testid="schedule-panel">
      <CardHeader className="px-4 pt-4 pb-3" title={title} />
      <p className="px-4 pb-3 text-sm">
        <Link className="text-oe-blue-text underline" to={`/schedule?project_id=${encodeURIComponent(projectId)}`} data-testid="schedule-link">{tr(t, 'design.schedule.open')}</Link>
      </p>
      <dl className="grid grid-cols-3 gap-2 px-4 pb-3 text-sm" data-testid="schedule-totals">
        <div><dt className="text-content-tertiary">{tr(t, 'design.schedule.finish_now')}</dt><dd>{day(totals.current_finish, locale)}</dd></div>
        <div><dt className="text-content-tertiary">{tr(t, 'design.schedule.finish_after')}</dt><dd>{day(totals.after_finish, locale)}</dd></div>
        <div>
          <dt className="text-content-tertiary">{tr(t, 'design.schedule.delta')}</dt>
          <dd className={`font-medium ${tone}`} data-testid="schedule-delta">{tr(t, 'design.schedule.days', { value: signedDays(totals.delta_days) })}</dd>
        </div>
      </dl>
      {missing.length > 0 && (
        <p role="note" data-testid="schedule-missing" className="mx-4 mb-3 rounded border border-semantic-warning px-3 py-2 text-sm">
          {tr(t, 'design.schedule.missing_n', { count: missing.length, list: fmtList(missing.map((m) => m.label)) })}
        </p>
      )}
      {totals.overrides_kept > 0 && (
        <p className="px-4 pb-2 text-xs text-content-secondary" data-testid="schedule-overrides">
          {tr(t, 'design.schedule.overrides_n', { count: totals.overrides_kept })}
        </p>
      )}
      {rows.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border-light border-t border-border-light text-sm" data-testid="schedule-rows">
          {rows.map((r) => <Row key={`${r.rule}/${r.storey}`} row={r} />)}
        </ul>
      ) : (
        <p className="px-4 pb-3 text-sm text-content-secondary" data-testid="schedule-no-change">{tr(t, 'design.schedule.no_change')}</p>
      )}
      <p className="px-4 py-3 text-xs text-content-tertiary" data-testid="schedule-assumption">{tr(t, 'design.schedule.assumption')}</p>
    </Card>
  );
}

function Row({ row }: { row: ScheduleRow }) {
  const { t } = useTranslation();
  const src = row.provenance.source;
  const where = row.storey || tr(t, 'design.schedule.building');
  return (
    <li className="flex flex-col gap-1 px-4 py-2" data-testid={`schedule-row-${row.rule}-${row.storey || 'building'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{row.label}</span>
        <span className="text-content-tertiary">· {where}</span>
        {row.new_activity && <Badge variant="blue">{tr(t, 'design.schedule.new')}</Badge>}
        {row.override && <Badge variant="warning">{tr(t, 'design.schedule.override', { days: row.model_days_new })}</Badge>}
        {row.flags.includes('no_match') && <Badge variant="neutral">{tr(t, 'design.schedule.no_match')}</Badge>}
      </div>
      <div>
        {tr(t, 'design.schedule.from_to', { from: row.current_days ?? 0, to: row.new_days })}{' '}
        <span className={row.delta_days > 0 ? 'text-semantic-error' : row.delta_days < 0 ? 'text-semantic-success' : 'text-content-tertiary'}>
          ({signedDays(row.delta_days)})
        </span>
      </div>
      {row.provenance.worked && <div className="text-xs text-content-tertiary">{row.provenance.worked}</div>}
      {src && (
        <a className="text-xs text-oe-blue-text underline" href={src.url} target="_blank" rel="noreferrer" title={src.quote}>
          {tr(t, 'design.schedule.source', { title: src.title, published: src.published, retrieved: src.retrieved })}
        </a>
      )}
    </li>
  );
}
