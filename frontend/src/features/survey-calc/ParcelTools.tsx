// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Parcel tools inside the parcel drawer: subdivide (by line or to an area),
 * the boundary corner register, and the setback check of a footprint.
 * A split shows the parts first; Save creates them and retires the parent.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge, Button, TabBar } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fmtM, parseCoord, parseRing } from './angles';
import { checkSetback, getCorners, patchCorner, splitParcel, stakeCorners, type SplitIn } from './api';
import { Findings } from './CalcPage';

type Tool = 'split' | 'corners' | 'setback';
const CORNER_STATUSES = ['', 'found', 'set', 'calculated'] as const;

interface Props {
  parcelId: string;
  onSplit: () => void;
}

function SplitTool({ parcelId, onSplit }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [mode, setMode] = useState<SplitIn['mode']>('parallel');
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [side, setSide] = useState('1');
  const [target, setTarget] = useState('');
  const onError = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });

  const body = (): SplitIn | null => {
    if (mode === 'line') {
      const pa = parseCoord(a);
      const pb = parseCoord(b);
      return pa && pb ? { mode, a: pa.slice(0, 2), b: pb.slice(0, 2), preview: true } : null;
    }
    const area = Number(target.replace(',', '.'));
    if (!(area > 0)) return null;
    if (mode === 'rotate') {
      const pv = parseCoord(a);
      return pv ? { mode, pivot: pv.slice(0, 2), target_area: area, preview: true } : null;
    }
    const s = Number(side);
    return Number.isInteger(s) && s >= 1 ? { mode, side: s - 1, target_area: area, preview: true } : null;
  };
  const req = body();
  const preview = useMutation({ mutationFn: (r: SplitIn) => splitParcel(parcelId, r), onError });
  const save = useMutation({
    mutationFn: (r: SplitIn) => splitParcel(parcelId, { ...r, preview: false }),
    onSuccess: (o) => {
      if (!o.saved) return;
      addToast({ type: 'success', title: t('survey.subdivide.saved', { defaultValue: 'Parcel split into {{a}} and {{b}}', a: o.parts[0]?.ref, b: o.parts[1]?.ref }) });
      void qc.invalidateQueries({ queryKey: ['land-parcels'] });
      onSplit();
    },
    onError,
  });
  const r = preview.data;
  const blocked = r?.findings.some((f) => f.severity === 'error');

  return (
    <div className="space-y-2">
      <label className="block">
        <span className="oe-label">{t('survey.subdivide.mode', { defaultValue: 'Cut' })}</span>
        <select className="oe-input w-full" value={mode} onChange={(e) => { setMode(e.target.value as SplitIn['mode']); preview.reset(); }}>
          <option value="parallel">{t('survey.subdivide.parallel', { defaultValue: 'To an area, parallel to a side' })}</option>
          <option value="rotate">{t('survey.subdivide.rotate', { defaultValue: 'To an area, turning about a point' })}</option>
          <option value="line">{t('survey.subdivide.line', { defaultValue: 'Along a line through two points' })}</option>
        </select>
      </label>
      {mode !== 'parallel' && (
        <label className="block">
          <span className="oe-label">{mode === 'rotate' ? t('survey.subdivide.pivot', { defaultValue: 'Pivot E N' }) : t('survey.cogo.field.point', { defaultValue: 'Point {{p}} (E N)', p: 'A' })}</span>
          <input className="oe-input w-full font-mono" dir="ltr" value={a} onChange={(e) => setA(e.target.value)} />
        </label>
      )}
      {mode === 'line' && (
        <label className="block">
          <span className="oe-label">{t('survey.cogo.field.point', { defaultValue: 'Point {{p}} (E N)', p: 'B' })}</span>
          <input className="oe-input w-full font-mono" dir="ltr" value={b} onChange={(e) => setB(e.target.value)} />
        </label>
      )}
      {mode === 'parallel' && (
        <label className="block">
          <span className="oe-label">{t('survey.subdivide.side', { defaultValue: 'Side from corner number' })}</span>
          <input className="oe-input w-24 font-mono" dir="ltr" value={side} onChange={(e) => setSide(e.target.value)} />
        </label>
      )}
      {mode !== 'line' && (
        <label className="block">
          <span className="oe-label">{t('survey.subdivide.target', { defaultValue: 'Area of the new part (m²)' })}</span>
          <input className="oe-input w-full font-mono" dir="ltr" value={target} onChange={(e) => setTarget(e.target.value)} />
        </label>
      )}
      <div className="flex gap-2">
        <Button size="sm" disabled={!req} loading={preview.isPending} onClick={() => req && preview.mutate(req)}>
          {t('survey.subdivide.preview', { defaultValue: 'Show the parts' })}
        </Button>
        {r && req && !blocked && (
          <Button size="sm" variant="secondary" loading={save.isPending} onClick={() => save.mutate(req)}>
            {t('survey.subdivide.save', { defaultValue: 'Split the parcel' })}
          </Button>
        )}
      </div>
      {r && (
        <div className="space-y-1" data-testid="split-preview">
          {r.parts.map((p) => (
            <div key={p.ref}><bdi dir="ltr" className="font-mono">{p.ref}</bdi>: <bdi dir="ltr" className="font-mono">{fmtM(p.area, 2)} m²</bdi></div>
          ))}
          {r.cut_length != null && (
            <div className="text-content-secondary">{t('survey.subdivide.cut_length', { defaultValue: 'Cut line {{l}} m', l: fmtM(r.cut_length) })}</div>
          )}
          <Findings items={r.findings} />
        </div>
      )}
    </div>
  );
}

function CornersTool({ parcelId }: { parcelId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const key = ['land-parcels', 'corners', parcelId];
  const reg = useQuery({ queryKey: key, queryFn: () => getCorners(parcelId) });
  const onError = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const patch = useMutation({
    mutationFn: ({ seq, body }: { seq: number; body: Parameters<typeof patchCorner>[2] }) => patchCorner(parcelId, seq, body),
    onSuccess: (d) => qc.setQueryData(key, d),
    onError,
  });
  const stake = useMutation({
    mutationFn: () => stakeCorners(parcelId),
    onSuccess: (o) => addToast({ type: 'success', title: t('survey.corners.staked', { defaultValue: 'Setting-out request {{code}} with {{n}} corners', code: o.code, n: o.stakes }) }),
    onError,
  });
  const d = reg.data;
  if (!d) return null;
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="oe-table w-full text-xs">
          <thead>
            <tr>
              <th>{t('survey.corners.col.id', { defaultValue: 'Corner' })}</th>
              <th>{t('survey.corners.col.status', { defaultValue: 'Found / set' })}</th>
              <th>{t('survey.corners.col.class', { defaultValue: 'Precision class' })}</th>
              <th className="text-right">{t('survey.corners.col.precision', { defaultValue: 'Precision (m)' })}</th>
              <th className="text-right">{t('survey.corners.col.limit', { defaultValue: 'Allowed (m)' })}</th>
            </tr>
          </thead>
          <tbody>
            {d.corners.map((c) => (
              <tr key={c.seq}>
                <td><bdi dir="ltr" className="font-mono">{c.label}</bdi></td>
                <td>
                  <select className="oe-input py-0.5 text-xs" value={c.corner_status}
                    onChange={(e) => patch.mutate({ seq: c.seq, body: { corner_status: e.target.value } })}>
                    {CORNER_STATUSES.map((s) => (
                      <option key={s} value={s}>{s ? t(`survey.corners.status.${s}`, { defaultValue: s }) : '-'}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <select className="oe-input py-0.5 text-xs" value={c.accuracy_class}
                    onChange={(e) => patch.mutate({ seq: c.seq, body: { accuracy_class: e.target.value } })}>
                    <option value="">-</option>
                    {d.classes.map((k) => (
                      <option key={k.key} value={k.key}>{k.label}</option>
                    ))}
                  </select>
                </td>
                <td className="text-right">
                  <input className="oe-input w-20 py-0.5 text-right font-mono text-xs" dir="ltr" defaultValue={c.accuracy_m ?? ''}
                    onBlur={(e) => {
                      const raw = e.target.value.trim();
                      const v = Number(raw.replace(',', '.'));
                      if (raw === '') patch.mutate({ seq: c.seq, body: { clear_accuracy: true } });
                      else if (Number.isFinite(v) && v >= 0 && v !== c.accuracy_m) patch.mutate({ seq: c.seq, body: { accuracy_m: v } });
                    }} />
                </td>
                <td className="text-right">
                  <bdi dir="ltr" className="font-mono">{fmtM(c.limit_m)}</bdi>
                  {c.findings.length > 0 && <Badge variant="warning" size="sm" className="ms-1">{c.findings[0]?.rule_id}</Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.corners.flatMap((c) => c.findings).length > 0 && <Findings items={d.corners.flatMap((c) => c.findings)} />}
      <Button size="sm" variant="secondary" disabled={!d.corners.length} loading={stake.isPending} onClick={() => stake.mutate()}>
        {t('survey.corners.stake', { defaultValue: 'Stake the corners' })}
      </Button>
    </div>
  );
}

function SetbackTool({ parcelId }: { parcelId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [ring, setRing] = useState('');
  const [name, setName] = useState('');
  const [need, setNeed] = useState('3.00');
  const fp = parseRing(ring);
  const s = Number(need.replace(',', '.'));
  const run = useMutation({
    mutationFn: () => checkSetback(parcelId, fp!, name.trim() || 'Footprint', s),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const r = run.data;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="oe-label">{t('survey.setback.name', { defaultValue: 'Footprint name' })}</span>
          <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="block">
          <span className="oe-label">{t('survey.setback.required', { defaultValue: 'Required setback (m)' })}</span>
          <input className="oe-input w-full font-mono" dir="ltr" value={need} onChange={(e) => setNeed(e.target.value)} />
        </label>
      </div>
      <label className="block">
        <span className="oe-label">{t('survey.setback.footprint', { defaultValue: 'Footprint corners, one "E N" per line' })}</span>
        <textarea className="oe-input w-full font-mono" rows={4} dir="ltr" value={ring} onChange={(e) => setRing(e.target.value)} />
      </label>
      <Button size="sm" disabled={!fp || !(s > 0)} loading={run.isPending} onClick={() => run.mutate()}>
        {t('survey.setback.check', { defaultValue: 'Check setback' })}
      </Button>
      {r && (
        <div className="space-y-1" data-testid="setback-result">
          {r.edges.map((e) => (
            <div key={e.edge} className="flex items-center gap-2">
              <bdi dir="ltr" className="font-mono">{e.label}</bdi>
              <bdi dir="ltr" className="font-mono">{fmtM(e.distance, 2)} m</bdi>
              <Badge variant={e.ok ? 'success' : 'warning'} size="sm">
                {e.encroaches ? t('survey.setback.encroaches', { defaultValue: 'Crosses the boundary' }) : e.ok ? t('survey.setback.ok', { defaultValue: 'Kept' }) : t('survey.setback.short', { defaultValue: 'Too close' })}
              </Badge>
            </div>
          ))}
          <Findings items={r.findings} />
        </div>
      )}
    </div>
  );
}

export function ParcelTools({ parcelId, onSplit }: Props) {
  const { t } = useTranslation();
  const [tool, setTool] = useState<Tool>('split');
  const label = t('survey.parcels.tools', { defaultValue: 'Parcel tools' });
  return (
    <section className="space-y-2" data-testid="parcel-tools">
      <h3 className="font-medium">{label}</h3>
      <TabBar<Tool>
        ariaLabel={label}
        activeId={tool}
        onChange={setTool}
        size="sm"
        tabs={[
          { id: 'split', label: t('survey.subdivide.tab', { defaultValue: 'Subdivide' }) },
          { id: 'corners', label: t('survey.corners.tab', { defaultValue: 'Corners' }) },
          { id: 'setback', label: t('survey.setback.tab', { defaultValue: 'Setback' }) },
        ]}
      />
      {tool === 'split' && <SplitTool parcelId={parcelId} onSplit={onSplit} />}
      {tool === 'corners' && <CornersTool parcelId={parcelId} />}
      {tool === 'setback' && <SetbackTool parcelId={parcelId} />}
    </section>
  );
}
