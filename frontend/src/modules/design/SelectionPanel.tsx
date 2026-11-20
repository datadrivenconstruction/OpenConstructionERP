// Design module (ERP side of the design editor link).
/**
 * Right side of the editor workspace: everything the ERP knows about the selection, in blocks the person can hide
 * and reorder (kept per user). Estimate lines with cost — from the person's draft (exact: the server ran the rules
 * on it, current → draft quantity) or, without a draft, from the estimate; the model's own quantities; BOQ
 * positions, schedule activities and tender packages that use the elements; documents, field reports and open
 * remarks. Each entry opens the module that holds it. Below: what the draft changes in the estimate.
 */
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowRight, ArrowUp, Check, MousePointerClick, SlidersHorizontal } from 'lucide-react';
import clsx from 'clsx';
import { useAuthStore } from '@/stores/useAuthStore';
import { fetchAccess, fetchEstimate } from './api';
import { moneyExact, moneyWhole, pickCurrency } from './money';
import { CORE_STEPS, ICON, stepState, stepText } from './overviewSteps';
import type { EstimateView } from './data/estimate';
import type { SelectedElement } from './bridge/protocol';
import type { DraftLine, DraftView } from './draftApi';
import { changedLines, draftLinesFor, linesFor } from './data/workspace';
import { tr } from './BriefFields';
import { FieldReportLinks } from './FieldReportLinks';
import { boqUrl, fetchElementContext, fetchLinks, fetchOverview, packageUrl, scheduleUrl } from './linksApi';
import type { ElementContext, ElementLinks } from './linksApi';
import {
  DEFAULT_LAYOUT, loadLayout, moveBlock, saveLayout, toggleBlock, visibleBlocks,
  type BlockId, type PanelLayout,
} from './data/panelBlocks';

/** Figures in the language the page is shown in. */
function useNum() {
  const { i18n } = useTranslation();
  const lang = i18n.language || 'en';
  return (v: string | null | undefined) => (v === null || v === undefined ? '–' : Number(v).toLocaleString(lang, { maximumFractionDigits: 2 }));
}

/** The project's currency, from the estimate or the project setting. */
function useCurrency(projectId: string): string {
  const estimate = useQuery({ queryKey: ['design-estimate', projectId], queryFn: () => fetchEstimate(projectId), retry: false });
  const access = useQuery({ queryKey: ['design-access', projectId], queryFn: () => fetchAccess(projectId), retry: false });
  const e = estimate.data && estimate.data.estimate ? estimate.data : null;
  return pickCurrency(e?.range.currency, access.data?.currency);
}

const ROW = 'block rounded-md border border-border-light px-2.5 py-1.5 hover:border-oe-blue hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue';
const SUB = 'text-[11px] font-medium text-content-tertiary';
const H = 'text-xs font-semibold uppercase tracking-wide text-content-tertiary';

function DraftRow({ l, cur }: { l: DraftLine; cur: string }) {
  const { t } = useTranslation();
  const num = useNum();
  const moved = l.quantity !== null && l.current_quantity !== null && Number(l.quantity) !== Number(l.current_quantity);
  return (
    <li className="rounded-md border border-border-light px-2.5 py-1.5" data-testid={`line-${l.rule}`}>
      <p className="font-medium text-content-primary">{l.description}</p>
      <p className="tabular-nums text-content-secondary">
        {moved ? <><s className="text-content-tertiary">{num(l.current_quantity)}</s> → <b className="text-content-primary">{num(l.quantity)}</b></> : num(l.quantity)}
        {' '}{l.unit ?? ''}
        {l.unit_rate && Number(l.unit_rate) > 0 ? <> × {moneyExact(l.unit_rate, cur)} = <b className="font-medium text-content-primary">{moneyWhole(l.total, cur)}</b></> : null}
      </p>
      {l.flags.includes('rate_missing') && <p className="text-xs text-content-tertiary">{tr(t, 'design.workspace.side.rate_missing')}</p>}
    </li>
  );
}

function useLinks(projectId: string, keys: string[]) {
  return useQuery({
    queryKey: ['design-links', projectId, keys], queryFn: () => fetchLinks(projectId, keys),
    enabled: keys.length > 0, retry: false, staleTime: 30_000,
  });
}

function useElementContext(projectId: string, keys: string[]) {
  return useQuery({
    queryKey: ['design-element-context', projectId, keys], queryFn: () => fetchElementContext(projectId, keys),
    enabled: keys.length > 0, retry: false, staleTime: 30_000,
  });
}

/** Loading, failed or empty, else the content: the same states in every block. */
function States<T>({ q, empty, none, children }: {
  q: { isLoading: boolean; isError: boolean; data?: T; refetch?: () => unknown };
  empty: (d: T) => boolean; none: string; children: (d: T) => ReactNode;
}) {
  const { t } = useTranslation();
  if (q.isLoading) return <p className="text-content-tertiary" aria-busy="true">…</p>;
  if (q.isError || !q.data) {
    return (
      <p className="text-content-secondary">
        {tr(t, 'design.panel.failed')}{' '}
        {q.refetch && <button type="button" className="text-oe-blue-text underline" onClick={() => void q.refetch!()}>{tr(t, 'design.panel.retry')}</button>}
      </p>
    );
  }
  if (empty(q.data)) return <p className="text-content-secondary">{none}</p>;
  return <>{children(q.data)}</>;
}

function BoqRows({ d }: { d: ElementLinks }) {
  const { t } = useTranslation();
  const num = useNum();
  return (
    <div className="flex flex-col gap-1.5">
      {d.positions.map((p) => (
        <Link key={p.position_id} to={boqUrl(p)} className={ROW} data-testid={`link-position-${p.position_id}`}>
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate font-medium text-content-primary">{p.ordinal} {p.description}</span>
            <span className="shrink-0 text-[11px] text-content-tertiary">{tr(t, `design.links.source.${p.source}`)}</span>
          </span>
          <span className="tabular-nums text-content-secondary">{num(p.quantity)} {p.unit}</span>
        </Link>
      ))}
    </div>
  );
}

function ScheduleRows({ d }: { d: ElementLinks }) {
  return (
    <div className="flex flex-col gap-1.5">
      {d.activities.map((a) => (
        <Link key={a.activity_id} to={scheduleUrl(a)} className={ROW} data-testid={`link-activity-${a.activity_id}`}>
          <span className="block truncate font-medium text-content-primary">{a.name}</span>
          <span className="tabular-nums text-content-secondary">{(a.start_date ?? '').slice(0, 10)} – {(a.end_date ?? '').slice(0, 10)}</span>
        </Link>
      ))}
    </div>
  );
}

function PackageRows({ d }: { d: ElementLinks }) {
  return (
    <div className="flex flex-col gap-1.5">
      {d.packages.map((k) => (
        <Link key={k.package_id} to={packageUrl(k)} className={ROW} data-testid={`link-package-${k.package_id}`}>
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate font-medium text-content-primary">{k.name}</span>
            <span className="shrink-0 text-[11px] text-content-tertiary">{k.status}</span>
          </span>
        </Link>
      ))}
    </div>
  );
}

/** Where else the ERP uses the selected elements, each entry opening the module that holds it. */
export function LinkedInErp({ projectId, keys }: { projectId: string; keys: string[] }) {
  const { t } = useTranslation();
  const q = useLinks(projectId, keys);
  if (keys.length === 0) return null;
  const d = q.data;
  const empty = d && d.positions.length + d.activities.length + d.packages.length === 0;
  return (
    <section className="flex flex-col gap-2 border-t border-border-light pt-3" data-testid="linked-in-erp"
      aria-busy={q.isLoading || undefined}>
      <h2 className={H}>{tr(t, 'design.links.title')}</h2>
      {q.isLoading ? <p className="text-content-tertiary">…</p>
        : q.isError ? <p className="text-content-secondary">{tr(t, 'design.links.failed')}</p>
        : empty ? <p className="text-content-secondary">{tr(t, 'design.links.none')}</p>
        : d && (
          <>
            {d.positions.length > 0 && <><p className={SUB}>{tr(t, 'design.links.boq')}</p><BoqRows d={d} /></>}
            {d.activities.length > 0 && <><p className={SUB}>{tr(t, 'design.links.schedule')}</p><ScheduleRows d={d} /></>}
            {d.packages.length > 0 && <><p className={SUB}>{tr(t, 'design.links.tendering')}</p><PackageRows d={d} /></>}
          </>
        )}
      <FieldReportLinks projectId={projectId} keys={keys} />
    </section>
  );
}

function EstimateBlock({ projectId, selection, draft }: { projectId: string; selection: SelectedElement[]; draft: DraftView | null }) {
  const { t } = useTranslation();
  const num = useNum();
  const estimate = useQuery({ queryKey: ['design-estimate', projectId], queryFn: () => fetchEstimate(projectId), retry: false });
  const cur = useCurrency(projectId);
  const data: EstimateView | undefined = estimate.data;
  const positions = data && data.estimate ? data.positions : null;
  const exact = draftLinesFor(selection, draft);
  const guessed = positions && exact.length === 0 ? linesFor(selection, positions) : [];
  if (exact.length > 0) {
    return (
      <>
        <p className="text-xs text-content-tertiary">{tr(t, 'design.workspace.side.draft')}</p>
        <ul className="flex flex-col gap-2" data-testid="selection-lines">{exact.map((l) => <DraftRow key={l.rule} l={l} cur={cur} />)}</ul>
      </>
    );
  }
  if (estimate.isLoading) return <p className="text-content-tertiary" aria-busy="true">…</p>;
  if (!positions) {
    return (
      <p className="text-content-secondary">
        {tr(t, 'design.workspace.side.no_estimate')}{' '}
        <Link className="text-oe-blue-text underline" to="/design/estimate">{tr(t, 'design.estimate.nav')}</Link>
      </p>
    );
  }
  if (guessed.length === 0) return <p className="text-content-secondary">{tr(t, 'design.workspace.side.no_lines')}</p>;
  const total = guessed.reduce((s, { position: p }) => s + (Number(p.total) || 0), 0);
  return (
    <>
      <ul className="flex flex-col gap-2" data-testid="selection-lines">
        {guessed.map(({ position: p, match }) => (
          <li key={p.position_id} className="rounded-md border border-border-light px-2.5 py-1.5">
            <p className="font-medium text-content-primary">{p.ordinal} {p.description}</p>
            <p className="tabular-nums text-content-secondary">{num(p.quantity)} {p.unit} × {moneyExact(p.unit_rate, cur)} = <b className="font-medium text-content-primary">{moneyWhole(p.total, cur)}</b></p>
            {match === 'maybe' && <p className="text-xs text-content-tertiary">{tr(t, 'design.workspace.side.maybe')}</p>}
          </li>
        ))}
      </ul>
      {guessed.length > 1 && (
        <p className="tabular-nums text-content-secondary" data-testid="selection-cost">{tr(t, 'design.panel.cost', { total: moneyWhole(total, cur) })}</p>
      )}
    </>
  );
}

function Quantities({ d }: { d: ElementContext }) {
  const { t } = useTranslation();
  const num = useNum();
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1" data-testid="selection-quantities">
      {d.quantities.map((q) => (
        <div key={q.kind} className="contents">
          <dt className="text-content-secondary">{tr(t, `design.panel.qty.${q.kind}`)}</dt>
          <dd className="text-right tabular-nums text-content-primary">{num(q.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Documents({ d }: { d: ElementContext }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1.5">
      {d.documents.map((x) => (
        <Link key={x.document_id} to={x.url} className={ROW} data-testid={`doc-${x.document_id}`}>
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate font-medium text-content-primary">{x.name}</span>
            <span className="shrink-0 text-[11px] text-content-tertiary">
              {x.link_type === 'design_sheet' ? tr(t, 'design.panel.sheet', { revision: x.revision ?? '–' }) : x.category}
            </span>
          </span>
        </Link>
      ))}
    </div>
  );
}

function Remarks({ d }: { d: ElementContext }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1.5">
      {d.remarks.map((r) => (
        <Link key={`${r.kind}-${r.id}`} to={r.url} className={ROW} data-testid={`remark-${r.id}`}>
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate font-medium text-content-primary">{r.title}</span>
            <span className="shrink-0 text-[11px] text-content-tertiary">{tr(t, `design.panel.remark.${r.kind}`)}</span>
          </span>
          <span className="text-xs text-content-secondary">
            {r.status}{r.due ? ` · ${tr(t, 'design.panel.due', { date: String(r.due).slice(0, 10) })}` : ''}
          </span>
        </Link>
      ))}
    </div>
  );
}

/** With nothing selected: the project in figures and the next steps, so the panel is never a blank column. */
function ProjectSnapshot({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const cur = useCurrency(projectId);
  const estimate = useQuery({ queryKey: ['design-estimate', projectId], queryFn: () => fetchEstimate(projectId), retry: false });
  const overview = useQuery({ queryKey: ['design-overview', projectId], queryFn: () => fetchOverview(projectId), retry: false, staleTime: 30_000 });
  const e = estimate.data && estimate.data.estimate ? estimate.data : null;
  const steps = overview.data?.steps ?? [];
  const next = steps.filter((s) => stepState(s) !== 'done').slice(0, 3);
  const counted = steps.filter((s) => s.done && s.count !== null && ['model', 'schedule', 'procurement', 'documents'].includes(s.id));
  const unpriced = e ? e.positions.filter((p) => !(Number(p.unit_rate) > 0)).length : 0;
  const mid = Number(e?.range?.total?.mid) || 0;
  const loading = estimate.isLoading || overview.isLoading;
  return (
    <div className="flex flex-col gap-4" data-testid="project-snapshot">
      <p className="flex items-start gap-2 rounded-lg bg-surface-secondary px-3 py-2 text-content-secondary">
        <MousePointerClick size={15} aria-hidden className="mt-0.5 shrink-0 text-content-tertiary" />
        <span>{tr(t, 'design.workspace.side.none')}</span>
      </p>
      <section aria-labelledby="snap-figures" className="flex flex-col gap-2">
        <h3 id="snap-figures" className={H}>{tr(t, 'design.panel.snapshot.title')}</h3>
        {loading ? <p className="text-content-tertiary" aria-busy="true">…</p> : (
          <>
            <Link to="/design/estimate" data-testid="snapshot-estimate"
              className="flex flex-col gap-0.5 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 hover:border-oe-blue focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue">
              {/* Same hero figure and labels as the estimate page: the range mid, then the priced lines' sum. */}
              <span className="text-xs text-content-tertiary" data-testid="snapshot-label">
                {mid > 0 ? `${tr(t, 'design.estimate.range')} · ${tr(t, 'design.estimate.mid')}` : tr(t, 'design.estimate.priced_total')}</span>
              <span className="text-2xl font-semibold tabular-nums leading-tight text-content-primary" data-testid="snapshot-total">
                {e ? moneyWhole(mid > 0 ? mid : e.total, cur) : '–'}</span>
              {e && (
                <span className="text-xs text-content-secondary">
                  {mid > 0 && <span data-testid="snapshot-priced">{tr(t, 'design.estimate.priced_total')} {Number(e.total) !== 0 ? moneyWhole(e.total, cur) : '–'} · </span>}
                  {tr(t, 'design.panel.snapshot.lines_n', { count: e.positions.length })}
                  {unpriced > 0 && <> · <span className="text-semantic-warning">{tr(t, 'design.panel.snapshot.unpriced_n', { count: unpriced })}</span></>}
                </span>
              )}
            </Link>
            {counted.length > 0 && (
              <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 px-1">
                {counted.map((s) => (
                  <div key={s.id} className="contents">
                    <dt className="text-content-secondary">{tr(t, `design.overview.step.${s.id}`)}</dt>
                    <dd className="text-right font-medium tabular-nums text-content-primary">{s.count}</dd>
                  </div>
                ))}
              </dl>
            )}
          </>
        )}
      </section>
      {next.length > 0 && (
        <section aria-labelledby="snap-next" className="flex flex-col gap-2">
          <h3 id="snap-next" className={H}>{tr(t, 'design.panel.snapshot.next')}</h3>
          <ol className="flex flex-col divide-y divide-border-light overflow-hidden rounded-lg border border-border-light bg-surface-primary">
            {next.map((s) => {
              const Icon = ICON[s.id];
              const state = stepState(s);
              const action = state === 'todo' && CORE_STEPS.includes(s.id)
                ? tr(t, `design.overview.action.${s.id}`)
                : tr(t, state === 'todo' ? 'design.overview.set_up' : 'design.overview.open');
              return (
                <li key={s.id}>
                  <Link to={s.url} data-testid={`snapshot-next-${s.id}`} data-state={state}
                    className="group flex items-start gap-2.5 px-3 py-2.5 hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-oe-blue">
                    <span className={clsx('mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
                      state === 'waiting' ? 'bg-semantic-warning/15 text-semantic-warning' : 'bg-oe-blue/10 text-oe-blue')}>
                      {state === 'done' ? <Check size={14} aria-hidden /> : <Icon size={14} aria-hidden />}
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="font-medium text-content-primary">{tr(t, `design.overview.step.${s.id}`)}</span>
                      <span className="text-xs text-content-secondary" data-testid={`snapshot-status-${s.id}`}>{stepText(t, s, steps)}</span>
                      <span className="mt-0.5 inline-flex items-center gap-1 text-xs font-medium text-oe-blue-text group-hover:underline">
                        {action}<ArrowRight size={12} aria-hidden />
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}

/** Show/hide and reorder the blocks. Alt+↑/↓ moves the focused block. */
function Chooser({ layout, onChange, onClose }: { layout: PanelLayout; onChange: (l: PanelLayout) => void; onClose: () => void }) {
  const { t } = useTranslation();
  const first = useRef<HTMLInputElement>(null);
  const [focusId, setFocusId] = useState<BlockId | null>(null);
  useEffect(() => { first.current?.focus(); }, []);
  useEffect(() => {
    if (focusId) document.getElementById(`panel-choose-${focusId}`)?.focus();
  }, [layout, focusId]);
  const move = (id: BlockId, by: -1 | 1) => { setFocusId(id); onChange(moveBlock(layout, id, by)); };
  const onKey = (e: KeyboardEvent, id: BlockId) => {
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      move(id, e.key === 'ArrowUp' ? -1 : 1);
    } else if (e.key === 'Escape') {
      onClose();
    }
  };
  const iconBtn = 'rounded p-1 text-content-secondary hover:bg-surface-secondary hover:text-content-primary disabled:opacity-30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue';
  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-2" data-testid="panel-chooser"
      role="group" aria-label={tr(t, 'design.panel.customize')}>
      <p className="px-1 pb-1.5 text-xs text-content-tertiary">{tr(t, 'design.panel.customize_hint')}</p>
      <ol className="flex flex-col">
        {layout.order.map((id, i) => {
          const name = tr(t, `design.panel.block.${id}`);
          return (
            <li key={id} className="flex items-center gap-1 rounded px-1 py-0.5 hover:bg-surface-secondary" data-testid={`choose-${id}`}>
              <label className="flex min-w-0 flex-1 items-center gap-2 py-1">
                <input id={`panel-choose-${id}`} ref={i === 0 ? first : undefined} type="checkbox"
                  checked={!layout.hidden.includes(id)} onChange={() => onChange(toggleBlock(layout, id))}
                  onKeyDown={(e) => onKey(e, id)} className="accent-oe-blue" />
                <span className="truncate">{name}</span>
              </label>
              <button type="button" className={iconBtn} disabled={i === 0} onClick={() => move(id, -1)}
                aria-label={tr(t, 'design.panel.move_up', { name })}><ArrowUp size={14} aria-hidden /></button>
              <button type="button" className={iconBtn} disabled={i === layout.order.length - 1} onClick={() => move(id, 1)}
                aria-label={tr(t, 'design.panel.move_down', { name })}><ArrowDown size={14} aria-hidden /></button>
            </li>
          );
        })}
      </ol>
      <div className="flex justify-between gap-2 px-1 pt-1.5">
        <button type="button" className="text-xs text-oe-blue-text hover:underline" onClick={() => onChange(DEFAULT_LAYOUT)}
          data-testid="panel-reset">{tr(t, 'design.panel.reset')}</button>
        <button type="button" className="text-xs text-oe-blue-text hover:underline" onClick={onClose}>{tr(t, 'design.panel.done')}</button>
      </div>
    </div>
  );
}

function Block({ id, children }: { id: BlockId; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2 border-t border-border-light pt-3 first:border-t-0 first:pt-0"
      aria-labelledby={`panel-block-${id}`} data-testid={`block-${id}`}>
      <h3 id={`panel-block-${id}`} className={H}>{tr(t, `design.panel.block.${id}`)}</h3>
      {children}
    </section>
  );
}

export function SelectionPanel({ projectId, selection, draft }: {
  projectId: string; selection: SelectedElement[]; draft?: DraftView | null;
}) {
  const { t } = useTranslation();
  const cur = useCurrency(projectId);
  const userId = useAuthStore((s) => s.userId);
  const [layout, setLayout] = useState<PanelLayout>(() => loadLayout(userId));
  const [choosing, setChoosing] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  useEffect(() => { setLayout(loadLayout(userId)); }, [userId]);
  const change = (l: PanelLayout) => { setLayout(l); saveLayout(userId, l); };
  const close = () => { setChoosing(false); opener.current?.focus(); };
  const keys = selection.map((e) => e.element_key);
  const links = useLinks(projectId, keys);
  const ctx = useElementContext(projectId, keys);
  const changed = changedLines(draft ?? null);

  const body = (id: BlockId): ReactNode => {
    switch (id) {
      case 'estimate': return <EstimateBlock projectId={projectId} selection={selection} draft={draft ?? null} />;
      case 'quantities': return <States q={ctx} empty={(d) => d.quantities.length === 0} none={tr(t, ctx.data?.found === 0 ? 'design.panel.not_in_model' : 'design.panel.none.quantities')}>{(d) => <Quantities d={d} />}</States>;
      case 'boq': return <States q={links} empty={(d) => d.positions.length === 0} none={tr(t, 'design.panel.none.boq')}>{(d) => <BoqRows d={d} />}</States>;
      case 'schedule': return <States q={links} empty={(d) => d.activities.length === 0} none={tr(t, 'design.panel.none.schedule')}>{(d) => <ScheduleRows d={d} />}</States>;
      case 'procurement': return <States q={links} empty={(d) => d.packages.length === 0} none={tr(t, 'design.panel.none.procurement')}>{(d) => <PackageRows d={d} />}</States>;
      case 'documents': return <States q={ctx} empty={(d) => d.documents.length === 0} none={tr(t, 'design.panel.none.documents')}>{(d) => <Documents d={d} />}</States>;
      case 'field_reports': return <FieldReportLinks projectId={projectId} keys={keys} inBlock />;
      case 'remarks': return <States q={ctx} empty={(d) => d.remarks.length === 0} none={tr(t, 'design.panel.none.remarks')}>{(d) => <Remarks d={d} />}</States>;
    }
  };
  const shown = visibleBlocks(layout);

  return (
    <aside data-testid="selection-panel" aria-label={tr(t, 'design.panel.title')}
      className="flex min-w-0 flex-col gap-4 overflow-auto text-sm">
      <header className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className={H}>{tr(t, 'design.panel.title')}</h2>
          <button ref={opener} type="button" onClick={() => (choosing ? close() : setChoosing(true))} aria-expanded={choosing}
            data-testid="panel-customize"
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-content-secondary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue">
            <SlidersHorizontal size={13} aria-hidden />{tr(t, 'design.panel.customize')}
          </button>
        </div>
        {choosing && <Chooser layout={layout} onChange={change} onClose={close} />}
        {selection.length === 0 ? (
          <ProjectSnapshot projectId={projectId} />
        ) : (
          <p className="truncate font-medium text-content-primary" data-testid="selection-what"
            title={selection.length === 1 ? selection[0]!.element_key : undefined}>
            {selection.length === 1
              ? `${selection[0]!.ifc_class ?? ''} ${selection[0]!.element_key}`.trim()
              : tr(t, 'design.workspace.side.many', { count: selection.length })}
          </p>
        )}
      </header>
      {selection.length > 0 && (shown.length === 0
        ? <p className="text-content-secondary" data-testid="panel-all-hidden">{tr(t, 'design.panel.all_hidden')}</p>
        : shown.map((id) => <Block key={id} id={id}>{body(id)}</Block>))}
      {draft && (
        <section className="flex flex-col gap-2 border-t border-border-light pt-3" data-testid="draft-impact">
          <h2 className={H}>{tr(t, 'design.workspace.impact.title')}</h2>
          {changed.length === 0 ? (
            <p className="text-content-secondary">{tr(t, 'design.workspace.impact.none')}</p>
          ) : (
            <ul className="flex flex-col gap-2">{changed.map((l) => <DraftRow key={l.rule} l={l} cur={cur} />)}</ul>
          )}
          {Number(draft.estimate.model_total) > 0 && (
            <p className="tabular-nums text-content-secondary">{tr(t, 'design.workspace.impact.total', { total: moneyWhole(draft.estimate.model_total, cur) })}</p>
          )}
        </section>
      )}
    </aside>
  );
}

