// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The focused-module canvas: stage columns (sources, supplies here, this
// module, uses it directly, on to the result) across coloured lanes named
// after the menu groups. Every card fetches its own live chips, so one
// failing number hides only itself. Hovering a card lights every path between
// it and the focus; a playing data trace runs particles along its links;
// arrow keys walk the cards; far out, cards fold into dots.

import { memo, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  BaseEdge,
  Handle,
  MiniMap,
  Position,
  useReactFlow,
  useStore,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Building2,
  FileText,
  LayoutDashboard,
  Map as MapIcon,
  Maximize2,
  Radio,
  RectangleHorizontal,
  RectangleVertical,
  Search,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';

import { formatNumber } from '@/shared/lib/formatters';
import { useThemeStore } from '@/stores/useThemeStore';

import { useModuleChips, type Chip, type EdgeOut, type MapModule, type ModuleFocus } from './api';
import { humanize, moduleLabel } from './flowModel';
import { moduleMeta } from './moduleMeta';
import { useReducedMotion } from './motion';
import {
  COLUMNS,
  EXTERNAL_LANE,
  edgeKey,
  fadeFor,
  flowEdges,
  nextNode,
  pathsBetween,
  stagesFrom,
  swimlaneLayout,
  type FlowEdge,
  type Orientation,
} from './swimlane';
import { RoleHex } from './RoleHex';

export type LayoutMode = 'auto' | Orientation;

const CARD_W = 216;
const CARD_H = 96;
/** Below this zoom a card folds into a dot with its name underneath. */
const DOT_ZOOM = 0.5;

const CHIP_TONE: Record<string, string> = {
  neutral: 'bg-surface-secondary text-content-secondary',
  info: 'bg-oe-blue-subtle text-oe-blue-text',
  success: 'bg-semantic-success-bg text-semantic-success',
  warning: 'bg-semantic-warning-bg text-semantic-warning',
  error: 'bg-semantic-error-bg text-semantic-error',
};

const COLUMN_KEYS: Record<string, [string, string]> = {
  sources: ['data_paths.col_sources', 'Sources'],
  supplies: ['data_paths.col_supplies', 'Supplies here'],
  here: ['data_paths.col_here', 'This module'],
  uses: ['data_paths.col_uses', 'Uses it directly'],
  result: ['data_paths.col_result', 'On to the result'],
};

type CardData = {
  module: string;
  label: string;
  sub: string;
  tone: string;
  stage: number;
  focus: boolean;
  selected: boolean;
  lit: boolean;
  dim: boolean;
  roles: string[];
  projectId: string | null;
  installed: boolean;
  portrait: boolean;
  onRole?: (role: string) => void;
};

type ExternalData = { label: string; kind: 'party' | 'file' | 'device'; role: string; portrait: boolean; dim: boolean };
type LaneData = { label: string; tone: string; width: number; height: number; portrait: boolean };
type HeaderData = { label: string; span: number; portrait: boolean; here: boolean };

function LiveChips({ module, projectId, label }: { module: string; projectId: string | null; label: string }) {
  const { t } = useTranslation();
  const chips = useModuleChips(module, projectId, !!projectId);
  // A failed source is silent: its chips disappear, the card stays.
  const list: Chip[] = chips.data?.chips ?? [];
  if (!list.length) return null;
  return (
    <div className="flex flex-wrap gap-1" aria-label={label}>
      {list.slice(0, 3).map((c) => (
        <span
          key={c.id}
          className={clsx('inline-flex h-5 items-center gap-1 rounded-full px-1.5 text-2xs font-medium tabular-nums', CHIP_TONE[c.tone] ?? CHIP_TONE.neutral)}
          data-testid="dp-chip"
        >
          {c.tone !== 'neutral' && <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />}
          {c.id === 'head'
            ? `${formatNumber(c.count)} ${String(t(c.label, { defaultValue: '' }))}`
            : String(t(c.label, { defaultValue: '{{count}}', count: c.count }))}
        </span>
      ))}
    </div>
  );
}

const ModuleCard = memo(function ModuleCard({ data }: NodeProps<Node<CardData>>) {
  const { t } = useTranslation();
  const zoom = useStore((s) => s.transform[2]);
  const target = data.portrait ? Position.Top : Position.Left;
  const source = data.portrait ? Position.Bottom : Position.Right;
  const handles = (
    <>
      <Handle type="target" position={target} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
      <Handle type="source" position={source} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
    </>
  );
  const opacity = data.dim ? 0.18 : data.lit || data.focus ? 1 : fadeFor(data.stage);
  if (zoom < DOT_ZOOM && !data.focus) {
    return (
      <div className="flex flex-col items-center gap-1" style={{ width: CARD_W, height: CARD_H, opacity }} title={data.label}>
        {handles}
        <span className="mt-6 h-9 w-9 rounded-full border-2 border-surface-primary shadow-sm" style={{ background: data.tone }} />
        <span className="max-w-full truncate text-lg font-medium text-content-primary">{data.label}</span>
      </div>
    );
  }
  return (
    <div
      className={clsx(
        'group relative flex flex-col gap-1.5 overflow-hidden rounded-2xl border bg-surface-primary px-3 py-2.5 transition-[opacity,box-shadow,transform] duration-200 motion-reduce:transition-none',
        data.focus
          ? 'border-oe-blue shadow-lg ring-4 ring-oe-blue/15'
          : data.lit
            ? 'border-oe-blue/70 shadow-md'
            : 'border-border-light shadow-sm hover:shadow-md',
        data.selected && !data.focus && 'ring-2 ring-oe-blue/50',
        !data.installed && 'border-dashed',
      )}
      style={{ width: CARD_W, height: CARD_H, opacity }}
      data-testid={data.focus ? 'dp-focus-card' : 'dp-card'}
      data-module={data.module}
    >
      {handles}
      <span className="absolute inset-y-0 start-0 w-1" style={{ background: data.tone }} aria-hidden />
      <div className="min-w-0">
        <p className={clsx('truncate leading-tight text-content-primary', data.focus ? 'text-base font-semibold' : 'text-sm font-semibold')}>
          {data.label}
        </p>
        <p className="truncate text-xs text-content-tertiary">{data.sub}</p>
      </div>
      {data.installed ? (
        <LiveChips module={data.module} projectId={data.projectId} label={t('data_paths.live_numbers', { defaultValue: 'Live numbers' })} />
      ) : (
        <span className="text-2xs text-content-tertiary">{t('data_paths.state_not_installed', { defaultValue: 'Not installed' })}</span>
      )}
      {data.roles.length > 0 && (
        <div className="mt-auto flex items-center gap-0.5">
          {data.roles.slice(0, 4).map((r) => (
            <RoleHex key={r} role={r} size={18} onClick={data.onRole ? () => data.onRole?.(r) : undefined} />
          ))}
          {data.roles.length > 4 && <span className="ms-0.5 text-2xs text-content-tertiary">+{data.roles.length - 4}</span>}
        </div>
      )}
    </div>
  );
});

const EXTERNAL_ICON = { party: Building2, file: FileText, device: Radio } as const;

const ExternalCard = memo(function ExternalCard({ data }: NodeProps<Node<ExternalData>>) {
  const { t } = useTranslation();
  const Icon = EXTERNAL_ICON[data.kind] ?? FileText;
  const kindKey = { party: 'data_paths.external_party', file: 'data_paths.external_file', device: 'data_paths.external_device' }[data.kind];
  const kindDef = { party: 'Person or company', file: 'File', device: 'Device or service' }[data.kind];
  return (
    <div
      className="flex h-full flex-col gap-1.5 rounded-2xl border-2 border-dashed border-border bg-surface-primary/80 px-3 py-2.5"
      style={{ width: CARD_W, height: CARD_H, opacity: data.dim ? 0.25 : 1 }}
      data-testid="dp-external-card"
    >
      <Handle type="source" position={data.portrait ? Position.Bottom : Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
      <div className="flex items-center gap-2">
        <Icon size={16} className="shrink-0 text-content-tertiary" aria-hidden />
        <p className="truncate text-sm font-semibold text-content-primary">{t(data.label, { defaultValue: '' })}</p>
      </div>
      <p className="text-xs text-content-tertiary">{t(kindKey, { defaultValue: kindDef })}</p>
      {data.role && (
        <div className="mt-auto">
          <RoleHex role={data.role} size={18} />
        </div>
      )}
    </div>
  );
});

const LaneBand = memo(function LaneBand({ data }: NodeProps<Node<LaneData>>) {
  return (
    <div
      className="pointer-events-none rounded-3xl border"
      style={{
        width: data.width,
        height: data.height,
        background: `color-mix(in srgb, ${data.tone} 7%, transparent)`,
        borderColor: `color-mix(in srgb, ${data.tone} 22%, transparent)`,
      }}
    >
      <div
        className={clsx('flex p-4', data.portrait ? 'h-28 items-start' : 'h-full w-28 items-start')}
        style={{ borderColor: `color-mix(in srgb, ${data.tone} 22%, transparent)` }}
      >
        <span className="text-sm font-semibold leading-tight" style={{ color: `color-mix(in srgb, ${data.tone} 75%, var(--oe-text-primary))` }}>
          {data.label}
        </span>
      </div>
    </div>
  );
});

const ColumnHeader = memo(function ColumnHeader({ data }: NodeProps<Node<HeaderData>>) {
  return (
    <div
      className={clsx(
        'pointer-events-none text-2xs font-semibold uppercase tracking-widest',
        data.here ? 'text-oe-blue' : 'text-content-tertiary',
        data.portrait ? 'w-32 text-end' : 'text-center',
      )}
      style={data.portrait ? undefined : { width: data.span }}
    >
      {data.label}
    </div>
  );
});

type LinkData = { lit: boolean; dim: boolean; trace: boolean; derived: boolean; external: boolean; reduce: boolean; portrait: boolean; title: string };

function bezier(sx: number, sy: number, tx: number, ty: number, portrait: boolean): string {
  if (portrait) {
    const c = Math.max(30, Math.abs(ty - sy) * 0.45);
    return `M ${sx} ${sy} C ${sx} ${sy + c}, ${tx} ${ty - c}, ${tx} ${ty}`;
  }
  const c = Math.max(30, Math.abs(tx - sx) * 0.45);
  return `M ${sx} ${sy} C ${sx + c} ${sy}, ${tx - c} ${ty}, ${tx} ${ty}`;
}

function LinkEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<Edge<LinkData>>) {
  const d = data as LinkData;
  const path = bezier(sourceX, sourceY, targetX, targetY, d.portrait);
  const strong = d.lit || d.trace;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={strong ? 'url(#dp-arrow-lit)' : 'url(#dp-arrow)'}
        style={{
          stroke: strong ? 'var(--oe-blue)' : 'var(--oe-border)',
          strokeWidth: strong ? 2.5 : d.derived ? 1.25 : 1.75,
          strokeDasharray: d.external || d.derived ? '5 5' : undefined,
          opacity: d.dim ? 0.15 : strong ? 1 : 0.9,
          transition: 'opacity 150ms, stroke 150ms',
        }}
      />
      <path d={path} fill="none" stroke="transparent" strokeWidth={12}>
        <title>{d.title}</title>
      </path>
      {d.trace && !d.reduce && (
        <>
          {[0, 0.5, 1].map((begin) => (
            <circle key={begin} r={3.5} fill="var(--oe-blue)">
              <animateMotion dur="1.6s" begin={`${begin}s`} repeatCount="indefinite" path={path} />
            </circle>
          ))}
        </>
      )}
    </>
  );
}

const nodeTypes = { card: ModuleCard, external: ExternalCard, lane: LaneBand, header: ColumnHeader };
const edgeTypes = { link: LinkEdge };

export interface FocusCanvasProps {
  focus: string;
  modules: MapModule[];
  edges: EdgeOut[];
  info: ModuleFocus | undefined;
  projectId: string | null;
  technical: boolean;
  layout: LayoutMode;
  onLayout: (mode: LayoutMode) => void;
  /** Links a playing trace has walked (`a>b`), lit with particles. */
  traceLinks: string[];
  /** Modules of the playing trace up to its current step. */
  traceModules: string[];
  onRefocus: (module: string) => void;
  onOpen: (module: string) => void;
  onRole?: (role: string) => void;
  /** Called with the downstream modules in view (for the changes panel). */
  onWindow?: (stages: Map<string, number>) => void;
  initialNode?: string | null;
  onSelectNode?: (module: string) => void;
  height?: number | string;
}

function CanvasInner(props: FocusCanvasProps) {
  const { focus, modules, edges, info, projectId, technical, layout, onLayout, traceLinks, traceModules, onRefocus, onOpen, onRole, onWindow, initialNode, onSelectNode } = props;
  const { t } = useTranslation();
  const reduce = useReducedMotion();
  const colorMode = useThemeStore((s) => s.resolved);
  const { fitView, zoomIn, zoomOut, setCenter, getZoom } = useReactFlow();
  const zoom = useStore((s) => s.transform[2]);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>(initialNode ?? focus);
  const [query, setQuery] = useState('');
  const [showMini, setShowMini] = useState(true);
  const [aspect, setAspect] = useState(1.6);

  useEffect(() => setSelected(initialNode ?? focus), [focus, initialNode]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setAspect(entry.contentRect.width / Math.max(1, entry.contentRect.height));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const orientation: Orientation = layout === 'auto' ? (aspect >= 1 ? 'landscape' : 'portrait') : layout;
  const portrait = orientation === 'portrait';
  const byName = useMemo(() => new Map(modules.map((m) => [m.name, m])), [modules]);
  const fe = useMemo(
    () => flowEdges(edges.filter((e) => byName.has(e.source) && byName.has(e.target)), { technical }),
    [edges, byName, technical],
  );
  const stages = useMemo(() => stagesFrom(focus, fe), [focus, fe]);
  useEffect(() => onWindow?.(stages), [stages, onWindow]);

  const externals = useMemo(() => (info?.external ?? []).map((x, i) => ({ ...x, id: `ext:${i}` })), [info]);
  const allEdges: FlowEdge[] = useMemo(
    () => [
      ...fe.filter((e) => stages.has(e.source) && stages.has(e.target)),
      ...externals.map((x) => ({ source: x.id, target: focus, kind: 'declared' as const })),
    ],
    [fe, stages, externals, focus],
  );
  const laneOf = useCallback((m: string) => (m.startsWith('ext:') ? EXTERNAL_LANE : moduleMeta(m).familyId), []);
  const placed = useMemo(() => {
    const laneNodes = [
      ...[...stages].map(([id, stage]) => ({ id, stage, lane: laneOf(id) })),
      ...externals.map((x) => ({ id: x.id, stage: Math.min(-1, ...[...stages.values()]), lane: EXTERNAL_LANE })),
    ];
    return swimlaneLayout(laneNodes, allEdges, { orientation, cardWidth: CARD_W, cardHeight: CARD_H });
  }, [stages, externals, allEdges, orientation, laneOf]);

  const lit = useMemo(() => {
    if (traceModules.length) return { nodes: new Set(traceModules), edges: new Set(traceLinks) };
    if (hovered && hovered !== focus) return pathsBetween(hovered, focus, allEdges);
    return null;
  }, [hovered, focus, allEdges, traceModules, traceLinks]);

  const needle = query.trim().toLowerCase();
  const nodes: Node[] = useMemo(() => {
    const out: Node[] = [];
    const laneLabel = (lane: string) => {
      if (lane === EXTERNAL_LANE) return String(t('data_paths.lane_external', { defaultValue: 'Where from' }));
      const sample = [...stages.keys()].find((m) => laneOf(m) === lane);
      const meta = sample ? moduleMeta(sample) : null;
      if (!meta?.familyLabelKey) return String(t('data_paths.lane_platform', { defaultValue: 'Platform' }));
      return String(t(meta.familyLabelKey, { defaultValue: meta.familyDefaultLabel ?? humanize(lane) }));
    };
    const laneTone = (lane: string) => {
      const sample = [...stages.keys()].find((m) => laneOf(m) === lane);
      return lane === EXTERNAL_LANE || !sample ? 'var(--oe-text-tertiary)' : moduleMeta(sample).tone;
    };
    for (const box of placed.lanes) {
      out.push({
        id: `lane:${box.id}`,
        type: 'lane',
        position: { x: box.x - (portrait ? 0 : 0), y: box.y },
        data: { label: laneLabel(box.id), tone: laneTone(box.id), width: box.width, height: box.height, portrait },
        draggable: false,
        selectable: false,
        focusable: false,
        zIndex: -1,
      });
    }
    for (const col of COLUMNS) {
      const at = col.stages.map((s) => placed.stageAt.get(s)).filter((v): v is number => v !== undefined);
      if (!at.length) continue;
      const [key, def] = COLUMN_KEYS[col.id]!;
      const start = Math.min(...at);
      const span = Math.max(...at) - start + (portrait ? CARD_H : CARD_W);
      out.push({
        id: `col:${col.id}`,
        type: 'header',
        position: portrait ? { x: -150, y: start + CARD_H / 2 - 8 } : { x: start, y: -34 },
        data: { label: String(t(key, { defaultValue: def })), span, portrait, here: col.id === 'here' },
        draggable: false,
        selectable: false,
        focusable: false,
      });
    }
    for (const [id, stage] of stages) {
      const pos = placed.nodes.get(id);
      const m = byName.get(id);
      if (!pos || !m) continue;
      const label = moduleLabel(t, id, m.display_name);
      const match = needle && `${label} ${id}`.toLowerCase().includes(needle);
      const meta = moduleMeta(id);
      out.push({
        id,
        type: 'card',
        position: pos,
        data: {
          module: id,
          label,
          sub: m.why ? String(t(m.why, { defaultValue: '' })) || laneLabel(meta.familyId) : laneLabel(meta.familyId),
          tone: meta.tone,
          stage,
          focus: id === focus,
          selected: id === selected,
          lit: !!lit?.nodes.has(id) || !!match,
          dim: (!!lit && !lit.nodes.has(id)) || (!!needle && !match && id !== focus),
          roles: m.roles,
          projectId,
          installed: m.installed,
          portrait,
          onRole,
        } satisfies CardData,
        draggable: false,
      });
    }
    for (const x of externals) {
      const pos = placed.nodes.get(x.id);
      if (!pos) continue;
      out.push({
        id: x.id,
        type: 'external',
        position: pos,
        data: { label: x.label, kind: x.kind, role: x.role, portrait, dim: !!lit && !traceModules.length && hovered !== x.id } satisfies ExternalData,
        draggable: false,
      });
    }
    return out;
  }, [placed, stages, byName, t, focus, selected, lit, needle, projectId, portrait, onRole, externals, laneOf, traceModules.length, hovered]);

  const rfEdges: Edge[] = useMemo(
    () =>
      allEdges.map((e) => {
        const key = edgeKey(e.source, e.target);
        const external = e.source.startsWith('ext:');
        return {
          id: key,
          source: e.source,
          target: e.target,
          type: 'link',
          data: {
            lit: !!lit?.edges.has(key),
            dim: !!lit && !lit.edges.has(key),
            trace: traceLinks.includes(key),
            derived: e.kind !== 'declared',
            external,
            reduce,
            portrait,
            title:
              e.kind === 'declared'
                ? `${moduleLabel(t, e.source.startsWith('ext:') ? focus : e.source)} → ${moduleLabel(t, e.target)}`
                : String(t('data_paths.derived_link', { defaultValue: 'Technical link, found in the code' })),
          } satisfies LinkData,
        };
      }),
    [allEdges, lit, traceLinks, reduce, portrait, t, focus],
  );

  useEffect(() => {
    const id = window.setTimeout(() => void fitView({ padding: 0.12, duration: reduce ? 0 : 300 }), 30);
    return () => window.clearTimeout(id);
  }, [focus, orientation, technical, fitView, reduce, placed.width, placed.height]);

  const positions = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    for (const [id] of stages) {
      const p = placed.nodes.get(id);
      if (p) m.set(id, p);
    }
    return m;
  }, [stages, placed]);

  const centreOn = useCallback(
    (id: string) => {
      const p = positions.get(id);
      if (p) void setCenter(p.x + CARD_W / 2, p.y + CARD_H / 2, { zoom: Math.max(getZoom(), 0.8), duration: reduce ? 0 : 250 });
    },
    [positions, setCenter, getZoom, reduce],
  );

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const dirs: Record<string, 'left' | 'right' | 'up' | 'down'> = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
    const dir = dirs[e.key];
    if (dir) {
      e.preventDefault();
      const next = nextNode(selected, dir, positions);
      setSelected(next);
      setHovered(next);
      onSelectNode?.(next);
      centreOn(next);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (selected !== focus) onRefocus(selected);
    } else if (e.key === 'o' || e.key === 'O') {
      onOpen(selected);
    } else if (e.key === 'Escape') {
      setHovered(null);
    }
  };

  const selectedLabel = moduleLabel(t, selected, byName.get(selected)?.display_name);
  const btn = 'flex h-8 w-8 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue';
  const modes: { id: LayoutMode; icon: typeof LayoutDashboard; key: string; def: string }[] = [
    { id: 'auto', icon: LayoutDashboard, key: 'data_paths.layout_auto', def: 'Auto' },
    { id: 'landscape', icon: RectangleHorizontal, key: 'data_paths.layout_landscape', def: 'Landscape' },
    { id: 'portrait', icon: RectangleVertical, key: 'data_paths.layout_portrait', def: 'Portrait' },
  ];

  return (
    <div
      ref={wrapRef}
      className="relative h-full min-h-[420px] w-full overflow-hidden rounded-2xl border border-border-light bg-surface-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
      tabIndex={0}
      role="application"
      aria-roledescription={t('data_paths.canvas_role', { defaultValue: 'data path map' })}
      aria-label={t('data_paths.canvas_aria', { defaultValue: 'Data paths around {{module}}', module: moduleLabel(t, focus) })}
      aria-describedby="dp-keyboard-hint"
      onKeyDown={onKey}
      data-testid="dp-focus-canvas"
    >
      <svg width="0" height="0" className="absolute" aria-hidden>
        <defs>
          <marker id="dp-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--oe-border)" />
          </marker>
          <marker id="dp-arrow-lit" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--oe-blue)" />
          </marker>
        </defs>
      </svg>
      <ReactFlow
        nodes={nodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        colorMode={colorMode}
        minZoom={0.15}
        maxZoom={2}
        nodesConnectable={false}
        nodesDraggable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        onNodeMouseEnter={(_, n) => (n.type === 'card' || n.type === 'external' ? setHovered(n.id) : undefined)}
        onNodeMouseLeave={() => setHovered(null)}
        onNodeClick={(_, n) => {
          if (n.type !== 'card') return;
          setSelected(n.id);
          onSelectNode?.(n.id);
          if (n.id !== focus) onRefocus(n.id);
        }}
        onNodeDoubleClick={(_, n) => (n.type === 'card' ? onOpen(n.id) : undefined)}
      >
        {showMini && (
          <MiniMap
            pannable
            zoomable
            className="!rounded-xl !border !border-border-light !bg-surface-primary"
            nodeColor={(n) => (n.id === focus ? 'var(--oe-blue)' : n.type === 'lane' || n.type === 'header' ? 'transparent' : 'var(--oe-border)')}
            nodeStrokeWidth={0}
            maskColor="color-mix(in srgb, var(--oe-bg-secondary) 60%, transparent)"
            ariaLabel={t('data_paths.minimap_toggle', { defaultValue: 'Overview map' })}
          />
        )}
      </ReactFlow>

      <div className="absolute end-3 top-3 flex items-center gap-2">
        <label className="relative">
          <span className="sr-only">{t('data_paths.search_node', { defaultValue: 'Find a module on the canvas' })}</span>
          <Search size={14} className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter') return;
              const hit = [...stages.keys()].find((m) => `${moduleLabel(t, m)} ${m}`.toLowerCase().includes(needle));
              if (hit) {
                setSelected(hit);
                centreOn(hit);
              }
            }}
            placeholder={t('data_paths.search_node', { defaultValue: 'Find a module on the canvas' })}
            className="h-8 w-52 rounded-lg border border-border-light bg-surface-primary/95 ps-8 pe-2 text-sm text-content-primary shadow-sm backdrop-blur focus:border-oe-blue focus:outline-none"
            data-testid="dp-canvas-search"
          />
        </label>
      </div>

      <div
        className="absolute bottom-3 start-3 flex items-center gap-1 rounded-xl border border-border-light bg-surface-primary/95 p-1 shadow-md backdrop-blur"
        role="toolbar"
        aria-label={t('data_paths.canvas_controls', { defaultValue: 'Canvas controls' })}
      >
        <button type="button" className={btn} onClick={() => void zoomIn({ duration: 150 })} aria-label={t('data_paths.zoom_in', { defaultValue: 'Zoom in' })} title={t('data_paths.zoom_in', { defaultValue: 'Zoom in' })}>
          <ZoomIn size={16} />
        </button>
        <button type="button" className={btn} onClick={() => void zoomOut({ duration: 150 })} aria-label={t('data_paths.zoom_out', { defaultValue: 'Zoom out' })} title={t('data_paths.zoom_out', { defaultValue: 'Zoom out' })}>
          <ZoomOut size={16} />
        </button>
        <button type="button" className={btn} onClick={() => void fitView({ padding: 0.12, duration: 200 })} aria-label={t('data_paths.fit', { defaultValue: 'Fit to screen' })} title={t('data_paths.fit', { defaultValue: 'Fit to screen' })}>
          <Maximize2 size={16} />
        </button>
        <span className="w-12 text-center text-xs tabular-nums text-content-tertiary" aria-live="polite" data-testid="dp-zoom">
          {formatNumber(Math.round(zoom * 100))}%
        </span>
        <span className="mx-1 h-5 w-px bg-border-light" aria-hidden />
        <div role="radiogroup" aria-label={t('data_paths.layout_aria', { defaultValue: 'Layout' })} className="flex items-center gap-0.5">
          {modes.map((m) => {
            const Icon = m.icon;
            const active = layout === m.id;
            return (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => onLayout(m.id)}
                className={clsx(
                  'flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                  active ? 'bg-oe-blue-subtle text-oe-blue-text' : 'text-content-secondary hover:bg-surface-secondary',
                )}
                data-testid={`dp-layout-${m.id}`}
              >
                <Icon size={14} aria-hidden />
                <span className="hidden md:inline">{t(m.key, { defaultValue: m.def })}</span>
              </button>
            );
          })}
        </div>
        <span className="mx-1 h-5 w-px bg-border-light" aria-hidden />
        <button
          type="button"
          className={clsx(btn, showMini && 'text-oe-blue')}
          onClick={() => setShowMini((v) => !v)}
          aria-pressed={showMini}
          aria-label={t('data_paths.minimap_toggle', { defaultValue: 'Overview map' })}
          title={t('data_paths.minimap_toggle', { defaultValue: 'Overview map' })}
        >
          <MapIcon size={16} />
        </button>
      </div>

      <p id="dp-keyboard-hint" className="sr-only">
        {t('data_paths.keyboard_hint', {
          defaultValue: 'Arrow keys move between cards, Enter makes a card the centre, O opens its module.',
        })}{' '}
        {selectedLabel}
      </p>
    </div>
  );
}

export function FocusCanvas(props: FocusCanvasProps) {
  return (
    <div style={{ height: props.height ?? '100%' }} className="w-full">
      <ReactFlowProvider>
        <CanvasInner {...props} />
      </ReactFlowProvider>
    </div>
  );
}
