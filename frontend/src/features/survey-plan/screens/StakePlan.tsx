// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The stakes of a request on the plan: design position, as-staked position
 * and the deviation arrow drawn x10 to x500 (the legend says what one metre
 * of arrow stands for). Verdict in colour and shape; filter chips by verdict.
 */

import { lazy, Suspense, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Stake, StakeoutRequestDetail } from '@/features/setting-out/api';
import { fmtMm } from '@/features/setting-out/verdict';
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
  type VerdictShape,
} from '../engine/deviationArrows';
import type { FeatureShape, MapToken } from '../cartography';
import { usePlanConventions } from '../hooks';
import { layer } from '../planLayers';
import type { PlanFeature, PlanLayerSpec } from '../types';
import { formatCoordPair, formatDistance } from '../units';
import { MarkGlyph, PlanLegend, PlanPrintButton, marked } from './planMarks';

const PlanCanvas = lazy(() => import('../PlanCanvas'));

const VERDICTS: StakeVerdict[] = ['pass', 'fail', 'no_tolerance', 'open'];
const VERDICT_DEFAULT: Record<StakeVerdict, string> = { pass: 'In tolerance', fail: 'Out of tolerance', no_tolerance: 'No tolerance', open: 'Not staked yet' };
/** The verdict cross is drawn turned, as an x. */
const shapeOf = (s: VerdictShape): FeatureShape => (s === 'cross' ? 'x' : s);

function Glyph({ shape, token }: { shape: VerdictShape; token: MapToken }) {
  return <MarkGlyph shape={shapeOf(shape)} token={token} />;
}

/** Stake plan layers: the centreline, the deviation arrows and the design marks on top. */
export function stakeLayers(features: readonly PlanFeature[]): PlanLayerSpec[] {
  const line: PlanFeature[] = [];
  const dev: PlanFeature[] = [];
  const marks: PlanFeature[] = [];
  for (const f of features) {
    const tok = (f.properties.colour as MapToken | undefined) ?? 'ink-2';
    switch (f.properties.role) {
      case 'centreline':
        line.push(marked(f, { colour: 'line', width: 1.25, dash: 'dashdot' }));
        break;
      case 'design':
        marks.push(marked(f, { shape: shapeOf(f.properties.shape as VerdictShape), size: 4.5, colour: tok, fill: f.properties.verdict === 'open' ? 'bg' : tok }));
        break;
      case 'measured':
        dev.push(marked({ ...f, layer: 'stake_deviation' }, { shape: 'circle', size: 2, colour: tok, fill: tok }));
        break;
      case 'arrow':
        dev.push(marked({ ...f, layer: 'stake_deviation' }, { colour: tok, width: 2 }));
        break;
      case 'head':
        dev.push(marked({ ...f, layer: 'stake_deviation' }, { colour: tok, fill: tok, fillOpacity: 1, width: 1 }));
        break;
    }
  }
  return [
    layer('alignment', line, { selectable: false }),
    { id: 'stake_deviation', titleKey: 'plan.stake.layer_deviation', defaultTitle: 'Deviation arrows', order: 128, features: dev, snappable: false, selectable: false },
    layer('stakes', marks),
  ];
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
  const layers = useMemo(() => stakeLayers(features), [features]);
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
      <Suspense fallback={<div className="h-[480px] animate-pulse rounded-lg border border-border-light bg-surface-secondary" />}>
        <PlanCanvas
          projectId={projectId}
          layers={layers}
          heightClass="h-[520px]"
          selectedIds={selected ? [`stake:${selected}`] : []}
          onSelect={(ids) => {
            const id = ids.find((x) => x.startsWith('stake:'));
            const s = id ? stakes.find((x) => `stake:${x.id}` === id) : undefined;
            setSelected(s?.id ?? null);
            if (s) onSelect?.(s);
          }}
          toolbarSlot={<PlanPrintButton projectId={projectId} layers={layers} conventions={conv} title={request.name} testId="stake-plan-print" />}
          inspectorSlot={sel && (
            <div className="space-y-1 px-3 py-3 text-xs" data-testid="stake-inspector">
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
          overlay={
            <PlanLegend testId="stake-legend">
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
            </PlanLegend>
          }
          testId="stake-plan-canvas"
        />
      </Suspense>
    </div>
  );
}
