// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Least-squares result of a traverse: the global test, the sketch with error
 * ellipses, Bowditch and LSQ coordinates side by side, residuals with the
 * largest standardized one flagged, and the ellipse table.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { fmtM } from './angles';
import type { FieldTraverseOut } from './api';
import { ellipseExaggeration, ellipseRotation, fitSketch, type LsqOut } from './adjustment';

const W = 420;
const H = 300;

export function TraverseSketch({ result, lsq }: { result: FieldTraverseOut; lsq: LsqOut | null | undefined }) {
  const { t } = useTranslation();
  const [conf95, setConf95] = useState(false);
  const pts = lsq ? lsq.stations : result.stations;
  if (pts.length < 2) return null;
  const { at, scale } = fitSketch(pts, W, H);
  const ring = pts.map((p) => at(p.e, p.n));
  if (result.shape === 'loop') ring.push(ring[0]!);
  const ellipses = lsq?.ellipses ?? [];
  const exag = ellipseExaggeration(ellipses, Math.min(W, H) - 48);
  const factor = conf95 && lsq ? lsq.confidence_95 : 1;
  const byId = new Map(pts.map((p) => [p.station_id, p]));
  return (
    <figure className="space-y-1">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-md border border-border-light bg-surface-secondary" role="img" aria-label={t('survey.lsq.sketch', { defaultValue: 'Sketch with error ellipses' })} data-testid="traverse-sketch">
        <polyline points={ring.map(([x, y]) => `${x},${y}`).join(' ')} fill="none" stroke="currentColor" className="text-oe-blue" strokeWidth={1.5} />
        {ellipses.map((e) => {
          const p = byId.get(e.ref);
          if (!p) return null;
          const [x, y] = at(p.e, p.n);
          return (
            <ellipse
              key={e.ref}
              cx={x}
              cy={y}
              rx={Math.max(e.b_m * exag * factor, 0.5)}
              ry={Math.max(e.a_m * exag * factor, 0.5)}
              transform={`rotate(${ellipseRotation(e.azimuth_deg)} ${x} ${y})`}
              fill="none"
              stroke="#c0392b"
              strokeWidth={1.2}
            />
          );
        })}
        {pts.map((p) => {
          const [x, y] = at(p.e, p.n);
          return (
            <g key={p.station_id}>
              <circle cx={x} cy={y} r={2.5} fill="currentColor" className="text-content-primary" />
              <text x={x + 5} y={y - 5} fontSize={11} className="fill-current">{p.station_id}</text>
            </g>
          );
        })}
        <text x={W - 16} y={16} fontSize={11} fontWeight="bold" className="fill-current">N</text>
        <line x1={W - 12} y1={22} x2={W - 12} y2={42} stroke="currentColor" />
      </svg>
      {lsq && ellipses.length > 0 && (
        <figcaption className="flex flex-wrap items-center gap-3 text-xs text-content-tertiary">
          <span>{t('survey.lsq.exaggeration', { defaultValue: 'Ellipses exaggerated {{x}} times', x: fmtNumber(exag / scale, 0) })}</span>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={conf95} onChange={(e) => setConf95(e.target.checked)} />
            {t('survey.lsq.conf95', { defaultValue: '95% ellipses' })}
          </label>
        </figcaption>
      )}
    </figure>
  );
}

export function LsqPanel({ result }: { result: FieldTraverseOut }) {
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
      <TraverseSketch result={result} lsq={lsq} />
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
