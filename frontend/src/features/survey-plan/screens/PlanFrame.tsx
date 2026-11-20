// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The frame every P2 screen renders its layers into. It draws the plan with
 * the shared canvas when one is provided (`canvas`), and otherwise as a light
 * grid-true SVG view (wheel to zoom, drag to pan, click to select), so the
 * screens, checks, print and DXF work on their own. Findings are marked on
 * the plan and listed beside it; clicking one selects its feature.
 */

import { useMemo, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CircleAlert, Info } from 'lucide-react';
import type { GridXYZ, PlanCanvasProps, PlanFeature, PlanLayerSpec } from '../types';
import type { LiveFinding } from '../engine/liveChecks';
import { featuresBBox } from '../engine/geometry';
import { planColour, type MapToken } from '../cartography';

export interface PlanFrameProps {
  projectId: string;
  layers: PlanLayerSpec[];
  findings?: LiveFinding[];
  selected?: string | null;
  onSelect?: (featureId: string | null) => void;
  /** Controls at the top right (print, export, tools of the screen). */
  toolbar?: ReactNode;
  /** Panel under the findings (inspector of the screen). */
  side?: ReactNode;
  /** The shared plan canvas; the SVG view is used without it. */
  canvas?: ComponentType<PlanCanvasProps>;
  canvasProps?: Partial<PlanCanvasProps>;
  /** A raster under the layers (shaded relief), placed by its grid bounds [e0, n0, e1, n1]. */
  relief?: { dataUrl: string; bounds: [number, number, number, number] } | null;
  testId?: string;
}

const TOKEN: Record<string, MapToken> = {
  parcels: 'parcel', zones: 'zone', pads: 'surface', contours: 'topo', heat: 'neutral', breaklines: 'breakline',
  points: 'ink', control: 'ink', surfaces: 'surface', sketch: 'ink-2',
};

const sevIcon = { error: CircleAlert, warning: AlertTriangle, info: Info } as const;
const sevClass = { error: 'text-semantic-error', warning: 'text-amber-600', info: 'text-content-tertiary' } as const;

function path(pts: readonly GridXYZ[], closed: boolean): string {
  return pts.map((p, i) => `${i ? 'L' : 'M'}${p[0]} ${-p[1]}`).join('') + (closed ? 'Z' : '');
}

function colourOf(layer: PlanLayerSpec, f: PlanFeature): string {
  const c = f.properties.colour;
  if (typeof c === 'string' && c) return c;
  return planColour(TOKEN[layer.id] ?? 'ink');
}

export function PlanFrame({ projectId, layers, findings = [], selected, onSelect, toolbar, side, canvas: Canvas, canvasProps, relief, testId }: PlanFrameProps) {
  const { t } = useTranslation();
  const all = useMemo(() => layers.flatMap((l) => l.features), [layers]);
  const box = useMemo(() => {
    const b = featuresBBox(all);
    if (!relief) return b;
    const r = relief.bounds;
    return b ? ([Math.min(b[0], r[0]), Math.min(b[1], r[1]), Math.max(b[2], r[2]), Math.max(b[3], r[3])] as typeof b) : r;
  }, [all, relief]);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<[number, number]>([0, 0]);
  const drag = useRef<{ x: number; y: number; pan: [number, number] } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const sorted = useMemo(() => [...layers].sort((a, b) => a.order - b.order), [layers]);
  const pad = box ? Math.max(box[2] - box[0], box[3] - box[1]) * 0.06 + 1 : 0;
  const w = box ? (box[2] - box[0] + 2 * pad) / zoom : 1;
  const h = box ? (box[3] - box[1] + 2 * pad) / zoom : 1;
  const cx = box ? (box[0] + box[2]) / 2 + pan[0] : 0;
  const cy = box ? (box[1] + box[3]) / 2 + pan[1] : 0;
  const unit = Math.max(w, h) / 600;

  const flagged = new Set(findings.filter((f) => f.severity === 'error').map((f) => f.featureId));

  const view = Canvas ? (
    <Canvas projectId={projectId} layers={layers} onSelect={(ids) => onSelect?.(ids[0] ?? null)} heightClass="h-[520px]" {...canvasProps} />
  ) : box ? (
    <svg
      ref={svgRef}
      className="h-[520px] w-full cursor-grab touch-none select-none rounded-lg border border-border-light bg-[var(--oe-map-bg)]"
      viewBox={`${cx - w / 2} ${-cy - h / 2} ${w} ${h}`}
      role="img"
      aria-label={t('plan.parcel.view_label', { defaultValue: 'Plan view' })}
      onWheel={(e) => setZoom((z) => Math.min(Math.max(z * (e.deltaY < 0 ? 1.2 : 1 / 1.2), 0.5), 200))}
      onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, pan }; }}
      onPointerMove={(e) => {
        const d = drag.current;
        const el = svgRef.current;
        if (!d || !el) return;
        const k = w / el.clientWidth;
        setPan([d.pan[0] - (e.clientX - d.x) * k, d.pan[1] + (e.clientY - d.y) * k]);
      }}
      onPointerUp={() => { drag.current = null; }}
      onPointerLeave={() => { drag.current = null; }}
      data-testid={testId ? `${testId}-svg` : undefined}
    >
      {relief && (
        <image href={relief.dataUrl} x={relief.bounds[0]} y={-relief.bounds[3]} width={relief.bounds[2] - relief.bounds[0]}
          height={relief.bounds[3] - relief.bounds[1]} preserveAspectRatio="none" style={{ imageRendering: 'auto' }} />
      )}
      {sorted.map((layer) => (
        <g key={layer.id} data-layer={layer.id}>
          {layer.features.map((f) => {
            const c = colourOf(layer, f);
            const isSel = selected === f.id;
            const stroke = flagged.has(f.id) ? 'var(--oe-map-error)' : c;
            const sw = (isSel ? 3 : layer.id === 'contours' ? (f.properties.index ? 1.2 : 0.6) : 1.5) * unit;
            const g = f.geometry;
            const click = () => onSelect?.(f.id);
            if (g.type === 'Point') {
              return <circle key={f.id} cx={g.coordinates[0]} cy={-g.coordinates[1]} r={(isSel ? 5 : 3) * unit} fill={c} onClick={click} />;
            }
            if (g.type === 'LineString') {
              return <path key={f.id} d={path(g.coordinates, false)} fill="none" stroke={stroke} strokeWidth={sw} onClick={click} />;
            }
            const fill = typeof f.properties.fill === 'string' ? f.properties.fill : c;
            return (
              <path
                key={f.id}
                d={path(g.coordinates[0] ?? [], true)}
                fill={fill}
                fillOpacity={layer.id === 'heat' ? 0.75 : layer.id === 'parcels' ? 0.14 : 0.06}
                stroke={layer.id === 'heat' ? 'none' : stroke}
                strokeWidth={sw}
                strokeDasharray={layer.id === 'zones' ? `${6 * unit} ${4 * unit}` : undefined}
                onClick={click}
                data-feature={f.id}
              />
            );
          })}
        </g>
      ))}
      {sorted.flatMap((layer) =>
        layer.features
          .filter((f) => f.properties.label != null && f.properties.label !== '')
          .map((f) => {
            const vs = f.geometry.type === 'Point' ? [f.geometry.coordinates] : f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] ?? [] : f.geometry.coordinates;
            const b = featuresBBox([f]);
            if (!b || !vs.length) return null;
            const at = f.geometry.type === 'Point' ? [vs[0]![0] + 4 * unit, vs[0]![1] + 4 * unit] : [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
            return (
              <text key={`${f.id}:label`} x={at[0]} y={-at[1]!} fontSize={(layer.id === 'parcels' ? 13 : 10) * unit} textAnchor={f.geometry.type === 'Point' ? 'start' : 'middle'}
                className="fill-[var(--oe-map-ink)] font-medium" paintOrder="stroke" stroke="var(--oe-map-halo)" strokeWidth={3 * unit}>
                {String(f.properties.label)}
              </text>
            );
          }),
      )}
      {findings.filter((f) => f.at).map((f, i) => (
        <g key={`find:${i}`} transform={`translate(${f.at![0]} ${-f.at![1]})`} onClick={() => onSelect?.(f.featureId ?? null)}>
          <circle r={7 * unit} fill={f.severity === 'error' ? 'var(--oe-map-error)' : 'var(--oe-map-warning)'} fillOpacity={0.9} />
          <text y={3.5 * unit} fontSize={10 * unit} textAnchor="middle" className="fill-white font-semibold">!</text>
        </g>
      ))}
    </svg>
  ) : (
    <div className="flex h-[320px] items-center justify-center rounded-lg border border-dashed border-border-light text-sm text-content-secondary">
      {t('plan.parcel.empty', { defaultValue: 'Nothing on the plan yet' })}
    </div>
  );

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_320px]" data-testid={testId}>
      <div className="min-w-0 space-y-2">
        {toolbar && <div className="flex flex-wrap items-center justify-end gap-2">{toolbar}</div>}
        {view}
      </div>
      <aside className="space-y-3 text-sm">
        <section>
          <h3 className="mb-1 font-semibold text-content-primary">
            {t('plan.parcel.checks', { defaultValue: 'Checks' })}
            <span className="ml-2 text-xs font-normal text-content-tertiary">{findings.length}</span>
          </h3>
          {findings.length === 0 ? (
            <p className="text-xs text-content-secondary">{t('plan.parcel.checks_clean', { defaultValue: 'No problems found' })}</p>
          ) : (
            <ul className="max-h-64 space-y-1 overflow-auto" data-testid={testId ? `${testId}-findings` : undefined}>
              {findings.map((f, i) => {
                const Icon = sevIcon[f.severity];
                return (
                  <li key={i}>
                    <button type="button" className="flex w-full items-start gap-2 rounded px-1 py-0.5 text-left hover:bg-surface-secondary" onClick={() => onSelect?.(f.featureId ?? null)}>
                      <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${sevClass[f.severity]}`} aria-hidden />
                      <span className="text-xs">
                        <span className="mr-1 font-medium text-content-tertiary">{f.ruleId}</span>
                        {t(f.messageKey, { defaultValue: f.defaultMessage, ...(f.params ?? {}) })}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        {side}
      </aside>
    </div>
  );
}

export default PlanFrame;
