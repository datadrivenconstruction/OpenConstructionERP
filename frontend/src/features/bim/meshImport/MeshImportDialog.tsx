// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MeshImportDialog - in-app 3D geometry import for common mesh formats.
 *
 * Flow: parse the picked file in the browser (see ``loaders.ts``) -> walk the
 * scene and extract per-object and total quantities (see ``geometry.ts``) ->
 * let the user confirm the source unit and up-axis (quantities recompute live)
 * -> on confirm, re-export a normalized GLB whose node names equal the element
 * ids and build a matching element data table (CSV), then feed both into the
 * existing bim_hub upload. The imported mesh then behaves exactly like an
 * IFC/RVT import: same viewer, element list, BOQ linking, quantity maps,
 * takeoff and exports, with no backend changes.
 *
 * Quantities are a construction deliverable, so: vertices are always
 * transformed by the mesh world matrix before measuring; unit scaling is exact
 * (area x s^2, volume x s^3); volume is flagged approximate whenever the mesh
 * is not watertight; and the user always confirms the unit before anything is
 * committed.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import * as THREE from 'three';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Info,
  Loader2,
  UploadCloud,
  X,
} from 'lucide-react';
import { deriveGeometry } from '@/shared/ui/BIMViewer/canonicalElementDetails';
import { useToastStore } from '@/stores/useToastStore';
import { uploadBIMData } from '../api';
import {
  defaultUnitFor,
  defaultUpAxisFor,
  loadMeshFile,
  meshFormatFromName,
  UNIT_CODES,
  UNIT_TO_METERS,
  type MeshFormat,
  type UnitCode,
} from './loaders';
import { isImplausibleBuildingSize, suggestUnitForExtent } from './formats';
import {
  extractSceneMetrics,
  scaleExtraction,
  upAxisMatrix,
  type ExtractedObject,
  type ExtractionResult,
  type UpAxis,
} from './geometry';
import { MeshPreview } from './MeshPreview';
import { getNumberLocale } from '@/stores/usePreferencesStore';

interface MeshImportDialogProps {
  projectId: string;
  /** The picked mesh file (extension already routed here by BIMPage). */
  file: File;
  onClose: () => void;
  /** Called with the new model id after a successful upload. */
  onUploadComplete: (modelId: string) => void;
}

/* ── Helpers (pure, module scope) ──────────────────────────────────────── */

interface AssignedObject {
  object: ExtractedObject;
  /** Unique id used as the GLB node name, the mesh_ref and element_id. */
  elementId: string;
  /** Human-readable name (the ``name`` column). */
  displayName: string;
  /** Element type / category (grouped in the element list). */
  elementType: string;
}

const r6 = (n: number): number => Math.round(n * 1e6) / 1e6;

/** Strip characters that would break a node name or a CSV cell. */
function sanitizeId(raw: string): string {
  return raw.replace(/[\r\n",]+/g, ' ').replace(/\s+/g, ' ').trim();
}

/** Best-effort element type: the object name without a trailing instance
 *  number (so "Wall.001" / "Wall_2" group under "Wall"), or a default. */
function toElementType(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return 'Mesh';
  const stripped = trimmed.replace(/[._\s-]\d+$/, '').trim();
  return stripped || trimmed;
}

/**
 * Assign every object a unique, stable element id. The id becomes the GLB node
 * name AND the mesh_ref AND the element_id column, which is what lets the
 * viewer match rendered meshes back to element rows.
 */
function assignIds(objects: readonly ExtractedObject[], prefix: string): AssignedObject[] {
  const used = new Set<string>();
  return objects.map((object, i) => {
    const named = sanitizeId(object.name);
    const base = named || `${prefix}_${i + 1}`;
    let id = base;
    let n = 2;
    while (used.has(id)) {
      id = `${base}_${n}`;
      n += 1;
    }
    used.add(id);
    return {
      object,
      elementId: id,
      displayName: named || `${prefix} ${i + 1}`,
      elementType: toElementType(object.name),
    };
  });
}

/**
 * Re-export the selected objects as one normalized binary GLB. Each object's
 * world matrix, the up-axis correction and the unit scale are baked straight
 * into the geometry, and the node name is set to the element id. The viewer's
 * fixed Z-up -> Y-up display rotation then shows the model upright, in metres.
 */
async function buildNormalizedGlb(
  assigned: readonly AssignedObject[],
  opts: { scale: number; upAxis: UpAxis; fileName: string },
): Promise<File> {
  const group = new THREE.Group();
  const correction = upAxisMatrix(opts.upAxis);
  const scaleMat = new THREE.Matrix4().makeScale(opts.scale, opts.scale, opts.scale);
  const exportMatrix = new THREE.Matrix4();
  const material = new THREE.MeshStandardMaterial({ color: 0xbfc4cc, side: THREE.DoubleSide });

  for (const a of assigned) {
    const src = a.object.mesh;
    src.updateWorldMatrix(true, false);
    // final = scale * correction * world  (applied to each local vertex)
    exportMatrix.copy(scaleMat).multiply(correction).multiply(src.matrixWorld);
    const geometry = (src.geometry as THREE.BufferGeometry).clone();
    geometry.applyMatrix4(exportMatrix);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = a.elementId;
    group.add(mesh);
  }

  const exporter = new GLTFExporter();
  const glb = (await exporter.parseAsync(group, { binary: true })) as ArrayBuffer;

  // Release the cloned geometries; the exported ArrayBuffer is self-contained.
  group.traverse((o) => {
    if (o instanceof THREE.Mesh) o.geometry.dispose();
  });

  return new File([glb], opts.fileName, { type: 'model/gltf-binary' });
}

const CSV_HEADERS = [
  'element_id',
  'name',
  'element_type',
  'discipline',
  'area_m2',
  'volume_m3',
  'length_m',
  'mesh_ref',
  'bbox_min_x',
  'bbox_min_y',
  'bbox_min_z',
  'bbox_max_x',
  'bbox_max_y',
  'bbox_max_z',
  'source_unit',
  'source_format',
  'up_axis',
  'watertight',
  'volume_m3_approx',
] as const;

function csvCell(value: string | number): string {
  const s = String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/**
 * Build the element data table (one row per object) as a CSV File. Values are
 * already in metres (the scale was applied during extraction). Watertight
 * objects carry an exact ``volume_m3``; open meshes leave it blank and instead
 * record the value under ``volume_m3_approx`` so an approximate volume is never
 * presented as exact.
 */
function buildElementTableCsv(
  assigned: readonly AssignedObject[],
  opts: { discipline: string; unit: UnitCode; format: MeshFormat; upAxis: UpAxis },
): File {
  const lines = [CSV_HEADERS.join(',')];
  for (const a of assigned) {
    const o = a.object;
    const bb = o.bbox;
    const volumeExact = o.watertight ? r6(o.volume_m3) : '';
    const volumeApprox = o.watertight ? '' : r6(o.volume_m3);
    const row = [
      a.elementId,
      a.displayName,
      a.elementType,
      opts.discipline,
      r6(o.area_m2),
      volumeExact,
      r6(o.length_m),
      a.elementId, // mesh_ref == element_id == GLB node name
      bb ? r6(bb.min_x) : '',
      bb ? r6(bb.min_y) : '',
      bb ? r6(bb.min_z) : '',
      bb ? r6(bb.max_x) : '',
      bb ? r6(bb.max_y) : '',
      bb ? r6(bb.max_z) : '',
      opts.unit,
      opts.format,
      opts.upAxis === 'z' ? 'Z-up' : 'Y-up',
      o.watertight ? 'true' : 'false',
      volumeApprox,
    ];
    lines.push(row.map(csvCell).join(','));
  }
  return new File([lines.join('\r\n')], 'mesh_import_elements.csv', { type: 'text/csv' });
}

/* ── Component ─────────────────────────────────────────────────────────── */

const DISCIPLINE_KEYS: { v: string; k: string; d: string }[] = [
  { v: 'architecture', k: 'bim.disc_architecture', d: 'Architecture' },
  { v: 'structural', k: 'bim.disc_structural', d: 'Structural' },
  { v: 'mechanical', k: 'bim.disc_mechanical', d: 'Mechanical' },
  { v: 'electrical', k: 'bim.disc_electrical', d: 'Electrical' },
  { v: 'plumbing', k: 'bim.disc_plumbing', d: 'Plumbing' },
  { v: 'civil', k: 'bim.disc_civil', d: 'Civil' },
  { v: 'mixed', k: 'bim.disc_mixed', d: 'Mixed' },
];

export default function MeshImportDialog({
  projectId,
  file,
  onClose,
  onUploadComplete,
}: MeshImportDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const format = useMemo(() => meshFormatFromName(file.name), [file]);

  const [scene, setScene] = useState<THREE.Object3D | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [experimental, setExperimental] = useState(false);

  const [unit, setUnit] = useState<UnitCode>(() => (format ? defaultUnitFor(format) : 'm'));
  const [upAxis, setUpAxis] = useState<UpAxis>(() => (format ? defaultUpAxisFor(format) : 'y'));
  const [modelName, setModelName] = useState(() => file.name.replace(/\.[^.]+$/, ''));
  const [discipline, setDiscipline] = useState('architecture');
  const [uploading, setUploading] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  // Parse the file when the dialog opens (or the file changes).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setScene(null);
    setExperimental(false);
    loadMeshFile(file)
      .then((res) => {
        if (cancelled) return;
        setScene(res.object);
        setExperimental(res.experimental);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [file]);

  // Abort any in-flight upload if the dialog unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  const unitScale = UNIT_TO_METERS[unit];

  // Re-walk only when the scene or up-axis changes; unit changes are a cheap
  // re-scale of the already-extracted result.
  const rawResult: ExtractionResult | null = useMemo(
    () => (scene ? extractSceneMetrics(scene, { upAxis }) : null),
    [scene, upAxis],
  );
  const display: ExtractionResult | null = useMemo(
    () => (rawResult ? scaleExtraction(rawResult, unitScale) : null),
    [rawResult, unitScale],
  );

  const totals = display?.totals ?? null;
  const objectCount = totals?.objectCount ?? 0;
  const hasObjects = objectCount > 0;
  const allWatertight = !!totals && totals.watertightCount === totals.objectCount && totals.objectCount > 0;
  const boxDims = useMemo(() => (totals?.bbox ? deriveGeometry(totals.bbox) : null), [totals]);

  // Wrong-unit detection. The preview shows orientation and proportion, but it
  // cannot show scale: the grid adapts to the model, so a millimetre model and
  // a metre model look identical and only the grid label differs. The signal
  // that actually catches a wrong unit is the absolute size, because buildings
  // occupy a narrow band of it. Anything under 0.3 m or over 500 m across is
  // either not a building or not in the unit the dialog currently assumes.
  const maxDimM = boxDims ? Math.max(boxDims.width, boxDims.depth, boxDims.height) : 0;
  const scaleSuspect = hasObjects && isImplausibleBuildingSize(maxDimM);

  // If some other unit would land the model inside that band, name it and offer
  // it as one click - the point is to fix the mistake, not just report it.
  const suggestedUnit = useMemo<UnitCode | null>(
    () =>
      scaleSuspect && unitScale > 0
        ? // maxDimM / unitScale is the extent back in the file's own numbers.
          suggestUnitForExtent(maxDimM / unitScale, unit, UNIT_CODES, UNIT_TO_METERS)
        : null,
    [scaleSuspect, maxDimM, unitScale, unit],
  );

  const fmtNum = useCallback(
    (n: number, dp = 2): string =>
      n.toLocaleString(getNumberLocale(), { maximumFractionDigits: dp, minimumFractionDigits: 0 }),
    [],
  );

  const handleConfirm = useCallback(async () => {
    if (!display || !hasObjects || !format || !projectId) return;
    setUploading(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const prefix = sanitizeId(modelName) || 'object';
      const assigned = assignIds(display.objects, prefix);
      const glbFile = await buildNormalizedGlb(assigned, {
        scale: unitScale,
        upAxis,
        fileName: `${prefix}.glb`,
      });
      const csvFile = buildElementTableCsv(assigned, { discipline, unit, format, upAxis });
      const res = await uploadBIMData(
        projectId,
        modelName.trim() || file.name,
        discipline,
        csvFile,
        glbFile,
        ac.signal,
      );
      addToast({
        type: 'success',
        title: t('bim.mesh_import.upload_success_title', { defaultValue: 'Model imported' }),
        message: t('bim.upload_complete_count', {
          defaultValue: '{{count}} elements',
          count: res.element_count,
        }),
      });
      onUploadComplete(res.model_id);
      onClose();
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      addToast({
        type: 'error',
        title: t('bim.mesh_import.upload_failed_title', { defaultValue: 'Import failed' }),
        message: err instanceof Error ? err.message : String(err),
      });
      setUploading(false);
    }
  }, [
    display,
    hasObjects,
    format,
    projectId,
    modelName,
    unitScale,
    upAxis,
    discipline,
    unit,
    file,
    addToast,
    onUploadComplete,
    onClose,
    t,
  ]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg p-4"
      role="dialog"
      aria-modal="true"
      onClick={uploading ? undefined : onClose}
    >
      <div
        className="bg-surface-primary rounded-xl shadow-2xl w-full max-w-2xl flex flex-col border border-border-light max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-light shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <Boxes size={16} className="text-oe-blue shrink-0" />
            <h2 className="text-sm font-semibold text-content-primary truncate">
              {t('bim.mesh_import.title', { defaultValue: 'Import 3D geometry' })}
            </h2>
            <span className="text-[11px] text-content-tertiary uppercase font-mono shrink-0">
              {format ?? ''}
            </span>
          </div>
          <button
            onClick={onClose}
            disabled={uploading}
            className="p-1 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary disabled:opacity-40"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 overflow-y-auto">
          <p className="text-[11px] text-content-tertiary truncate">{file.name}</p>

          {loading && (
            <div className="flex flex-col items-center gap-2 py-10 text-content-tertiary">
              <Loader2 size={22} className="animate-spin text-oe-blue" />
              <span className="text-xs">
                {t('bim.mesh_import.parsing', { defaultValue: 'Reading geometry...' })}
              </span>
            </div>
          )}

          {!loading && loadError && (
            <div className="rounded-lg border border-red-300/50 bg-red-50/60 dark:bg-red-950/20 px-3 py-2.5 text-[12px] text-red-700 dark:text-red-300">
              <div className="flex items-start gap-2">
                <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                <span>{loadError}</span>
              </div>
            </div>
          )}

          {!loading && !loadError && experimental && (
            <div className="rounded-lg border border-amber-300/50 bg-amber-50/60 dark:bg-amber-950/20 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-300">
              <div className="flex items-start gap-2">
                <Info size={12} className="shrink-0 mt-0.5" />
                <span>
                  {t('bim.mesh_import.usd_experimental', {
                    defaultValue:
                      'USD support is experimental. Please double-check the extracted quantities before importing.',
                  })}
                </span>
              </div>
            </div>
          )}

          {!loading && !loadError && display && !hasObjects && (
            <div className="rounded-lg border border-amber-300/50 bg-amber-50/60 dark:bg-amber-950/20 px-3 py-2.5 text-[12px] text-amber-700 dark:text-amber-300">
              <div className="flex items-start gap-2">
                <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                <span>
                  {t('bim.mesh_import.no_meshes', {
                    defaultValue:
                      'No surface geometry was found in this file (it may contain only points, curves or cameras).',
                  })}
                </span>
              </div>
            </div>
          )}

          {!loading && !loadError && display && hasObjects && (
            <>
              {/* Honest expectation-setting: a mesh is geometry only. The
                  quantities below are measured from the shape; there are no
                  BIM properties / classifications to extract (unlike IFC/RVT). */}
              <div className="rounded-lg border border-blue-300/40 bg-blue-50/50 dark:bg-blue-950/20 px-3 py-2 text-[11px] text-blue-700 dark:text-blue-300">
                <div className="flex items-start gap-2">
                  <Info size={12} className="shrink-0 mt-0.5" />
                  <span>
                    {t('bim.mesh_import.geometry_only_note', {
                      defaultValue:
                        'Geometry-only import: the quantities below are measured from the mesh shape. Mesh files carry no BIM properties, materials or classifications - for those, import an IFC or RVT model instead.',
                    })}
                  </span>
                </div>
              </div>

              {/* Live viewport. Sits directly above the unit and up-axis
                  controls because it exists to make those two choices
                  visible: the model rebuilds under the same transform the
                  import will bake in, against a grid labelled in metres. */}
              {scene && <MeshPreview object={scene} upAxis={upAxis} unitScale={unitScale} />}

              {/* The real wrong-unit check. Sits immediately above the unit
                  control so the report and the fix are the same glance. */}
              {scaleSuspect && (
                <div className="rounded-lg border border-amber-300/50 bg-amber-50/60 dark:bg-amber-950/20 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-300">
                  <div className="flex items-start gap-2">
                    <AlertTriangle size={12} className="shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <span className="block">
                        {t('bim.mesh_import.scale_suspect', {
                          defaultValue:
                            'At this unit the model is {{size}} m across, which is an unusual size for a building. Check the source unit before importing.',
                          size: fmtNum(maxDimM, maxDimM < 1 ? 3 : 0),
                        })}
                      </span>
                      {suggestedUnit && (
                        <button
                          type="button"
                          onClick={() => setUnit(suggestedUnit)}
                          className="underline underline-offset-2 font-semibold hover:no-underline"
                        >
                          {t('bim.mesh_import.scale_switch', {
                            defaultValue: 'Switch to {{unit}}',
                            unit: t(`bim.mesh_import.unit_${suggestedUnit}`, {
                              defaultValue: UNIT_LABELS[suggestedUnit],
                            }),
                          })}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Unit + up-axis controls */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
                    {t('bim.mesh_import.source_unit', { defaultValue: 'Source unit' })}
                  </label>
                  <select
                    value={unit}
                    onChange={(e) => setUnit(e.target.value as UnitCode)}
                    className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  >
                    {UNIT_CODES.map((u) => (
                      <option key={u} value={u}>
                        {t(`bim.mesh_import.unit_${u}`, { defaultValue: UNIT_LABELS[u] })}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
                    {t('bim.mesh_import.up_axis', { defaultValue: 'Up axis' })}
                  </label>
                  <select
                    value={upAxis}
                    onChange={(e) => setUpAxis(e.target.value as UpAxis)}
                    className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  >
                    <option value="y">
                      {t('bim.mesh_import.up_y', { defaultValue: 'Y up (glTF, OBJ, FBX)' })}
                    </option>
                    <option value="z">
                      {t('bim.mesh_import.up_z', { defaultValue: 'Z up (STL, 3DS, CAD)' })}
                    </option>
                  </select>
                </div>
              </div>

              {/* Summary */}
              <div className="rounded-lg border border-border-light bg-surface-secondary/50 p-3 space-y-2">
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
                  <Metric
                    label={t('bim.mesh_import.objects', { defaultValue: 'Objects' })}
                    value={fmtNum(objectCount, 0)}
                  />
                  <Metric
                    label={t('bim.mesh_import.triangles', { defaultValue: 'Triangles' })}
                    value={fmtNum(totals?.triangleCount ?? 0, 0)}
                  />
                  {boxDims && (
                    <Metric
                      label={t('bim.mesh_import.size_wdh', { defaultValue: 'Size W x D x H' })}
                      value={`${fmtNum(boxDims.width, 2)} x ${fmtNum(boxDims.depth, 2)} x ${fmtNum(boxDims.height, 2)} m`}
                    />
                  )}
                  <Metric
                    label={t('bim.mesh_import.longest', { defaultValue: 'Longest extent' })}
                    value={`${fmtNum(totals?.length_m ?? 0, 2)} m`}
                  />
                  <Metric
                    label={t('bim.mesh_import.surface_area', { defaultValue: 'Surface area' })}
                    value={`${fmtNum(totals?.area_m2 ?? 0, 2)} m2`}
                  />
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-content-tertiary">
                      {t('bim.mesh_import.volume', { defaultValue: 'Volume' })}
                    </span>
                    <span className="text-content-primary font-medium flex items-center gap-1.5">
                      {`${fmtNum(totals?.volume_m3 ?? 0, 3)} m3`}
                      {allWatertight ? (
                        <span className="inline-flex items-center gap-0.5 text-[9px] text-green-600 dark:text-green-400">
                          <CheckCircle2 size={10} />
                          {t('bim.mesh_import.exact', { defaultValue: 'exact' })}
                        </span>
                      ) : (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border border-amber-300/40">
                          {t('bim.mesh_import.approximate', { defaultValue: 'approximate' })}
                        </span>
                      )}
                    </span>
                  </div>
                </div>
                {!allWatertight && (
                  <p className="text-[10px] text-content-tertiary leading-relaxed">
                    {t('bim.mesh_import.volume_note', {
                      defaultValue:
                        'Volume is exact only for closed (watertight) meshes. {{closed}} of {{total}} objects are closed; open meshes contribute surface area but no volume.',
                      closed: totals?.watertightCount ?? 0,
                      total: objectCount,
                    })}
                  </p>
                )}
              </div>

              {/* Model name + discipline */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
                    {t('bim.upload_model_name_label', { defaultValue: 'Model name' })}
                  </label>
                  <input
                    type="text"
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                    className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
                    {t('bim.upload_discipline_label', { defaultValue: 'Discipline' })}
                  </label>
                  <select
                    value={discipline}
                    onChange={(e) => setDiscipline(e.target.value)}
                    className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  >
                    {DISCIPLINE_KEYS.map((d) => (
                      <option key={d.v} value={d.v}>
                        {t(d.k, { defaultValue: d.d })}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light shrink-0">
          <button
            type="button"
            onClick={onClose}
            disabled={uploading}
            className="text-xs text-content-tertiary hover:text-content-primary px-2 disabled:opacity-40"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!hasObjects || uploading || loading}
            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-oe-blue text-white hover:bg-oe-blue-dark disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uploading ? <Loader2 size={13} className="animate-spin" /> : <UploadCloud size={13} />}
            {uploading
              ? t('bim.mesh_import.importing', { defaultValue: 'Importing...' })
              : t('bim.mesh_import.import_btn', { defaultValue: 'Import model' })}
          </button>
        </div>
      </div>
    </div>
  );
}

const UNIT_LABELS: Record<UnitCode, string> = {
  mm: 'Millimetres (mm)',
  cm: 'Centimetres (cm)',
  m: 'Metres (m)',
  in: 'Inches (in)',
  ft: 'Feet (ft)',
};

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-content-tertiary">{label}</span>
      <span className="text-content-primary font-medium">{value}</span>
    </div>
  );
}
