// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The dense table - the List view and every list in My queue. Sortable by
 * any column, a click opens the request, a right-click gets the shared
 * menu. Deviation is coloured: over the quote red, under it green.
 *
 * The List view also SELECTS: a checkbox column, select-all over the rows
 * on screen, and the bulk bar underneath. Selection is optional so My
 * queue's four tables stay what they were - four read-only lists.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import type { Department, WorkRequest } from './api';
import type { RequestActions } from './actions';
import { Avatars, BallPill, LatePill, PriorityGlyph, RefChip, StagePill, StatusPill, TypeChips } from './bits';
import { deptOf, dueWords, fmtDay, fmtDeviation, fmtHours, sortRequests, type Me, type SortKey } from './lib';

export function RequestTable({
  rows,
  departments,
  me,
  actions,
  onOpen,
  selectedId,
  emptyText,
  showDepartment = false,
  selection,
}: {
  rows: WorkRequest[];
  departments: Department[];
  me: Me | null;
  actions: RequestActions;
  onOpen: (req: WorkRequest) => void;
  selectedId?: string | null;
  emptyText?: string;
  showDepartment?: boolean;
  /**
   * Tick boxes. Absent means no checkbox column at all - My queue is a
   * set of read-only lists, and a column of boxes that does nothing is
   * worse than no column.
   */
  selection?: {
    ids: Set<string>;
    onToggle: (id: string, on: boolean) => void;
    /** Every row currently on screen, in one gesture. */
    onToggleAll: (ids: string[], on: boolean) => void;
  };
}) {
  const { t } = useTranslation();
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'due', dir: 'asc' });
  const sorted = useMemo(() => sortRequests(rows, sort.key, sort.dir), [rows, sort]);
  const pageIds = useMemo(() => sorted.map((r) => r.id), [sorted]);
  const allOn = !!selection && pageIds.length > 0 && pageIds.every((id) => selection.ids.has(id));
  const someOn = !!selection && !allOn && pageIds.some((id) => selection.ids.has(id));

  const head = (key: SortKey, label: string, cls?: string) => (
    <th
      className={cls}
      onClick={() => setSort((s) => ({ key, dir: s.key === key && s.dir === 'asc' ? 'desc' : 'asc' }))}
      aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      scope="col"
    >
      {label}
      {sort.key === key && <span className="arrow">{sort.dir === 'asc' ? '▲' : '▼'}</span>}
    </th>
  );

  if (rows.length === 0) {
    return <div className="wr-empty">{emptyText ?? t('wr.list_empty', { defaultValue: 'No requests match these filters.' })}</div>;
  }

  return (
    <div className="wr-tablewrap">
      <table className="wr-table">
        <thead>
          <tr>
            {selection && (
              <th className="wr-selcol" scope="col">
                <input
                  type="checkbox"
                  checked={allOn}
                  ref={(el) => {
                    // Some-but-not-all is a third state, and it is the one
                    // that says "your select-all will ADD to what you have".
                    if (el) el.indeterminate = someOn;
                  }}
                  onChange={(e) => selection.onToggleAll(pageIds, e.target.checked)}
                  aria-label={t('wr.select_all', { defaultValue: 'Select every request in this list' })}
                  data-testid="wr-select-all"
                />
              </th>
            )}
            {head('reference', t('wr.col_ref', { defaultValue: 'Ref' }))}
            {head('title', t('wr.col_title', { defaultValue: 'Title' }))}
            {head('project', t('wr.col_job', { defaultValue: 'Job' }))}
            {head('client', t('wr.col_client', { defaultValue: 'Client' }))}
            {head('type', t('wr.col_type', { defaultValue: 'Type' }))}
            {head('stage', t('wr.col_stage', { defaultValue: 'Stage' }))}
            {head('status', t('wr.col_status', { defaultValue: 'Status' }))}
            {head('responsible', t('wr.col_responsible', { defaultValue: 'Responsible' }))}
            {head('assignees', t('wr.col_assignees', { defaultValue: 'Assignees' }))}
            {head('due', t('wr.col_due', { defaultValue: 'Due' }))}
            {head('hours', t('wr.col_hours', { defaultValue: 'Hours' }), 'n')}
            {head('ball', t('wr.col_ball', { defaultValue: 'Ball in court' }))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const dept = deptOf(departments, r.department);
            const dev = r.deviation_hours;
            const picked = !!selection && selection.ids.has(r.id);
            return (
              <tr
                key={r.id}
                className={clsx('row', selectedId === r.id && 'sel', picked && 'picked')}
                onClick={() => onOpen(r)}
                onContextMenu={(e) => actions.openMenu(e, r)}
                data-testid={`wr-row-${r.id}`}
              >
                {selection && (
                  // The click must NOT open the request: a tick is a
                  // selection, and a drawer sliding over the list after
                  // every box makes bulk selection impossible.
                  <td className="wr-selcol" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={picked}
                      onChange={(e) => selection.onToggle(r.id, e.target.checked)}
                      aria-label={t('wr.select_one', { defaultValue: 'Select {{ref}}', ref: r.reference })}
                      data-testid={`wr-select-${r.id}`}
                    />
                  </td>
                )}
                <td>
                  <span className="flex items-center gap-1.5">
                    <RefChip reference={r.reference} colour={dept?.colour} title={showDepartment ? dept?.name : undefined} />
                    <PriorityGlyph priority={r.priority} />
                    <LatePill req={r} />
                  </span>
                </td>
                <td>
                  <span className="ttl">{r.title}</span>
                  {r.needs_info && <span className="wr-hint block">{t('wr.needs_info_short', { defaultValue: '? info' })}: {r.needs_info}</span>}
                </td>
                <td className="wr-mono whitespace-nowrap">{r.project_code || '—'}</td>
                <td className="dim">{r.client_name || '—'}</td>
                <td className="dim">
                  <TypeChips req={r} dept={dept} />
                </td>
                <td>
                  <StagePill dept={dept} stage={r.stage} />
                </td>
                <td>
                  <StatusPill status={r.status} />
                </td>
                <td className="whitespace-nowrap">{r.responsible?.name ?? <span className="wr-hint">—</span>}</td>
                <td>
                  <Avatars people={r.assignees} />
                </td>
                <td className="whitespace-nowrap" title={dueWords(r)}>
                  {r.due_date ? <span className={clsx(r.is_overdue && 'late')}>{fmtDay(r.due_date)}</span> : <span className="wr-hint">—</span>}
                </td>
                <td className="n">
                  {fmtHours(r.hours_logged)}
                  {r.quoted_hours !== null ? ` / ${fmtHours(r.quoted_hours)}` : ''}
                  {dev !== null && dev !== undefined && dev !== 0 && (
                    <span className={clsx('wr-dev ml-1', dev > 0 ? 'over' : 'under')} title={t('wr.deviation', { defaultValue: 'Deviation from the quote' })}>
                      {fmtDeviation(dev)}
                    </span>
                  )}
                </td>
                <td>
                  <BallPill req={r} me={me} deptName={dept?.name ?? r.department} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
