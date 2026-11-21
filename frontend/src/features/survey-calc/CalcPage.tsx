// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Survey calculations (/survey/calc): COGO, a field traverse from angles and
 * distances, and a level book. Compute shows the answer and the checks; Save
 * keeps the result in the open project with how it was computed.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Calculator, FileDown, FlaskConical, Save } from 'lucide-react';
import { Badge, Breadcrumb, Button, Card, TabBar } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { ANGLE_UNITS, fmtM, formatAngle, parseCoord, parseRing, type AngleUnit } from './angles';
import { fmtNumber } from '@/shared/lib/formatters';
import { TraverseTabHost } from '@/features/survey-plan/screens/TraverseTabHost';
import {
  COGO_METHODS,
  getClasses,
  runCogo,
  runLevelBook,
  runTraverse,
  saveComputedPoints,
  saveLevelBook,
  saveTraverse,
  type BookRow,
  type CogoMethod,
  type CogoRequest,
  type FieldTraverseIn,
  type Finding,
  type LevelBookIn,
  type StationIn,
} from './api';
import { downloadTraverseReport, getCalcDemo, type AdjustMethod, type CalcDemo } from './adjustment';
import { LsqPanel, TraverseSketch } from './LsqPanel';
import { SurveyLinksPanel } from './SurveyLinksPanel';

type Tab = 'cogo' | 'traverse' | 'level';

const NEEDS: Record<CogoMethod, string[]> = {
  inverse: ['a', 'b'],
  polar: ['a', 'bearing_a', 'distance'],
  bearing_bearing: ['a', 'bearing_a', 'b', 'bearing_b'],
  line_line: ['a', 'b', 'c', 'd'],
  distance_distance: ['a', 'distance_a', 'b', 'distance_b'],
  offset: ['a', 'b', 'c'],
  area: ['ring'],
};

export function Findings({ items }: { items: Finding[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1 text-sm" data-testid="calc-findings">
      {items.map((f, i) => (
        <li key={`${f.rule_id}-${i}`} className="flex gap-2">
          <Badge variant={f.severity === 'error' ? 'error' : 'warning'} size="sm">{f.rule_id}</Badge>
          <span>
            {f.message}
            {f.suggestion && <span className="block text-content-tertiary">{f.suggestion}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Verdict({ value }: { value: string }) {
  const { t } = useTranslation();
  const variant = value === 'pass' ? 'success' : value === 'fail' ? 'error' : 'neutral';
  return (
    <Badge variant={variant} size="sm">
      {t(`survey.cogo.verdict.${value}`, { defaultValue: value === 'pass' ? 'Within class' : value === 'fail' ? 'Outside class' : 'No class picked' })}
    </Badge>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="oe-label">{label}</span>
      {children}
    </label>
  );
}

function UnitSelect({ value, onChange }: { value: AngleUnit; onChange: (u: AngleUnit) => void }) {
  const { t } = useTranslation();
  return (
    <Field label={t('survey.cogo.angle_unit', { defaultValue: 'Angles in' })}>
      <select className="oe-input w-full" value={value} onChange={(e) => onChange(e.target.value as AngleUnit)}>
        {ANGLE_UNITS.map((u) => (
          <option key={u} value={u}>{t(`survey.cogo.unit.${u}`, { defaultValue: u === 'dms' ? 'Degrees, minutes, seconds' : u === 'deg' ? 'Decimal degrees' : 'Gon' })}</option>
        ))}
      </select>
    </Field>
  );
}

function CogoTab({ projectId }: { projectId: string | null }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [method, setMethod] = useState<CogoMethod>('inverse');
  const [unit, setUnit] = useState<AngleUnit>('dms');
  const [v, setV] = useState<Record<string, string>>({});
  const [pointId, setPointId] = useState('');
  const [pick, setPick] = useState(0);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setV((s) => ({ ...s, [k]: e.target.value }));

  const build = (): CogoRequest | null => {
    const body: CogoRequest = { method, angle_unit: unit };
    for (const k of NEEDS[method]) {
      const raw = (v[k] ?? '').trim();
      if (!raw) return null;
      if (k === 'ring') {
        const ring = parseRing(raw);
        if (!ring) return null;
        body.ring = ring;
      } else if (k.startsWith('bearing')) {
        (body as unknown as Record<string, string>)[k] = raw;
      } else if (k.startsWith('distance')) {
        const n = Number(raw.replace(',', '.'));
        if (!Number.isFinite(n)) return null;
        (body as unknown as Record<string, number>)[k] = n;
      } else {
        const c = parseCoord(raw);
        if (!c) return null;
        (body as unknown as Record<string, number[]>)[k] = c;
      }
    }
    return body;
  };
  const body = build();
  const compute = useMutation({ mutationFn: runCogo, onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }) });
  const r = compute.data;
  const chosen = r?.solutions[Math.min(pick, (r?.solutions.length ?? 1) - 1)];
  const save = useMutation({
    mutationFn: () =>
      saveComputedPoints(projectId as string, '', [
        { point_id: pointId.trim(), e: chosen![0]!, n: chosen![1]!, method: r!.method, inputs: r!.inputs },
      ]),
    onSuccess: () => addToast({ type: 'success', title: t('survey.cogo.saved', { defaultValue: 'Point saved to the survey register' }) }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const label = (k: string) =>
    k === 'ring'
      ? t('survey.cogo.field.ring', { defaultValue: 'Corners, one "E N" per line' })
      : k.startsWith('bearing')
        ? t('survey.cogo.field.bearing', { defaultValue: 'Bearing from {{p}}', p: k.slice(-1).toUpperCase() })
        : k.startsWith('distance')
          ? t('survey.cogo.field.distance', { defaultValue: 'Distance (m)' })
          : t('survey.cogo.field.point', { defaultValue: 'Point {{p}} (E N)', p: k.toUpperCase() });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-4 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Field label={t('survey.cogo.method_label', { defaultValue: 'Computation' })}>
            <select className="oe-input w-full" value={method} onChange={(e) => { setMethod(e.target.value as CogoMethod); compute.reset(); }}>
              {COGO_METHODS.map((m) => (
                <option key={m} value={m}>{t(`survey.cogo.method.${m}`, { defaultValue: m })}</option>
              ))}
            </select>
          </Field>
          <UnitSelect value={unit} onChange={setUnit} />
        </div>
        {NEEDS[method].map((k) => (
          <Field key={k} label={label(k)}>
            {k === 'ring' ? (
              <textarea className="oe-input w-full font-mono" rows={5} dir="ltr" value={v[k] ?? ''} onChange={set(k)} />
            ) : (
              <input className="oe-input w-full font-mono" dir="ltr" value={v[k] ?? ''} onChange={set(k)} />
            )}
          </Field>
        ))}
        <Button icon={<Calculator size={14} />} disabled={!body} loading={compute.isPending} onClick={() => body && compute.mutate(body)}>
          {t('survey.cogo.compute', { defaultValue: 'Compute' })}
        </Button>
      </Card>
      {r && (
        <Card className="p-4 space-y-3" data-testid="cogo-result">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            {r.distance != null && (<><dt>{t('survey.cogo.result.distance', { defaultValue: 'Distance' })}</dt><dd><bdi dir="ltr" className="font-mono">{fmtM(r.distance)} m</bdi></dd></>)}
            {r.bearing_deg != null && (<><dt>{t('survey.cogo.result.bearing', { defaultValue: 'Bearing' })}</dt><dd><bdi dir="ltr" className="font-mono">{r.bearing_text || formatAngle(r.bearing_deg, unit)}</bdi></dd></>)}
            {r.chainage != null && (<><dt>{t('survey.cogo.result.chainage', { defaultValue: 'Chainage along A-B' })}</dt><dd><bdi dir="ltr" className="font-mono">{fmtM(r.chainage)} m</bdi></dd></>)}
            {r.offset != null && (<><dt>{t('survey.cogo.result.offset', { defaultValue: 'Offset (right +)' })}</dt><dd><bdi dir="ltr" className="font-mono">{fmtM(r.offset)} m</bdi></dd></>)}
            {r.area != null && (<><dt>{t('survey.cogo.result.area', { defaultValue: 'Area' })}</dt><dd><bdi dir="ltr" className="font-mono">{fmtM(r.area, 2)} m²</bdi></dd></>)}
            {r.perimeter != null && (<><dt>{t('survey.cogo.result.perimeter', { defaultValue: 'Perimeter' })}</dt><dd><bdi dir="ltr" className="font-mono">{fmtM(r.perimeter)} m</bdi></dd></>)}
          </dl>
          {r.solutions.length > 0 && (
            <div className="space-y-1 text-sm">
              {r.solutions.map((s, i) => (
                <label key={i} className="flex items-center gap-2">
                  {r.solutions.length > 1 && <input type="radio" checked={pick === i} onChange={() => setPick(i)} />}
                  <bdi dir="ltr" className="font-mono">E {fmtM(s[0])} N {fmtM(s[1])}</bdi>
                </label>
              ))}
            </div>
          )}
          <Findings items={r.findings} />
          {chosen && projectId && (
            <div className="flex items-end gap-2">
              <Field label={t('survey.cogo.point_id', { defaultValue: 'Point ID' })}>
                <input className="oe-input font-mono" dir="ltr" value={pointId} onChange={(e) => setPointId(e.target.value)} />
              </Field>
              <Button variant="secondary" icon={<Save size={14} />} disabled={!pointId.trim()} loading={save.isPending} onClick={() => save.mutate()}>
                {t('survey.cogo.save_point', { defaultValue: 'Save point' })}
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

/** "1.5" -> 1.5; empty or not a number -> null. */
const numOrNull = (v: string): number | null => {
  const n = Number(v.replace(',', '.'));
  return v.trim() && Number.isFinite(n) ? n : null;
};
const numText = (v: number | null | undefined) => (v == null ? '' : String(v));

function DemoButton({ onLoad }: { onLoad: (demo: CalcDemo) => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const load = useMutation({ mutationFn: getCalcDemo, onSuccess: onLoad, onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }) });
  return (
    <Button size="sm" variant="ghost" icon={<FlaskConical size={14} />} loading={load.isPending} onClick={() => load.mutate()} data-testid="calc-load-demo">
      {t('survey.calc.load_demo', { defaultValue: 'Load demo field book' })}
    </Button>
  );
}

/** "ID angle [distance]" per line. A DMS angle may be one token (108-12-30) or three (108 12 30). */
export function parseStations(text: string, unit: AngleUnit): StationIn[] | null {
  const out: StationIn[] = [];
  for (const line of text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)) {
    const [id, ...rest] = line.split(/\s+/);
    const width = unit === 'dms' && rest.length >= 3 ? 3 : 1;
    if (rest.length < width || rest.length > width + 1) return null;
    const dist = rest.length > width ? Number(rest[width]!.replace(',', '.')) : null;
    if (dist != null && !(Number.isFinite(dist) && dist > 0)) return null;
    out.push({ station_id: id ?? '', angle: rest.slice(0, width).join(' '), distance_m: dist });
  }
  return out.length >= 2 ? out : null;
}

function TraverseTab({ projectId }: { projectId: string | null }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const classes = useQuery({ queryKey: ['survey-calc', 'classes'], queryFn: getClasses, staleTime: 300_000 });
  const [unit, setUnit] = useState<AngleUnit>('dms');
  const [shape, setShape] = useState<'loop' | 'link'>('loop');
  const [sense, setSense] = useState<'right' | 'left'>('right');
  const [name, setName] = useState('Traverse 1');
  const [start, setStart] = useState('');
  const [startId, setStartId] = useState('');
  const [az, setAz] = useState('');
  const [stations, setStations] = useState('');
  const [end, setEnd] = useState('');
  const [closeAz, setCloseAz] = useState('');
  const [cls, setCls] = useState('');
  const [kSec, setKSec] = useState('');
  const [minRatio, setMinRatio] = useState('');
  const [method, setMethod] = useState<AdjustMethod>('bowditch');
  const [instrument, setInstrument] = useState('ts_2');
  const [sd, setSd] = useState({ angle: '', dist: '', ppm: '', centering: '' });
  const [reporting, setReporting] = useState(false);
  const options = (classes.data?.closure ?? []).filter((c) => c.angular_k_sec != null || c.traverse_min_ratio != null);
  const instruments = classes.data?.instruments ?? [];
  const pickInstrument = (key: string) => {
    setInstrument(key);
    const i = instruments.find((x) => x.key === key);
    if (i) setSd({ angle: String(i.angle_sd_sec), dist: String(i.dist_sd_mm), ppm: String(i.dist_ppm), centering: String(i.centering_sd_mm) });
  };
  const loadDemo = (demo: CalcDemo) => {
    const d = demo.traverse;
    setName(d.name);
    setShape(d.shape);
    setUnit(d.angle_unit);
    setSense(d.angle_sense);
    setStartId(d.start.station_id);
    setStart(`${d.start.e} ${d.start.n}`);
    setAz(d.azimuth);
    setStations(d.stations.map((s) => `${s.station_id} ${s.angle}${s.distance_m != null ? ` ${s.distance_m.toFixed(3)}` : ''}`).join('\n'));
    setEnd(d.end ? `${d.end.e} ${d.end.n}` : '');
    setCloseAz(d.closing_azimuth ?? '');
    setCls(d.class_key);
    setKSec(numText(d.angular_k_sec));
    setMinRatio(numText(d.min_ratio));
    setMethod(d.method ?? 'bowditch');
    setInstrument(d.instrument_key ?? '');
    setSd({ angle: numText(d.angle_sd_sec), dist: numText(d.dist_sd_mm), ppm: numText(d.dist_ppm), centering: numText(d.centering_sd_mm) });
    compute.reset();
    save.reset();
  };

  const build = (): FieldTraverseIn | null => {
    const s = parseCoord(start);
    const rows = parseStations(stations, unit);
    if (!s || !rows || !az.trim()) return null;
    const e = shape === 'link' ? parseCoord(end) : null;
    if (shape === 'link' && (!e || !closeAz.trim())) return null;
    return {
      name: name.trim() || 'Traverse',
      shape,
      angle_unit: unit,
      angle_sense: sense,
      start: { station_id: startId.trim(), e: s[0]!, n: s[1]! },
      azimuth: az.trim(),
      stations: rows,
      end: e ? { station_id: '', e: e[0]!, n: e[1]! } : null,
      closing_azimuth: shape === 'link' ? closeAz.trim() : null,
      class_key: cls,
      angular_k_sec: numOrNull(kSec),
      min_ratio: numOrNull(minRatio),
      method,
      instrument_key: method === 'lsq' ? instrument : '',
      angle_sd_sec: method === 'lsq' ? numOrNull(sd.angle) : null,
      dist_sd_mm: method === 'lsq' ? numOrNull(sd.dist) : null,
      dist_ppm: method === 'lsq' ? numOrNull(sd.ppm) : null,
      centering_sd_mm: method === 'lsq' ? numOrNull(sd.centering) : null,
    };
  };
  const body = build();
  const compute = useMutation({ mutationFn: runTraverse, onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }) });
  const report = async (b: FieldTraverseIn) => {
    setReporting(true);
    try {
      const labels: Record<string, string> = {
        title: t('survey.report.title', { defaultValue: 'Traverse adjustment report' }),
        method: t('survey.lsq.method', { defaultValue: 'Adjustment' }),
        bowditch: t('survey.lsq.bowditch', { defaultValue: 'Bowditch (compass rule)' }),
        lsq: t('survey.lsq.lsq', { defaultValue: 'Least squares' }),
        angular: t('survey.report.angular', { defaultValue: 'Angular misclosure' }),
        allowed: t('survey.report.allowed', { defaultValue: 'allowed' }),
        linear: t('survey.report.linear', { defaultValue: 'Linear misclosure' }),
        ratio: t('survey.report.ratio', { defaultValue: 'Relative precision' }),
        length: t('survey.traverse.length', { defaultValue: 'Length (m)' }),
        sigma0: t('survey.report.sigma0', { defaultValue: 'A posteriori sigma0' }),
        chi2: t('survey.report.chi2', { defaultValue: 'Chi-square global test' }),
        pass: t('survey.lsq.chi2_pass', { defaultValue: 'Global test passes' }),
        fail: t('survey.lsq.chi2_fail', { defaultValue: 'Global test fails' }),
        weights: t('survey.lsq.weights', { defaultValue: 'A priori standard deviations' }),
        coordinates: t('survey.lsq.compare', { defaultValue: 'Bowditch and least squares side by side' }),
        station: t('survey.cogo.col.station', { defaultValue: 'Station' }),
        residuals: t('survey.lsq.residuals', { defaultValue: 'Residuals' }),
        observation: t('survey.lsq.observation', { defaultValue: 'Observation' }),
        ellipses: t('survey.lsq.ellipses', { defaultValue: 'Error ellipses, one sigma' }),
        orientation: t('survey.lsq.azimuth', { defaultValue: 'Azimuth of a' }),
        sketch: t('survey.lsq.sketch', { defaultValue: 'Sketch with error ellipses' }),
        fixed: t('survey.lsq.fixed', { defaultValue: 'fixed' }),
      };
      await downloadTraverseReport(b, `${labels.title}: ${b.name}`, labels);
    } catch (e) {
      addToast({ type: 'error', title: getErrorMessage(e) });
    } finally {
      setReporting(false);
    }
  };
  const save = useMutation({
    mutationFn: (b: FieldTraverseIn) => saveTraverse(projectId as string, { ...b, save_points: true }),
    onSuccess: () => addToast({ type: 'success', title: t('survey.cogo.traverse_saved', { defaultValue: 'Traverse saved with its stations as control' }) }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const r = compute.data;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-4 space-y-3">
        <div className="flex justify-end"><DemoButton onLoad={loadDemo} /></div>
        <div className="grid grid-cols-2 gap-2">
          <Field label={t('survey.cogo.name', { defaultValue: 'Name' })}>
            <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t('survey.cogo.shape', { defaultValue: 'Shape' })}>
            <select className="oe-input w-full" value={shape} onChange={(e) => setShape(e.target.value as 'loop' | 'link')}>
              <option value="loop">{t('survey.cogo.shape_loop', { defaultValue: 'Closed loop' })}</option>
              <option value="link">{t('survey.cogo.shape_link', { defaultValue: 'Link between known points' })}</option>
            </select>
          </Field>
          <UnitSelect value={unit} onChange={setUnit} />
          <Field label={t('survey.cogo.sense', { defaultValue: 'Angles turned' })}>
            <select className="oe-input w-full" value={sense} onChange={(e) => setSense(e.target.value as 'right' | 'left')}>
              <option value="right">{t('survey.cogo.sense_right', { defaultValue: 'To the right (clockwise)' })}</option>
              <option value="left">{t('survey.cogo.sense_left', { defaultValue: 'To the left' })}</option>
            </select>
          </Field>
          <Field label={t('survey.cogo.start', { defaultValue: 'Start station ID and E N' })}>
            <div className="flex gap-1">
              <input className="oe-input w-20 font-mono" dir="ltr" value={startId} onChange={(e) => setStartId(e.target.value)} />
              <input className="oe-input w-full font-mono" dir="ltr" value={start} onChange={(e) => setStart(e.target.value)} />
            </div>
          </Field>
          <Field label={shape === 'loop' ? t('survey.cogo.first_azimuth', { defaultValue: 'Azimuth of the first leg' }) : t('survey.cogo.back_azimuth', { defaultValue: 'Backsight azimuth at start' })}>
            <input className="oe-input w-full font-mono" dir="ltr" value={az} onChange={(e) => setAz(e.target.value)} />
          </Field>
        </div>
        <Field label={t('survey.cogo.stations', { defaultValue: 'Stations: ID, angle, distance to the next (m), one per line' })}>
          <textarea className="oe-input w-full font-mono" rows={6} dir="ltr" value={stations} onChange={(e) => setStations(e.target.value)} />
        </Field>
        {shape === 'link' && (
          <div className="grid grid-cols-2 gap-2">
            <Field label={t('survey.cogo.end', { defaultValue: 'Closing point E N' })}>
              <input className="oe-input w-full font-mono" dir="ltr" value={end} onChange={(e) => setEnd(e.target.value)} />
            </Field>
            <Field label={t('survey.cogo.closing_azimuth', { defaultValue: 'Closing azimuth' })}>
              <input className="oe-input w-full font-mono" dir="ltr" value={closeAz} onChange={(e) => setCloseAz(e.target.value)} />
            </Field>
          </div>
        )}
        <Field label={t('survey.cogo.class', { defaultValue: 'Closure class' })}>
          <select className="oe-input w-full" value={cls} onChange={(e) => setCls(e.target.value)}>
            <option value="">{t('survey.cogo.class_none', { defaultValue: 'None, show the numbers only' })}</option>
            {options.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label={t('survey.calc.k_sec', { defaultValue: 'Angular k (seconds), overrides the class' })}>
            <input className="oe-input w-full font-mono" dir="ltr" inputMode="decimal" value={kSec} onChange={(e) => setKSec(e.target.value)} />
          </Field>
          <Field label={t('survey.calc.min_ratio', { defaultValue: 'Minimum ratio 1:x, overrides the class' })}>
            <input className="oe-input w-full font-mono" dir="ltr" inputMode="numeric" value={minRatio} onChange={(e) => setMinRatio(e.target.value)} />
          </Field>
        </div>
        <Field label={t('survey.lsq.method', { defaultValue: 'Adjustment' })}>
          <select className="oe-input w-full" value={method} onChange={(e) => { const m = e.target.value as AdjustMethod; setMethod(m); if (m === 'lsq' && !sd.angle) pickInstrument(instrument || 'ts_2'); }} data-testid="traverse-method">
            <option value="bowditch">{t('survey.lsq.bowditch', { defaultValue: 'Bowditch (compass rule)' })}</option>
            <option value="lsq">{t('survey.lsq.lsq', { defaultValue: 'Least squares' })}</option>
          </select>
        </Field>
        {method === 'lsq' && (
          <div className="grid grid-cols-2 gap-2 rounded-md border border-border-light p-2">
            <Field label={t('survey.lsq.instrument', { defaultValue: 'Instrument class' })}>
              <select className="oe-input w-full" value={instrument} onChange={(e) => pickInstrument(e.target.value)}>
                <option value="">{t('survey.lsq.custom', { defaultValue: 'Own values' })}</option>
                {instruments.map((i) => (
                  <option key={i.key} value={i.key}>{t('survey.lsq.instrument_option', { defaultValue: '{{a}}" total station, {{d}} mm + {{p}} ppm', a: i.angle_sd_sec, d: i.dist_sd_mm, p: i.dist_ppm })}</option>
                ))}
              </select>
            </Field>
            <Field label={t('survey.lsq.sd_angle', { defaultValue: 'Angle sd (seconds)' })}>
              <input className="oe-input w-full font-mono" dir="ltr" inputMode="decimal" value={sd.angle} onChange={(e) => { setInstrument(''); setSd({ ...sd, angle: e.target.value }); }} />
            </Field>
            <Field label={t('survey.lsq.sd_dist', { defaultValue: 'Distance sd (mm) + ppm' })}>
              <div className="flex gap-1">
                <input className="oe-input w-full font-mono" dir="ltr" inputMode="decimal" value={sd.dist} onChange={(e) => { setInstrument(''); setSd({ ...sd, dist: e.target.value }); }} />
                <input className="oe-input w-full font-mono" dir="ltr" inputMode="decimal" value={sd.ppm} onChange={(e) => { setInstrument(''); setSd({ ...sd, ppm: e.target.value }); }} />
              </div>
            </Field>
            <Field label={t('survey.lsq.sd_centering', { defaultValue: 'Centering sd (mm)' })}>
              <input className="oe-input w-full font-mono" dir="ltr" inputMode="decimal" value={sd.centering} onChange={(e) => { setInstrument(''); setSd({ ...sd, centering: e.target.value }); }} />
            </Field>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button icon={<Calculator size={14} />} disabled={!body} loading={compute.isPending} onClick={() => body && compute.mutate(body)} data-testid="traverse-calc-compute">
            {t('survey.cogo.compute', { defaultValue: 'Compute' })}
          </Button>
          {projectId && r && body && (
            <Button variant="secondary" icon={<Save size={14} />} loading={save.isPending} onClick={() => save.mutate(body)}>
              {t('survey.cogo.save_traverse', { defaultValue: 'Save traverse' })}
            </Button>
          )}
          {r && body && (
            <Button variant="secondary" icon={<FileDown size={14} />} loading={reporting} onClick={() => void report(body)} data-testid="traverse-report">
              {t('survey.report.download', { defaultValue: 'Report PDF' })}
            </Button>
          )}
        </div>
      </Card>
      {r && (
        <Card className="p-4 space-y-3" data-testid="traverse-result">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>
              {t('survey.cogo.angular', { defaultValue: 'Angular misclosure {{w}}" over {{n}} angles', w: fmtNumber(r.angular_misclosure_sec, 1), n: r.angle_count })}
              {r.angular_allowed_sec != null && <> · {t('survey.cogo.allowed', { defaultValue: 'allowed {{a}}"', a: fmtNumber(r.angular_allowed_sec, 1) })}</>}
            </span>
            <Verdict value={r.angular_verdict} />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>
              {t('survey.cogo.linear', { defaultValue: 'Linear misclosure {{f}} m, 1:{{ratio}}', f: fmtNumber(r.misclosure_m, 3), ratio: r.ratio ?? '-' })}
            </span>
            <Verdict value={r.linear_verdict} />
          </div>
          <table className="oe-table w-full text-sm">
            <thead>
              <tr>
                <th>{t('survey.cogo.col.station', { defaultValue: 'Station' })}</th>
                <th className="text-right">E</th>
                <th className="text-right">N</th>
                <th className="text-right">{t('survey.cogo.col.angle', { defaultValue: 'Corrected angle' })}</th>
              </tr>
            </thead>
            <tbody>
              {r.stations.map((s) => (
                <tr key={s.station_id}>
                  <td><bdi dir="ltr" className="font-mono">{s.station_id}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(s.e)}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(s.n)}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{formatAngle(s.angle_corrected_deg, unit)}</bdi></td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.lsq ? <LsqPanel result={r} projectId={projectId} /> : <TraverseSketch result={r} lsq={null} projectId={projectId} />}
          <Findings items={r.findings} />
          {projectId && save.data?.traverse && (
            <SurveyLinksPanel projectId={projectId} kind="traverse" targetId={save.data.traverse.id} label={save.data.traverse.name} />
          )}
        </Card>
      )}
    </div>
  );
}

/** "station BS IS FS [distance]" per line; "-" or empty for a reading not taken. */
export function parseBook(text: string): BookRow[] | null {
  const num = (s: string | undefined) => (s == null || s === '-' || s === '' ? null : Number(s.replace(',', '.')));
  const rows: BookRow[] = [];
  for (const line of text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)) {
    const [station, bs, is, fs, dist] = line.split(/\s+/);
    const row = { station: station ?? '', bs: num(bs), is: num(is), fs: num(fs), distance_m: num(dist) };
    if ([row.bs, row.is, row.fs, row.distance_m].some((x) => x != null && !Number.isFinite(x))) return null;
    rows.push(row);
  }
  return rows.length >= 2 ? rows : null;
}

function LevelTab({ projectId }: { projectId: string | null }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const classes = useQuery({ queryKey: ['survey-calc', 'classes'], queryFn: getClasses, staleTime: 300_000 });
  const [method, setMethod] = useState<'rise_fall' | 'hi'>('rise_fall');
  const [name, setName] = useState('Level run 1');
  const [startRl, setStartRl] = useState('');
  const [closeRl, setCloseRl] = useState('');
  const [book, setBook] = useState('');
  const [cls, setCls] = useState('');
  const [kMm, setKMm] = useState('');
  const [writeRls, setWriteRls] = useState(false);
  const options = (classes.data?.closure ?? []).filter((c) => c.level_k_mm != null);
  const rows = parseBook(book);
  const s0 = Number(startRl.replace(',', '.'));
  const body: LevelBookIn | null =
    rows && startRl.trim() && Number.isFinite(s0)
      ? { name: name.trim() || 'Level run', method, start_rl: s0, close_rl: closeRl.trim() ? Number(closeRl.replace(',', '.')) : null, rows, class_key: cls, k_mm: numOrNull(kMm) }
      : null;
  const loadDemo = (demo: CalcDemo) => {
    const d = demo.level_book;
    const cell = (v: number | null | undefined) => (v == null ? '-' : v.toFixed(3));
    setName(d.name);
    setMethod(d.method);
    setStartRl(d.start_rl.toFixed(3));
    setCloseRl(d.close_rl == null ? '' : d.close_rl.toFixed(3));
    setBook(d.rows.map((r) => [r.station, cell(r.bs), cell(r.is), cell(r.fs), r.distance_m == null ? '' : String(r.distance_m)].join(' ').trim()).join('\n'));
    setCls(d.class_key);
    setKMm(numText(d.k_mm));
    compute.reset();
    save.reset();
  };
  const compute = useMutation({ mutationFn: runLevelBook, onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }) });
  const save = useMutation({
    mutationFn: (b: LevelBookIn) => saveLevelBook(projectId as string, { ...b, write_rls: writeRls }),
    onSuccess: (o) => addToast({ type: 'success', title: t('survey.cogo.level_saved', { defaultValue: 'Level book saved, {{n}} points updated', n: o.points_updated }) }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const r = compute.data;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-4 space-y-3">
        <div className="flex justify-end"><DemoButton onLoad={loadDemo} /></div>
        <div className="grid grid-cols-2 gap-2">
          <Field label={t('survey.cogo.name', { defaultValue: 'Name' })}>
            <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t('survey.cogo.level_method', { defaultValue: 'Reduction' })}>
            <select className="oe-input w-full" value={method} onChange={(e) => setMethod(e.target.value as 'rise_fall' | 'hi')}>
              <option value="rise_fall">{t('survey.cogo.rise_fall', { defaultValue: 'Rise and fall' })}</option>
              <option value="hi">{t('survey.cogo.hi', { defaultValue: 'Height of instrument' })}</option>
            </select>
          </Field>
          <Field label={t('survey.cogo.start_rl', { defaultValue: 'Start benchmark RL (m)' })}>
            <input className="oe-input w-full font-mono" dir="ltr" value={startRl} onChange={(e) => setStartRl(e.target.value)} />
          </Field>
          <Field label={t('survey.cogo.close_rl', { defaultValue: 'Closing benchmark RL (m), optional' })}>
            <input className="oe-input w-full font-mono" dir="ltr" value={closeRl} onChange={(e) => setCloseRl(e.target.value)} />
          </Field>
        </div>
        <Field label={t('survey.cogo.book', { defaultValue: 'Readings: station BS IS FS distance (m), "-" when not read' })}>
          <textarea className="oe-input w-full font-mono" rows={7} dir="ltr" value={book} onChange={(e) => setBook(e.target.value)} />
        </Field>
        <Field label={t('survey.cogo.class', { defaultValue: 'Closure class' })}>
          <select className="oe-input w-full" value={cls} onChange={(e) => setCls(e.target.value)}>
            <option value="">{t('survey.cogo.class_none', { defaultValue: 'None, show the numbers only' })}</option>
            {options.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
        </Field>
        <Field label={t('survey.calc.k_mm', { defaultValue: 'Level k (mm per root km), overrides the class' })}>
          <input className="oe-input w-full font-mono" dir="ltr" inputMode="decimal" value={kMm} onChange={(e) => setKMm(e.target.value)} />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button icon={<Calculator size={14} />} disabled={!body} loading={compute.isPending} onClick={() => body && compute.mutate(body)}>
            {t('survey.cogo.compute', { defaultValue: 'Compute' })}
          </Button>
          {projectId && r && body && (
            <>
              <label className="flex items-center gap-1 text-sm">
                <input type="checkbox" checked={writeRls} onChange={(e) => setWriteRls(e.target.checked)} />
                {t('survey.cogo.write_rls', { defaultValue: 'Write adjusted RLs to matching points' })}
              </label>
              <Button variant="secondary" icon={<Save size={14} />} loading={save.isPending} onClick={() => save.mutate(body)}>
                {t('survey.cogo.save_book', { defaultValue: 'Save level book' })}
              </Button>
            </>
          )}
        </div>
      </Card>
      {r && (
        <Card className="p-4 space-y-3" data-testid="level-result">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant={r.arithmetic_ok ? 'success' : 'error'} size="sm">
              {r.arithmetic_ok ? t('survey.cogo.arith_ok', { defaultValue: 'Arithmetic check passes' }) : t('survey.cogo.arith_bad', { defaultValue: 'Arithmetic check fails' })}
            </Badge>
            {r.misclosure_mm != null && (
              <span>
                {t('survey.cogo.level_misclosure', { defaultValue: 'Misclosure {{m}} mm over {{k}} km', m: fmtNumber(r.misclosure_mm, 1), k: fmtNumber(r.distance_km, 3) })}
                {r.allowed_mm != null && <> · {t('survey.cogo.allowed_mm', { defaultValue: 'allowed {{a}} mm', a: fmtNumber(r.allowed_mm, 1) })}</>}
              </span>
            )}
            <Verdict value={r.verdict} />
          </div>
          <div className="overflow-x-auto">
            <table className="oe-table w-full text-sm">
              <thead>
                <tr>
                  <th>{t('survey.cogo.col.station', { defaultValue: 'Station' })}</th>
                  <th className="text-right">{method === 'hi' ? 'HI' : t('survey.cogo.col.rise_fall', { defaultValue: 'Rise / fall' })}</th>
                  <th className="text-right">RL</th>
                  <th className="text-right">{t('survey.cogo.col.correction', { defaultValue: 'Corr. (mm)' })}</th>
                  <th className="text-right">{t('survey.cogo.col.adjusted', { defaultValue: 'Adjusted RL' })}</th>
                </tr>
              </thead>
              <tbody>
                {r.rows.map((row, i) => (
                  <tr key={`${row.station}-${i}`}>
                    <td><bdi dir="ltr" className="font-mono">{row.station}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">
                      {method === 'hi' ? fmtM(row.hi) : row.rise != null ? `+${fmtM(row.rise)}` : row.fall != null ? `-${fmtM(row.fall)}` : ''}
                    </bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(row.rl)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtNumber(row.correction_mm, 1)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(row.rl_adjusted)}</bdi></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Findings items={r.findings} />
          {projectId && save.data?.traverse && (
            <SurveyLinksPanel projectId={projectId} kind="traverse" targetId={save.data.traverse.id} label={save.data.traverse.name} />
          )}
        </Card>
      )}
    </div>
  );
}

export function CalcPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const [tab, setTab] = useState<Tab>('cogo');
  const title = t('survey.cogo.title', { defaultValue: 'Calculations' });
  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }), to: '/survey' }, { label: title }]} />
      <PageHeader
        srTitle={title}
        subtitle={projectId ? undefined : t('survey.cogo.no_project', { defaultValue: 'Compute without a project; open one to save results.' })}
      />
      <TabBar<Tab>
        ariaLabel={title}
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: 'cogo', label: t('survey.cogo.tab.cogo', { defaultValue: 'COGO' }) },
          { id: 'traverse', label: t('survey.cogo.tab.traverse', { defaultValue: 'Traverse' }) },
          { id: 'level', label: t('survey.cogo.tab.level', { defaultValue: 'Level book' }) },
        ]}
      />
      {tab === 'cogo' && <CogoTab projectId={projectId} />}
      {tab === 'traverse' && <TraverseTabHost projectId={projectId} classic={<TraverseTab projectId={projectId} />} />}
      {tab === 'level' && <LevelTab projectId={projectId} />}
    </div>
  );
}

export default CalcPage;
