// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The kanban: one column per stage of the chosen department, a card per
 * open request. Drag a card onto a column to move it (a closing stage asks
 * for a note first). With "All departments" chosen there is no shared
 * stage list, so the columns are the request statuses instead - said so
 * in the hint above the board.
 */

import { useMemo, useState, type DragEvent, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import type { Department, WorkRequest } from './api';
import type { RequestActions } from './actions';
import { Avatars, BallPill, HScroll, HoursBar, LatePill, PriorityGlyph, RefChip, TypeChips } from './bits';
import { STATUS_COLOUR, STATUS_LABEL, deptOf, dueWords, fmtDay, resolveColour, stagesOf, type Me } from './lib';

interface Column {
  key: string;
  name: string;
  colour: string;
  closes: boolean;
}

const STATUS_COLUMNS: Column[] = (['submitted', 'accepted', 'in_progress', 'on_hold', 'review', 'complete'] as const).map((s) => ({
  key: s,
  name: STATUS_LABEL[s],
  colour: STATUS_COLOUR[s],
  closes: s === 'complete',
}));

export function BoardView({
  dept,
  departments,
  rows,
  me,
  actions,
  onOpen,
}: {
  /** The department whose stages make the columns; undefined = all. */
  dept: Department | undefined;
  departments: Department[];
  rows: WorkRequest[];
  me: Me | null;
  actions: RequestActions;
  onOpen: (req: WorkRequest) => void;
}) {
  const { t } = useTranslation();
  const [dragId, setDragId] = useState<string | null>(null);
  const [hot, setHot] = useState<string | null>(null);
  const byStage = !!dept;

  const columns = useMemo<Column[]>(() => {
    if (dept) return stagesOf(dept).map((s) => ({ key: s.key, name: s.name, colour: s.colour, closes: s.closes }));
    return STATUS_COLUMNS;
  }, [dept]);

  const grouped = useMemo(() => {
    const map = new Map<string, WorkRequest[]>();
    for (const c of columns) map.set(c.key, []);
    const stray: WorkRequest[] = [];
    for (const r of rows) {
      const k = byStage ? r.stage : r.status;
      const list = map.get(k);
      if (list) list.push(r);
      else stray.push(r);
    }
    // A request whose stage the department no longer has still needs a
    // home: the first column, flagged in its title.
    const first = columns[0]?.key;
    if (first && stray.length) map.get(first)?.push(...stray);
    return { map, strayIds: new Set(stray.map((r) => r.id)) };
  }, [columns, rows, byStage]);

  const dropOn = (colKey: string) => {
    const req = rows.find((r) => r.id === dragId);
    setHot(null);
    setDragId(null);
    if (!req) return;
    if (byStage) void actions.toStage(req, colKey);
    else void actions.toStatusColumn(req, colKey as WorkRequest['status']);
  };

  const allow = (e: DragEvent, colKey: string) => {
    if (!dragId) return;
    e.preventDefault();
    // A drag that reaches us without a DataTransfer (an assistive tool, a
    // synthetic event) must still highlight and drop - it used to throw an
    // uncaught TypeError here and take the whole handler with it.
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    if (hot !== colKey) setHot(colKey);
  };

  if (columns.length === 0) {
    return (
      <div className="wr-empty">
        <b>{t('wr.no_stages', { defaultValue: 'This department has no stages configured.' })}</b>
        {t('wr.no_stages_body', { defaultValue: 'Add stages to the department (Manage) and the board will grow its columns.' })}
      </div>
    );
  }

  return (
    <div>
      {!byStage && (
        <p className="wr-hint mb-2">
          {t('wr.board_all_hint', { defaultValue: 'All departments: columns are statuses. Pick a department tab for its own stages.' })}
        </p>
      )}
      <HScroll className="wr-board" label={t('wr.board', { defaultValue: 'Board' })} step={282}>
        <div className="wr-board-cols" role="list" aria-label={t('wr.board', { defaultValue: 'Board' })}>
          {columns.map((col) => {
          const cards = grouped.map.get(col.key) ?? [];
          return (
            <section
              key={col.key}
              className={clsx('wr-col', hot === col.key && 'hot')}
              style={{ ['--col' as string]: resolveColour(col.colour) } as CSSProperties}
              onDragOver={(e) => allow(e, col.key)}
              onDragEnter={(e) => allow(e, col.key)}
              onDragLeave={() => hot === col.key && setHot(null)}
              onDrop={(e) => {
                e.preventDefault();
                dropOn(col.key);
              }}
              aria-label={col.name}
              data-testid={`wr-col-${col.key}`}
            >
              <header className="wr-colhead">
                <span>{col.name}</span>
                {col.closes && <span className="closes">{t('wr.closes', { defaultValue: 'closes' })}</span>}
                <span className="n">{cards.length}</span>
              </header>
              <div className="wr-colbody">
                {cards.length === 0 && <div className="wr-colempty">{t('wr.col_empty', { defaultValue: 'Nothing here' })}</div>}
                {cards.map((req) => (
                  <Card
                    key={req.id}
                    req={req}
                    dept={deptOf(departments, req.department)}
                    me={me}
                    stray={grouped.strayIds.has(req.id)}
                    dragging={dragId === req.id}
                    onDragStart={(e) => {
                      setDragId(req.id);
                      try {
                        e.dataTransfer.effectAllowed = 'move';
                        e.dataTransfer.setData('text/plain', req.reference);
                      } catch {
                        /* no DataTransfer on this event - the drag still works */
                      }
                    }}
                    onDragEnd={() => {
                      setDragId(null);
                      setHot(null);
                    }}
                    onOpen={() => onOpen(req)}
                    onMenu={(e) => actions.openMenu(e, req)}
                  />
                ))}
              </div>
              </section>
            );
          })}
        </div>
      </HScroll>
    </div>
  );
}

function Card({
  req,
  dept,
  me,
  stray,
  dragging,
  onDragStart,
  onDragEnd,
  onOpen,
  onMenu,
}: {
  req: WorkRequest;
  dept: Department | undefined;
  me: Me | null;
  stray: boolean;
  dragging: boolean;
  onDragStart: (e: DragEvent<HTMLDivElement>) => void;
  onDragEnd: () => void;
  onOpen: () => void;
  onMenu: (e: React.MouseEvent) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className={clsx('wr-card', dragging && 'dragging')}
      draggable
      role="listitem"
      tabIndex={0}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen();
      }}
      onContextMenu={onMenu}
      title={stray ? t('wr.stray_stage', { defaultValue: 'Stage "{{stage}}" is not on this department any more', stage: req.stage }) : undefined}
      data-testid={`wr-card-${req.id}`}
    >
      <div className="flex items-center gap-2">
        <RefChip reference={req.reference} colour={dept?.colour} />
        <PriorityGlyph priority={req.priority} />
        <LatePill req={req} />
        <span className="ml-auto">
          <BallPill req={req} me={me} deptName={dept?.name ?? req.department} />
        </span>
      </div>
      <div className="ttl">{req.title}</div>
      <div className="job">
        <b>{req.project_code || '—'}</b>
        {req.client_name && <span>· {req.client_name}</span>}
      </div>
      <TypeChips req={req} dept={dept} />
      <div className="foot">
        {req.due_date && (
          <span className={clsx('due', req.is_overdue && 'late')} title={dueWords(req)}>
            {req.is_overdue ? '⚠ ' : ''}
            {fmtDay(req.due_date)}
          </span>
        )}
        {req.needs_info && <span title={req.needs_info}>{t('wr.needs_info_short', { defaultValue: '? info' })}</span>}
        <span className="sp" />
        <Avatars people={req.assignees} max={3} />
      </div>
      {(req.quoted_hours !== null || req.hours_logged > 0) && <HoursBar req={req} />}
    </div>
  );
}
