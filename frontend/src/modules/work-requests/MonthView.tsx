// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The month calendar - the Team Standup board's month view, made to fit a
 * work request.
 *
 * A standup task has one date and that is the end of it. A request has
 * three kinds: the DUE date it was promised for, the INFO REQUIRED BY
 * date the department is waiting on, and the typed dates each request
 * type brings ("Tested by", "Date the factory receives drawings") which
 * live in `fields` and are described by `field_specs`. So the grid plots
 * one kind at a time, says which on the chip when it is a typed one, and
 * only lets the DUE date be dragged - the other two are not a promise the
 * calendar owns.
 *
 * Above the grid sits the "No date yet" tray: the open requests in scope
 * that carry no date of the chosen kind, as chips you drag onto a day.
 * Nothing here is optimistic - a drop PATCHes, waits, invalidates, and
 * says what changed with the request's own reference; a refusal shows the
 * server's own sentence inline rather than a toast that scrolls away.
 */

import { fmtList } from '@/shared/lib/formatters';
import { useCallback, useMemo, useState, type CSSProperties, type DragEvent, type MouseEvent as ReactMouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { CalendarPlus, CalendarX2, ListFilter, Plus } from 'lucide-react';
import clsx from 'clsx';
import { WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { patchRequest, type Department, type WorkRequest } from './api';
import type { RequestActions } from './actions';
import { useMenu, type MenuItem } from '../comms-intelligence/ContextMenu';
import { WR } from './hooks';
import { Avatars, BallPill } from './bits';
import {
  DATE_MODES,
  addMonths,
  conflictOf,
  dayOf,
  deptOf,
  dueWords,
  errorText,
  firstOfMonth,
  fmtDay,
  isClosed,
  isoDay,
  monthGrid,
  monthLabel,
  plotsByDay,
  plotsFor,
  resolveColour,
  sameMonth,
  stageOf,
  weekdayHeads,
  type DateMode,
  type Me,
  type Plot,
} from './lib';

/**
 * A day never draws more than this many things. At exactly four they all
 * fit; past four the fourth slot becomes the "+N more" pill, so the cell
 * height never depends on the day - the standup board's own rule.
 */
const MAX_CHIPS = 4;

/** What a month drag puts on the clipboard, so no other view claims it. */
const DRAG_PREFIX = 'wr-request:';

export function MonthView({
  departments,
  dept,
  rows,
  me,
  actions,
  onOpen,
  onRaiseOn,
  onShowUndated,
}: {
  /** Every active department, for the colour of a chip on the All tab. */
  departments: Department[];
  /** The chosen department, or undefined on All. */
  dept: Department | undefined;
  /** The filtered rows - the same set the board and the list draw. */
  rows: WorkRequest[];
  me: Me | null;
  actions: RequestActions;
  onOpen: (req: WorkRequest) => void;
  /** Raise a request with a day already in its Due field. */
  onRaiseOn: (day: string | null) => void;
  /** "Show these in the list" - the list, filtered to the undated ones. */
  onShowUndated: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const menu = useMenu();
  const today = isoDay(new Date());

  const [cursor, setCursor] = useState(() => firstOfMonth(today));
  const [mode, setMode] = useState<DateMode>('due');
  const [drag, setDrag] = useState<{ id: string; from: string | null } | null>(null);
  const [hot, setHot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<{ reference: string; text: string } | null>(null);
  const [dueFor, setDueFor] = useState<WorkRequest | null>(null);

  /** Only the due date is the calendar's to move. */
  const draggable = mode === 'due';

  const weeks = useMemo(() => monthGrid(cursor), [cursor]);
  const heads = useMemo(weekdayHeads, []);
  const plots = useMemo(() => plotsFor(rows, mode, departments), [rows, mode, departments]);
  const byDay = useMemo(() => plotsByDay(plots), [plots]);

  /**
   * The requests carrying no date of the chosen kind and still open. In
   * "Key dates" there is no tray: a request whose types define no date
   * field is not MISSING one, and listing every such request would be a
   * tray longer than the calendar.
   */
  const undated = useMemo(() => {
    if (mode === 'key') return [];
    const field = mode === 'due' ? 'due_date' : 'info_required_by';
    return rows.filter((r) => !isClosed(r.status) && !r[field]);
  }, [rows, mode]);

  /** How many of the plotted chips actually land in the month on screen. */
  const inMonth = useMemo(() => plots.filter((p) => sameMonth(p.day, cursor)).length, [plots, cursor]);

  const modeLabel = (m: DateMode) =>
    m === 'due'
      ? t('wr.month_mode_due', { defaultValue: 'Due' })
      : m === 'info'
        ? t('wr.month_mode_info', { defaultValue: 'Info required by' })
        : t('wr.month_mode_key', { defaultValue: 'Key dates' });

  const readOnlyHint = t('wr.month_readonly', {
    defaultValue: '{{what}} is read-only here - switch to Due to move a date by dragging.',
    what: modeLabel(mode),
  });

  /* ── The one write this screen makes ───────────────────────────── */

  const setDue = useCallback(
    async (req: WorkRequest, day: string | null) => {
      if ((req.due_date ?? null) === day) return;
      setBusy(true);
      setRefusal(null);
      try {
        await patchRequest(req.id, { due_date: day });
        await qc.invalidateQueries({ queryKey: [WR] });
        addToast({
          type: 'success',
          title: day
            ? t('wr.month_moved', { defaultValue: '{{ref}} is now due {{day}}', ref: req.reference, day: fmtDay(day) })
            : t('wr.month_cleared', { defaultValue: '{{ref}} has no due date now', ref: req.reference }),
        });
      } catch (err) {
        // The server's own sentence, inline and staying put - a 409 here
        // is a rule the reader has to read, not a toast that slides away.
        const c = conflictOf(err);
        setRefusal({ reference: req.reference, text: c ? (c.allowed.length ? `${c.error} (${fmtList(c.allowed)})` : c.error) : errorText(err) });
      } finally {
        setBusy(false);
      }
    },
    [addToast, qc, t],
  );

  /* ── Drag and drop ─────────────────────────────────────────────── */

  const startDrag = (e: DragEvent, req: WorkRequest, from: string | null) => {
    if (!draggable) return;
    setDrag({ id: req.id, from });
    // Every DataTransfer touch is guarded: a drag can reach a handler with
    // none at all (an assistive tool, a synthetic event in a test), and an
    // unguarded `dropEffect` used to throw and take the handler with it.
    try {
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move';
        // Namespaced: the board drags cards of its own, and a payload
        // that says only "WR-WKS-000012" is something any drop target
        // would happily believe.
        e.dataTransfer.setData('text/plain', `${DRAG_PREFIX}${req.id}`);
      }
    } catch {
      /* no DataTransfer - the drag still works, it just carries nothing */
    }
  };

  const allowDrop = (e: DragEvent, day: string) => {
    if (!drag || !draggable) return;
    e.preventDefault();
    try {
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    } catch {
      /* see above */
    }
    if (hot !== day) setHot(day);
  };

  const dropOn = (e: DragEvent, day: string) => {
    setHot(null);
    let raw = '';
    try {
      raw = e.dataTransfer?.getData('text/plain') ?? '';
    } catch {
      /* some browsers refuse to read the payload outside a real drop */
    }
    // The in-flight id wins; the payload is the fallback, and a payload
    // that is not ours is left alone for whoever it belongs to.
    const id = drag?.id || (raw.startsWith(DRAG_PREFIX) ? raw.slice(DRAG_PREFIX.length) : '');
    setDrag(null);
    if (!id || !draggable) return;
    e.preventDefault();
    e.stopPropagation();
    const req = rows.find((r) => r.id === id);
    if (req) void setDue(req, day);
  };

  /* ── Menus ─────────────────────────────────────────────────────── */

  const chipMenu = (e: ReactMouseEvent, p: Plot) => {
    const extra: (MenuItem | null)[] = [
      null,
      { label: t('wr.month_set_due', { defaultValue: 'Set the due date…' }), icon: CalendarPlus, onClick: () => setDueFor(p.req) },
      {
        label: t('wr.month_clear_due', { defaultValue: 'Clear the due date' }),
        icon: CalendarX2,
        note: p.req.due_date ? fmtDay(p.req.due_date) : undefined,
        disabled: !p.req.due_date,
        onClick: () => void setDue(p.req, null),
      },
    ];
    menu.openFromEvent(e, [...actions.menuFor(p.req), ...extra], { head: `${p.req.reference} · ${p.req.title}` });
  };

  const dayMenu = (e: ReactMouseEvent, day: string) => {
    menu.openFromEvent(
      e,
      [
        {
          label: t('wr.month_raise_on', { defaultValue: 'Raise a request due this day' }),
          icon: Plus,
          onClick: () => onRaiseOn(day),
        },
      ],
      { head: fmtDay(day) },
    );
  };

  const trayMenu = (e: ReactMouseEvent) => {
    menu.openFromEvent(
      e,
      [
        { label: t('wr.raise_btn', { defaultValue: 'Raise a request' }), icon: Plus, onClick: () => onRaiseOn(null) },
        { label: t('wr.month_show_list', { defaultValue: 'Show these in the list' }), icon: ListFilter, onClick: onShowUndated },
      ],
      { head: t('wr.month_tray', { defaultValue: 'No date yet' }) },
    );
  };

  const moreMenu = (e: ReactMouseEvent, day: string, list: Plot[]) => {
    const el = e.currentTarget as HTMLElement;
    menu.openBelow(
      el,
      list.map<MenuItem>((p) => {
        const d = deptOf(departments, p.req.department);
        const who = p.req.assignees[0]?.name ?? p.req.responsible?.name ?? t('wr.unassigned', { defaultValue: 'unassigned' });
        return {
          label: `${p.req.reference} · ${p.req.title}`,
          color: resolveColour(d?.colour),
          note: [p.req.project_code, stageOf(d, p.req.stage)?.name ?? p.req.stage, who].filter(Boolean).join(' · '),
          onClick: () => onOpen(p.req),
        };
      }),
      { head: `${fmtDay(day)} · ${modeLabel(mode)}` },
    );
  };

  /* ── Render ────────────────────────────────────────────────────── */

  return (
    <div className="wr-month" data-testid="wr-month">
      {/* ── Toolbar: month nav, the date-mode toggle, the count ──── */}
      <div className="wr-mhead">
        <div className="wr-mnav">
          <button type="button" className="wr-btn-quiet" onClick={() => setCursor((c) => addMonths(c, -1))} aria-label={t('wr.prev_month', { defaultValue: 'Previous month' })}>
            ◂
          </button>
          <b className="wr-mlabel" data-testid="wr-month-label">
            {monthLabel(cursor)}
          </b>
          <button type="button" className="wr-btn-quiet" onClick={() => setCursor((c) => addMonths(c, 1))} aria-label={t('wr.next_month', { defaultValue: 'Next month' })}>
            ▸
          </button>
          <button type="button" className="wr-btn-quiet" onClick={() => setCursor(firstOfMonth(today))} disabled={sameMonth(cursor, today)}>
            {t('wr.this_month', { defaultValue: 'This month' })}
          </button>
        </div>

        <div className="wr-seg" role="group" aria-label={t('wr.month_mode', { defaultValue: 'Which dates to plot' })} data-testid="wr-month-modes">
          {DATE_MODES.map((mkey) => (
            <button
              key={mkey}
              type="button"
              aria-pressed={mode === mkey}
              onClick={() => {
                setMode(mkey);
                setDrag(null);
                setHot(null);
              }}
              title={
                mkey === 'due'
                  ? t('wr.month_mode_due_hint', { defaultValue: 'The date the request was promised for. Drag a chip to move it.' })
                  : mkey === 'info'
                    ? t('wr.month_mode_info_hint', { defaultValue: 'The date the department needs the answer by. Read-only here.' })
                    : t('wr.month_mode_key_hint', { defaultValue: 'The dates each request type brings, named on the chip. Read-only here.' })
              }
            >
              {modeLabel(mkey)}
            </button>
          ))}
        </div>

        <span className="wr-hint ml-auto" data-testid="wr-month-count">
          {t('wr.month_count', {
            defaultValue: '{{shown}} of {{total}} {{what}} in {{month}}',
            shown: inMonth,
            total: plots.length,
            what: modeLabel(mode).toLowerCase(),
            month: monthLabel(cursor),
          })}
          {undated.length > 0 && ` · ${t('wr.month_undated', { defaultValue: '{{count}} with no date', count: undated.length })}`}
        </span>
      </div>

      {!draggable && <p className="wr-hint wr-mnote">{readOnlyHint}</p>}

      {refusal && (
        <div className="wr-banner err" role="alert">
          <span>
            <b>{t('wr.refused', { defaultValue: '{{ref}}: the server refused that move', ref: refusal.reference })}</b> {refusal.text}
          </span>
          <button type="button" className="wr-btn-quiet ml-auto" onClick={() => setRefusal(null)} aria-label={t('common.close', { defaultValue: 'Close' })}>
            ✕
          </button>
        </div>
      )}

      {/* ── The "No date yet" tray ────────────────────────────────── */}
      {undated.length > 0 && (
        <div className="wr-mtray" data-testid="wr-month-tray">
          <div className="wr-mtray-h" onContextMenu={trayMenu} role="button" tabIndex={0} onKeyDown={() => undefined} title={t('wr.month_tray_hint', { defaultValue: 'Right-click for more. Drag one onto a day to set its due date.' })}>
            <span className="lab">{t('wr.month_tray', { defaultValue: 'No date yet' })}</span>
            <span className="n">{undated.length}</span>
            {draggable && <span className="wr-hint">{t('wr.month_tray_drag', { defaultValue: 'drag onto a day' })}</span>}
          </div>
          <div className="wr-mtray-b">
            {undated.map((req) => {
              const d = deptOf(departments, req.department) ?? dept;
              return (
                <span
                  key={req.id}
                  className={clsx('wr-mtchip', drag?.id === req.id && 'dragging')}
                  style={{ ['--ev' as string]: resolveColour(d?.colour) } as CSSProperties}
                  draggable={draggable}
                  role="button"
                  tabIndex={0}
                  data-testid={`wr-mtchip-${req.id}`}
                  title={
                    draggable
                      ? t('wr.month_tchip_hint', { defaultValue: '{{ref}} · {{title}} · {{dept}}\nDrag onto a day to set its due date, click to open', ref: req.reference, title: req.title, dept: d?.name ?? req.department })
                      : `${req.reference} · ${req.title} · ${d?.name ?? req.department}\n${readOnlyHint}`
                  }
                  onDragStart={(e) => startDrag(e, req, null)}
                  onDragEnd={() => {
                    setDrag(null);
                    setHot(null);
                  }}
                  onClick={() => onOpen(req)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') onOpen(req);
                  }}
                  onContextMenu={(e) => chipMenu(e, { req, day: '', key: 'due_date', label: 'Due' })}
                >
                  <b>{req.reference}</b>
                  <span className="ttl">{req.title}</span>
                  <Avatars people={req.assignees} max={2} />
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* ── The grid ──────────────────────────────────────────────── */}
      {/* One grid, seven columns; the weekday heads and the day cells are
          siblings in it, so no row wrapper can make a column drift. */}
      <div className={clsx('wr-monthgrid', busy && 'busy')} aria-label={monthLabel(cursor)}>
        {heads.map((h) => (
          <div className="wr-dow" key={h}>
            {h}
          </div>
        ))}
        {weeks.flat().map((day) => {
          const list = byDay.get(day) ?? [];
          // At five or more, the fourth slot is the pill rather than a
          // chip - a day is never taller than any other day.
          const shown = list.length > MAX_CHIPS ? list.slice(0, MAX_CHIPS - 1) : list;
          const rest = list.length - shown.length;
          const dow = dayOf(day).getDay();
          return (
            <div
              key={day}
              className={clsx(
                'wr-day',
                !sameMonth(day, cursor) && 'out',
                (dow === 0 || dow === 6) && 'weekend',
                day === today && 'today',
                hot === day && 'over',
              )}
              data-testid={`wr-day-${day}`}
              aria-label={fmtDay(day)}
              onDragOver={(e) => allowDrop(e, day)}
              onDragEnter={(e) => allowDrop(e, day)}
              onDragLeave={() => hot === day && setHot(null)}
              onDrop={(e) => dropOn(e, day)}
              onContextMenu={(e) => {
                // Only the empty part of the day: a right-click that
                // landed on a chip is the chip's own menu.
                if ((e.target as HTMLElement)?.closest?.('.wr-ev, .wr-evmore')) return;
                dayMenu(e, day);
              }}
            >
              <span className="wr-dnum">{Number(day.slice(8))}</span>
              {shown.map((p) => {
                const d = deptOf(departments, p.req.department) ?? dept;
                const late = p.key === 'due_date' && p.req.is_overdue && !isClosed(p.req.status);
                const done = isClosed(p.req.status);
                return (
                  <span
                    key={`${p.req.id}:${p.key}`}
                    className={clsx('wr-ev', late && 'over', done && 'done', drag?.id === p.req.id && 'dragging')}
                    style={{ ['--ev' as string]: resolveColour(d?.colour) } as CSSProperties}
                    role="button"
                    tabIndex={0}
                    draggable={draggable}
                    data-testid={`wr-ev-${p.req.id}-${p.key}`}
                    title={
                      draggable
                        ? `${p.req.reference} · ${p.req.title} · ${d?.name ?? p.req.department}\n${dueWords(p.req) || fmtDay(p.day)}\nDrag onto a day to move it, click to open`
                        : `${p.req.reference} · ${p.req.title} · ${d?.name ?? p.req.department}\n${p.label}: ${fmtDay(p.day)}\n${readOnlyHint}`
                    }
                    onDragStart={(e) => startDrag(e, p.req, day)}
                    onDragEnd={() => {
                      setDrag(null);
                      setHot(null);
                    }}
                    onClick={() => onOpen(p.req)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') onOpen(p.req);
                    }}
                    onContextMenu={(e) => chipMenu(e, p)}
                  >
                    {/* Two lines on purpose. A month column is about 150px
                        wide at 1280, and one line put the reference, the
                        title, the ball and the initials in a race the
                        reference lost - it read "WR-E…", which identifies
                        nothing. The identity gets its own row and never
                        shrinks; the title takes the width that is left. */}
                    <span className="wr-evh">
                      <b>{p.req.reference}</b>
                      <BallPill req={p.req} me={me} deptName={d?.name ?? p.req.department} />
                      <Avatars people={p.req.assignees} max={2} />
                    </span>
                    <span className="wr-evt">
                      {mode === 'key' && <em className="what">{p.label}</em>}
                      {p.req.title}
                    </span>
                  </span>
                );
              })}
              {rest > 0 && (
                <button
                  type="button"
                  className="wr-evmore"
                  data-testid={`wr-evmore-${day}`}
                  title={t('wr.month_more_hint', { defaultValue: 'Show all {{count}}', count: list.length })}
                  onClick={(e) => moreMenu(e, day, list)}
                >
                  {t('wr.month_more', { defaultValue: '+{{count}} more', count: rest })}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {plots.length === 0 && (
        <p className="wr-hint wr-mnote">
          {t('wr.month_empty', { defaultValue: 'Nothing carries a {{what}} date in this scope.', what: modeLabel(mode).toLowerCase() })}
        </p>
      )}

      {menu.element}

      {dueFor && (
        <SetDueDialog
          req={dueFor}
          busy={busy}
          onClose={() => setDueFor(null)}
          onSubmit={(day) => {
            const req = dueFor;
            setDueFor(null);
            void setDue(req, day);
          }}
        />
      )}
    </div>
  );
}

/**
 * "Set the due date…" - the browser's OWN picker, like every other date
 * in the module. The generic ask has free-text fields only, and a typed
 * `YYYY-MM-DD` is the one date format nobody in this office writes.
 */
function SetDueDialog({
  req,
  busy,
  onClose,
  onSubmit,
}: {
  req: WorkRequest;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (day: string | null) => void;
}) {
  const { t } = useTranslation();
  const [day, setDay] = useState(req.due_date ?? '');
  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="sm"
      testId="wr-setdue"
      title={t('wr.month_set_due_title', { defaultValue: 'Due date for {{ref}}', ref: req.reference })}
      subtitle={req.title}
      footer={
        <div className="wr wr-foot">
          <div className="wr-foot-row">
            <span className="wr-hint wr-foot-draft">{t('wr.month_set_due_sub', { defaultValue: 'Clearing it puts the request back in the tray.' })}</span>
            <div className="wr-foot-acts">
              <button type="button" className="wr-btn-quiet" onClick={onClose} disabled={busy}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button type="button" className="wr-btn-quiet on" disabled={busy} onClick={() => onSubmit(day || null)} data-testid="wr-setdue-submit">
                {t('wr.save', { defaultValue: 'Save' })}
              </button>
            </div>
          </div>
        </div>
      }
    >
      <div className="wr">
        <div className="wr-form">
          <div className="wr-field">
            <label htmlFor="wr-setdue-day">{t('wr.due', { defaultValue: 'Due' })}</label>
            <input id="wr-setdue-day" type="date" className="wr-in" autoFocus value={day} onChange={(e) => setDay(e.target.value)} />
          </div>
        </div>
      </div>
    </WideModal>
  );
}
