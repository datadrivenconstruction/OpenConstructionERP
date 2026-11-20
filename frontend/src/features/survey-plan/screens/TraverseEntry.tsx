// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Traverse from the field book. The grid is the page of the book: station,
 * backsight, foresight, both faces, distance (horizontal, or slope with the
 * zenith), instrument and target heights. Every edit is reduced and closed on
 * the server within a quarter second; the sketch shows the observed run grey,
 * the adjusted run blue and the misclosure vector magenta, exaggerated by a
 * printed power of ten. A closure outside its class saves only with a reason.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { BookOpen, FileUp, Plus, Save, Trash2 } from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { getClasses } from '@/features/survey-calc/api';
import type { MapToken } from '../cartography';
import { planColour } from '../cartography';
import { traverseSketch } from '../engine/traverseSketch';
import { usePlanConventions } from '../hooks';
import type { PlanFeature } from '../types';
import { LINEAR_SYMBOL, axisLabelFor, formatAngle, formatCoord, formatDistance, inputDistance, parseDistance, type AngleUnit } from '../units';
import { fieldBookApi, type AngleMode, type BookShape, type DistMode, type FieldBookIn, type ParsedBook } from '../p3api';
import { FindingList } from './FindingList';
import { PlanSketch, type SketchStyle } from './PlanSketch';

interface GridRow {
  station: string;
  bs: string;
  fs: string;
  face_l: string;
  face_r: string;
  dist_mode: DistMode;
  distance: string;
  zenith: string;
  hi: string;
  ht: string;
  note: string;
}

const EMPTY_ROW: GridRow = { station: '', bs: '', fs: '', face_l: '', face_r: '', dist_mode: 'horizontal', distance: '', zenith: '', hi: '', ht: '', note: '' };
const ANGLE_MODES: AngleMode[] = ['right', 'left', 'deflection', 'azimuth'];
const ANGLE_UNITS: AngleUnit[] = ['dms', 'deg', 'gon'];

const str = (v: unknown) => (v == null ? '' : String(v));

/** The parsed book (server) into the grid's text cells. */
export function gridFromParsed(p: ParsedBook): GridRow[] {
  return p.rows.map((r) => ({
    station: r.station,
    bs: str(r.bs),
    fs: str(r.fs),
    face_l: str(r.face_l),
    face_r: str(r.face_r),
    dist_mode: r.dist_mode === 'slope' ? 'slope' : 'horizontal',
    distance: str(r.distance),
    zenith: str(r.zenith),
    hi: str(r.hi),
    ht: str(r.ht),
    note: str(r.note),
  }));
}

function Verdict({ value }: { value: string }) {
  const { t } = useTranslation();
  const variant = value === 'pass' ? 'success' : value === 'fail' ? 'error' : 'neutral';
  return (
    <Badge variant={variant} size="sm">
      {t(`plan.trav.verdict.${value}`, { defaultValue: value === 'pass' ? 'Within class' : value === 'fail' ? 'Outside class' : 'No class' })}
    </Badge>
  );
}

const STYLE: Record<string, (f: PlanFeature) => SketchStyle> = {
  raw: () => ({ stroke: 'ink-2', width: 1.25, dash: '5 4' }),
  adjusted: () => ({ stroke: 'accent', width: 2.25 }),
  station: (f) => ({ shape: 'circle', size: 4.5, stroke: 'accent', fill: 'bg', label: String(f.properties.label ?? '') }),
  control: (f) => ({ shape: 'triangle', size: 6, stroke: 'ink', fill: 'control-fill', label: String(f.properties.label ?? ''), labelDy: 16 }),
  misclosure: (f) => ({ stroke: 'misclosure', width: 2.5, label: String(f.properties.label ?? ''), labelToken: 'misclosure', top: true }),
};

function LegendItem({ token, dash, label }: { token: MapToken; dash?: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <svg width={22} height={8} aria-hidden>
        <path d="M1,4H21" stroke={planColour(token)} strokeWidth={2} strokeDasharray={dash} />
      </svg>
      {label}
    </span>
  );
}

export function TraverseEntry({ projectId, canWrite }: { projectId: string | null; canWrite: boolean }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { conventions: conv } = usePlanConventions(projectId);
  const axes = axisLabelFor(conv.axis);
  const unitSym = LINEAR_SYMBOL[conv.linearUnit];
  const classes = useQuery({ queryKey: ['survey-calc', 'classes'], queryFn: getClasses, staleTime: 300_000 });
  const classOptions = (classes.data?.closure ?? []).filter((c) => c.angular_k_sec != null || c.traverse_min_ratio != null);

  const [name, setName] = useState('');
  const [shape, setShape] = useState<BookShape>('loop');
  const [mode, setMode] = useState<AngleMode>('right');
  const [unit, setUnit] = useState<AngleUnit>(conv.angleUnit);
  const [startId, setStartId] = useState('');
  const [startE, setStartE] = useState('');
  const [startN, setStartN] = useState('');
  const [bsId, setBsId] = useState('');
  const [bsAz, setBsAz] = useState('');
  const [closing, setClosing] = useState('');
  const [endE, setEndE] = useState('');
  const [endN, setEndN] = useState('');
  const [closeAz, setCloseAz] = useState('');
  const [cls, setCls] = useState('');
  const [rows, setRows] = useState<GridRow[]>(() => [{ ...EMPTY_ROW }, { ...EMPTY_ROW }, { ...EMPTY_ROW }]);
  const [reason, setReason] = useState('');
  const [savePoints, setSavePoints] = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);
  const touchedUnit = useRef(false);
  useEffect(() => {
    if (!touchedUnit.current) setUnit(conv.angleUnit);
  }, [conv.angleUnit]);

  const load = (p: ParsedBook) => {
    touchedUnit.current = true;
    setName(p.name);
    setShape(p.shape);
    setMode(p.angle_mode);
    setUnit(p.angle_unit);
    setStartId(p.start.station_id);
    setStartE(inputDistance(p.start.e, conv));
    setStartN(inputDistance(p.start.n, conv));
    setBsId(p.backsight_id);
    setBsAz(str(p.backsight_azimuth));
    setClosing(str(p.closing_angle));
    setEndE(p.end ? inputDistance(p.end.e, conv) : '');
    setEndN(p.end ? inputDistance(p.end.n, conv) : '');
    setCloseAz(str(p.closing_azimuth));
    // The demo book is metric: show it in the project unit.
    setRows(
      gridFromParsed(p).map((r) => ({
        ...r,
        distance: r.distance && conv.linearUnit !== 'm' ? inputDistance(Number(r.distance), conv) : r.distance,
        hi: r.hi && conv.linearUnit !== 'm' ? inputDistance(Number(r.hi), conv) : r.hi,
        ht: r.ht && conv.linearUnit !== 'm' ? inputDistance(Number(r.ht), conv) : r.ht,
      })),
    );
  };
  const demo = useMutation({ mutationFn: fieldBookApi.demo, onSuccess: load, onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }) });
  const parse = useMutation({ mutationFn: fieldBookApi.parse, onSuccess: load, onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }) });

  const len = (s: string) => (s.trim() ? parseDistance(s, conv) : null);
  const body = useMemo<FieldBookIn | null>(() => {
    const e0 = len(startE);
    const n0 = len(startN);
    if (e0 == null || n0 == null) return null;
    const filled = rows.filter((r) => r.station.trim());
    if (filled.length < 2) return null;
    const out = filled.map((r) => ({
      station: r.station.trim(),
      bs: r.bs.trim(),
      fs: r.fs.trim(),
      face_l: r.face_l.trim() || null,
      face_r: r.face_r.trim() || null,
      dist_mode: r.dist_mode,
      distance: len(r.distance),
      zenith: r.dist_mode === 'slope' ? r.zenith.trim() || null : null,
      hi: len(r.hi),
      ht: len(r.ht),
      note: r.note,
    }));
    if (out.some((r) => !r.face_l && !r.face_r)) return null;
    const ee = len(endE);
    const en = len(endN);
    const link = shape === 'link';
    if (link && (ee == null || en == null)) return null;
    if (!bsAz.trim()) return null;
    return {
      name: name.trim() || t('plan.trav.default_name', { defaultValue: 'Traverse' }),
      shape,
      angle_unit: unit,
      angle_mode: mode,
      start: { station_id: startId.trim(), e: e0, n: n0 },
      backsight_id: bsId.trim(),
      backsight_azimuth: bsAz.trim(),
      closing_angle: !link && closing.trim() ? closing.trim() : null,
      end: link && ee != null && en != null ? { station_id: '', e: ee, n: en } : null,
      closing_azimuth: link && closeAz.trim() ? closeAz.trim() : null,
      rows: out,
      class_key: cls,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, shape, unit, mode, startId, startE, startN, bsId, bsAz, closing, endE, endN, closeAz, cls, rows, conv]);

  const [debounced, setDebounced] = useState<FieldBookIn | null>(null);
  useEffect(() => {
    const h = setTimeout(() => setDebounced(body), 250);
    return () => clearTimeout(h);
  }, [body]);
  const result = useQuery({
    queryKey: ['survey-plan', 'field-book', projectId, debounced],
    queryFn: () => fieldBookApi.compute(debounced!, projectId),
    enabled: !!debounced,
    placeholderData: (prev) => prev,
    retry: false,
  });
  const r = debounced ? result.data : undefined;
  const failing = !!r && (r.traverse.angular_verdict === 'fail' || r.traverse.linear_verdict === 'fail');
  const save = useMutation({
    mutationFn: () => fieldBookApi.save(projectId!, { ...body!, note: reason.trim(), save_points: savePoints }),
    onSuccess: (out) =>
      addToast({
        type: 'success',
        title: t('plan.trav.saved', { defaultValue: 'Traverse saved, {{n}} stations in the register', n: out.traverse.points_saved }),
      }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const sketch = useMemo(() => {
    if (!r) return null;
    const ctl = [r.fixed_end, ...(body?.start ? [body.start] : [])];
    return traverseSketch({
      shape: r.traverse.shape,
      unadjusted: r.unadjusted,
      adjusted: r.traverse.stations,
      computedEnd: r.computed_end,
      fixedEnd: r.fixed_end,
      control: shape === 'link' ? ctl : [],
    });
  }, [r, body?.start, shape]);

  const setCell = (i: number, k: keyof GridRow, v: string) => setRows((rs) => rs.map((row, j) => (j === i ? { ...row, [k]: v } : row)));
  const addRow = () => setRows((rs) => [...rs, { ...EMPTY_ROW }]);
  const reduced = (i: number) => {
    const st = rows[i]?.station.trim();
    return st ? r?.rows.find((x) => x.station === st) : undefined;
  };
  const cell = 'oe-input-sm w-full font-mono';
  const tr = r?.traverse;
  const misSec = tr?.angular_misclosure_sec ?? 0;

  return (
    <div className="space-y-4" data-testid="traverse-entry">
      <Card className="p-4 space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="w-48">
            <span className="oe-label">{t('plan.trav.name', { defaultValue: 'Name' })}</span>
            <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="flex h-8 rounded-lg border border-border-light p-0.5" role="group" aria-label={t('plan.trav.shape', { defaultValue: 'Shape' })}>
            {(['loop', 'link'] as BookShape[]).map((s) => (
              <button key={s} type="button" data-oe-segment aria-pressed={shape === s} onClick={() => setShape(s)}
                className={`rounded-sm px-2.5 text-sm ${shape === s ? 'bg-surface-secondary font-medium text-content-primary' : 'text-content-secondary'}`}>
                {s === 'loop' ? t('plan.trav.loop', { defaultValue: 'Closed loop' }) : t('plan.trav.link', { defaultValue: 'Link' })}
              </button>
            ))}
          </div>
          <label>
            <span className="oe-label">{t('plan.trav.angle_mode', { defaultValue: 'Angles booked as' })}</span>
            <select className="oe-select" value={mode} onChange={(e) => setMode(e.target.value as AngleMode)}>
              {ANGLE_MODES.map((m) => (
                <option key={m} value={m}>
                  {t(`plan.trav.mode.${m}`, { defaultValue: { right: 'Angles to the right', left: 'Angles to the left', deflection: 'Deflection angles (R/L)', azimuth: 'Direct azimuths' }[m] })}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="oe-label">{t('plan.trav.angle_unit', { defaultValue: 'Angle unit' })}</span>
            <select className="oe-select" value={unit} onChange={(e) => { touchedUnit.current = true; setUnit(e.target.value as AngleUnit); }}>
              {ANGLE_UNITS.map((u) => (
                <option key={u} value={u}>{t(`plan.trav.unit.${u}`, { defaultValue: { dms: 'Degrees, minutes, seconds', deg: 'Decimal degrees', gon: 'Gon (grads)' }[u] })}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="oe-label">{t('plan.trav.class', { defaultValue: 'Closure class' })}</span>
            <select className="oe-select" value={cls} onChange={(e) => setCls(e.target.value)}>
              <option value="">{t('plan.trav.class_project', { defaultValue: 'Project survey profile' })}</option>
              {classOptions.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </label>
          <div className="ms-auto flex gap-2">
            <Button size="sm" variant="secondary" icon={<BookOpen size={14} />} loading={demo.isPending} onClick={() => demo.mutate()}>
              {t('plan.trav.load_example', { defaultValue: 'Load example' })}
            </Button>
            <Button size="sm" variant="secondary" icon={<FileUp size={14} />} loading={parse.isPending} onClick={() => fileRef.current?.click()}>
              {t('plan.trav.import', { defaultValue: 'Import book (CSV)' })}
            </Button>
            <input ref={fileRef} type="file" accept=".csv,.txt" className="hidden" aria-hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void f.text().then((txt) => parse.mutate(txt)); e.target.value = ''; }} />
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <fieldset className="space-y-1">
            <legend className="oe-label">{t('plan.trav.start', { defaultValue: 'Start station (known)' })}</legend>
            <div className="flex gap-1">
              <input className="oe-input w-20 font-mono" dir="ltr" aria-label={t('plan.trav.col.station', { defaultValue: 'Station' })} value={startId} onChange={(e) => setStartId(e.target.value)} />
              <input className="oe-input w-full font-mono" dir="ltr" placeholder={axes.e} aria-label={axes.e} value={startE} onChange={(e) => setStartE(e.target.value)} />
              <input className="oe-input w-full font-mono" dir="ltr" placeholder={axes.n} aria-label={axes.n} value={startN} onChange={(e) => setStartN(e.target.value)} />
            </div>
          </fieldset>
          <fieldset className="space-y-1">
            <legend className="oe-label">{t('plan.trav.backsight', { defaultValue: 'Backsight and its azimuth' })}</legend>
            <div className="flex gap-1">
              <input className="oe-input w-20 font-mono" dir="ltr" aria-label={t('plan.trav.col.bs', { defaultValue: 'BS' })} value={bsId} onChange={(e) => setBsId(e.target.value)} />
              <input className="oe-input w-full font-mono" dir="ltr" aria-label={t('plan.trav.bs_azimuth', { defaultValue: 'Backsight azimuth' })} value={bsAz} onChange={(e) => setBsAz(e.target.value)} />
            </div>
          </fieldset>
          {shape === 'loop' ? (
            <label className="space-y-1">
              <span className="oe-label">{t('plan.trav.closing_angle', { defaultValue: 'Closing angle at the start (last station to backsight)' })}</span>
              <input className="oe-input w-full font-mono" dir="ltr" value={closing} onChange={(e) => setClosing(e.target.value)} />
            </label>
          ) : (
            <>
              <fieldset className="space-y-1">
                <legend className="oe-label">{t('plan.trav.end', { defaultValue: 'Closing station (known)' })}</legend>
                <div className="flex gap-1">
                  <input className="oe-input w-full font-mono" dir="ltr" placeholder={axes.e} aria-label={axes.e} value={endE} onChange={(e) => setEndE(e.target.value)} />
                  <input className="oe-input w-full font-mono" dir="ltr" placeholder={axes.n} aria-label={axes.n} value={endN} onChange={(e) => setEndN(e.target.value)} />
                </div>
              </fieldset>
              <label className="space-y-1">
                <span className="oe-label">{t('plan.trav.closing_azimuth', { defaultValue: 'Closing azimuth' })}</span>
                <input className="oe-input w-full font-mono" dir="ltr" value={closeAz} onChange={(e) => setCloseAz(e.target.value)} />
              </label>
            </>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="oe-table oe-table-compact w-full text-sm" data-testid="field-book-grid">
            <thead>
              <tr>
                <th>{t('plan.trav.col.station', { defaultValue: 'Station' })}</th>
                <th>{t('plan.trav.col.bs', { defaultValue: 'BS' })}</th>
                <th>{t('plan.trav.col.fs', { defaultValue: 'FS' })}</th>
                <th title={t('plan.trav.tip.fl', { defaultValue: 'Face left (circle left) reading' })}>{t('plan.trav.col.fl', { defaultValue: 'FL' })}</th>
                <th title={t('plan.trav.tip.fr', { defaultValue: 'Face right (circle right) reading, optional' })}>{t('plan.trav.col.fr', { defaultValue: 'FR' })}</th>
                <th className="text-right">{t('plan.trav.col.mean', { defaultValue: 'Mean' })}</th>
                <th className="text-right" title={t('plan.trav.tip.faces', { defaultValue: 'Face left minus face right after the 180 degree flip, in seconds' })}>{t('plan.trav.col.faces', { defaultValue: 'FL-FR"' })}</th>
                <th>{t('plan.trav.col.dist_mode', { defaultValue: 'Dist.' })}</th>
                <th className="text-right">{t('plan.trav.col.distance', { defaultValue: 'Distance ({{u}})', u: unitSym })}</th>
                <th>{t('plan.trav.col.zenith', { defaultValue: 'Zenith' })}</th>
                <th className="text-right">{t('plan.trav.col.hi', { defaultValue: 'HI' })}</th>
                <th className="text-right">{t('plan.trav.col.ht', { defaultValue: 'HT' })}</th>
                <th className="text-right">{t('plan.trav.col.hd', { defaultValue: 'HD' })}</th>
                <th>{t('plan.trav.col.note', { defaultValue: 'Note' })}</th>
                <th aria-label={t('plan.trav.remove_row', { defaultValue: 'Remove row' })} />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const red = reduced(i);
                const faceBad = red?.face_diff_sec != null && Math.abs(red.face_diff_sec) > 30;
                return (
                  <tr key={i}>
                    <td><input className={`${cell} w-16`} dir="ltr" value={row.station} onChange={(e) => setCell(i, 'station', e.target.value)} aria-label={t('plan.trav.col.station', { defaultValue: 'Station' })} /></td>
                    <td><input className={`${cell} w-14`} dir="ltr" value={row.bs} onChange={(e) => setCell(i, 'bs', e.target.value)} aria-label={t('plan.trav.col.bs', { defaultValue: 'BS' })} /></td>
                    <td><input className={`${cell} w-14`} dir="ltr" value={row.fs} onChange={(e) => setCell(i, 'fs', e.target.value)} aria-label={t('plan.trav.col.fs', { defaultValue: 'FS' })} /></td>
                    <td><input className={`${cell} w-28`} dir="ltr" value={row.face_l} onChange={(e) => setCell(i, 'face_l', e.target.value)} aria-label={t('plan.trav.col.fl', { defaultValue: 'FL' })} /></td>
                    <td><input className={`${cell} w-28`} dir="ltr" value={row.face_r} onChange={(e) => setCell(i, 'face_r', e.target.value)} aria-label={t('plan.trav.col.fr', { defaultValue: 'FR' })} /></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono text-content-secondary">{red ? formatAngle(red.angle_deg, unit, conv.angleDecimals) : ''}</bdi></td>
                    <td className={`text-right font-mono ${faceBad ? 'text-semantic-warning' : 'text-content-tertiary'}`}>{red?.face_diff_sec != null ? fmtNumber(red.face_diff_sec, 1) : ''}</td>
                    <td>
                      <select className="oe-select-sm" value={row.dist_mode} onChange={(e) => setCell(i, 'dist_mode', e.target.value)} aria-label={t('plan.trav.col.dist_mode', { defaultValue: 'Dist.' })}>
                        <option value="horizontal">{t('plan.trav.dist.h', { defaultValue: 'HD' })}</option>
                        <option value="slope">{t('plan.trav.dist.s', { defaultValue: 'SD' })}</option>
                      </select>
                    </td>
                    <td><input className={`${cell} w-24 text-right`} dir="ltr" value={row.distance} onChange={(e) => setCell(i, 'distance', e.target.value)} aria-label={t('plan.trav.col.distance', { defaultValue: 'Distance ({{u}})', u: unitSym })} /></td>
                    <td><input className={`${cell} w-28`} dir="ltr" disabled={row.dist_mode !== 'slope'} value={row.zenith} onChange={(e) => setCell(i, 'zenith', e.target.value)} aria-label={t('plan.trav.col.zenith', { defaultValue: 'Zenith' })} /></td>
                    <td><input className={`${cell} w-16 text-right`} dir="ltr" value={row.hi} onChange={(e) => setCell(i, 'hi', e.target.value)} aria-label={t('plan.trav.col.hi', { defaultValue: 'HI' })} /></td>
                    <td><input className={`${cell} w-16 text-right`} dir="ltr" value={row.ht} onChange={(e) => setCell(i, 'ht', e.target.value)} aria-label={t('plan.trav.col.ht', { defaultValue: 'HT' })} /></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono text-content-secondary">{red?.hd != null ? formatDistance(red.hd, conv, false) : ''}</bdi></td>
                    <td><input className={`${cell} w-28 font-sans`} value={row.note} onChange={(e) => setCell(i, 'note', e.target.value)} aria-label={t('plan.trav.col.note', { defaultValue: 'Note' })} /></td>
                    <td>
                      <Button size="sm" variant="ghost" icon={<Trash2 size={14} />} aria-label={t('plan.trav.remove_row', { defaultValue: 'Remove row' })}
                        onClick={() => setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : rs))} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex items-center gap-2 text-xs text-content-tertiary">
          <Button size="sm" variant="ghost" icon={<Plus size={14} />} onClick={addRow}>{t('plan.trav.add_row', { defaultValue: 'Add station' })}</Button>
          <span>{t('plan.trav.hint', { defaultValue: 'Type the book as booked; the mean, the face difference and the horizontal distance appear as you go.' })}</span>
          {result.isError && debounced && <span className="text-semantic-error">{getErrorMessage(result.error)}</span>}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <PlanSketch
          features={sketch?.features ?? []}
          styleFor={(f) => STYLE[String(f.properties.role)]?.(f) ?? null}
          conventions={conv}
          heightClass="h-[440px]"
          testId="traverse-sketch"
        >
          {sketch && (
            <div className="absolute bottom-3 end-3 flex flex-col gap-1 rounded-lg border border-border-light bg-surface-primary/90 px-2.5 py-2 text-xs text-content-secondary">
              <LegendItem token="ink-2" dash="5 4" label={t('plan.trav.legend.observed', { defaultValue: 'As observed' })} />
              <LegendItem token="accent" label={t('plan.trav.legend.adjusted', { defaultValue: 'Adjusted' })} />
              {sketch.misclosure > 0 && (
                <LegendItem token="misclosure" label={t('plan.trav.legend.misclosure', { defaultValue: 'Misclosure, drawn x{{k}}', k: fmtNumber(sketch.scale, 0) })} />
              )}
            </div>
          )}
          {!sketch && (
            <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-content-tertiary">
              {t('plan.trav.sketch_empty', { defaultValue: 'The sketch draws itself as you book the stations. Or load the example.' })}
            </div>
          )}
        </PlanSketch>

        <Card className="p-4 space-y-3" data-testid="traverse-closure">
          {!tr ? (
            <p className="text-sm text-content-tertiary">{t('plan.trav.result_empty', { defaultValue: 'The closure appears once the start, the backsight azimuth and two stations are booked.' })}</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-border-light px-3 py-2">
                  <div className="oe-overline">{t('plan.trav.angular', { defaultValue: 'Angular misclosure' })}</div>
                  <div className="font-mono text-lg">{misSec > 0 ? '+' : misSec < 0 ? '−' : ''}{formatAngle(Math.abs(misSec) / 3600, unit, 1)}</div>
                  <div className="text-xs text-content-tertiary">
                    {tr.angular_allowed_sec != null
                      ? t('plan.trav.allowed', { defaultValue: 'allowed {{a}} ({{k}}" x √{{n}})', a: formatAngle(tr.angular_allowed_sec / 3600, unit, 1), k: fmtNumber(tr.angular_k_sec ?? 0, 0), n: tr.angle_count })
                      : t('plan.trav.no_allowance', { defaultValue: 'No allowance: pick a closure class or set the project profile' })}
                  </div>
                  <div className="mt-1"><Verdict value={tr.angular_verdict} /></div>
                </div>
                <div className="rounded-xl border border-border-light px-3 py-2">
                  <div className="oe-overline">{t('plan.trav.linear', { defaultValue: 'Linear misclosure' })}</div>
                  <div className="font-mono text-lg">{tr.ratio ? `1:${fmtNumber(tr.ratio, 0)}` : formatDistance(tr.misclosure_m, conv)}</div>
                  <div className="text-xs text-content-tertiary">
                    {t('plan.trav.f_over_l', { defaultValue: 'f {{f}} over {{l}}', f: formatDistance(tr.misclosure_m, conv), l: formatDistance(tr.length_m, conv) })}
                    {tr.min_ratio != null && <> · {t('plan.trav.min_ratio', { defaultValue: 'class 1:{{r}}', r: fmtNumber(tr.min_ratio, 0) })}</>}
                  </div>
                  <div className="mt-1"><Verdict value={tr.linear_verdict} /></div>
                </div>
              </div>
              <table className="oe-table oe-table-compact w-full text-sm">
                <thead>
                  <tr>
                    <th>{t('plan.trav.col.station', { defaultValue: 'Station' })}</th>
                    <th className="text-right">{axes.e}</th>
                    <th className="text-right">{axes.n}</th>
                  </tr>
                </thead>
                <tbody>
                  {tr.stations.map((s) => (
                    <tr key={s.station_id}>
                      <td><bdi dir="ltr" className="font-mono">{s.station_id}</bdi></td>
                      <td className="text-right"><bdi dir="ltr" className="font-mono">{formatCoord(s.e, conv)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr" className="font-mono">{formatCoord(s.n, conv)}</bdi></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <FindingList items={tr.findings} testId="traverse-findings" />
              {projectId && canWrite && (
                <div className="space-y-2 border-t border-border-light pt-3">
                  {failing && (
                    <label className="block">
                      <span className="oe-label">{t('plan.trav.reason', { defaultValue: 'Reason to accept a closure outside its class' })}</span>
                      <textarea className="oe-textarea w-full" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
                    </label>
                  )}
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={savePoints} onChange={(e) => setSavePoints(e.target.checked)} />
                    {t('plan.trav.save_points', { defaultValue: 'Add the adjusted stations to the point register' })}
                  </label>
                  <Button icon={<Save size={14} />} disabled={!body || (failing && !reason.trim())} loading={save.isPending} onClick={() => save.mutate()}>
                    {t('plan.trav.accept', { defaultValue: 'Accept and save' })}
                  </Button>
                </div>
              )}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
