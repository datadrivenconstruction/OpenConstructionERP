// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Road alignment by intersection points. Click the plan to add an IP, type
 * the radius in the table; tangents, arcs and chainage ticks redraw at once
 * (browser maths), the server checks the minimum radius of the active market
 * and stores the alignment on the request. Curves that overlap draw red and
 * cannot be saved.
 */

import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MousePointerClick, Save, Trash2 } from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import type { StakeoutRequestDetail } from '@/features/setting-out/api';
import { centreline, chainageTicks, designAlignment, ipsFromStored, pointAt, tickSegment, type IpInput } from '../engine/alignmentGeom';
import { usePlanConventions } from '../hooks';
import { layer } from '../planLayers';
import type { GridXY, PlanFeature, PlanLayerSpec } from '../types';
import { axisLabelFor, formatAngle, formatChainage, formatDistance, inputDistance, parseDistance } from '../units';
import { alignmentApi, type AlignmentDesignIn } from '../p3api';
import { SectionPanel } from '../sections/SectionPanel';
import { FindingList } from './FindingList';
import { LineGlyph, PlanLegend, PlanPrintButton, marked, type MarkStyle } from './planMarks';

const PlanCanvas = lazy(() => import('../PlanCanvas'));

const TICK = 20;
const LABEL = 100;

const MARK: Record<string, MarkStyle> = {
  'ip-line': { colour: 'ink-2', width: 1, dash: 'dash' },
  tangent: { colour: 'line', width: 2.5 },
  arc: { colour: 'accent', width: 2.75, labelColour: 'accent' },
  'arc-warn': { colour: 'warning', width: 2.75, labelColour: 'warning' },
  'arc-bad': { colour: 'error', width: 2.75, dash: 'dash', labelColour: 'error' },
  tp: { shape: 'circle', size: 2.5, colour: 'accent', fill: 'bg' },
  tick: { colour: 'ink', width: 1 },
  'tick-major': { colour: 'ink', width: 1.75 },
  'tick-label': { shape: 'none' },
  ip: { shape: 'diamond', size: 4.5, colour: 'ink', fill: 'bg' },
  hover: { shape: 'circle', size: 5, colour: 'misclosure', fill: 'misclosure' },
};

/** Alignment plan layers: geometry and IPs, chainage ticks, and the section cursor. */
export function alignmentLayers(features: readonly PlanFeature[]): PlanLayerSpec[] {
  const styled = features.map((f) => {
    const m = MARK[String(f.properties.role)];
    return m ? marked(f, m) : f;
  });
  const isTick = (f: PlanFeature) => String(f.properties.role).startsWith('tick');
  return [
    layer('alignment', styled.filter((f) => f.layer === 'alignment' && !isTick(f))),
    { id: 'chainage', titleKey: 'plan.align.layer_chainage', defaultTitle: 'Chainage ticks', order: 105, features: styled.filter(isTick), snappable: false, selectable: false },
    layer('sections', styled.filter((f) => f.layer === 'sections'), { selectable: false, snappable: false }),
  ];
}

interface IpText {
  name: string;
  e: string;
  n: string;
  r: string;
}

export function AlignmentEditor({ projectId, request, canWrite }: { projectId: string; request: StakeoutRequestDetail; canWrite: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { conventions: conv } = usePlanConventions(projectId);
  const axes = axisLabelFor(conv.axis);
  const stored = useMemo(() => ipsFromStored(request.alignment), [request.alignment]);
  const toText = (ips: IpInput[]): IpText[] =>
    ips.map((p) => ({ name: p.name ?? '', e: inputDistance(p.e, conv), n: inputDistance(p.n, conv), r: p.radius ? inputDistance(p.radius, conv) : '' }));
  const [rows, setRows] = useState<IpText[]>(() => toText(stored?.ips ?? []));
  const [startCh, setStartCh] = useState(String(stored?.startCh ?? 0));
  const [speed, setSpeed] = useState(stored?.speed != null ? String(stored.speed) : '');
  const [adding, setAdding] = useState(!stored);
  const [selected, setSelected] = useState<number | null>(null);
  const [hoverCh, setHoverCh] = useState<number | null>(null);
  useEffect(() => {
    setRows(toText(stored?.ips ?? []));
    setStartCh(String(stored?.startCh ?? 0));
    setSpeed(stored?.speed != null ? String(stored.speed) : '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request.id, stored]);

  const ips = useMemo<IpInput[]>(
    () =>
      rows.flatMap((r, i): IpInput[] => {
        const e = parseDistance(r.e, conv);
        const n = parseDistance(r.n, conv);
        if (e == null || n == null) return [];
        return [{ name: r.name.trim() || `IP${i}`, e, n, radius: parseDistance(r.r, conv) ?? 0 }];
      }),
    [rows, conv],
  );
  const ch0 = Number(startCh) || 0;
  const design = useMemo(() => designAlignment(ips, ch0), [ips, ch0]);
  const ticks = useMemo(() => chainageTicks(design, TICK, LABEL), [design]);

  const body: AlignmentDesignIn | null =
    ips.length >= 2 ? { name: request.name, ips, start_chainage: ch0, design_speed_kmh: Number(speed) > 0 ? Number(speed) : null, tick_interval: TICK, label_interval: LABEL } : null;
  const [debounced, setDebounced] = useState<AlignmentDesignIn | null>(null);
  useEffect(() => {
    const h = setTimeout(() => setDebounced(body), 300);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(body)]);
  const check = useQuery({
    queryKey: ['survey-plan', 'alignment-preview', debounced],
    queryFn: () => alignmentApi.preview(debounced!),
    enabled: !!debounced,
    placeholderData: (p) => p,
    retry: false,
  });
  const belowMin = new Set((check.data?.curves ?? []).filter((c) => c.below_min).map((c) => c.ref));
  const save = useMutation({
    mutationFn: () => alignmentApi.save(request.id, body!),
    onSuccess: () => {
      addToast({ type: 'success', title: t('plan.align.saved', { defaultValue: 'Alignment saved on the request' }) });
      void qc.invalidateQueries({ queryKey: ['setting-out'] });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const features = useMemo<PlanFeature[]>(() => {
    const out: PlanFeature[] = [];
    if (ips.length >= 2) out.push({ id: 'ip-line', layer: 'alignment', geometry: { type: 'LineString', coordinates: ips.map((p) => [p.e, p.n] as GridXY) }, properties: { role: 'ip-line' } });
    // Tangent runs and arcs drawn separately so a bad curve can turn red on its own.
    design.elements.forEach((el, i) => {
      if (el.kind === 'line') {
        out.push({ id: `el:${i}`, layer: 'alignment', geometry: { type: 'LineString', coordinates: [el.start, el.end] }, properties: { role: 'tangent' } });
        return;
      }
      const c = design.curves.find((x) => Math.abs(x.tcCh - el.ch0) < 1e-6);
      const one = { ...design, elements: [el], startCh: el.ch0, length: el.length };
      out.push({
        id: `el:${i}`,
        layer: 'alignment',
        geometry: { type: 'LineString', coordinates: centreline(one, 1.5) },
        properties: { role: c && !c.fits ? 'arc-bad' : c && belowMin.has(c.ref) ? 'arc-warn' : 'arc', label: c ? `R ${formatDistance(c.radius, conv)}` : '' },
      });
      if (c) {
        out.push({ id: `tc:${i}`, layer: 'alignment', geometry: { type: 'Point', coordinates: c.tc }, properties: { role: 'tp' } });
        out.push({ id: `ct:${i}`, layer: 'alignment', geometry: { type: 'Point', coordinates: c.ct }, properties: { role: 'tp' } });
      }
    });
    ticks.forEach((tk) => {
      out.push({ id: `tick:${tk.ch}`, layer: 'alignment', geometry: { type: 'LineString', coordinates: tickSegment(tk, tk.labelled ? 3 : 1.6) }, properties: { role: tk.labelled ? 'tick-major' : 'tick' } });
      if (tk.labelled) {
        const end = tickSegment(tk, 3)[1];
        out.push({ id: `tlab:${tk.ch}`, layer: 'alignment', geometry: { type: 'Point', coordinates: end }, properties: { role: 'tick-label', label: formatChainage(tk.ch, conv.chainage, conv) } });
      }
    });
    ips.forEach((p, i) =>
      out.push({ id: `ip:${i}`, layer: 'alignment', geometry: { type: 'Point', coordinates: [p.e, p.n] }, properties: { role: 'ip', label: p.name, index: i } }),
    );
    if (hoverCh != null) {
      const at = pointAt(design, hoverCh);
      if (at) out.push({ id: 'hover', layer: 'sections', geometry: { type: 'Point', coordinates: at.p }, properties: { role: 'hover' } });
    }
    return out;
  }, [ips, design, ticks, belowMin.size, conv, hoverCh]); // eslint-disable-line react-hooks/exhaustive-deps

  const layers = useMemo(() => alignmentLayers(features), [features]);

  const setCell = (i: number, k: keyof IpText, v: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const curveAt = (i: number) => design.curves.find((c) => c.ipIndex === i);
  const minR = check.data?.min_radius;

  return (
    <div className="space-y-4 p-3" data-testid="alignment-editor">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Suspense fallback={<div className="h-[480px] animate-pulse rounded-lg border border-border-light bg-surface-secondary" />}>
          <PlanCanvas
            projectId={projectId}
            layers={layers}
            heightClass="h-[500px]"
            inspector={false}
            selectedIds={selected != null ? [`ip:${selected}`] : []}
            onSelect={(ids) => {
              const id = ids.find((x) => x.startsWith('ip:'));
              setSelected(id ? Number(id.slice(3)) : null);
            }}
            pickPoint={
              adding && canWrite
                ? (p: GridXY) => setRows((rs) => [...rs, { name: `IP${rs.length}`, e: inputDistance(p[0], conv), n: inputDistance(p[1], conv), r: rs.length ? inputDistance(50, conv) : '' }])
                : undefined
            }
            pickHint={adding && canWrite ? t('plan.align.pick_hint', { defaultValue: 'Click the plan to place the next IP, or type its position' }) : undefined}
            empty={{ title: t('plan.align.empty', { defaultValue: 'Click the plan to place the intersection points in order, then type a radius at each bend.' }) }}
            toolbarSlot={
              <>
                {canWrite && (
                  <Button size="sm" variant={adding ? 'primary' : 'secondary'} icon={<MousePointerClick size={14} />} aria-pressed={adding} onClick={() => setAdding((a) => !a)}>
                    {t('plan.align.add_ip', { defaultValue: 'Add IP by click' })}
                  </Button>
                )}
                <PlanPrintButton projectId={projectId} layers={layers} conventions={conv} title={request.name} testId="alignment-print" />
              </>
            }
            overlay={
              <PlanLegend testId="alignment-legend">
                {([
                  ['line', t('plan.align.legend.tangent', { defaultValue: 'Tangent' })],
                  ['accent', t('plan.align.legend.arc', { defaultValue: 'Circular curve' })],
                  ['warning', t('plan.align.legend.below_min', { defaultValue: 'Below minimum radius' })],
                  ['error', t('plan.align.legend.overlap', { defaultValue: 'Curves overlap' })],
                ] as const).map(([tok, label]) => (
                  <span key={tok} className="flex items-center gap-1.5">
                    <LineGlyph token={tok} width={2.5} />
                    {label}
                  </span>
                ))}
                <span className="block text-content-tertiary">{t('plan.align.legend.ticks', { defaultValue: 'Ticks every {{a}} m, labels every {{b}} m', a: TICK, b: LABEL })}</span>
              </PlanLegend>
            }
            testId="alignment-plan"
          />
        </Suspense>

        <Card className="p-4 space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="w-32">
              <span className="oe-label">{t('plan.align.start_ch', { defaultValue: 'Start chainage (m)' })}</span>
              <input className="oe-input w-full font-mono" dir="ltr" value={startCh} onChange={(e) => setStartCh(e.target.value)} />
            </label>
            <label className="w-32">
              <span className="oe-label">{t('plan.align.speed', { defaultValue: 'Design speed (km/h)' })}</span>
              <input className="oe-input w-full font-mono" dir="ltr" value={speed} onChange={(e) => setSpeed(e.target.value)} />
            </label>
            <div className="ms-auto text-end text-sm">
              <div className="oe-overline">{t('plan.align.length', { defaultValue: 'Length' })}</div>
              <div className="font-mono">{formatDistance(design.length, conv)}</div>
            </div>
          </div>
          {minR && (
            <p className="text-xs text-content-tertiary" data-testid="min-radius">
              {t('plan.align.min_radius', { defaultValue: 'Minimum radius at {{v}} km/h: {{r}}', v: fmtNumber(minR.speed_kmh, 0), r: formatDistance(minR.radius_m, conv) })}{' '}
              <Badge variant={minR.source === 'pack' ? 'neutral' : 'warning'} size="sm">
                {minR.source === 'pack' ? minR.reference : t('plan.align.demo_table', { defaultValue: 'Demo values, not a standard' })}
              </Badge>
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="oe-table oe-table-compact w-full text-sm" data-testid="ip-table">
              <thead>
                <tr>
                  <th>{t('plan.align.col.ip', { defaultValue: 'IP' })}</th>
                  <th className="text-right">{axes.e}</th>
                  <th className="text-right">{axes.n}</th>
                  <th className="text-right">{t('plan.align.col.radius', { defaultValue: 'R' })}</th>
                  <th className="text-right" title={t('plan.align.tip.deflection', { defaultValue: 'Deflection angle, L or R' })}>{t('plan.align.col.deflection', { defaultValue: 'Δ' })}</th>
                  <th className="text-right" title={t('plan.align.tip.tangent', { defaultValue: 'Tangent length IP to TC' })}>{t('plan.align.col.tangent', { defaultValue: 'T' })}</th>
                  <th className="text-right">{t('plan.align.col.tc', { defaultValue: 'TC' })}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const c = curveAt(i);
                  const tone = c && !c.fits ? 'text-semantic-error' : c && belowMin.has(c.ref) ? 'text-semantic-warning' : '';
                  return (
                    <tr key={i} className={selected === i ? 'bg-surface-secondary' : ''} onClick={() => setSelected(i)}>
                      <td><input className="oe-input-sm w-16 font-mono" dir="ltr" value={r.name} onChange={(e) => setCell(i, 'name', e.target.value)} aria-label={t('plan.align.col.ip', { defaultValue: 'IP' })} /></td>
                      <td><input className="oe-input-sm w-28 text-right font-mono" dir="ltr" value={r.e} onChange={(e) => setCell(i, 'e', e.target.value)} aria-label={axes.e} /></td>
                      <td><input className="oe-input-sm w-28 text-right font-mono" dir="ltr" value={r.n} onChange={(e) => setCell(i, 'n', e.target.value)} aria-label={axes.n} /></td>
                      <td>
                        {i > 0 && i < rows.length - 1 ? (
                          <input className={`oe-input-sm w-20 text-right font-mono ${tone}`} dir="ltr" value={r.r} onChange={(e) => setCell(i, 'r', e.target.value)} aria-label={t('plan.align.col.radius', { defaultValue: 'R' })} />
                        ) : null}
                      </td>
                      <td className={`text-right font-mono ${tone}`}>{c ? `${formatAngle(c.deflectionDeg, conv.angleUnit, 0)} ${c.left ? t('plan.align.left', { defaultValue: 'L' }) : t('plan.align.right', { defaultValue: 'R' })}` : ''}</td>
                      <td className={`text-right font-mono ${tone}`}>{c ? formatDistance(c.tangent, conv, false) : ''}</td>
                      <td className="text-right font-mono">{c ? formatChainage(c.tcCh, conv.chainage, conv) : ''}</td>
                      <td>
                        {canWrite && (
                          <Button size="sm" variant="ghost" icon={<Trash2 size={14} />} aria-label={t('plan.align.remove_ip', { defaultValue: 'Remove IP' })}
                            onClick={(e) => { e.stopPropagation(); setRows((rs) => rs.filter((_, j) => j !== i)); setSelected(null); }} />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rows.length < 2 && <p className="text-sm text-content-tertiary">{t('plan.align.empty', { defaultValue: 'Click the plan to place the intersection points in order, then type a radius at each bend.' })}</p>}
          {design.overlaps.map((o) => (
            <p key={`${o.a}-${o.b}`} className="text-sm text-semantic-error">
              {t('plan.align.overlap', { defaultValue: 'Curves at {{a}} and {{b}} need {{need}} of tangent, the leg has {{have}}.', a: o.a, b: o.b, need: formatDistance(o.need, conv), have: formatDistance(o.have, conv) })}
            </p>
          ))}
          <FindingList items={check.data?.findings ?? []} testId="alignment-findings" />
          {canWrite && (
            <Button icon={<Save size={14} />} disabled={!body || !design.fits} loading={save.isPending} onClick={() => save.mutate()}>
              {t('plan.align.save', { defaultValue: 'Save alignment' })}
            </Button>
          )}
        </Card>
      </div>
      {design.elements.length > 0 && (
        <Card className="p-4 space-y-2">
          <h3 className="oe-card-title">{t('plan.section.title', { defaultValue: 'Long and cross sections' })}</h3>
          <SectionPanel projectId={projectId} design={design} conventions={conv} labelEvery={LABEL} crossEvery={TICK} onHover={setHoverCh} />
        </Card>
      )}
    </div>
  );
}
