// Design module (ERP side of the design editor link).
import { Suspense, lazy, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Plus, Trash2, Undo2, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import { areaM2, fromPolygon, perimeterM, plotProblem, toPolygon, type GeoPolygon, type LngLat } from './data/polygon';
import { parseInput, fieldSpec } from './data/briefModel';
import { PLOT_POINTER, getAt, type BriefDoc } from './data/briefModel';
import { ProvenanceControl, errorText, tr, type ProvenanceProps } from './BriefFields';
import type { SchemaError } from './data/schemaCheck';

const PlotMap = lazy(() => import('./PlotMap'));

function webglAvailable(): boolean {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

export interface PlotEditorProps {
  doc: BriefDoc;
  errors: SchemaError[];
  focus: { lat: number; lng: number } | null;
  onChange: (pointer: string, value: unknown) => void;
  provenance: Omit<ProvenanceProps, 'doc' | 'pointer'>;
}

/** Number in the app language (grouping, decimal mark, digits). */
function formatNumber(lang: string, value: number, digits: number): string {
  const options = { maximumFractionDigits: digits, minimumFractionDigits: digits };
  try {
    return new Intl.NumberFormat(lang, options).format(value);
  } catch {
    return new Intl.NumberFormat('en', options).format(value);
  }
}

const NUMBER = fieldSpec('/massing/floor_height_m'); // any plain number field: same reading rules for coordinates
/** Corners from typed cells, or null while any cell is empty or not a plain number. */
function readPoints(rows: string[][]): LngLat[] | null {
  const out: LngLat[] = [];
  for (const [a, b] of rows) {
    const lon = parseInput(NUMBER, a ?? '');
    const lat = parseInput(NUMBER, b ?? '');
    if (!lon.ok || !lat.ok || typeof lon.value !== 'number' || typeof lat.value !== 'number') return null;
    out.push([lon.value, lat.value]);
  }
  return out;
}
const toRows = (points: LngLat[]) => points.map(([lon, lat]) => [String(lon), String(lat)]);

/**
 * Corner coordinates as text: the way to enter or edit the outline without a pointer. Rows that do
 * not form a valid outline yet stay as typed; a valid outline goes to the brief at once.
 */
function CornerTable({ points, rows, onRows, onPoints }: {
  points: LngLat[];
  rows: string[][] | null;
  onRows: (rows: string[][] | null) => void;
  onPoints: (points: LngLat[]) => void;
}) {
  const { t } = useTranslation();
  // An outline needs three corners: offer three empty rows to start from.
  const shown = rows ?? (points.length ? toRows(points) : [['', ''], ['', ''], ['', '']]);

  // The text stays as typed ("13." must survive on its way to "13.4"); the brief gets every valid outline.
  const edit = (next: string[][]) => {
    onRows(next);
    const pts = readPoints(next);
    if (pts && plotProblem(pts) === null) onPoints(pts);
  };
  const bad = (text: string) => text.trim() !== '' && !parseInput(NUMBER, text).ok;
  const cell = 'h-9 w-full min-w-0 rounded-lg border bg-surface-primary px-2 text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue';

  return (
    <fieldset className="flex flex-col gap-2 rounded-lg border border-border-light p-3">
      <legend className="px-1 text-sm font-medium">{tr(t, 'design.plot.coords_title')}</legend>
      <p id="plot-coords-hint" className="text-xs text-content-tertiary">{tr(t, 'design.plot.coords_hint')}</p>
      {shown.map(([lon, lat], i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2">
          {([[lon, 0, 'design.plot.lon'], [lat, 1, 'design.plot.lat']] as const).map(([text, k, label]) => (
            <input
              key={k}
              inputMode="decimal"
              autoComplete="off"
              className={`${cell} ${bad(text ?? '') ? 'border-semantic-error' : 'border-border'}`}
              aria-label={tr(t, label, { n: i + 1 })}
              aria-describedby="plot-coords-hint"
              aria-invalid={bad(text ?? '')}
              value={text}
              onChange={(e) => edit(shown.map((r, j) => (j === i ? (k === 0 ? [e.target.value, r[1]!] : [r[0]!, e.target.value]) : r)))}
            />
          ))}
          <Button size="sm" variant="ghost" aria-label={tr(t, 'design.plot.remove_corner', { n: i + 1 })}
            onClick={() => edit(shown.filter((_, j) => j !== i))}>
            <X size={14} aria-hidden />
          </Button>
        </div>
      ))}
      <div>
        <Button size="sm" variant="secondary" onClick={() => onRows([...shown, ['', '']])}>
          <Plus size={14} aria-hidden /> {tr(t, 'design.plot.add_corner')}
        </Button>
      </div>
    </fieldset>
  );
}

export function PlotEditor({ doc, errors, focus, onChange, provenance }: PlotEditorProps) {
  const { t, i18n } = useTranslation();
  const stored = getAt(doc, PLOT_POINTER) as GeoPolygon | undefined;
  const [drawing, setDrawing] = useState(false);
  const [draft, setDraft] = useState<LngLat[]>([]);
  const [canMap] = useState(webglAvailable);
  const [rows, setRows] = useState<string[][] | null>(null);

  const points = drawing ? draft : fromPolygon(stored);
  const typed = useMemo(() => (rows ? readPoints(rows) : null), [rows]);
  const problem = (typed ?? points).length ? plotProblem(typed ?? points) : null;
  const current = typed ?? points;
  const measures = useMemo(
    () => (problem === null && current.length >= 3 ? { area: areaM2(current), perimeter: perimeterM(current) } : null),
    [current, problem],
  );

  const store = (next: LngLat[]) => {
    if (plotProblem(next) === null) onChange(PLOT_POINTER, toPolygon(next, stored));
  };

  const handleMapChange = (next: LngLat[]) => {
    setRows(null);
    if (drawing) setDraft(next);
    else store(next); // dragging a corner of the stored outline
  };

  const applyTyped = (next: LngLat[]) => (drawing ? setDraft(next) : store(next));

  const finish = () => {
    if (plotProblem(draft) !== null) return;
    store(draft);
    setRows(null);
    setDrawing(false);
    setDraft([]);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-content-secondary">{tr(t, 'design.plot.hint')}</p>
        <ProvenanceControl doc={doc} pointer={PLOT_POINTER} {...provenance} />
      </div>
      <div
        role="region"
        aria-label={tr(t, 'design.plot.map_label')}
        className="relative h-[420px] overflow-hidden rounded-lg border border-border-light bg-surface-secondary"
      >
        {canMap ? (
          <Suspense fallback={null}>
            <PlotMap points={points} drawing={drawing} focus={focus} onChange={handleMapChange} />
          </Suspense>
        ) : (
          <p className="p-6 text-sm text-content-secondary">{tr(t, 'design.plot.no_webgl')}</p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {drawing ? (
          <>
            <Button size="sm" onClick={finish} disabled={plotProblem(draft) !== null}>
              {tr(t, 'design.plot.finish')}
            </Button>
            <Button size="sm" variant="secondary" disabled={!draft.length} onClick={() => { setRows(null); setDraft(draft.slice(0, -1)); }}>
              <Undo2 size={14} aria-hidden /> {tr(t, 'design.plot.undo')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setRows(null); setDrawing(false); setDraft([]); }}>
              {tr(t, 'design.plot.cancel')}
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="secondary" disabled={!canMap} onClick={() => { setRows(null); setDraft([]); setDrawing(true); }}>
              <Pencil size={14} aria-hidden /> {tr(t, stored ? 'design.plot.redraw' : 'design.plot.draw')}
            </Button>
            {stored && (
              <Button size="sm" variant="ghost" onClick={() => { setRows(null); onChange(PLOT_POINTER, undefined); }}>
                <Trash2 size={14} aria-hidden /> {tr(t, 'design.plot.clear')}
              </Button>
            )}
          </>
        )}
        <dl className="ml-auto flex flex-wrap gap-x-5 gap-y-1 text-sm" data-testid="plot-measures">
          <div className="flex gap-1.5">
            <dt className="text-content-tertiary">{tr(t, 'design.plot.corners')}</dt>
            <dd className="font-medium tabular-nums">{current.length}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-content-tertiary">{tr(t, 'design.plot.area')}</dt>
            <dd className="font-medium tabular-nums">{measures ? `${formatNumber(i18n.language, measures.area, 0)} ${tr(t, 'design.unit.m2')}` : '—'}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-content-tertiary">{tr(t, 'design.plot.perimeter')}</dt>
            <dd className="font-medium tabular-nums">{measures ? `${formatNumber(i18n.language, measures.perimeter, 1)} ${tr(t, 'design.unit.m')}` : '—'}</dd>
          </div>
        </dl>
      </div>
      <CornerTable points={points} rows={rows} onRows={setRows} onPoints={applyTyped} />
      {!points.length && !rows?.length && !drawing && <p className="text-sm text-content-tertiary">{tr(t, 'design.plot.none')}</p>}
      {problem && current.length > 0 && (drawing || rows ? current.length >= 3 : true) && (
        <p role="alert" className="text-sm text-semantic-error">{tr(t, `design.plot.problem.${problem}`)}</p>
      )}
      {errors.map((e) => (
        <p key={`${e.pointer}-${e.code}`} role="alert" className="text-sm text-semantic-error">
          {e.pointer}: {errorText(t, e)}
        </p>
      ))}
    </div>
  );
}
