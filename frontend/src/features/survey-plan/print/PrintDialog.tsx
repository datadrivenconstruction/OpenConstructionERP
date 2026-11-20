// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Print the plan: paper (the market default from the server), orientation,
 * a standard scale (fitted to the plan at start), title, drawing number and
 * revision. Produces a vector PDF at true scale, or the same layers as DXF.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import type { GridXY, PlanLayerSpec } from '../types';
import type { PlanConventions } from '../units/conventions';
import { readPalette } from '../cartography';
import { featuresBBox } from '../engine/geometry';
import { PAPERS, SCALES, fitScale, pageLayout, renderPlanPdf, type PaperId } from './pdfPlan';
import { fetchTitleBlock, titleBlockData } from './titleBlock';
import { dxfBody, downloadPlanDxf, printLayers } from './planExport';

export interface PrintDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  layers: PlanLayerSpec[];
  conventions: PlanConventions;
  defaultTitle: string;
  /** A shaded relief to print under the vectors. */
  relief?: { dataUrl: string; bounds: [number, number, number, number] } | null;
}

const fileStem = (s: string) => s.replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60) || 'plan';

export function PrintDialog({ open, onClose, projectId, layers, conventions, defaultTitle, relief }: PrintDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const box = useMemo(() => featuresBBox(layers.flatMap((l) => l.features)), [layers]);
  const centre: GridXY | null = box ? [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] : null;
  const header = useQuery({
    queryKey: ['survey-plan', 'title-block', projectId, centre?.[0], centre?.[1]],
    queryFn: () => fetchTitleBlock(projectId, centre),
    enabled: open && !!projectId,
    staleTime: 60_000,
  });
  const [paper, setPaper] = useState<PaperId>('A3');
  const [orientation, setOrientation] = useState<'landscape' | 'portrait'>('landscape');
  const [scale, setScale] = useState<number>(500);
  const [title, setTitle] = useState(defaultTitle);
  const [drawingNo, setDrawingNo] = useState('');
  const [revision, setRevision] = useState('A');
  const [busy, setBusy] = useState<'pdf' | 'dxf' | null>(null);

  useEffect(() => {
    const p = header.data?.paper;
    if (p && p in PAPERS) setPaper(p as PaperId);
  }, [header.data?.paper]);
  useEffect(() => {
    if (!box) return;
    setScale(fitScale([box[2] - box[0], box[3] - box[1]], pageLayout(paper, orientation).frame));
  }, [box, paper, orientation]);

  const layerTitle = (l: PlanLayerSpec) => t(l.titleKey, { defaultValue: l.defaultTitle });

  const makePdf = async () => {
    if (!header.data || !centre) return;
    setBusy('pdf');
    try {
      const { blob, dropped } = await renderPlanPdf({
        paper,
        orientation,
        scale,
        centre,
        layers: printLayers(layers, readPalette(), layerTitle),
        title: titleBlockData(header.data, { title, drawingNo, revision }, t),
        conventions,
        convergenceDeg: header.data.convergence_deg,
        relief: relief ?? null,
        t,
      });
      triggerDownload(blob, `${fileStem(drawingNo || title)}.pdf`);
      if (dropped > 0) {
        addToast({ type: 'info', title: t('plan.print.labels_dropped', { defaultValue: '{{count}} labels left out so none overlap; print at a larger scale to show them', count: dropped }) });
      }
    } catch (e) {
      addToast({ type: 'error', title: t('plan.print.failed', { defaultValue: 'Could not build the plan' }), message: getErrorMessage(e) });
    } finally {
      setBusy(null);
    }
  };

  const makeDxf = async () => {
    setBusy('dxf');
    try {
      await downloadPlanDxf(projectId, dxfBody(layers, { title, drawingNo, revision, scale }), `${fileStem(drawingNo || title)}.dxf`);
    } catch (e) {
      addToast({ type: 'error', title: t('plan.print.failed', { defaultValue: 'Could not build the plan' }), message: getErrorMessage(e) });
    } finally {
      setBusy(null);
    }
  };

  const papers = (header.data?.papers ?? Object.keys(PAPERS)).filter((p): p is PaperId => p in PAPERS);
  const scales = header.data?.scales ?? [...SCALES];

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('plan.print.title', { defaultValue: 'Print plan' })}
      subtitle={t('plan.print.subtitle', { defaultValue: 'Vector PDF at true scale with title block, legend, north arrow and scale bar' })}
      size="md"
      busy={busy !== null}
      footer={
        <div className="flex gap-2">
          <Button variant="secondary" disabled={busy !== null || !box} loading={busy === 'dxf'} onClick={makeDxf} data-testid="plan-print-dxf">
            {t('plan.print.dxf', { defaultValue: 'Download DXF' })}
          </Button>
          <Button variant="primary" disabled={busy !== null || !header.data || !box} loading={busy === 'pdf'} onClick={makePdf} data-testid="plan-print-pdf">
            {t('plan.print.pdf', { defaultValue: 'Download PDF' })}
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-3 text-sm">
        <label className="block">
          <span className="oe-label">{t('plan.print.paper', { defaultValue: 'Paper' })}</span>
          <select className="oe-input w-full" value={paper} onChange={(e) => setPaper(e.target.value as PaperId)} data-testid="plan-print-paper">
            {papers.map((p) => <option key={p} value={p}>{p.replace('_', ' ')}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="oe-label">{t('plan.print.orientation', { defaultValue: 'Orientation' })}</span>
          <select className="oe-input w-full" value={orientation} onChange={(e) => setOrientation(e.target.value as 'landscape' | 'portrait')}>
            <option value="landscape">{t('plan.print.landscape', { defaultValue: 'Landscape' })}</option>
            <option value="portrait">{t('plan.print.portrait', { defaultValue: 'Portrait' })}</option>
          </select>
        </label>
        <label className="block">
          <span className="oe-label">{t('plan.print.scale', { defaultValue: 'Scale' })}</span>
          <select className="oe-input w-full" value={scale} onChange={(e) => setScale(Number(e.target.value))} data-testid="plan-print-scale">
            {scales.map((s) => <option key={s} value={s}>1:{s}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="oe-label">{t('plan.print.revision', { defaultValue: 'Revision' })}</span>
          <input className="oe-input w-full" value={revision} maxLength={20} onChange={(e) => setRevision(e.target.value)} />
        </label>
        <label className="col-span-2 block">
          <span className="oe-label">{t('plan.print.drawing_title', { defaultValue: 'Title' })}</span>
          <input className="oe-input w-full" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} data-testid="plan-print-title" />
        </label>
        <label className="col-span-2 block">
          <span className="oe-label">{t('plan.print.drawing_no', { defaultValue: 'Drawing no.' })}</span>
          <input className="oe-input w-full" value={drawingNo} maxLength={60} onChange={(e) => setDrawingNo(e.target.value)} />
        </label>
        <p className="col-span-2 text-xs text-content-secondary">
          {header.data?.company.legal_name
            ? t('plan.print.issuer', { defaultValue: 'Issued by {{name}}', name: header.data.company.legal_name })
            : t('plan.print.no_company', { defaultValue: 'No company details yet: set them in Settings, Company profile' })}
        </p>
      </div>
    </WideModal>
  );
}

export default PrintDialog;
