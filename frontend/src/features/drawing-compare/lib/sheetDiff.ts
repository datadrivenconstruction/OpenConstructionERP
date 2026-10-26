// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One sheet compare from two rasters: align, diff, cluster, text diff.
 *
 * Pure: the rasters come in as RGBA arrays with their scale (pixels per PDF
 * unit), so the whole pipeline is testable without a browser. The stored
 * alignment is always in PDF units (old sheet -> new sheet), whatever the two
 * raster resolutions were.
 */

import { autoAlign } from './align';
import { buildChanges, type DraftChange } from './buildChanges';
import { clusterRegions, type DiffRegion } from './cluster';
import { diffMasks, inkMaskFromRgba, warpMask, type InkMask, type PixelDiff } from './raster';
import { diffText, type TextChange, type TextItem } from './textDiff';
import { composeAffine, similarityFromTwoPoints, type Affine, type Pt } from './transform';

export interface SheetRaster {
  width: number;
  height: number;
  rgba: Uint8ClampedArray;
  /** Pixels per PDF unit. */
  scale: number;
  widthPt: number;
  heightPt: number;
  text: TextItem[];
}

export type AlignMode = 'auto' | 'manual' | 'none';

export interface CompareSettings {
  alignment: AlignMode;
  /** Two marks on each sheet, PDF units; required for `manual`. */
  manualPoints?: { old: [Pt, Pt]; new: [Pt, Pt] } | null;
  /** Pixels of misregistration that do not count as change. */
  tolerance: number;
  /** Luminance below which a pixel is ink (0-255). */
  inkThreshold: number;
  cell: number;
  gap: number;
  minPixels: number;
  compareText: boolean;
  /** Use this old -> new transform (PDF units) as it is, e.g. one stored with a compare. */
  fixedMatrix?: Affine | null;
}

export const DEFAULT_SETTINGS: CompareSettings = {
  alignment: 'auto',
  manualPoints: null,
  tolerance: 2,
  inkThreshold: 200,
  cell: 8,
  gap: 3,
  minPixels: 20,
  compareText: true,
};

export interface SheetDiffResult {
  /** Old sheet -> new sheet, PDF units. */
  matrix: Affine;
  confidence: number | null;
  diff: PixelDiff;
  regions: DiffRegion[];
  texts: TextChange[];
  changes: DraftChange[];
  oldAligned: InkMask;
}

const scaleM = (s: number): Affine => [s, 0, 0, s, 0, 0];

/** Old raster pixel -> new raster pixel, from a PDF-unit transform. */
export function pixelMatrix(pdf: Affine, oldScale: number, newScale: number): Affine {
  return composeAffine(scaleM(newScale), composeAffine(pdf, scaleM(1 / oldScale)));
}

/** PDF-unit transform from an old-pixel -> new-pixel transform. */
export function pdfMatrix(px: Affine, oldScale: number, newScale: number): Affine {
  return composeAffine(scaleM(1 / newScale), composeAffine(px, scaleM(oldScale)));
}

export function computeSheetDiff(
  oldSheet: SheetRaster,
  newSheet: SheetRaster,
  settings: CompareSettings = DEFAULT_SETTINGS,
): SheetDiffResult {
  const oldMask = inkMaskFromRgba(oldSheet.rgba, oldSheet.width, oldSheet.height, settings.inkThreshold);
  const newMask = inkMaskFromRgba(newSheet.rgba, newSheet.width, newSheet.height, settings.inkThreshold);

  let matrix: Affine = [1, 0, 0, 1, 0, 0];
  let confidence: number | null = null;
  if (settings.fixedMatrix) {
    matrix = settings.fixedMatrix;
  } else if (settings.alignment === 'manual' && settings.manualPoints) {
    const m = similarityFromTwoPoints(settings.manualPoints.old, settings.manualPoints.new);
    if (m) matrix = m;
  } else if (settings.alignment === 'auto') {
    // Bring the old raster to the new resolution first, so the search runs in one pixel grid.
    const base = pixelMatrix(matrix, oldSheet.scale, newSheet.scale);
    const resampled = warpMask(oldMask, base, newSheet.width, newSheet.height);
    const found = autoAlign(resampled, newMask);
    matrix = pdfMatrix(composeAffine(found.matrix, base), oldSheet.scale, newSheet.scale);
    confidence = found.confidence;
  }
  const px = pixelMatrix(matrix, oldSheet.scale, newSheet.scale);
  const oldAligned = warpMask(oldMask, px, newSheet.width, newSheet.height);
  const diff = diffMasks(oldAligned, newMask, settings.tolerance);
  const regions = clusterRegions(diff, { cell: settings.cell, gap: settings.gap, minPixels: settings.minPixels });
  const texts =
    settings.compareText && oldSheet.text.length > 0 && newSheet.text.length > 0
      ? diffText(oldSheet.text, newSheet.text, matrix)
      : [];
  const changes = buildChanges(regions, texts, newSheet.scale).filter(
    (c) => c.x + c.w >= 0 && c.y + c.h >= 0 && c.x <= newSheet.widthPt && c.y <= newSheet.heightPt,
  );
  return { matrix, confidence, diff, regions, texts, changes, oldAligned };
}
