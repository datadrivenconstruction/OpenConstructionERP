// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Long section of the ground along a centreline, sampled from a project
 * surface by the surfaces module. Heights are exaggerated (stated on the
 * frame); hovering reports the chainage so the plan can mark the spot.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { planColour } from '../cartography';
import { niceStep, runs, sectionFrame, type SectionPoint } from '../engine/sections';
import { formatChainage, formatDistance, type PlanConventions } from '../units';
import { fmtFixed } from '@/shared/lib/formatters';

export interface LongSectionProps {
  points: readonly SectionPoint[];
  conventions: PlanConventions;
  labelEvery?: number;
  /** Vertical exaggeration asked for; the frame lowers it when the relief would not fit. */
  exaggeration?: number;
  /** Chainages of curve ends to mark (TC/CT). */
  marks?: readonly { ch: number; label: string }[];
  onHover?: (ch: number | null) => void;
  height?: number;
}

export function LongSection({ points, conventions, labelEvery = 100, exaggeration = 10, marks = [], onHover, height = 220 }: LongSectionProps) {
  const { t } = useTranslation();
  const ref = useRef<SVGSVGElement>(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState<SectionPoint | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([e]) => e && setW(Math.max(e.contentRect.width, 200)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [points.length > 0]);
  const f = useMemo(() => sectionFrame(points.map((p) => p.ch), points.map((p) => p.z), w, height, exaggeration, 32), [points, w, height, exaggeration]);
  const lines = useMemo(() => runs(points), [points]);
  const step = niceStep(f.z1 - f.z0, 4);
  const zTicks: number[] = [];
  for (let z = Math.ceil(f.z0 / step) * step; z <= f.z1 + 1e-9; z += step) zTicks.push(Number(z.toFixed(6)));
  const chTicks: number[] = [];
  for (let c = Math.ceil(f.x0 / labelEvery) * labelEvery; c <= f.x1 + 1e-9; c += labelEvery) chTicks.push(c);

  const move = (clientX: number) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r || !points.length) return;
    const x = clientX - r.left;
    let best = points[0]!;
    for (const p of points) if (Math.abs(f.sx(p.ch) - x) < Math.abs(f.sx(best.ch) - x)) best = p;
    setHover(best);
    onHover?.(best.ch);
  };

  if (!points.length) return null;
  return (
    <figure className="space-y-1" data-testid="long-section">
      <svg
        ref={ref}
        width="100%"
        height={height}
        className="block rounded-xl border border-border-light"
        style={{ background: planColour('bg') }}
        onPointerMove={(e) => move(e.clientX)}
        onPointerLeave={() => {
          setHover(null);
          onHover?.(null);
        }}
        role="img"
        aria-label={t('plan.section.long_aria', { defaultValue: 'Long section of the ground along the centreline' })}
      >
        {zTicks.map((z) => (
          <g key={`z${z}`}>
            <line x1={32} x2={w - 32} y1={f.sz(z)} y2={f.sz(z)} stroke={planColour('grid')} />
            <text x={4} y={f.sz(z) + 4} className="text-2xs" fill={planColour('ink-2')}>{formatDistance(z, conventions, false)}</text>
          </g>
        ))}
        {chTicks.map((c) => (
          <g key={`c${c}`}>
            <line x1={f.sx(c)} x2={f.sx(c)} y1={24} y2={height - 28} stroke={planColour('grid-major')} />
            <text x={f.sx(c)} y={height - 10} textAnchor="middle" className="text-2xs" fill={planColour('ink')}>{formatChainage(c, conventions.chainage, conventions)}</text>
          </g>
        ))}
        {marks.map((m) => (
          <g key={`m${m.label}${m.ch}`}>
            <line x1={f.sx(m.ch)} x2={f.sx(m.ch)} y1={14} y2={height - 28} stroke={planColour('accent')} strokeDasharray="2 3" />
            <text x={f.sx(m.ch) + 3} y={20} className="text-2xs" fill={planColour('accent')}>{m.label}</text>
          </g>
        ))}
        {lines.map((run, i) => {
          const d = run.map((p, j) => `${j ? 'L' : 'M'}${f.sx(p.ch).toFixed(1)},${f.sz(p.z).toFixed(1)}`).join('');
          const area = `${d}L${f.sx(run[run.length - 1]!.ch).toFixed(1)},${height - 28}L${f.sx(run[0]!.ch).toFixed(1)},${height - 28}Z`;
          return (
            <g key={i}>
              <path d={area} fill={planColour('surface')} fillOpacity={0.25} />
              <path d={d} fill="none" stroke={planColour('topo')} strokeWidth={1.75} strokeLinejoin="round" />
            </g>
          );
        })}
        {hover && hover.z != null && (
          <g>
            <line x1={f.sx(hover.ch)} x2={f.sx(hover.ch)} y1={24} y2={height - 28} stroke={planColour('ink')} />
            <circle cx={f.sx(hover.ch)} cy={f.sz(hover.z)} r={4} fill={planColour('bg')} stroke={planColour('ink')} strokeWidth={1.5} />
            <text x={f.sx(hover.ch) + 6} y={f.sz(hover.z) - 8} className="text-xs" fill={planColour('ink')} stroke={planColour('halo')} strokeWidth={3} paintOrder="stroke">
              {formatChainage(hover.ch, conventions.chainage, conventions)} · {formatDistance(hover.z, conventions)}
            </text>
          </g>
        )}
      </svg>
      <figcaption className="text-xs text-content-tertiary">
        {t('plan.section.exaggeration', { defaultValue: 'Heights drawn x{{v}}', v: f.vx >= 1.95 ? Math.round(f.vx) : fmtFixed(f.vx, 1) })}
      </figcaption>
    </figure>
  );
}
