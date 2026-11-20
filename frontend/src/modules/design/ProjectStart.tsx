// Design module (ERP side of the design editor link).
/**
 * First screen of a project made from modules: four equal ways in — describe it in words, upload drawings or
 * photos, pick a template, draw the plot on a map. Each ends on the one summary screen (ProposalSummary): AI or
 * the template proposes, the person corrects and confirms everything with one button. Then the path goes on:
 * confirmed brief → model → estimate, schedule and procurement, all linked.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ArrowRight, Check, CheckCircle2, FileUp, LayoutTemplate, Loader2, Map as MapIcon, MessageSquareText, RotateCcw,
  Sparkles, X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Button, ErrorState, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import { extractBrief, fetchAiSettings, fetchBrief } from './api';
import { editField, getAt, newBrief, PLOT_POINTER, type BriefDoc } from './data/briefModel';
import { aiConfigured } from './data/workspace';
import { fromExtraction, fromValues, type ProposalSet } from './data/proposals';
import type { OverviewStep } from './linksApi';
import { PlotEditor } from './PlotEditor';
import { ProposalSummary, type SummaryOutcome } from './ProposalSummary';
import { tr } from './BriefFields';
import {
  ACCEPT, acceptable, extractFromFiles, fetchTemplates, MAX_FILES, uploadSource, type StartTemplate,
} from './startApi';

export type Way = 'describe' | 'upload' | 'template' | 'map';
export const WAYS: { id: Way; icon: LucideIcon }[] = [
  { id: 'describe', icon: MessageSquareText },
  { id: 'upload', icon: FileUp },
  { id: 'template', icon: LayoutTemplate },
  { id: 'map', icon: MapIcon },
];

interface Ctx {
  projectId: string;
  brief: BriefDoc | null;
  base: BriefDoc;
  aiReady: boolean;
  propose: (set: ProposalSet) => void;
}

/* ── 1. describe ─────────────────────────────────────────────────────── */

function DescribeWay({ projectId, brief, aiReady, propose }: Ctx) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const read = async () => {
    setBusy(true); setError(null);
    try {
      const x = await extractBrief(projectId, text.trim(), brief);
      propose(fromExtraction('text', x.brief, x.summary.proposed, x.summary.questions, undefined, x.summary.confirmed?.length ?? 0));
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-3">
      <label htmlFor="start-describe" className="text-sm font-medium text-content-primary">{tr(t, 'design.start.describe.label')}</label>
      <textarea id="start-describe" value={text} onChange={(e) => setText(e.target.value)} rows={6} maxLength={20000}
        placeholder={tr(t, 'design.start.describe.placeholder')}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && text.trim()) { e.preventDefault(); void read(); } }}
        className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary" />
      <AiNote aiReady={aiReady} />
      {error && <p role="alert" className="text-sm text-semantic-error">{error}</p>}
      <div>
        <Button onClick={() => void read()} loading={busy} disabled={!text.trim() || busy} icon={<Sparkles size={16} aria-hidden />}>
          {tr(t, 'design.start.describe.read')}
        </Button>
      </div>
    </div>
  );
}

function AiNote({ aiReady }: { aiReady: boolean }) {
  const { t } = useTranslation();
  return aiReady ? null : (
    <p className="text-xs text-content-tertiary" data-testid="start-no-ai">
      {tr(t, 'design.workspace.ai.no_ai')}{' '}
      <Link className="text-oe-blue-text underline" to="/settings?tab=ai">{tr(t, 'design.start.ai_settings')}</Link>
    </p>
  );
}

/* ── 2. upload ───────────────────────────────────────────────────────── */

interface Upload { key: string; name: string; status: 'uploading' | 'ready' | 'failed'; id?: string; error?: string }

function UploadWay({ projectId, brief, aiReady, propose }: Ctx) {
  const { t } = useTranslation();
  const [files, setFiles] = useState<Upload[]>([]);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const add = (list: FileList | File[]) => {
    setError(null);
    const picked = [...list];
    const bad = picked.filter((f) => !acceptable(f.name));
    if (bad.length) setError(tr(t, 'design.start.upload.wrong_type', { names: bad.map((f) => f.name).join(', ') }));
    const room = MAX_FILES - files.length;
    const ok = picked.filter((f) => acceptable(f.name)).slice(0, Math.max(0, room));
    if (picked.filter((f) => acceptable(f.name)).length > ok.length) setError(tr(t, 'design.start.upload.too_many', { count: MAX_FILES }));
    for (const f of ok) {
      const key = `${f.name}-${f.size}-${Math.random().toString(36).slice(2, 8)}`;
      setFiles((cur) => [...cur, { key, name: f.name, status: 'uploading' }]);
      uploadSource(projectId, f).then(
        (doc) => setFiles((cur) => cur.map((x) => (x.key === key ? { ...x, status: 'ready', id: doc.id } : x))),
        (e) => setFiles((cur) => cur.map((x) => (x.key === key ? { ...x, status: 'failed', error: getErrorMessage(e) } : x))),
      );
    }
  };
  const ready = files.filter((f) => f.status === 'ready');
  const uploading = files.some((f) => f.status === 'uploading');

  const read = async () => {
    setBusy(true); setError(null);
    try {
      const x = await extractFromFiles(projectId, ready.map((f) => f.id!), brief);
      const names = Object.fromEntries(ready.map((f) => [f.id!, f.name]));
      propose(fromExtraction('files', x.brief, x.summary.proposed, x.summary.questions, names, x.summary.confirmed?.length ?? 0));
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
        data-testid="start-dropzone"
        className={clsx('flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors',
          over ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light')}>
        <FileUp size={28} aria-hidden className="text-content-tertiary" />
        <p className="text-sm text-content-primary">{tr(t, 'design.start.upload.drop')}</p>
        <p className="text-xs text-content-tertiary">{tr(t, 'design.start.upload.types')}</p>
        <Button variant="secondary" size="sm" onClick={() => input.current?.click()}>{tr(t, 'design.start.upload.pick')}</Button>
        <input ref={input} type="file" multiple accept={ACCEPT.join(',')} className="sr-only" tabIndex={-1}
          aria-label={tr(t, 'design.start.upload.pick')}
          onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ''; }} />
      </div>
      {files.length > 0 && (
        <ul className="flex flex-col gap-1.5" aria-live="polite" data-testid="start-files">
          {files.map((f) => (
            <li key={f.key} className="flex items-center gap-2 rounded-md border border-border-light px-3 py-1.5 text-sm">
              {f.status === 'uploading' ? <Loader2 size={14} className="animate-spin text-content-tertiary" aria-hidden />
                : f.status === 'ready' ? <Check size={14} className="text-semantic-success" aria-hidden />
                  : <X size={14} className="text-semantic-error" aria-hidden />}
              <span className="min-w-0 flex-1 truncate text-content-primary">{f.name}</span>
              <span className={clsx('shrink-0 text-xs', f.status === 'failed' ? 'text-semantic-error' : 'text-content-tertiary')}>
                {f.status === 'failed' ? f.error : tr(t, `design.start.upload.${f.status}`)}
              </span>
              {f.status !== 'uploading' && (
                <button type="button" className="rounded p-1 text-content-tertiary hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue"
                  aria-label={tr(t, 'design.start.upload.remove', { name: f.name })}
                  onClick={() => setFiles((cur) => cur.filter((x) => x.key !== f.key))}>
                  <X size={14} aria-hidden />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {files.length > 0 && <p className="text-xs text-content-tertiary">{tr(t, 'design.start.upload.kept')}</p>}
      <AiNote aiReady={aiReady} />
      {error && <p role="alert" className="text-sm text-semantic-error">{error}</p>}
      <div>
        <Button onClick={() => void read()} loading={busy} disabled={!ready.length || uploading || busy}
          icon={<Sparkles size={16} aria-hidden />} data-testid="start-read-files">
          {tr(t, 'design.start.upload.read', { count: ready.length })}
        </Button>
      </div>
    </div>
  );
}

/* ── 3. template ─────────────────────────────────────────────────────── */

function TemplateWay({ base, propose }: Ctx) {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ['design-templates'], queryFn: fetchTemplates, staleTime: Infinity });
  const [picked, setPicked] = useState<string | null>(null);
  const list = q.data?.templates ?? [];
  const use = (tpl: StartTemplate) => propose(fromValues('template', base, tpl.values.map((v) => ({
    pointer: v.pointer, value: v.value, doubtful: v.doubtful, source: { kind: 'user' as const },
    note: `Template ${tpl.id}: generator defaults (${tpl.source})`,
  }))));
  const move = (e: React.KeyboardEvent, i: number) => {
    const n = list.length;
    const to = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? (i + 1) % n : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? (i - 1 + n) % n : -1;
    if (to < 0) return;
    e.preventDefault();
    setPicked(list[to]!.id);
    (e.currentTarget.parentElement?.children[to] as HTMLElement | undefined)?.focus();
  };
  if (q.isError) return <ErrorState title={tr(t, 'design.start.template.failed')} hint={getErrorMessage(q.error)} onRetry={() => q.refetch()} />;
  if (q.isLoading) return <Skeleton className="h-40 w-full" />;
  const chosen = list.find((x) => x.id === picked) ?? null;
  return (
    <div className="flex flex-col gap-3">
      <div role="radiogroup" aria-label={tr(t, 'design.start.way.template')} className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3"
        data-testid="start-templates">
        {list.map((tpl, i) => {
          const on = tpl.id === picked;
          return (
            <button key={tpl.id} type="button" role="radio" aria-checked={on} tabIndex={on || (!picked && i === 0) ? 0 : -1}
              onClick={() => setPicked(tpl.id)} onKeyDown={(e) => move(e, i)} data-testid={`template-${tpl.id}`}
              className={clsx('flex flex-col items-start gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue',
                on ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light hover:border-oe-blue/60 hover:bg-surface-secondary')}>
              <span className="text-sm font-medium text-content-primary">{tr(t, `design.start.template.${tpl.id}`)}</span>
              <span className="text-xs text-content-secondary">{tr(t, `design.start.template.${tpl.id}_hint`, { floors: tpl.max_floors })}</span>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-content-tertiary">{tr(t, 'design.start.template.note')}</p>
      <div>
        <Button onClick={() => chosen && use(chosen)} disabled={!chosen} data-testid="start-use-template">
          {tr(t, 'design.start.template.use')}
        </Button>
      </div>
    </div>
  );
}

/* ── 4. map ──────────────────────────────────────────────────────────── */

function MapWay({ base, propose, focus }: Ctx & { focus: { lat: number; lng: number } | null }) {
  const { t } = useTranslation();
  const [doc, setDoc] = useState<BriefDoc>(base);
  const plot = getAt(doc, PLOT_POINTER);
  const onChange = useCallback((pointer: string, value: unknown) => setDoc((d) => editField(d, pointer, value, 'map')), []);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-content-secondary">{tr(t, 'design.start.map.hint')}</p>
      <PlotEditor doc={doc} errors={[]} focus={focus} onChange={onChange}
        provenance={{ onConfirm: null, confirmBlockedReason: tr(t, 'design.start.map.confirm_below') }} />
      <div>
        <Button disabled={plot === undefined} data-testid="start-use-plot"
          onClick={() => propose(fromValues('map', base, [{ pointer: PLOT_POINTER, value: plot, source: { kind: 'map' } }]))}>
          {tr(t, 'design.start.map.use')}
        </Button>
      </div>
    </div>
  );
}

/* ── path after the start ────────────────────────────────────────────── */

function Journey({ steps, confirmed }: { steps: OverviewStep[]; confirmed: number }) {
  const { t } = useTranslation();
  const by = Object.fromEntries(steps.map((s) => [s.id, s]));
  const linked = ['estimate', 'schedule', 'procurement'].filter((id) => by[id]?.done).length;
  const stages = [
    { id: 'brief', done: !!by.brief?.done || confirmed > 0, text: tr(t, 'design.start.path.brief') },
    { id: 'model', done: !!by.model?.done, text: tr(t, 'design.start.path.model') },
    { id: 'linked', done: linked === 3, text: tr(t, 'design.start.path.linked') },
  ];
  return (
    <ol className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-0" aria-label={tr(t, 'design.start.path.title')} data-testid="start-path">
      {stages.map((s, i) => (
        <li key={s.id} className="flex items-center gap-2 sm:flex-1" data-done={s.done || undefined}>
          <span className={clsx('flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
            s.done ? 'bg-semantic-success/15 text-semantic-success' : 'bg-surface-secondary text-content-tertiary')}>
            {s.done ? <Check size={14} aria-hidden /> : i + 1}
          </span>
          <span className="text-sm text-content-secondary">{s.text}</span>
          <span className="sr-only">{tr(t, s.done ? 'design.overview.status.done' : 'design.overview.status.todo')}</span>
          {i < stages.length - 1 && <ArrowRight size={14} aria-hidden className="mx-2 hidden shrink-0 text-content-tertiary sm:block" />}
        </li>
      ))}
    </ol>
  );
}

/* ── the screen ──────────────────────────────────────────────────────── */

export function ProjectStart({ projectId, steps = [] }: { projectId: string; steps?: OverviewStep[] }) {
  const { t } = useTranslation();
  const project = useQuery({ queryKey: ['projects', projectId], queryFn: () => projectsApi.get(projectId) });
  const brief = useQuery({ queryKey: ['design-brief', projectId], queryFn: () => fetchBrief(projectId) });
  const ai = useQuery({ queryKey: ['ai-settings'], queryFn: fetchAiSettings, staleTime: 60_000 });
  const [way, setWay] = useState<Way>('describe');
  const [pending, setPending] = useState<ProposalSet | null>(null);
  const [done, setDone] = useState<(SummaryOutcome & { way: Way }) | null>(null);
  const [confirmedTotal, setConfirmedTotal] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  const base = useMemo<BriefDoc | null>(() => {
    if (brief.data) return brief.data;
    if (!project.data || !brief.isSuccess) return null;
    const p = project.data;
    return newBrief({ id: projectId, country_code: p.country_code, locale: p.locale, currency: p.currency, name: p.name },
      crypto.randomUUID());
  }, [brief.data, brief.isSuccess, project.data, projectId]);

  const choose = (w: Way) => { setWay(w); setPending(null); setDone(null); };
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const n = WAYS.length;
    const to = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? (i + 1) % n
      : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? (i - 1 + n) % n
        : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    choose(WAYS[to]!.id);
    tabs.current[to]?.focus();
  };

  const addr = project.data?.address;
  const focus = addr?.lat != null && addr?.lng != null ? { lat: addr.lat, lng: addr.lng } : null;
  const modelStep = steps.find((s) => s.id === 'model');
  const hasBrief = !!brief.data;

  return (
    <section aria-labelledby="start-title" data-testid="project-start"
      className="flex flex-col gap-4 rounded-xl border border-border-light bg-surface-primary p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <h2 id="start-title" className="text-lg font-semibold text-content-primary">
          {tr(t, hasBrief ? 'design.start.title_more' : 'design.start.title')}
        </h2>
        <p className="text-sm text-content-secondary">{tr(t, 'design.start.subtitle')}</p>
      </div>

      <div role="tablist" aria-label={tr(t, 'design.start.ways')} className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {WAYS.map((w, i) => {
          const on = way === w.id;
          const Icon = w.icon;
          return (
            <button key={w.id} ref={(el) => { tabs.current[i] = el; }} type="button" role="tab" id={`start-tab-${w.id}`}
              aria-selected={on} aria-controls="start-panel" tabIndex={on ? 0 : -1}
              onClick={() => choose(w.id)} onKeyDown={(e) => onKey(e, i)} data-testid={`way-${w.id}`}
              className={clsx('flex items-start gap-3 rounded-lg border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue',
                on ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light hover:border-oe-blue/60 hover:bg-surface-secondary')}>
              <span className={clsx('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg',
                on ? 'bg-oe-blue text-white' : 'bg-surface-secondary text-content-secondary')}>
                <Icon size={18} aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium text-content-primary">{tr(t, `design.start.way.${w.id}`)}</span>
                <span className="block text-xs text-content-secondary">{tr(t, `design.start.way.${w.id}_hint`)}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div id="start-panel" role="tabpanel" aria-labelledby={`start-tab-${way}`} className="min-h-[12rem]">
        {project.isError || brief.isError ? (
          <ErrorState title={tr(t, 'design.brief.load_failed')} hint={getErrorMessage(project.error ?? brief.error)}
            onRetry={() => { void project.refetch(); void brief.refetch(); }} />
        ) : !base ? (
          <Skeleton className="h-48 w-full" />
        ) : done ? (
          <div className="flex flex-col gap-3 rounded-lg border border-semantic-success/40 bg-semantic-success/5 p-4" role="status" data-testid="start-done">
            <p className="flex items-center gap-2 text-sm font-medium text-content-primary">
              <CheckCircle2 size={18} className="text-semantic-success" aria-hidden />
              {tr(t, 'design.start.done', { count: done.confirmed.length, version: done.brief.version })}
            </p>
            <div className="flex flex-wrap gap-2">
              <Link to={modelStep?.url ?? '/design/revisions'} data-testid="start-next-model"
                className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue">
                {tr(t, 'design.start.next.model')} <ArrowRight size={14} aria-hidden />
              </Link>
              <Link to="/design/brief" className="inline-flex items-center rounded-lg border border-border-light px-3 py-1.5 text-sm text-content-primary hover:bg-surface-secondary">
                {tr(t, 'design.start.next.brief')}
              </Link>
              <Button variant="ghost" size="sm" icon={<RotateCcw size={14} aria-hidden />} onClick={() => setDone(null)}>
                {tr(t, 'design.start.next.more')}
              </Button>
            </div>
          </div>
        ) : pending ? (
          <ProposalSummary projectId={projectId} brief={brief.data ?? null} set={pending}
            onDiscard={() => setPending(null)}
            onDone={(o) => { setPending(null); setDone({ ...o, way }); setConfirmedTotal((n) => n + o.confirmed.length); }} />
        ) : (
          (() => {
            const ctx: Ctx = { projectId, brief: brief.data ?? null, base, aiReady: aiConfigured(ai.data), propose: setPending };
            if (way === 'describe') return <DescribeWay {...ctx} />;
            if (way === 'upload') return <UploadWay {...ctx} />;
            if (way === 'template') return <TemplateWay {...ctx} />;
            return <MapWay key={base.version} {...ctx} focus={focus} />;
          })()
        )}
      </div>

      <div className="border-t border-border-light pt-3">
        <Journey steps={steps} confirmed={confirmedTotal} />
      </div>
    </section>
  );
}
