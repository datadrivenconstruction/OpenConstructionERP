// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The platform map canvas: modules in workflow-stage columns (layout.ts) under
// stage headers, coloured by their sidebar family, edges as smooth curves whose
// width grows with the project's live counts. It opens fitted to its content and
// never below the zoom at which node labels stay 12 px or larger.
// Data moves along active edges as small particles; with reduced motion the
// particles are replaced by a static arrowhead. Hovering a module lights its
// whole upstream and downstream chain; clicking it zooms to its path.

import { memo, useCallback, useEffect, useMemo, type CSSProperties } from 'react';
import {
  ReactFlow,
  Background,
  BaseEdge,
  Controls,
  Handle,
  Position,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import { useThemeStore } from '@/stores/useThemeStore';
import '@xyflow/react/dist/style.css';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';

import { formatNumber } from '@/shared/lib/formatters';

import type { EdgeOut, Importance, MapModule } from './api';
import { chainOf, layeredLayout } from './layout';
import { STAGES, moduleMeta } from './moduleMeta';
import { moduleLabel } from './flowModel';
import { useReducedMotion } from './motion';

const STAGE_DEFAULTS: Record<string, string> = {
  capture: 'Takeoff',
  estimate: 'Estimating',
  tender: 'Procurement',
  contract: 'Commercial',
  execution: 'Site',
  finance: 'Finance',
  platform: 'Platform',
};

export type ModuleStatus = 'with_data' | 'empty' | 'not_installed';

export interface CanvasModule {
  module: MapModule;
  status: ModuleStatus;
  critical: boolean;
}

type ModuleNodeData = {
  label: string;
  family: string;
  icon: LucideIcon | null;
  tone: string;
  count: number | null;
  status: ModuleStatus;
  focus: boolean;
  lit: boolean;
  dim: boolean;
  critical: boolean;
  declared: boolean;
};

type FlowEdgeData = {
  title: string;
  /** Touches the platform band (contacts, documents, RFIs): supporting links drawn quietly. */
  band: boolean;
  tone: string;
  count: number | null;
  active: boolean;
  importance: Importance;
  lit: boolean;
  dim: boolean;
  reduce: boolean;
  stale: boolean;
};

const NODE_W = 160;
const NODE_H = 64;
const COL_GAP = 36;
const ROW_GAP = 14;
const HEADER_H = 40;
// Node names are 14 px; below this zoom they would drop under 12 px on screen.
const MIN_READABLE_ZOOM = 0.86;

type StageNodeData = { label: string; n: number; width: number };

const StageNode = memo(function StageNode({ data }: NodeProps<Node<StageNodeData>>) {
  return (
    <div
      className="flex items-baseline justify-between border-b border-border-light pb-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary"
      style={{ width: data.width }}
    >
      <span className="truncate">{data.label}</span>
      <span className="tabular-nums font-medium">{data.n}</span>
    </div>
  );
});

const ModuleNode = memo(function ModuleNode({ data }: NodeProps<Node<ModuleNodeData>>) {
  const { t } = useTranslation();
  const Icon = data.icon;
  return (
    <div
      className={clsx(
        'flex flex-col justify-between rounded-xl border bg-surface-primary px-2.5 py-2 transition-[opacity,box-shadow] duration-200',
        data.focus ? 'border-oe-blue shadow-md ring-2 ring-oe-blue/30' : data.lit ? 'border-oe-blue/60 shadow-sm' : 'border-border-light shadow-xs',
        data.dim && 'opacity-30',
        data.status === 'not_installed' && 'border-dashed',
      )}
      style={{ width: NODE_W, height: NODE_H }}
      title={`${data.label} · ${data.family}`}
      data-testid="dp-map-node"
    >
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
      <div className="flex min-w-0 items-start gap-2">
        <span
          className="mt-px flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
          style={{ background: `color-mix(in srgb, ${data.tone} 16%, transparent)`, color: data.tone }}
          aria-hidden
        >
          {Icon ? <Icon size={14} strokeWidth={2} /> : <span className="h-2 w-2 rounded-full" style={{ background: data.tone }} />}
        </span>
        <span className="line-clamp-2 min-w-0 flex-1 break-words text-sm font-medium leading-tight text-content-primary">{data.label}</span>
        {data.critical && (
          <span
            className="mt-1 h-2 w-2 shrink-0 rounded-full bg-semantic-error"
            title={t('data_paths.health_missing_short', { defaultValue: 'A critical input is missing' })}
          />
        )}
      </div>
      <div className="flex items-baseline justify-end gap-1">
        {data.status === 'not_installed' ? (
          <span className="text-xs text-content-tertiary">{t('data_paths.state_not_installed', { defaultValue: 'Not installed' })}</span>
        ) : data.count !== null ? (
          <span className={clsx('text-base font-semibold leading-none tabular-nums', data.count ? 'text-content-primary' : 'text-content-quaternary')}>
            {formatNumber(data.count)}
          </span>
        ) : null}
      </div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
    </div>
  );
});

/** Smooth curve; a link that runs backwards loops under its nodes instead of through them. */
function curve(sx: number, sy: number, tx: number, ty: number): [string, number, number] {
  if (tx > sx + 8) {
    const c = Math.max(36, (tx - sx) * 0.5);
    return [`M ${sx} ${sy} C ${sx + c} ${sy}, ${tx - c} ${ty}, ${tx} ${ty}`, (sx + tx) / 2, (sy + ty) / 2];
  }
  const drop = Math.max(sy, ty) + NODE_H * 0.75;
  return [`M ${sx} ${sy} C ${sx + 28} ${sy}, ${sx + 28} ${drop}, ${(sx + tx) / 2} ${drop} S ${tx - 28} ${ty}, ${tx} ${ty}`, (sx + tx) / 2, drop];
}

export function edgeWidth(count: number | null, importance: Importance): number {
  const base = importance === 'critical' ? 1.75 : importance === 'high' ? 1.4 : 1.1;
  return base + Math.min(4.5, Math.log2(1 + Math.max(0, count ?? 0)) * 0.7);
}

function FlowEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<Edge<FlowEdgeData>>) {
  const [path] = curve(sourceX, sourceY, targetX, targetY);
  const d = data as FlowEdgeData;
  // Links that run against the workflow stay quiet until their chain is lit.
  const quiet = (targetX <= sourceX + 8 || d.band) && !d.lit;
  const width = quiet ? 1 : edgeWidth(d.count, d.importance);
  const stroke = d.stale ? 'var(--oe-warning)' : d.lit ? 'var(--oe-blue)' : d.tone;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke,
          strokeWidth: width + (d.lit ? 0.75 : 0),
          strokeLinecap: 'round',
          opacity: d.dim ? 0.12 : d.lit ? 0.95 : quiet ? 0.28 : 0.5,
          strokeDasharray: d.stale ? '6 4' : quiet ? '3 4' : undefined,
          transition: 'opacity 200ms, stroke 200ms',
        }}
        markerEnd={d.reduce || !d.active ? 'url(#dp-arrow)' : undefined}
      />
      <path d={path} fill="none" stroke="transparent" strokeWidth={12}>
        <title>{d.title}</title>
      </path>
      {d.active && !d.reduce && !d.dim && (
        <circle r={d.lit ? 3 : 2.2} fill="var(--oe-blue)" opacity={0.75}>
          <animateMotion dur={`${d.importance === 'critical' ? 2.2 : 3.2}s`} repeatCount="indefinite" path={path} />
        </circle>
      )}
    </>
  );
}

const nodeTypes = { module: ModuleNode, stage: StageNode };
const edgeTypes = { flow: FlowEdge };

export interface PlatformMapCanvasProps {
  modules: CanvasModule[];
  edges: EdgeOut[];
  focus: string | null;
  /** Modules to show; null shows every module. */
  visible: Set<string> | null;
  /** Externally lit modules (a party hovered in the honeycomb). */
  lit: Set<string> | null;
  hovered: string | null;
  onHover: (module: string | null) => void;
  onSelect: (module: string) => void;
  showTechnical: boolean;
  height?: number;
}

function Canvas({ modules, edges, focus, visible, lit, hovered, onHover, onSelect, showTechnical, height }: PlatformMapCanvasProps) {
  const { t } = useTranslation();
  const reduce = useReducedMotion();
  const { fitView } = useReactFlow();

  const shownEdges = useMemo(
    () => edges.filter((e) => (showTechnical || e.kind === 'declared') && e.source !== e.target),
    [edges, showTechnical],
  );
  // The default map is the declared data network; modules with no declared link
  // join only through a filter, a search or "Show all links".
  const connected = useMemo(() => {
    const s = new Set<string>();
    for (const e of shownEdges) {
      s.add(e.source);
      s.add(e.target);
    }
    return s;
  }, [shownEdges]);
  const colorMode = useThemeStore((s) => s.resolved);
  const shown = useMemo(
    () =>
      modules.filter((m) => {
        const name = m.module.name;
        if (visible) return visible.has(name);
        return showTechnical || connected.has(name) || name === focus;
      }),
    [modules, visible, showTechnical, connected, focus],
  );
  const ids = useMemo(() => new Set(shown.map((m) => m.module.name)), [shown]);
  const inView = useMemo(() => shownEdges.filter((e) => ids.has(e.source) && ids.has(e.target)), [shownEdges, ids]);

  const positions = useMemo(
    () =>
      layeredLayout(
        shown.map((m) => {
          const meta = moduleMeta(m.module.name);
          return { id: m.module.name, stage: meta.stage, sortKey: `${meta.familyId}:${m.module.name}` };
        }),
        inView,
        { nodeWidth: NODE_W, nodeHeight: NODE_H, columnGap: COL_GAP, rowGap: ROW_GAP, bandColumns: 6 },
      ),
    [shown, inView],
  );

  // Stage headers over every column that has modules, and one over the platform band.
  const stageNodes: Node<StageNodeData>[] = useMemo(() => {
    const byStage = new Map<number, { x: number; top: number; n: number }>();
    for (const m of shown) {
      const pos = positions.get(m.module.name);
      if (!pos) continue;
      const stage = moduleMeta(m.module.name).stage;
      const bandStage = STAGES.indexOf('platform');
      const key = stage === bandStage ? -1 : stage;
      const hit = byStage.get(key);
      if (!hit) byStage.set(key, { x: key === -1 ? 0 : pos.x, top: pos.y, n: 1 });
      else {
        hit.top = Math.min(hit.top, pos.y);
        hit.n += 1;
      }
    }
    const mainTop = Math.min(...[...byStage.entries()].filter(([k]) => k !== -1).map(([, v]) => v.top), 0);
    return [...byStage.entries()].map(([key, v]) => {
      const stage = key === -1 ? 'platform' : (STAGES[key] ?? 'platform');
      return {
        id: `stage:${stage}`,
        type: 'stage',
        position: { x: v.x, y: (key === -1 ? v.top : mainTop) - HEADER_H },
        data: { label: String(t(`data_paths.stage_${stage}`, { defaultValue: STAGE_DEFAULTS[stage] })), n: v.n, width: NODE_W },
        draggable: false,
        selectable: false,
        connectable: false,
        focusable: false,
      };
    });
  }, [shown, positions, t]);

  const contentHeight = useMemo(() => {
    let top = 0;
    let bottom = 0;
    for (const pos of positions.values()) {
      top = Math.min(top, pos.y);
      bottom = Math.max(bottom, pos.y + NODE_H);
    }
    return bottom - top + HEADER_H;
  }, [positions]);

  const chain = useMemo(() => {
    const anchor = hovered ?? null;
    if (anchor) {
      const { up, down } = chainOf(anchor, inView);
      return new Set([anchor, ...up, ...down]);
    }
    return lit;
  }, [hovered, inView, lit]);

  const nodes: Node<ModuleNodeData>[] = useMemo(
    () =>
      shown.map((m) => {
        const meta = moduleMeta(m.module.name);
        const family = meta.familyLabelKey
          ? String(t(meta.familyLabelKey, { defaultValue: meta.familyDefaultLabel ?? '' }))
          : String(t('data_paths.family_platform', { defaultValue: 'Platform' }));
        return {
          id: m.module.name,
          type: 'module',
          position: positions.get(m.module.name) ?? { x: 0, y: 0 },
          data: {
            label: moduleLabel(t, m.module.name, m.module.display_name),
            family,
            icon: meta.icon,
            tone: meta.tone,
            count: m.module.count,
            status: m.status,
            focus: focus === m.module.name,
            lit: !!chain?.has(m.module.name),
            dim: !!chain && !chain.has(m.module.name),
            critical: m.critical,
            declared: m.module.declared,
          },
          ariaLabel: moduleLabel(t, m.module.name, m.module.display_name),
          draggable: false,
          connectable: false,
        };
      }),
    [shown, positions, focus, chain, t],
  );

  const flowEdges: Edge<FlowEdgeData>[] = useMemo(
    () =>
      inView.map((e, i) => {
        const litEdge = !!chain && chain.has(e.source) && chain.has(e.target);
        return {
          id: `${e.kind}:${e.source}:${e.target}:${i}`,
          source: e.source,
          target: e.target,
          type: 'flow',
          focusable: false,
          data: {
            title: `${moduleLabel(t, e.source)} → ${moduleLabel(t, e.target)}${e.count !== null ? `: ${formatNumber(e.count)}` : ''}`,
            tone: moduleMeta(e.source).tone,
            band: [e.source, e.target].some((m) => STAGES[moduleMeta(m).stage] === 'platform'),
            count: e.count,
            active: e.active,
            importance: e.importance,
            lit: litEdge,
            dim: !!chain && !litEdge,
            reduce,
            stale: e.state === 'stale',
          },
        };
      }),
    [inView, chain, reduce, t],
  );

  // Zoom smoothly to the focused module's neighbourhood (or the whole map).
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (focus && ids.has(focus)) {
        const near = new Set([focus]);
        for (const e of inView) {
          if (e.source === focus) near.add(e.target);
          if (e.target === focus) near.add(e.source);
        }
        void fitView({
          nodes: [...near].map((id) => ({ id })),
          padding: 0.2,
          duration: reduce ? 0 : 600,
          minZoom: MIN_READABLE_ZOOM,
          maxZoom: 1.2,
        });
      } else {
        void fitView({ padding: 0.04, duration: reduce ? 0 : 500, minZoom: MIN_READABLE_ZOOM, maxZoom: 1.1 });
      }
    }, 30);
    return () => window.clearTimeout(handle);
  }, [focus, ids, inView, fitView, reduce]);

  const onNodeClick = useCallback((_: unknown, node: Node) => onSelect(node.id), [onSelect]);

  return (
    <div
      className="relative overflow-hidden rounded-xl border border-border-light bg-surface-secondary"
      style={{ height: height ?? Math.min(760, Math.max(380, contentHeight + 72)) }}
      role="application"
      aria-label={t('data_paths.map_aria', { defaultValue: 'Platform data map. A list with the same content follows.' })}
    >
      <svg width="0" height="0" className="absolute" aria-hidden>
        <defs>
          <marker id="dp-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--oe-text-tertiary)" />
          </marker>
        </defs>
      </svg>
      <ReactFlow
        nodes={[...stageNodes, ...nodes] as Node[]}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={(e, n) => n.type === 'module' && onNodeClick(e, n)}
        onNodeMouseEnter={(_, n) => n.type === 'module' && onHover(n.id)}
        onNodeMouseLeave={() => onHover(null)}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.3}
        maxZoom={2}
        fitView
        fitViewOptions={{ padding: 0.04, minZoom: MIN_READABLE_ZOOM, maxZoom: 1.1 }}
        colorMode={colorMode}
        style={{ background: 'transparent', '--xy-background-color': 'transparent' } as CSSProperties}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={28} size={1} color="var(--oe-border-light)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}

export function PlatformMapCanvas(props: PlatformMapCanvasProps) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
