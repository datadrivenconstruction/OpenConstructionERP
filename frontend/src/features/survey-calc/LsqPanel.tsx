// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Least-squares result of a traverse: the global test, the sketch with error
 * ellipses, Bowditch and LSQ coordinates side by side, residuals with the
 * largest standardized one flagged, and the ellipse table.
 */

import { lazy, Suspense, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { ellipseFeatures, ellipseScale } from '@/features/survey-plan/engine/errorEllipses';
import { extentOf } from '@/features/survey-plan/engine/traverseSketch';
import { layer } from '@/features/survey-plan/planLayers';
import { EllipseGlyph, PlanLegend, marked } from '@/features/survey-plan/screens/planMarks';
import type { GridXY, PlanFeature } from '@/features/survey-plan/types';
import { fmtM } from './angles';
import type { FieldTraverseOut } from './api';
import type { LsqOut } from './adjustment';

const PlanCanvas = lazy(() => import('@/features/survey-plan/PlanCanvas'));

/** The adjusted run and its error ellipses on the shared plan canvas. */
export function TraverseSketch({ result, lsq, projectId }: { result: FieldTraverseOut; lsq: LsqOut | null | undefined; projectId?: string | null }) {
  const { t } = useTranslation();
  const [conf95, setConf95] = useState(false);
  const pts = lsq ? lsq.stations : result.stations;
  const factor = conf95 && lsq ? lsq.confidence_95 : 1;
  const plan = useMemo(() => {
    const xy = pts.map((p): GridXY => [p.e, p.n]);
    const run: PlanFeature[] = [];
    if (xy.length >= 2) {
      const line = result.shape === 'loop' ? [...xy, xy[0]!] : xy;
      run.push(marked({ id: 'lsq-run', layer: 'traverse', geometry: { type: 'LineString', coordinates: line }, properties: {} }, { colour: 'accent', width: 2 }));
    }
    pts.forEach((p, i) =>
      run.push(marked({ id: `lsq-stn:${i}`, layer: 'traverse', geometry: { type: 'Point', coordinates: [p.e, p.n] }, properties: { label: p.station_id } }, { shape: 'circle', size: 3.5, colour: 'ink', fill: 'bg' })),
    );
    const ellipses = (lsq?.ellipses ?? []).map((e) => ({ ...e, a_m: e.a_m * factor, b_m: e.b_m * factor }));
    const scale = ellipseScale(ellipses, extentOf(pts));
    const at = new Map(pts.map((p) => [p.station_id, [p.e, p.n] as GridXY]));
    const rings = ellipseFeatures(ellipses, at, scale).map((f) =>
      marked(f, f.properties.role === 'ellipse' ? { colour: 'misclosure', width: 1.25, fill: 'misclosure', fillOpacity: 0.08 } : { colour: 'misclosure', width: 0.75, dash: 'dot' }),
    );
    return { scale, count: ellipses.length, layers: [layer('traverse', run), layer('ellipses', rings)] };
  }, [pts, result.shape, lsq, factor]);
  if (pts.length < 2) return null;
  return (
    <Suspense fallback={<div className="h-[360px] animate-pulse rounded-lg border border-border-light bg-surface-secondary" />}>
      <PlanCanvas
        projectId={projectId ?? ''}
        layers={plan.layers}
        heightClass="h-[380px]"
        inspector={false}
        overlay={plan.count > 0 && (
          <PlanLegend testId="lsq-legend">
            <span className="flex items-center gap-1.5">
              <EllipseGlyph token="misclosure" />
              {t('survey.lsq.exaggeration', { defaultValue: 'Ellipses exaggerated {{x}} times', x: fmtNumber(plan.scale, 0) })}
            </span>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={conf95} onChange={(e) => setConf95(e.target.checked)} />
              {t('survey.lsq.conf95', { defaultValue: '95% ellipses' })}
            </label>
          </PlanLegend>
        )}
        testId="lsq-sketch"
      />
    </Suspense>
  );
}

export function LsqPanel({ result, projectId }: { result: FieldTraverseOut; projectId?: string | null }) {
  const { t } = useTranslation();
  const lsq = result.lsq;
  if (!lsq) return null;
  const bow = new Map(result.stations.map((s) => [s.station_id, s]));
  return (
    <div className="space-y-3" data-testid="lsq-result">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          {t('survey.lsq.sigma0', { defaultValue: 'A posteriori sigma0 {{s}} (redundancy {{r}})', s: fmtNumber(lsq.sigma0, 3), r: lsq.redundancy })}
        </span>
        <Badge variant={lsq.chi2_pass ? 'success' : 'error'} size="sm">
          {lsq.chi2_pass
            ? t('survey.lsq.chi2_pass', { defaultValue: 'Global test passes' })
            : t('survey.lsq.chi2_fail', { defaultValue: 'Global test fails' })}
        </Badge>
        <span className="text-xs text-content-tertiary">
          <bdi dir="ltr">χ² {fmtNumber(lsq.vtpv, 2)} ∈ [{fmtNumber(lsq.chi2_lower, 2)}, {fmtNumber(lsq.chi2_upper, 2)}]</bdi>
        </span>
      </div>
      <TraverseSketch result={result} lsq={lsq} projectId={projectId} />
      <div className="overflow-x-auto">
        <h4 className="oe-label">{t('survey.lsq.compare', { defaultValue: 'Bowditch and least squares side by side' })}</h4>
        <table className="oe-table w-full text-xs" data-testid="lsq-compare">
          <thead>
            <tr>
              <th>{t('survey.cogo.col.station', { defaultValue: 'Station' })}</th>
              <th className="text-right">E Bowditch</th>
              <th className="text-right">N Bowditch</th>
              <th className="text-right">E LSQ</th>
              <th className="text-right">N LSQ</th>
              <th className="text-right">ΔE / ΔN (mm)</th>
            </tr>
          </thead>
          <tbody>
            {lsq.stations.map((s) => {
              const b = bow.get(s.station_id);
              return (
                <tr key={s.station_id}>
                  <td><bdi dir="ltr" className="font-mono">{s.station_id}</bdi>{s.fixed && <span className="ms-1 text-content-tertiary">({t('survey.lsq.fixed', { defaultValue: 'fixed' })})</span>}</td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{b ? fmtM(b.e) : '-'}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{b ? fmtM(b.n) : '-'}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(s.e)}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(s.n)}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtNumber(s.d_e_mm, 1)} / {fmtNumber(s.d_n_mm, 1)}</bdi></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto">
        <h4 className="oe-label">{t('survey.lsq.residuals', { defaultValue: 'Residuals' })}</h4>
        <table className="oe-table w-full text-xs" data-testid="lsq-residuals">
          <thead>
            <tr>
              <th>{t('survey.lsq.observation', { defaultValue: 'Observation' })}</th>
              <th className="text-right">v</th>
              <th className="text-right">σ</th>
              <th className="text-right">r</th>
              <th className="text-right">w</th>
            </tr>
          </thead>
          <tbody>
            {lsq.residuals.map((r) => {
              const unit = r.kind === 'angle' ? '"' : ' mm';
              return (
                <tr key={`${r.kind}-${r.ref}`} className={r.flagged ? 'bg-amber-50 dark:bg-amber-900/20' : undefined}>
                  <td>
                    {r.kind === 'angle' ? t('survey.lsq.angle_at', { defaultValue: 'Angle at {{s}}', s: r.ref }) : t('survey.lsq.distance_of', { defaultValue: 'Distance {{s}}', s: r.ref })}
                    {r.flagged && <span className="ms-1"><Badge variant={r.suspect ? 'error' : 'warning'} size="sm">{t('survey.lsq.largest', { defaultValue: 'Largest' })}</Badge></span>}
                  </td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtNumber(r.residual, 2)}{unit}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtNumber(r.sd, 2)}{unit}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtNumber(r.redundancy, 2)}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{r.standardized == null ? '-' : fmtNumber(r.standardized, 2)}</bdi></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto">
        <h4 className="oe-label">{t('survey.lsq.ellipses', { defaultValue: 'Error ellipses, one sigma' })}</h4>
        <table className="oe-table w-full text-xs" data-testid="lsq-ellipses">
          <thead>
            <tr>
              <th>{t('survey.cogo.col.station', { defaultValue: 'Station' })}</th>
              <th className="text-right">a (mm)</th>
              <th className="text-right">b (mm)</th>
              <th className="text-right">{t('survey.lsq.azimuth', { defaultValue: 'Azimuth of a' })}</th>
            </tr>
          </thead>
          <tbody>
            {[...lsq.ellipses, ...lsq.relative_ellipses].map((e, i) => (
              <tr key={`${e.ref}-${i}`} className={i === lsq.ellipses.length ? 'border-t-2 border-border' : undefined}>
                <td>
                  <bdi dir="ltr" className="font-mono">{e.ref}</bdi>
                  {i >= lsq.ellipses.length && <span className="ms-1 text-content-tertiary">({t('survey.lsq.relative', { defaultValue: 'relative' })})</span>}
                </td>
                <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtNumber(e.a_m * 1000, 1)}</bdi></td>
                <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtNumber(e.b_m * 1000, 1)}</bdi></td>
                <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtNumber(e.azimuth_deg, 1)}°</bdi></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default LsqPanel;
