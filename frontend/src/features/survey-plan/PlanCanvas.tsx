// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PlanCanvas: the grid-first plan editor every survey screen shares.
 *
 * Geometry lives in project grid metres; MapLibre only draws, through the
 * server's view transform. Tools, snapping, precision input and undo work on
 * grid coordinates, so a typed 25.000 m is 25.000 m on the grid. See README.md.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import Map, { Layer, Source, type LayerProps, type MapLayerMouseEvent, type MapRef } from 'react-map-gl/maplibre';
import type { StyleSpecification } from 'maplibre-gl';
import type { Feature, FeatureCollection } from 'geojson';
import { Keyboard, Layers, Maximize2, PanelRight, Redo2, Save, Undo2 } from 'lucide-react';
import 'maplibre-gl/dist/maplibre-gl.css';
import '@/shared/lib/mapLibre';
import { buildBasemapStyle } from '@/features/geo-hub/mapStyles';
import { ApiError } from '@/shared/lib/api';
import { registerActions } from '@/shared/lib/actions/registry';
import { useThemeStore } from '@/stores/useThemeStore';
import { useToastStore } from '@/stores/useToastStore';
import { planApi, planKeys, type ConflictDetail } from './api';
import { GLYPHS_URL, defaultStyle, gridStep, overlayStyle, readPalette, symbolImage, SYMBOLS, type LabelMode, type SymbolName } from './cartography';
import { batch, deleteFeatures, insertVertex, moveVertex, newId, removeVertex, translate, updateFeature } from './engine/commands';
import { bboxOf, dist, distanceToFeature, featureVertices, featuresBBox, midpoint, ringSelfIntersections, type BBox } from './engine/geometry';
import { buildLinework, type CodedPoint } from './engine/linework';
import { runLiveChecks, type LiveFinding } from './engine/liveChecks';
import { SNAP_RADIUS_PX, defaultSnapSettings, setMode, snap as runSnap, toggleAll } from './engine/snap';
import { buildIndex } from './engine/spatialIndex';
import { fromDTO, localTransform, metresPerPixel, scaleDenominator, type ViewTransform } from './engine/viewTransform';
import { useCodeLibrary, usePlanConventions, useViewTransform } from './hooks';
import { layer as makeLayer, mergeLayers } from './planLayers';
import { EMPTY_FC, gridBBoxOfView, gridLines, overlayFeature, toCollection } from './render';
import { BUILTIN_TOOLS, PAN_TOOL, SELECT_TOOL, defaultToolIds, legLabels, measureOf } from './tools/builtins';
import { useDirty, usePlanEditStore } from './usePlanEditStore';
import { Inspector } from './chrome/Inspector';
import { LayerPanel, type Basemap } from './chrome/LayerPanel';
import { DECOR_CLEARANCE_PX, NorthArrow, ScaleBar } from './chrome/MapDecor';
import { PrecisionBar } from './chrome/PrecisionBar';
import { ShortcutHelp } from './chrome/ShortcutHelp';
import { SNAP_LABEL, SnapCursor, SnapIcon } from './chrome/SnapGlyph';
import { StatusBar } from './chrome/StatusBar';
import { ToolRail } from './chrome/ToolRail';
import type { GridXY, LayerViewState, MeasureResult, PlanCanvasProps, PlanFeature, PlanLayerSpec, PlanTool, SnapKind, SnapResult, SnapSettings, ToolContext } from './types';
import { SNAP_KINDS } from './types';
import { useMapLibreLocale } from '@/shared/lib/mapLibreLocale';

const HIT_PX = 6;
const HANDLE_PX = 8;
const DRAG_PX = 3;
const MAX_HANDLE_FEATURES = 20;

type Drag =
  | { kind: 'vertex'; fid: string; index: number; at: GridXY }
  | { kind: 'mid'; fid: string; index: number; at: GridXY }
  | { kind: 'move'; ids: string[]; from: GridXY; at: GridXY }
  | { kind: 'box'; from: GridXY; at: GridXY; crossing: boolean };

interface ViewState {
  zoom: number;
  lat: number;
  bearing: number;
  bbox: BBox | null;
}

function paperStyle(bg: string): StyleSpecification {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  return {
    version: 8,
    glyphs: `${origin}${GLYPHS_URL}`,
    sources: {},
    layers: [{ id: 'oe-plan-bg', type: 'background', paint: { 'background-color': bg } }],
  };
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable);
}

/** `Shift+M`, `Mod+Z`, `F3`, `?` from a key event, letters by physical key. */
/** One fixed-height row: tool options scroll sideways instead of wrapping and pushing the plan down. */
export const OPTIONS_BAR_CLASS = 'flex h-12 flex-nowrap items-center gap-2 border-b border-border-light bg-surface-elevated px-3';

export function chordOf(e: Pick<KeyboardEvent, 'key' | 'code' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>): string {
  let key = e.key;
  if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);
  else if (/^Digit[0-9]$/.test(e.code)) key = e.code.slice(5);
  if (key === '?') return '?';
  const mods: string[] = [];
  if (e.ctrlKey || e.metaKey) mods.push('Mod');
  if (e.altKey) mods.push('Alt');
  if (e.shiftKey) mods.push('Shift');
  return [...mods, key].join('+');
}

/** Vertex handle indices of a feature (a closed ring's repeat is not a handle). */
function handleIndices(f: PlanFeature): number[] {
  const g = f.geometry;
  if (g.type === 'Point') return [0];
  if (g.type === 'LineString') return g.coordinates.map((_, i) => i);
  const out: number[] = [];
  let base = 0;
  for (const r of g.coordinates) {
    const closed = r.length > 1 && r[0]![0] === r[r.length - 1]![0] && r[0]![1] === r[r.length - 1]![1];
    for (let i = 0; i < r.length - (closed ? 1 : 0); i++) out.push(base + i);
    base += r.length;
  }
  return out;
}

/** Segments between consecutive handles, with the index the new vertex goes after. */
function midHandles(f: PlanFeature): { index: number; at: GridXY }[] {
  const g = f.geometry;
  if (g.type === 'Point') return [];
  const v = featureVertices(f);
  const out: { index: number; at: GridXY }[] = [];
  if (g.type === 'LineString') {
    for (let i = 1; i < v.length; i++) out.push({ index: i - 1, at: midpoint(v[i - 1]!, v[i]!) });
    return out;
  }
  let base = 0;
  for (const r of g.coordinates) {
    for (let i = 1; i < r.length; i++) out.push({ index: base + i - 1, at: midpoint(v[base + i - 1]!, v[base + i]!) });
    base += r.length;
  }
  return out;
}

export default function PlanCanvas(props: PlanCanvasProps) {
  const { projectId, editable = false, heightClass = 'h-[32rem]', testId = 'plan-canvas' } = props;
  const { t } = useTranslation();
  const mapLocale = useMapLibreLocale();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const theme = useThemeStore((s) => s.resolved);
  const mapRef = useRef<MapRef | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // ── Data ────────────────────────────────────────────────────────────────
  const palette = useMemo(() => readPalette(), [theme]);
  const { conventions, csf } = usePlanConventions(projectId, props.conventions);
  const library = useCodeLibrary(projectId).data?.items ?? [];
  const vtQuery = useViewTransform(projectId);

  const declared = useMemo(() => {
    let all = mergeLayers(props.layers, props.extraLayers ?? []);
    if (editable && !all.some((l) => l.id === 'sketch')) all = mergeLayers([...all, makeLayer('sketch', [], { editable: true })]);
    return all;
  }, [props.layers, props.extraLayers, editable]);

  const editableLayers = useMemo(() => new Set(declared.filter((l) => editable && l.editable).map((l) => l.id as string)), [declared, editable]);
  const baseFeatures = useMemo(() => declared.filter((l) => editableLayers.has(l.id)).flatMap((l) => l.features), [declared, editableLayers]);

  const scope = `${projectId}:${testId}`;
  const bind = usePlanEditStore((s) => s.bind);
  const setBase = usePlanEditStore((s) => s.setBase);
  const working = usePlanEditStore((s) => s.working);
  const selection = usePlanEditStore((s) => s.selection);
  const setSelectionStore = usePlanEditStore((s) => s.setSelection);
  const push = usePlanEditStore((s) => s.push);
  const undoOne = usePlanEditStore((s) => s.undoOne);
  const redoOne = usePlanEditStore((s) => s.redoOne);
  const canUndo = usePlanEditStore((s) => s.undo.length > 0);
  const canRedo = usePlanEditStore((s) => s.redo.length > 0);
  const saving = usePlanEditStore((s) => s.saving);
  const dirty = useDirty();
  useEffect(() => bind(scope), [bind, scope]);
  useEffect(() => setBase(baseFeatures), [setBase, baseFeatures]);

  // Layers as drawn: editable ones read the working copy (undo applied), the rest as given.
  const layers = useMemo((): PlanLayerSpec[] => {
    const byLayer = new globalThis.Map<string, PlanFeature[]>();
    for (const f of working.values()) {
      const list = byLayer.get(f.layer) ?? [];
      list.push(f);
      byLayer.set(f.layer, list);
    }
    let out = declared.map((l) => (editableLayers.has(l.id) ? { ...l, features: byLayer.get(l.id) ?? [] } : l));
    const points = out.find((l) => l.id === 'points');
    if (points && library.length > 0 && !out.some((l) => l.id === 'linework')) {
      const coded: CodedPoint[] = points.features
        .filter((f) => f.geometry.type === 'Point' && typeof f.properties.code === 'string' && f.properties.code)
        .map((f) => {
          const c = f.geometry.coordinates as number[];
          return { id: f.id, e: c[0]!, n: c[1]!, z: c[2] ?? null, code: String(f.properties.code), sourceLine: (f.properties.source_line as number | null) ?? null };
        });
      const lw = buildLinework(coded, library);
      if (lw.length > 0) out = mergeLayers([...out, makeLayer('linework', lw, { snappable: true, selectable: true })]);
    }
    return out;
  }, [declared, editableLayers, working, library]);

  const allFeatures = useMemo(() => layers.flatMap((l) => l.features), [layers]);
  const featureById = useMemo(() => {
    const m = new globalThis.Map<string, PlanFeature>();
    for (const f of allFeatures) m.set(f.id, f);
    return m;
  }, [allFeatures]);

  const vt: ViewTransform = useMemo(() => {
    if (vtQuery.data) return fromDTO(vtQuery.data);
    const bb = featuresBBox(allFeatures);
    return localTransform(bb ? (bb[0] + bb[2]) / 2 : 0, bb ? (bb[1] + bb[3]) / 2 : 0);
    // The fallback only needs the first extent; refitting on every edit would jump the view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vtQuery.data]);

  // ── View state ──────────────────────────────────────────────────────────
  const [layerState, setLayerState] = useState<Record<string, LayerViewState>>({});
  const viewOf = (l: PlanLayerSpec): LayerViewState => layerState[l.id] ?? { visible: !l.defaultHidden, locked: false, opacity: 1 };
  const [basemap, setBasemap] = useState<Basemap>('paper');
  const [labels, setLabels] = useState<LabelMode>('id');
  const [panel, setPanel] = useState<'none' | 'layers'>('none');
  const [inspectorOpen, setInspectorOpen] = useState(props.inspector ?? true);
  const [help, setHelp] = useState(false);
  const [view, setView] = useState<ViewState>({ zoom: 16, lat: 0, bearing: 0, bbox: null });
  const [activeLayer, setActiveLayer] = useState<string>(props.activeLayer ?? 'sketch');
  const canMap = vt.kind === 'polynomial';

  // ── Tools ───────────────────────────────────────────────────────────────
  const tools = useMemo(() => {
    const ids = props.tools ?? defaultToolIds(editable);
    const all = [...BUILTIN_TOOLS, ...(props.extraTools ?? [])];
    return all.filter((x) => (ids.includes(x.id) || (props.extraTools ?? []).includes(x)) && (editable || !x.edits));
  }, [props.tools, props.extraTools, editable]);
  const [toolId, setToolId] = useState<string>(SELECT_TOOL);
  const tool: PlanTool = tools.find((x) => x.id === toolId) ?? tools[0] ?? BUILTIN_TOOLS[0]!;
  const [vertices, setVertices] = useState<GridXY[]>([]);
  const [measure, setMeasure] = useState<MeasureResult | null>(null);
  const [measurePts, setMeasurePts] = useState<GridXY[]>([]);
  const [snapSettings, setSnapSettings] = useState<SnapSettings>(defaultSnapSettings);
  const [cursor, setCursor] = useState<GridXY | null>(null);
  const [snapHit, setSnapHit] = useState<SnapResult | null>(null);
  const [screen, setScreen] = useState<{ x: number; y: number } | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [focusToken, setFocusToken] = useState(0);
  const [announce, setAnnounce] = useState('');
  const downRef = useRef<{ x: number; y: number; at: GridXY; shift: boolean; alt: boolean } | null>(null);

  const pickTool = useCallback(
    (id: string) => {
      setToolId(id);
      setVertices([]);
      setDrag(null);
      if (!id.startsWith('measure')) {
        setMeasure(null);
        setMeasurePts([]);
      }
    },
    [],
  );

  const isEditable = useCallback(
    (f: PlanFeature) => {
      if (!editableLayers.has(f.layer)) return false;
      const l = layers.find((x) => x.id === f.layer);
      return !!l && !viewOf(l).locked && viewOf(l).visible;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editableLayers, layers, layerState],
  );

  const visibleSnappable = useMemo(
    () => layers.filter((l) => (l.snappable ?? true) && viewOf(l).visible).flatMap((l) => l.features),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layers, layerState],
  );
  const index = useMemo(() => buildIndex(visibleSnappable, 5), [visibleSnappable]);
  const selectable = useMemo(
    () => layers.filter((l) => (l.selectable ?? true) && viewOf(l).visible).flatMap((l) => l.features),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layers, layerState],
  );

  const mpp = metresPerPixel(view.zoom, view.lat, vt.kind);
  const selected = useMemo(() => [...selection].map((id) => featureById.get(id)).filter((f): f is PlanFeature => !!f), [selection, featureById]);

  const setSelection = useCallback(
    (ids: Iterable<string>) => {
      const list = [...ids];
      setSelectionStore(list);
      props.onSelect?.(list);
    },
    [setSelectionStore, props],
  );

  const ctx: ToolContext = {
    conventions,
    activeLayer,
    cursor,
    snap: snapHit,
    vertices,
    setVertices,
    commit: (c) => push(c),
    finish: () => finishShape(),
    announce: setAnnounce,
    features: working,
    selection,
    setSelection,
    setMeasure: (m) => {
      setMeasure(m);
      if (m) setAnnounce(m.text);
    },
    newId,
    t: (key, options) => String(t(key, options as never)),
  };

  function finishShape(pts: GridXY[] = vertices) {
    if (tool.onFinish && pts.length > 0) tool.onFinish(pts, ctx);
    if (tool.group === 'measure') setMeasurePts(pts);
    setVertices([]);
  }

  function addVertex(p: GridXY) {
    if (props.pickPoint) {
      props.pickPoint(p);
      return;
    }
    if (tool.onClick?.(p, ctx)) {
      if (tool.group === 'measure') setMeasurePts([...vertices, p].slice(-3));
      return;
    }
    const kind = tool.collects ?? 'none';
    if (kind === 'none') return;
    if (kind === 'point') {
      finishShape([p]);
      return;
    }
    const last = vertices[vertices.length - 1];
    if (last && dist(last, p) < 1e-9) return;
    if (kind === 'ring' && vertices.length >= 3 && dist(p, vertices[0]!) < HANDLE_PX * mpp) {
      finishShape();
      return;
    }
    const next = [...vertices, p];
    if (kind === 'arc3' && next.length === 3) {
      finishShape(next);
      return;
    }
    if (tool.group === 'measure') {
      setMeasure(null);
      setMeasurePts([]);
    }
    setVertices(next);
  }

  // ── Pointer ─────────────────────────────────────────────────────────────
  const toGrid = useCallback((e: MapLayerMouseEvent): GridXY => vt.toGrid([e.lngLat.lng, e.lngLat.lat]), [vt]);

  const hitTest = useCallback(
    (p: GridXY): PlanFeature | null => {
      const tol = HIT_PX * mpp;
      let best: PlanFeature | null = null;
      let bestD = tol;
      for (const f of selectable) {
        const d = distanceToFeature(p, f);
        // Points win over the polygon they sit in.
        const bias = f.geometry.type === 'Point' ? 0 : tol * 0.5;
        if (d + bias <= bestD) {
          best = f;
          bestD = d + bias;
        }
      }
      return best;
    },
    [selectable, mpp],
  );

  const handleAt = useCallback(
    (p: GridXY): Drag | null => {
      const tol = HANDLE_PX * mpp;
      for (const f of selected.slice(0, MAX_HANDLE_FEATURES)) {
        if (!isEditable(f)) continue;
        const v = featureVertices(f);
        for (const i of handleIndices(f)) if (dist(v[i]!, p) <= tol) return { kind: 'vertex', fid: f.id, index: i, at: v[i]! };
        for (const m of midHandles(f)) if (dist(m.at, p) <= tol) return { kind: 'mid', fid: f.id, index: m.index, at: m.at };
      }
      return null;
    },
    [selected, isEditable, mpp],
  );

  const snapFor = useCallback(
    (raw: GridXY, alt: boolean, exclude?: Set<string>): SnapResult | null => {
      if (alt) return null;
      return runSnap(index, { cursor: raw, radius: SNAP_RADIUS_PX * mpp, settings: snapSettings, last: vertices[vertices.length - 1] ?? null, exclude });
    },
    [index, mpp, snapSettings, vertices],
  );

  const picking = !!props.pickPoint;
  const drawing = picking || tool.group === 'draw' || tool.group === 'measure' || tool.group === 'annotate' || (tool.collects && tool.collects !== 'none');

  const onMouseMove = (e: MapLayerMouseEvent) => {
    const raw = toGrid(e);
    const alt = e.originalEvent.altKey;
    const exclude = drag && drag.kind !== 'box' && drag.kind !== 'move' ? new Set([drag.fid]) : undefined;
    const s = drawing || (drag && drag.kind !== 'box') ? snapFor(raw, alt, exclude) : null;
    const at = s?.point ?? raw;
    setSnapHit(s);
    setCursor(at);
    if (s) {
      const pt = mapRef.current?.project(vt.toView(s.point));
      setScreen(pt ? { x: pt.x, y: pt.y } : null);
    } else setScreen(null);
    const down = downRef.current;
    if (down && !drag && Math.hypot(e.point.x - down.x, e.point.y - down.y) > DRAG_PX && tool.id === SELECT_TOOL && !spaceHeld && !picking) {
      const h = handleAt(down.at);
      if (h) setDrag(h);
      else {
        const hit = hitTest(down.at);
        if (hit && selection.has(hit.id) && isEditable(hit)) setDrag({ kind: 'move', ids: selected.filter(isEditable).map((f) => f.id), from: down.at, at: down.at });
        else setDrag({ kind: 'box', from: down.at, at: raw, crossing: false });
      }
      return;
    }
    if (drag) {
      if (drag.kind === 'box') setDrag({ ...drag, at: raw, crossing: raw[0] < drag.from[0] });
      else setDrag({ ...drag, at });
      return;
    }
    if (tool.id === SELECT_TOOL && !picking) setHover(hitTest(raw)?.id ?? null);
  };

  const onMouseDown = (e: MapLayerMouseEvent) => {
    downRef.current = { x: e.point.x, y: e.point.y, at: toGrid(e), shift: e.originalEvent.shiftKey, alt: e.originalEvent.altKey };
  };

  const finishDrag = (d: Drag) => {
    if (d.kind === 'box') {
      const bb: BBox = [Math.min(d.from[0], d.at[0]), Math.min(d.from[1], d.at[1]), Math.max(d.from[0], d.at[0]), Math.max(d.from[1], d.at[1])];
      const inside = (p: GridXY) => p[0] >= bb[0] && p[0] <= bb[2] && p[1] >= bb[1] && p[1] <= bb[3];
      const hits = selectable.filter((f) => {
        const v = featureVertices(f);
        return d.crossing ? v.some(inside) : v.every(inside);
      });
      const ids = new Set(downRef.current?.shift ? selection : []);
      hits.forEach((f) => ids.add(f.id));
      setSelection(ids);
      setAnnounce(t('plan.status.selected', { defaultValue: '{{count}} selected', count: ids.size }));
      return;
    }
    if (d.kind === 'move') {
      const de = d.at[0] - d.from[0];
      const dn = d.at[1] - d.from[1];
      if (Math.abs(de) + Math.abs(dn) < 1e-9) return;
      const changes = d.ids.map((id) => featureById.get(id)!).filter(Boolean).map((f) => ({ before: f, after: translate(f, de, dn) }));
      push(batch(changes, { labelKey: 'plan.cmd.move', defaultLabel: 'Move {{count}}', labelParams: { count: changes.length } }));
      return;
    }
    const f = featureById.get(d.fid);
    if (!f) return;
    const after = d.kind === 'vertex' ? moveVertex(f, d.index, d.at) : insertVertex(f, d.index, d.at);
    push(updateFeature(f, after, { labelKey: d.kind === 'vertex' ? 'plan.cmd.vertex_move' : 'plan.cmd.vertex_add', defaultLabel: d.kind === 'vertex' ? 'Vertex moved' : 'Vertex added' }));
  };

  const onMouseUp = () => {
    if (drag) {
      finishDrag(drag);
      setDrag(null);
      downRef.current = null;
      // The click that follows a drag must not change the selection again.
      suppressClick.current = true;
    } else downRef.current = null;
  };
  const suppressClick = useRef(false);

  const onClick = (e: MapLayerMouseEvent) => {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    if (spaceHeld || tool.id === PAN_TOOL) return;
    const raw = toGrid(e);
    if (picking) {
      const s = snapFor(raw, e.originalEvent.altKey);
      addVertex(s?.point ?? raw);
      return;
    }
    if (tool.id === SELECT_TOOL) {
      if (e.originalEvent.altKey) {
        const h = handleAt(raw);
        if (h?.kind === 'vertex') {
          const f = featureById.get(h.fid);
          const after = f ? removeVertex(f, h.index) : null;
          if (f && after) push(updateFeature(f, after, { labelKey: 'plan.cmd.vertex_remove', defaultLabel: 'Vertex removed' }));
          return;
        }
      }
      const hit = hitTest(raw);
      if (!hit) {
        if (!e.originalEvent.shiftKey) setSelection([]);
        return;
      }
      if (e.originalEvent.shiftKey) {
        const ids = new Set(selection);
        if (ids.has(hit.id)) ids.delete(hit.id);
        else ids.add(hit.id);
        setSelection(ids);
      } else setSelection([hit.id]);
      setAnnounce(String(hit.properties.label ?? hit.properties.code ?? t(`plan.layer.${hit.layer}`, { defaultValue: hit.layer })));
      return;
    }
    const s = snapFor(raw, e.originalEvent.altKey);
    addVertex(s?.point ?? raw);
    if (s?.targetLabel) setAnnounce(`${t(SNAP_LABEL[s.kind][0], { defaultValue: SNAP_LABEL[s.kind][1] })} ${s.targetLabel}`);
  };

  const onDblClick = (e: MapLayerMouseEvent) => {
    if (vertices.length > 0) {
      e.preventDefault();
      finishShape();
    }
  };

  // ── Commands ────────────────────────────────────────────────────────────
  const deleteSelection = useCallback(() => {
    const doomed = selected.filter(isEditable);
    if (doomed.length === 0) return;
    push(deleteFeatures(doomed));
    setSelection([]);
    setAnnounce(t('plan.cmd.deleted', { defaultValue: '{{count}} deleted', count: doomed.length }));
  }, [selected, isEditable, push, setSelection, t]);

  const fitTo = useCallback(
    (features: Iterable<PlanFeature>, padding = 48) => {
      const map = mapRef.current;
      const bb = featuresBBox(features);
      if (!map || !bb) return;
      const pad = Math.max(bb[2] - bb[0], bb[3] - bb[1]) < 1 ? 10 : 0;
      const corners: GridXY[] = [
        [bb[0] - pad, bb[1] - pad],
        [bb[2] + pad, bb[1] - pad],
        [bb[2] + pad, bb[3] + pad],
        [bb[0] - pad, bb[3] + pad],
      ];
      const ll = bboxOf(corners.map((c) => vt.toView(c)))!;
      map.fitBounds(
        [
          [ll[0], ll[1]],
          [ll[2], ll[3]],
        ],
        // The north arrow and scale bar sit bottom-left: keep fitted points clear of them.
        { padding: { top: padding, right: padding, left: padding, bottom: padding + DECOR_CLEARANCE_PX }, bearing: vt.gridNorthBearing, duration: matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : 400, maxZoom: 22 },
      );
    },
    [vt],
  );

  const zoomExtents = useCallback(() => fitTo(allFeatures), [fitTo, allFeatures]);

  const save = useCallback(async () => {
    const st = usePlanEditStore.getState();
    const ops = st.ops();
    if (ops.length === 0 || st.saving) return;
    st.setSaving(true);
    try {
      if (props.onSave) await props.onSave(ops);
      else await planApi.save(projectId, ops);
      usePlanEditStore.getState().markSaved(new Date().toISOString());
      await qc.invalidateQueries({ queryKey: planKeys.all(projectId) });
      addToast({ type: 'success', title: t('plan.saved', { defaultValue: 'Plan saved' }) });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const d = (err.body as { detail?: ConflictDetail } | undefined)?.detail;
        addToast({
          type: 'error',
          title: t('plan.conflict', {
            defaultValue: '{{who}} changed this on {{when}}. Reload to see their version; your edits stay until you discard them.',
            who: d?.author_name || t('plan.history.someone', { defaultValue: 'someone' }),
            when: d?.changed_at ? new Date(d.changed_at).toLocaleString() : '',
          }),
        });
      } else {
        addToast({ type: 'error', title: t('plan.save_failed', { defaultValue: 'The plan could not be saved' }) });
      }
    } finally {
      usePlanEditStore.getState().setSaving(false);
    }
  }, [props, projectId, qc, addToast, t]);

  const copyMeasure = useCallback(() => {
    if (measure) void navigator.clipboard?.writeText(measure.text);
  }, [measure]);

  // ── Keyboard ────────────────────────────────────────────────────────────
  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (isTyping(e.target)) return;
    const chord = chordOf(e.nativeEvent);
    const byShortcut = tools.find((x) => x.shortcut && x.shortcut === chord);
    const handled = (() => {
      if (byShortcut) {
        pickTool(byShortcut.id);
        setAnnounce(t(byShortcut.labelKey, { defaultValue: byShortcut.defaultLabel }));
        return true;
      }
      switch (chord) {
        case 'Escape':
          if (vertices.length > 0) setVertices([]);
          else if (drag) setDrag(null);
          else if (selection.size > 0) setSelection([]);
          else if (tool.id !== SELECT_TOOL) pickTool(SELECT_TOOL);
          return true;
        case 'Enter':
          if (vertices.length > 0) finishShape();
          return true;
        case 'Backspace':
          if (vertices.length > 0) {
            setVertices(vertices.slice(0, -1));
            return true;
          }
          if (editable) deleteSelection();
          return true;
        case 'Delete':
          if (editable) deleteSelection();
          return true;
        case 'Mod+Z':
          if (editable) undoOne();
          return true;
        case 'Mod+Shift+Z':
        case 'Mod+Y':
          if (editable) redoOne();
          return true;
        case 'Mod+S':
          if (editable) void save();
          return true;
        case 'Mod+A':
          setSelection(selectable.map((f) => f.id));
          return true;
        case 'Mod+C':
          if (measure) {
            copyMeasure();
            return true;
          }
          return false;
        case 'F3':
          setSnapSettings((s) => toggleAll(s));
          return true;
        case 'Z':
          zoomExtents();
          return true;
        case '?':
          setHelp(true);
          return true;
        case ' ':
          setSpaceHeld(true);
          return true;
        default:
          if (drawing && /^[0-9.\-]$/.test(e.key)) {
            setFocusToken((n) => n + 1);
            return false;
          }
          return false;
      }
    })();
    if (handled) {
      e.preventDefault();
      e.stopPropagation();
    }
  };
  const onKeyUp = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === ' ') setSpaceHeld(false);
  };

  // Palette entries (Ctrl+K): tools and view commands while this canvas is mounted.
  const runRef = useRef({ pickTool, zoomExtents, save, setHelp });
  runRef.current = { pickTool, zoomExtents, save, setHelp };
  useEffect(() => {
    const defs = [
      ...tools.map((x) => ({
        id: `plan.tool.${x.id}`,
        titleKey: x.labelKey,
        defaultTitle: x.defaultLabel,
        group: 'view' as const,
        run: () => runRef.current.pickTool(x.id),
      })),
      { id: 'plan.zoom_extents', titleKey: 'plan.keys.extents', defaultTitle: 'Zoom to everything', group: 'view' as const, run: () => runRef.current.zoomExtents() },
      { id: 'plan.shortcuts', titleKey: 'plan.keys.title', defaultTitle: 'Keyboard shortcuts', group: 'view' as const, run: () => runRef.current.setHelp(true) },
      ...(editable ? [{ id: 'plan.save', titleKey: 'plan.keys.save', defaultTitle: 'Save', group: 'project' as const, run: () => void runRef.current.save() }] : []),
    ];
    return registerActions('plan', defs);
  }, [tools, editable]);

  // ── Live checks ─────────────────────────────────────────────────────────
  const findings = useMemo<LiveFinding[]>(() => {
    const codedPoints = (layers.find((l) => l.id === 'points')?.features ?? [])
      .filter((f) => f.geometry.type === 'Point')
      .map((f) => {
        const c = f.geometry.coordinates as number[];
        return { id: f.id, e: c[0]!, n: c[1]!, code: String(f.properties.code ?? ''), sourceLine: (f.properties.source_line as number | null) ?? null };
      });
    const sketch = [...working.values()];
    return [...runLiveChecks({ features: sketch, codes: library, points: codedPoints }), ...(props.findings ?? [])];
  }, [layers, working, library, props.findings]);

  const focusFinding = useCallback(
    (f: LiveFinding) => {
      const target = f.featureId ? featureById.get(f.featureId) : null;
      if (target) {
        setSelection([target.id]);
        fitTo([target], 120);
      }
    },
    [featureById, fitTo, setSelection],
  );

  // The screen's own list can hold the selection: follow it and frame what it picked.
  const selKey = props.selectedIds?.join('|');
  useEffect(() => {
    if (selKey === undefined) return;
    const ids = (props.selectedIds ?? []).filter((id) => featureById.has(id));
    const cur = usePlanEditStore.getState().selection;
    if (cur.size === ids.length && ids.every((id) => cur.has(id))) return;
    setSelectionStore(ids);
    if (ids.length > 0) fitTo(ids.map((id) => featureById.get(id)!), 120);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selKey]);

  // ── Focus feature at start ──────────────────────────────────────────────
  const fitted = useRef(false);
  const onLoad = () => {
    const map = mapRef.current?.getMap();
    if (map) {
      map.on('styleimagemissing', (ev: { id: string }) => {
        const name = ev.id.replace(/^oe-sym-/, '') as SymbolName;
        if (!ev.id.startsWith('oe-sym-') || !(SYMBOLS as readonly string[]).includes(name) || map.hasImage(ev.id)) return;
        const img = symbolImage(name);
        if (img) map.addImage(ev.id, img, { sdf: true, pixelRatio: 2 });
      });
    }
    readView();
  };
  useEffect(() => {
    if (fitted.current || !mapRef.current || allFeatures.length === 0 || vtQuery.isLoading) return;
    fitted.current = true;
    const focus = props.focusFeatureId ? featureById.get(props.focusFeatureId) : null;
    if (focus) {
      setSelection([focus.id]);
      fitTo([focus], 160);
    } else zoomExtents();
  });

  const readView = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const b = map.getBounds();
    const corners: [number, number][] = [
      [b.getWest(), b.getSouth()],
      [b.getEast(), b.getSouth()],
      [b.getEast(), b.getNorth()],
      [b.getWest(), b.getNorth()],
    ];
    setView({ zoom: map.getZoom(), lat: map.getCenter().lat, bearing: map.getBearing(), bbox: gridBBoxOfView(corners, vt.toGrid) });
  }, [vt]);

  // ── Sources ─────────────────────────────────────────────────────────────
  const zDecimals = conventions.precision === 'cm' || conventions.precision === '0.01ft' ? 2 : 3;
  const dragPreview = useMemo(() => {
    if (!drag || drag.kind === 'box') return null;
    const out = new globalThis.Map<string, PlanFeature>();
    if (drag.kind === 'move') {
      for (const id of drag.ids) {
        const f = featureById.get(id);
        if (f) out.set(id, translate(f, drag.at[0] - drag.from[0], drag.at[1] - drag.from[1]));
      }
    } else {
      const f = featureById.get(drag.fid);
      if (f) out.set(f.id, drag.kind === 'vertex' ? moveVertex(f, drag.index, drag.at) : insertVertex(f, drag.index, drag.at));
    }
    return out;
  }, [drag, featureById]);

  const sources = useMemo(
    () =>
      [...layers]
        .sort((a, b) => a.order - b.order)
        .map((l) => {
          const st = viewOf(l);
          const features = dragPreview ? l.features.map((f) => dragPreview.get(f.id) ?? f) : l.features;
          const data: FeatureCollection = l.viewFeatures
            ? l.viewFeatures
            : toCollection(features, vt.toView, { palette, library, priority: l.labelPriority ?? 40, zDecimals });
          const style = l.style ?? defaultStyle(l.id, { palette, labels, opacity: st.opacity });
          return { l, st, data, style };
        }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layers, layerState, vt, palette, library, labels, zDecimals, dragPreview],
  );

  const overlay = useMemo((): FeatureCollection => {
    const out: Feature[] = [];
    const shown = (f: PlanFeature) => dragPreview?.get(f.id) ?? f;
    if (hover && !selection.has(hover)) {
      const f = featureById.get(hover);
      if (f) out.push(overlayFeature('hover', shown(f).geometry, vt.toView));
    }
    for (const f0 of selected) {
      const f = shown(f0);
      out.push(overlayFeature('selected', f.geometry, vt.toView));
    }
    for (const f0 of selected.slice(0, MAX_HANDLE_FEATURES)) {
      if (!isEditable(f0) || f0.geometry.type === 'Point') continue;
      const f = shown(f0);
      const v = featureVertices(f);
      for (const i of handleIndices(f)) {
        const on = drag && drag.kind === 'vertex' && drag.fid === f.id && drag.index === i;
        out.push(overlayFeature(on ? 'handle-on' : 'handle', { type: 'Point', coordinates: v[i]! }, vt.toView));
      }
      if (!drag) for (const m of midHandles(f)) out.push(overlayFeature('mid', { type: 'Point', coordinates: m.at }, vt.toView));
    }
    for (const f of findings) if (f.at) out.push(overlayFeature('finding', { type: 'Point', coordinates: f.at }, vt.toView));
    if (drag?.kind === 'box') {
      const [a, b] = [drag.from, drag.at];
      out.push(
        overlayFeature('box', { type: 'Polygon', coordinates: [[a, [b[0], a[1]], b, [a[0], b[1]], a]] }, vt.toView, { crossing: drag.crossing ? 1 : 0 }),
      );
    }
    return { type: 'FeatureCollection', features: out };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hover, selection, selected, featureById, dragPreview, drag, findings, vt, layerState]);

  const preview = useMemo((): FeatureCollection => {
    const pts = vertices.length > 0 ? (cursor && drawing ? [...vertices, cursor] : vertices) : measurePts;
    if (pts.length === 0) return EMPTY_FC;
    const feats: PlanFeature[] = [];
    const ring = tool.collects === 'ring' && pts.length >= 3;
    if (pts.length >= 2) {
      feats.push({
        id: 'pv',
        layer: 'measure',
        geometry: ring ? { type: 'Polygon', coordinates: [[...pts, pts[0]!]] } : { type: 'LineString', coordinates: pts },
        properties: {},
      });
    }
    pts.forEach((p, i) => feats.push({ id: `pv${i}`, layer: 'measure', geometry: { type: 'Point', coordinates: p }, properties: {} }));
    const extra = tool.preview ? tool.preview({ ...ctx, vertices: pts }) : tool.group === 'measure' ? legLabels(pts, conventions, ring) : [];
    if (ring) for (const at of ringSelfIntersections(pts)) feats.push({ id: `x${at[0]}`, layer: 'measure', geometry: { type: 'Point', coordinates: at }, properties: { text: '×' } });
    return toCollection([...feats, ...extra], vt.toView, { palette, library, priority: 0, zDecimals });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vertices, cursor, measurePts, tool, vt, palette, conventions]);

  const liveMeasure = useMemo(() => {
    if (tool.group !== 'measure' || vertices.length === 0 || !cursor) return measure;
    return measureOf(tool.id, [...vertices, cursor], conventions) ?? measure;
  }, [tool, vertices, cursor, conventions, measure]);

  const grid = useMemo(() => {
    if (basemap !== 'paper' || !view.bbox) return EMPTY_FC;
    return gridLines(view.bbox, gridStep(mpp), vt.toView);
  }, [basemap, view.bbox, mpp, vt]);

  const raster = props.raster;
  const rasterCorners = useMemo(() => {
    if (!raster) return null;
    const [e0, n0, e1, n1] = raster.bounds;
    return ([[e0, n1], [e1, n1], [e1, n0], [e0, n0]] as GridXY[]).map((c) => vt.toView(c)) as [[number, number], [number, number], [number, number], [number, number]];
  }, [raster, vt]);

  const mapStyle = useMemo(
    () => (basemap === 'map' && canMap ? buildBasemapStyle('streets', theme) : paperStyle(palette.bg)),
    [basemap, canMap, theme, palette.bg],
  );

  const layerProps = (prefix: string, s: { id: string; type: string; filter?: unknown[]; layout?: Record<string, unknown>; paint?: Record<string, unknown>; minzoom?: number; maxzoom?: number }, visible = true): LayerProps =>
    ({
      id: `${prefix}-${s.id}`,
      type: s.type,
      ...(s.filter ? { filter: s.filter } : {}),
      layout: { ...(s.layout ?? {}), visibility: visible ? 'visible' : 'none' },
      paint: s.paint ?? {},
      ...(s.minzoom != null ? { minzoom: s.minzoom } : {}),
      ...(s.maxzoom != null ? { maxzoom: s.maxzoom } : {}),
    }) as LayerProps;

  const empty = props.empty && allFeatures.length === 0 && !vtQuery.isLoading;
  const cursorStyle = spaceHeld || tool.id === PAN_TOOL ? (drag ? 'grabbing' : 'grab') : drawing ? 'crosshair' : hover ? 'pointer' : 'default';
  const precisionCtx = {
    conventions,
    last: vertices[vertices.length - 1] ?? null,
    lookup: (pid: string) => {
      const f = allFeatures.find((x) => x.geometry.type === 'Point' && String(x.properties.label ?? '').toUpperCase() === pid.trim().toUpperCase());
      return f && f.geometry.type === 'Point' ? ([f.geometry.coordinates[0], f.geometry.coordinates[1]] as GridXY) : null;
    },
    csf,
  };

  return (
    <div
      ref={rootRef}
      className={`relative flex flex-col overflow-hidden rounded-lg border border-border-light bg-surface-primary ${heightClass}`}
      data-testid={testId}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      aria-label={t('plan.canvas', { defaultValue: 'Plan' })}
      aria-describedby={`${testId}-hint`}
    >
      <p id={`${testId}-hint`} className="sr-only">
        {t('plan.canvas_hint', { defaultValue: 'Press ? for keyboard shortcuts. Tool keys work while the plan has focus.' })}
      </p>
      <div className="sr-only" aria-live="polite">
        {announce}
      </div>

      {/* Options bar */}
      <div className={OPTIONS_BAR_CLASS} data-testid="plan-options">
        <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto py-1 [scrollbar-width:thin]" data-testid="plan-options-scroll">
          <span className="shrink-0 whitespace-nowrap text-sm font-semibold text-content-primary">{t(tool.labelKey, { defaultValue: tool.defaultLabel })}</span>
          <span className="h-5 border-s border-border-light" aria-hidden />
          <div className="flex shrink-0 items-center gap-0.5" role="group" aria-label={t('plan.snap.title', { defaultValue: 'Snap' })}>
            <button
              type="button"
              onClick={() => setSnapSettings((s) => toggleAll(s))}
              aria-pressed={snapSettings.enabled}
              className={`h-8 rounded-md px-2 text-xs font-medium ${snapSettings.enabled ? 'bg-oe-blue/10 text-oe-blue-text' : 'text-content-tertiary hover:bg-surface-secondary'}`}
              title={t('plan.keys.snap', { defaultValue: 'Snap on or off' }) + ' (F3)'}
              data-testid="plan-snap-toggle"
            >
              {t('plan.snap.title', { defaultValue: 'Snap' })}
            </button>
            {SNAP_KINDS.map((k: SnapKind) => (
              <button
                key={k}
                type="button"
                onClick={() => setSnapSettings((s) => setMode(s, k, !s.modes[k]))}
                aria-pressed={snapSettings.modes[k]}
                disabled={!snapSettings.enabled}
                title={t(SNAP_LABEL[k][0], { defaultValue: SNAP_LABEL[k][1] })}
                aria-label={t(SNAP_LABEL[k][0], { defaultValue: SNAP_LABEL[k][1] })}
                className={`flex h-8 w-8 items-center justify-center rounded-md disabled:opacity-40 ${
                  snapSettings.modes[k] ? 'text-oe-blue-text' : 'text-content-quaternary hover:bg-surface-secondary'
                }`}
              >
                <SnapIcon kind={k} />
              </button>
            ))}
          </div>
          {drawing && (
            <>
              <span className="h-5 border-s border-border-light" aria-hidden />
              <PrecisionBar ctx={precisionCtx} onPoint={addVertex} focusToken={focusToken} />
            </>
          )}
          {tool.options?.(ctx)}
        </div>
        <div className="ms-auto flex shrink-0 items-center gap-1">
          {editable && (
            <>
              <button type="button" onClick={undoOne} disabled={!canUndo} className="flex h-9 w-9 items-center justify-center rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40" aria-label={t('plan.keys.undo', { defaultValue: 'Undo' })} title={`${t('plan.keys.undo', { defaultValue: 'Undo' })} (Ctrl+Z)`} data-testid="plan-undo">
                <Undo2 size={16} aria-hidden />
              </button>
              <button type="button" onClick={redoOne} disabled={!canRedo} className="flex h-9 w-9 items-center justify-center rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40" aria-label={t('plan.keys.redo', { defaultValue: 'Redo' })} title={`${t('plan.keys.redo', { defaultValue: 'Redo' })} (Ctrl+Shift+Z)`} data-testid="plan-redo">
                <Redo2 size={16} aria-hidden />
              </button>
              <button
                type="button"
                onClick={() => void save()}
                disabled={!dirty || saving}
                className="inline-flex h-9 items-center gap-1.5 rounded-md bg-oe-blue px-3 text-sm font-medium text-content-inverse hover:bg-oe-blue-hover disabled:opacity-40"
                data-testid="plan-save"
              >
                <Save size={14} aria-hidden />
                {saving ? t('plan.saving', { defaultValue: 'Saving' }) : t('plan.keys.save', { defaultValue: 'Save' })}
              </button>
            </>
          )}
          {props.toolbarSlot}
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1" style={{ cursor: cursorStyle }}>
          <Map
            locale={mapLocale}
            ref={mapRef}
            mapStyle={mapStyle}
            initialViewState={{ longitude: 0, latitude: 0, zoom: 2 }}
            maxPitch={0}
            pitchWithRotate={false}
            dragRotate={false}
            touchPitch={false}
            doubleClickZoom={false}
            boxZoom={false}
            dragPan={spaceHeld || picking || tool.id === PAN_TOOL || (tool.id !== SELECT_TOOL && !drag)}
            cursor={cursorStyle}
            attributionControl={basemap === 'map' ? { compact: true } : false}
            onLoad={onLoad}
            onMoveEnd={readView}
            onMouseMove={onMouseMove}
            onMouseDown={onMouseDown}
            onMouseUp={onMouseUp}
            onMouseOut={() => {
              setCursor(null);
              setScreen(null);
              setHover(null);
            }}
            onClick={onClick}
            onDblClick={onDblClick}
            style={{ position: 'absolute', inset: 0 }}
          >
            <Source id="plan-grid" type="geojson" data={grid}>
              <Layer id="plan-grid-minor" type="line" filter={['==', ['get', 'major'], 0]} paint={{ 'line-color': palette.grid, 'line-width': 1 }} />
              <Layer id="plan-grid-major" type="line" filter={['==', ['get', 'major'], 1]} paint={{ 'line-color': palette['grid-major'], 'line-width': 1 }} />
            </Source>
            {raster && rasterCorners && (
              <Source id="plan-raster" type="image" url={raster.dataUrl} coordinates={rasterCorners}>
                <Layer id="plan-raster-layer" type="raster" paint={{ 'raster-opacity': 0.9, 'raster-fade-duration': 0 }} />
              </Source>
            )}
            {sources.map(({ l, st, data, style }) => (
              <Source key={l.id} id={`plan-src-${l.id}`} type="geojson" data={data}>
                {style.map((s) => (
                  <Layer key={s.id} {...layerProps(`plan-${l.id}`, s, st.visible)} />
                ))}
              </Source>
            ))}
            <Source id="plan-preview" type="geojson" data={preview}>
              {defaultStyle('measure', { palette, labels, opacity: 1 }).map((s) => (
                <Layer key={s.id} {...layerProps('plan-preview', s)} />
              ))}
            </Source>
            <Source id="plan-overlay" type="geojson" data={overlay}>
              {overlayStyle(palette).map((s) => (
                <Layer key={s.id} {...layerProps('plan-overlay', s)} />
              ))}
            </Source>
          </Map>

          {snapHit && screen && (
            <SnapCursor
              kind={snapHit.kind}
              x={screen.x}
              y={screen.y}
              label={`${t(SNAP_LABEL[snapHit.kind][0], { defaultValue: SNAP_LABEL[snapHit.kind][1] })}${snapHit.targetLabel ? ` ${snapHit.targetLabel}` : ''}`}
            />
          )}

          <div className="absolute start-3 top-3 z-10">
            <ToolRail tools={tools} active={tool.id} onPick={pickTool} />
          </div>

          <div className="absolute end-3 top-3 z-10 flex flex-col items-end gap-2">
            <div className="flex gap-1 rounded-xl border border-border-light bg-surface-elevated/95 p-1 shadow-md backdrop-blur">
              <button type="button" onClick={() => setPanel((p) => (p === 'layers' ? 'none' : 'layers'))} aria-expanded={panel === 'layers'} className={`flex h-11 w-11 items-center justify-center rounded-lg ${panel === 'layers' ? 'bg-oe-blue/10 text-oe-blue-text' : 'text-content-secondary hover:bg-surface-secondary'}`} aria-label={t('plan.layers', { defaultValue: 'Layers' })} title={t('plan.layers', { defaultValue: 'Layers' })} data-testid="plan-layers-button">
                <Layers size={18} aria-hidden />
              </button>
              <button type="button" onClick={zoomExtents} className="flex h-11 w-11 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary" aria-label={t('plan.keys.extents', { defaultValue: 'Zoom to everything' })} title={`${t('plan.keys.extents', { defaultValue: 'Zoom to everything' })} (Z)`}>
                <Maximize2 size={18} aria-hidden />
              </button>
              <button type="button" onClick={() => setInspectorOpen((v) => !v)} aria-pressed={inspectorOpen} className="hidden h-11 w-11 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary md:flex" aria-label={t('plan.inspector.toggle', { defaultValue: 'Inspector' })} title={t('plan.inspector.toggle', { defaultValue: 'Inspector' })}>
                <PanelRight size={18} aria-hidden />
              </button>
              <button type="button" onClick={() => setHelp(true)} className="flex h-11 w-11 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary" aria-label={t('plan.keys.title', { defaultValue: 'Keyboard shortcuts' })} title={`${t('plan.keys.title', { defaultValue: 'Keyboard shortcuts' })} (?)`}>
                <Keyboard size={18} aria-hidden />
              </button>
            </div>
            {panel === 'layers' && (
              <div className="max-h-[60vh] overflow-y-auto rounded-xl border border-border-light bg-surface-elevated shadow-lg">
                <LayerPanel
                  layers={layers}
                  state={Object.fromEntries(layers.map((l) => [l.id, viewOf(l)]))}
                  onChange={(id, next) => setLayerState((s) => ({ ...s, [id]: next }))}
                  basemap={basemap}
                  onBasemap={setBasemap}
                  canMap={canMap}
                  labels={labels}
                  onLabels={setLabels}
                  activeLayer={activeLayer}
                  onActiveLayer={editable ? setActiveLayer : undefined}
                />
              </div>
            )}
          </div>

          <div className="pointer-events-none absolute bottom-3 start-3 z-10 flex items-end gap-3" data-testid="plan-decor">
            <NorthArrow bearing={view.bearing} gridNorth={vt.gridNorthBearing} onReset={() => mapRef.current?.rotateTo(vt.gridNorthBearing)} />
            <ScaleBar mpp={mpp} conventions={conventions} />
          </div>

          {picking && props.pickHint && (
            <div className="pointer-events-none absolute start-1/2 top-3 z-10 -translate-x-1/2 rounded-lg border border-border-light bg-surface-elevated/95 px-3 py-1.5 text-xs text-content-primary shadow-md" data-testid="plan-pick-hint">
              {props.pickHint}
            </div>
          )}
          {props.overlay}

          {empty && props.empty && (
            <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 p-6 text-center" data-testid="plan-empty">
              <p className="max-w-sm text-sm text-content-secondary">{props.empty.title}</p>
              <div className="pointer-events-auto">{props.empty.action}</div>
            </div>
          )}
        </div>

        {inspectorOpen && (
          <aside className="hidden w-80 shrink-0 border-s border-border-light bg-surface-elevated md:block" aria-label={t('plan.inspector.toggle', { defaultValue: 'Inspector' })}>
            <Inspector
              projectId={projectId}
              conventions={conventions}
              measure={liveMeasure}
              selected={selected}
              editable={editable && selected.length === 1 && isEditable(selected[0]!)}
              onEdit={(before, after) => push(updateFeature(before, after, { labelKey: 'plan.cmd.properties', defaultLabel: 'Properties changed' }))}
              findings={findings}
              onFocusFinding={focusFinding}
              slot={props.inspectorSlot}
            />
          </aside>
        )}
      </div>

      <StatusBar
        cursor={cursor}
        snap={snapHit}
        snapOn={snapSettings.enabled}
        conventions={conventions}
        scale={view.bbox ? scaleDenominator(mpp) : null}
        csf={csf}
        crsName={vt.crsName}
        residualMm={vt.kind === 'polynomial' ? vt.residualMm : null}
        selected={selection.size}
        dirty={dirty}
      />

      {help && <ShortcutHelp tools={tools} onClose={() => setHelp(false)} />}
    </div>
  );
}

