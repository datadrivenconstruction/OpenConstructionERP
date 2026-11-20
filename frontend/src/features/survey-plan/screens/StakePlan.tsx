// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The stakes of a request on the plan: design position, as-staked position
 * and the deviation arrow drawn x10 to x500 (the legend says what one metre
 * of arrow stands for). Verdict in colour and shape; filter chips by verdict.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Stake, StakeoutRequestDetail } from '@/features/setting-out/api';
import { fmtMm } from '@/features/setting-out/verdict';
import { planColour } from '../cartography';
import { centreline, designAlignment, ipsFromStored } from '../engine/alignmentGeom';
import {
  ARROW_SCALES,
  DEFAULT_ARROW_SCALE,
  mmPerArrowMetre,
  stakeFeatures,
  verdictCounts,
  verdictStyle,
  type ArrowScale,
  type StakeVerdict,
} from '../engine/deviationArrows';
import { usePlanConventions } from '../hooks';
import type { PlanFeature } from '../types';
import { formatCoordPair, formatDistance } from '../units';
import { PlanSketch, type SketchShape, type SketchStyle } from './PlanSketch';

const VERDICTS: StakeVerdict[] = ['pass', 'fail', 'no_tolerance', 'open'];
const VERDICT_DEFAULT: Record<StakeVerdict, string> = { pass: 'In tolerance', fail: 'Out of tolerance', no_tolerance: 'No tolerance', open: 'Not staked yet' };

function Glyph({ shape, token }: { shape: SketchShape; token: Parameters<typeof planColour>[0] }) {
  const c = planColour(token);
  const d =
    shape === 'square' ? 'M3,3h8v8h-8Z' : shape === 'diamond' ? 'M7,1.5L12.5,7L7,12.5L1.5,7Z' : shape === 'cross' ? 'M3,3L11,11M3,11L11,3' : 'M2.5,7a4.5,4.5 0 1,0 9,0a4.5,4.5 0 1,0 -9,0';
  return (
    <svg width={14} height={14} aria-hidden>
      <path d={d} fill={shape === 'cross' ? 'none' : c} stroke={c} strokeWidth={shape === 'cross' ? 2 : 1} />
    </svg>
  );
}

export function StakePlan({ projectId, request, onSelect }: { projectId: string; request: StakeoutRequestDetail; onSelect?: (stake: Stake) => void }) {
  const { t } = useTranslation();
  const { conventions: conv } = usePlanConventions(projectId);
  const [scale, setScale] = useState<ArrowScale>(DEFAULT_ARROW_SCALE);
  const [hidden, setHidden] = useState<Set<StakeVerdict>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const stakes = request.stakes;
  const counts = verdictCounts(stakes.map((s) => ({ verdict: s.verdict as StakeVerdict })));

  const features = useMemo<PlanFeature[]>(() => {
    const out = stakeFeatures(
      stakes
        .filter((s) => !hidden.has(s.verdict as StakeVerdict))
        .map((s) => ({
          id: s.id,
          pointId: s.point_id,
          design: [s.design_e, s.design_n],
          measured: s.latest ? [s.latest.measured_e, s.latest.measured_n] : null,
          verdict: s.verdict as StakeVerdict,
          dE: s.latest?.de_mm,
          dN: s.latest?.dn_mm,
          dZ: s.latest?.dz_mm,
        })),
      scale,
    );
    const stored = ipsFromStored(request.alignment);
    if (stored) {
      const line = centreline(designAlignment(stored.ips, stored.startCh), 2);
      out.unshift({ id: 'centreline', layer: 'alignment', geometry: { type: 'LineString', coordinates: line }, properties: { role: 'centreline' } });
    }
    return out;
  }, [stakes, hidden, scale, request.alignment]);
  const fit = useMemo(() => features.filter((f) => f.properties.role === 'design'), [features]);

  const styleFor = (f: PlanFeature): SketchStyle | null => {
    const tok = (f.properties.colour as SketchStyle['stroke']) ?? 'ink-2';
    switch (f.properties.role) {
      case 'centreline':
        return { stroke: 'line', width: 1.25, dash: '8 3 2 3' };
      case 'design':
        return { shape: f.properties.shape as SketchShape, size: 4.5, stroke: tok, fill: f.properties.verdict === 'open' ? undefined : tok, label: String(f.properties.label ?? ''), top: true };
      case 'measured':
        return { shape: 'circle', size: 2, stroke: tok, fill: tok };
      case 'arrow':
        return { stroke: tok, width: 2 };
      case 'head':
        return { stroke: tok, fill: tok, width: 1 };
      default:
        return null;
    }
  };
  const sel = stakes.find((s) => s.id === selected);

  return (
    <div className="space-y-3 p-3" data-testid="stake-plan">
      <div className="flex flex-wrap items-center gap-2">
        {VERDICTS.map((v) => {
          const vs = verdictStyle(v);
          const on = !hidden.has(v);
          return (
            <button key={v} type="button" aria-pressed={on}
              onClick={() => setHidden((h) => { const n = new Set(h); if (n.has(v)) n.delete(v); else n.add(v); return n; })}
              className={`flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs ${on ? 'border-border-light text-content-primary' : 'border-dashed border-border-light text-content-quaternary'}`}>
              <Glyph shape={vs.shape} token={vs.token} />
              {t(`plan.stake.verdict.${v}`, { defaultValue: VERDICT_DEFAULT[v] })}
              <span className="font-mono text-content-tertiary">{counts[v]}</span>
            </button>
          );
        })}
        <div className="ms-auto flex h-8 items-center gap-2">
          <span className="text-xs text-content-tertiary">{t('plan.stake.arrows', { defaultValue: 'Arrows' })}</span>
          <div className="flex h-8 rounded-lg border border-border-light p-0.5" role="group" aria-label={t('plan.stake.arrows', { defaultValue: 'Arrows' })}>
            {ARROW_SCALES.map((s) => (
              <button key={s} type="button" data-oe-segment aria-pressed={scale === s} onClick={() => setScale(s)}
                className={`rounded-sm px-2 font-mono text-xs ${scale === s ? 'bg-surface-secondary font-medium text-content-primary' : 'text-content-secondary'}`}>
                x{s}
              </button>
            ))}
          </div>
        </div>
      </div>
      <PlanSketch
        features={features}
        fitTo={fit}
        styleFor={styleFor}
        conventions={conv}
        heightClass="h-[480px]"
        selectedId={selected ? `stake:${selected}` : null}
        onPick={(f) => {
          if (f.entityType !== 'stake' || !f.entityId) return;
          setSelected(f.entityId);
          const s = stakes.find((x) => x.id === f.entityId);
          if (s) onSelect?.(s);
        }}
        testId="stake-plan-canvas"
      >
        <div className="absolute bottom-3 end-3 space-y-1 rounded-lg border border-border-light bg-surface-primary/90 px-2.5 py-2 text-xs text-content-secondary" data-testid="stake-legend">
          {VERDICTS.map((v) => {
            const vs = verdictStyle(v);
            return (
              <span key={v} className="flex items-center gap-1.5">
                <Glyph shape={vs.shape} token={vs.token} />
                {t(`plan.stake.verdict.${v}`, { defaultValue: VERDICT_DEFAULT[v] })}
              </span>
            );
          })}
          <span className="block border-t border-border-light pt-1 text-content-tertiary">
            {t('plan.stake.scale_legend', { defaultValue: 'Arrows x{{s}}: 1 m of arrow = {{mm}} mm', s: scale, mm: mmPerArrowMetre(scale) })}
          </span>
        </div>
        {sel && (
          <div className="absolute start-3 top-3 w-60 space-y-1 rounded-lg border border-border-light bg-surface-primary/95 px-3 py-2 text-xs shadow-md" data-testid="stake-inspector">
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <Glyph shape={verdictStyle(sel.verdict).shape} token={verdictStyle(sel.verdict).token} />
              {sel.point_id}
            </div>
            <div className="font-mono text-content-secondary">{formatCoordPair(sel.design_e, sel.design_n, conv)}</div>
            {sel.latest ? (
              <div className="font-mono">
                {t('plan.stake.deltas', { defaultValue: 'dE {{de}} · dN {{dn}} · d {{d}} mm', de: fmtMm(sel.latest.de_mm), dn: fmtMm(sel.latest.dn_mm), d: fmtMm(sel.latest.d_mm) })}
              </div>
            ) : (
              <div className="text-content-tertiary">{t('plan.stake.not_staked', { defaultValue: 'Not staked yet' })}</div>
            )}
            {request.tol_h_mm != null && (
              <div className="text-content-tertiary">{t('plan.stake.tolerance', { defaultValue: 'Tolerance {{t}}', t: formatDistance(request.tol_h_mm / 1000, conv) })}</div>
            )}
          </div>
        )}
      </PlanSketch>
    </div>
  );
}
