// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Start a compare: pick the older and newer revision, align, preview, save.
 *
 * PDF sheets are rendered and diffed here in the browser; the preview shows
 * every region before anything is stored, so the reviewer can change the
 * alignment or tolerance first. DWG/DXF revisions are diffed by the server.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { Crosshair, GitCompare, Loader2, Save } from 'lucide-react';

import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { takeoffApi } from '@/features/takeoff/api';
import { fetchDrawings, fetchDrawingVersions } from '@/features/dwg-takeoff/api';
import { drawingCompareApi, type Comparison, type SourceKind } from '../api';
import { computeSheetDiff, DEFAULT_SETTINGS, pixelMatrix, type AlignMode, type SheetDiffResult } from '../lib/sheetDiff';
import { asRaster, overlayCanvas, regionThumbnail, useSheetPair } from '../lib/useSheetPair';
import type { Pt } from '../lib/transform';
import { CompareViewer, type ViewerMode, type ViewerRegion } from './CompareViewer';

/** Thumbnails are generated for at most this many regions (payload stays small). */
const MAX_THUMBNAILS = 200;

interface NewComparePanelProps {
  projectId: string;
  initialOld?: string | null;
  initialNew?: string | null;
  onSaved: (cmp: Comparison) => void;
}

const SELECT =
  'w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm focus:border-oe-blue focus:outline-none';

export function NewComparePanel({ projectId, initialOld, initialNew, onSaved }: NewComparePanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [kind, setKind] = useState<SourceKind>('pdf');

  /* ── PDF sides ───────────────────────────────────────────────────── */
  const docsQuery = useQuery({
    queryKey: ['drawing-compare', 'takeoff-docs', projectId],
    queryFn: () => takeoffApi.listDocuments(projectId),
    enabled: !!projectId,
  });
  const docs = useMemo(() => docsQuery.data ?? [], [docsQuery.data]);
  const [oldId, setOldId] = useState<string>(initialOld ?? '');
  const [newId, setNewId] = useState<string>(initialNew ?? '');
  const [oldPage, setOldPage] = useState(1);
  const [newPage, setNewPage] = useState(1);
  const [align, setAlign] = useState<AlignMode>('auto');
  const [tolerance, setTolerance] = useState(DEFAULT_SETTINGS.tolerance);
  const [compareText, setCompareText] = useState(true);
  const [mode, setMode] = useState<ViewerMode>('overlay');
  const [picks, setPicks] = useState<{ old: Pt[]; new: Pt[] }>({ old: [], new: [] });
  const [result, setResult] = useState<SheetDiffResult | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  // Offer the revision the newer one supersedes, from the documents chain.
  useEffect(() => {
    if (!newId || oldId) return;
    let alive = true;
    drawingCompareApi
      .previousRevision(projectId, newId)
      .then((r) => {
        if (alive && r.previous_document_id && docs.some((d) => d.id === r.previous_document_id)) setOldId(r.previous_document_id);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [newId, oldId, projectId, docs]);

  const pair = useSheetPair(kind === 'pdf' ? oldId || null : null, kind === 'pdf' ? newId || null : null, oldPage, newPage);
  useEffect(() => {
    setResult(null);
    setPicks({ old: [], new: [] });
  }, [oldId, newId, oldPage, newPage]);

  const pickSide: 'old' | 'new' | null =
    align === 'manual' && !result ? (picks.old.length <= picks.new.length && picks.old.length < 2 ? 'old' : picks.new.length < 2 ? 'new' : null) : null;
  const manualReady = picks.old.length === 2 && picks.new.length === 2;

  const run = () => {
    if (!pair.old || !pair.new) return;
    const toPt = (p: Pt, scale: number): Pt => [p[0] / scale, p[1] / scale];
    const res = computeSheetDiff(asRaster(pair.old), asRaster(pair.new), {
      ...DEFAULT_SETTINGS,
      alignment: align,
      tolerance,
      compareText,
      manualPoints:
        align === 'manual' && manualReady
          ? {
              old: [toPt(picks.old[0]!, pair.old.scale), toPt(picks.old[1]!, pair.old.scale)],
              new: [toPt(picks.new[0]!, pair.new.scale), toPt(picks.new[1]!, pair.new.scale)],
            }
          : null,
    });
    setResult(res);
    setMode('overlay');
  };

  const overlay = useMemo(() => (result ? overlayCanvas(result.diff) : null), [result]);
  const regions: ViewerRegion[] = useMemo(() => {
    if (!result || !pair.new) return [];
    const s = pair.new.scale;
    return result.changes.map((c, i) => ({ id: String(i), seq: i + 1, kind: c.kind, x: c.x * s, y: c.y * s, w: c.w * s, h: c.h * s }));
  }, [result, pair.new]);

  const savePdf = useMutation({
    mutationFn: async () => {
      if (!result || !pair.new || !pair.old || !overlay) throw new Error('nothing to save');
      const s = pair.new.scale;
      return drawingCompareApi.createPdf({
        project_id: projectId,
        old_ref_id: oldId,
        new_ref_id: newId,
        old_page: oldPage,
        new_page: newPage,
        page_width: pair.new.widthPt,
        page_height: pair.new.heightPt,
        alignment: {
          method: align,
          matrix: result.matrix,
          confidence: result.confidence,
          points_old: align === 'manual' ? picks.old.map((p) => [p[0] / pair.old!.scale, p[1] / pair.old!.scale] as Pt) : [],
          points_new: align === 'manual' ? picks.new.map((p) => [p[0] / s, p[1] / s] as Pt) : [],
        },
        settings: { tolerance, compare_text: compareText, raster_scale: s, cell: DEFAULT_SETTINGS.cell, gap: DEFAULT_SETTINGS.gap },
        changes: result.changes.map((c, i) => ({
          ...c,
          page: newPage,
          w: Math.max(c.w, 0.01),
          h: Math.max(c.h, 0.01),
          thumbnail: i < MAX_THUMBNAILS ? regionThumbnail(overlay, { x: c.x * s, y: c.y * s, w: c.w * s, h: c.h * s }) : null,
        })),
      });
    },
    onSuccess: (cmp) => {
      addToast({ type: 'success', title: t('drawing_compare.saved', { defaultValue: 'Comparison saved' }) });
      onSaved(cmp);
    },
    onError: (err) => addToast({ type: 'error', title: t('drawing_compare.save_failed', { defaultValue: 'Could not save the comparison' }), message: getErrorMessage(err) }),
  });

  /* ── DWG sides ───────────────────────────────────────────────────── */
  const drawingsQuery = useQuery({
    queryKey: ['drawing-compare', 'dwg-drawings', projectId],
    queryFn: () => fetchDrawings(projectId),
    enabled: !!projectId && kind === 'dwg',
  });
  const [oldDrawing, setOldDrawing] = useState('');
  const [newDrawing, setNewDrawing] = useState('');
  const [oldVersion, setOldVersion] = useState('');
  const [newVersion, setNewVersion] = useState('');
  const oldVersions = useQuery({
    queryKey: ['drawing-compare', 'dwg-versions', oldDrawing],
    queryFn: () => fetchDrawingVersions(oldDrawing),
    enabled: !!oldDrawing,
  });
  const newVersions = useQuery({
    queryKey: ['drawing-compare', 'dwg-versions', newDrawing],
    queryFn: () => fetchDrawingVersions(newDrawing),
    enabled: !!newDrawing,
  });
  const saveDwg = useMutation({
    mutationFn: () =>
      drawingCompareApi.createDwg({
        project_id: projectId,
        old_drawing_id: oldDrawing,
        new_drawing_id: newDrawing,
        old_version_id: oldVersion || null,
        new_version_id: newVersion || null,
      }),
    onSuccess: (cmp) => {
      addToast({ type: 'success', title: t('drawing_compare.saved', { defaultValue: 'Comparison saved' }) });
      onSaved(cmp);
    },
    onError: (err) => addToast({ type: 'error', title: t('drawing_compare.save_failed', { defaultValue: 'Could not save the comparison' }), message: getErrorMessage(err) }),
  });
  const dwgSame = !!oldDrawing && oldDrawing === newDrawing && (oldVersion || '') === (newVersion || '');

  const pageOptions = (docId: string) => {
    const n = docs.find((d) => d.id === docId)?.pages ?? 1;
    return Array.from({ length: Math.max(1, n) }, (_, i) => i + 1);
  };
  const samePdf = !!oldId && oldId === newId && oldPage === newPage;

  return (
    <div className="flex flex-col gap-3" data-testid="drawing-compare-new">
      <div className="flex gap-1" role="tablist">
        {(['pdf', 'dwg'] as SourceKind[]).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            onClick={() => setKind(k)}
            className={clsx('rounded-md border px-3 py-1 text-sm', kind === k ? 'border-oe-blue bg-oe-blue/10 text-oe-blue' : 'border-border')}
          >
            {k === 'pdf'
              ? t('drawing_compare.kind_pdf', { defaultValue: 'PDF sheets' })
              : t('drawing_compare.kind_dwg', { defaultValue: 'DWG / DXF drawings' })}
          </button>
        ))}
      </div>

      {kind === 'pdf' ? (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            {([
              ['old', oldId, setOldId, oldPage, setOldPage],
              ['new', newId, setNewId, newPage, setNewPage],
            ] as const).map(([side, value, setValue, page, setPage]) => (
              <fieldset key={side} className="rounded-lg border border-border p-2">
                <legend className={clsx('px-1 text-xs font-semibold', side === 'old' ? 'text-red-600' : 'text-blue-600')}>
                  {side === 'old'
                    ? t('drawing_compare.old_revision', { defaultValue: 'Older revision' })
                    : t('drawing_compare.new_revision', { defaultValue: 'Newer revision' })}
                </legend>
                <div className="flex gap-2">
                  <select className={SELECT} value={value} onChange={(e) => setValue(e.target.value)} aria-label={side}>
                    <option value="">{t('drawing_compare.pick_document', { defaultValue: 'Choose a drawing' })}</option>
                    {docs.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.filename}
                      </option>
                    ))}
                  </select>
                  <select className={clsx(SELECT, 'w-24')} value={page} onChange={(e) => setPage(Number(e.target.value))} aria-label={t('drawing_compare.page', { defaultValue: 'Page' })}>
                    {pageOptions(value).map((p) => (
                      <option key={p} value={p}>
                        {t('drawing_compare.page_n', { defaultValue: 'Page {{page}}', page: p })}
                      </option>
                    ))}
                  </select>
                </div>
              </fieldset>
            ))}
          </div>
          {docsQuery.isSuccess && docs.length < 2 && (
            <p className="text-sm text-content-secondary">
              {t('drawing_compare.need_two_docs', { defaultValue: 'Upload both revisions in Takeoff first; they appear here as drawings to compare.' })}
            </p>
          )}

          <div className="flex flex-wrap items-end gap-4 text-sm">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-content-secondary">{t('drawing_compare.alignment', { defaultValue: 'Alignment' })}</span>
              <select className={SELECT} value={align} onChange={(e) => { setAlign(e.target.value as AlignMode); setPicks({ old: [], new: [] }); if (e.target.value === 'manual') setMode('side'); }}>
                <option value="auto">{t('drawing_compare.align_auto', { defaultValue: 'Automatic (frame and title block)' })}</option>
                <option value="manual">{t('drawing_compare.align_manual', { defaultValue: 'Manual, two points' })}</option>
                <option value="none">{t('drawing_compare.align_none', { defaultValue: 'None, same frame' })}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-content-secondary">
                {t('drawing_compare.tolerance', { defaultValue: 'Tolerance: {{px}} px', px: tolerance })}
              </span>
              <input type="range" min={0} max={6} step={1} value={tolerance} onChange={(e) => setTolerance(Number(e.target.value))} />
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={compareText} onChange={(e) => setCompareText(e.target.checked)} />
              {t('drawing_compare.compare_text', { defaultValue: 'Compare the text layer too' })}
            </label>
            <Button
              variant="primary"
              icon={<GitCompare size={14} />}
              disabled={!pair.old || !pair.new || samePdf || (align === 'manual' && !manualReady)}
              onClick={run}
              data-testid="drawing-compare-run"
            >
              {t('drawing_compare.run', { defaultValue: 'Compare' })}
            </Button>
          </div>
          {samePdf && <p className="text-sm text-amber-700">{t('drawing_compare.same_revision', { defaultValue: 'Choose two different revisions or pages.' })}</p>}
          {align === 'manual' && pickSide && (
            <p className="flex items-center gap-1 text-sm text-oe-blue">
              <Crosshair size={14} />
              {pickSide === 'old'
                ? t('drawing_compare.pick_old', { defaultValue: 'Click mark {{n}} on the older revision (left).', n: picks.old.length + 1 })
                : t('drawing_compare.pick_new', { defaultValue: 'Click the same mark {{n}} on the newer revision (right).', n: picks.new.length + 1 })}
            </p>
          )}

          {pair.loading && (
            <p className="flex items-center gap-2 text-sm text-content-secondary">
              <Loader2 size={14} className="animate-spin" />
              {t('drawing_compare.rendering', { defaultValue: 'Rendering both sheets...' })}
            </p>
          )}
          {pair.error && <p className="text-sm text-red-600">{pair.error}</p>}

          {pair.old && pair.new && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex gap-1">
                  {(['overlay', 'side'] as ViewerMode[]).map((m) => (
                    <button key={m} type="button" onClick={() => setMode(m)} className={clsx('rounded border px-2 py-0.5 text-xs', mode === m ? 'border-oe-blue text-oe-blue' : 'border-border')}>
                      {m === 'overlay'
                        ? t('drawing_compare.mode_overlay', { defaultValue: 'Overlay' })
                        : t('drawing_compare.mode_side', { defaultValue: 'Side by side' })}
                    </button>
                  ))}
                </div>
                {result && (
                  <div className="flex items-center gap-3 text-sm">
                    <span>
                      {t('drawing_compare.preview_count', { defaultValue: 'Changes found: {{n}}', n: result.changes.length })}
                      {result.confidence !== null &&
                        ` · ${t('drawing_compare.alignment_confidence', { defaultValue: 'alignment {{value}}%', value: Math.round(result.confidence * 100) })}`}
                    </span>
                    <Button variant="primary" icon={<Save size={14} />} loading={savePdf.isPending} onClick={() => savePdf.mutate()} data-testid="drawing-compare-save">
                      {t('drawing_compare.save', { defaultValue: 'Save comparison' })}
                    </Button>
                  </div>
                )}
              </div>
              <CompareViewer
                mode={align === 'manual' && !result ? 'side' : mode}
                newCanvas={pair.new.canvas}
                oldCanvas={pair.old.canvas}
                oldToNew={pixelMatrix(result?.matrix ?? [1, 0, 0, 1, 0, 0], pair.old.scale, pair.new.scale)}
                oldToNewUnaligned={pixelMatrix([1, 0, 0, 1, 0, 0], pair.old.scale, pair.new.scale)}
                overlayCanvas={overlay}
                regions={regions}
                selectedId={selected}
                onSelect={setSelected}
                pickSide={pickSide}
                onPick={(side, pt) => setPicks((p) => ({ ...p, [side]: [...p[side], pt].slice(0, 2) }))}
                marks={align === 'manual' ? picks : undefined}
              />
            </>
          )}
        </>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            {([
              ['old', oldDrawing, setOldDrawing, oldVersion, setOldVersion, oldVersions.data],
              ['new', newDrawing, setNewDrawing, newVersion, setNewVersion, newVersions.data],
            ] as const).map(([side, drawing, setDrawing, version, setVersion, versions]) => (
              <fieldset key={side} className="rounded-lg border border-border p-2">
                <legend className={clsx('px-1 text-xs font-semibold', side === 'old' ? 'text-red-600' : 'text-blue-600')}>
                  {side === 'old'
                    ? t('drawing_compare.old_revision', { defaultValue: 'Older revision' })
                    : t('drawing_compare.new_revision', { defaultValue: 'Newer revision' })}
                </legend>
                <div className="flex gap-2">
                  <select className={SELECT} value={drawing} onChange={(e) => { setDrawing(e.target.value); setVersion(''); }} aria-label={side}>
                    <option value="">{t('drawing_compare.pick_drawing', { defaultValue: 'Choose a DWG/DXF drawing' })}</option>
                    {(drawingsQuery.data ?? []).map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                  <select className={clsx(SELECT, 'w-32')} value={version} onChange={(e) => setVersion(e.target.value)} aria-label={t('drawing_compare.version', { defaultValue: 'Version' })}>
                    <option value="">{t('drawing_compare.latest_version', { defaultValue: 'Latest' })}</option>
                    {(versions ?? []).map((v) => (
                      <option key={v.id} value={v.id}>
                        {t('drawing_compare.version_n', { defaultValue: 'Version {{n}}', n: v.version_number })}
                      </option>
                    ))}
                  </select>
                </div>
              </fieldset>
            ))}
          </div>
          {dwgSame && <p className="text-sm text-amber-700">{t('drawing_compare.same_revision', { defaultValue: 'Choose two different revisions or pages.' })}</p>}
          <div>
            <Button
              variant="primary"
              icon={<GitCompare size={14} />}
              disabled={!oldDrawing || !newDrawing || dwgSame}
              loading={saveDwg.isPending}
              onClick={() => saveDwg.mutate()}
            >
              {t('drawing_compare.run_dwg', { defaultValue: 'Compare and save' })}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
