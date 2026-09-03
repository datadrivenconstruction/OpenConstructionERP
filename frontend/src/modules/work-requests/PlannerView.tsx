// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The workbook grid: a row per open request of the department, a column
 * per working day for five weeks (weekends folded away), a headcount in
 * every cell. Type a number, arrow around, Enter or Tab commits - each
 * commit is one `PUT /planner/{request_id}` with the row's whole
 * allocation. The capacity row is editable the same way and turns red
 * where the day is over-allocated. Hours are headcount × 8 per day.
 *
 * Three things make it as quick as the standup's own planner:
 *
 * - PAINT. Press on a cell and drag along the row to lay the same
 *   headcount over a range, with a live preview and ONE PUT at the end.
 *   The paint only starts once the pointer has left the cell it began on,
 *   so a plain click still focuses the input and typing still works.
 * - RIGHT-CLICK. The request's own menu on the row (plus "Clear this
 *   row's allocation" and "Copy last week to this week"), and 0/1/2/3,
 *   "Fill the rest of the week" and "Clear" on a cell.
 * - The UNSCHEDULED tray: the department's open requests with nothing in
 *   the visible window, dragged onto a day to start one.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { CalendarRange, ChevronLeft, ChevronRight, CopyPlus, Eraser } from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { patchRequest, putPlannerAlloc, putPlannerCapacity, type Department, type Planner, type PlannerRow, type WorkRequest } from './api';
import type { RequestActions } from './actions';
import { useMenu, type MenuItem } from '../comms-intelligence/ContextMenu';
import { WR, usePlanner } from './hooks';
import { RefChip, StagePill, Avatars } from './bits';
import { HOURS_PER_HEAD_DAY, addDays, columnHeads, dayHead, errorText, fmtDay, fmtDayShort, fmtHours, isClosed, isModuleMissing, isoDay, mondayOf, resolveColour, rowHours, sum, weeksOf } from './lib';
import { ModuleMissing } from './ModuleMissing';
import { getIntlLocale } from '@/shared/lib/formatters';

const WEEKS = 5;

/** The capacity row's stand-in id, so one paint handler serves both. */
const CAP_ROW = '\u0000capacity';

/** What a tray drag puts on the clipboard, namespaced so nothing else takes it. */
const DRAG_PREFIX = 'wr-unscheduled:';

export function PlannerView({
  dept,
  requests,
  actions,
  onOpen,
}: {
  dept: Department;
  /** The same department's open requests, for quoted hours + the planner flag. */
  requests: WorkRequest[];
  /** The module's one request menu, for the row's right-click. */
  actions?: RequestActions;
  onOpen: (req: WorkRequest) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const menu = useMenu();
  const [start, setStart] = useState(() => mondayOf(isoDay(new Date())));
  const from = start;
  const to = addDays(start, WEEKS * 7 - 3); // Friday of the fifth week
  const planner = usePlanner(dept.key, from, to);
  const today = isoDay(new Date());

  // Local copy of the allocations so typing is instant; the server's copy
  // replaces it whenever the query refreshes.
  const [alloc, setAlloc] = useState<Record<string, Record<string, number>>>({});
  const [cap, setCap] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!planner.data) return;
    const a: Record<string, Record<string, number>> = {};
    for (const r of planner.data.rows) a[r.request_id] = { ...r.alloc };
    setAlloc(a);
    const c: Record<string, number> = {};
    for (const [d, v] of Object.entries(planner.data.capacity ?? {})) c[d] = v.available;
    setCap(c);
  }, [planner.data]);

  const days = useMemo(() => {
    const listed = planner.data?.days?.length ? planner.data.days : [];
    // Fall back to the requested window if the server sends none.
    const all = listed.length ? listed : Array.from({ length: WEEKS * 7 }, (_, i) => addDays(from, i));
    return weeksOf(all);
  }, [planner.data, from]);
  const flatDays = useMemo(() => days.flatMap((w) => w.days), [days]);

  const byId = useMemo(() => new Map(requests.map((r) => [r.id, r])), [requests]);
  const rows: PlannerRow[] = useMemo(() => planner.data?.rows ?? [], [planner.data]);

  const gridRef = useRef<HTMLTableElement>(null);
  const focusCell = (row: number, col: number) => {
    const el = gridRef.current?.querySelector<HTMLInputElement>(`input[data-r="${row}"][data-c="${col}"]`);
    el?.focus();
    el?.select();
  };

  const commitRow = useCallback(
    async (requestId: string, next: Record<string, number>) => {
      setSaving((s) => new Set(s).add(requestId));
      try {
        // Drop zeros so the payload says only what is planned.
        const clean: Record<string, number> = {};
        for (const [d, v] of Object.entries(next)) if (v > 0) clean[d] = v;
        await putPlannerAlloc(requestId, clean);
        qc.setQueryData<Planner>([WR, 'planner', dept.key, from, to], (old) =>
          old ? { ...old, rows: old.rows.map((r) => (r.request_id === requestId ? { ...r, alloc: clean } : r)) } : old,
        );
      } catch (err) {
        addToast({ type: 'error', title: errorText(err) });
        void planner.refetch();
      } finally {
        setSaving((s) => {
          const n = new Set(s);
          n.delete(requestId);
          return n;
        });
      }
    },
    [addToast, dept.key, from, planner, qc, to],
  );

  const commitCap = useCallback(
    async (next: Record<string, number>) => {
      try {
        await putPlannerCapacity(dept.key, next);
        void qc.invalidateQueries({ queryKey: [WR, 'planner'] });
      } catch (err) {
        addToast({ type: 'error', title: errorText(err) });
        void planner.refetch();
      }
    },
    [addToast, dept.key, planner, qc],
  );

  /** Write a whole row (or the capacity row) at once, from any gesture. */
  const applyRow = useCallback(
    (rowId: string, next: Record<string, number>) => {
      if (rowId === CAP_ROW) {
        setCap(next);
        void commitCap(next);
        return;
      }
      setAlloc((s) => ({ ...s, [rowId]: next }));
      void commitRow(rowId, next);
    },
    [commitCap, commitRow],
  );

  const allocOf = useCallback(
    (rowId: string): Record<string, number> => (rowId === CAP_ROW ? cap : alloc[rowId] ?? rows.find((r) => r.request_id === rowId)?.alloc ?? {}),
    [alloc, cap, rows],
  );

  /* ── Paint: press, drag along the row, one PUT at the end ──────── */

  /** The press that has not become a paint yet. */
  const anchor = useRef<{ rowId: string; day: string; value: number } | null>(null);
  /** The live preview - the days about to take `value`, nothing written yet. */
  const [paint, setPaint] = useState<{ rowId: string; value: number; days: string[] } | null>(null);
  const paintRef = useRef(paint);
  paintRef.current = paint;

  const dayRange = useCallback(
    (a: string, b: string): string[] => {
      const ia = flatDays.indexOf(a);
      const ib = flatDays.indexOf(b);
      if (ia < 0 || ib < 0) return [];
      return flatDays.slice(Math.min(ia, ib), Math.max(ia, ib) + 1);
    },
    [flatDays],
  );

  const startPress = (e: ReactPointerEvent, rowId: string, day: string, value: number) => {
    // Left button / touch only: a right-click is the menu's, and a middle
    // click must never leave a half-started paint behind.
    if (e.button !== 0) return;
    anchor.current = { rowId, day, value: value > 0 ? value : 1 };
  };

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const move = (e: PointerEvent) => {
      const a = anchor.current;
      if (!a) return;
      // The pointer is captured by nothing, so the element under it is the
      // honest answer - and it is the only one that works for touch, where
      // the event target never changes after the press.
      const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
      const cell = el?.closest?.('td.cell') as HTMLElement | null;
      const day = cell?.dataset?.day;
      const rowId = cell?.dataset?.row;
      if (!day || rowId !== a.rowId) return;
      if (day === a.day && !paintRef.current) return; // still on the anchor: a click, not a paint
      const span = dayRange(a.day, day);
      if (!span.length) return;
      // Once it IS a paint, the input must not keep the caret, and the
      // page must not scroll under a finger that is drawing.
      (document.activeElement as HTMLElement | null)?.blur?.();
      if (e.cancelable) e.preventDefault();
      setPaint({ rowId: a.rowId, value: a.value, days: span });
    };
    const up = () => {
      const p = paintRef.current;
      const a = anchor.current;
      anchor.current = null;
      if (!p || !a) return;
      setPaint(null);
      const next = { ...allocOf(p.rowId) };
      for (const d of p.days) next[d] = p.value;
      applyRow(p.rowId, next);
      addToast({
        type: 'success',
        title: t('wr.plan_painted', {
          defaultValue: '{{n}} on {{count}} days',
          n: p.value,
          count: p.days.length,
        }),
      });
    };
    window.addEventListener('pointermove', move, { passive: false });
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  }, [addToast, allocOf, applyRow, dayRange, t]);

  /* ── The Unscheduled tray ──────────────────────────────────────── */

  const [drag, setDrag] = useState<string | null>(null);
  const [hot, setHot] = useState<string | null>(null);

  /**
   * The department's open requests with no headcount anywhere in the
   * window. A request the server has never given a planner row counts
   * too - it is unscheduled in the most literal sense.
   */
  const unscheduled = useMemo(() => {
    const planned = new Set(
      rows.filter((r) => flatDays.some((d) => (alloc[r.request_id] ?? r.alloc)[d] ?? 0)).map((r) => r.request_id),
    );
    return requests.filter((r) => !isClosed(r.status) && !planned.has(r.id));
  }, [requests, rows, alloc, flatDays]);

  const dropDay = async (e: DragEvent, day: string) => {
    setHot(null);
    let raw = '';
    try {
      raw = e.dataTransfer?.getData('text/plain') ?? '';
    } catch {
      /* the payload is not always readable outside a real drop */
    }
    const id = drag || (raw.startsWith(DRAG_PREFIX) ? raw.slice(DRAG_PREFIX.length) : '');
    setDrag(null);
    if (!id) return;
    e.preventDefault();
    e.stopPropagation();
    const next = { ...allocOf(id), [day]: 1 };
    setAlloc((s) => ({ ...s, [id]: next }));
    await commitRow(id, next);
    // A request with no row yet only grows one server-side, so the window
    // has to be asked again rather than patched in place.
    await qc.invalidateQueries({ queryKey: [WR, 'planner'] });
    addToast({
      type: 'success',
      title: t('wr.plan_scheduled', { defaultValue: '{{ref}} starts {{day}}', ref: byId.get(id)?.reference ?? '', day: fmtDay(day) }),
    });
  };

  const allowDay = (e: DragEvent, day: string) => {
    if (!drag) return;
    e.preventDefault();
    try {
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    } catch {
      /* an event with no DataTransfer still drops */
    }
    if (hot !== day) setHot(day);
  };

  /* ── The scroll affordance ─────────────────────────────────────── */

  /**
   * The grid is wider than 1280 and the first and last columns are
   * STICKY, so the usual overlay fade and floating arrows sit under them
   * - the affordance was invisible exactly where it was needed. So the
   * arrows live INSIDE the two sticky header cells (which are already on
   * top of everything) and the sticky edges grow a shadow while there is
   * something hidden behind them. Nothing overlays anything.
   */
  const wrapRef = useRef<HTMLDivElement>(null);
  const [edge, setEdge] = useState<{ l: boolean; r: boolean }>({ l: false, r: false });
  const edgeRef = useRef('');
  const measure = useCallback(() => {
    const el = wrapRef.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    const l = el.scrollLeft > 2;
    const r = max > 2 && el.scrollLeft < max - 2;
    const sig = `${l}:${r}`;
    if (sig === edgeRef.current) return;
    edgeRef.current = sig;
    setEdge({ l, r });
  }, []);
  useEffect(() => {
    measure();
    const el = wrapRef.current;
    if (!el) return undefined;
    window.addEventListener('resize', measure);
    let ro: ResizeObserver | undefined;
    // jsdom has neither ResizeObserver nor scrollBy; the grid must render
    // without either or every test that draws a planner falls over.
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(measure);
      ro.observe(el);
    }
    return () => {
      window.removeEventListener('resize', measure);
      ro?.disconnect();
    };
  }, [measure, flatDays.length, rows.length]);

  /**
   * Move the window by most of its own width.
   *
   * `scrollBy({behavior: 'smooth'})` is measurably a NO-OP on this
   * element in at least one browser - the arrow was pressed, the class
   * said there was more to see, and `scrollLeft` stayed at 0. Assigning
   * `scrollLeft` always works, and the easing is left to CSS
   * `scroll-behavior`, which honours prefers-reduced-motion for free.
   */
  const nudge = (dir: 1 | -1) => {
    const el = wrapRef.current;
    if (!el) return;
    const by = dir * Math.max(200, Math.round(el.clientWidth * 0.7));
    const max = el.scrollWidth - el.clientWidth;
    el.scrollLeft = Math.max(0, Math.min(max, el.scrollLeft + by));
    measure();
  };

  /* ── Menus ─────────────────────────────────────────────────────── */

  /** The week of `day`, Monday-first, as the visible working days. */
  const weekOf = useCallback((day: string) => days.find((w) => w.days.includes(day))?.days ?? [], [days]);

  const cellMenu = (e: ReactMouseEvent, rowId: string, day: string, label: string) => {
    const a = allocOf(rowId);
    const rest = weekOf(day);
    const tail = rest.slice(rest.indexOf(day));
    const set = (v: number) => applyRow(rowId, { ...a, [day]: v });
    menu.openFromEvent(
      e,
      [
        ...[0, 1, 2, 3].map<MenuItem>((v) => ({
          label: v === 0 ? t('wr.plan_none', { defaultValue: 'Nobody' }) : t('wr.plan_heads', { defaultValue: '{{count}} on it', count: v }),
          note: (a[day] ?? 0) === v ? t('wr.current', { defaultValue: 'current' }) : undefined,
          disabled: (a[day] ?? 0) === v,
          onClick: () => set(v),
        })),
        null,
        {
          label: t('wr.plan_fill_week', { defaultValue: 'Fill the rest of the week' }),
          icon: CalendarRange,
          note: tail.length > 1 ? t('wr.plan_days', { defaultValue: '{{count}} days', count: tail.length }) : undefined,
          disabled: tail.length < 2,
          onClick: () => {
            const v = a[day] ?? 1;
            const next = { ...a };
            for (const d of tail) next[d] = v;
            applyRow(rowId, next);
          },
        },
        { label: t('wr.plan_clear_cell', { defaultValue: 'Clear' }), icon: Eraser, disabled: !(a[day] ?? 0), onClick: () => set(0) },
      ],
      { head: `${label} · ${fmtDay(day)}` },
    );
  };

  const rowMenu = (e: ReactMouseEvent, row: PlannerRow) => {
    const req = byId.get(row.request_id);
    const a = allocOf(row.request_id);
    // "This week" is the week holding today when it is on screen, and the
    // first visible week otherwise - so the item never means nothing.
    const thisMon = days.find((w) => w.days.includes(today))?.monday ?? days[0]?.monday ?? from;
    const lastMon = addDays(thisMon, -7);
    const planner: (MenuItem | null)[] = [
      null,
      {
        label: t('wr.plan_clear_row', { defaultValue: "Clear this row's allocation" }),
        icon: Eraser,
        danger: true,
        note: fmtHours(rowHours(a)),
        disabled: !Object.values(a).some((v) => v > 0),
        onClick: () => applyRow(row.request_id, {}),
      },
      {
        label: t('wr.plan_copy_week', { defaultValue: 'Copy last week to this week' }),
        icon: CopyPlus,
        note: fmtDayShort(lastMon),
        onClick: () => {
          const next = { ...a };
          let moved = 0;
          for (let i = 0; i < 5; i += 1) {
            const src = addDays(lastMon, i);
            const dst = addDays(thisMon, i);
            const v = a[src] ?? 0;
            if (v > 0) moved += 1;
            next[dst] = v;
          }
          if (moved === 0) {
            addToast({ type: 'info', title: t('wr.plan_copy_none', { defaultValue: 'Nothing was planned the week of {{d}}', d: fmtDayShort(lastMon) }) });
            return;
          }
          applyRow(row.request_id, next);
        },
      },
    ];
    const base = req && actions ? actions.menuFor(req) : [{ label: t('wr.open', { defaultValue: 'Open' }), onClick: () => req && onOpen(req) }];
    menu.openFromEvent(e, [...base, ...planner], { head: `${row.reference} · ${row.title}` });
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>, r: number, c: number, commit: () => void, revert: () => void) => {
    const rowsN = rows.length + 1; // + capacity row
    if (e.key === 'ArrowRight' || (e.key === 'Tab' && !e.shiftKey)) {
      if (c < flatDays.length - 1) {
        e.preventDefault();
        commit();
        focusCell(r, c + 1);
      }
    } else if (e.key === 'ArrowLeft' || (e.key === 'Tab' && e.shiftKey)) {
      if (c > 0) {
        e.preventDefault();
        commit();
        focusCell(r, c - 1);
      }
    } else if (e.key === 'ArrowDown' || e.key === 'Enter') {
      e.preventDefault();
      commit();
      if (r < rowsN - 1) focusCell(r + 1, c);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      commit();
      if (r > 0) focusCell(r - 1, c);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      revert();
      (e.target as HTMLInputElement).blur();
    }
  };

  if (planner.isError && isModuleMissing(planner.error)) return <ModuleMissing onRetry={() => void planner.refetch()} />;

  const totalPlanned = sum(rows.map((r) => rowHours(alloc[r.request_id] ?? r.alloc)));
  const totalQuoted = sum(rows.map((r) => byId.get(r.request_id)?.quoted_hours));

  /** The value a cell should SHOW - the paint preview wins while it runs. */
  const shown = (rowId: string, day: string, saved: number) =>
    paint && paint.rowId === rowId && paint.days.includes(day) ? paint.value : saved;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button type="button" className="wr-btn-quiet" onClick={() => setStart((s) => addDays(s, -7))} aria-label={t('wr.prev_week', { defaultValue: 'Previous week' })}>
          ◂
        </button>
        <button type="button" className="wr-btn-quiet" onClick={() => setStart(mondayOf(isoDay(new Date())))}>
          {t('wr.this_week', { defaultValue: 'This week' })}
        </button>
        <button type="button" className="wr-btn-quiet" onClick={() => setStart((s) => addDays(s, 7))} aria-label={t('wr.next_week', { defaultValue: 'Next week' })}>
          ▸
        </button>
        <span className="wr-hint">
          {t('wr.planner_hint', {
            defaultValue: 'Headcount per day. Hours = headcount × {{h}}. Type a number, arrows move, Enter commits, Escape reverts. Drag along a row to paint a range; right-click a cell or a row for more. Weekends are folded.',
            h: HOURS_PER_HEAD_DAY,
          })}
        </span>
        <span className="ml-auto wr-hint">
          {t('wr.planner_totals', { defaultValue: 'Planned {{p}} vs quoted {{q}}', p: fmtHours(totalPlanned), q: fmtHours(totalQuoted) })}
        </span>
      </div>

      {planner.isLoading && <p className="wr-hint">{t('wr.loading', { defaultValue: 'Loading…' })}</p>}
      {planner.isError && !isModuleMissing(planner.error) && (
        <div className="wr-banner err mb-2">
          {errorText(planner.error)}{' '}
          <button type="button" className="wr-btn-quiet" onClick={() => void planner.refetch()}>
            {t('wr.retry', { defaultValue: 'Try again' })}
          </button>
        </div>
      )}

      {planner.data && unscheduled.length > 0 && (
        <div className="wr-mtray mb-2" data-testid="wr-plan-tray">
          <div className="wr-mtray-h">
            <span className="lab">{t('wr.plan_tray', { defaultValue: 'Unscheduled' })}</span>
            <span className="n">{unscheduled.length}</span>
            <span className="wr-hint">{t('wr.plan_tray_hint', { defaultValue: 'nothing in these five weeks - drag one onto a day to start it' })}</span>
          </div>
          <div className="wr-mtray-b">
            {unscheduled.map((req) => (
              <span
                key={req.id}
                className={clsx('wr-mtchip', drag === req.id && 'dragging')}
                style={{ ['--ev' as string]: resolveColour(dept.colour) }}
                draggable
                role="button"
                tabIndex={0}
                data-testid={`wr-plan-chip-${req.id}`}
                title={t('wr.plan_chip_hint', { defaultValue: '{{ref}} · {{title}}\nDrag onto a day to put one person on it, click to open', ref: req.reference, title: req.title })}
                onDragStart={(e) => {
                  setDrag(req.id);
                  try {
                    if (e.dataTransfer) {
                      e.dataTransfer.effectAllowed = 'move';
                      e.dataTransfer.setData('text/plain', `${DRAG_PREFIX}${req.id}`);
                    }
                  } catch {
                    /* no DataTransfer - the drag still works */
                  }
                }}
                onDragEnd={() => {
                  setDrag(null);
                  setHot(null);
                }}
                onClick={() => onOpen(req)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onOpen(req);
                }}
                onContextMenu={(e) => actions?.openMenu(e, req)}
              >
                <b>{req.reference}</b>
                <span className="ttl">{req.title}</span>
                <Avatars people={req.assignees} max={2} />
              </span>
            ))}
          </div>
        </div>
      )}

      {planner.data && (
        <div ref={wrapRef} className={clsx('wr-plan', edge.l && 'sl', edge.r && 'sr', paint && 'painting', drag && 'dropping')} onScroll={measure}>
          <table className="wr-grid" ref={gridRef}>
            <thead>
              <tr>
                <th className="first" rowSpan={2}>
                  <span className="hd">
                    {/* The arrow lives IN the sticky column, not over it. */}
                    <button
                      type="button"
                      className="wr-gscroll prev"
                      tabIndex={-1}
                      aria-hidden={!edge.l}
                      aria-label={t('wr.scroll_left', { defaultValue: 'Scroll {{what}} left', what: t('wr.view_planner', { defaultValue: 'Planner' }) })}
                      onClick={() => nudge(-1)}
                    >
                      <ChevronLeft size={14} aria-hidden />
                    </button>
                    {t('wr.planner_request', { defaultValue: 'Request' })}
                  </span>
                </th>
                {days.map((w) => (
                  <th key={w.monday} className="week" colSpan={w.days.length}>
                    {t('wr.week_of', { defaultValue: 'Week of {{d}}', d: fmtDayShort(w.monday) })}
                  </th>
                ))}
                <th className="tot" rowSpan={2}>
                  <span className="hd">
                    {t('wr.planner_total', { defaultValue: 'Planned / quoted' })}
                    <button
                      type="button"
                      className="wr-gscroll next"
                      tabIndex={-1}
                      aria-hidden={!edge.r}
                      aria-label={t('wr.scroll_right', { defaultValue: 'Scroll {{what}} right', what: t('wr.view_planner', { defaultValue: 'Planner' }) })}
                      onClick={() => nudge(1)}
                    >
                      <ChevronRight size={14} aria-hidden />
                    </button>
                  </span>
                </th>
              </tr>
              <tr>
                {flatDays.map((d, i) => {
                  const head = dayHead(d, flatDays[i - 1]);
                  return (
                    <th key={d} className={clsx('day', d === today && 'today', head.month && 'mstart')} title={fmtDay(d)}>
                      <span className="dow">{new Date(d + 'T00:00').toLocaleDateString(getIntlLocale(), { weekday: 'narrow' })}</span>{' '}
                      {head.day}
                      {head.month && <span className="mo">{head.month}</span>}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td className="first" colSpan={flatDays.length + 2}>
                    <span className="wr-hint">{t('wr.planner_empty', { defaultValue: 'No open requests in this department to plan.' })}</span>
                  </td>
                </tr>
              )}
              {rows.map((row, ri) => {
                const req = byId.get(row.request_id);
                const a = alloc[row.request_id] ?? row.alloc;
                const planned = rowHours(a);
                const quoted = req?.quoted_hours ?? null;
                const over = quoted !== null && planned > quoted;
                return (
                  <tr key={row.request_id}>
                    <td className="first" onContextMenu={(e) => rowMenu(e, row)} data-testid={`wr-plan-row-${row.request_id}`}>
                      <span className="ttl" title={row.title}>
                        {row.title}
                      </span>
                      <span className="sub">
                        <RefChip reference={row.reference} colour={dept.colour} onClick={() => req && onOpen(req)} />
                        <span className="wr-mono">{row.project_code}</span>
                        <StagePill dept={dept} stage={row.stage} />
                        <Avatars people={row.assignees} max={3} />
                        {req && (
                          <label className="wr-tog" title={t('wr.uploaded_hint', { defaultValue: 'Ticked once this request is in the department planner workbook' })}>
                            <input
                              type="checkbox"
                              checked={req.planner_uploaded}
                              onChange={async (e) => {
                                try {
                                  await patchRequest(req.id, { planner_uploaded: e.target.checked });
                                  void qc.invalidateQueries({ queryKey: [WR, 'requests'] });
                                } catch (err) {
                                  addToast({ type: 'error', title: errorText(err) });
                                }
                              }}
                            />
                            {t('wr.uploaded', { defaultValue: 'Uploaded to planner' })}
                          </label>
                        )}
                      </span>
                    </td>
                    {flatDays.map((d, ci) => (
                      <Cell
                        key={d}
                        r={ri}
                        c={ci}
                        day={d}
                        rowId={row.request_id}
                        value={shown(row.request_id, d, a[d] ?? 0)}
                        ghost={!!paint && paint.rowId === row.request_id && paint.days.includes(d)}
                        weekStart={days.some((w) => w.days[0] === d)}
                        today={d === today}
                        saving={saving.has(row.request_id)}
                        hot={hot === d && !!drag}
                        onKey={onKey}
                        onPress={(e) => startPress(e, row.request_id, d, a[d] ?? 0)}
                        onMenu={(e) => cellMenu(e, row.request_id, d, row.reference)}
                        onDragOver={(e) => allowDay(e, d)}
                        onDrop={(e) => void dropDay(e, d)}
                        onCommit={(v) => {
                          const next = { ...a, [d]: v };
                          if ((a[d] ?? 0) === v) return;
                          setAlloc((s) => ({ ...s, [row.request_id]: next }));
                          void commitRow(row.request_id, next);
                        }}
                      />
                    ))}
                    <td className={clsx('tot', over && 'wr-dev over')}>
                      {fmtHours(planned)} <span className="vs">/ {fmtHours(quoted)}</span>
                    </td>
                  </tr>
                );
              })}
              <tr className="cap">
                <td className="first">
                  <span className="ttl">{t('wr.capacity', { defaultValue: 'Capacity' })}</span>
                  <span className="sub">{t('wr.capacity_sub', { defaultValue: 'available heads (edit) · allocated below' })}</span>
                </td>
                {flatDays.map((d, ci) => {
                  const allocated = columnHeads(rows.map((r) => ({ alloc: alloc[r.request_id] ?? r.alloc })), d);
                  const available = shown(CAP_ROW, d, cap[d] ?? planner.data?.capacity?.[d]?.available ?? 0);
                  return (
                    <Cell
                      key={d}
                      r={rows.length}
                      c={ci}
                      day={d}
                      rowId={CAP_ROW}
                      value={available}
                      ghost={!!paint && paint.rowId === CAP_ROW && paint.days.includes(d)}
                      weekStart={days.some((w) => w.days[0] === d)}
                      today={d === today}
                      over={allocated > available}
                      note={`${allocated}`}
                      onKey={onKey}
                      onPress={(e) => startPress(e, CAP_ROW, d, cap[d] ?? 0)}
                      onMenu={(e) => cellMenu(e, CAP_ROW, d, t('wr.capacity', { defaultValue: 'Capacity' }))}
                      onCommit={(v) => {
                        if ((cap[d] ?? 0) === v) return;
                        const next = { ...cap, [d]: v };
                        setCap(next);
                        void commitCap(next);
                      }}
                    />
                  );
                })}
                <td className="tot">
                  {fmtHours(sum(flatDays.map((d) => (cap[d] ?? 0) * HOURS_PER_HEAD_DAY)))}{' '}
                  <span className="vs">{t('wr.available', { defaultValue: 'available' })}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {menu.element}
    </div>
  );
}

function Cell({
  r,
  c,
  day,
  rowId,
  value,
  ghost,
  weekStart,
  today,
  saving,
  over,
  hot,
  note,
  onKey,
  onCommit,
  onPress,
  onMenu,
  onDragOver,
  onDrop,
}: {
  r: number;
  c: number;
  day: string;
  rowId: string;
  value: number;
  /** Part of the live paint preview - shown, not saved. */
  ghost?: boolean;
  weekStart: boolean;
  today: boolean;
  saving?: boolean;
  over?: boolean;
  hot?: boolean;
  note?: string;
  onKey: (e: KeyboardEvent<HTMLInputElement>, r: number, c: number, commit: () => void, revert: () => void) => void;
  onCommit: (v: number) => void;
  onPress?: (e: ReactPointerEvent) => void;
  onMenu?: (e: ReactMouseEvent) => void;
  onDragOver?: (e: DragEvent) => void;
  onDrop?: (e: DragEvent) => void;
}) {
  const [text, setText] = useState(value ? String(value) : '');
  useEffect(() => setText(value ? String(value) : ''), [value]);
  const commit = () => {
    const n = Number(text.replace(',', '.'));
    onCommit(Number.isFinite(n) && n > 0 ? Math.round(n * 10) / 10 : 0);
  };
  const revert = () => setText(value ? String(value) : '');
  return (
    <td
      className={clsx('cell', value > 0 && 'has', ghost && 'ghost', weekStart && 'week-start', today && 'today', saving && 'saving', over && 'over', hot && 'hot')}
      data-day={day}
      data-row={rowId}
      onPointerDown={onPress}
      onContextMenu={onMenu}
      onDragOver={onDragOver}
      onDragEnter={onDragOver}
      onDrop={onDrop}
    >
      <input
        type="text"
        inputMode="decimal"
        value={text}
        data-r={r}
        data-c={c}
        aria-label={`${day}`}
        onChange={(e) => setText(e.target.value.replace(/[^\d.,]/g, ''))}
        onBlur={commit}
        onFocus={(e) => e.target.select()}
        onKeyDown={(e) => onKey(e, r, c, commit, revert)}
      />
      {note !== undefined && <span className="a">{note}</span>}
    </td>
  );
}
