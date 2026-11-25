// Design module (ERP side of the design editor link).
/**
 * Procurement delta beside the estimate and schedule deltas on the acceptance screen: which take-off quantities and
 * which tender packages a revision moves, quantities a person set (kept), packages already issued. No prices, no
 * lead times: both are said to be empty.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, CardHeader, ErrorState, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchProcurementImpact, setupProcurement } from './procurementApi';
import { changedRows, signed, type TakeoffRow } from './data/procurement';
import { tr } from './BriefFields';
import { takeoffName } from './data/takeoffName';

export function ProcurementPanel({ projectId, revisionId, canManage }: {
  projectId: string; revisionId: string; canManage: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [groupBy, setGroupBy] = useState<'type_key' | 'ifc_class'>('type_key');
  const q = useQuery({ queryKey: ['design-procurement-impact', revisionId], queryFn: () => fetchProcurementImpact(revisionId) });
  const setup = useMutation({
    mutationFn: () => setupProcurement(projectId, groupBy),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['design-procurement-impact'] }),
  });
  const title = tr(t, 'design.procurement.title');
  if (q.isError) {
    return <ErrorState title={tr(t, 'design.procurement.failed')} hint={getErrorMessage(q.error)} onRetry={() => q.refetch()} />;
  }
  if (q.isLoading || !q.data) return <Skeleton className="h-40 w-full" />;
  const imp = q.data;
  if (!imp.procurement || !imp.totals) {
    return (
      <Card padding="none" data-testid="procurement-panel">
        <CardHeader className="px-4 pt-4 pb-3" title={title} />
        <div className="flex flex-col gap-2 px-4 pb-4 text-sm text-content-secondary">
          <p data-testid="no-procurement">{tr(t, 'design.procurement.none')}</p>
          {canManage ? (
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2">
                <span>{tr(t, 'design.procurement.group_by')}</span>
                <select
                  className="rounded border border-border-light bg-surface-primary px-2 py-1"
                  value={groupBy}
                  onChange={(e) => setGroupBy(e.target.value as 'type_key' | 'ifc_class')}
                  data-testid="procurement-group-by"
                >
                  <option value="type_key">{tr(t, 'design.procurement.by_type')}</option>
                  <option value="ifc_class">{tr(t, 'design.procurement.by_class')}</option>
                </select>
              </label>
              <Button variant="secondary" onClick={() => setup.mutate()} disabled={setup.isPending} data-testid="procurement-setup">
                {tr(t, 'design.procurement.setup')}
              </Button>
            </div>
          ) : (
            <p className="text-xs">{tr(t, 'design.procurement.setup_by_manager')}</p>
          )}
          {setup.isError && (
            <p role="alert" className="text-semantic-error">{tr(t, 'design.procurement.setup_failed')} {getErrorMessage(setup.error)}</p>
          )}
        </div>
      </Card>
    );
  }
  const totals = imp.totals;
  const rows = changedRows(imp.rows ?? []);
  return (
    <Card padding="none" data-testid="procurement-panel">
      <CardHeader className="px-4 pt-4 pb-3" title={title} />
      <p className="px-4 pb-3 text-sm">
        <Link className="text-oe-blue-text underline" to="/tendering" data-testid="procurement-link">{tr(t, 'design.procurement.open')}</Link>
      </p>
      <dl className="grid grid-cols-3 gap-2 px-4 pb-3 text-sm" data-testid="procurement-totals">
        <div>
          <dt className="text-content-tertiary">{tr(t, 'design.procurement.lines')}</dt>
          <dd data-testid="procurement-lines">
            {tr(t, 'design.procurement.lines_value', { changed: totals.lines_changed, added: totals.lines_added, removed: totals.lines_removed })}
          </dd>
        </div>
        <div>
          <dt className="text-content-tertiary">{tr(t, 'design.procurement.packages')}</dt>
          <dd data-testid="procurement-packages">{totals.packages_affected + totals.packages_new}</dd>
        </div>
        <div>
          <dt className="text-content-tertiary">{tr(t, 'design.procurement.issued')}</dt>
          <dd className={totals.issued_packages_affected > 0 ? 'font-medium text-semantic-error' : ''} data-testid="procurement-issued">
            {totals.issued_packages_affected}
          </dd>
        </div>
      </dl>
      {totals.issued_packages_affected > 0 && (
        <p role="note" data-testid="procurement-issued-note" className="mx-4 mb-3 rounded border border-semantic-warning px-3 py-2 text-sm">
          {tr(t, 'design.procurement.issued_note', { count: totals.issued_packages_affected })}
        </p>
      )}
      {imp.follow === false && (
        <p className="px-4 pb-2 text-xs text-content-secondary" data-testid="procurement-paused">{tr(t, 'design.procurement.paused')}</p>
      )}
      {totals.overrides_kept > 0 && (
        <p className="px-4 pb-2 text-xs text-content-secondary" data-testid="procurement-overrides">
          {tr(t, 'design.procurement.overrides_n', { count: totals.overrides_kept })}
        </p>
      )}
      {rows.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border-light border-t border-border-light text-sm" data-testid="procurement-rows">
          {rows.map((r) => <Row key={r.group_key} row={r} />)}
        </ul>
      ) : (
        <p className="px-4 pb-3 text-sm text-content-secondary" data-testid="procurement-no-change">{tr(t, 'design.procurement.no_change')}</p>
      )}
      <p className="px-4 pt-3 text-xs text-content-tertiary" data-testid="procurement-unpriced">{tr(t, 'design.procurement.unpriced')}</p>
      <p className="px-4 py-3 text-xs text-content-tertiary" data-testid="procurement-assumption">{tr(t, 'design.procurement.assumption')}</p>
    </Card>
  );
}

function Row({ row }: { row: TakeoffRow }) {
  const { t } = useTranslation();
  return (
    <li className="flex flex-col gap-1 px-4 py-2" data-testid={`procurement-row-${row.group_key}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{row.label}</span>
        {row.new_line && <Badge variant="blue">{tr(t, 'design.procurement.new')}</Badge>}
        {row.override && (
          <Badge variant="warning">{tr(t, 'design.procurement.override', { value: row.model_quantity_new, unit: row.unit })}</Badge>
        )}
        {row.flags.includes('no_match') && <Badge variant="neutral">{tr(t, 'design.procurement.no_match')}</Badge>}
        {row.flags.includes('position_deleted') && <Badge variant="warning">{tr(t, 'design.procurement.position_deleted')}</Badge>}
        {row.flags.includes('no_quantity') && <Badge variant="neutral">{tr(t, 'design.procurement.no_quantity')}</Badge>}
      </div>
      <div>
        {tr(t, 'design.procurement.from_to', { from: row.current_quantity, to: row.new_quantity, unit: row.unit })}{' '}
        <span className="text-content-tertiary">({signed(row.quantity_delta)})</span>
      </div>
      <div className="text-xs text-content-tertiary">
        {row.package
          ? tr(t, 'design.procurement.package_status', { name: takeoffName(t, row.package.name), status: row.package.status })
          : tr(t, 'design.procurement.package_new')}
      </div>
    </li>
  );
}
