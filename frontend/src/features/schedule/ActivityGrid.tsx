// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, RotateCcw, GitBranch, Diamond, Minus, Users } from 'lucide-react';
import { Button, Badge, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { listCalendars } from '@/features/schedule-advanced/api';
import { listAssignmentsForActivity, listResources } from '@/features/resources/api';
import { scheduleApi, type Activity } from './api';
import { fmtList } from '@/shared/lib/formatters';
import {
  autoFitWidth,
  clampWidth,
  clearWidths,
  fitColumnWidths,
  loadWidths,
  resolveWidths,
  saveWidths,
  textMeasurer,
  totalWidth,
  CELL_CHROME,
  type ColumnSpec,
  type ColumnWidths,
} from './columnWidths';
import { DeliveryCell } from './DeliveryCell';
import { emptyDelivery, type DeliveryIndex } from './delivery';

const TYPES = ['task', 'milestone', 'summary'] as const;

const CELL_INPUT_CLS =
  'w-full rounded-md border border-transparent bg-transparent px-2 py-1 text-sm text-content-primary ' +
  'hover:border-border-light focus:border-oe-blue focus:bg-surface-primary focus:outline-none disabled:opacity-60';

const DATE_INPUT_CLS =
  'w-full rounded-md border border-transparent bg-transparent px-1.5 py-1 text-sm tabular-nums text-content-primary ' +
  'hover:border-border-light focus:border-oe-blue focus:bg-surface-primary focus:outline-none disabled:opacity-60';

/**
 * The grid's columns, and the narrowest each may be dragged to.
 *
 * The minimum here is a *floor*; the real minimum is raised at runtime to the
 * measured width of the column's own header label, because a header reading
 * "Predecess…" is a worse table than one that scrolls.
 */
const BASE_COLUMN_SPECS: ColumnSpec[] = [
  { key: 'wbs', min: 56, def: 76 },
  { key: 'name', min: 160, def: 280 },
  { key: 'type', min: 88, def: 110 },
  { key: 'start', min: 108, def: 128 },
  { key: 'end', min: 108, def: 128 },
  { key: 'duration', min: 72, def: 88 },
  { key: 'progress', min: 76, def: 92 },
  { key: 'calendar', min: 96, def: 128 },
  { key: 'resources', min: 100, def: 150 },
  { key: 'delivery', min: 130, def: 210 },
  { key: 'deps', min: 104, def: 132 },
];

/** The column spare width flows into while the user has not set widths. */
const GROW_KEY = 'name';

/** Furniture a column carries beyond its text (badges, icons, a select arrow). */
function columnExtra(key: string): number {
  if (key === 'name') return 46; // CP badge + milestone glyph + input padding
  if (key === 'type' || key === 'calendar') return 22; // the select's arrow
  if (key === 'deps') return 30; // the branch icon and the button's border
  if (key === 'delivery') return 58; // the chip's dot, icon and the Link button
  return 0;
}

/** Whole calendar-day count from ISO ``a`` to ISO ``b`` (b - a); may be negative. */
function isoDeltaDays(a: string, b: string): number {
  const ms = new Date(b).getTime() - new Date(a).getTime();
  if (Number.isNaN(ms)) return 0;
  return Math.round(ms / 86_400_000);
}

/** Add ``days`` calendar days to an ISO ``YYYY-MM-DD`` date (UTC, stays YYYY-MM-DD). */
function addDaysIso(iso: string, days: number): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** What the schedule page hands down so the Delivery column can render. */
export interface GridDelivery {
  index: DeliveryIndex;
  doneStages: Set<string>;
  today: string;
  departmentColour: (key: string) => string | undefined;
  onOpenLinks: (activityId: string) => void;
}

/**
 * Editable activity grid - the schedule "Table" view.
 *
 * A spreadsheet-style table of every activity with inline-editable name, type,
 * start and end. Duration is shown read-only because it is *working* days:
 * the backend recomputes ``duration_days`` from the dates on every update using
 * the project's regional work calendar (skipping weekends / holidays), so it
 * cannot be honestly derived from a calendar-day span on the client. Editing the
 * start moves the whole bar (the end shifts by the same number of calendar days
 * so the span is preserved); editing the end changes the span.
 *
 * Each cell commit writes through the existing ``updateActivity`` PATCH (which
 * recomputes the working-day duration server-side) and refetches the Gantt. The
 * predecessors cell opens the shared #348 dependency editor via ``onEditDependencies``.
 * The explicit Reschedule button recomputes dates from the dependency network
 * (CPM) - activities with predecessors move, roots keep their manual start - so
 * a bulk edit does not silently overwrite typed dates mid-flight.
 *
 * **Column widths.** Every column carries a drag grip on its right border;
 * double-clicking a grip auto-fits that column to its widest visible cell, and
 * right-clicking the header offers Reset / Fit all. Widths are stored per user
 * in localStorage keyed by schedule id. The stored widths are the *user's*
 * numbers and are never overwritten by layout: what renders is the stored map
 * put through ``fitColumnWidths`` against the live wrap width, so a narrow
 * window squeezes the table without destroying the widths a wide one restores.
 */
export function ActivityGrid({
  scheduleId,
  projectId,
  activities,
  criticalActivityIds,
  onEditDependencies,
  onAddActivity,
  delivery,
}: {
  scheduleId: string;
  projectId: string;
  activities: Activity[];
  criticalActivityIds?: Set<string>;
  onEditDependencies: (activityId: string) => void;
  onAddActivity: () => void;
  /** Omitted when neither delivery module answered - the column disappears. */
  delivery?: GridDelivery;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const invalidateGantt = () =>
    queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });

  // #348: the project's named work calendars, for the per-row calendar picker.
  // Keyed by projectId so the picker and the WorkCalendarManager share a cache.
  const { data: calendars = [] } = useQuery({
    queryKey: ['schedule-calendars', projectId],
    queryFn: () => listCalendars(projectId),
    enabled: !!projectId,
  });

  // Who is booked on each activity, fanned out through ``useQueries``.
  //
  // One request per activity in the list this grid was handed, which is the
  // whole filtered schedule and not a page of it: a six-hundred-activity
  // schedule issues six hundred requests, six at a time through the browser's
  // per-host cap. That is the cost, stated plainly rather than hidden behind
  // the word "visible".
  //
  // It is still the honest read. The only project-wide assignment list the API
  // offers is the dispatcher board, and the board is keyed by resource: it
  // lists resources whose home project is this one or none, capped at 500, so
  // a crew homed on another project but booked here vanishes from it entirely,
  // and it is bounded by a date window an assignment can legitimately fall
  // outside of (the backend ships a validation rule for exactly that case). A
  // column that silently omits the rows it exists to show is worse than N
  // requests. The shared React Query cache dedupes in-flight duplicates and
  // keeps a revisit warm; the change that would collapse this to one call is a
  // project-scoped by-activity list on the backend, which does not exist yet.
  const assignmentQueries = useQueries({
    queries: projectId
      ? activities.map((a) => ({
          queryKey: ['resources', 'by-activity', a.id, projectId],
          queryFn: () => listAssignmentsForActivity(a.id, { project_id: projectId }),
          staleTime: 60_000,
        }))
      : [],
  });

  // An assignment carries a resource_id and no resource name - no endpoint
  // resolves one - so the register is read once and indexed here.
  const { data: resourcePage } = useQuery({
    queryKey: ['resources', 'list', 'all'],
    queryFn: () => listResources({ limit: 500 }),
    enabled: !!projectId && activities.length > 0,
    staleTime: 300_000,
  });
  // This is a lookup, not a register the reader browses, so it gets no
  // truncation notice. Worth knowing what a short page costs here: an id the
  // page did not carry renders as "Unnamed resource" below, which reads like
  // a resource with no name rather than like a lookup that ran out of rows.
  const resourceNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const r of resourcePage?.items ?? []) map[r.id] = r.name;
    return map;
  }, [resourcePage]);

  // Optimistic value for the per-row calendar picker while its change is in
  // flight, keyed by activity id (value is the calendar id, or null for the
  // project default). The <select> is controlled off this map layered over the
  // stored calendar_id, so it shows the picked calendar immediately, reflects
  // the real calendar once the async calendar list loads, and reverts to the
  // stored value if the save fails.
  const [pendingCal, setPendingCal] = useState<Record<string, string | null>>({});
  const calendarValue = (a: Activity) =>
    a.id in pendingCal ? (pendingCal[a.id] ?? '') : (a.calendar_id ?? '');

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Activity> }) =>
      scheduleApi.updateActivity(id, body),
    onSuccess: invalidateGantt,
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.update_failed', { defaultValue: 'Update failed' }),
        message: error.message,
      });
      // Refetch so a rejected cell reverts to the stored value.
      invalidateGantt();
    },
  });

  const rescheduleMutation = useMutation({
    mutationFn: () => scheduleApi.reschedule(scheduleId),
    onSuccess: async () => {
      await invalidateGantt();
      addToast({
        type: 'success',
        title: t('schedule.rescheduled', { defaultValue: 'Schedule recalculated' }),
      });
    },
    onError: (error: Error) =>
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      }),
  });

  // #348: assign (calendarId) or clear (null) an activity's work calendar, then
  // recompute dates from the network - working-day durations depend on the
  // calendar - and refetch the edges + bars. Mirrors DependencyEditor.afterChange().
  const setCalendarMutation = useMutation({
    mutationFn: ({ id, calendarId }: { id: string; calendarId: string | null }) =>
      scheduleApi.setActivityCalendar(id, calendarId),
    onSuccess: async () => {
      await scheduleApi.reschedule(scheduleId);
      await queryClient.invalidateQueries({ queryKey: ['schedule-relationships', scheduleId] });
      await queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
      addToast({
        type: 'success',
        title: t('schedule.calendar.assigned', { defaultValue: 'Calendar updated' }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
      invalidateGantt();
    },
    // Drop the optimistic value once the change settles: on success the gantt
    // has been refetched so the stored calendar_id now matches; on failure the
    // select falls back to the unchanged stored value.
    onSettled: (_data, _err, variables) => {
      setPendingCal((m) => {
        const next = { ...m };
        delete next[variables.id];
        return next;
      });
    },
  });

  const busy =
    updateMutation.isPending || rescheduleMutation.isPending || setCalendarMutation.isPending;
  // Only an operation that moves rows (a full reschedule, or a calendar change
  // that reschedules) locks editing; per-cell PATCHes leave the grid editable.
  const cellsDisabled = rescheduleMutation.isPending || setCalendarMutation.isPending;

  // ── Cell commit handlers ────────────────────────────────────────────────
  const commitName = (a: Activity, raw: string) => {
    const name = raw.trim();
    if (!name || name === a.name) return;
    updateMutation.mutate({ id: a.id, body: { name } });
  };

  const commitType = (a: Activity, type: string) => {
    if (type === a.activity_type) return;
    updateMutation.mutate({ id: a.id, body: { activity_type: type } });
  };

  const commitStart = (a: Activity, raw: string) => {
    const start = raw.slice(0, 10);
    const current = a.start_date.slice(0, 10);
    if (!start || start === current) return;
    if (Number.isNaN(new Date(start).getTime())) {
      invalidateGantt();
      return;
    }
    // Preserve the calendar span: shift the end by the same delta as the start.
    const delta = isoDeltaDays(current, start);
    const end = addDaysIso(a.end_date.slice(0, 10), delta);
    updateMutation.mutate({ id: a.id, body: { start_date: start, end_date: end } });
  };

  const commitEnd = (a: Activity, raw: string) => {
    const end = raw.slice(0, 10);
    const current = a.end_date.slice(0, 10);
    if (!end || end === current) return;
    const start = a.start_date.slice(0, 10);
    // Reject an end before the start (the backend would 422); refetch to revert.
    if (Number.isNaN(new Date(end).getTime()) || isoDeltaDays(start, end) < 0) {
      invalidateGantt();
      return;
    }
    updateMutation.mutate({ id: a.id, body: { end_date: end } });
  };

  const commitCalendar = (a: Activity, raw: string) => {
    // Empty value -> clear (fall back to the project default). No-op if unchanged.
    const next = raw || null;
    if ((a.calendar_id ?? null) === next) return;
    setPendingCal((m) => ({ ...m, [a.id]: next }));
    setCalendarMutation.mutate({ id: a.id, calendarId: next });
  };

  const hasDelivery = !!delivery;
  const columns = useMemo(
    () =>
      [
        { key: 'wbs', label: t('schedule.wbs_code', { defaultValue: 'WBS' }), align: 'left' as const },
        { key: 'name', label: t('schedule.activity_name', { defaultValue: 'Activity' }), align: 'left' as const },
        { key: 'type', label: t('schedule.activity_type', { defaultValue: 'Type' }), align: 'left' as const },
        { key: 'start', label: t('schedule.start_date', { defaultValue: 'Start' }), align: 'left' as const },
        { key: 'end', label: t('schedule.end_date', { defaultValue: 'End' }), align: 'left' as const },
        { key: 'duration', label: t('schedule.duration', { defaultValue: 'Duration' }), align: 'right' as const },
        { key: 'progress', label: t('schedule.progress', { defaultValue: 'Progress' }), align: 'right' as const },
        { key: 'calendar', label: t('schedule.calendar.column', { defaultValue: 'Calendar' }), align: 'left' as const },
        { key: 'resources', label: t('schedule.assigned_resources', { defaultValue: 'Resources' }), align: 'left' as const },
        ...(hasDelivery
          ? [
              {
                key: 'delivery',
                label: t('schedule.delivery.column', { defaultValue: 'Delivery' }),
                align: 'left' as const,
              },
            ]
          : []),
        { key: 'deps', label: t('schedule.predecessors', { defaultValue: 'Predecessors' }), align: 'left' as const },
      ],
    [t, hasDelivery],
  );

  /* ── Column widths ─────────────────────────────────────────────────────
     The stored map is the user's; what renders is that map fitted to the
     wrap. Splitting the two is what lets a window shrink and grow back
     without silently eating the widths that were dragged. */

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const headRef = useRef<HTMLTableSectionElement | null>(null);
  const storageKey = scheduleId || projectId || 'default';

  const [userWidths, setUserWidths] = useState<ColumnWidths>(() =>
    resolveWidths(BASE_COLUMN_SPECS, loadWidths(storageKey)),
  );
  /** The user has set widths, so spare space stops flowing into the name column. */
  const [dirty, setDirty] = useState<boolean>(() => loadWidths(storageKey) !== null);
  const [avail, setAvail] = useState(0);
  const [headerMins, setHeaderMins] = useState<Record<string, number>>({});
  const [dragging, setDragging] = useState<{ key: string; startX: number; guideX: number } | null>(
    null,
  );
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);

  /** Only the columns actually rendered, with header-derived minimums. */
  const specs = useMemo<ColumnSpec[]>(() => {
    const keys = new Set<string>(columns.map((c) => c.key));
    return BASE_COLUMN_SPECS.filter((s) => keys.has(s.key)).map((s) => ({
      ...s,
      min: Math.max(s.min, headerMins[s.key] ?? 0),
    }));
  }, [columns, headerMins]);

  // Measure the header labels once they are on screen. Their real rendered
  // width is the only honest floor for a column: it is font-, locale- and
  // zoom-dependent, and guessing it in CSS pixels is how a translated header
  // ends up clipped in one language and fine in another.
  useLayoutEffect(() => {
    const head = headRef.current;
    if (!head) return;
    const next: Record<string, number> = {};
    head.querySelectorAll<HTMLElement>('[data-collabel]').forEach((el) => {
      const key = el.dataset.collabel;
      if (!key) return;
      const w = Math.ceil(el.scrollWidth);
      if (w > 0) next[key] = w + CELL_CHROME;
    });
    setHeaderMins((prev) => {
      const same =
        Object.keys(next).length === Object.keys(prev).length &&
        Object.entries(next).every(([k, v]) => prev[k] === v);
      return same ? prev : next;
    });
  }, [columns]);

  // The wrap's inner width, watched so a sidebar collapse or a window resize
  // re-fits. ResizeObserver is absent in jsdom and in older engines; the
  // window listener alone still covers the common case.
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const read = () => setAvail(wrap.clientWidth);
    read();
    window.addEventListener('resize', read);
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(read);
      ro.observe(wrap);
    }
    return () => {
      window.removeEventListener('resize', read);
      ro?.disconnect();
    };
  }, []);

  const widths = useMemo(
    () => fitColumnWidths(specs, userWidths, avail, GROW_KEY, { expand: !dirty, shrink: !dirty }),
    [specs, userWidths, avail, dirty],
  );
  const tableWidth = totalWidth(specs, widths);

  const commitWidths = useCallback(
    (next: ColumnWidths) => {
      setUserWidths(next);
      setDirty(true);
      saveWidths(storageKey, next);
    },
    [storageKey],
  );

  /** The strings a column's cells actually contain, for auto-fit. */
  const columnTexts = useCallback(
    (key: string): string[] => {
      switch (key) {
        case 'wbs':
          return activities.map((a) => a.wbs_code || '-');
        case 'name':
          return activities.map((a) => a.name);
        case 'type':
          return TYPES.map((tp) => t(`schedule.type_${tp}`, { defaultValue: tp }));
        case 'start':
        case 'end':
          return ['0000-00-00'];
        case 'duration':
          return activities.map(
            (a) => `${a.duration_days} ${t('schedule.days_short', { defaultValue: 'd' })}`,
          );
        case 'progress':
          return activities.map((a) => `${a.progress_pct}%`);
        case 'calendar':
          return [
            t('schedule.calendar.default_option', { defaultValue: 'Default' }),
            ...calendars.map((c) => c.name),
          ];
        case 'resources':
          return assignmentQueries.map((q) =>
            fmtList(
              (q?.data ?? [])
                .filter((as) => as.status !== 'cancelled')
                .map((as) => resourceNameById[as.resource_id] ?? ''),
            ),
          );
        case 'delivery':
          return activities.flatMap((a) => {
            const d = delivery?.index[a.id];
            if (!d) return [];
            return [
              ...d.requests.map((r) => r.reference || r.title),
              ...d.tasks.map((x) => x.title),
            ];
          });
        case 'deps':
          return [t('schedule.add_predecessor', { defaultValue: 'Add predecessor' })];
        default:
          return [];
      }
    },
    [activities, assignmentQueries, calendars, delivery, resourceNameById, t],
  );

  const fitColumn = useCallback(
    (key: string, from: ColumnWidths): ColumnWidths => {
      const spec = specs.find((s) => s.key === key);
      if (!spec) return from;
      const measure = textMeasurer('14px ui-sans-serif, system-ui, -apple-system, sans-serif');
      const texts = columnTexts(key);
      const header = headerMins[key] ?? 0;
      const fitted = autoFitWidth(texts, measure, {
        min: spec.min,
        extra: columnExtra(key),
      });
      return { ...from, [key]: clampWidth(spec, Math.max(fitted, header)) };
    },
    [columnTexts, headerMins, specs],
  );

  const autoFitOne = useCallback(
    (key: string) => commitWidths(fitColumn(key, widths)),
    [commitWidths, fitColumn, widths],
  );

  const autoFitAll = useCallback(() => {
    let next = { ...widths };
    for (const s of specs) next = fitColumn(s.key, next);
    commitWidths(next);
    setMenu(null);
  }, [commitWidths, fitColumn, specs, widths]);

  const resetWidths = useCallback(() => {
    clearWidths(storageKey);
    setUserWidths(resolveWidths(BASE_COLUMN_SPECS, null));
    setDirty(false);
    setMenu(null);
  }, [storageKey]);

  // Pointer drag.
  //
  // The document listeners are attached inside the mousedown handler, NOT from
  // an effect keyed on the drag state. An effect only runs after React has
  // committed, so a drag whose move and release land in the same frame as the
  // press - a flick of the wrist, and every synthetic drag a test harness
  // sends - would be over before anything was listening, and the column would
  // not move. Attaching synchronously means the very next mousemove counts.
  //
  // They live on the document rather than the 8px grip so a fast drag that
  // outruns the pointer keeps resizing, and the teardown is kept in a ref so
  // an unmount mid-drag cannot leak them.
  const dragCleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => dragCleanup.current?.(), []);

  const startDrag = useCallback(
    (key: string, clientX: number) => {
      const spec = specs.find((s) => s.key === key);
      if (!spec) return;
      // Freeze the fitted widths as the new baseline: without this, dragging
      // one column re-runs the fit against widths that were never the user's
      // and its neighbours jump.
      const base: ColumnWidths = { ...widths };
      const startWidth = base[key] ?? spec.def;
      const guideAt = (x: number) => {
        const wrap = wrapRef.current;
        if (!wrap) return x;
        return x - wrap.getBoundingClientRect().left + wrap.scrollLeft;
      };
      const widthAt = (x: number) => clampWidth(spec, startWidth + (x - clientX));

      const onMove = (e: MouseEvent) => {
        setUserWidths({ ...base, [key]: widthAt(e.clientX) });
        setDirty(true);
        setDragging((d) => (d ? { ...d, guideX: guideAt(e.clientX) } : d));
      };
      const teardown = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.classList.remove('select-none');
        dragCleanup.current = null;
      };
      function onUp(e: MouseEvent) {
        commitWidths({ ...base, [key]: widthAt(e.clientX) });
        setDragging(null);
        teardown();
      }

      setDragging({ key, startX: clientX, guideX: guideAt(clientX) });
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      document.body.classList.add('select-none');
      dragCleanup.current = teardown;
    },
    [commitWidths, specs, widths],
  );

  // Close the header menu on the next click or Escape.
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenu(null);
    };
    document.addEventListener('click', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  const nudge = (key: string, by: number) => {
    const spec = specs.find((s) => s.key === key);
    if (!spec) return;
    commitWidths({ ...widths, [key]: clampWidth(spec, (widths[key] ?? spec.def) + by) });
  };

  return (
    <Card padding="none" className="overflow-hidden">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light bg-surface-secondary/40 px-3 py-2">
        <span className="text-xs text-content-tertiary">
          {t('schedule.grid_hint_resizable', {
            defaultValue:
              'Edit names, dates and types inline. Duration is working days and updates automatically. Drag a column border to resize; double-click it to fit.',
          })}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={15} />}
            data-testid="grid-add-activity"
            disabled={busy}
            onClick={onAddActivity}
          >
            {t('schedule.add_activity', { defaultValue: 'Add activity' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<RotateCcw size={15} />}
            data-testid="grid-reschedule"
            loading={rescheduleMutation.isPending}
            disabled={busy}
            onClick={() => rescheduleMutation.mutate()}
            title={t('schedule.reschedule_tooltip', {
              defaultValue:
                'Recompute dates from the dependency network (CPM). Activities with predecessors move; roots keep their manual start.',
            })}
          >
            {t('schedule.reschedule', { defaultValue: 'Reschedule' })}
          </Button>
        </div>
      </div>

      <div className="relative overflow-x-auto" ref={wrapRef}>
        {/* Live guideline: the drag has to show where the border is going. */}
        {dragging && (
          <div
            aria-hidden
            data-testid="col-resize-guide"
            className="pointer-events-none absolute inset-y-0 z-20 w-px bg-oe-blue"
            style={{ left: Math.max(0, dragging.guideX) }}
          />
        )}
        <table
          data-testid="activity-grid"
          className="border-collapse text-sm"
          style={{ tableLayout: 'fixed', width: tableWidth < avail ? '100%' : tableWidth }}
        >
          <colgroup>
            {specs.map((s) => (
              <col key={s.key} data-col={s.key} style={{ width: widths[s.key] }} />
            ))}
            {/* Absorbs the slack once the user has set their own widths, so the
                header rule runs the full width of the wrap instead of stopping
                short with a bare strip beside it. */}
            <col data-col="spacer" />
          </colgroup>
          <thead ref={headRef}>
            <tr
              className="border-b border-border-light bg-surface-secondary/30 text-2xs font-semibold uppercase tracking-wider text-content-tertiary"
              onContextMenu={(e) => {
                e.preventDefault();
                const box = wrapRef.current?.getBoundingClientRect();
                setMenu({ x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0) });
              }}
            >
              {columns.map((c) => (
                <th
                  key={c.key}
                  data-col={c.key}
                  className={`relative px-3 py-2 font-semibold ${c.align === 'right' ? 'text-right' : 'text-left'}`}
                >
                  {/* inline-block, NOT block: a block-level label is stretched
                      to the cell, and `scrollWidth` on a stretched box reports
                      the box, not the text - so the measured "minimum" below
                      would ratchet up to whatever width the column already had
                      and no column could ever be narrowed again. Shrink-wrapped,
                      it reports the text. */}
                  <span
                    data-collabel={c.key}
                    className="inline-block max-w-full overflow-hidden text-ellipsis whitespace-nowrap align-bottom"
                    title={c.label}
                  >
                    {c.label}
                  </span>
                  <button
                    type="button"
                    aria-label={t('schedule.resize_column', {
                      defaultValue: 'Resize the {{column}} column',
                      column: c.label,
                    })}
                    data-testid={`col-grip-${c.key}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      startDrag(c.key, e.clientX);
                    }}
                    onDoubleClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      autoFitOne(c.key);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'ArrowLeft') {
                        e.preventDefault();
                        nudge(c.key, -16);
                      } else if (e.key === 'ArrowRight') {
                        e.preventDefault();
                        nudge(c.key, 16);
                      } else if (e.key === 'Enter') {
                        e.preventDefault();
                        autoFitOne(c.key);
                      }
                    }}
                    title={t('schedule.resize_hint', {
                      defaultValue: 'Drag to resize · double-click to fit · right-click for more',
                    })}
                    // No outward translate: a grip nudged past the last
                    // column's right edge overflows the wrap by its own width
                    // and buys a horizontal scrollbar under a table that fits.
                    className={`absolute inset-y-0 right-0 z-10 w-2 cursor-col-resize border-r-2 transition-colors focus:outline-none focus-visible:border-oe-blue ${
                      dragging?.key === c.key
                        ? 'border-oe-blue'
                        : 'border-transparent hover:border-oe-blue/60'
                    }`}
                  />
                </th>
              ))}
              <th aria-hidden className="px-0 py-2" />
            </tr>
          </thead>
          <tbody>
            {activities.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length + 1}
                  className="px-3 py-6 text-center text-sm text-content-tertiary"
                >
                  {t('schedule.grid_empty', {
                    defaultValue: 'No activities match the current filter.',
                  })}
                </td>
              </tr>
            ) : (
              activities.map((a, rowIdx) => {
                const isCritical = criticalActivityIds?.has(a.id) ?? false;
                const depCount = a.dependencies?.length ?? 0;
                const isMilestone = a.activity_type === 'milestone';
                const isSummary = a.activity_type === 'summary';
                const assignQuery = assignmentQueries[rowIdx];
                const rowDelivery = delivery?.index[a.id] ?? emptyDelivery();
                // Cancelled bookings staff nothing, so they are not shown. An
                // id the register did not return still counts: dropping it
                // would under-report the row rather than admit the gap.
                const assignedNames = (assignQuery?.data ?? [])
                  .filter((as) => as.status !== 'cancelled')
                  .map(
                    (as) =>
                      resourceNameById[as.resource_id] ??
                      t('schedule.assigned_unknown_resource', {
                        defaultValue: 'Unnamed resource',
                      }),
                  );
                return (
                  <tr
                    key={a.id}
                    data-testid={`grid-row-${a.id}`}
                    data-delivery-risk={rowDelivery.atRisk ? 'true' : undefined}
                    className={`border-b border-border-light transition-colors hover:bg-surface-secondary/20${
                      isCritical ? ' bg-semantic-error/5' : ''
                    }${
                      // A late or blocked attachment is a programme fact, so it
                      // marks the row rather than living only in one cell.
                      rowDelivery.atRisk ? ' border-l-2 border-l-semantic-error' : ''
                    }`}
                  >
                    <td className="truncate px-3 py-1.5 align-middle tabular-nums text-content-tertiary">
                      {a.wbs_code || '-'}
                    </td>
                    <td className="px-2 py-1.5 align-middle">
                      <div className="flex items-center gap-1.5">
                        {isCritical && (
                          <span className="shrink-0 rounded bg-semantic-error px-1 py-0.5 text-[9px] font-bold leading-none text-white">
                            CP
                          </span>
                        )}
                        {isMilestone && (
                          <Diamond size={11} className="shrink-0 text-oe-blue" fill="currentColor" />
                        )}
                        {isSummary && <Minus size={11} className="shrink-0 text-content-tertiary" />}
                        <input
                          key={`name-${a.id}-${a.name}`}
                          data-testid={`grid-name-${a.id}`}
                          aria-label={t('schedule.activity_name', { defaultValue: 'Activity name' })}
                          className={CELL_INPUT_CLS}
                          defaultValue={a.name}
                          title={a.name}
                          disabled={cellsDisabled}
                          onBlur={(e) => commitName(a, e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') e.currentTarget.blur();
                          }}
                        />
                      </div>
                    </td>
                    <td className="px-2 py-1.5 align-middle">
                      <select
                        key={`type-${a.id}-${a.activity_type}`}
                        data-testid={`grid-type-${a.id}`}
                        aria-label={t('schedule.activity_type', { defaultValue: 'Type' })}
                        className={CELL_INPUT_CLS}
                        defaultValue={a.activity_type}
                        disabled={cellsDisabled}
                        onChange={(e) => commitType(a, e.target.value)}
                      >
                        {TYPES.map((tp) => (
                          <option key={tp} value={tp}>
                            {t(`schedule.type_${tp}`, { defaultValue: tp })}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-1.5 align-middle">
                      <input
                        type="date"
                        key={`start-${a.id}-${a.start_date}`}
                        data-testid={`grid-start-${a.id}`}
                        aria-label={t('schedule.start_date', { defaultValue: 'Start date' })}
                        className={DATE_INPUT_CLS}
                        defaultValue={a.start_date.slice(0, 10)}
                        disabled={cellsDisabled}
                        onBlur={(e) => commitStart(a, e.target.value)}
                      />
                    </td>
                    <td className="px-2 py-1.5 align-middle">
                      <input
                        type="date"
                        key={`end-${a.id}-${a.end_date}`}
                        data-testid={`grid-end-${a.id}`}
                        aria-label={t('schedule.end_date', { defaultValue: 'End date' })}
                        className={DATE_INPUT_CLS}
                        defaultValue={a.end_date.slice(0, 10)}
                        disabled={cellsDisabled}
                        onBlur={(e) => commitEnd(a, e.target.value)}
                      />
                    </td>
                    <td
                      data-testid={`grid-duration-${a.id}`}
                      className="px-3 py-1.5 text-right align-middle tabular-nums text-content-secondary"
                    >
                      {a.duration_days} {t('schedule.days_short', { defaultValue: 'd' })}
                    </td>
                    <td className="px-3 py-1.5 text-right align-middle">
                      <Badge variant={isCritical ? 'error' : 'neutral'} size="sm">
                        {a.progress_pct}%
                      </Badge>
                    </td>
                    <td className="px-2 py-1.5 align-middle">
                      <select
                        data-testid={`grid-calendar-${a.id}`}
                        aria-label={t('schedule.calendar.column', { defaultValue: 'Calendar' })}
                        className={CELL_INPUT_CLS}
                        value={calendarValue(a)}
                        disabled={cellsDisabled}
                        onChange={(e) => commitCalendar(a, e.target.value)}
                      >
                        <option value="">
                          {t('schedule.calendar.default_option', { defaultValue: 'Default' })}
                        </option>
                        {calendars.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td
                      className="px-3 py-1.5 align-middle"
                      data-testid={`grid-resources-${a.id}`}
                    >
                      {/* No project scope means nothing was asked, so the cell
                          claims nothing rather than reading as "none". */}
                      {!assignQuery ? null : assignQuery.isPending ? (
                        <span className="inline-block h-3 w-16 animate-pulse rounded bg-surface-secondary" />
                      ) : assignedNames.length === 0 ? (
                        <span className="text-content-tertiary">-</span>
                      ) : (
                        <span
                          className="inline-flex max-w-full items-center gap-1 text-xs text-content-secondary"
                          title={fmtList(assignedNames)}
                        >
                          <Users size={12} className="shrink-0 text-content-tertiary" />
                          <span className="truncate">{fmtList(assignedNames)}</span>
                        </span>
                      )}
                    </td>
                    {delivery && (
                      <td className="px-2 py-1.5 align-middle">
                        <DeliveryCell
                          activityId={a.id}
                          delivery={rowDelivery}
                          doneStages={delivery.doneStages}
                          today={delivery.today}
                          departmentColour={delivery.departmentColour}
                          onOpenLinks={delivery.onOpenLinks}
                        />
                      </td>
                    )}
                    <td className="px-2 py-1.5 align-middle">
                      <button
                        type="button"
                        data-testid={`grid-deps-${a.id}`}
                        onClick={() => onEditDependencies(a.id)}
                        title={t('schedule.edit_predecessors', { defaultValue: 'Edit predecessors' })}
                        className="inline-flex max-w-full items-center gap-1 truncate rounded-md border border-border-light px-2 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue/40 hover:text-oe-blue"
                      >
                        <GitBranch size={13} className="shrink-0" />
                        {depCount > 0
                          ? String(depCount)
                          : t('schedule.add_predecessor', { defaultValue: 'Add predecessor' })}
                      </button>
                    </td>
                    <td aria-hidden className="px-0" />
                  </tr>
                );
              })
            )}
          </tbody>
        </table>

        {menu && (
          <div
            data-testid="col-header-menu"
            role="menu"
            className="absolute z-30 min-w-[180px] rounded-lg border border-border-light bg-surface-primary py-1 shadow-lg"
            style={{ left: menu.x, top: menu.y }}
          >
            <button
              type="button"
              role="menuitem"
              data-testid="col-menu-fit-all"
              className="block w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-secondary"
              onClick={autoFitAll}
            >
              {t('schedule.fit_all_columns', { defaultValue: 'Fit all columns' })}
            </button>
            <button
              type="button"
              role="menuitem"
              data-testid="col-menu-reset"
              className="block w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-secondary"
              onClick={resetWidths}
            >
              {t('schedule.reset_columns', { defaultValue: 'Reset column widths' })}
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}
