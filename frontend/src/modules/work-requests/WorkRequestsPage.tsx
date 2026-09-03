// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Work requests - the cross-department intake and tracker. Department
 * tabs across the top, four views (Board / List / Planner / My queue), a
 * job scope, filters, and "Raise a request". A request opens in a
 * slide-over; the same detail is a full page at /work-requests/:id.
 *
 * State lives in the URL (?dept=&view=&open=) via history.replaceState
 * rather than the router, so a reload lands on the same view and a link
 * to an open request can be shared.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ClipboardList, Download, Plus, Search, SlidersHorizontal } from 'lucide-react';
import clsx from 'clsx';
import { SideDrawer } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { bulkPatch, exportRequests, type BulkPatch, type Department, type Status, type WorkRequest } from './api';
import { useRequestActions } from './actions';
import { BulkBar, type BulkOutcome } from './BulkBar';
import { useMenu } from '../comms-intelligence/ContextMenu';
import { BoardView } from './BoardView';
import { MonthView } from './MonthView';
import { MyQueueView } from './MyQueueView';
import { PlannerView } from './PlannerView';
import { RequestTable } from './RequestTable';
import { RequestDetail } from './RequestDetail';
import { RaiseRequestDialog } from './RaiseRequestDialog';
import { ModuleMissing } from './ModuleMissing';
import { useCanManageWr, useDepartments, useInvalidateWr, useMe, useMyQueue, useRequests, useSummary, useUsers } from './hooks';
import { STATUS_LABEL, errorText, isLate, isModuleMissing, matchesText, matchesTypes, resolveColour, typesOf } from './lib';
import './wr.css';
import { fmtList } from '@/shared/lib/formatters';

type View = 'board' | 'list' | 'planner' | 'month' | 'queue';
/** The order the switcher offers them in - Month sits under the Planner. */
const VIEWS: View[] = ['board', 'list', 'planner', 'month', 'queue'];
const ALL_JOBS_KEY = 'wr-all-jobs';

/**
 * `?dept=&view=&open=`, plus the two the widgets outside this module
 * link with: the dashboard's department card sends `?department=` and
 * the project hub's raise button sends `?raise=1&project=`. Both used to
 * land on a bare, unfiltered board with nothing open - so both spellings
 * are read here rather than made someone else's problem.
 */
function readUrl(): { dept: string; view: View; open: string | null; raise: boolean; project: string | null } {
  try {
    const p = new URLSearchParams(window.location.search);
    const v = p.get('view') as View | null;
    return {
      dept: p.get('dept') || p.get('department') || 'all',
      view: v && VIEWS.includes(v) ? v : 'board',
      open: p.get('open'),
      raise: p.get('raise') === '1',
      project: p.get('project'),
    };
  } catch {
    return { dept: 'all', view: 'board', open: null, raise: false, project: null };
  }
}

function writeUrl(next: { dept: string; view: View; open: string | null }) {
  try {
    const p = new URLSearchParams(window.location.search);
    // The inbound-only aliases are consumed once and dropped, so a
    // reload does not re-open the raise dialog on top of the work.
    p.delete('department');
    p.delete('raise');
    p.delete('project');
    if (next.dept === 'all') p.delete('dept');
    else p.set('dept', next.dept);
    if (next.view === 'board') p.delete('view');
    else p.set('view', next.view);
    if (next.open) p.set('open', next.open);
    else p.delete('open');
    const qs = p.toString();
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${qs ? `?${qs}` : ''}`);
  } catch {
    /* not in a browser */
  }
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

export default function WorkRequestsPage() {
  const { t } = useTranslation();
  const params = useParams<{ projectId?: string }>();
  const routeProjectId = params.projectId ?? null;
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  const initial = useMemo(readUrl, []);
  const [dept, setDept] = useState(initial.dept);
  const [view, setView] = useState<View>(initial.view);
  const [openId, setOpenId] = useState<string | null>(initial.open);
  const [allJobs, setAllJobs] = useState<boolean>(() => {
    try {
      return localStorage.getItem(ALL_JOBS_KEY) === '1';
    } catch {
      return false;
    }
  });
  const [status, setStatus] = useState<Status | ''>('');
  /** Any-of. Several keys are legal; the select offers one at a time. */
  const [typeKeys, setTypeKeys] = useState<string[]>([]);
  const [assignee, setAssignee] = useState('');
  const [raisedBy, setRaisedBy] = useState('');
  const [showClosed, setShowClosed] = useState(false);
  const [q, setQ] = useState('');
  const qDebounced = useDebounced(q.trim(), 250);
  const [raising, setRaising] = useState(initial.raise);
  /** The day a "Raise a request due this day" started from, if any. */
  const [raiseDue, setRaiseDue] = useState<string | null>(null);
  /**
   * "Show these in the list", off the month tray: the same rows, cut to
   * the ones with no due date. It is a filter like any other, so it wears
   * a removable pill beside the count rather than hiding in a menu.
   */
  const [undatedOnly, setUndatedOnly] = useState(false);
  /** Only the ones past the department's own target date. */
  const [lateOnly, setLateOnly] = useState(false);
  /** The List view's tick boxes, and the last bulk write's two halves. */
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkOutcome, setBulkOutcome] = useState<BulkOutcome | null>(null);
  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null);

  useEffect(() => writeUrl({ dept, view, open: openId }), [dept, view, openId]);

  // A `?project=` in the link scopes the first render (the hub's "Raise a
  // request" arrives that way), but the All jobs toggle still clears it.
  const [linkedProject, setLinkedProject] = useState<string | null>(initial.project);
  const projectId = routeProjectId ?? linkedProject ?? (allJobs ? null : activeProjectId);
  const scopeName = routeProjectId ? t('wr.this_job', { defaultValue: 'this job' }) : activeProjectName;

  const departments = useDepartments();
  const deps = useMemo(() => (departments.data ?? []).filter((d) => d.active), [departments.data]);
  const current: Department | undefined = dept === 'all' ? undefined : deps.find((d) => d.key === dept);
  useEffect(() => {
    // A department that no longer exists (renamed, deactivated) falls back to All.
    if (departments.data && dept !== 'all' && !current) setDept('all');
  }, [departments.data, dept, current]);

  const me = useMe();
  const users = useUsers();
  const summary = useSummary(projectId);
  const canManage = useCanManageWr();
  const addToast = useToastStore((s) => s.addToast);
  const invalidate = useInvalidateWr();
  const navigate = useNavigate();
  const tabMenu = useMenu();
  const exportMenu = useMenu();

  /**
   * The types the filter offers: the chosen department's, or every
   * department's when the tabs are on All. Keys are unique per
   * department, so a label that appears twice ("Other") is qualified.
   */
  const typeOptions = useMemo(() => {
    const src = current ? [current] : deps;
    const out: { key: string; label: string; group: string }[] = [];
    for (const d of src) for (const rt of typesOf(d)) out.push({ key: rt.key, label: rt.label, group: d.name });
    return out;
  }, [current, deps]);
  // A department switch can strand a type key that only existed on the old
  // one, which would filter every row away with no visible cause.
  useEffect(() => {
    setTypeKeys((keys) => {
      const live = keys.filter((k) => typeOptions.some((o) => o.key === k));
      return live.length === keys.length ? keys : live;
    });
  }, [typeOptions]);

  const filters = useMemo(
    () => ({
      project_id: projectId ?? undefined,
      department: current?.key,
      request_types: typeKeys.length ? typeKeys : undefined,
      status: status || undefined,
      assignee_id: assignee || undefined,
      raised_by: raisedBy || undefined,
      q: qDebounced || undefined,
      include_closed: showClosed || (!!status && ['complete', 'closed', 'cancelled'].includes(status)),
      late_only: lateOnly || undefined,
    }),
    [projectId, current?.key, typeKeys, status, assignee, raisedBy, qDebounced, showClosed, lateOnly],
  );
  const requests = useRequests(filters, view !== 'queue' && !!departments.data);
  const queue = useMyQueue(view === 'queue' && !!departments.data);

  // The type filter is applied here as well as on the wire: a backend that
  // does not know `?request_types=` yet returns everything, and the board
  // must still show what the filter says it shows.
  const rows = useMemo(
    () =>
      (requests.data ?? []).filter(
        (r) =>
          // A template is a shape to raise FROM, not work anybody owes.
          // The server hides them; this makes sure a server that has not
          // learned to cannot put one on the board.
          r.is_template !== true &&
          matchesText(r, q) &&
          matchesTypes(r, typeKeys) &&
          (!undatedOnly || !r.due_date) &&
          // Applied here as well as on the wire: a backend that does not
          // know `?late_only=` returns everything, and the pill above the
          // list has to mean what it says.
          (!lateOnly || isLate(r)),
      ),
    [requests.data, q, typeKeys, undatedOnly, lateOnly],
  );

  const open = useCallback((req: { id: string }) => setOpenId(req.id), []);
  const actions = useRequestActions({ departments: departments.data, me, onOpen: open });

  /**
   * The tab badge, the board and the "N requests" line used to be three
   * different numbers on one screen: Engineering read `0` beside a board
   * showing a complete card and a header saying "1 request", because
   * `summary.open` stops counting at complete while the list does not.
   *
   * The badge counts what is still LIVE - open PLUS `awaiting_close`,
   * the finished ones nobody has closed off yet. That is exactly the set
   * the board draws and the set the list returns while "Show closed" is
   * off, so all three agree. (`awaiting_close` is optional on the wire;
   * a server that omits it just makes the badge the old open count.)
   */
  const liveCount = (key: string): number | undefined => {
    const s = summary.data?.departments;
    if (!s) return undefined;
    const live = (d: { open?: number; awaiting_close?: number }) => (d.open ?? 0) + (d.awaiting_close ?? 0);
    if (key === 'all') return s.reduce((a, d) => a + live(d), 0);
    const row = s.find((d) => d.key === key);
    return row ? live(row) : undefined;
  };

  /**
   * The tab's own tooltip. The badge is one number (what is live); the
   * tooltip is where the breakdown belongs, and lateness is exactly the
   * kind of thing a PM wants per department without another badge
   * competing for the same 20 pixels. `late` is optional on the wire, so
   * a server without it simply contributes no sentence.
   */
  const tabTitle = (key: string, fallback?: string): string | undefined => {
    const s = summary.data?.departments;
    const base = t('wr.tab_count_hint', { defaultValue: 'Open, plus the finished ones waiting to be closed off' });
    if (!s) return fallback || base;
    const rows = key === 'all' ? s : s.filter((d) => d.key === key);
    const late = rows.reduce((a, d) => a + (d.late ?? 0), 0);
    const knows = rows.some((d) => typeof d.late === 'number');
    const overdue = rows.reduce((a, d) => a + (d.overdue ?? 0), 0);
    const parts = [fallback, base];
    if (overdue > 0) parts.push(t('wr.tab_overdue', { defaultValue: '{{n}} overdue', n: overdue }));
    if (knows && late > 0) parts.push(t('wr.tab_late', { defaultValue: '{{n}} past the department target', n: late }));
    return parts.filter(Boolean).join(' · ');
  };

  /** The export carries the CURRENT filters - the same query as the list. */
  const doExport = async (format: 'csv' | 'xlsx') => {
    setExporting(format);
    try {
      await exportRequests(filters, format);
    } catch (err) {
      addToast({ type: 'error', title: errorText(err) });
    } finally {
      setExporting(null);
    }
  };

  const selectedRows = useMemo(() => rows.filter((r) => picked.has(r.id)), [rows, picked]);
  // A filter change can strand a tick on a row that is no longer on
  // screen, which would then be written by a bulk action nobody could see.
  useEffect(() => {
    setPicked((p) => {
      if (p.size === 0) return p;
      const live = new Set(Array.from(p).filter((id) => rows.some((r) => r.id === id)));
      return live.size === p.size ? p : live;
    });
  }, [rows]);

  const applyBulk = async (patch: BulkPatch, what: string) => {
    const ids = selectedRows.map((r) => r.id);
    if (ids.length === 0) return;
    setBulkBusy(true);
    try {
      const out = await bulkPatch(ids, patch);
      // Both halves, honestly. A server that answers with neither array is
      // read as "everything went through" only because it said so - the
      // counts still come from what came back, never from what was asked.
      setBulkOutcome({ updated: out.updated ?? [], refused: out.refused ?? [], what });
      invalidate();
      // What was refused stays ticked, so a second attempt (or a fix) does
      // not need the selection rebuilding by hand.
      const refusedIds = new Set((out.refused ?? []).map((r) => r.id));
      setPicked(new Set(ids.filter((id) => refusedIds.has(id))));
    } catch (err) {
      addToast({ type: 'error', title: errorText(err) });
    } finally {
      setBulkBusy(false);
    }
  };

  const toggleAllJobs = () => {
    setLinkedProject(null);
    setAllJobs((v) => {
      try {
        localStorage.setItem(ALL_JOBS_KEY, v ? '0' : '1');
      } catch {
        /* forgets */
      }
      return !v;
    });
  };

  const missing = departments.isError && isModuleMissing(departments.error);
  const openReq: WorkRequest | undefined = openId ? (requests.data ?? []).find((r) => r.id === openId) : undefined;

  return (
    <div className="wr flex flex-col gap-3">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="m-0 flex items-center gap-2 text-xl font-bold text-content-primary">
            <ClipboardList size={20} className="text-content-tertiary" aria-hidden />
            {t('wr.title', { defaultValue: 'Work requests' })}
          </h1>
          <p className="m-0 text-xs text-content-tertiary">
            {t('wr.subtitle', { defaultValue: 'What one department needs from another - who, when, how many hours, and where it is up to.' })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!routeProjectId && (
            <button
              type="button"
              className={clsx('wr-btn-quiet', projectId && 'on')}
              onClick={toggleAllJobs}
              title={t('wr.scope_hint', { defaultValue: 'Click to switch between the active job and every job' })}
              aria-pressed={!!projectId}
            >
              {projectId
                ? t('wr.scope_job', { defaultValue: 'Job: {{name}}', name: scopeName || projectId })
                : t('wr.scope_all', { defaultValue: 'All jobs' })}
            </button>
          )}
          {routeProjectId && (
            <Link to="/work-requests" className="wr-btn-quiet">
              {t('wr.scope_all', { defaultValue: 'All jobs' })}
            </Link>
          )}
          {/* Hidden outright for a role that could only be refused; the
              server is still the one that decides, and the screen it opens
              says so plainly when it is. */}
          {canManage && !missing && (
            <Link to="/work-requests/departments" className="wr-btn-quiet" data-testid="wr-manage-btn" title={t('wr.manage_hint', { defaultValue: 'Departments, their people, and the request types they offer' })}>
              <SlidersHorizontal size={12} /> {t('wr.manage_btn', { defaultValue: 'Manage departments' })}
            </Link>
          )}
          {!missing && (
            <button
              type="button"
              className="wr-btn-quiet"
              disabled={!!exporting || !departments.data}
              title={t('wr.export_hint', { defaultValue: 'Everything the filters above are showing, as a file' })}
              onClick={(e) =>
                exportMenu.openBelow(
                  e.currentTarget,
                  [
                    { label: t('wr.export_csv', { defaultValue: 'CSV (.csv)' }), note: t('wr.export_note', { defaultValue: 'current filters' }), onClick: () => void doExport('csv') },
                    { label: t('wr.export_xlsx', { defaultValue: 'Excel (.xlsx)' }), note: t('wr.export_note', { defaultValue: 'current filters' }), onClick: () => void doExport('xlsx') },
                  ],
                  { head: t('wr.export', { defaultValue: 'Export' }) },
                )
              }
              data-testid="wr-export-btn"
            >
              <Download size={12} /> {exporting ? t('wr.exporting', { defaultValue: 'Exporting…' }) : t('wr.export', { defaultValue: 'Export' })}
            </button>
          )}
          <button type="button" className="wr-btn-quiet on" onClick={() => setRaising(true)} disabled={missing || !departments.data} data-testid="wr-raise-btn">
            <Plus size={12} /> {t('wr.raise_btn', { defaultValue: 'Raise a request' })}
          </button>
        </div>
      </div>

      {missing && <ModuleMissing onRetry={() => void departments.refetch()} />}
      {departments.isError && !missing && (
        <div className="wr-banner err">
          {errorText(departments.error)}{' '}
          <button type="button" className="wr-btn-quiet" onClick={() => void departments.refetch()}>
            {t('wr.retry', { defaultValue: 'Try again' })}
          </button>
        </div>
      )}
      {departments.isLoading && <p className="wr-hint">{t('wr.loading', { defaultValue: 'Loading…' })}</p>}

      {departments.data && (
        <>
          {/* ── Department tabs ─────────────────────────────────── */}
          <div className="wr-tabs" role="tablist" aria-label={t('wr.departments', { defaultValue: 'Departments' })}>
            <button
              type="button"
              role="tab"
              className="wr-tab"
              aria-selected={dept === 'all'}
              onClick={() => setDept('all')}
              title={tabTitle('all')}
            >
              {t('wr.all_departments', { defaultValue: 'All' })}
              {liveCount('all') !== undefined && <span className="n">{liveCount('all')}</span>}
            </button>
            {deps.map((d) => (
              <button
                key={d.key}
                type="button"
                role="tab"
                className="wr-tab"
                aria-selected={dept === d.key}
                style={{ ['--tab' as string]: resolveColour(d.colour) }}
                onClick={() => setDept(d.key)}
                title={tabTitle(d.key, d.description)}
                onContextMenu={(e) =>
                  tabMenu.openFromEvent(
                    e,
                    [
                      { label: t('wr.show_dept', { defaultValue: 'Show only {{name}}', name: d.name }), onClick: () => setDept(d.key) },
                      { label: t('wr.plan_dept', { defaultValue: 'Plan {{name}}', name: d.name }), onClick: () => { setDept(d.key); setView('planner'); } },
                      null,
                      canManage
                        ? { label: t('wr.manage_dept', { defaultValue: 'Manage {{name}}…', name: d.name }), icon: SlidersHorizontal, onClick: () => navigate(`/work-requests/departments?dept=${encodeURIComponent(d.key)}`) }
                        : null,
                    ],
                    { head: d.name },
                  )
                }
              >
                <span className="dot" aria-hidden />
                {d.name}
                {liveCount(d.key) !== undefined && <span className="n">{liveCount(d.key)}</span>}
              </button>
            ))}
            {deps.length === 0 && <span className="wr-hint py-2">{t('wr.no_departments', { defaultValue: 'No active departments are configured.' })}</span>}
          </div>
          {tabMenu.element}
          {exportMenu.element}

          {/* ── View switch + filters ───────────────────────────── */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="wr-seg" role="group" aria-label={t('wr.view', { defaultValue: 'View' })}>
              {VIEWS.map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>
                  {v === 'board' && t('wr.view_board', { defaultValue: 'Board' })}
                  {v === 'list' && t('wr.view_list', { defaultValue: 'List' })}
                  {v === 'planner' && t('wr.view_planner', { defaultValue: 'Planner' })}
                  {v === 'month' && t('wr.view_month', { defaultValue: 'Month' })}
                  {v === 'queue' && t('wr.view_queue', { defaultValue: 'My queue' })}
                </button>
              ))}
            </div>
            {view !== 'queue' && (
              <>
                <select className="wr-in" style={{ width: 'auto' }} value={status} onChange={(e) => setStatus(e.target.value as Status | '')} aria-label={t('wr.filter_status', { defaultValue: 'Status' })}>
                  <option value="">{t('wr.any_status', { defaultValue: 'Any status' })}</option>
                  {(Object.keys(STATUS_LABEL) as Status[]).map((s) => (
                    <option key={s} value={s}>
                      {t(`wr.status.${s}`, { defaultValue: STATUS_LABEL[s] })}
                    </option>
                  ))}
                </select>
                {typeOptions.length > 0 && (
                  <select
                    className="wr-in"
                    style={{ width: 'auto' }}
                    value={typeKeys[0] ?? ''}
                    onChange={(e) => setTypeKeys(e.target.value ? [e.target.value] : [])}
                    aria-label={t('wr.filter_type', { defaultValue: 'Request type' })}
                    data-testid="wr-filter-type"
                  >
                    <option value="">{t('wr.any_type', { defaultValue: 'Any type' })}</option>
                    {typeOptions.map((o) => (
                      <option key={`${o.group}:${o.key}`} value={o.key}>
                        {current ? o.label : `${o.group} · ${o.label}`}
                      </option>
                    ))}
                  </select>
                )}
                <select className="wr-in" style={{ width: 'auto' }} value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label={t('wr.filter_assignee', { defaultValue: 'Assignee' })}>
                  <option value="">{t('wr.any_assignee', { defaultValue: 'Any assignee' })}</option>
                  {(users.data ?? []).map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.email}
                    </option>
                  ))}
                </select>
                <select className="wr-in" style={{ width: 'auto' }} value={raisedBy} onChange={(e) => setRaisedBy(e.target.value)} aria-label={t('wr.filter_pm', { defaultValue: 'Raised by (PM)' })}>
                  <option value="">{t('wr.any_pm', { defaultValue: 'Any PM' })}</option>
                  {(users.data ?? []).map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.email}
                    </option>
                  ))}
                </select>
                <label className="relative">
                  <Search size={12} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-content-tertiary" aria-hidden />
                  <input className="wr-in" style={{ paddingLeft: 24, width: 220 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('wr.search_ph', { defaultValue: 'Search ref, title, job, people…' })} aria-label={t('wr.search', { defaultValue: 'Search' })} />
                </label>
                <label className="wr-tog">
                  <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
                  {t('wr.show_closed', { defaultValue: 'Show closed' })}
                </label>
                <label className="wr-tog" title={t('wr.late_only_hint', { defaultValue: 'Past the department’s own target date - not the same as the requester’s due date' })}>
                  <input type="checkbox" checked={lateOnly} onChange={(e) => setLateOnly(e.target.checked)} data-testid="wr-late-only" />
                  {t('wr.late_only', { defaultValue: 'Late only' })}
                </label>
                {undatedOnly && (
                  <button type="button" className="wr-btn-quiet on" onClick={() => setUndatedOnly(false)} data-testid="wr-undated-pill">
                    {t('wr.month_tray', { defaultValue: 'No date yet' })} ✕
                  </button>
                )}
                <span className="wr-hint ml-auto">
                  {requests.isFetching
                    ? t('wr.refreshing', { defaultValue: 'Refreshing…' })
                    : t('wr.count', { defaultValue_one: '{{count}} request', defaultValue_other: '{{count}} requests', defaultValue: '{{count}} requests', count: rows.length })}
                </span>
              </>
            )}
          </div>

          {actions.error && (
            <div className="wr-banner err" role="alert">
              <span>
                <b>{t('wr.refused', { defaultValue: '{{ref}}: the server refused that move', ref: actions.error.reference })}</b>
                {actions.error.text}
                {actions.error.allowed.length > 0 && ` · ${t('wr.allowed', { defaultValue: 'allowed: {{list}}', list: fmtList(actions.error.allowed) })}`}
              </span>
              <button type="button" className="wr-btn-quiet ml-auto" onClick={actions.clearError} aria-label={t('common.close', { defaultValue: 'Close' })}>
                ✕
              </button>
            </div>
          )}

          {/* ── The view ────────────────────────────────────────── */}
          {view !== 'queue' && requests.isError && (
            <div className="wr-banner err">
              {isModuleMissing(requests.error) ? t('wr.missing_title', { defaultValue: 'This server does not have the Work Requests module yet.' }) : errorText(requests.error)}
            </div>
          )}
          {view !== 'queue' && requests.isLoading && <p className="wr-hint">{t('wr.loading', { defaultValue: 'Loading…' })}</p>}

          {view === 'board' && requests.data && <BoardView dept={current} departments={deps} rows={rows} me={me} actions={actions} onOpen={open} />}

          {view === 'list' && requests.data && (
            <>
              <RequestTable
                rows={rows}
                departments={deps}
                me={me}
                actions={actions}
                onOpen={open}
                selectedId={openId}
                showDepartment={!current}
                emptyText={t('wr.list_empty_raise', { defaultValue: 'No requests match. Raise one with the button above.' })}
                selection={{
                  ids: picked,
                  onToggle: (id, on) =>
                    setPicked((p) => {
                      const next = new Set(p);
                      if (on) next.add(id);
                      else next.delete(id);
                      return next;
                    }),
                  // Select-all ADDS the rows on screen and unticking
                  // removes only those - a filtered page must never
                  // silently drop a tick made on another page.
                  onToggleAll: (ids, on) =>
                    setPicked((p) => {
                      const next = new Set(p);
                      for (const id of ids) {
                        if (on) next.add(id);
                        else next.delete(id);
                      }
                      return next;
                    }),
                }}
              />
              <BulkBar
                selected={selectedRows}
                departments={deps}
                busy={bulkBusy}
                outcome={bulkOutcome}
                onApply={(patch, what) => void applyBulk(patch, what)}
                onClear={() => setPicked(new Set())}
                onDismiss={() => setBulkOutcome(null)}
              />
            </>
          )}

          {view === 'planner' &&
            (current ? (
              <PlannerView dept={current} requests={(requests.data ?? []).filter((r) => r.department === current.key)} actions={actions} onOpen={open} />
            ) : (
              <div className="wr-empty">
                <b>{t('wr.planner_pick', { defaultValue: 'Pick a department to plan.' })}</b>
                <div className="mt-2 flex flex-wrap justify-center gap-2">
                  {deps.map((d) => (
                    <button key={d.key} type="button" className="wr-btn-quiet" onClick={() => setDept(d.key)}>
                      <span className="wr-pill" style={{ background: resolveColour(d.colour), borderColor: resolveColour(d.colour), color: '#fff' }}>
                        {d.name}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}

          {view === 'month' && requests.data && (
            <MonthView
              departments={deps}
              dept={current}
              rows={rows}
              me={me}
              actions={actions}
              onOpen={open}
              onRaiseOn={(day) => {
                setRaiseDue(day);
                setRaising(true);
              }}
              onShowUndated={() => {
                setUndatedOnly(true);
                setView('list');
              }}
            />
          )}

          {view === 'queue' && (
            <>
              {queue.isLoading && <p className="wr-hint">{t('wr.loading', { defaultValue: 'Loading…' })}</p>}
              {queue.isError && <div className="wr-banner err">{errorText(queue.error)}</div>}
              {queue.data && <MyQueueView queue={queue.data} departments={deps} me={me} actions={actions} onOpen={open} selectedId={openId} />}
            </>
          )}
        </>
      )}

      {actions.element}

      <SideDrawer
        open={!!openId}
        onClose={() => setOpenId(null)}
        widthClass="max-w-3xl"
        title={openReq ? `${openReq.reference} · ${openReq.title}` : t('wr.request', { defaultValue: 'Request' })}
        headerActions={
          openId ? (
            <Link to={`/work-requests/${encodeURIComponent(openId)}`} className="wr-btn-quiet wr">
              {t('wr.full_page', { defaultValue: 'Open full page' })}
            </Link>
          ) : null
        }
      >
        {openId && departments.data && <RequestDetail id={openId} departments={departments.data} me={me} actions={actions} onOpenOther={(r) => setOpenId(r.id)} />}
      </SideDrawer>

      {raising && departments.data && (
        <RaiseRequestDialog
          open
          departments={departments.data}
          me={me}
          defaultDepartment={current?.key}
          defaultProjectId={projectId}
          defaultDue={raiseDue}
          onClose={() => {
            setRaising(false);
            setRaiseDue(null);
          }}
          onRaised={(req) => {
            setRaising(false);
            setRaiseDue(null);
            setOpenId(req.id);
          }}
        />
      )}
    </div>
  );
}
