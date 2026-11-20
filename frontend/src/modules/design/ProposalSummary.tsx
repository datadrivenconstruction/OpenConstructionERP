// Design module (ERP side of the design editor link).
/**
 * The one summary screen every proposal ends on: all values with their sources, the doubtful ones first and
 * highlighted, each correctable or left out, then one button confirms them all. Nothing is stored before that.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { AlertTriangle, CheckCheck, Pencil, Undo2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { confirmBrief, saveBrief } from './api';
import { briefErrors, fieldSpec, formatValue, parseInput, tidy, PLOT_POINTER, type BriefDoc } from './data/briefModel';
import { areaM2, fromPolygon, type GeoPolygon } from './data/polygon';
import { applySummary, type ProposalSet, type SummaryItem } from './data/proposals';
import { fieldLabel, optionLabel, tr } from './BriefFields';

export interface SummaryOutcome { brief: BriefDoc; confirmed: string[] }

function useShow() {
  const { t, i18n } = useTranslation();
  return (pointer: string, value: unknown): string => {
    if (pointer === PLOT_POINTER) {
      const m2 = areaM2(fromPolygon(value as GeoPolygon));
      return tr(t, 'design.start.plot_value', { area: Math.round(m2).toLocaleString(i18n.language || 'en') });
    }
    if (typeof value === 'number') {
      const n = value.toLocaleString(i18n.language || 'en', { maximumFractionDigits: 3 });
      let unit: string | undefined;
      try { unit = fieldSpec(pointer).unit; } catch { unit = undefined; }
      return unit && unit !== 'currency' ? `${n} ${unit}` : n;
    }
    if (typeof value === 'boolean') return tr(t, value ? 'design.start.yes' : 'design.start.no');
    if (typeof value === 'string') return optionLabel(t, value);
    return formatValue(value);
  };
}

function SourceLine({ item, set }: { item: SummaryItem; set: ProposalSet }) {
  const { t } = useTranslation();
  const s = item.source;
  let where: string;
  if (set.origin === 'template') where = tr(t, 'design.start.source.template');
  else if (set.origin === 'map' || s?.kind === 'map') where = tr(t, 'design.start.source.map');
  else if (s?.document_id) {
    const name = set.documents?.[s.document_id] ?? tr(t, 'design.start.source.file');
    where = s.page ? tr(t, 'design.start.source.page', { name, page: s.page }) : name;
  } else where = tr(t, 'design.start.source.text');
  return (
    <p className="text-xs text-content-tertiary">
      <span>{where}</span>
      {s?.quote && <>{' · '}<q className="italic text-content-secondary">{s.quote}</q></>}
    </p>
  );
}

function ValueEditor({ pointer, value, onSave, onCancel }: {
  pointer: string; value: unknown; onSave: (v: unknown) => void; onCancel: () => void;
}) {
  const { t } = useTranslation();
  const spec = fieldSpec(pointer);
  const [text, setText] = useState(formatValue(value));
  const [bad, setBad] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement & HTMLSelectElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const label = tr(t, 'design.start.correct_label', { field: fieldLabel(t, pointer) });
  const save = () => {
    const p = parseInput(spec, text);
    if (!p.ok) { setBad(tr(t, `design.error.${p.code}`)); return; }
    if (p.value === undefined) { setBad(tr(t, 'design.start.empty_value')); return; }
    onSave(p.value);
  };
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel(); }
  };
  const cls = 'w-full min-w-0 rounded-md border border-border bg-surface-primary px-2 py-1 text-sm text-content-primary';
  return (
    <div className="flex flex-wrap items-center gap-2">
      {spec.kind === 'choice' || spec.kind === 'boolean' ? (
        <select ref={ref} aria-label={label} className={clsx(cls, 'sm:w-56')} value={text} onKeyDown={keys}
          onChange={(e) => setText(e.target.value)}>
          {(spec.kind === 'boolean' ? ['true', 'false'] : spec.options).map((o) => (
            <option key={o} value={o}>{spec.kind === 'boolean' ? tr(t, o === 'true' ? 'design.start.yes' : 'design.start.no') : optionLabel(t, o)}</option>
          ))}
        </select>
      ) : (
        <input ref={ref} aria-label={label} className={clsx(cls, 'sm:w-40')} value={text} inputMode={spec.kind === 'text' ? undefined : 'decimal'}
          onKeyDown={keys} onChange={(e) => { setText(e.target.value); setBad(null); }} aria-invalid={bad ? true : undefined} />
      )}
      {spec.unit && spec.unit !== 'currency' && <span className="text-xs text-content-tertiary">{spec.unit}</span>}
      <Button size="sm" onClick={save}>{tr(t, 'design.start.correct_save')}</Button>
      <Button size="sm" variant="secondary" onClick={onCancel}>{tr(t, 'design.start.correct_cancel')}</Button>
      {bad && <p role="alert" className="w-full text-xs text-semantic-error">{bad}</p>}
    </div>
  );
}

export function ProposalSummary({ projectId, brief, set, onDone, onDiscard }: {
  projectId: string;
  brief: BriefDoc | null;
  set: ProposalSet;
  onDone: (o: SummaryOutcome) => void;
  onDiscard: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const show = useShow();
  const [leftOut, setLeftOut] = useState<Set<string>>(new Set());
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const headRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headRef.current?.focus(); }, [set]);

  const kept = set.items.filter((i) => !leftOut.has(i.pointer));
  const doubtful = set.items.filter((i) => i.doubt && !(i.pointer in edits)).length;
  const editable = useMemo(() => new Set(set.items.filter((i) => {
    if (i.pointer === PLOT_POINTER) return false;
    try { return ['integer', 'number', 'text', 'choice', 'boolean'].includes(fieldSpec(i.pointer).kind); } catch { return false; }
  }).map((i) => i.pointer)), [set]);

  const toggle = (p: string) => setLeftOut((s) => {
    const n = new Set(s);
    if (n.has(p)) n.delete(p); else n.add(p);
    return n;
  });

  const confirmAll = async () => {
    if (!kept.length || busy || editing) return;
    setBusy(true); setError(null);
    try {
      const { doc, pointers } = applySummary(set, leftOut, edits);
      const clean = tidy(doc);
      const missing = Object.values(briefErrors(clean)).flat().filter((e) => e.code === 'required').length;
      const stored = await saveBrief(projectId, clean, brief?.version ?? 0, missing > 0);
      const done = await confirmBrief(projectId, pointers, stored.version);
      qc.setQueryData(['design-brief', projectId], done);
      void qc.invalidateQueries({ queryKey: ['design-overview', projectId] });
      void qc.invalidateQueries({ queryKey: ['design-model', projectId] });
      onDone({ brief: done, confirmed: pointers });
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="proposal-summary-title" data-testid="proposal-summary" data-origin={set.origin}
      className="flex flex-col gap-3"
      onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void confirmAll(); } }}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="proposal-summary-title" ref={headRef} tabIndex={-1} className="text-base font-semibold text-content-primary outline-none">
          {tr(t, 'design.start.summary.title')}
        </h3>
        <p className="text-xs text-content-secondary" data-testid="summary-counts">
          {tr(t, 'design.start.summary.counts', { count: set.items.length })}
          {doubtful > 0 && <> · <span className="font-medium text-semantic-warning">{tr(t, 'design.start.summary.doubtful', { count: doubtful })}</span></>}
        </p>
      </div>
      <p className="text-sm text-content-secondary">{tr(t, 'design.start.summary.hint')}</p>

      {set.items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-secondary" data-testid="summary-empty">
          {set.known ? tr(t, 'design.start.summary.known', { count: set.known }) : tr(t, 'design.start.summary.nothing')}
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border-light overflow-hidden rounded-xl border border-border-light" data-testid="summary-items">
          {set.items.map((item) => {
            const out = leftOut.has(item.pointer);
            const corrected = item.pointer in edits;
            const value = corrected ? edits[item.pointer] : item.value;
            const doubt = item.doubt && !corrected ? item.doubt : null;
            return (
              <li key={item.pointer} data-testid={`summary-${item.pointer}`} data-doubt={doubt ?? undefined} data-out={out || undefined}
                className={clsx('flex flex-col gap-1 border-l-4 px-3 py-2.5 sm:flex-row sm:items-start sm:gap-4',
                  doubt ? 'border-l-semantic-warning bg-semantic-warning/5' : 'border-l-transparent',
                  out && 'opacity-60')}>
                <div className="min-w-0 sm:w-48 sm:shrink-0">
                  <p className="text-sm text-content-secondary">{fieldLabel(t, item.pointer)}</p>
                  {doubt && (
                    <p className="mt-0.5 inline-flex items-center gap-1 text-xs font-medium text-semantic-warning">
                      <AlertTriangle size={12} aria-hidden /> {tr(t, `design.start.doubt.${doubt}`)}
                    </p>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  {editing === item.pointer ? (
                    <ValueEditor pointer={item.pointer} value={value}
                      onSave={(v) => { setEdits((e) => ({ ...e, [item.pointer]: v })); setEditing(null); }}
                      onCancel={() => setEditing(null)} />
                  ) : (
                    <p className={clsx('text-sm font-medium text-content-primary', out && 'line-through')}>
                      {show(item.pointer, value)}
                      {corrected && <span className="ml-2 text-xs font-normal text-content-tertiary">{tr(t, 'design.start.corrected')}</span>}
                    </p>
                  )}
                  {!corrected && <SourceLine item={item} set={set} />}
                </div>
                <div className="flex shrink-0 gap-1">
                  {editable.has(item.pointer) && editing !== item.pointer && !out && (
                    <Button size="sm" variant="ghost" onClick={() => setEditing(item.pointer)}
                      aria-label={tr(t, 'design.start.correct_label', { field: fieldLabel(t, item.pointer) })}>
                      <Pencil size={14} aria-hidden /> <span className="hidden sm:inline">{tr(t, 'design.start.correct')}</span>
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" aria-pressed={out} onClick={() => toggle(item.pointer)}
                    aria-label={tr(t, out ? 'design.start.keep_label' : 'design.start.leave_out_label', { field: fieldLabel(t, item.pointer) })}>
                    {out ? <><Undo2 size={14} aria-hidden /> {tr(t, 'design.start.keep')}</> : tr(t, 'design.start.leave_out')}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {set.questions.length > 0 && (
        <p className="text-sm text-content-secondary" data-testid="summary-questions">
          {tr(t, 'design.start.summary.questions', { count: set.questions.length })}{' '}
          <Link className="text-oe-blue-text underline" to="/design/brief">{tr(t, 'design.brief.title')}</Link>
        </p>
      )}
      {error && <p role="alert" className="text-sm text-semantic-error">{error}</p>}
      <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-2 bg-surface-primary/95 px-1 py-2 backdrop-blur">
        <Button onClick={() => void confirmAll()} loading={busy} disabled={!kept.length || editing !== null}
          data-testid="confirm-all" icon={<CheckCheck size={16} aria-hidden />}>
          {tr(t, 'design.start.summary.confirm_all', { count: kept.length })}
        </Button>
        <Button variant="secondary" onClick={onDiscard} disabled={busy}>{tr(t, 'design.start.summary.discard')}</Button>
        <span className="hidden text-xs text-content-tertiary sm:inline">{tr(t, 'design.start.summary.shortcut')}</span>
      </div>
    </section>
  );
}
