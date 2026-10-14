// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The plan image behind the site plan drawing and its scale. The image is a
// project document the stage points at; the scale is two points clicked on
// it and the real distance between them. Both are stored on the stage, so
// every reader sees the drawing over the same plan.

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Ruler } from 'lucide-react';

import { Button } from '@/shared/ui/Button';

import { listPlanImages, loadPlanImage, planKeys, updateItem, type Body, type PlanCatalogue, type PlanImage, type Stage } from './api';
import { num } from './format';
import { metresPerPixel, type Calibration, type Pt } from './geometry';
import { useInvalidatePlan, useReportProblem, useWords } from './hooks';
import { tx } from './texts';

export function usePlanImage(documentId: string | null | undefined) {
  return useQuery({
    queryKey: ['site-logistics-plan-image', documentId],
    queryFn: () => loadPlanImage(documentId as string),
    enabled: !!documentId,
    staleTime: Infinity,
    retry: false,
  });
}

/** The scale stored on the stage, or none. */
export function storedCalibration(stage: Stage | undefined): Calibration | null {
  const scale = Number(stage?.plan_metres_per_pixel);
  const origin = stage?.plan_origin_px;
  if (!stage?.plan_document_id || !(scale > 0) || !origin) return null;
  return { metresPerPixel: scale, origin: [origin[0], origin[1]] };
}

/** Until a scale is set the image is laid out at ten pixels to the metre from its bottom left corner. */
export function provisionalCalibration(image: PlanImage): Calibration {
  return { metresPerPixel: 0.1, origin: [0, image.height] };
}

const selectCls = 'mt-1 block h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary';

export function PlanImageBar({
  projectId,
  stage,
  catalogue,
  readOnly,
  image,
  imageFailed,
  scaling,
  picked,
  onScaling,
}: {
  projectId: string;
  stage: Stage;
  catalogue: PlanCatalogue | null;
  readOnly: boolean;
  image: PlanImage | undefined;
  imageFailed: boolean;
  scaling: boolean;
  /** The image pixels clicked so far while setting the scale. */
  picked: readonly Pt[];
  onScaling: (on: boolean) => void;
}) {
  const { t } = useWords();
  const images = useQuery({ queryKey: planKeys.of(projectId, 'plan-images'), queryFn: () => listPlanImages(projectId) });
  const invalidate = useInvalidatePlan(projectId);
  const report = useReportProblem(catalogue);
  const [distance, setDistance] = useState('');
  const [busy, setBusy] = useState(false);

  const write = async (body: Body) => {
    setBusy(true);
    try {
      await updateItem(projectId, 'stage', stage.id, body);
      await invalidate();
      onScaling(false);
      setDistance('');
    } catch (err) {
      report(err);
    } finally {
      setBusy(false);
    }
  };

  const stored = storedCalibration(stage);
  const [a, b] = picked;
  const metres = Number(distance.replace(',', '.'));
  const scale = a && b ? metresPerPixel(a, b, metres) : null;
  // The server keeps six decimals; a scale that rounds to nothing is not a scale.
  const scaleText = scale ? String(Number(scale.toFixed(6))) : '0';
  const choices = images.data ?? [];

  return (
    <div className="space-y-2" data-testid="siteplan-image-bar">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs font-medium text-content-secondary">
          {tx(t, 'siteplan.image')}
          <select
            className={selectCls}
            value={stage.plan_document_id ?? ''}
            disabled={readOnly || busy || images.isLoading}
            aria-busy={images.isLoading}
            // A different image has a different scale, so the old one goes with it.
            onChange={(e) =>
              void write({ plan_document_id: e.target.value || null, plan_metres_per_pixel: null, plan_origin_px: null })
            }
            data-testid="siteplan-image"
          >
            <option value="">{tx(t, 'siteplan.image_none')}</option>
            {/* A document that is no longer listed stays selectable as what the stage points at. */}
            {stage.plan_document_id && !choices.some((c) => c.id === stage.plan_document_id) && (
              <option value={stage.plan_document_id}>{stage.plan_document_id}</option>
            )}
            {choices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        {image && stored && !scaling && (
          <span className="pb-2 text-xs text-content-secondary" data-testid="siteplan-scale">
            {tx(t, 'siteplan.scale_now', { m: num(stored.metresPerPixel) ?? '' })}
          </span>
        )}
        {image && !readOnly && !scaling && (
          <Button size="sm" variant="secondary" onClick={() => onScaling(true)} data-testid="siteplan-scale-set">
            <Ruler size={14} className="mr-1" />
            {tx(t, 'siteplan.scale_set')}
          </Button>
        )}
      </div>
      {!readOnly && (
        <p className="text-xs text-content-tertiary" data-testid="siteplan-image-formats">
          {tx(t, 'siteplan.image_formats')}
        </p>
      )}
      {images.isLoading && (
        <p className="text-xs text-content-tertiary" role="status" data-testid="siteplan-images-loading">
          {tx(t, 'siteplan.images_loading')}
        </p>
      )}
      {images.isError && (
        <p role="alert" className="text-xs text-semantic-error" data-testid="siteplan-images-failed">
          {tx(t, 'siteplan.images_failed')}
        </p>
      )}
      {images.isSuccess && choices.length === 0 && !stage.plan_document_id && (
        <p className="text-xs text-content-tertiary" data-testid="siteplan-image-empty">
          {tx(t, 'siteplan.image_empty')}
        </p>
      )}
      {imageFailed && (
        <p role="alert" className="text-xs text-semantic-error" data-testid="siteplan-image-failed">
          {tx(t, 'siteplan.image_failed')}
        </p>
      )}
      {image && !stored && !scaling && (
        <p className="flex items-start gap-1.5 text-sm text-content-primary" data-testid="siteplan-scale-missing">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          {tx(t, 'siteplan.scale_missing')}
        </p>
      )}
      {scaling && image && (
        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border-light p-3" data-testid="siteplan-scale-form">
          <p className="basis-full text-sm text-content-secondary">{tx(t, 'siteplan.scale_hint')}</p>
          <label className="text-xs font-medium text-content-secondary">
            {tx(t, 'siteplan.scale_distance')}
            <input
              className={selectCls}
              inputMode="decimal"
              value={distance}
              disabled={picked.length < 2}
              onChange={(e) => setDistance(e.target.value)}
              data-testid="siteplan-scale-distance"
            />
          </label>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => onScaling(false)}>
            {tx(t, 'cancel')}
          </Button>
          <Button
            size="sm"
            loading={busy}
            disabled={scaleText === '0'}
            onClick={() =>
              void write({
                plan_metres_per_pixel: scaleText,
                // The first scale puts the metre origin in the bottom left corner; a later one keeps the origin.
                plan_origin_px: stored ? [stored.origin[0], stored.origin[1]] : [0, image.height],
              })
            }
            data-testid="siteplan-scale-save"
          >
            {tx(t, 'siteplan.scale_save')}
          </Button>
        </div>
      )}
    </div>
  );
}
