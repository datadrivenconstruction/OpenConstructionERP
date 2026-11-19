// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The platform map canvas: modules in workflow-stage columns (layout.ts),
// coloured by their sidebar family, edges carrying the project's live counts.
// Data moves along active edges as small particles; with reduced motion the
// particles are replaced by a static arrowhead. Hovering a module lights its
// whole upstream and downstream chain; clicking it zooms to its path.

import { memo, useCallback, useEffect, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MiniMap,
  Position,
  ReactFlowProvider,
  getBezierPath,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import { formatNumber } from '@/shared/lib/formatters';

import type { EdgeOut, Importance, MapModule } from './api';
import { chainOf, layeredLayout } from './layout';
import { moduleMeta } from './moduleMeta';
import { moduleLabel } from './flowModel';
import { useReducedMotion } from './motion';

export type ModuleStatus = 'with_data' | 'empty' | 'not_installed';

export interface CanvasModule {
  module: MapModule;
  status: ModuleStatus;
  critical: boolean;
}

type ModuleNodeData = {
  label: string;
  family: string;
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
  count: number | null;
  active: boolean;
  importance: Importance;
  lit: boolean;
  dim: boolean;
  reduce: boolean;
  stale: boolean;
};

const ModuleNode = memo(function ModuleNode({ data }: NodeProps<Node<ModuleNodeData>>) {
  const { t } = useTranslation();
  return (
    <div
      className={clsx(
        'w-52 rounded-xl border bg-surface-primary px-3 py-2 transition-[opacity,box-shadow] duration-200',
        data.focus ? 'border-oe-blue shadow-md ring-2 ring-oe-blue/30' : data.lit ? 'border-oe-blue/60 shadow-sm' : 'border-border-light shadow-xs',
        data.dim && 'opacity-30',
        data.status === 'not_installed' && 'border-dashed',
      )}
      style={{ borderInlineStartWidth: 4, borderInlineStartColor: data.tone }}
      data-testid="dp-map-node"
    >
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-content-primary">{data.label}</span>
        {data.critical && (
          <span
            className="h-2 w-2 shrink-0 rounded-full bg-semantic-error"
            title={t('data_paths.health_missing_short', { defaultValue: 'A critical input is missing' })}
          />
        )}
      </div>
      <div className="mt-0.5 flex items-center justify-between gap-2 text-2xs text-content-tertiary">
        <span className="truncate">{data.family}</span>
        {data.status === 'not_installed' ? (
          <span>{t('data_paths.state_not_installed', { defaultValue: 'Not installed' })}</span>
        ) : data.count !== null ? (
          <span className={clsx('tabular-nums', data.count ? 'font-medium text-content-secondary' : 'text-content-quaternary')}>
            {formatNumber(data.count)}
          </span>
        ) : null}
      </div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
    </div>
  );
});

function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<Edge<FlowEdgeData>>) {
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const d = data as FlowEdgeData;
  const width = d.importance === 'critical' ? 2.5 : d.importance === 'high' ? 1.75 : 1.1;
  const stroke = d.stale ? 'var(--oe-warning)' : d.lit ? 'var(--oe-blue)' : 'var(--oe-border)';
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke,
          strokeWidth: width + (d.lit ? 0.75 : 0),
          opacity: d.dim ? 0.15 : 1,
          strokeDasharray: d.stale ? '6 4' : undefined,
          transition: 'opacity 200ms, stroke 200ms',
        }}
        markerEnd={d.reduce || !d.active ? 'url(#dp-arrow)' : undefined}
      />
      {d.active && !d.reduce && !d.dim && (
        <circle r={d.lit ? 3 : 2.2} fill="var(--oe-blue)" opacity={0.75}>
          <animateMotion dur={`${d.importance === 'critical' ? 2.2 : 3.2}s`} repeatCount="indefinite" path={path} />
        </circle>
      )}
      {d.count !== null && d.count > 0 && !d.dim && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none absolute rounded-full border border-border-light bg-surface-primary px-1.5 text-2xs tabular-nums text-content-secondary shadow-xs"
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
          >
            {formatNumber(d.count)}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { module: ModuleNode };
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

function Canvas({ modules, edges, focus, visible, lit, hovered, onHover, onSelect, showTechnical, height = 620 }: PlatformMapCanvasProps) {
  const { t } = useTranslation();
  const reduce = useReducedMotion();
  const { fitView } = useReactFlow();

  const shownEdges = useMemo(
    () => edges.filter((e) => (showTechnical || e.kind === 'declared') && e.source !== e.target),
    [edges, showTechnical],
  );
  const shown = useMemo(() => modules.filter((m) => !visible || visible.has(m.module.name)), [modules, visible]);
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
      ),
    [shown, inView],
  );

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
    [inView, chain, reduce],
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
        void fitView({ nodes: [...near].map((id) => ({ id })), padding: 0.25, duration: reduce ? 0 : 600, maxZoom: 1.2 });
      } else {
        void fitView({ padding: 0.12, duration: reduce ? 0 : 500 });
      }
    }, 30);
    return () => window.clearTimeout(handle);
  }, [focus, ids, inView, fitView, reduce]);

  const onNodeClick = useCallback((_: unknown, node: Node) => onSelect(node.id), [onSelect]);

  return (
    <div
      className="relative overflow-hidden rounded-xl border border-border-light bg-surface-secondary"
      style={{ height }}
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
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={(_, n) => onHover(n.id)}
        onNodeMouseLeave={() => onHover(null)}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.1}
        maxZoom={2}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={28} size={1} color="var(--oe-border-light)" />
        <Controls showInteractive={false} position="bottom-right" />
        <MiniMap
          pannable
          zoomable
          position="top-right"
          nodeColor={(n) => (n.data as ModuleNodeData).tone}
          nodeStrokeWidth={0}
          maskColor="rgb(0 0 0 / 0.08)"
          className="!rounded-lg !border !border-border-light !bg-surface-primary"
        />
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
