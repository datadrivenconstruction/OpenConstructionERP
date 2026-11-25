// Design module (ERP side of the design editor link).
/**
 * Model panel: change the main design values (only those the generator takes, with its ranges) and get a new
 * revision built on the server by the R13 job; then open it on the acceptance screen. Shown to whoever may edit the
 * design of the project (its design rights: members or managers); accepting stays with the manager.
 * Beside the form, a simplified live preview built in the browser (ModelPreview); when it cannot run, the panel is as before.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Boxes } from 'lucide-react';
import { Button, Card, CardHeader } from '@/shared/ui';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { fetchAccess, fetchBrief, fetchGeneration } from './api';
import { fetchRights } from './draftApi';
import { fetchModel, generateModel, perFloor, rangeProblem, type ModelParam, type ModelValue } from './modelApi';
import { noWorkerText, tr } from './BriefFields';
import { ModelPreview, usePreview } from './ModelPreview';

export const ACTIVE = ['queued', 'running'];
const inputClass = (bad: boolean) => clsx(
  'h-9 w-full rounded-lg border bg-surface-primary px-3 text-sm text-content-primary',
  'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 disabled:opacity-60',
  bad ? 'border-semantic-error' : 'border-border',
);

type Draft = Record<string, ModelValue>;

/** State of the model values, the live preview and the server build; shared by the panel and the editor workspace. */
export function useModelEditor(projectId: string) {
  const { t } = useTranslation();
  const m = (key: string, o?: Record<string, unknown>) => t(key, o) as string;
  const queryClient = useQueryClient();
  const access = useQuery({ queryKey: ['design-access', projectId], queryFn: () => fetchAccess(projectId) });
  const brief = useQuery({ queryKey: ['design-brief', projectId], queryFn: () => fetchBrief(projectId) });
  const model = useQuery({ queryKey: ['design-model', projectId], queryFn: () => fetchModel(projectId),
    enabled: !!brief.data });
  const [started, setStarted] = useState<{ id: string; at: number } | null>(null);
  const gen = useQuery({
    queryKey: ['design-generation', projectId],
    queryFn: () => fetchGeneration(projectId),
    // keep asking until the job just started shows up: the first answer can still be the previous, finished one
    refetchInterval: (q) => {
      const j = q.state.data?.job;
      return (j && ACTIVE.includes(j.status)) || (started && j?.job_id !== started.id) ? 2000 : false;
    },
  });
  const [draft, setDraft] = useState<Draft>({});
  const [elapsed, setElapsed] = useState<number | null>(null);
  const view = model.data;
  const job = gen.data?.job ?? null;
  const active = !!job && ACTIVE.includes(job.status);
  const mine = started && job?.job_id === started.id ? job : null;

  // A new brief version arrives after a start: values shown again from the server, nothing kept locally.
  useEffect(() => { setDraft({}); }, [view?.brief_version]);

  const doneOnce = useRef<string | null>(null);
  useEffect(() => {
    if (!mine || ACTIVE.includes(mine.status) || doneOnce.current === mine.job_id || !started) return;
    doneOnce.current = mine.job_id;
    setElapsed(Math.round((Date.now() - started.at) / 1000));
    void queryClient.invalidateQueries({ queryKey: ['design-revisions', projectId] });
    void queryClient.invalidateQueries({ queryKey: ['design-overview', projectId] });
  }, [mine, started, projectId, queryClient]);

  const value = (p: { pointer: string; value: ModelValue }) => (p.pointer in draft ? draft[p.pointer] : p.value);
  const set = (pointer: string, v: ModelValue, original: ModelValue) =>
    setDraft((d) => {
      const next = { ...d };
      if (v === original) delete next[pointer];
      else next[pointer] = v;
      return next;
    });

  const floors = useMemo(() => {
    const p = view?.params.find((x) => x.id === 'floors');
    return p ? Number(value(p) ?? 1) : 1;
  }, [view, draft]); // eslint-disable-line react-hooks/exhaustive-deps
  const problems = useMemo(() => {
    const out: Record<string, string> = {};
    for (const p of view?.params ?? []) {
      if (!(p.pointer in draft)) continue;
      const why = rangeProblem(p, draft[p.pointer] ?? null);
      if (why) out[p.pointer] = why;
    }
    for (const u of view?.units ?? []) {
      if (!(u.pointer in draft)) continue;
      const why = rangeProblem({ kind: 'int', min: u.min, max: u.max, nullable: false }, draft[u.pointer] ?? null);
      if (why) out[u.pointer] = why;
    }
    return out;
  }, [view, draft]);
  const unitsPerFloor = (view?.units ?? []).reduce((s, u) => s + perFloor(Number(value(u) ?? 1), floors), 0);
  const widthParam = view?.params.find((p) => p.id === 'width');
  const width = widthParam ? Number(value(widthParam)) : NaN;
  const maxPerFloor = view?.apartment_frontage && width > 0
    ? Math.min(view.apartments_top ?? Infinity, 2 * Math.max(1, Math.floor(width / view.apartment_frontage)))
    : view?.max_units_per_floor ?? null;
  const tooMany = !!maxPerFloor && unitsPerFloor > maxPerFloor;
  const preview = usePreview(projectId, view?.brief_version, draft,
    !!view?.typology && Object.keys(problems).length === 0 && !tooMany);

  const start = useMutation({
    mutationFn: () => generateModel(projectId, view!.brief_version, draft),
    onSuccess: (r) => {
      setStarted({ id: r.job_id, at: Date.now() });
      setElapsed(null);
      void queryClient.invalidateQueries({ queryKey: ['design-generation', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['design-brief', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['design-model', projectId] });
    },
    // a refusal can follow a changed brief; the retry must carry the head version, not the cached one
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ['design-brief', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['design-model', projectId] });
    },
  });

  const doc = brief.data ?? null;
  const unconfirmed = Object.entries(doc?.provenance ?? {}).some(([p, e]) => e.status !== 'confirmed' && !(p in draft));
  const offReason = !gen.data?.enabled ? (gen.data?.reason ?? undefined) : undefined;
  const blocked = !gen.data?.enabled
    ? tr(t, 'design.generate.unavailable')
    : !doc || unconfirmed
      ? m('design.model.no_brief')
      : view && !view.typology
        ? m('design.model.no_generator')
        : access.data?.lock && !active
          ? tr(t, 'design.generate.locked', { name: access.data!.lock!.held_by })
          : null;
  const changed = Object.keys(draft).length;
  const invalid = Object.keys(problems).length > 0 || tooMany;
  const startError = start.error ? startErrorText(start.error, t) : null;
  const showPreview = preview.status !== 'off' && !!view?.typology;

  const fieldHint = (p: ModelParam) => {
    if (p.overridden) return m('design.model.overridden');
    const parts: string[] = [];
    if (p.min !== null && p.max !== null) {
      parts.push(m('design.model.range', { min: p.min, max: p.max, unit: p.unit ? m(`design.model.unit.${p.unit}`) : '' }).trim());
    }
    if (value(p) === null) {
      parts.push(p.default === null || p.default === undefined ? m('design.model.sized')
        : m('design.model.default', { value: shown(p.default) }));
    }
    return parts.join(' · ');
  };
  const shown = (v: ModelValue) => (typeof v === 'boolean' ? m(v ? 'design.model.yes' : 'design.model.no')
    : typeof v === 'string' ? m(`design.model.option.${v}`) : v === null ? m('design.model.option.none') : String(v));

  const loading = access.isLoading || brief.isLoading || gen.isLoading;
  return { m, access, brief, view, draft, setDraft, value, set, floors, problems, unitsPerFloor, maxPerFloor, tooMany, preview, start,
    job, active, mine, elapsed, blocked, offReason, changed, invalid, startError, showPreview, fieldHint, shown, loading,
    modelFailed: model.isError, genOff: !!gen.data && !gen.data.enabled };
}

export type ModelEditor = ReturnType<typeof useModelEditor>;

/** `fallback` stands in where this panel has nothing to offer (no edit right, a generator without parameters). */
export default function ModelPanel({ projectId, fallback = null }: { projectId: string; fallback?: ReactNode }) {
  const { t } = useTranslation();
  const ed = useModelEditor(projectId);
  const { m, access, preview, start, active, mine, elapsed, blocked, offReason, changed, invalid, startError, showPreview } = ed;
  const rights = useQuery({ queryKey: ['design-rights', projectId], queryFn: () => fetchRights(projectId), retry: false });
  if (ed.loading || rights.isLoading) return null;
  // The server decides with the same rule (model_api: can_edit); an older server without rights keeps managers only.
  if (!(rights.data ? rights.data.can_edit : access.data?.can_accept)) return <>{fallback}</>;
  if (ed.view && !ed.view.typology) return <>{fallback}</>;

  return (
    <Card data-testid="model-panel">
      <CardHeader title={m('design.model.title')} subtitle={m(ed.genOff ? 'design.model.hint_editor' : 'design.model.hint')} />
      {/* without the server generator the form cannot make a revision: say so first and point to the editor */}
      {ed.genOff && (
        <p className="mt-3 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-secondary" data-testid="model-gen-off" title={offReason}>
          {tr(t, 'design.generate.unavailable')} {tr(t, 'design.generate.unavailable_next')}{' '}
          <Link className="font-medium text-oe-blue-text underline" to="/design/editor">{tr(t, 'design.editor.open')}</Link>
        </p>
      )}
      <div className={clsx('mt-4', showPreview && 'grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(480px,52%)]')}>
        <div className="flex min-w-0 flex-col gap-4">
          <ModelForm ed={ed} />
          <div className="flex flex-wrap items-center gap-3">
            <Button icon={<Boxes size={16} aria-hidden />} loading={start.isPending}
              disabled={active || blocked !== null || invalid || !ed.view} onClick={() => start.mutate()}>
              {m('design.model.generate')}
            </Button>
            {changed > 0 && (
              <Button variant="secondary" disabled={active} onClick={() => ed.setDraft({})}>{m('design.model.reset')}</Button>
            )}
            <span className="text-sm text-content-secondary" data-testid="model-changed">
              {changed > 0 ? m('design.model.changed_n', { count: changed }) : m('design.model.unchanged')}
            </span>
          </div>
          {blocked && !active && !ed.genOff && <p className="text-sm text-content-secondary" data-testid="model-blocked"
            title={offReason}>{blocked}</p>}
          {startError && <p role="alert" className="text-sm text-semantic-error">{m('design.model.failed')}: {startError}</p>}
          {mine && ACTIVE.includes(mine.status) && (
            <progress className="h-2 w-full" max={1} value={mine.progress} aria-label={tr(t, 'design.generate.progress')} />
          )}
          {mine?.status === 'failed' && mine.error && <p role="alert" className="text-sm text-semantic-error">{mine.error}</p>}
          {mine?.status === 'done' && mine.revision_id && (
            <div className="flex flex-wrap items-center gap-3" data-testid="model-done">
              <span className="text-sm text-content-primary">{m('design.model.done')}</span>
              {elapsed !== null && <span className="text-xs text-content-tertiary">{m('design.model.elapsed', { seconds: elapsed })}</span>}
              <Link className="text-sm font-medium text-oe-blue hover:underline" to={`/design/acceptance?revision=${mine.revision_id}`}>
                {m('design.model.open_acceptance')}
              </Link>
            </div>
          )}
        </div>
        {showPreview && preview.status !== 'off' && <ModelPreview projectId={projectId} state={preview} genOff={ed.genOff} />}
      </div>
    </Card>
  );
}

/** The generator's values with their ranges (presets, parameters, dwellings per type). */
export function ModelForm({ ed, compact = false }: { ed: ModelEditor; compact?: boolean }) {
  const { m, view, value, set, setDraft, problems, active, floors, tooMany, unitsPerFloor, maxPerFloor, fieldHint, shown } = ed;
  // Beside the preview (xl) the form gets about half the card: two columns, so the viewer toolbar keeps one row.
  const grid = compact ? 'grid grid-cols-1 gap-3' : 'grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3';
  return (
    <>
          {view && view.presets.length > 0 && (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={m('design.model.presets')}>
              <span className="text-sm text-content-secondary">{m('design.model.presets')}</span>
              {view.presets.map((pr) => (
                <Button key={pr.id} variant="secondary" size="sm" disabled={active}
                  onClick={() => setDraft((d) => {
                    const next = { ...d };
                    for (const [ptr, v] of Object.entries(pr.values)) {
                      const orig = [...view.params, ...view.units].find((x) => x.pointer === ptr)?.value ?? null;
                      if (v === orig) delete next[ptr];
                      else next[ptr] = v;
                    }
                    return next;
                  })}>
                  {m(`design.model.preset.${pr.id}`)}
                </Button>
              ))}
            </div>
          )}
          {view && view.typology && (
            <div className={grid}>
              {view.params.map((p) => {
                const id = `model-${p.id}`;
                const v = value(p);
                const bad = !!problems[p.pointer];
                const off = p.overridden || active;
                const slopeIdle = p.id === 'roof_slope' && (value(view.params.find((x) => x.id === 'roof')!) ?? 'flat') === 'flat';
                return (
                  <div key={p.id} className="flex flex-col gap-1">
                    <label htmlFor={id} className="text-sm font-medium text-content-primary">
                      {m(`design.model.param.${p.id}`)}{p.unit && p.unit !== 'storeys' && p.kind !== 'bool' ? `, ${m(`design.model.unit.${p.unit}`)}` : ''}
                    </label>
                    {p.kind === 'bool' ? (
                      <select id={id} className={inputClass(bad)} disabled={off}
                        value={v === null ? '' : String(v)}
                        onChange={(e) => set(p.pointer, e.target.value === '' ? null : e.target.value === 'true', p.value)}>
                        {p.nullable && <option value="">{m('design.model.default', { value: shown(p.default) })}</option>}
                        <option value="true">{m('design.model.yes')}</option>
                        <option value="false">{m('design.model.no')}</option>
                      </select>
                    ) : p.kind === 'choice' ? (
                      <select id={id} className={inputClass(bad)} disabled={off} value={v === null ? '' : String(v)}
                        onChange={(e) => set(p.pointer, e.target.value === '' ? null : e.target.value, p.value)}>
                        {(p.options ?? []).map((o) => (
                          <option key={String(o)} value={o ?? ''}>{shown(o)}</option>
                        ))}
                      </select>
                    ) : (
                      <input id={id} type="number" inputMode="decimal" className={inputClass(bad)} disabled={off || slopeIdle}
                        min={p.min ?? undefined} max={p.max ?? undefined} step={p.step ?? 'any'}
                        value={v === null || v === undefined ? '' : String(v)}
                        placeholder={p.default !== null && p.default !== undefined ? String(p.default) : ''}
                        aria-invalid={bad || undefined} aria-describedby={`${id}-hint`}
                        onChange={(e) => set(p.pointer, e.target.value === '' ? null : Number(e.target.value), p.value)} />
                    )}
                    <span id={`${id}-hint`} className={clsx('text-xs', bad ? 'text-semantic-error' : 'text-content-tertiary')}>
                      {bad ? m(`design.model.problem.${problems[p.pointer]}`) : fieldHint(p)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          {view && view.units.length > 0 && (
            <fieldset className="flex flex-col gap-2">
              <legend className="text-sm font-medium text-content-primary">{m('design.model.units')}</legend>
              <div className={grid}>
                {view.units.map((u) => {
                  const id = `model-unit-${u.index}`;
                  const v = value(u);
                  const bad = !!problems[u.pointer];
                  return (
                    <div key={u.pointer} className="flex flex-col gap-1">
                      <label htmlFor={id} className="text-sm text-content-primary">{u.name ?? `#${u.index + 1}`}</label>
                      <input id={id} type="number" inputMode="numeric" className={inputClass(bad)} min={u.min} max={u.max} step={1}
                        disabled={u.overridden || active} value={v === null ? '' : String(v)} aria-invalid={bad || undefined}
                        onChange={(e) => set(u.pointer, e.target.value === '' ? null : Number(e.target.value), u.value)} />
                      <span className={clsx('text-xs', bad ? 'text-semantic-error' : 'text-content-tertiary')}>
                        {bad ? m(`design.model.problem.${problems[u.pointer]}`)
                          : m('design.model.per_floor', { count: perFloor(Number(v ?? 1), floors) })}
                      </span>
                    </div>
                  );
                })}
              </div>
              {tooMany && (
                <p role="alert" className="text-sm text-semantic-error">
                  {m('design.model.units_too_many', { count: unitsPerFloor, max: maxPerFloor })}
                </p>
              )}
            </fieldset>
          )}
    </>
  );
}

function startErrorText(err: unknown, t: ReturnType<typeof useTranslation>['t']): string {
  const noWorker = noWorkerText(err, t);
  if (noWorker) return noWorker;
  if (err instanceof ApiError && err.status === 409) {
    const detail = (err.body as { detail?: { held_by?: string } } | null)?.detail;
    if (detail && typeof detail === 'object' && detail.held_by) return tr(t, 'design.generate.locked', { name: detail.held_by });
  }
  if (err instanceof ApiError && err.status === 422) {
    const errors = (err.body as { detail?: { errors?: { pointer: string; message: string }[] } } | null)?.detail?.errors;
    if (errors?.length) return errors.map((e) => `${e.pointer}: ${e.message}`).join('; ');
  }
  return getErrorMessage(err);
}
