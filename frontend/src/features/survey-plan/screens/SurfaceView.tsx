// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A surface on the plan: shaded relief (light from the north-west), contours
 * at an interval picked to give about twenty lines (or one the user sets),
 * every fifth an index contour labelled with its height. Extra layers of the
 * calling screen (pads, zones, toe and crest) draw on top.
 */

import { useMemo, useState, type ComponentType, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Printer } from 'lucide-react';
import { Button } from '@/shared/ui';
import type { PlanCanvasProps, PlanLayerSpec } from '../types';
import type { LiveFinding } from '../engine/liveChecks';
import { usePlanConventions } from '../hooks';
import { formatDistance } from '../units/linear';
import { PrintDialog } from '../print/PrintDialog';
import { PlanFrame } from './PlanFrame';
import { p2Api, p2Keys } from './api';
import { contourLayer, reliefImage } from './surfaceLayers';

export const CONTOUR_INTERVALS = [0.1, 0.25, 0.5, 1, 2, 5, 10] as const;

export interface SurfaceViewProps {
  projectId: string;
  surfaces: Array<{ id: string; name: string; code?: string }>;
  /** Pick this surface at start. */
  surfaceId?: string | null;
  extraLayers?: PlanLayerSpec[];
  findings?: LiveFinding[];
  side?: ReactNode;
  toolbar?: ReactNode;
  printTitle?: string;
  canvas?: ComponentType<PlanCanvasProps>;
  testId?: string;
}

export function SurfaceView({ projectId, surfaces, surfaceId, extraLayers = [], findings, side, toolbar, printTitle, canvas, testId = 'plan-surface' }: SurfaceViewProps) {
  const { t } = useTranslation();
  const { conventions: conv } = usePlanConventions(projectId);
  const [picked, setPicked] = useState<string | null>(null);
  const [interval, setStep] = useState<number | null>(null);
  const [showRelief, setShowRelief] = useState(true);
  const [printing, setPrinting] = useState(false);
  const sid = picked ?? surfaceId ?? surfaces[0]?.id ?? null;

  const contours = useQuery({ queryKey: p2Keys.contours(sid ?? '', interval), queryFn: () => p2Api.contours(sid!, interval), enabled: !!sid });
  const mesh = useQuery({ queryKey: p2Keys.mesh(sid ?? ''), queryFn: () => p2Api.mesh(sid!), enabled: !!sid && showRelief, staleTime: 5 * 60_000 });
  const relief = useMemo(() => (showRelief ? reliefImage(mesh.data) : null), [mesh.data, showRelief]);
  const layers = useMemo(() => [contourLayer(contours.data, conv), ...extraLayers], [contours.data, conv, extraLayers]);
  const c = contours.data;

  const bar = (
    <>
      {surfaces.length > 0 && <select className="oe-input py-1 text-sm" value={sid ?? ''} onChange={(e) => setPicked(e.target.value || null)} aria-label={t('plan.tin.surface', { defaultValue: 'Surface' })} data-testid={`${testId}-pick`}>
        {surfaces.map((s) => <option key={s.id} value={s.id}>{s.code ? `${s.code} ${s.name}` : s.name}</option>)}
      </select>}
      <select className="oe-input py-1 text-sm" value={interval ?? ''} onChange={(e) => setStep(e.target.value ? Number(e.target.value) : null)} aria-label={t('plan.tin.interval', { defaultValue: 'Contour interval' })}>
        <option value="">{t('plan.tin.interval_auto', { defaultValue: 'Auto interval' })}{c ? ` (${formatDistance(c.auto_interval, conv)})` : ''}</option>
        {CONTOUR_INTERVALS.map((v) => <option key={v} value={v}>{formatDistance(v, conv)}</option>)}
      </select>
      <label className="flex items-center gap-1 text-sm">
        <input type="checkbox" checked={showRelief} onChange={(e) => setShowRelief(e.target.checked)} />
        {t('plan.tin.hillshade', { defaultValue: 'Shaded relief' })}
      </label>
      {toolbar}
      <Button variant="secondary" size="sm" icon={<Printer size={14} />} disabled={!layers.some((l) => l.features.length)} onClick={() => setPrinting(true)}>
        {t('plan.print.action', { defaultValue: 'Print plan' })}
      </Button>
    </>
  );

  const info = c && c.z_min != null && c.z_max != null ? (
    <p className="text-xs text-content-secondary" data-testid={`${testId}-range`}>
      {t('plan.tin.range', {
        defaultValue: 'Heights {{min}} to {{max}}, contours every {{interval}}, index every {{every}}',
        min: formatDistance(c.z_min, conv), max: formatDistance(c.z_max, conv), interval: formatDistance(c.interval, conv), every: c.index_every,
      })}
    </p>
  ) : null;

  if (!surfaces.length && !extraLayers.some((l) => l.features.length)) {
    return <p className="text-sm text-content-secondary">{t('plan.tin.no_surfaces', { defaultValue: 'No surface yet. Build one from points or import a LandXML or DTM file.' })}</p>;
  }

  return (
    <>
      <PlanFrame projectId={projectId} layers={layers} findings={findings} relief={relief} toolbar={bar} side={<>{info}{side}</>} canvas={canvas} testId={testId} />
      {printing && (
        <PrintDialog open={printing} onClose={() => setPrinting(false)} projectId={projectId} layers={layers} conventions={conv} relief={relief}
          defaultTitle={printTitle ?? t('plan.tin.print_title', { defaultValue: 'Terrain and contours' })} />
      )}
    </>
  );
}

export default SurfaceView;
