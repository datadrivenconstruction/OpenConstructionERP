// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<PipelinesPage>` — full-bleed 3-zone shell for the Pipeline Builder.
 *
 * Layout (03_ux_visual §1), mirroring `EACBlockEditorPage`'s
 * `h-[calc(100vh-var(--oe-header-height,56px))]`:
 *
 *   ┌──────────┬──────────────────────────────────┬───────────┐
 *   │ Palette  │  Toolbar                          │ Inspector │
 *   │ 260px    ├──────────────────────────────────┤ 320px     │
 *   │ collap.  │  Canvas (xyflow)                  │ collap.   │
 *   │          ├──────────────────────────────────┴───────────┤
 *   │          │  Run dock (28px idle → 280px)                 │
 *   └──────────┴──────────────────────────────────────────────┘
 *
 * Server state via React Query (`api.ts`); local graph state via the Zustand
 * store. Live run = polling `GET /runs/{run_id}` (no websocket).
 * Empty canvas → `EmptyState`. Onboarding via the shared `OnboardingTour`.
 */
import { FolderOpen, Info, LayoutTemplate, Workflow } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';

import { BetaBanner, EmptyState, OnboardingTour } from '@/shared/ui';
import type { TourStep } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import type { PipelineGraph } from './api';
import { PipelineCanvas } from './canvas/PipelineCanvas';
import { PipelineToolbar } from './canvas/PipelineToolbar';
import { InspectorPanel } from './components/InspectorPanel';
import { NodePalette } from './components/NodePalette';
import { PipelineLibraryModal } from './components/PipelineLibraryModal';
import { RunDock } from './components/RunDock';
import type { PipelineTemplate } from './templates';
import {
  isTerminalRunStatus,
  pipelineKeys,
  requiredInputIds,
  useCreatePipeline,
  useNodeTypes,
  usePipeline,
  usePipelineRun,
  usePipelineRuns,
  useRunPipeline,
  useUpdatePipeline,
} from './api';
import { usePipelineStore } from './usePipelineStore';

export function PipelinesPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectId = searchParams.get('project');
  const pipelineIdParam = searchParams.get('id') ?? undefined;
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [paletteCollapsed, setPaletteCollapsed] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [dockExpanded, setDockExpanded] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | undefined>(undefined);
  const [loadToken, setLoadToken] = useState(0);
  const [explainSummary, setExplainSummary] = useState<string | null>(null);
  // The graph currently being hydrated onto the canvas. Unifies two sources -
  // a fetched saved pipeline and a chosen starter template - so both flow
  // through the canvas's single `loadGraph`+`loadToken` hydration path.
  const [graphToHydrate, setGraphToHydrate] = useState<PipelineGraph | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [libraryTab, setLibraryTab] = useState<'templates' | 'saved'>('templates');
  const fitViewRef = useRef<(() => void) | null>(null);

  // ── Server state ────────────────────────────────────────────────────────
  const nodeTypesQuery = useNodeTypes();
  const pipelineQuery = usePipeline(pipelineIdParam);
  const runsQuery = usePipelineRuns(
    usePipelineStore((s) => s.meta.id) ?? pipelineIdParam,
  );
  const runDetailQuery = usePipelineRun(activeRunId);

  const createMut = useCreatePipeline();
  const savedId = usePipelineStore((s) => s.meta.id);
  const updateMut = useUpdatePipeline(savedId ?? pipelineIdParam ?? '');
  const runMut = useRunPipeline(savedId ?? pipelineIdParam ?? '');

  const nodeTypes = useMemo(
    () => nodeTypesQuery.data ?? [],
    [nodeTypesQuery.data],
  );

  // ── Store wiring ────────────────────────────────────────────────────────
  const nodeCount = usePipelineStore((s) => s.nodes.length);
  const edgeCount = usePipelineStore((s) => s.edges.length);
  const dirty = usePipelineStore((s) => s.dirty);
  const loadGraphMeta = usePipelineStore((s) => s.loadGraph);
  const markSaved = usePipelineStore((s) => s.markSaved);
  const patchMeta = usePipelineStore((s) => s.patchMeta);
  const startRun = usePipelineStore((s) => s.startRun);
  const applyRunDetail = usePipelineStore((s) => s.applyRunDetail);
  const clearRun = usePipelineStore((s) => s.clearRun);
  const toGraphJSON = usePipelineStore((s) => s.toGraphJSON);
  const clearSelection = usePipelineStore((s) => s.clearSelection);
  const reset = usePipelineStore((s) => s.reset);

  // Reset the store on unmount so a fresh visit starts clean.
  useEffect(() => () => reset(), [reset]);

  // Warn before closing / reloading the tab while there are unsaved edits, so
  // a stray Ctrl+W doesn't silently drop a half-built pipeline. The browser
  // shows its own generic prompt; returnValue must be set for it to fire.
  useEffect(() => {
    if (!dirty) return undefined;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  // The explain summary is a point-in-time snapshot of the graph, so drop it
  // whenever the graph changes — a stale summary would misrepresent the canvas.
  useEffect(() => {
    setExplainSummary(null);
  }, [nodeCount, edgeCount, loadToken]);

  // Set the project binding once from the URL.
  useEffect(() => {
    if (projectId) patchMeta({ projectId });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Hydrate a loaded pipeline (canvas does the actual graph rebuild).
  useEffect(() => {
    if (!pipelineQuery.data) return;
    const p = pipelineQuery.data;
    loadGraphMeta(p.graph, {
      id: p.id,
      name: p.name ?? '',
      description: p.description ?? '',
      projectId: p.project_id ?? projectId ?? null,
      isPublished: Boolean(p.is_published),
    });
    setGraphToHydrate(p.graph ?? null);
    setLoadToken((n) => n + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineQuery.data]);

  // Project polled run detail onto the canvas/dock; stop when terminal.
  useEffect(() => {
    const d = runDetailQuery.data;
    if (!d) return;
    applyRunDetail({
      status: d.status,
      progress_percent: d.progress_percent,
      error: d.error,
      nodes: d.nodes,
    });
    if (isTerminalRunStatus(d.status)) {
      setActiveRunId(undefined);
      void runsQuery.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runDetailQuery.data]);

  // Safety net: if a run never reaches a terminal status, log a single warning
  // after 5 minutes so a stuck poller is visible in the console rather than
  // silently churning forever. Resets whenever the active run changes.
  useEffect(() => {
    if (!activeRunId) return undefined;
    const timer = window.setTimeout(
      () => {
        // eslint-disable-next-line no-console
        console.warn(
          `[pipelines] run ${activeRunId} has been in-flight for over 5 minutes; the backend may have stopped reporting progress.`,
        );
      },
      5 * 60 * 1000,
    );
    return () => window.clearTimeout(timer);
  }, [activeRunId]);

  // ── Authoring-time issues (lightweight linter) ─────────────────────────
  const issueCount = useMemo(() => {
    // A node is flagged only when one of its *required* input ports has no
    // incoming edge. Optional inputs (e.g. a port the step can also read from
    // its params) are ignored, so we don't manufacture false issues. The
    // required-port set comes from the node-type catalogue (see
    // requiredInputIds); ports map to incoming edges by their targetHandle.
    const edges = usePipelineStore.getState().edges;
    const nodes = usePipelineStore.getState().nodes;
    const defByType = new Map(nodeTypes.map((d) => [d.type, d]));
    // Nodes touched by at least one edge - used to spot "islands" (a step with
    // no wire at all), which silently never run, the classic "not all the logic
    // works" trap when a graph is half-wired.
    const connected = new Set<string>();
    for (const e of edges) {
      connected.add(e.source);
      connected.add(e.target);
    }
    let count = 0;
    for (const n of nodes) {
      // An island in a multi-node graph is always an issue, regardless of its
      // port requirements: nothing feeds it and it feeds nothing.
      if (nodes.length > 1 && !connected.has(n.id)) {
        count += 1;
        continue;
      }
      const required = requiredInputIds(defByType.get(n.type));
      if (required.length === 0) continue;
      const incoming = edges.filter((e) => e.target === n.id);
      const wired = new Set(incoming.map((e) => e.targetHandle));
      // If the catalogue can't resolve specific port ids on this node, fall
      // back to "any incoming edge satisfies it" so an unknown type isn't
      // permanently red.
      const portIds = new Set(n.inputs.map((p) => p.id));
      const requiresKnownPorts = required.some((id) => portIds.has(id));
      const unmet = requiresKnownPorts
        ? required.some((id) => portIds.has(id) && !wired.has(id))
        : incoming.length === 0;
      if (unmet) count += 1;
    }
    return count;
    // recompute when the node OR edge set changes (an unconnected
    // required input is an edge-level fact, so edgeCount must be a dep)
  }, [nodeCount, edgeCount, loadToken, nodeTypes, runDetailQuery.dataUpdatedAt]);

  // ── Actions ─────────────────────────────────────────────────────────────
  const handleSave = useCallback(async () => {
    const meta = usePipelineStore.getState().meta;
    const graph = toGraphJSON();
    const name =
      meta.name.trim() ||
      t('pipeline.untitled', { defaultValue: 'Untitled pipeline' });
    try {
      if (meta.id) {
        await updateMut.mutateAsync({
          name,
          description: meta.description,
          graph,
          is_published: meta.isPublished,
        });
        // Clear the dirty flag (and keep the id) so the unsaved-changes
        // warning / badge resolves after a successful update too.
        markSaved(meta.id);
      } else {
        const created = await createMut.mutateAsync({
          name,
          description: meta.description || undefined,
          project_id: meta.projectId,
          graph,
        });
        if (created?.id) markSaved(created.id);
      }
      addToast({
        type: 'success',
        title: t('pipeline.toast.saved', { defaultValue: 'Pipeline saved' }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('pipeline.toast.save_failed', {
          defaultValue: 'Could not save pipeline',
        }),
        message: getErrorMessage(err),
      });
    }
  }, [addToast, createMut, markSaved, t, toGraphJSON, updateMut]);

  const handleRun = useCallback(async () => {
    const meta = usePipelineStore.getState().meta;
    let id = meta.id;
    if (!id) {
      // Auto-save first so there's something to run.
      try {
        const created = await createMut.mutateAsync({
          name:
            meta.name.trim() ||
            t('pipeline.untitled', { defaultValue: 'Untitled pipeline' }),
          description: meta.description || undefined,
          project_id: meta.projectId,
          graph: toGraphJSON(),
        });
        id = created?.id ?? null;
        if (id) markSaved(id);
      } catch (err) {
        addToast({
          type: 'error',
          title: t('pipeline.toast.run_failed', {
            defaultValue: 'Could not start the run',
          }),
          message: getErrorMessage(err),
        });
        return;
      }
    }
    if (!id) return;
    try {
      const res = await runMut.mutateAsync();
      if (res?.run_id) {
        startRun(res.run_id);
        setActiveRunId(res.run_id);
        setDockExpanded(true);
      }
    } catch (err) {
      addToast({
        type: 'error',
        title: t('pipeline.toast.run_failed', {
          defaultValue: 'Could not start the run',
        }),
        message: getErrorMessage(err),
      });
    }
  }, [addToast, createMut, markSaved, runMut, startRun, t, toGraphJSON]);

  const handleStop = useCallback(() => {
    // Phase-1: no cancel endpoint in the pinned contract — just detach the
    // poller and clear the local overlay (run continues server-side).
    const runId = activeRunId;
    setActiveRunId(undefined);
    clearRun();
    // Cancel + drop the cached run-detail query so polling stops immediately
    // instead of riding out the current refetch interval.
    if (runId) {
      void queryClient.cancelQueries({ queryKey: pipelineKeys.run(runId) });
      queryClient.removeQueries({ queryKey: pipelineKeys.run(runId) });
    }
  }, [activeRunId, clearRun, queryClient]);

  const handleExplain = useCallback(() => {
    // Deterministic plain-language summary built from the current graph JSON.
    // No LLM / network — describes the steps and how they are wired together.
    const graph = toGraphJSON();
    const meta = usePipelineStore.getState().meta;

    const labelFor = (n: { type: string; label?: string }): string => {
      if (n.label && n.label.trim()) return n.label.trim();
      const def = nodeTypes.find((d) => d.type === n.type);
      return def?.label?.trim() || n.type;
    };
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const nameFor = (id: string): string => {
      const n = byId.get(id);
      return n ? labelFor(n) : id;
    };

    const lines: string[] = [];
    const title =
      meta.name.trim() ||
      t('pipeline.untitled', { defaultValue: 'Untitled pipeline' });

    if (graph.nodes.length === 0) {
      setExplainSummary(
        t('pipeline.explain.empty', {
          defaultValue:
            'This pipeline is empty. Drag a few steps from the palette and connect them, then ask again.',
        }),
      );
      clearSelection();
      setInspectorCollapsed(false);
      return;
    }

    lines.push(
      t('pipeline.explain.heading', {
        defaultValue: '"{{name}}" has {{nodes}} step(s) and {{edges}} connection(s).',
        name: title,
        nodes: graph.nodes.length,
        edges: graph.edges.length,
      }),
    );
    lines.push('');

    lines.push(t('pipeline.explain.steps_label', { defaultValue: 'Steps:' }));
    for (const n of graph.nodes) {
      lines.push(
        t('pipeline.explain.step_line', {
          defaultValue: '• {{label}} ({{type}})',
          label: labelFor(n),
          type: n.type,
        }),
      );
    }

    if (graph.edges.length > 0) {
      lines.push('');
      lines.push(t('pipeline.explain.flow_label', { defaultValue: 'Data flow:' }));
      for (const e of graph.edges) {
        lines.push(
          t('pipeline.explain.flow_line', {
            defaultValue: '• {{from}} → {{to}}',
            from: nameFor(e.source),
            to: nameFor(e.target),
          }),
        );
      }
    }

    // Surface authoring issues so the summary is honest about gaps.
    if (issueCount > 0) {
      lines.push('');
      lines.push(
        t('pipeline.explain.issues_line', {
          defaultValue:
            '{{count}} step(s) still need connecting before this can run.',
          count: issueCount,
        }),
      );
    }

    setExplainSummary(lines.join('\n'));
    clearSelection();
    setInspectorCollapsed(false);
  }, [clearSelection, issueCount, nodeTypes, t, toGraphJSON]);

  // Load a starter template as a fresh, unsaved draft (id cleared) so the first
  // Save creates a new pipeline rather than overwriting whatever was open.
  const applyTemplate = useCallback(
    (tpl: PipelineTemplate) => {
      loadGraphMeta(tpl.graph, {
        id: null,
        name: tpl.name,
        description: tpl.description,
        projectId: projectId ?? null,
        isPublished: false,
      });
      setGraphToHydrate(tpl.graph);
      setLoadToken((n) => n + 1);
      // Drop any ?id= so the URL no longer points at a saved pipeline.
      if (pipelineIdParam) {
        const next = new URLSearchParams(searchParams);
        next.delete('id');
        setSearchParams(next, { replace: true });
      }
      addToast({
        type: 'success',
        title: t('pipeline.toast.template_loaded', {
          defaultValue: 'Template loaded - review, then Save or Run',
        }),
      });
    },
    [
      addToast,
      loadGraphMeta,
      pipelineIdParam,
      projectId,
      searchParams,
      setSearchParams,
      t,
    ],
  );

  // Reopen a saved workflow: point the URL at it so the existing fetch effect
  // hydrates the graph + meta (id set), turning Save into an update.
  const openSaved = useCallback(
    (id: string) => {
      const next = new URLSearchParams(searchParams);
      next.set('id', id);
      setSearchParams(next, { replace: false });
    },
    [searchParams, setSearchParams],
  );

  const openLibrary = useCallback((tab: 'templates' | 'saved') => {
    setLibraryTab(tab);
    setLibraryOpen(true);
  }, []);

  // The shared OnboardingTour resolves `title`/`description` via its internal
  // STEP_DEFAULTS map and falls back to the raw value when a key is unknown —
  // so we pass already-translated strings (we may not edit locale files).
  const tourSteps: TourStep[] = useMemo(
    () => [
      {
        target: '[data-tour="pipeline-palette"]',
        title: t('pipeline.tour.palette_title', {
          defaultValue: 'Pick your steps',
        }),
        description: t('pipeline.tour.palette_body', {
          defaultValue:
            'Drag a step from here onto the canvas, or just click it to drop it in the middle.',
        }),
        position: 'right',
      },
      {
        target: '[data-tour="pipeline-canvas"]',
        title: t('pipeline.tour.canvas_title', {
          defaultValue: 'Connect the steps',
        }),
        description: t('pipeline.tour.canvas_body', {
          defaultValue:
            'Drag from one step output dot to the next step input. Colours show the data type.',
        }),
        position: 'bottom',
      },
      {
        target: '[data-testid="pipeline-run"]',
        title: t('pipeline.tour.run_title', { defaultValue: 'Run it' }),
        description: t('pipeline.tour.run_body', {
          defaultValue:
            'Press Run to execute the pipeline and watch each step light up live.',
        }),
        position: 'bottom',
      },
    ],
    [t],
  );

  const isRunning =
    Boolean(activeRunId) &&
    !isTerminalRunStatus(runDetailQuery.data?.status);
  const busy =
    createMut.isPending || updateMut.isPending || runMut.isPending;

  return (
    <div
      data-testid="pipelines-page"
      data-tour="pipelines"
      className="flex flex-col -mx-4 -mt-6 -mb-4 h-[calc(100vh-var(--oe-header-height,56px))] overflow-hidden bg-surface-primary sm:-mx-7"
    >
      {/* BETA notice stacks on TOP of the editor. It must not be a sibling of
          the palette / canvas / inspector row: as a row child it collapsed into
          a sliver column and broke the 3-zone layout (and the page also skipped
          the full-bleed -mx negation, so it was inset by the app padding). The
          row now lives in its own flex child below and the root is full-bleed. */}
      <BetaBanner moduleKey="pipelines" className="mx-3 mt-3 shrink-0" />
      <div className="flex min-h-0 flex-1 overflow-hidden">
      <NodePalette
        nodeTypes={nodeTypes}
        loading={nodeTypesQuery.isLoading}
        collapsed={paletteCollapsed}
        onToggleCollapsed={() => setPaletteCollapsed((v) => !v)}
      />

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <PipelineToolbar
          onFitView={() => fitViewRef.current?.()}
          onSave={handleSave}
          onRun={handleRun}
          onStop={handleStop}
          onExplain={handleExplain}
          onOpenLibrary={() => openLibrary('saved')}
          busy={busy}
          running={isRunning}
          issueCount={issueCount}
          dirty={dirty}
        />
        <div
          className="relative min-h-0 flex-1"
          data-tour="pipeline-canvas"
        >
          {nodeCount === 0 && !pipelineQuery.isLoading ? (
            // pointer-events-none lets a first drag/drop fall through to the
            // canvas underneath so "drag a step onto the canvas" works even
            // while this guidance overlay is showing.
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center overflow-y-auto bg-surface-primary">
              <EmptyState
                icon={<Workflow size={24} aria-hidden="true" />}
                title={t('pipeline.empty.title', {
                  defaultValue: 'Build your first automation',
                })}
                description={t('pipeline.empty.description', {
                  defaultValue:
                    'A pipeline is a few steps wired together. Follow these steps to build your first one.',
                })}
                action={
                  // The empty-state overlay is pointer-events-none so a first
                  // drag falls through to the canvas; re-enable events on the
                  // card itself so its buttons remain clickable.
                  <div className="pointer-events-auto w-full max-w-md rounded-xl border border-border bg-surface-secondary/60 p-4 text-start">
                    {/* Fast path: start from a ready-made automation instead of
                        building from scratch, or reopen a saved workflow. */}
                    <div className="mb-4 flex flex-col gap-2 sm:flex-row">
                      <button
                        type="button"
                        data-testid="pipeline-browse-templates"
                        onClick={() => openLibrary('templates')}
                        className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-oe-blue bg-oe-blue px-3 py-2 text-sm font-medium text-white hover:bg-oe-blue/90"
                      >
                        <LayoutTemplate size={15} aria-hidden="true" />
                        {t('pipeline.empty.browse_templates', {
                          defaultValue: 'Browse templates',
                        })}
                      </button>
                      <button
                        type="button"
                        onClick={() => openLibrary('saved')}
                        className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
                      >
                        <FolderOpen size={15} aria-hidden="true" />
                        {t('pipeline.empty.open_saved', {
                          defaultValue: 'Open saved',
                        })}
                      </button>
                    </div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
                      {t('pipeline.empty.or_build', {
                        defaultValue: 'Or build your own',
                      })}
                    </p>
                    <ol className="space-y-2.5">
                      {[
                        t('pipeline.empty.step_trigger', {
                          defaultValue:
                            'Drag a trigger from the palette on the left to start the flow.',
                        }),
                        t('pipeline.empty.step_add', {
                          defaultValue:
                            'Add more steps: get data, transform, validate, then an action.',
                        }),
                        t('pipeline.empty.step_connect', {
                          defaultValue:
                            "Connect them left to right: drag from a step's Out dot to the next step's In dot.",
                        }),
                        t('pipeline.empty.step_run', {
                          defaultValue:
                            'Press Run and watch each step finish live.',
                        }),
                      ].map((step, i) => (
                        <li key={i} className="flex items-start gap-3">
                          <span className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-2xs font-semibold text-oe-blue">
                            {i + 1}
                          </span>
                          <span className="text-sm text-content-secondary">
                            {step}
                          </span>
                        </li>
                      ))}
                    </ol>
                    <p className="mt-3 flex items-start gap-1.5 border-t border-border pt-3 text-xs text-content-tertiary">
                      <Info
                        size={13}
                        aria-hidden="true"
                        className="mt-px shrink-0"
                      />
                      {t('pipeline.empty.tip', {
                        defaultValue:
                          'Ports only connect when their data types match. Hover a dot to see what it carries.',
                      })}
                    </p>
                  </div>
                }
              />
            </div>
          ) : null}
          <PipelineCanvas
            nodeTypes={nodeTypes}
            loadGraph={graphToHydrate}
            loadToken={loadToken}
            onFitViewReady={(fit) => {
              fitViewRef.current = fit;
            }}
            testId="pipeline-canvas"
          />
        </div>
        <RunDock
          runs={runsQuery.data ?? []}
          runsLoading={runsQuery.isLoading}
          expanded={dockExpanded}
          onToggleExpanded={() => setDockExpanded((v) => !v)}
        />
      </main>

      <InspectorPanel
        nodeTypes={nodeTypes}
        collapsed={inspectorCollapsed}
        onToggleCollapsed={() => setInspectorCollapsed((v) => !v)}
        summary={explainSummary}
      />
      </div>

      <PipelineLibraryModal
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        projectId={projectId}
        initialTab={libraryTab}
        onPickTemplate={applyTemplate}
        onOpenSaved={openSaved}
      />

      <OnboardingTour steps={tourSteps} />
    </div>
  );
}

export default PipelinesPage;
