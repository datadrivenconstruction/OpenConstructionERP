// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A light SVG plan for the field book, alignment, stake and monitoring
 * screens: the same `PlanFeature`s and map tokens the plan canvas draws, fitted
 * to the features, with wheel zoom, drag pan, a north arrow and a scale bar.
 * Grid metres in, screen pixels out; north is up.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { planColour, type MapToken } from '../cartography';
import type { GridXY, PlanFeature } from '../types';
import { LINEAR_SYMBOL, fromMetres, toMetres, type PlanConventions } from '../units';

export type SketchShape = 'circle' | 'square' | 'diamond' | 'cross' | 'triangle' | 'none';

export interface SketchStyle {
  stroke?: MapToken;
  width?: number;
  dash?: string;
  fill?: MapToken;
  fillOpacity?: number;
  shape?: SketchShape;
  size?: number;
  label?: string;
  /** Label placement in px from the point. */
  labelDx?: number;
  labelDy?: number;
  labelToken?: MapToken;
  /** Drawn on top of everything else. */
  top?: boolean;
}

export interface PlanSketchProps {
  features: readonly PlanFeature[];
  styleFor: (f: PlanFeature) => SketchStyle | null;
  conventions: Pick<PlanConventions, 'linearUnit' | 'precision'>;
  /** Features that set the initial view; defaults to all of them. */
  fitTo?: readonly PlanFeature[];
  selectedId?: string | null;
  onPick?: (f: PlanFeature) => void;
  /** A click on empty plan, in grid metres. */
  onPlanClick?: (p: GridXY) => void;
  /** Pointer position in grid metres, null when it leaves. */
  onHover?: (p: GridXY | null) => void;
  heightClass?: string;
  /** Overlays in the plan's corners (legend, scale switch). */
  children?: ReactNode;
  cursor?: 'crosshair' | 'default';
  testId?: string;
}

function coordsOf(f: PlanFeature): GridXY[] {
  const g = f.geometry;
  if (g.type === 'Point') return [g.coordinates as GridXY];
  if (g.type === 'LineString') return g.coordinates as GridXY[];
  if (g.type === 'Polygon') return (g.coordinates as GridXY[][]).flat();
  return [];
}

function niceLength(m: number): number {
  const p = 10 ** Math.floor(Math.log10(m));
  const k = m / p;
  return (k >= 5 ? 5 : k >= 2 ? 2 : 1) * p;
}

interface View {
  cx: number;
  cy: number;
  /** Pixels per metre. */
  k: number;
}

export function PlanSketch({
  features,
  styleFor,
  conventions,
  fitTo,
  selectedId,
  onPick,
  onPlanClick,
  onHover,
  heightClass = 'h-[420px]',
  children,
  cursor = 'default',
  testId,
}: PlanSketchProps) {
  const { t } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 640, h: 420 });
  const [view, setView] = useState<View | null>(null);
  const drag = useRef<{ x: number; y: number; v: View; moved: boolean } | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([e]) => {
      if (e) setSize({ w: Math.max(e.contentRect.width, 50), h: Math.max(e.contentRect.height, 50) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fitKey = (fitTo ?? features).map((f) => f.id).join('|');
  const fitted = useMemo<View>(() => {
    const pts = (fitTo ?? features).flatMap(coordsOf);
    if (!pts.length) return { cx: 0, cy: 0, k: 1 };
    const es = pts.map((p) => p[0]);
    const ns = pts.map((p) => p[1]);
    const [e0, e1, n0, n1] = [Math.min(...es), Math.max(...es), Math.min(...ns), Math.max(...ns)];
    const span = Math.max(e1 - e0, n1 - n0, 1);
    const k = Math.min((size.w - 64) / Math.max(e1 - e0, span * 0.2), (size.h - 64) / Math.max(n1 - n0, span * 0.2));
    return { cx: (e0 + e1) / 2, cy: (n0 + n1) / 2, k };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, size.w, size.h]);
  useEffect(() => setView(null), [fitKey]);
  const v = view ?? fitted;

  const toPx = useCallback((p: GridXY): [number, number] => [size.w / 2 + (p[0] - v.cx) * v.k, size.h / 2 - (p[1] - v.cy) * v.k], [v, size]);
  const toGrid = useCallback(
    (x: number, y: number): GridXY => [v.cx + (x - size.w / 2) / v.k, v.cy - (y - size.h / 2) / v.k],
    [v, size],
  );
  const local = (e: { clientX: number; clientY: number }) => {
    const r = box.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top] as const;
  };

  const onWheel = (e: React.WheelEvent) => {
    const [x, y] = local(e);
    const g = toGrid(x, y);
    const k = Math.min(Math.max(v.k * (e.deltaY < 0 ? 1.2 : 1 / 1.2), fitted.k / 50), fitted.k * 5000);
    setView({ k, cx: g[0] - (x - size.w / 2) / k, cy: g[1] + (y - size.h / 2) / k });
  };

  const sorted = useMemo(() => {
    const styled = features.map((f) => ({ f, s: styleFor(f) })).filter((x): x is { f: PlanFeature; s: SketchStyle } => !!x.s);
    const rank = (x: { f: PlanFeature; s: SketchStyle }) => (x.s.top ? 3 : x.f.geometry.type === 'Point' ? 2 : x.f.geometry.type === 'LineString' ? 1 : 0);
    return styled.sort((a, b) => rank(a) - rank(b));
  }, [features, styleFor]);

  const barShown = niceLength(fromMetres(110 / v.k, conventions.linearUnit));
  const bar = toMetres(barShown, conventions.linearUnit);
  const shapeAt = (shape: SketchShape, x: number, y: number, r: number) => {
    switch (shape) {
      case 'square':
        return `M${x - r},${y - r}h${2 * r}v${2 * r}h${-2 * r}Z`;
      case 'diamond':
        return `M${x},${y - r * 1.3}L${x + r * 1.3},${y}L${x},${y + r * 1.3}L${x - r * 1.3},${y}Z`;
      case 'triangle':
        return `M${x},${y - r * 1.3}L${x + r * 1.15},${y + r * 0.75}L${x - r * 1.15},${y + r * 0.75}Z`;
      case 'cross':
        return `M${x - r},${y - r}L${x + r},${y + r}M${x - r},${y + r}L${x + r},${y - r}`;
      default:
        return `M${x - r},${y}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0`;
    }
  };

  return (
    <div
      ref={box}
      className={`relative overflow-hidden rounded-xl border border-border-light ${heightClass}`}
      style={{ background: planColour('bg'), cursor: drag.current?.moved ? 'grabbing' : cursor }}
      data-testid={testId}
      onWheel={onWheel}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        drag.current = { x: e.clientX, y: e.clientY, v, moved: false };
      }}
      onPointerMove={(e) => {
        const [x, y] = local(e);
        onHover?.(toGrid(x, y));
        const d = drag.current;
        if (!d) return;
        const dx = e.clientX - d.x;
        const dy = e.clientY - d.y;
        if (!d.moved && Math.hypot(dx, dy) < 4) return;
        d.moved = true;
        setView({ k: d.v.k, cx: d.v.cx - dx / d.v.k, cy: d.v.cy + dy / d.v.k });
      }}
      onPointerUp={(e) => {
        const d = drag.current;
        drag.current = null;
        if (d?.moved || !onPlanClick) return;
        if ((e.target as Element).closest?.('[data-pick]')) return;
        const [x, y] = local(e);
        onPlanClick(toGrid(x, y));
      }}
      onPointerLeave={() => {
        drag.current = null;
        onHover?.(null);
      }}
      onDoubleClick={() => setView(null)}
    >
      <svg width={size.w} height={size.h} className="block select-none" role="img" aria-label={t('plan.sketch.aria', { defaultValue: 'Plan sketch, north up' })}>
        {sorted.map(({ f, s }) => {
          const sel = f.id === selectedId;
          const stroke = s.stroke ? planColour(s.stroke) : 'none';
          const pickable = !!onPick;
          const pick = onPick ? { 'data-pick': '1', onClick: () => onPick(f), style: { cursor: 'pointer' } } : {};
          const g = f.geometry;
          if (g.type === 'Point') {
            const [x, y] = toPx(g.coordinates as GridXY);
            const r = (s.size ?? 5) + (sel ? 2 : 0);
            const shape = s.shape ?? 'circle';
            return (
              <g key={f.id} {...pick}>
                {shape !== 'none' && (
                  <path
                    d={shapeAt(shape, x, y, r)}
                    fill={shape === 'cross' ? 'none' : s.fill ? planColour(s.fill) : planColour('bg')}
                    stroke={sel ? planColour('accent') : s.stroke ? stroke : planColour('ink')}
                    strokeWidth={shape === 'cross' ? (s.width ?? 2) : sel ? 2.5 : (s.width ?? 1.5)}
                    strokeLinecap="round"
                  />
                )}
                {s.label && (
                  <text
                    x={x + (s.labelDx ?? 8)}
                    y={y + (s.labelDy ?? -8)}
                    className="text-xs"
                    fill={planColour(s.labelToken ?? 'ink')}
                    stroke={planColour('halo')}
                    strokeWidth={3}
                    paintOrder="stroke"
                  >
                    {s.label}
                  </text>
                )}
                {pickable && <circle cx={x} cy={y} r={Math.max(r + 4, 10)} fill="transparent" />}
              </g>
            );
          }
          if (g.type === 'LineString') {
            const pts = (g.coordinates as GridXY[]).map(toPx);
            const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
            const mid = pts[Math.floor((pts.length - 1) / 2)];
            return (
              <g key={f.id} {...pick}>
                <path d={d} fill="none" stroke={stroke} strokeWidth={(s.width ?? 1.5) + (sel ? 1.5 : 0)} strokeDasharray={s.dash} strokeLinecap="round" strokeLinejoin="round" />
                {s.label && mid && (
                  <text x={mid[0] + (s.labelDx ?? 6)} y={mid[1] + (s.labelDy ?? -6)} className="text-xs" fill={planColour(s.labelToken ?? 'ink')} stroke={planColour('halo')} strokeWidth={3} paintOrder="stroke">
                    {s.label}
                  </text>
                )}
                {pickable && <path d={d} fill="none" stroke="transparent" strokeWidth={12} />}
              </g>
            );
          }
          if (g.type === 'Polygon') {
            const d = (g.coordinates as GridXY[][])
              .map((ring) => ring.map(toPx).map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('') + 'Z')
              .join('');
            return <path key={f.id} d={d} fill={s.fill ? planColour(s.fill) : 'none'} fillOpacity={s.fillOpacity ?? 1} stroke={stroke} strokeWidth={s.width ?? 1} {...pick} />;
          }
          return null;
        })}
        {/* North arrow */}
        <g transform={`translate(${size.w - 28},30)`} aria-hidden>
          <path d="M0,-14L6,6L0,2L-6,6Z" fill={planColour('ink')} />
          <text y={20} textAnchor="middle" className="text-2xs" fill={planColour('ink')}>
            {t('plan.sketch.north', { defaultValue: 'N' })}
          </text>
        </g>
        {/* Scale bar */}
        <g transform={`translate(16,${size.h - 18})`} aria-hidden>
          <path d={`M0,-5V0H${bar * v.k}V-5`} fill="none" stroke={planColour('ink')} strokeWidth={1.5} />
          <text x={bar * v.k + 6} y={0} className="text-2xs" fill={planColour('ink')} stroke={planColour('halo')} strokeWidth={3} paintOrder="stroke">
            {`${barShown} ${LINEAR_SYMBOL[conventions.linearUnit]}`}
          </text>
        </g>
      </svg>
      {children}
    </div>
  );
}
