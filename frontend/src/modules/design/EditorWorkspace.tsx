// Design module (ERP side of the design editor link).
/**
 * Design editor page: a full-screen workspace inside the ERP. The canvas runs the browser editor when this ERP
 * publishes one (`ddc-web-editor/1`, bridge `ddc-web-bridge/1`), else the generator already in the module (brief
 * values + live 3D). Every edit in the editor autosaves the person's draft; its quantities and estimate lines show at
 * once on the right, beside the selection. One button makes a revision for acceptance from the draft (the desktop
 * editor's intake). Editing needs a desktop browser and the project's edit right; otherwise look and select.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, CloudOff, FolderOpen, GitCommitVertical, Loader2, Monitor, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { Button, EmptyState } from '@/shared/ui';
import { projectsApi } from '@/features/projects/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useProjectFromUrl } from './useProjectFromUrl';
import { selectionFromUrl } from './linksApi';
import { fetchAiSettings, fetchBrief, fetchRevisions } from './api';
import { bridgeError, connectBridge, framePort, modulePort, type BridgeHost, type BridgeState, type EditorModule } from './bridge/host';
import { DRAFT_FILE, type SelectedElement } from './bridge/protocol';
import { aiConfigured, chainTip, deviceMode, openMessage } from './data/workspace';
import { readConsent, type Payload } from './data/webEditor';
import { currentPayload, startBackgroundLoad } from './editorPayload';
import { fetchDraft, fetchRights, makeRevision, readDraftPackage, readRevisionFile, saveDraft, type DesignRights, type DraftView } from './draftApi';
import type { RevisionView } from './data/revisions';
import { ACTIVE, ModelForm, useModelEditor } from './ModelPanel';
import { ModelPreview } from './ModelPreview';
import { TipModel } from './TipModel';
import { AiBriefBox, type AiOutcome } from './AiBriefBox';
import { SelectionPanel } from './SelectionPanel';
import { WorkspaceSettings } from './WorkspaceSettings';
import { useLeaveGuard } from './useLeaveGuard';
import { useDemoServer } from '@/shared/lib/useDemoModules';
import { tr } from './BriefFields';
import { getIntlLocale } from '@/shared/lib/formatters';

export default function EditorWorkspacePage() {
  const { t } = useTranslation();
  useProjectFromUrl();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  if (!projectId) {
    return (
      <EmptyState icon={<FolderOpen size={28} aria-hidden />} title={tr(t, 'design.brief.no_project')}
        description={tr(t, 'design.editor.no_project_hint')} />
    );
  }
  return <Workspace key={projectId} projectId={projectId} />;
}

const theme = (): 'light' | 'dark' =>
  typeof document !== 'undefined' && document.documentElement.classList.contains('dark') ? 'dark' : 'light';

function readDevice(): 'edit' | 'view' {
  if (typeof window === 'undefined') return 'edit';
  const fine = typeof window.matchMedia === 'function' ? window.matchMedia('(hover: hover) and (pointer: fine)').matches : true;
  return deviceMode({ finePointer: fine, width: window.innerWidth });
}

function useDevice(): 'edit' | 'view' {
  const [d, setD] = useState(readDevice);
  useEffect(() => {
    const on = () => setD(readDevice());
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return d;
}

type DraftState = { status: 'idle' } | { status: 'saving' } | { status: 'saved'; at: string } | { status: 'failed'; reason: string };

const time = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString(getIntlLocale(), { hour: '2-digit', minute: '2-digit' });
};

/** Why a revision could not be made, in words: someone else edits, or the chain moved on under the draft. */
export function revisionError(t: ReturnType<typeof useTranslation>['t'], e: unknown): string {
  const err = bridgeError(e);
  const body = (e as { body?: { detail?: unknown } })?.body?.detail;
  const who = body && typeof body === 'object' ? (body as { held_by?: string }).held_by : undefined;
  if (err.code === 'locked' && who) return tr(t, 'design.workspace.locked', { who });
  if (err.code === 'locked') return tr(t, 'design.workspace.stale');
  if (body && typeof body === 'object' && (body as { code?: string }).code === 'revision_too_large') return tr(t, 'design.workspace.too_large');
  return typeof body === 'string' ? body : err.message;
}

type EditorMode = 'quick' | 'full';
const MODE_KEY = 'oe_design_editor_mode';
function readEditorMode(): EditorMode {
  try { return localStorage.getItem(MODE_KEY) === 'quick' ? 'quick' : 'full'; } catch { return 'full'; }
}
function writeEditorMode(m: EditorMode): void {
  try { localStorage.setItem(MODE_KEY, m); } catch { /* private mode: the choice lasts for this page */ }
}

function Workspace({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [payload, setPayload] = useState<(Payload & { fallback?: string }) | null>(null);
  const [bridge, setBridge] = useState<BridgeState | null>(null);
  // ?select=k1,k2 (from an estimate position or a BOQ row): those elements, selected as soon as the editor is open
  const [params] = useSearchParams();
  const [selection, setSelection] = useState<SelectedElement[]>(() => selectionFromUrl(params.get('select')));
  const pendingSelect = useRef(selection.length > 0);
  const [dirty, setDirty] = useState(false);
  const [draftState, setDraftState] = useState<DraftState>({ status: 'idle' });
  const [created, setCreated] = useState<RevisionView | null>(null);
  const link = useRef<BridgeHost | null>(null);
  const device = useDevice();
  // Both ways to work stay on offer: the quick concept from the brief values, or the full editor on the same project.
  const [want, setWant] = useState<EditorMode>(readEditorMode);
  const choose = (m: EditorMode) => { setBridge(null); setWant(m); writeEditorMode(m); };

  useEffect(() => {
    let live = true;
    void currentPayload().then((p) => { if (live) setPayload(p); });
    // the page itself is the strongest hint the editor will be wanted: finish a load the person agreed to
    if (readConsent() === 'yes') void startBackgroundLoad('yes');
    return () => { live = false; };
  }, []);
  useLeaveGuard(dirty || draftState.status === 'saving', tr(t, 'design.workspace.leave'));

  const project = useQuery({ queryKey: ['projects', projectId], queryFn: () => projectsApi.get(projectId) });
  const rights = useQuery({ queryKey: ['design-rights', projectId], queryFn: () => fetchRights(projectId) });
  const demoServer = useDemoServer();
  const draft = useQuery({ queryKey: ['design-draft', projectId], queryFn: () => fetchDraft(projectId) });
  const mode: 'edit' | 'view' = rights.data?.can_edit && device === 'edit' ? 'edit' : 'view';
  const viewWhy = !rights.data || mode === 'edit' ? null
    // the public demo signs everyone in read-only: that, not the person's role, is why
    : !rights.data.can_edit ? tr(t, demoServer ? 'design.workspace.view_demo'
      : rights.data.edit === 'managers' ? 'design.workspace.view_rights' : 'design.workspace.view_role')
      : tr(t, 'design.workspace.view_device');

  const select = useCallback((els: SelectedElement[]) => setSelection(els), []);
  useEffect(() => {
    if (bridge?.status !== 'open' || !pendingSelect.current) return;
    pendingSelect.current = false;
    link.current?.select(selection);
  }, [bridge, selection]);
  // a turned tablet or changed rights: the editor learns its new mode
  useEffect(() => { void link.current?.reopen().catch(() => undefined); }, [mode]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.key !== 'Escape' || el?.closest('input,textarea,select,[role="dialog"]')) return;
      setSelection([]);
      link.current?.select([]);
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, []);

  const make = useMutation({
    mutationFn: () => makeRevision(projectId),
    onSuccess: (rev) => {
      setCreated(rev);
      setDraftState({ status: 'idle' });
      qc.setQueryData(['design-draft', projectId], null);
      void qc.invalidateQueries({ queryKey: ['design-revisions', projectId] });
      void qc.invalidateQueries({ queryKey: ['design-estimate', projectId] });
      void link.current?.reopen();
    },
  });

  // The editor is used when the bundle is there and the bridge did not refuse or fail; otherwise today's engine.
  const editorOn = payload?.kind === 'editor' && want === 'full' && bridge?.status !== 'refused' && bridge?.status !== 'failed';
  const engineLabel = !payload ? '' : editorOn && bridge?.status === 'open'
    ? tr(t, 'design.workspace.engine_editor', { version: bridge.editor.version })
    : editorOn ? tr(t, 'design.workspace.engine_starting') : tr(t, 'design.workspace.engine_simple_short');
  const engineHint = payload && !editorOn ? tr(t, 'design.workspace.engine_simple') : '';

  const draftStatus = mode === 'view' ? null
    : draftState.status === 'saving' ? <><Loader2 size={14} className="animate-spin" aria-hidden />{tr(t, 'design.workspace.draft.saving')}</>
      : draftState.status === 'failed' ? <><CloudOff size={14} className="text-semantic-error" aria-hidden />{tr(t, 'design.workspace.draft.failed', { reason: draftState.reason })}</>
        : draft.data ? <><Check size={14} className="text-semantic-success" aria-hidden />{tr(t, 'design.workspace.draft.saved', { time: time(draftState.status === 'saved' ? draftState.at : draft.data.updated_at) })}</>
          : <span className="text-content-tertiary">{tr(t, 'design.workspace.draft.none')}</span>;

  const createButton = mode === 'edit' && editorOn ? (
    <Button size="sm" icon={<GitCommitVertical size={14} aria-hidden />} loading={make.isPending} data-testid="create-revision"
      disabled={!draft.data || make.isPending || draftState.status === 'saving'}
      title={draft.data ? tr(t, 'design.workspace.create_hint') : tr(t, 'design.workspace.no_draft')}
      onClick={() => { setCreated(null); make.mutate(); }}>
      {tr(t, 'design.workspace.create_revision')}
    </Button>
  ) : null;

  const header = (engineAction: ReactNode) => (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border-light bg-surface-primary px-4 py-2">
      <div className="me-auto flex min-w-0 flex-col">
        <h1 className="truncate text-base font-semibold text-content-primary">
          {tr(t, 'design.editor.title')}
          {project.data?.name ? <span className="font-normal text-content-secondary"> · {project.data.name}</span> : null}
        </h1>
        <span className="truncate text-xs text-content-tertiary" data-testid="engine-label" title={engineHint || undefined}>{engineLabel}</span>
      </div>
      {payload?.kind === 'editor' && (
        <div role="group" aria-label={tr(t, 'design.workspace.mode_label')} data-testid="editor-mode"
          className="inline-flex h-8 items-stretch rounded-md border border-border p-0.5">
          {(['quick', 'full'] as const).map((m) => (
            // unsaved work in the full editor is not dropped by a switch: leave it to Save or Discard first
            <button key={m} type="button" aria-pressed={want === m} disabled={want !== m && dirty}
              title={want !== m && dirty ? tr(t, 'design.workspace.leave') : undefined} onClick={() => choose(m)}
              className={want === m
                ? 'rounded px-2.5 text-sm font-medium text-content-primary bg-surface-secondary'
                : 'rounded px-2.5 text-sm text-content-secondary hover:text-content-primary disabled:opacity-50'}>
              {tr(t, `design.workspace.mode_${m}`)}
            </button>
          ))}
        </div>
      )}
      {editorOn && draftStatus && (
        <span role="status" aria-live="polite" data-testid="draft-status" className="flex items-center gap-1.5 text-xs text-content-secondary">
          {draftStatus}
        </span>
      )}
      {createButton}
      {engineAction}
      <Link to="/design/editor/desktop" data-testid="open-desktop"
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-content-primary hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue">
        <Monitor size={14} aria-hidden /> <span className="hidden sm:inline">{tr(t, 'design.workspace.desktop')}</span>
      </Link>
      <WorkspaceSettings projectId={projectId} rights={rights.data} />
    </header>
  );

  const banners = (
    <>
      {viewWhy && <p className="border-b border-border-light bg-surface-secondary px-4 py-1.5 text-sm text-content-secondary" data-testid="view-why">{viewWhy}</p>}
      {created && (
        <p role="status" className="flex flex-wrap items-center gap-2 border-b border-border-light bg-semantic-success-bg px-4 py-1.5 text-sm" data-testid="revision-created">
          {tr(t, 'design.workspace.created', { number: created.number })}
          <Link className="text-oe-blue-text underline" to={`/design/acceptance?revision=${created.revision_id}`}>{tr(t, 'design.workspace.open_acceptance')}</Link>
        </p>
      )}
      {make.isError && <p role="alert" className="border-b border-border-light bg-semantic-error-bg px-4 py-1.5 text-sm" data-testid="revision-error">{revisionError(t, make.error)}</p>}
    </>
  );

  return (
    <div className="flex h-[calc(100dvh-4rem)] min-h-[480px] flex-col" data-testid="editor-workspace" data-mode={mode}>
      {!payload ? (
        <>{header(null)}<div className="flex flex-1 items-center justify-center text-content-tertiary" aria-busy="true"><Loader2 className="animate-spin" aria-hidden /></div></>
      ) : editorOn ? (
        <>
          {header(null)}
          {banners}
          <EditorCanvas projectId={projectId} payload={payload} locale={i18n.language} mode={mode} rights={rights.data}
            onLink={(l) => { link.current = l; }} onState={setBridge} onSelect={select} onDirty={setDirty}
            onDraft={(d) => setDraftState(d)} selection={selection} draft={draft.data ?? null} />
        </>
      ) : (
        <EngineMode projectId={projectId} header={header} banners={banners} selection={selection} onSelect={select}
          canEdit={mode === 'edit'} notice={bridge?.status === 'refused' || bridge?.status === 'failed'
            ? tr(t, bridge.status === 'refused' ? 'design.workspace.bridge_refused' : 'design.workspace.bridge_failed') : null} />
      )}
    </div>
  );
}

/* ── Today's engine: brief values + live 3D; Create revision = server build ── */

const FORM_KEY = 'ddc-design-workspace-form-open';
/** The parameters panel starts open only where the model still gets most of the width; the person's choice wins. */
function readFormOpen(): boolean {
  try {
    const v = globalThis.localStorage?.getItem(FORM_KEY);
    if (v === '1' || v === '0') return v === '1';
  } catch { /* storage blocked */ }
  return typeof window === 'undefined' || window.innerWidth >= 1600;
}
function writeFormOpen(open: boolean) {
  try { globalThis.localStorage?.setItem(FORM_KEY, open ? '1' : '0'); } catch { /* storage blocked */ }
}

function EngineMode({ projectId, header, banners, selection, onSelect, canEdit, notice }: {
  projectId: string; header: (action: ReactNode) => ReactNode; banners: ReactNode; selection: SelectedElement[];
  onSelect: (s: SelectedElement[]) => void; canEdit: boolean; notice: string | null;
}) {
  const { t } = useTranslation();
  // one editor state for the form, the preview and the button
  const ed = useModelEditor(projectId);
  const ai = useQuery({ queryKey: ['ai-settings'], queryFn: fetchAiSettings, staleTime: 60_000 });
  const revs = useQuery({ queryKey: ['design-revisions', projectId], queryFn: () => fetchRevisions(projectId) });
  // Unchanged values: the real model of the newest in-play revision; the simplified preview only shows changes.
  const tip = chainTip(revs.data ?? []);
  const tipModel = ed.changed === 0 && tip?.bim_model_id ? { ...tip, bim_model_id: tip.bim_model_id } : null;
  const { m } = ed;
  const doc = ed.brief.data ?? null;
  const noDesign = ed.brief.isSuccess && doc === null && revs.isSuccess && !tip?.bim_model_id;
  const [formOpen, setFormOpen] = useState(() => readFormOpen());
  const formToggle = useRef<HTMLButtonElement>(null);
  const moveFocus = useRef(false);
  const setForm = (open: boolean) => { moveFocus.current = true; setFormOpen(open); writeFormOpen(open); };
  useEffect(() => {
    if (moveFocus.current) { moveFocus.current = false; (formOpen ? document.getElementById('form-close') : formToggle.current)?.focus(); }
  }, [formOpen]);
  const action = ed.loading || !canEdit ? null : (
    <span className="flex items-center gap-2">
      <Button size="sm" icon={<GitCommitVertical size={14} aria-hidden />} loading={ed.start.isPending} data-testid="create-revision"
        title={ed.blocked ?? tr(t, 'design.workspace.draft.engine')} data-hint="draft-status"
        disabled={ed.active || ed.blocked !== null || ed.invalid || !ed.view} onClick={() => ed.start.mutate()}>
        {tr(t, 'design.workspace.create_revision')}
      </Button>
      {ed.mine && ACTIVE.includes(ed.mine.status) && (
        <progress className="h-1.5 w-20" max={1} value={ed.mine.progress} aria-label={m('design.model.generate')} />
      )}
      {ed.mine?.status === 'done' && ed.mine.revision_id && (
        <Link className="text-sm text-oe-blue hover:underline" data-testid="saved-link" to={`/design/acceptance?revision=${ed.mine.revision_id}`}>
          {m('design.model.open_acceptance')}
        </Link>
      )}
      {ed.startError && <span role="alert" className="text-xs text-semantic-error">{ed.startError}</span>}
    </span>
  );
  return (
    <>
      {header(action)}
      {banners}
      {notice && <p role="alert" className="border-b border-border-light bg-semantic-warning-bg px-4 py-1.5 text-sm" data-testid="bridge-fallback">{notice}</p>}
      {ed.blocked && canEdit && !ed.loading && <p className="px-4 pt-2 text-xs text-content-secondary" data-testid="blocked-why">{ed.blocked}</p>}
      <div className={`grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-auto p-3 lg:overflow-hidden ${!canEdit
        ? 'lg:grid-cols-[minmax(0,1fr)_minmax(260px,300px)]'
        : formOpen ? 'lg:grid-cols-[280px_minmax(0,1fr)_minmax(260px,300px)]' : 'lg:grid-cols-[40px_minmax(0,1fr)_minmax(260px,300px)]'}`}>
        {canEdit && !formOpen && (
          <button ref={formToggle} type="button" onClick={() => setForm(true)} data-testid="form-open" aria-expanded={false}
            aria-controls="workspace-left" title={tr(t, 'design.workspace.form.open')}
            className="order-2 flex items-center justify-center gap-2 rounded-lg border border-border-light py-2 text-sm text-content-secondary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue lg:order-none lg:flex-col lg:justify-start lg:py-3">
            <PanelLeftOpen size={16} aria-hidden />
            <span className="lg:[writing-mode:vertical-rl]">{tr(t, 'design.workspace.form.title')}</span>
          </button>
        )}
        {canEdit && formOpen && (
          <div id="workspace-left" className="order-2 flex min-w-0 flex-col gap-4 lg:order-none lg:overflow-auto" data-testid="workspace-left">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">{tr(t, 'design.workspace.form.title')}</h2>
              <button id="form-close" type="button" onClick={() => setForm(false)} data-testid="form-close" aria-expanded aria-controls="workspace-left"
                aria-label={tr(t, 'design.workspace.form.close')} title={tr(t, 'design.workspace.form.close')}
                className="rounded p-1 text-content-secondary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue">
                <PanelLeftClose size={16} aria-hidden />
              </button>
            </div>
            <AiBriefBox projectId={projectId} brief={doc} aiReady={aiConfigured(ai.data)} />
            {ed.view?.typology ? <ModelForm ed={ed} compact /> : (
              <p className="text-sm text-content-secondary">
                {tr(t, 'design.workspace.brief_first')}{' '}
                <Link className="text-oe-blue-text underline" to="/design/brief">{tr(t, 'design.brief.title')}</Link>
              </p>
            )}
          </div>
        )}
        <div className="order-1 flex min-h-[60dvh] min-w-0 flex-col lg:order-none lg:min-h-0" data-testid="workspace-canvas">
          {tipModel ? (
            <TipModel projectId={projectId} revision={tipModel} onSelect={(el) => onSelect(el ? [el] : [])} />
          ) : noDesign || ed.modelFailed ? (
            // without a brief nothing can be built: say so instead of a preview that never starts
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center" data-testid="no-design">
              <p className="text-sm text-content-secondary">
                {tr(t, ed.modelFailed ? 'design.workspace.model_failed' : 'design.workspace.no_design')}
              </p>
              {noDesign && (
                <Link className="text-sm font-medium text-oe-blue-text underline" to="/design/brief" data-testid="no-design-brief">
                  {tr(t, 'design.workspace.write_brief')}
                </Link>
              )}
            </div>
          ) : ed.preview.status === 'off' ? (
            <p className="p-3 text-sm text-content-secondary">{tr(t, 'design.workspace.no_engine')}</p>
          ) : (
            <ModelPreview projectId={projectId} state={ed.preview} tall onSelect={(el) => onSelect(el ? [el] : [])} />
          )}
        </div>
        <div className="order-3 min-w-0 lg:order-none lg:overflow-auto"><SelectionPanel projectId={projectId} selection={selection} /></div>
      </div>
    </>
  );
}

/* ── The browser editor, over the bridge ─────────────────────────────── */

function EditorCanvas({ projectId, payload, locale, mode, rights, onLink, onState, onSelect, onDirty, onDraft, selection, draft }: {
  projectId: string; payload: Extract<Payload, { kind: 'editor' }>; locale: string; mode: 'edit' | 'view';
  rights: DesignRights | undefined; onLink: (l: BridgeHost | null) => void;
  onState: (s: BridgeState) => void; onSelect: (s: SelectedElement[]) => void; onDirty: (d: boolean) => void;
  onDraft: (d: DraftState) => void; selection: SelectedElement[]; draft: DraftView | null;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const host = useRef<HTMLDivElement>(null);
  const [aiAsk, setAiAsk] = useState<{ text: string; resolve: (o: AiOutcome) => void } | null>(null);
  const brief = useQuery({ queryKey: ['design-brief', projectId], queryFn: () => fetchBrief(projectId) });
  const ai = useQuery({ queryKey: ['ai-settings'], queryFn: fetchAiSettings, staleTime: 60_000 });
  // what open() reads changes with the device and the rights; the bridge itself stays connected
  const live = useRef({ mode, rights, locale });
  live.current = { mode, rights, locale };

  const open = useCallback(async () => {
    const [project, revisions, doc, aiSettings, mine] = await Promise.all([
      qc.fetchQuery({ queryKey: ['projects', projectId], queryFn: () => projectsApi.get(projectId) }),
      fetchRevisions(projectId), fetchBrief(projectId), fetchAiSettings(), fetchDraft(projectId),
    ]);
    const p = project as { id: string; name: string };
    const { mode: md, rights: r, locale: lc } = live.current;
    return openMessage({
      project: { id: p.id ?? projectId, name: p.name ?? '' }, brief: doc, revisions, draft: mine,
      locale: lc, theme: theme(), mode: md, canEdit: !!r?.can_edit, canAccept: !!r?.can_accept, ai: aiConfigured(aiSettings),
    });
  }, [projectId, qc]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let stopped = false;
    void (async () => {
      try {
        let port;
        if (payload.entryUrl.endsWith('.html')) {
          const frame = document.createElement('iframe');
          frame.setAttribute('sandbox', 'allow-scripts');
          frame.className = 'h-full w-full border-0';
          frame.title = 'design-editor';
          port = framePort(frame);
          frame.src = payload.entryUrl;
          el.appendChild(frame);
        } else {
          const mod = (await import(/* @vite-ignore */ payload.entryUrl)) as EditorModule;
          port = await modulePort(mod, el);
        }
        if (stopped) { port.close(); return; }
        onLink(connectBridge(port, {
          open,
          save: async (bytes) => {
            onDraft({ status: 'saving' });
            try {
              const d = await saveDraft(projectId, bytes);
              qc.setQueryData(['design-draft', projectId], d);
              onDraft({ status: 'saved', at: d.updated_at });
              return { revision_id: d.revision_id, updated_at: d.updated_at, element_count: d.element_count };
            } catch (e) {
              onDraft({ status: 'failed', reason: bridgeError(e).message });
              throw e;
            }
          },
          ai: (text) => new Promise<AiOutcome>((resolve) => setAiAsk({ text, resolve })).then((o) => ({
            status: o.status, ...(o.brief_version ? { brief_version: o.brief_version } : {}),
            ...(o.brief ? { brief: o.brief as unknown as Record<string, unknown> } : {}),
            ...(o.confirmed ? { confirmed: o.confirmed } : {}),
          })),
          readFile: async (path) => {
            if (path === DRAFT_FILE) return readDraftPackage(projectId);
            const tip = chainTip(await fetchRevisions(projectId));
            if (!tip) throw new Error('no revision');
            return readRevisionFile(tip.revision_id, path);
          },
          select: onSelect,
          dirty: onDirty,
          state: onState,
        }));
      } catch (e) {
        onState({ status: 'failed', reason: e instanceof Error ? e.message : String(e) });
      }
    })();
    return () => {
      stopped = true;
      onLink(null);
      el.replaceChildren();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one bridge per bundle and project
  }, [payload.entryUrl, projectId]);

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-auto p-3 lg:grid-cols-[minmax(0,1fr)_320px] lg:overflow-hidden">
      <div className="relative min-h-[50dvh] min-w-0 overflow-hidden rounded-lg border border-border-light lg:min-h-0">
        <div ref={host} className="h-full w-full" data-testid="editor-host" />
        {aiAsk && (
          <div className="absolute inset-y-0 start-0 w-[min(340px,100%)] overflow-auto border-e border-border-light bg-surface-primary p-3 shadow-lg" role="dialog"
            aria-label={tr(t, 'design.workspace.ai.title')} aria-modal="false">
            <AiBriefBox projectId={projectId} brief={brief.data ?? null} aiReady={aiConfigured(ai.data)} initialText={aiAsk.text}
              onDone={(o) => { aiAsk.resolve(o); setAiAsk(null); }} />
          </div>
        )}
      </div>
      <div className="min-w-0 lg:overflow-auto"><SelectionPanel projectId={projectId} selection={selection} draft={draft} /></div>
    </div>
  );
}
