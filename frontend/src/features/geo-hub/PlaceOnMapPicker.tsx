// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * PlaceOnMapPicker - a unified picker that lists every placeable file in a
 * project and lets the user drop each one onto the project map in one click.
 *
 * Two source groups, fetched live:
 *
 *  1. 3D models (BIM Hub: RVT / IFC / DWG / DGN). A model that has finished
 *     converting (``status === 'ready'`` with geometry) is placed as a
 *     georeferenced 3D Tileset anchored to the project location, via
 *     ``POST /v1/geo-hub/from-canonical/{modelId}``. Models still
 *     converting, or that produced no geometry, link out to BIM Hub instead.
 *  2. PDF drawings (Documents module). The stored PDF is downloaded and
 *     re-uploaded as a flat raster overlay the user can then drag into place
 *     (``POST /v1/geo-hub/raster-overlays/upload-pdf``).
 *
 * Already-placed files are detected by cross-referencing the existing
 * tilesets (``source_kind === 'bim_model'`` + ``source_id``) and raster
 * overlays (``source_kind === 'pdf'`` matched by name), so a file is never
 * placed twice by accident.
 *
 * Placing a 3D model requires the project to be anchored first; when it is
 * not, the picker shows a single banner pointing at the anchor flow rather
 * than letting placements fail one by one. PDF overlays fall back to a
 * draggable placeholder bbox even without an anchor, but we still nudge the
 * user to anchor first so the overlay lands in roughly the right spot.
 *
 * Everything here is client-only: it composes endpoints that already exist,
 * so no backend change or restart is involved.
 */

import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ArrowUpRight,
  Boxes,
  Check,
  FileText,
  Loader2,
  MapPin,
  Plus,
} from 'lucide-react';

import { ApiError, type Page } from '@/shared/lib/api';
import { WideModal } from '@/shared/ui';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useToastStore } from '@/stores/useToastStore';
import type { BIMModelData } from '@/shared/ui/BIMViewer';
import { fetchBIMModels } from '@/features/bim/api';
import {
  downloadDocumentBlob,
  fetchDocuments,
  type DocumentItem,
} from '@/features/documents/api';

import {
  listRasterOverlays,
  listTilesets,
  placeBimModelOnMap,
  uploadPdfRasterOverlay,
} from './api';
import { fmtFixed } from '@/shared/lib/formatters';

interface PlaceOnMapPickerProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Whether the project already has a geo anchor. 3D model placement
   *  needs one; when false we surface a banner instead of failing. */
  hasAnchor: boolean;
  /** Fired after a file is successfully placed so the parent can focus
   *  the camera on the result. ``kind: 'model'`` carries the placed BIM
   *  model id (the parent resolves it to a tileset and flies to its
   *  bounding sphere); ``kind: 'overlay'`` carries the new raster overlay
   *  centroid (lon/lat) so the parent can fly straight to the drawing. */
  onPlaced?: (
    placed:
      | { kind: 'model'; modelId: string }
      | { kind: 'overlay'; lon: number; lat: number },
  ) => void;
}

/** Mean of an overlay's four ``[lon, lat]`` corners — the point the
 *  camera flies to so a freshly-placed PDF drawing is immediately framed
 *  instead of dropped somewhere off-screen. Returns ``null`` when the
 *  corner array is missing or malformed (the parent then skips the fly).
 *  Exported for unit testing. */
export function overlayCentroid(
  corners: ReadonlyArray<readonly [number, number]> | null | undefined,
): { lon: number; lat: number } | null {
  if (!Array.isArray(corners) || corners.length === 0) return null;
  let sumLon = 0;
  let sumLat = 0;
  let n = 0;
  for (const c of corners) {
    if (!Array.isArray(c) || c.length < 2) continue;
    const lon = Number(c[0]);
    const lat = Number(c[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    sumLon += lon;
    sumLat += lat;
    n += 1;
  }
  if (n === 0) return null;
  return { lon: sumLon / n, lat: sumLat / n };
}

/** Classify a document as a PDF for the place-on-map flow. Reads the
 *  document's ``name``/``mime_type`` defensively: the CDE document model
 *  carries ``name`` (not ``filename``), and either field may be missing,
 *  so neither is dereferenced without a guard. Exported for unit testing. */
export function isPdfDocument(doc: DocumentItem): boolean {
  if (doc.mime_type && doc.mime_type.toLowerCase() === 'application/pdf') {
    return true;
  }
  return (doc.name ?? '').toLowerCase().endsWith('.pdf');
}

function modelFormatOf(model: BIMModelData): string {
  return (model.model_format || model.format || '').toLowerCase();
}

/** A ready model carries geometry unless the list endpoint explicitly says
 *  otherwise (``has_geometry === false``). The field is not on the typed
 *  model so we read it defensively. */
function modelHasGeometry(model: BIMModelData): boolean {
  const flag = (model as { has_geometry?: boolean }).has_geometry;
  return flag !== false;
}

export function PlaceOnMapPicker({
  open,
  onClose,
  projectId,
  hasAnchor,
  onPlaced,
}: PlaceOnMapPickerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  // Only one placement runs at a time; this holds the id of the file
  // currently being placed so its row can show a spinner.
  const [busyId, setBusyId] = useState<string | null>(null);

  const modelsQuery = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: open && Boolean(projectId),
    staleTime: 15_000,
  });
  const documentsQuery = useQuery({
    queryKey: ['documents', projectId],
    // Spelled out because this query holds a page, not a list: three surfaces
    // cache under ['documents', <project>] and React Query will hand any of
    // them what another put there.
    queryFn: (): Promise<Page<DocumentItem>> => fetchDocuments(projectId),
    enabled: open && Boolean(projectId),
    staleTime: 15_000,
  });
  const tilesetsQuery = useQuery({
    queryKey: ['geo-hub', 'tilesets', projectId],
    queryFn: () => listTilesets(projectId),
    enabled: open && Boolean(projectId),
    staleTime: 15_000,
  });
  const overlaysQuery = useQuery({
    queryKey: ['geo-hub', 'raster-overlays', projectId],
    queryFn: () => listRasterOverlays(projectId, { includeHidden: true }),
    enabled: open && Boolean(projectId),
    staleTime: 15_000,
  });

  const models = useMemo(
    () => modelsQuery.data?.items ?? [],
    [modelsQuery.data],
  );
  const pdfs = useMemo(
    () => (documentsQuery.data?.items ?? []).filter(isPdfDocument),
    [documentsQuery.data],
  );

  // Set of bim_model ids already published as a tileset.
  const placedModelIds = useMemo(() => {
    const s = new Set<string>();
    for (const ts of tilesetsQuery.data ?? []) {
      if (ts.source_kind === 'bim_model') s.add(ts.source_id);
    }
    return s;
  }, [tilesetsQuery.data]);

  // Raster overlays have no foreign key back to a document, so PDF
  // placement is matched best-effort by the overlay name (which we set to
  // the document filename on upload).
  const placedPdfNames = useMemo(() => {
    const s = new Set<string>();
    for (const o of overlaysQuery.data ?? []) {
      if (o.source_kind === 'pdf') s.add(o.name);
    }
    return s;
  }, [overlaysQuery.data]);

  const place3dModel = useCallback(
    async (model: BIMModelData) => {
      if (busyId) return;
      setBusyId(model.id);
      try {
        await placeBimModelOnMap(model.id, { projectId });
        addToast({
          type: 'success',
          title: t('geo_hub.place.placed_model_title', {
            defaultValue: 'Model placed on the map',
          }),
          message: t('geo_hub.place.placed_model_message', {
            defaultValue: '{{name}} is now anchored at the project location.',
            name: model.name,
          }),
        });
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: ['geo-hub', 'map-config', projectId],
          }),
          queryClient.invalidateQueries({
            queryKey: ['geo-hub', 'tilesets', projectId],
          }),
        ]);
        onPlaced?.({ kind: 'model', modelId: model.id });
      } catch (err) {
        const detail =
          err instanceof ApiError
            ? (err.body as { detail?: string })?.detail
            : undefined;
        let message = t('geo_hub.place.place_failed_generic', {
          defaultValue: 'Could not place this model. Please try again.',
        });
        if (err instanceof ApiError) {
          if (detail === 'no_anchor_for_project') {
            message = t('geo_hub.place.error_no_anchor', {
              defaultValue:
                'Set the project location on the map first, then place models.',
            });
          } else if (
            detail === 'canonical_elements_empty' ||
            detail === 'canonical_elements_have_no_geometry'
          ) {
            message = t('geo_hub.place.error_no_geometry', {
              defaultValue:
                'This model has no 3D geometry to place. Open it in BIM Hub and re-convert it.',
            });
          } else if (err.status === 404) {
            message = t('geo_hub.place.error_not_found', {
              defaultValue: 'This model is no longer available.',
            });
          }
        }
        addToast({
          type: 'error',
          title: t('geo_hub.place.place_failed_title', {
            defaultValue: 'Placement failed',
          }),
          message,
        });
      } finally {
        setBusyId(null);
      }
    },
    [busyId, projectId, addToast, t, queryClient, onPlaced],
  );

  const placePdf = useCallback(
    async (doc: DocumentItem) => {
      if (busyId) return;
      setBusyId(doc.id);
      try {
        const blob = await downloadDocumentBlob(doc.id);
        const file = new File([blob], doc.name, {
          type: 'application/pdf',
        });
        const res = await uploadPdfRasterOverlay(projectId, file, {
          name: doc.name,
        });
        addToast({
          type: 'success',
          title: t('geo_hub.place.placed_pdf_title', {
            defaultValue: 'Drawing placed on the map',
          }),
          message: t('geo_hub.place.placed_pdf_message', {
            defaultValue:
              '{{name}} was added as an overlay. Drag its corners to position it.',
            name: doc.name,
          }),
        });
        await queryClient.invalidateQueries({
          queryKey: ['geo-hub', 'raster-overlays', projectId],
        });
        // Fly the camera to the new overlay so it's immediately visible.
        // The overlay is created centred on the project anchor, but the
        // camera may have drifted; framing its centroid guarantees the
        // user sees the drawing instead of an off-screen square they have
        // to hunt for. When the centroid can't be derived we just skip the
        // fly (the overlay still renders on the next refetch).
        const centroid = overlayCentroid(res.overlay?.corners_geojson);
        if (centroid) {
          onPlaced?.({ kind: 'overlay', lon: centroid.lon, lat: centroid.lat });
        }
      } catch (err) {
        const detail =
          err instanceof ApiError
            ? (err.body as { detail?: string })?.detail
            : undefined;
        addToast({
          type: 'error',
          title: t('geo_hub.place.place_failed_title', {
            defaultValue: 'Placement failed',
          }),
          message:
            detail ||
            t('geo_hub.place.place_pdf_failed', {
              defaultValue:
                'Could not place this drawing. Please try again.',
            }),
        });
      } finally {
        setBusyId(null);
      }
    },
    [busyId, projectId, addToast, t, queryClient, onPlaced],
  );

  const isLoading =
    modelsQuery.isLoading ||
    documentsQuery.isLoading ||
    tilesetsQuery.isLoading ||
    overlaysQuery.isLoading;
  const nothingToPlace = !isLoading && models.length === 0 && pdfs.length === 0;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="lg"
      busy={Boolean(busyId)}
      title={t('geo_hub.place.title', { defaultValue: 'Place a file on the map' })}
      subtitle={t('geo_hub.place.subtitle', {
        defaultValue:
          'Pick a project file to position on the map. 3D models (RVT, IFC, DWG) anchor to the project location; PDF drawings drop in as a flat overlay you can drag into place.',
      })}
      footer={
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border bg-surface-primary px-4 py-2 text-sm font-medium text-content-secondary transition hover:bg-surface-secondary"
          >
            {t('common.done', { defaultValue: 'Done' })}
          </button>
        </div>
      }
    >
      {!hasAnchor && (
        <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-amber-300/50 bg-amber-50 px-3.5 py-2.5 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-900/20 dark:text-amber-100">
          <MapPin size={16} className="mt-0.5 shrink-0" />
          <span>
            {t('geo_hub.place.anchor_first', {
              defaultValue:
                'Set the project location on the map first. 3D models need an anchor to be placed; close this and use "Anchor this project".',
            })}
          </span>
        </div>
      )}

      {isLoading && (
        <div
          className="flex items-center justify-center gap-2 py-12 text-sm text-content-tertiary"
          role="status"
        >
          <Loader2 size={18} className="animate-spin" />
          {t('geo_hub.place.loading', { defaultValue: 'Loading project files...' })}
        </div>
      )}

      {nothingToPlace && (
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-secondary text-content-tertiary">
            <Boxes size={22} />
          </div>
          <p className="max-w-sm text-sm text-content-secondary">
            {t('geo_hub.place.empty', {
              defaultValue:
                'This project has no models or PDF drawings yet. Add a BIM model or upload a drawing, then come back to place it on the map.',
            })}
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Link
              to={`/projects/${projectId}/bim`}
              className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-oe-blue/90"
            >
              <Plus size={13} />
              {t('geo_hub.place.add_model', { defaultValue: 'Add a BIM model' })}
            </Link>
            <Link
              to={`/projects/${projectId}/files`}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-primary px-3 py-1.5 text-xs font-semibold text-content-secondary transition hover:bg-surface-secondary"
            >
              <Plus size={13} />
              {t('geo_hub.place.add_pdf', { defaultValue: 'Upload a drawing' })}
            </Link>
          </div>
        </div>
      )}

      {!isLoading && !nothingToPlace && (
        <div className="space-y-5">
          {/* 3D models -------------------------------------------------- */}
          {models.length > 0 && (
            <section>
              <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                <Boxes size={13} />
                {t('geo_hub.place.models_heading', {
                  defaultValue: '3D models',
                })}
              </h4>
              <ul className="divide-y divide-border-light overflow-hidden rounded-lg border border-border-light">
                {models.map((model) => {
                  const fmt = modelFormatOf(model);
                  const ready = model.status === 'ready';
                  const hasGeom = modelHasGeometry(model);
                  const placed = placedModelIds.has(model.id);
                  const placeable = ready && hasGeom && hasAnchor;
                  const busy = busyId === model.id;
                  return (
                    <li
                      key={model.id}
                      className="flex items-center gap-3 bg-surface-primary px-3.5 py-2.5"
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-oe-blue/10 text-oe-blue">
                        <Boxes size={16} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-content-primary">
                          {model.name}
                        </p>
                        <p className="flex items-center gap-1.5 text-xs text-content-tertiary">
                          {fmt && (
                            <span className="rounded bg-surface-secondary px-1.5 py-0.5 font-mono text-2xs uppercase">
                              {fmt}
                            </span>
                          )}
                          {ready
                            ? t('geo_hub.place.model_ready', {
                                defaultValue: '{{count}} elements',
                                count: model.element_count ?? 0,
                              })
                            : t('geo_hub.place.model_not_ready', {
                                defaultValue: 'Not converted yet',
                              })}
                        </p>
                      </div>
                      {placed ? (
                        <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                          <Check size={13} />
                          {t('geo_hub.place.on_map', {
                            defaultValue: 'On the map',
                          })}
                        </span>
                      ) : placeable ? (
                        <button
                          type="button"
                          onClick={() => place3dModel(model)}
                          disabled={busy || Boolean(busyId)}
                          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-oe-blue/90 disabled:cursor-wait disabled:opacity-60"
                        >
                          {busy ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <MapPin size={13} />
                          )}
                          {t('geo_hub.place.place_cta', {
                            defaultValue: 'Place on map',
                          })}
                        </button>
                      ) : ready && !hasGeom ? (
                        <span className="inline-flex items-center gap-1 text-xs text-content-tertiary">
                          <AlertTriangle size={13} />
                          {t('geo_hub.place.no_geometry_chip', {
                            defaultValue: 'No 3D geometry',
                          })}
                        </span>
                      ) : (
                        <Link
                          to={`/projects/${projectId}/bim/${model.id}`}
                          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs font-semibold text-content-secondary transition hover:bg-surface-secondary"
                        >
                          {t('geo_hub.place.open_in_bim', {
                            defaultValue: 'Convert first',
                          })}
                          <ArrowUpRight size={13} />
                        </Link>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {/* The PDF list below is filtered from one page of the register, so
              a drawing past that page cannot be placed and nothing on screen
              would say why. Gated on the server page, never on the filtered
              PDFs: the sentence is about the register, not about how many of
              its rows happened to be PDFs. */}
          {documentsQuery.data ? (
            <TruncationNotice page={documentsQuery.data} />
          ) : null}

          {/* PDF drawings --------------------------------------------- */}
          {pdfs.length > 0 && (
            <section>
              <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                <FileText size={13} />
                {t('geo_hub.place.pdfs_heading', {
                  defaultValue: 'PDF drawings',
                })}
              </h4>
              <ul className="divide-y divide-border-light overflow-hidden rounded-lg border border-border-light">
                {pdfs.map((doc) => {
                  const placed = placedPdfNames.has(doc.name);
                  const busy = busyId === doc.id;
                  return (
                    <li
                      key={doc.id}
                      className="flex items-center gap-3 bg-surface-primary px-3.5 py-2.5"
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-rose-500/10 text-rose-500">
                        <FileText size={16} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-content-primary">
                          {doc.name}
                        </p>
                        <p className="text-xs text-content-tertiary">
                          {fmtFixed((doc.file_size ?? 0) / 1024 / 1024, 1)} MB
                        </p>
                      </div>
                      {placed ? (
                        <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                          <Check size={13} />
                          {t('geo_hub.place.on_map', {
                            defaultValue: 'On the map',
                          })}
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => placePdf(doc)}
                          disabled={busy || Boolean(busyId)}
                          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-oe-blue/90 disabled:cursor-wait disabled:opacity-60"
                        >
                          {busy ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <MapPin size={13} />
                          )}
                          {t('geo_hub.place.place_cta', {
                            defaultValue: 'Place on map',
                          })}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </div>
      )}
    </WideModal>
  );
}

export default PlaceOnMapPicker;
