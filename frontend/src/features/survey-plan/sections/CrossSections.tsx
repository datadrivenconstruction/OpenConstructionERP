// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cross sections of the ground at round chainages: one station at a time with
 * a stepper, left to right as seen looking up chainage, centreline marked.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/shared/ui';
import { planColour } from '../cartography';
import { niceStep, runs, sectionFrame, type CrossSection } from '../engine/sections';
import { formatChainage, formatDistance, type PlanConventions } from '../units';
import { fmtFixed } from '@/shared/lib/formatters';

export function CrossSections({ sections, conventions, onStation }: { sections: readonly CrossSection[]; conventions: PlanConventions; onStation?: (ch: number) => void }) {
  const { t } = useTranslation();
  const [i, setI] = useState(0);
  const W = 520;
  const H = 200;
  const k = Math.min(i, sections.length - 1);
  const s = sections[k];
  if (!s) return null;
  // Both sides share one height scale so a cross fall reads true; x5 up.
  const f = sectionFrame(s.points.map((p) => p.offset), s.points.map((p) => p.z), W, H, 5, 28);
  const step = niceStep(f.z1 - f.z0, 3);
  const zTicks: number[] = [];
  for (let z = Math.ceil(f.z0 / step) * step; z <= f.z1 + 1e-9; z += step) zTicks.push(Number(z.toFixed(6)));
  const go = (j: number) => {
    setI(j);
    const c = sections[j]?.ch;
    if (c != null) onStation?.(c);
  };
  const centre = s.points.find((p) => Math.abs(p.offset) < 1e-9);

  return (
    <figure className="space-y-1" data-testid="cross-sections">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" icon={<ChevronLeft size={14} />} aria-label={t('plan.section.prev', { defaultValue: 'Previous station' })} disabled={k === 0} onClick={() => go(k - 1)} />
        <span className="font-mono text-sm">{formatChainage(s.ch, conventions.chainage, conventions)}</span>
        <Button size="sm" variant="ghost" icon={<ChevronRight size={14} />} aria-label={t('plan.section.next', { defaultValue: 'Next station' })} disabled={k >= sections.length - 1} onClick={() => go(k + 1)} />
        <span className="text-xs text-content-tertiary">{t('plan.section.count', { defaultValue: '{{i}} of {{n}}', i: k + 1, n: sections.length })}</span>
        {centre?.z != null && <span className="ms-auto font-mono text-xs text-content-secondary">{t('plan.section.cl_level', { defaultValue: 'CL {{z}}', z: formatDistance(centre.z, conventions) })}</span>}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="block rounded-xl border border-border-light" style={{ background: planColour('bg') }} role="img"
        aria-label={t('plan.section.cross_aria', { defaultValue: 'Cross section at {{ch}}', ch: formatChainage(s.ch, conventions.chainage, conventions) })}>
        {zTicks.map((z) => (
          <g key={z}>
            <line x1={28} x2={W - 28} y1={f.sz(z)} y2={f.sz(z)} stroke={planColour('grid')} />
            <text x={2} y={f.sz(z) + 4} className="text-2xs" fill={planColour('ink-2')}>{formatDistance(z, conventions, false)}</text>
          </g>
        ))}
        <line x1={f.sx(0)} x2={f.sx(0)} y1={12} y2={H - 22} stroke={planColour('accent')} strokeDasharray="4 3" />
        <text x={f.sx(0)} y={H - 8} textAnchor="middle" className="text-2xs" fill={planColour('accent')}>{t('plan.section.cl', { defaultValue: 'CL' })}</text>
        <text x={f.sx(f.x0)} y={H - 8} className="text-2xs" fill={planColour('ink-2')}>{t('plan.section.left', { defaultValue: 'Left' })} {formatDistance(Math.abs(f.x0), conventions)}</text>
        <text x={f.sx(f.x1)} y={H - 8} textAnchor="end" className="text-2xs" fill={planColour('ink-2')}>{t('plan.section.right', { defaultValue: 'Right' })} {formatDistance(f.x1, conventions)}</text>
        {runs(s.points).map((run, j) => (
          <path key={j} d={run.map((p, q) => `${q ? 'L' : 'M'}${f.sx(p.offset).toFixed(1)},${f.sz(p.z).toFixed(1)}`).join('')} fill="none" stroke={planColour('topo')} strokeWidth={1.75} strokeLinejoin="round" />
        ))}
      </svg>
      <figcaption className="text-xs text-content-tertiary">{t('plan.section.exaggeration', { defaultValue: 'Heights drawn x{{v}}', v: f.vx >= 1.95 ? Math.round(f.vx) : fmtFixed(f.vx, 1) })}</figcaption>
    </figure>
  );
}
