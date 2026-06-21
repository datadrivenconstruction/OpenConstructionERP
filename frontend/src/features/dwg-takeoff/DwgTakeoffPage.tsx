/**
 * DWG Takeoff page — upload DWG/DXF drawings, view entities in a Canvas2D
 * renderer, toggle layers, and create measurement annotations.
 *
 * Layout:
 *  - Top toolbar: annotation tool palette
 *  - Center: DXF canvas viewer (or empty state)
 *  - Right panel: layers, annotations, selected entity properties
 *  - Bottom filmstrip: drawing list + upload (like BIM page)
 */

import {
  useState,
  useMemo,
  useCallback,
  useRef,
  useEffect,
  type ReactNode,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import {
  calculateArea,
  calculateAreaSafe,
  type AreaDegeneracy,
  calculateDistance,
  calculatePerimeter,
  getSegmentLengths,
  formatMeasurement,
  unitFactorToMetres,
} from './lib/measurement';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import clsx from 'clsx';
import {
  Upload,
  FileUp,
  Trash2,
  Loader2,
  FileText,
  Layers,
  Zap,
  MessageSquare,
  Info,
  Plus,
  X,
  ShieldCheck,
  Link2,
  EyeOff,
  Eye,
  FolderPlus,
  Sigma,
  Wifi,
  WifiOff,
  BarChart3,
  Download,
  CheckSquare,
  CalendarDays,
  ClipboardCheck,
  ListChecks,
  Ruler,
  FileDown,
  RotateCcw,
  GitCompare,
  Hash,
} from 'lucide-react';
import { Badge, ConfirmDialog, DismissibleInfo, ElementInfoPopover, ModuleGuideButton, type DWGElementPayload } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useDwgUploadStore } from '@/stores/useDwgUploadStore';
import { apiGet } from '@/shared/lib/api';
import { boqApi, normalizePositions, type Position } from '@/features/boq/api';
import { projectsApi } from '@/features/projects/api';
import { installBIMConverter } from '@/features/bim/api';
import { ConverterInstallProgressBar } from '@/features/bim/ConverterInstallProgressBar';
import { AutoInstallConverterNotice } from '@/features/bim/AutoInstallConverterNotice';
import { useAutoInstallConverter } from '@/features/bim/useAutoInstallConverter';
import {
  fetchDrawing,
  fetchDrawings,
  deleteDrawing,
  fetchEntities,
  fetchAnnotations,
  createAnnotation,
  deleteAnnotation,
  linkAnnotationToBoq,
  createEntityGroup,
  fetchOfflineReadiness,
  updateDrawingScale,
  importDrawingFromDocument,
  USER_MARKUP_LAYER,
} from './api';
import { Undo2, Redo2, Target, Search, ChevronUp, ChevronDown } from 'lucide-react';
import type {
  DxfEntity,
  DxfLayer,
  DwgAnnotation,
  CreateAnnotationPayload,
  DwgOfflineReadiness,
  DwgScaleMode,
} from './api';
import {
  DxfViewer,
  type EntitySelectEvent,
  type EntityContextMenuEvent,
} from './components/DxfViewer';
import { aggregateEntities } from './lib/group-aggregation';
import { findTextMatches, type DwgTextMatch } from './lib/dwg-textsearch';
import {
  quantifyByLayer,
  quantityFor,
  unitForMeasure,
  type LayerQuantity,
  type QuantifyMeasure,
} from './lib/auto-quantify';
import { exportQuantifyToExcel } from './lib/dwg-quantify-export';
import { exportCanvasToPdf } from './lib/pdf-export';
import { ToolPalette, type DwgTool } from './components/ToolPalette';
import { CalibrationDialog, type CalibrationStep } from './components/CalibrationDialog';
import { SheetStrip } from './components/SheetStrip';
import {
  DwgDrawingCompareDrawer,
  type DwgCompareOverlayState,
} from './DwgDrawingCompareDrawer';
import { dwgTakeoffGuide } from './dwgTakeoffGuide';
import {
  deriveScale as deriveCalibration,
  type CalibrationState,
  type CalibrationUnit,
} from './lib/calibration';
import {
  calibrationKey,
  loadCalibration,
  saveCalibration,
} from './lib/calibration-store';
import {
  canRedo as canRedoFn,
  canUndo as canUndoFn,
  emptyUndoState,
  popRedo,
  popUndo,
  pushUndo,
  snapshotFrom,
  type UndoEntry,
  type UndoState,
} from './lib/undo-stack';
import type { SnapModes } from './lib/snap';
import { LayerPanel } from './components/LayerPanel';
import { EntityNameFilter, entityDisplayName } from './components/EntityNameFilter';
import CreateTaskFromDwgModal from './CreateTaskFromDwgModal';
import LinkDocumentToDwgModal from './LinkDocumentToDwgModal';
import LinkActivityToDwgModal from './LinkActivityToDwgModal';
import LinkRequirementToDwgModal from './LinkRequirementToDwgModal';
// boqApi / Position import removed — BOQ picker now handled via ElementInfoPopover callback

/* ── GridBackground ──────────────────────────────────────────────────── */

/**
 * AutoCAD-style drafting grid background.
 *
 * Renders two overlaid grids (minor 24px, major 120px — classic 1:5 ratio)
 * plus a radial vignette that darkens the corners so content in the middle
 * reads as the focal point. Meant to sit absolutely behind landing / empty
 * state content of the DWG Takeoff page. Pointer-events disabled so it
 * never interferes with the upload card or buttons on top.
 *
 * Dark mode uses faint white lines on the dark canvas; light mode uses
 * faint black lines. Opacities are intentionally low — the grid should
 * whisper, not shout.
 */
function GridBackground({ className = '' }: { className?: string }) {
  return (
    <div className={clsx('absolute inset-0 pointer-events-none overflow-hidden', className)}>
      {/* Grid lines — minor (24px) + major (120px), 1:5 AutoCAD-style ratio */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: `
            linear-gradient(to right, var(--oe-dwg-grid-major) 1px, transparent 1px),
            linear-gradient(to bottom, var(--oe-dwg-grid-major) 1px, transparent 1px),
            linear-gradient(to right, var(--oe-dwg-grid-minor) 1px, transparent 1px),
            linear-gradient(to bottom, var(--oe-dwg-grid-minor) 1px, transparent 1px)
          `,
          backgroundSize: '120px 120px, 120px 120px, 24px 24px, 24px 24px',
        }}
      />
      {/* Vignette — darker at corners, transparent in the middle */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse at center, transparent 0%, transparent 45%, var(--oe-dwg-vignette) 100%)',
        }}
      />
    </div>
  );
}

/* ── Helpers ─────────────────────────────────────────────────────────── */

function extractLayers(
  entities: DxfEntity[],
  annotations: DwgAnnotation[] = [],
): DxfLayer[] {
  const map = new Map<string, { color: string | number; count: number }>();
  for (const e of entities) {
    const existing = map.get(e.layer);
    if (existing) {
      existing.count++;
    } else {
      map.set(e.layer, { color: e.color, count: 1 });
    }
  }
  // Virtual layers (USER_MARKUP / ANNOTATIONS) — one entry per distinct
  // ``layer_name`` found on the annotation list, so estimators can toggle
  // hand-drawn markups separately from DXF entity layers. Default fallback
  // is USER_MARKUP for legacy annotations without a layer_name.
  const annLayerCounts = new Map<string, number>();
  for (const ann of annotations) {
    const name = ann.layer_name || USER_MARKUP_LAYER;
    annLayerCounts.set(name, (annLayerCounts.get(name) ?? 0) + 1);
  }
  for (const [name, count] of annLayerCounts.entries()) {
    if (!map.has(name)) {
      // Use a neutral accent color that stands out from DXF defaults.
      map.set(name, { color: '#f59e0b', count });
    } else {
      map.get(name)!.count += count;
    }
  }

  return Array.from(map.entries())
    .map(([name, { color, count }]) => ({
      name,
      color,
      visible: true,
      entity_count: count,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Convert a DxfEntity into the shared ElementInfoPopover payload shape.
 *
 *  ``effectiveScale`` converts raw DXF units to real metres (combines the
 *  DXF $INSUNITS factor with the user-picked paper scale). Without it the
 *  popover shows raw coordinate numbers — e.g. ``3580.2 m`` for a 3.58 m
 *  wall that is stored in a mm-unit file. */
function toDWGElementPayload(
  entity: DxfEntity,
  effectiveScale: number,
  opts?: {
    calculatePerimeter?: (verts: { x: number; y: number }[], closed: boolean) => number;
    calculateArea?: (verts: { x: number; y: number }[]) => number;
    calculateDistance?: (a: { x: number; y: number }, b: { x: number; y: number }) => number;
  },
): DWGElementPayload {
  const measurements: Record<string, { value: number; unit: string }> = {};
  const s = effectiveScale;
  const s2 = s * s;

  // Polyline measurements
  if (entity.type === 'LWPOLYLINE' && entity.vertices && entity.vertices.length >= 2) {
    const closed = !!entity.closed;
    if (opts?.calculatePerimeter) {
      measurements['Perimeter'] = {
        value: opts.calculatePerimeter(entity.vertices, closed) * s,
        unit: 'm',
      };
    }
    if (closed && opts?.calculateArea) {
      const area = opts.calculateArea(entity.vertices) * s2;
      if (area > 0) {
        measurements['Area'] = { value: area, unit: 'm\u00B2' };
      }
    }
    measurements['Segments'] = {
      value: closed ? entity.vertices.length : entity.vertices.length - 1,
      unit: '',
    };
  }

  // Line length
  if (entity.type === 'LINE' && entity.start && entity.end && opts?.calculateDistance) {
    measurements['Length'] = {
      value: opts.calculateDistance(entity.start, entity.end) * s,
      unit: 'm',
    };
  }

  // Circle measurements
  if (entity.type === 'CIRCLE' && entity.radius != null) {
    const r = entity.radius * s;
    measurements['Radius'] = { value: r, unit: 'm' };
    measurements['Circumference'] = {
      value: 2 * Math.PI * r,
      unit: 'm',
    };
    measurements['Area'] = {
      value: Math.PI * r ** 2,
      unit: 'm\u00B2',
    };
  }

  // ARC radius
  if (entity.type === 'ARC' && entity.radius != null) {
    measurements['Radius'] = { value: entity.radius * s, unit: 'm' };
  }

  // Extra properties
  const properties: Record<string, unknown> = {};
  if (entity.text) properties['Text'] = entity.text;
  if (entity.block_name) properties['Block'] = entity.block_name;
  if (entity.closed !== undefined) properties['Closed'] = entity.closed ? 'Yes' : 'No';
  if (entity.height != null) properties['Height'] = entity.height;
  if (entity.rotation != null) properties['Rotation'] = entity.rotation;

  return {
    source: 'dwg',
    id: entity.id,
    type: entity.type,
    layer: entity.layer,
    color: entity.color,
    measurements,
    properties,
  };
}

/**
 * Compute a geometric centroid for a DXF entity. Used as the insertion
 * point for the `text_pin` annotation that backs a BOQ link.  Falls back
 * sensibly when the entity doesn't carry the shape it "should" (defensive —
 * DXF files in the wild are messy).
 */
function computeEntityCentroid(entity: DxfEntity): { x: number; y: number } {
  if (entity.type === 'LINE' && entity.start && entity.end) {
    return {
      x: (entity.start.x + entity.end.x) / 2,
      y: (entity.start.y + entity.end.y) / 2,
    };
  }
  if (entity.vertices && entity.vertices.length > 0) {
    const n = entity.vertices.length;
    const sum = entity.vertices.reduce(
      (acc, v) => ({ x: acc.x + v.x, y: acc.y + v.y }),
      { x: 0, y: 0 },
    );
    return { x: sum.x / n, y: sum.y / n };
  }
  if (entity.start) return entity.start;
  return { x: 0, y: 0 };
}

/**
 * Derive the primary BOQ-relevant measurement from a DXF entity.
 * Returns the canonical backend unit (`m` / `m2`) and rounded value,
 * or null when the entity carries no measurable geometry.
 *
 * ``effectiveScale`` converts raw DXF units to real metres. Combines
 * the DXF header's $INSUNITS (mm/cm/m/…) with the user-chosen paper
 * scale. Callers must pass this so the value that gets pushed to BOQ
 * matches what the user sees on the canvas.
 */
function extractEntityMeasurement(
  entity: DxfEntity,
  effectiveScale: number,
): { value: number; unit: string; kind: 'length' | 'area' | 'radius' } | null {
  const s = effectiveScale;
  const s2 = s * s;
  if (entity.type === 'LWPOLYLINE' && entity.vertices && entity.vertices.length >= 2) {
    const closed = !!entity.closed;
    if (closed) {
      const area = calculateArea(entity.vertices) * s2;
      if (area > 0) {
        return { value: Math.round(area * 100) / 100, unit: 'm2', kind: 'area' };
      }
    }
    const perimeter = calculatePerimeter(entity.vertices, closed) * s;
    return { value: Math.round(perimeter * 100) / 100, unit: 'm', kind: 'length' };
  }
  if (entity.type === 'LINE' && entity.start && entity.end) {
    const len = calculateDistance(entity.start, entity.end) * s;
    return { value: Math.round(len * 100) / 100, unit: 'm', kind: 'length' };
  }
  if (entity.type === 'CIRCLE' && entity.radius != null) {
    const area = Math.PI * (entity.radius * s) ** 2;
    return { value: Math.round(area * 100) / 100, unit: 'm2', kind: 'area' };
  }
  if (entity.type === 'ARC' && entity.radius != null) {
    return { value: Math.round(entity.radius * s * 100) / 100, unit: 'm', kind: 'radius' };
  }
  return null;
}

/* ── Offline Ready badge (R3 #9) ──────────────────────────────────── */

/**
 * Small pill that surfaces the backend "offline-readiness" probe.
 *
 * Traffic-light states:
 *   🟢 ``ready`` — local DWG converter present; everything runs offline.
 *   🟡 ``converter_available=false`` — DXF-only mode; hint to install
 *      the binary to unlock ``.dwg`` upload. Also surfaced when the
 *      probe failed to reach the backend (treated as "unknown").
 * Clicking the pill reveals a concise install hint; the tooltip on
 * hover conveys the 80 % case without any interaction.
 */
function OfflineReadyBadge({
  readiness,
  isLoading,
  'data-testid': testId,
}: {
  readiness: DwgOfflineReadiness | undefined;
  isLoading: boolean;
  'data-testid'?: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showHint, setShowHint] = useState(false);

  // One-click DDC DWG converter install. Hits the same
  // /v1/takeoff/converters/dwg/install/ endpoint the BIM page uses, then
  // invalidates `dwg-offline-readiness` so the green "Offline Ready" pill
  // appears without a manual refresh.
  const installMutation = useMutation({
    mutationFn: () => installBIMConverter('dwg'),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['dwg-offline-readiness'] });
      queryClient.invalidateQueries({ queryKey: ['bim-converters'] });
      if (result.installed) {
        addToast({
          type: 'success',
          title: t('dwg_takeoff.converter_install_success_title', {
            defaultValue: 'DWG converter installed',
          }),
          message:
            result.message ||
            t('dwg_takeoff.converter_install_success_msg', {
              defaultValue: '.dwg uploads will now run locally.',
            }),
        });
        setShowHint(false);
      } else if (result.platform_unsupported && result.platform === 'linux') {
        const instructions = result.instructions
          ? `\n\n${result.instructions}`
          : result.apt_package
            ? `\n\nsudo apt install -y ${result.apt_package}`
            : '';
        addToast(
          {
            type: 'info',
            title: t('dwg_takeoff.converter_install_linux_title', {
              defaultValue: 'Run apt to finish installing',
            }),
            message:
              (result.message || 'Install via apt to enable .dwg uploads') +
              instructions,
          },
          { duration: 45_000 },
        );
      } else {
        addToast({
          type: 'warning',
          title: t('dwg_takeoff.converter_install_partial_title', {
            defaultValue: 'Install needs attention',
          }),
          message: result.message || 'Could not finish the install.',
        });
      }
    },
    onError: (error: unknown) => {
      const message =
        error instanceof Error ? error.message : String(error ?? 'Unknown error');
      addToast({
        type: 'error',
        title: t('dwg_takeoff.converter_install_error_title', {
          defaultValue: 'Install failed',
        }),
        message,
      });
    },
  });

  if (isLoading) {
    return (
      <div
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-secondary border border-border-light text-[11px] text-content-tertiary"
        data-testid={testId}
      >
        <Loader2 size={11} className="animate-spin" />
        {t('dwg_takeoff.offline_checking', { defaultValue: 'Checking...' })}
      </div>
    );
  }

  const ready = readiness?.ready ?? false;
  const converterMissing = readiness && !readiness.converter_available;
  // Only claim "runs on your machine" when the server is genuinely a
  // same-machine, non-hosted deployment. On the hosted demo we tell the
  // honest truth: processing happens on the user's OpenConstructionERP
  // server and is never forwarded to a third party.
  const localOnly = readiness?.local_only ?? false;
  const readyTooltip = localOnly
    ? t('dwg_takeoff.offline_ready_tooltip_local', {
        defaultValue:
          'This tool works fully offline - conversions run on your machine.',
      })
    : t('dwg_takeoff.offline_ready_tooltip_server', {
        defaultValue:
          'Conversions run on your OpenConstructionERP server and are never sent to third parties.',
      });

  return (
    <div className="relative" data-testid={testId}>
      <button
        type="button"
        onClick={() => setShowHint((v) => !v)}
        className={clsx(
          'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-medium transition-colors',
          ready
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/15'
            : 'bg-amber-500/10 border-amber-500/30 text-amber-300 hover:bg-amber-500/15',
        )}
        title={
          ready
            ? readyTooltip
            : t('dwg_takeoff.offline_install_tooltip', {
                defaultValue:
                  'Install the local DWG converter to enable offline .dwg conversion. DXF files already work.',
              })
        }
        aria-label={
          ready
            ? t('dwg_takeoff.offline_ready', { defaultValue: 'Offline Ready' })
            : t('dwg_takeoff.offline_install', { defaultValue: 'Install converter' })
        }
      >
        {ready ? <Wifi size={11} /> : <WifiOff size={11} />}
        <span className="relative flex h-1.5 w-1.5">
          <span
            className={clsx(
              'absolute inline-flex h-full w-full rounded-full opacity-75',
              ready ? 'bg-emerald-400 animate-ping' : 'bg-amber-400',
            )}
          />
          <span
            className={clsx(
              'relative inline-flex h-1.5 w-1.5 rounded-full',
              ready ? 'bg-emerald-400' : 'bg-amber-400',
            )}
          />
        </span>
        {ready
          ? t('dwg_takeoff.offline_ready', { defaultValue: 'Offline Ready' })
          : t('dwg_takeoff.offline_install', { defaultValue: 'Install converter' })}
      </button>

      {showHint && (
        <div
          className="absolute top-full right-0 mt-1.5 z-30 w-72 rounded-lg border border-border-light bg-surface-elevated shadow-xl p-3 text-[11px]"
          data-testid="dwg-offline-hint"
        >
          <div className="flex items-start justify-between gap-2 mb-1.5">
            <div className="font-semibold text-content-primary">
              {ready
                ? t('dwg_takeoff.offline_ready', { defaultValue: 'Offline Ready' })
                : t('dwg_takeoff.offline_install', { defaultValue: 'Install converter' })}
            </div>
            <button
              type="button"
              onClick={() => setShowHint(false)}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              title={t('common.close', { defaultValue: 'Close' })}
              className="text-content-tertiary hover:text-content-primary"
            >
              <X size={12} />
            </button>
          </div>
          <p className="text-content-secondary leading-relaxed">
            {readiness?.message ?? readyTooltip}
          </p>
          {converterMissing && (
            <>
              <div className="mt-2 rounded-md bg-amber-500/10 border border-amber-500/20 px-2 py-1.5 text-[10px] text-amber-300">
                {t('dwg_takeoff.offline_install_hint', {
                  defaultValue:
                    'Upload DXF files to continue without the converter, or install it to enable .dwg support.',
                })}
              </div>
              <button
                type="button"
                onClick={() => installMutation.mutate()}
                disabled={installMutation.isPending}
                data-testid="dwg-converter-install-btn"
                className="mt-2 w-full inline-flex items-center justify-center gap-1.5 rounded-md bg-oe-blue text-white text-[11px] font-semibold px-2.5 py-2 hover:bg-oe-blue-dark disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
              >
                {installMutation.isPending ? (
                  <>
                    <Loader2 size={12} className="animate-spin" />
                    {t('dwg_takeoff.converter_installing', {
                      defaultValue: 'Installing…',
                    })}
                  </>
                ) : (
                  <>
                    <Download size={12} />
                    {t('dwg_takeoff.converter_install_now', {
                      defaultValue: 'Install latest DWG converter',
                    })}
                  </>
                )}
              </button>
              {installMutation.isPending && (
                <div className="mt-2">
                  <ConverterInstallProgressBar
                    converterId="dwg"
                    installing={installMutation.isPending}
                  />
                </div>
              )}
              <a
                href="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN/tree/main/DDC_WINDOWS_Converters/DDC_CONVERTER_DWG"
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1.5 block text-center text-[10px] text-content-tertiary hover:text-content-secondary underline"
              >
                {t('dwg_takeoff.converter_install_manual', {
                  defaultValue: 'Manual install instructions',
                })}
              </a>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Component ─────────────────────────────────────────────────────── */

export function DwgTakeoffPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  // Fallback: if no project is currently active (e.g. first load after
  // ``clearProject`` wiped a stale id from localStorage), use the first
  // project from the server list. Without this, ``fetchDrawings('')``
  // short-circuits to ``[]`` and the DWG panel looks empty on every
  // reload — reported as "при перезагрузке потеряются все документы".
  // The drawings themselves are always persisted server-side; only the
  // client-side project context was lost.
  const { data: projects = [], isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 5 * 60_000,
  });
  const projectId = activeProjectId || projects[0]?.id || '';
  const noProjects = !projectsLoading && projects.length === 0;

  // Persist the fallback choice so subsequent reloads and sibling
  // modules (BIM, BOQ, CDE) see the same active project instead of each
  // picking the "first" independently.
  useEffect(() => {
    if (!activeProjectId && projectId) {
      const picked = projects.find((p) => p.id === projectId);
      if (picked) setActiveProject(picked.id, picked.name);
    }
  }, [activeProjectId, projectId, projects, setActiveProject]);

  // Deep-link support: ?drawingId=xxx opens a specific drawing.
  // From the Documents / File Manager "Open in DWG Takeoff" action we also
  // accept ?docId=xxx (+ optional ?docName=xxx). When a document has no
  // matching drawing yet we import one on demand (see the effect below) so
  // the document opens immediately instead of showing a blank viewer.
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkDrawingId = searchParams.get('drawingId');
  const deepLinkDocId = searchParams.get('docId');
  const deepLinkDocName = searchParams.get('docName');
  /** Tracks the in-flight on-demand import from a document deep-link so the
   *  viewer shows an honest "Opening document…" card instead of the empty
   *  upload hero while the drawing is being created server-side. Latched by
   *  document id so a single deep-link is imported exactly once even under
   *  StrictMode's double-effect-invoke in dev. */
  const [importingDocId, setImportingDocId] = useState<string | null>(null);
  const importedDocRef = useRef<string | null>(null);

  // State
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  // Revision compare (Item 17) — drawer visibility + onion-skin overlay hint.
  const [showCompare, setShowCompare] = useState(false);
  const [compareOverlay, setCompareOverlay] = useState<DwgCompareOverlayState>({
    enabled: false,
    opacity: 0.5,
  });
  const [activeTool, setActiveTool] = useState<DwgTool>('select');
  const [activeColor, setActiveColor] = useState('#ef4444');

  /* ── Q1 UX #2: Undo / redo stack ────────────────────────────────────
   * Holds the last 50 annotation mutations (create / delete / edit).
   * Reset when the selected drawing changes — an undo from drawing A
   * should not delete something on drawing B. */
  const [undoState, setUndoState] = useState<UndoState>(() => emptyUndoState());
  useEffect(() => {
    setUndoState(emptyUndoState());
  }, [selectedDrawingId]);

  /* ── Q1 UX #4: Snap modes ──────────────────────────────────────────
   * Estimators who want endpoint-only usually work across large plans,
   * so both modes default off. Persisted to localStorage so the user's
   * last choice survives a reload — snap mode is a preference, not a
   * per-drawing setting. */
  const [snapModes, setSnapModes] = useState<SnapModes>(() => {
    try {
      const raw = localStorage.getItem('dwg:snap_modes');
      if (raw) return JSON.parse(raw) as SnapModes;
    } catch {
      /* fall through */
    }
    return { endpoint: false, midpoint: false, intersection: false };
  });
  useEffect(() => {
    try {
      localStorage.setItem('dwg:snap_modes', JSON.stringify(snapModes));
    } catch {
      /* storage quota / disabled — acceptable fallback is in-memory only */
    }
  }, [snapModes]);
  const [snapMenuOpen, setSnapMenuOpen] = useState(false);
  /**
   * Drawing scale denominator (RFC 13 #13). `1` = use raw DXF units as
   * meters. `50` = the drawing is 1:50, so a 0.20-unit segment represents
   * 10 metres in the real world. Persisted per-drawing in localStorage so
   * the estimator doesn't have to re-enter it every time they reopen a
   * site plan.
   */
  const [drawingScale, setDrawingScale] = useState<number>(1);
  const [scaleMode, setScaleMode] = useState<DwgScaleMode>('preset');
  const [isCalibrating, setIsCalibrating] = useState(false);
  const [calibrationPixels, setCalibrationPixels] = useState<number | null>(null);

  /* ── Two-click calibration (Goal 1) ──────────────────────────────────
   * Independent of the pre-existing scale/calibration UI in the right
   * panel. Driven by the "Calibrate" (K) tool in the palette:
   *   - ``calibStep`` walks the state machine: 1 = waiting for A,
   *     2 = waiting for B, 3 = modal open with length input.
   *   - ``calibPointA`` / ``calibPointB`` are world-space coordinates
   *     captured from the viewer's ``onCalibrationPoint`` callback.
   *   - ``calibration`` is the active (persisted) scale for the current
   *     drawing + layout, loaded from localStorage on select/layout change. */
  const [calibStep, setCalibStep] = useState<CalibrationStep>(0);
  const [calibPointA, setCalibPointA] = useState<{ x: number; y: number } | null>(null);
  const [calibPointB, setCalibPointB] = useState<{ x: number; y: number } | null>(null);
  const [calibration, setCalibration] = useState<CalibrationState | null>(null);

  // Persist the scale per drawing ID — switching drawings restores its scale.
  useEffect(() => {
    if (!selectedDrawingId) return;
    const raw = localStorage.getItem(`dwg:scale:${selectedDrawingId}`);
    const parsed = raw ? Number(raw) : NaN;
    setDrawingScale(Number.isFinite(parsed) && parsed > 0 ? parsed : 1);
    setScaleMode(
      (localStorage.getItem(`dwg:scale_mode:${selectedDrawingId}`) as DwgScaleMode | null) ?? 'preset',
    );
    // Reset transient calibration state when the user switches drawing.
    setIsCalibrating(false);
    setCalibrationPixels(null);
  }, [selectedDrawingId]);

  useEffect(() => {
    if (!selectedDrawingId) return;
    localStorage.setItem(`dwg:scale:${selectedDrawingId}`, String(drawingScale));
    localStorage.setItem(`dwg:scale_mode:${selectedDrawingId}`, scaleMode);
  }, [selectedDrawingId, drawingScale, scaleMode]);

  /* ── DWG upload store subscription ───────────────────────────────────
   * When a store-based upload finishes, invalidate the drawings list and
   * auto-select the new one. Runs outside React so a job that completes
   * while the user is on another page still refreshes their list on
   * return. */
  useEffect(() => {
    const unsub = useDwgUploadStore.subscribe((state, prevState) => {
      if (!projectId) return;
      for (const [id, job] of state.jobs) {
        const prev = prevState.jobs.get(id);
        // As soon as the upload POST returns and the backend's drawing
        // row exists (drawingId is set), auto-select it so the user
        // immediately sees the ConversionProgressCard bound to *their*
        // specific drawing — instead of staring at the upload card with
        // a vague corner dock. The card itself drives the 3-8 minute
        // wait honestly, with elapsed time + step list.
        if (
          job.drawingId
          && !prev?.drawingId
          && job.projectId === projectId
        ) {
          queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
          setSelectedDrawingId(job.drawingId);
        }
        if (prev?.status !== 'ready' && job.status === 'ready' && job.projectId === projectId) {
          queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
          queryClient.invalidateQueries({ queryKey: ['documents'] });
          queryClient.invalidateQueries({ queryKey: ['dwg-entities', job.drawingId] });
          if (job.drawingId) setSelectedDrawingId(job.drawingId);
          addToast({
            type: 'success',
            title: t('dwg_takeoff.upload_success', { defaultValue: 'Drawing uploaded' }),
          });
        }
        if (prev?.status !== 'error' && job.status === 'error' && job.projectId === projectId) {
          addToast({
            type: 'error',
            title: t('dwg_takeoff.upload_error', { defaultValue: 'Upload failed' }),
            message: job.errorMessage ?? undefined,
          });
        }
      }
    });
    return unsub;
  }, [projectId, queryClient, addToast, t]);
  const [visibleLayers, setVisibleLayers] = useState<Set<string>>(new Set());
  const [visibleNames, setVisibleNames] = useState<Set<string>>(new Set());
  /**
   * Full layer roster for the drawing, accumulated across server-filtered
   * entity fetches. The entities query only ships the layers the user has
   * toggled on (perf — a medium DWG carries 50k+ entities), which means the
   * `layers` list derived from those entities would otherwise lose every
   * hidden layer's row and the user could never re-enable it. We remember
   * the union of layer names + metadata ever seen so the LayerPanel keeps
   * the complete, toggle-able roster regardless of what the last fetch
   * filtered out. Reset whenever the selected drawing changes.
   */
  const [allLayers, setAllLayers] = useState<DxfLayer[]>([]);
  /**
   * Multi-entity selection (RFC 11). A single-click produces a one-item set;
   * Shift+click toggles membership; Escape clears. `primarySelectedEntityId`
   * below is the first element of the set and drives the single-entity UI
   * affordances (properties panel, link-to-BOQ popover).
   */
  const [selectedEntityIds, setSelectedEntityIds] = useState<Set<string>>(new Set());
  /** Per-entity hide state (RFC 11). Filter is applied in DxfViewer. */
  const [hiddenEntityIds, setHiddenEntityIds] = useState<Set<string>>(new Set());
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<string | null>(null);
  /** Right-click context menu state. */
  const [contextMenu, setContextMenu] = useState<
    { entityId: string; screenX: number; screenY: number } | null
  >(null);
  const [rightTab, setRightTab] = useState<
    'layers' | 'annotations' | 'properties' | 'summary' | 'scale'
  >('layers');

  /** Inline cross-module link modals (mirrors the BIM page pattern).
   *  Each holds the selected DWG entity + drawing context for the
   *  corresponding modal — null when the modal is closed. */
  const [createTaskFor, setCreateTaskFor] = useState<{
    entityIds: string[];
    drawingId: string;
    entityLabel?: string;
  } | null>(null);
  const [linkDocumentFor, setLinkDocumentFor] = useState<{
    entityIds: string[];
    drawingId: string;
    entityLabel?: string;
  } | null>(null);
  const [linkActivityFor, setLinkActivityFor] = useState<{
    entityIds: string[];
    drawingId: string;
    entityLabel?: string;
  } | null>(null);
  const [linkRequirementFor, setLinkRequirementFor] = useState<{
    entityIds: string[];
    drawingId: string;
    entityLabel?: string;
  } | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadName, setUploadName] = useState('');
  const [uploadDiscipline, setUploadDiscipline] = useState('architectural');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  /** Visual drop-zone hover state — flips on `dragenter`/`dragover` and
   *  back on `dragleave`/`drop`. The hero card and modal both bind to it
   *  so the dashed border highlights while a real file is hovering, not
   *  only on mouse-hover. */
  const [isDragActive, setIsDragActive] = useState(false);
  const { confirm: confirmAnnotDelete, ...annotDeleteConfirmProps } = useConfirm();
  // filmstripExpanded removed in v1.8.3 — drawings are always visible
  // per UX feedback. No auto-hide, no collapse toggle.
  /** Screen position for floating entity info popup. */
  const [entityPopup, setEntityPopup] = useState<{ x: number; y: number } | null>(null);

  /* ── BOQ-link picker state ─────────────────────────────────────────
   * Mirrors the self-contained picker from the PDF takeoff module
   * (frontend/src/modules/pdf-takeoff/TakeoffViewerModule.tsx).  The picker
   * can discover project + BOQ on its own and supports creating a new
   * position inline. */
  const [linkingEntityId, setLinkingEntityId] = useState<string | null>(null);
  const [linkPickerProjectId, setLinkPickerProjectId] = useState('');
  const [linkPickerBoqId, setLinkPickerBoqId] = useState('');
  const [linkPickerProjects, setLinkPickerProjects] = useState<{ id: string; name: string }[]>([]);
  const [linkPickerBoqs, setLinkPickerBoqs] = useState<{ id: string; name: string }[]>([]);
  const [linkBoqPositions, setLinkBoqPositions] = useState<Position[]>([]);
  const [linkBoqsLoading, setLinkBoqsLoading] = useState(false);
  const [linkPositionsLoading, setLinkPositionsLoading] = useState(false);
  const [linkingInProgress, setLinkingInProgress] = useState(false);
  const [linkPickerSearch, setLinkPickerSearch] = useState('');
  const [linkPickerMode, setLinkPickerMode] = useState<'pick' | 'create'>('pick');

  // Queries
  const { data: drawings = [], isLoading: loadingDrawings } = useQuery({
    queryKey: ['dwg-drawings', projectId],
    queryFn: () => fetchDrawings(projectId),
    enabled: !!projectId,
  });


  /**
   * Layers to request from the backend. While `visibleLayers` is empty the
   * full roster is not yet known (it is reset on every drawing switch), so
   * we fetch ALL layers unfiltered to discover them. Once the user has a
   * concrete visible set the backend filters the entity payload before
   * serialising — only the toggled-on layers come over the wire. Sorted so
   * the array is a stable React Query cache key (toggling A then B yields
   * the same key as B then A).
   */
  const requestedLayers = useMemo(
    () => Array.from(visibleLayers).sort(),
    [visibleLayers],
  );

  const { data: entities = [], isLoading: loadingEntities } = useQuery({
    queryKey: ['dwg-entities', selectedDrawingId, requestedLayers],
    queryFn: () =>
      fetchEntities(
        selectedDrawingId!,
        requestedLayers.length > 0 ? requestedLayers : undefined,
      ),
    enabled: !!selectedDrawingId,
  });

  const { data: annotations = [] } = useQuery({
    queryKey: ['dwg-annotations', selectedDrawingId],
    queryFn: () => fetchAnnotations(selectedDrawingId!),
    enabled: !!selectedDrawingId,
  });

  /* ── Honest progress: backend status polling ────────────────────────
   * The /drawings list reflects the row at first paint, but for .dwg
   * uploads the backend dispatches conversion as an asyncio.create_task
   * and immediately returns `status="processing"` — that row can stay
   * "processing" for 3-8 minutes on a medium DWG. Without active
   * polling the user previously saw the empty DxfViewer (entities=[])
   * and assumed it was "loaded but broken". Poll every 3.5 s while the
   * drawing is not yet ready so we can render an honest conversion
   * card and invalidate the entities query when it flips to `ready`.
   *
   * The query reads its own dedicated `dwg-drawing` queryKey so we
   * don't keep refetching the whole drawings list (which would also
   * trash the SheetStrip thumbnails). */
  const selectedDrawingFromList = useMemo(
    () => drawings.find((d) => d.id === selectedDrawingId),
    [drawings, selectedDrawingId],
  );
  const { data: liveDrawing } = useQuery({
    queryKey: ['dwg-drawing', selectedDrawingId],
    queryFn: () => fetchDrawing(selectedDrawingId!),
    // Always fetch the single drawing (not just while converting): the
    // /drawings LIST response never carries the resolved unit, so the
    // single-drawing fetch (which embeds latest_version.units) is the only
    // place the frontend learns the drawing's unit and can apply the
    // mm→m factor. The refetchInterval below stops polling once the status
    // is terminal, so a ready drawing is fetched exactly once.
    enabled: !!selectedDrawingId,
    refetchInterval: (q) => {
      const s = (q.state.data as { status?: string } | undefined)?.status;
      // Stop polling once the backend has reached a terminal state.
      // `needs_conversion` is terminal: nothing on the server will move it
      // until the user installs the converter and re-uploads.
      if (s === 'ready' || s === 'error' || s === 'empty' || s === 'needs_conversion') return false;
      return 3500;
    },
    // Keep polling even when the tab is backgrounded so a long DWG/IFC
    // conversion that completes while the user is on another tab is reflected
    // the moment they return, instead of staying pinned on "Converting your
    // drawing…" until a manual reload.
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    staleTime: 0,
    gcTime: 0,
  });

  // Raw DXF unit → real metres factor. Combined with ``drawingScale`` (paper
  // ratio) it produces ``effectiveScale``, the single number every
  // measurement multiplies by. Without it mm-unit files read as "12 000 m
  // walls".
  //
  // Unit resolution order:
  //   1. The single-drawing fetch (``liveDrawing.latest_version.units``) —
  //      the only response that carries the backend-resolved/backfilled unit
  //      (the /drawings LIST never serialises it).
  //   2. The cached list row (kept for the rare first-paint window before the
  //      single-drawing fetch resolves).
  //   3. Belt-and-suspenders: when the unit is still unknown/"unitless",
  //      guess from the drawing's own extent. A plan whose largest extent is
  //      >= 1000 raw units is almost certainly authored in millimetres (the
  //      same heuristic the backend uses), so fall back to the mm factor.
  const knownUnits =
    liveDrawing?.latest_version?.units ??
    selectedDrawingFromList?.units ??
    null;
  /** Largest extent of the loaded entities, in raw drawing units. Used only
   *  for the units guess; ``0`` while entities are still loading. */
  const entitiesMaxDim = useMemo(() => {
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    const expand = (x: number, y: number): void => {
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    };
    for (const e of entities) {
      if (e.start) expand(e.start.x, e.start.y);
      if (e.end) expand(e.end.x, e.end.y);
      if (e.vertices) {
        for (const v of e.vertices) expand(v.x, v.y);
      }
      if (e.start && typeof e.radius === 'number') {
        expand(e.start.x - e.radius, e.start.y - e.radius);
        expand(e.start.x + e.radius, e.start.y + e.radius);
      }
    }
    if (!Number.isFinite(minX) || !Number.isFinite(maxX)) return 0;
    return Math.max(maxX - minX, maxY - minY);
  }, [entities]);
  const unitFactor = useMemo(() => {
    const normalised = (knownUnits ?? '').toLowerCase();
    // Honour an explicitly known unit (do NOT override the user's data).
    if (normalised && normalised !== 'unitless') {
      return unitFactorToMetres(knownUnits);
    }
    // Unknown unit → extents-based guess (mm for large drawings).
    if (entitiesMaxDim >= 1000) return 0.001;
    return unitFactorToMetres(knownUnits);
  }, [knownUnits, entitiesMaxDim]);
  const effectiveScale = drawingScale * unitFactor;
  /** Effective backend status. A terminal status (ready/error/empty) from
   *  EITHER the live poll or the cached drawings list wins, so a stale
   *  "processing" left over in one source after the other has already reached
   *  "ready" can no longer pin the conversion card open until a manual reload.
   *  Otherwise prefer the live-poll value, then the list value, so we don't
   *  briefly drop back into "loading…" between first paint and first poll. */
  const _listStatus = selectedDrawingFromList?.status;
  const _pollStatus = liveDrawing?.status;
  // `needs_conversion` is terminal too: a .dwg with no entities and no
  // converter on the server will never transition on its own, so it must win
  // over a stale `processing`/`uploaded` and surface the convert CTA instead
  // of pinning the spinner open.
  const _isTerminalStatus = (s: string | null | undefined) =>
    s === 'ready' || s === 'error' || s === 'empty' || s === 'needs_conversion';
  const drawingStatus =
    (_isTerminalStatus(_listStatus) ? _listStatus : undefined) ??
    (_isTerminalStatus(_pollStatus) ? _pollStatus : undefined) ??
    _pollStatus ??
    _listStatus ??
    null;
  const isConverting =
    !!selectedDrawingId &&
    (drawingStatus === 'processing' || drawingStatus === 'uploaded');
  const isNeedsConversion = drawingStatus === 'needs_conversion';
  const isErrorStatus = drawingStatus === 'error';
  const isEmptyStatus = drawingStatus === 'empty';
  const drawingErrorMessage =
    liveDrawing?.error_message ?? selectedDrawingFromList?.error_message ?? null;

  // When the backend finishes conversion, invalidate the entities and
  // drawings list queries so the canvas renders the freshly-parsed
  // entities without waiting for the next stale-time cycle.
  useEffect(() => {
    if (drawingStatus === 'ready' && selectedDrawingId) {
      queryClient.invalidateQueries({ queryKey: ['dwg-entities', selectedDrawingId] });
      queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
    }
  }, [drawingStatus, selectedDrawingId, projectId, queryClient]);

  /**
   * Offline-readiness probe (R3 #9). 60 s staleTime — the binary either
   * is or isn't on disk; polling would only add noise. Retry once on
   * network error, then fall through to the yellow "install converter"
   * state which is still a correct user signal.
   */
  const { data: offlineReadiness, isLoading: loadingOfflineReadiness } = useQuery({
    queryKey: ['dwg-offline-readiness'],
    queryFn: fetchOfflineReadiness,
    staleTime: 60_000,
    retry: 1,
  });

  // Auto-install the DWG converter in the background the moment the user
  // picks a .dwg file and the local converter is missing - no click. DXF
  // files parse without a converter, so this is scoped to .dwg only. The
  // notice + progress render inline in the upload modal below; the manual
  // "Install converter" CTA stays as a fallback only.
  const uploadNeedsDwgConverter =
    !!uploadFile &&
    uploadFile.name.toLowerCase().endsWith('.dwg') &&
    !!offlineReadiness &&
    !offlineReadiness.converter_available;
  const dwgAutoInstall = useAutoInstallConverter(
    uploadNeedsDwgConverter ? 'dwg' : null,
    uploadNeedsDwgConverter,
  );

  /** Strip the deep-link params off the URL after one shot so a refresh
   *  doesn't re-trigger selection / import. */
  const clearDeepLinkParams = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete('drawingId');
    next.delete('docId');
    next.delete('docName');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  /* ── On-demand import from a Documents / File Manager deep-link ───────────
   * The Documents page links here as ?docId=<uuid>&docName=<name> for a CAD
   * file that lives only as a Document. Such a file has no drawing to render,
   * so the viewer used to sit blank. We create (or reuse) a drawing from the
   * document via POST /drawings/from-document/ — idempotent server-side — and
   * select the result. Mirrors the BIM page's graceful fallback: on failure
   * we open the upload panel rather than leaving the user on a blank page. */
  const importFromDocumentMutation = useMutation({
    mutationFn: (docId: string) => importDrawingFromDocument(docId, deepLinkDocName ?? undefined),
    onSuccess: (drawing) => {
      queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
      setImportingDocId(null);
      handleSelectDrawing(drawing.id);
      clearDeepLinkParams();
    },
    onError: (err: Error) => {
      setImportingDocId(null);
      // Graceful fallback (BIM-page pattern): surface the reason and open the
      // upload panel pre-filled with the document name so the user can still
      // get the file into the viewer — never a silent blank page.
      addToast({
        type: 'error',
        title: t('dwg_takeoff.import_doc_failed', {
          defaultValue: 'Could not open this document in DWG Takeoff',
        }),
        message: err.message || undefined,
      });
      if (deepLinkDocName) setUploadName(decodeURIComponent(deepLinkDocName).replace(/\.[^.]+$/, ''));
      setShowUpload(true);
      clearDeepLinkParams();
    },
  });

  // Deep-link: auto-select drawing when ?drawingId= / ?docName= is in URL, or
  // import on demand when ?docId= points at a document with no drawing yet.
  useEffect(() => {
    let target: typeof drawings[number] | undefined;

    // 1. Try matching by exact drawing ID.
    if (deepLinkDrawingId) {
      target = drawings.find((d) => d.id === deepLinkDrawingId);
    }

    // 2. Fallback: match by document name from the Documents page (?docName=).
    //    Covers the case where the file was uploaded through the takeoff
    //    module (so a drawing with the same name already exists).
    if (!target && deepLinkDocName) {
      const docNameLower = decodeURIComponent(deepLinkDocName).toLowerCase();
      const docNameNoExt = docNameLower.replace(/\.[^.]+$/, '');
      target = drawings.find(
        (d) =>
          d.name.toLowerCase() === docNameLower ||
          d.name.toLowerCase() === docNameNoExt ||
          d.filename?.toLowerCase() === docNameLower,
      );
    }

    if (target) {
      if (selectedDrawingId !== target.id) {
        handleSelectDrawing(target.id);
        clearDeepLinkParams();
      }
      return;
    }

    // 3. No existing drawing matched. Materialise one on demand from the
    //    source document. We import when either:
    //      - ?docId= is present (the canonical Documents / File Manager
    //        link), or
    //      - ?drawingId= is present but matched nothing AND there's no
    //        ?docId=. The Files page historically passed a Document id as
    //        ?drawingId= (the blank-page bug), and stale bookmarks may
    //        still carry it — treating it as a document id recovers them.
    //    The backend is idempotent (returns the existing drawing if the
    //    document already has one) and 404s a truly bogus id, where the
    //    mutation's onError opens the upload panel instead of staying
    //    blank. Wait for the drawings list to load first so we don't fire
    //    an import for an id that simply hadn't arrived in the list yet.
    const importCandidateId =
      deepLinkDocId || (deepLinkDrawingId && !deepLinkDocName ? deepLinkDrawingId : null);
    if (
      importCandidateId &&
      !loadingDrawings &&
      importedDocRef.current !== importCandidateId &&
      !importFromDocumentMutation.isPending
    ) {
      importedDocRef.current = importCandidateId;
      setImportingDocId(importCandidateId);
      importFromDocumentMutation.mutate(importCandidateId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkDrawingId, deepLinkDocId, deepLinkDocName, drawings, loadingDrawings]);

  // Layout support
  const [selectedLayout, setSelectedLayout] = useState<string | null>(null);

  // Unique layout names from entities
  const layouts = useMemo(() => {
    const set = new Set<string>();
    for (const e of entities) {
      if (e.layout) set.add(e.layout);
    }
    if (set.size === 0) return [];
    // Sort: "Model" / "*Model_Space" first, then alphabetical
    return Array.from(set).sort((a, b) => {
      const aIsModel = a === 'Model' || a === '*Model_Space';
      const bIsModel = b === 'Model' || b === '*Model_Space';
      if (aIsModel && !bIsModel) return -1;
      if (!aIsModel && bIsModel) return 1;
      return a.localeCompare(b);
    });
  }, [entities]);

  // Auto-select first layout when entities load
  useEffect(() => {
    if (layouts.length > 0 && selectedLayout === null) {
      setSelectedLayout(layouts[0] ?? null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layouts]);

  // Per-layout entity counts for the SheetStrip. Memoised so a hover on
  // the strip doesn't re-walk the entity list.
  const entityCountByLayout = useMemo(() => {
    const out: Record<string, number> = {};
    for (const e of entities) {
      const key = e.layout ?? '__default__';
      out[key] = (out[key] ?? 0) + 1;
    }
    return out;
  }, [entities]);

  /**
   * Load the persisted two-click calibration whenever the drawing or
   * layout changes. The key combines projectId + filename + layout so
   * multi-layout files keep a scale per sheet — the same floor plan
   * can appear at 1:50 on one sheet and 1:100 on another.
   */
  useEffect(() => {
    if (!selectedDrawingId) {
      setCalibration(null);
      return;
    }
    const d = drawings.find((x) => x.id === selectedDrawingId);
    if (!d) {
      setCalibration(null);
      return;
    }
    const k = calibrationKey(projectId, d.filename, selectedLayout);
    setCalibration(loadCalibration(k));
  }, [selectedDrawingId, selectedLayout, drawings, projectId]);

  // Abort an in-flight two-click calibration when the user switches tool
  // away from "calibrate" — prevents a stranded Point A from leaking
  // into a subsequent calibration.
  useEffect(() => {
    if (activeTool !== 'calibrate' && calibStep > 0 && calibStep < 3) {
      setCalibStep(0);
      setCalibPointA(null);
      setCalibPointB(null);
    }
  }, [activeTool, calibStep]);

  // Open step 1 as soon as the user picks the tool.
  useEffect(() => {
    if (activeTool === 'calibrate' && calibStep === 0) {
      setCalibStep(1);
      setCalibPointA(null);
      setCalibPointB(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTool]);

  /** Step machine driver — receives world-space clicks from DxfViewer. */
  const handleCalibrationPoint = useCallback(
    (pt: { x: number; y: number }) => {
      if (calibStep === 1) {
        setCalibPointA(pt);
        setCalibStep(2);
      } else if (calibStep === 2) {
        setCalibPointB(pt);
        setCalibStep(3);
      }
    },
    [calibStep],
  );

  /** Confirm handler from the dialog: derive scale, persist, reset. */
  const handleCalibrationConfirm = useCallback(
    (realLength: number, unit: CalibrationUnit) => {
      if (!calibPointA || !calibPointB || !selectedDrawingId) {
        setCalibStep(0);
        return;
      }
      const d = drawings.find((x) => x.id === selectedDrawingId);
      if (!d) {
        setCalibStep(0);
        return;
      }
      try {
        const { unitsPerPixel } = deriveCalibration(
          [calibPointA.x, calibPointA.y],
          [calibPointB.x, calibPointB.y],
          realLength,
          unit,
        );
        const state: CalibrationState = {
          unitsPerPixel,
          unit,
          calibratedAt: Date.now(),
          pointA: [calibPointA.x, calibPointA.y],
          pointB: [calibPointB.x, calibPointB.y],
        };
        const k = calibrationKey(projectId, d.filename, selectedLayout);
        saveCalibration(k, state);
        setCalibration(state);
        addToast({
          type: 'success',
          title: t('dwg_takeoff.cal_success', {
            defaultValue: 'Scale calibrated',
          }) as string,
        });
      } catch {
        addToast({
          type: 'error',
          title: t('dwg_takeoff.cal_error_generic', {
            defaultValue: 'Calibration failed - try clicking two distinct points.',
          }) as string,
        });
      }
      setCalibStep(0);
      setCalibPointA(null);
      setCalibPointB(null);
      setActiveTool('select');
    },
    [
      calibPointA,
      calibPointB,
      selectedDrawingId,
      drawings,
      projectId,
      selectedLayout,
      addToast,
      t,
    ],
  );

  /** Cancel handler — drops any captured points and closes the dialog. */
  const handleCalibrationCancel = useCallback(() => {
    setCalibStep(0);
    setCalibPointA(null);
    setCalibPointB(null);
    // Fall back to the select tool so a stray click doesn't immediately
    // re-open step 1 (which would surprise the user).
    setActiveTool('select');
  }, []);

  /**
   * Area-cache entities at load time so the ranked hit-test (RFC 11 §4.1) can
   * score candidates in O(1) per entity without recomputing the polygon
   * area on every click. The cached ``_area`` field is an internal,
   * non-API detail — consumed only by ``DxfViewer``'s ``collectHitCandidates``.
   */
  const annotatedEntities = useMemo<DxfEntity[]>(() => {
    if (entities.length === 0) return entities;
    return entities.map((e) => {
      if (e.type === 'LWPOLYLINE' && e.closed && e.vertices && e.vertices.length >= 3) {
        return { ...e, _area: calculateArea(e.vertices) } as DxfEntity & { _area: number };
      }
      return e;
    });
  }, [entities]);

  // Filter entities by selected layout
  const filteredEntities = useMemo(() => {
    if (!selectedLayout || layouts.length === 0) return annotatedEntities;
    return annotatedEntities.filter((e) => e.layout === selectedLayout);
  }, [annotatedEntities, selectedLayout, layouts]);

  // Layers present in THIS (possibly server-filtered) fetch + the virtual
  // USER_MARKUP layer so it gets a LayerPanel row once users start drawing.
  const fetchedLayers = useMemo(
    () => extractLayers(filteredEntities, annotations),
    [filteredEntities, annotations],
  );

  // Merge the layers from the latest fetch into the persistent full roster.
  // Because the entity fetch is filtered by `visibleLayers`, hidden layers
  // are absent from `fetchedLayers` — the union preserves their rows so the
  // user can re-enable them. Entity counts/colours are refreshed from the
  // most recent fetch that included the layer.
  useEffect(() => {
    if (fetchedLayers.length === 0) return;
    setAllLayers((prev) => {
      const byName = new Map(prev.map((l) => [l.name, l]));
      for (const l of fetchedLayers) byName.set(l.name, l);
      const merged = Array.from(byName.values()).sort((a, b) =>
        a.name.localeCompare(b.name),
      );
      // Skip the state write when nothing changed to avoid a render loop.
      if (
        merged.length === prev.length &&
        merged.every(
          (l, i) =>
            prev[i]?.name === l.name && prev[i]?.entity_count === l.entity_count,
        )
      ) {
        return prev;
      }
      return merged;
    });
  }, [fetchedLayers]);

  // Full, toggle-able layer roster shown in the LayerPanel and used by the
  // summary/canvas. Falls back to the current fetch before the roster has
  // been seeded on first paint.
  const layers = allLayers.length > 0 ? allLayers : fetchedLayers;

  /**
   * Annotations filtered by the virtual layer toggle. If the annotation
   * carries a `layer_name` and that layer is hidden, drop it from the
   * viewer. Falls back to USER_MARKUP for legacy records without the
   * field (migration default already covers future rows).
   */
  const visibleAnnotations = useMemo(() => {
    if (annotations.length === 0) return annotations;
    return annotations.filter((ann) => {
      const name = ann.layer_name || USER_MARKUP_LAYER;
      // If no layers are tracked yet (initial load) — show everything.
      if (visibleLayers.size === 0 && layers.length === 0) return true;
      return visibleLayers.has(name);
    });
  }, [annotations, visibleLayers, layers]);

  // Seed visible layers from the full roster the FIRST time it is known for
  // the current drawing. A per-drawing latch (not a `visibleLayers.size === 0`
  // check) so that a deliberate "Hide All" — which also empties the set — is
  // never silently undone by this effect on the next render.
  const seededLayersForDrawingRef = useRef<string | null>(null);
  useEffect(() => {
    if (!selectedDrawingId) return;
    if (seededLayersForDrawingRef.current === selectedDrawingId) return;
    if (layers.length === 0) return;
    seededLayersForDrawingRef.current = selectedDrawingId;
    setVisibleLayers(new Set(layers.map((l) => l.name)));
  }, [layers, selectedDrawingId]);

  // Initialize visible entity names when entities/layout change
  useEffect(() => {
    if (filteredEntities.length > 0) {
      const names = new Set<string>();
      for (const e of filteredEntities) {
        names.add(entityDisplayName(e));
      }
      setVisibleNames(names);
    }
  }, [filteredEntities]);

  // Mutations (upload itself is now dispatched via useDwgUploadStore so
  // it survives navigation — see the subscription above).
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDrawing(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
      if (selectedDrawingId === confirmDeleteId) setSelectedDrawingId(null);
      setConfirmDeleteId(null);
      addToast({ type: 'success', title: t('dwg_takeoff.deleted', 'Drawing deleted') });
    },
  });

  /** When true, the next successful create/delete is a replay from an
   *  undo/redo operation and should NOT push a new entry onto the
   *  stack. Uses a ref so the flag survives across re-renders without
   *  triggering re-renders itself. */
  const skipUndoRef = useRef(false);

  const createAnnotationMutation = useMutation({
    mutationFn: (data: CreateAnnotationPayload) => createAnnotation(data),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['dwg-annotations', selectedDrawingId] });
      // Feed the unified Markups hub so the new annotation shows up there
      // without a manual reload (Option B aggregator).
      queryClient.invalidateQueries({ queryKey: ['unified-markups'] });
      // Q1 UX #2: push a "create" entry so Ctrl+Z can delete the just-
      // persisted annotation. ``skipUndoRef`` suppresses this during
      // replay paths to avoid doubling up entries during redo.
      if (skipUndoRef.current) {
        skipUndoRef.current = false;
        return;
      }
      setUndoState((prev) =>
        pushUndo(prev, {
          kind: 'create',
          id: created.id,
          snapshot: snapshotFrom(created),
        }),
      );
    },
    onError: (err: Error) => {
      skipUndoRef.current = false;
      // Surface the failure — silent 500s previously left users thinking
      // nothing happened.
      addToast({
        type: 'error',
        title: t('dwg_takeoff.annotation_failed', {
          defaultValue: 'Annotation could not be saved',
        }),
        message: err.message || String(err),
      });
    },
  });

  // Persist drawing scale + mode to the backend so a page reload on another
  // device restores exactly what the estimator picked. Kept separate from
  // the localStorage sync above so an offline user still gets instant UI
  // feedback — the backend call fires when the network comes back.
  const updateScaleMutation = useMutation({
    mutationFn: (data: { drawingId: string; denom: number; mode: DwgScaleMode }) =>
      updateDrawingScale(data.drawingId, {
        scale_denominator: data.denom,
        scale_mode: data.mode,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dwg-drawings'] });
    },
  });

  // Debounce backend sync so the user can type "1:50" one character at a time
  // without firing four PATCH requests.
  useEffect(() => {
    if (!selectedDrawingId) return;
    const handle = window.setTimeout(() => {
      updateScaleMutation.mutate({
        drawingId: selectedDrawingId,
        denom: drawingScale,
        mode: scaleMode,
      });
    }, 600);
    return () => window.clearTimeout(handle);
    // intentionally excludes updateScaleMutation from deps — it's a stable ref
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDrawingId, drawingScale, scaleMode]);

  // When the drawings list refreshes, hydrate local scale state from the
  // server-persisted fields (falling back to localStorage / defaults).
  useEffect(() => {
    if (!selectedDrawingId) return;
    const d = drawings.find((x) => x.id === selectedDrawingId);
    if (!d) return;
    if (typeof d.scale_denominator === 'number' && d.scale_denominator > 0) {
      setDrawingScale(d.scale_denominator);
    }
    if (d.scale_mode === 'preset' || d.scale_mode === 'calibrated' || d.scale_mode === 'per_annotation') {
      setScaleMode(d.scale_mode);
    }
  }, [selectedDrawingId, drawings]);

  const handleStartCalibration = useCallback(() => {
    setIsCalibrating(true);
    setCalibrationPixels(null);
    // Switch to the distance tool so the canvas captures two-point clicks
    // using the existing well-tested code path; `handleAnnotationCreated`
    // intercepts the resulting measurement below.
    setActiveTool('distance');
    addToast({
      type: 'info',
      title: t('dwg_takeoff.scale_calibrate_started_title', { defaultValue: 'Calibration armed' }),
      message: t('dwg_takeoff.scale_calibrate_started_msg', {
        defaultValue: 'Click two points on the drawing whose real-world distance you know.',
      }),
    });
  }, [addToast, t]);

  const handleCancelCalibration = useCallback(() => {
    setIsCalibrating(false);
    setActiveTool('select');
  }, []);

  const deleteAnnotationMutation = useMutation<
    void,
    Error,
    { id: string; snapshotForUndo?: ReturnType<typeof snapshotFrom> | null }
  >({
    mutationFn: ({ id }) => deleteAnnotation(id),
    onSuccess: (_res, vars) => {
      queryClient.invalidateQueries({ queryKey: ['dwg-annotations', selectedDrawingId] });
      queryClient.invalidateQueries({ queryKey: ['unified-markups'] });
      setSelectedAnnotationId(null);
      if (skipUndoRef.current) {
        skipUndoRef.current = false;
        return;
      }
      if (vars.snapshotForUndo) {
        setUndoState((prev) =>
          pushUndo(prev, { kind: 'delete', snapshot: vars.snapshotForUndo! }),
        );
      }
    },
    onError: () => {
      skipUndoRef.current = false;
    },
  });

  /* ── Q1 UX #2: Undo / redo handlers ────────────────────────────────
   *
   * Executes the inverse mutation for the entry. All backend calls are
   * wrapped in skipUndoRef guards so the reducer's bookkeeping stays
   * consistent (the entry was moved to the redo/undo stack synchronously
   * — the mutation's onSuccess should NOT push a fresh entry on top). */
  const replayUndo = useCallback(
    (entry: UndoEntry) => {
      if (!selectedDrawingId) return;
      const drawing = drawings.find((d) => d.id === selectedDrawingId);
      const effectiveProjectId = drawing?.project_id || projectId;

      switch (entry.kind) {
        case 'create': {
          // Inverse of create → delete.
          skipUndoRef.current = true;
          deleteAnnotationMutation.mutate({ id: entry.id });
          break;
        }
        case 'delete': {
          if (!effectiveProjectId) return;
          const s = entry.snapshot;
          skipUndoRef.current = true;
          createAnnotationMutation.mutate({
            project_id: effectiveProjectId,
            drawing_id: selectedDrawingId,
            annotation_type: s.annotation_type,
            geometry: { points: s.points },
            text: s.text ?? undefined,
            color: s.color,
            thickness: s.thickness ?? 2,
            line_width: s.line_width ?? 2,
            layer_name: s.layer_name ?? undefined,
            measurement_value: s.measurement_value ?? undefined,
            measurement_unit: s.measurement_unit ?? undefined,
            scale_override: s.scale_override ?? null,
            metadata: s.metadata,
          });
          break;
        }
        case 'edit': {
          // Edits are not yet wired to the page-level stack; no-op.
          break;
        }
      }
    },
    [
      selectedDrawingId,
      drawings,
      projectId,
      createAnnotationMutation,
      deleteAnnotationMutation,
    ],
  );

  const replayRedo = useCallback(
    (entry: UndoEntry) => {
      if (!selectedDrawingId) return;
      const drawing = drawings.find((d) => d.id === selectedDrawingId);
      const effectiveProjectId = drawing?.project_id || projectId;

      switch (entry.kind) {
        case 'create': {
          // Redo of a create → re-create from the captured snapshot.
          if (!effectiveProjectId) return;
          const s = entry.snapshot;
          skipUndoRef.current = true;
          createAnnotationMutation.mutate({
            project_id: effectiveProjectId,
            drawing_id: selectedDrawingId,
            annotation_type: s.annotation_type,
            geometry: { points: s.points },
            text: s.text ?? undefined,
            color: s.color,
            thickness: s.thickness ?? 2,
            line_width: s.line_width ?? 2,
            layer_name: s.layer_name ?? undefined,
            measurement_value: s.measurement_value ?? undefined,
            measurement_unit: s.measurement_unit ?? undefined,
            scale_override: s.scale_override ?? null,
            metadata: s.metadata,
          });
          break;
        }
        case 'delete': {
          // Redo of a delete → delete again (id may no longer exist if
          // the undone create produced a new id; best-effort).
          skipUndoRef.current = true;
          deleteAnnotationMutation.mutate({ id: entry.snapshot.id });
          break;
        }
        case 'edit': {
          break;
        }
      }
    },
    [
      selectedDrawingId,
      drawings,
      projectId,
      createAnnotationMutation,
      deleteAnnotationMutation,
    ],
  );

  const handleUndo = useCallback(() => {
    setUndoState((prev) => {
      const { state: next, entry } = popUndo(prev);
      if (entry) replayUndo(entry);
      return next;
    });
  }, [replayUndo]);

  const handleRedo = useCallback(() => {
    setUndoState((prev) => {
      const { state: next, entry } = popRedo(prev);
      if (entry) replayRedo(entry);
      return next;
    });
  }, [replayRedo]);

  // Handlers
  const handleToggleLayer = useCallback((name: string) => {
    setVisibleLayers((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const handleShowAllLayers = useCallback(() => {
    setVisibleLayers(new Set(layers.map((l) => l.name)));
  }, [layers]);

  const handleHideAllLayers = useCallback(() => {
    setVisibleLayers(new Set());
  }, []);

  // Entity name filter handlers
  const handleToggleName = useCallback((name: string) => {
    setVisibleNames((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const handleShowAllNames = useCallback(() => {
    const names = new Set<string>();
    for (const e of filteredEntities) {
      names.add(entityDisplayName(e));
    }
    setVisibleNames(names);
  }, [filteredEntities]);

  const handleHideAllNames = useCallback(() => {
    setVisibleNames(new Set());
  }, []);

  // Entities filtered by both layer AND name visibility
  const viewerEntities = useMemo(() => {
    // If all names are visible (or no names extracted yet), skip the name check
    const allNames = new Set<string>();
    for (const e of filteredEntities) {
      allNames.add(entityDisplayName(e));
    }
    const nameFilterActive = visibleNames.size < allNames.size;

    if (!nameFilterActive) return filteredEntities;
    return filteredEntities.filter((e) => visibleNames.has(entityDisplayName(e)));
  }, [filteredEntities, visibleNames]);

  /* ── Find text on drawing ───────────────────────────────────────────
   * Parity with the PDF takeoff "find on sheet". Searches the TEXT/MTEXT
   * entities currently rendered (visible layers only, so highlights match
   * what's on screen), highlights every hit, and pans/zooms to the active
   * one. MTEXT is normalised to TEXT by the backend, so both are covered. */
  const [findOpen, setFindOpen] = useState(false);
  const [findQuery, setFindQuery] = useState('');
  const [activeMatchIdx, setActiveMatchIdx] = useState(0);
  const [findFocusNonce, setFindFocusNonce] = useState(0);
  const findInputRef = useRef<HTMLInputElement>(null);
  const findOpenRef = useRef(false);
  findOpenRef.current = findOpen;

  const textMatches = useMemo<DwgTextMatch[]>(() => {
    if (!findOpen || !findQuery.trim()) return [];
    const searchable = viewerEntities.filter((e) => visibleLayers.has(e.layer));
    return findTextMatches(searchable, findQuery);
  }, [findOpen, findQuery, viewerEntities, visibleLayers]);

  // Reset to the first hit (and zoom to it) whenever the query changes.
  useEffect(() => {
    if (!findOpen) return;
    setActiveMatchIdx(0);
    if (textMatches.length > 0) setFindFocusNonce((n) => n + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [findQuery, findOpen]);

  const gotoMatch = useCallback(
    (idx: number) => {
      const n = textMatches.length;
      if (n === 0) return;
      setActiveMatchIdx(((idx % n) + n) % n);
      setFindFocusNonce((x) => x + 1);
    },
    [textMatches.length],
  );
  const nextMatch = useCallback(() => gotoMatch(activeMatchIdx + 1), [gotoMatch, activeMatchIdx]);
  const prevMatch = useCallback(() => gotoMatch(activeMatchIdx - 1), [gotoMatch, activeMatchIdx]);

  const handleFindKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (e.shiftKey) prevMatch();
        else nextMatch();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        setFindOpen(false);
        setFindQuery('');
      }
    },
    [prevMatch, nextMatch],
  );

  // Index used for display + the active highlight, clamped to the live set so a
  // shrinking result list never points past the end for a render.
  const safeMatchIdx = textMatches.length === 0 ? 0 : Math.min(activeMatchIdx, textMatches.length - 1);
  const activeMatch = textMatches[safeMatchIdx] ?? null;
  const searchBoxes = useMemo(() => textMatches.map((m) => m.box), [textMatches]);
  const findFocusTarget = useMemo(
    () => (activeMatch ? { box: activeMatch.box, nonce: findFocusNonce } : null),
    [activeMatch, findFocusNonce],
  );

  // Focus the input when the bar opens.
  useEffect(() => {
    if (!findOpen) return;
    const id = window.setTimeout(() => findInputRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [findOpen]);

  const handleAnnotationCreated = useCallback(
    (ann: {
      type: DwgAnnotation['type'];
      points: { x: number; y: number }[];
      text?: string;
      color?: string;
      fontSize?: number;
      measurement_value?: number;
      measurement_unit?: string;
    }) => {
      if (!selectedDrawingId) return;

      // Calibration interception: if the user armed "Pick two points", the
      // first distance measurement they draw feeds the calibration widget
      // instead of becoming a persistent annotation.
      if (isCalibrating && ann.type === 'distance' && ann.points.length >= 2) {
        const a = ann.points[0]!;
        const b = ann.points[1]!;
        const pixels = Math.hypot(b.x - a.x, b.y - a.y);
        setCalibrationPixels(pixels);
        setIsCalibrating(false);
        setActiveTool('select');
        return;
      }

      // Pull project_id from the drawing itself — the global
      // ProjectContext store is only populated if the user opened a
      // project first, and deep-linking straight to /dwg-takeoff would
      // previously make the save silently no-op.
      const drawing = drawings.find((d) => d.id === selectedDrawingId);
      const effectiveProjectId = drawing?.project_id || projectId;
      if (!effectiveProjectId) {
        addToast({
          type: 'error',
          title: t('dwg_takeoff.annotation_failed', {
            defaultValue: 'Annotation could not be saved',
          }),
          message: t('dwg_takeoff.no_project_context', {
            defaultValue: 'No active project - open this drawing from its project first.',
          }),
        });
        return;
      }
      // Primitive tools (line/rectangle/circle/polyline/arrow/text_pin) get
      // stamped with the virtual USER_MARKUP layer so they can be grouped
      // and toggled as a single unit in the LayerPanel. The canvas
      // renderer looks at `thickness` for stroke width; we default to 2 px
      // so existing backend records (line_width=2) render identically.
      const isPrimitive =
        ann.type === 'line' ||
        ann.type === 'rectangle' ||
        ann.type === 'circle' ||
        ann.type === 'polyline' ||
        ann.type === 'arrow' ||
        ann.type === 'text_pin' ||
        ann.type === 'count';
      const layerName = isPrimitive ? USER_MARKUP_LAYER : 'ANNOTATIONS';
      // A freshly drawn markup must show up the instant it is placed. The
      // visible-layer set is seeded ONCE per drawing from the entity layers
      // present at load (see seededLayersForDrawingRef), so a virtual markup
      // layer (USER_MARKUP / ANNOTATIONS) that only comes into existence after
      // the user starts drawing is absent from that set — and
      // `visibleAnnotations` would filter the new mark straight back out,
      // leaving the user staring at a canvas where nothing appears. Add the
      // target layer to the visible set up front so the mark is never hidden
      // by its own brand-new layer.
      setVisibleLayers((prev) => (prev.has(layerName) ? prev : new Set(prev).add(layerName)));
      createAnnotationMutation.mutate({
        project_id: effectiveProjectId,
        drawing_id: selectedDrawingId,
        annotation_type: ann.type,
        geometry: { points: ann.points },
        text: ann.text,
        color: ann.color ?? activeColor,
        thickness: 2,
        line_width: 2,
        layer_name: layerName,
        measurement_value: ann.measurement_value,
        measurement_unit: ann.measurement_unit,
        // Per-annotation scale override — carries the detail-view scale on
        // every annotation drawn while the user is in per_annotation mode,
        // so mixed-scale sheets compute quantities correctly at read time.
        scale_override: scaleMode === 'per_annotation' ? drawingScale : null,
        metadata: ann.fontSize ? { font_size: ann.fontSize } : undefined,
      });
    },
    [
      selectedDrawingId,
      projectId,
      drawings,
      activeColor,
      createAnnotationMutation,
      addToast,
      t,
      isCalibrating,
      scaleMode,
      drawingScale,
    ],
  );

  /**
   * Click handler. Shift+Click toggles the entity in/out of the selection;
   * a plain click replaces the selection with a one-item set. Clicking
   * empty space with no modifier clears the selection.
   */
  const handleSelectEntity = useCallback((id: string | null, event?: EntitySelectEvent) => {
    if (id == null) {
      if (!event?.shiftKey) {
        setSelectedEntityIds(new Set());
        setEntityPopup(null);
      }
      return;
    }

    setContextMenu(null);

    if (event?.shiftKey) {
      setSelectedEntityIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      // Don't open the single-entity popup when building a multi-selection —
      // the group aggregation panel on the right is the right affordance.
      setEntityPopup(null);
    } else {
      setSelectedEntityIds(new Set([id]));
      setRightTab('properties');
      if (event) {
        setEntityPopup({ x: event.screenX, y: event.screenY });
      }
    }
  }, []);

  const handleEntityContextMenu = useCallback((event: EntityContextMenuEvent) => {
    // Right-click implicitly selects the target unless it is already part of
    // the current multi-selection.
    setSelectedEntityIds((prev) => {
      if (prev.has(event.entityId)) return prev;
      return new Set([event.entityId]);
    });
    setContextMenu({
      entityId: event.entityId,
      screenX: event.screenX,
      screenY: event.screenY,
    });
    setEntityPopup(null);
  }, []);

  const handleSelectDrawing = useCallback((id: string) => {
    setSelectedDrawingId(id);
    setVisibleLayers(new Set());
    setVisibleNames(new Set());
    setAllLayers([]);
    seededLayersForDrawingRef.current = null;
    setSelectedEntityIds(new Set());
    setHiddenEntityIds(new Set());
    setSelectedAnnotationId(null);
    setSelectedLayout(null);
    setEntityPopup(null);
    setContextMenu(null);
    // Drop in-progress draw / calibration so a half-started measurement on
    // the previous drawing doesn't bleed into the new one.
    setActiveTool('select');
    setCalibStep(0);
    setCalibPointA(null);
    setCalibPointB(null);
    setIsCalibrating(false);
    setCalibrationPixels(null);
  }, []);

  /* Layout switch on the same drawing also has to reset in-progress
   * calibration — the picked points are world-space coords from the
   * previous viewport and would yield a nonsense scale. */
  useEffect(() => {
    setCalibStep(0);
    setCalibPointA(null);
    setCalibPointB(null);
  }, [selectedLayout]);

  /** First entity in the selection set — drives single-entity UI affordances. */
  const primarySelectedEntityId = useMemo(
    () => (selectedEntityIds.size > 0 ? selectedEntityIds.values().next().value ?? null : null),
    [selectedEntityIds],
  );

  // Selected entity details (primary = first in the set)
  const selectedEntity = useMemo(
    () => entities.find((e) => e.id === primarySelectedEntityId) ?? null,
    [entities, primarySelectedEntityId],
  );

  /** Entities in the current multi-selection (used by the group aggregation panel). */
  const selectedEntities = useMemo(
    () => entities.filter((e) => selectedEntityIds.has(e.id)),
    [entities, selectedEntityIds],
  );

  /** Σ area / Σ perimeter / Σ length for the current selection. */
  const selectionAggregate = useMemo(
    () => aggregateEntities(selectedEntities, effectiveScale),
    [selectedEntities, effectiveScale],
  );

  /**
   * Drawing-wide aggregate for the Summary tab (R3 #12). Uses the same
   * helper as the selection panel so totals are consistent — if a polygon
   * contributes 12 m² to the selection aggregate, it contributes the same
   * 12 m² to the drawing totals.
   */
  const summaryAggregate = useMemo(
    () => aggregateEntities(filteredEntities, effectiveScale),
    [filteredEntities, effectiveScale],
  );

  /**
   * Breakdown by DXF layer: count + Σ area + Σ length per layer, sorted
   * by area descending so the visually dominant layer lands on top.
   * Entities with zero measurable geometry still contribute to ``count``.
   */
  const summaryByLayer = useMemo(() => {
    const buckets = new Map<string, { area: number; length: number; count: number }>();
    for (const e of filteredEntities) {
      const entry = buckets.get(e.layer) ?? { area: 0, length: 0, count: 0 };
      entry.count++;
      if (e.type === 'LWPOLYLINE' && e.vertices && e.vertices.length >= 2) {
        const closed = !!e.closed;
        if (closed && e.vertices.length >= 3) {
          entry.area += calculateArea(e.vertices);
        } else {
          entry.length += calculatePerimeter(e.vertices, false);
        }
      } else if (e.type === 'LINE' && e.start && e.end) {
        entry.length += calculateDistance(e.start, e.end);
      } else if (e.type === 'CIRCLE' && e.radius != null) {
        entry.area += Math.PI * e.radius * e.radius;
      }
      buckets.set(e.layer, entry);
    }
    // Convert raw DXF units to real metres (area × scale², length × scale)
    // so the per-layer totals match the canvas labels and Σ panels.
    const areaScale = effectiveScale * effectiveScale;
    return Array.from(buckets.entries())
      .map(([layer, v]) => ({
        layer,
        count: v.count,
        area: v.area * areaScale,
        length: v.length * effectiveScale,
      }))
      .sort((a, b) => (b.area || b.length || b.count) - (a.area || a.length || a.count));
  }, [filteredEntities, effectiveScale]);

  /** Breakdown by DXF entity type, already computed by ``aggregateEntities``. */
  const summaryByType = useMemo(() => {
    const rows = Object.entries(summaryAggregate.byType)
      .map(([type, count]) => ({ type, count }))
      .sort((a, b) => b.count - a.count);
    return rows;
  }, [summaryAggregate]);

  /** Running total of manual count markers (annotations of type 'count'). */
  const countTotal = useMemo(
    () => annotations.filter((a) => a.type === 'count').length,
    [annotations],
  );

  /**
   * Count-by-block rollup: group INSERT entities by ``block_name`` and tally
   * how many of each block appear in the drawing (e.g. DOOR x12, WINDOW x8).
   * Blocks with no name fall back to a generic label. Sorted by count desc.
   */
  const summaryByBlock = useMemo(() => {
    const buckets = new Map<string, number>();
    for (const e of filteredEntities) {
      if (e.type !== 'INSERT') continue;
      const name = e.block_name && e.block_name.trim() ? e.block_name : 'Block';
      buckets.set(name, (buckets.get(name) ?? 0) + 1);
    }
    return Array.from(buckets.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);
  }, [filteredEntities]);

  /**
   * Auto-quantify by layer: roll the exact vector geometry of every visible
   * layer up into area / length / count and pick a headline measure per
   * layer. This is DWG's signature edge over PDF takeoff - real quantities
   * with zero manual tracing - so it leads the Summary tab.
   */
  const layerQuantities = useMemo(
    () => quantifyByLayer(filteredEntities, effectiveScale),
    [filteredEntities, effectiveScale],
  );

  /** CSV export of the summary (entity-type breakdown + totals). */
  const handleExportSummaryCsv = useCallback(() => {
    const lines: string[] = [
      '# DWG Summary Measurements',
      `# Entities: ${filteredEntities.length}`,
      `# Total area (m2): ${summaryAggregate.area.toFixed(3)}`,
      `# Total perimeter (m): ${summaryAggregate.perimeter.toFixed(3)}`,
      `# Total length (m): ${summaryAggregate.length.toFixed(3)}`,
      '',
      'scope,key,count,area_m2,length_m',
    ];
    for (const row of summaryByLayer) {
      lines.push([
        'layer',
        JSON.stringify(row.layer),
        row.count,
        row.area.toFixed(3),
        row.length.toFixed(3),
      ].join(','));
    }
    for (const row of summaryByType) {
      lines.push([
        'type',
        JSON.stringify(row.type),
        row.count,
        '',
        '',
      ].join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `dwg-summary-${selectedDrawingId?.slice(0, 8) ?? 'drawing'}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    addToast({
      type: 'success',
      title: t('dwg_takeoff.csv_exported', { defaultValue: 'Measurements exported' }),
    });
  }, [
    filteredEntities.length,
    summaryAggregate,
    summaryByLayer,
    summaryByType,
    selectedDrawingId,
    addToast,
    t,
  ]);

  /** PDF export of the summary: totals + per-layer + per-type table.
   *  Lean first pass — text-only tabular report, no viewport canvas.
   *  Viewport rasterisation is tracked as a v2 polish item. */
  const handleExportSummaryPdf = useCallback(async () => {
    const { jsPDF } = await import('jspdf');
    const doc = new jsPDF({ unit: 'mm', format: 'a4' });
    const drawingName =
      drawings.find((d) => d.id === selectedDrawingId)?.name || 'Drawing';
    const margin = 15;
    let y = margin;

    doc.setFontSize(16);
    doc.setFont('helvetica', 'bold');
    doc.text('DWG Summary Measurements', margin, y);
    y += 8;

    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.text(`Drawing: ${drawingName}`, margin, y);
    y += 5;
    doc.text(`Entities: ${filteredEntities.length}`, margin, y);
    y += 5;
    doc.text(`Σ area: ${summaryAggregate.area.toFixed(2)} m²`, margin, y);
    y += 5;
    doc.text(`Σ perimeter: ${summaryAggregate.perimeter.toFixed(2)} m`, margin, y);
    y += 5;
    doc.text(`Σ length: ${summaryAggregate.length.toFixed(2)} m`, margin, y);
    y += 8;

    doc.setFont('helvetica', 'bold');
    doc.text('By layer', margin, y);
    y += 5;
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    for (const row of summaryByLayer.slice(0, 40)) {
      if (y > 270) {
        doc.addPage();
        y = margin;
      }
      doc.text(
        `${row.layer.slice(0, 40).padEnd(42)} × ${String(row.count).padStart(4)}  ` +
          `area ${row.area.toFixed(2)} m²  length ${row.length.toFixed(2)} m`,
        margin,
        y,
      );
      y += 4;
    }

    y += 4;
    doc.setFontSize(10);
    doc.setFont('helvetica', 'bold');
    doc.text('By type', margin, y);
    y += 5;
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    for (const row of summaryByType.slice(0, 40)) {
      if (y > 270) {
        doc.addPage();
        y = margin;
      }
      doc.text(`${row.type.padEnd(22)} × ${row.count}`, margin, y);
      y += 4;
    }

    const file = `dwg-summary-${selectedDrawingId?.slice(0, 8) ?? 'drawing'}.pdf`;
    doc.save(file);
    addToast({
      type: 'success',
      title: t('dwg_takeoff.pdf_exported', { defaultValue: 'PDF exported' }),
    });
  }, [
    filteredEntities.length,
    summaryAggregate,
    summaryByLayer,
    summaryByType,
    drawings,
    selectedDrawingId,
    addToast,
    t,
  ]);

  /**
   * Export the auto-quantify table (+ count-by-block + manual count) to a
   * multi-sheet .xlsx workbook. exceljs is lazy-loaded inside the helper so
   * it never weighs down the initial bundle.
   */
  const handleExportSummaryExcel = useCallback(async () => {
    const drawingName = drawings.find((d) => d.id === selectedDrawingId)?.name || 'Drawing';
    try {
      await exportQuantifyToExcel({
        drawingName,
        layerQuantities,
        byBlock: summaryByBlock,
        countTotal,
      });
      addToast({
        type: 'success',
        title: t('dwg_takeoff.excel_exported', { defaultValue: 'Excel exported' }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.excel_failed', { defaultValue: 'Excel export failed' }),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [drawings, selectedDrawingId, layerQuantities, summaryByBlock, countTotal, addToast, t]);

  /**
   * Download the current viewport as a single-page A4-landscape PDF.
   * Snapshots the live canvas (so annotations + grid + selection halos
   * are all captured) and delegates layout to ``exportCanvasToPdf`` in
   * ``lib/pdf-export.ts``. Grabs the canvas from the DOM via its
   * parent container — the DxfViewer does not expose an imperative
   * handle and we'd rather not restructure it just for this button.
   */
  const handleDownloadCanvasPdf = useCallback(() => {
    const drawing = drawings.find((d) => d.id === selectedDrawingId);
    if (!drawing) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.pdf_no_drawing', { defaultValue: 'No drawing selected' }),
      });
      return;
    }
    // DxfViewer renders exactly one <canvas> inside its own container;
    // on this page the canvas is the only <canvas> in the viewer region,
    // so `document.querySelector` is a safe way to reach it without
    // adding an imperative ref to the viewer component.
    const canvas = document.querySelector<HTMLCanvasElement>(
      '[data-dwg-viewer-root] canvas, .relative.h-full.w-full.overflow-hidden canvas',
    );
    if (!canvas) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.pdf_no_canvas', { defaultValue: 'Canvas not ready yet' }),
      });
      return;
    }
    try {
      exportCanvasToPdf({
        canvas,
        filename: drawing.filename || drawing.name,
        scale: drawingScale,
      });
      addToast({
        type: 'success',
        title: t('dwg_takeoff.pdf_downloaded', { defaultValue: 'PDF downloaded' }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.pdf_failed', { defaultValue: 'PDF export failed' }),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [drawings, selectedDrawingId, drawingScale, addToast, t]);

  const closeUploadModal = useCallback(() => {
    setShowUpload(false);
    setUploadFile(null);
    setUploadName('');
    setUploadDiscipline('architectural');
  }, []);

  /* ── BOQ-link picker handlers ──────────────────────────────────────
   * Mirror the PDF-takeoff pattern: self-contained picker loads projects,
   * BOQs, and positions on demand.  "Pick existing" pushes quantity onto
   * the chosen position.  "Create new" mints a DW.NNN ordinal. */

  /** Canonical unit normalization — maps display glyph → canonical backend unit. */
  const normalizeUnit = useCallback((unit: string) => {
    const map: Record<string, string> = { m: 'm', 'm\u00B2': 'm2', 'm\u00B3': 'm3', pcs: 'pcs' };
    return map[unit] ?? unit;
  }, []);

  const loadPickerBoqs = useCallback(async (pid: string) => {
    if (!pid) { setLinkPickerBoqs([]); return; }
    setLinkBoqsLoading(true);
    try {
      const boqs = await apiGet<{ id: string; name: string }[]>(`/v1/boq/boqs/?project_id=${pid}`);
      setLinkPickerBoqs(boqs);
    } catch {
      setLinkPickerBoqs([]);
    } finally {
      setLinkBoqsLoading(false);
    }
  }, []);

  const loadPickerPositions = useCallback(async (boqId: string) => {
    if (!boqId) { setLinkBoqPositions([]); return; }
    setLinkPositionsLoading(true);
    try {
      const boqData = await boqApi.get(boqId);
      setLinkBoqPositions(normalizePositions(boqData.positions || []));
    } catch {
      setLinkBoqPositions([]);
    } finally {
      setLinkPositionsLoading(false);
    }
  }, []);

  const activeBoqIdFromStore = useProjectContextStore((s) => s.activeBOQId);

  /** Open the picker for the currently-selected DWG entity. */
  const handleOpenLinkToBoq = useCallback(async (entityId: string) => {
    setLinkingEntityId(entityId);
    setLinkPickerSearch('');
    setLinkPickerMode('pick');

    const seedProject = projectId || '';
    const seedBoq = activeBoqIdFromStore ?? '';
    setLinkPickerProjectId(seedProject);
    setLinkPickerBoqId(seedBoq);

    try {
      const projects = await projectsApi.list();
      setLinkPickerProjects(projects.map((p) => ({ id: p.id, name: p.name })));
    } catch {
      setLinkPickerProjects([]);
    }

    if (seedProject) {
      await loadPickerBoqs(seedProject);
    } else {
      setLinkPickerBoqs([]);
    }
    if (seedBoq) {
      await loadPickerPositions(seedBoq);
    } else {
      setLinkBoqPositions([]);
    }
  }, [projectId, activeBoqIdFromStore, loadPickerBoqs, loadPickerPositions]);

  const handlePickerProjectChange = useCallback(async (pid: string) => {
    setLinkPickerProjectId(pid);
    setLinkPickerBoqId('');
    setLinkBoqPositions([]);
    await loadPickerBoqs(pid);
  }, [loadPickerBoqs]);

  const handlePickerBoqChange = useCallback(async (bid: string) => {
    setLinkPickerBoqId(bid);
    await loadPickerPositions(bid);
  }, [loadPickerPositions]);

  /**
   * Ensure we have a `text_pin` annotation backing the link, creating one
   * at the entity centroid if none exists yet.  Returns the annotation id
   * (server-assigned), or null if creation fails.
   */
  const ensureAnnotationForEntity = useCallback(async (
    entity: DxfEntity,
    measurement: { value: number; unit: string } | null,
  ): Promise<string | null> => {
    if (!selectedDrawingId) return null;
    const drawing = drawings.find((d) => d.id === selectedDrawingId);
    const effectiveProjectId = drawing?.project_id || projectId;
    if (!effectiveProjectId) return null;

    // Reuse an existing text_pin annotation anchored to this entity, if any.
    const existing = annotations.find(
      (a) => a.type === 'text_pin'
        && (a.metadata as Record<string, unknown> | undefined)?.['dwg_entity_id'] === entity.id,
    );
    if (existing) return existing.id;

    const centroid = computeEntityCentroid(entity);
    try {
      const created = await createAnnotation({
        project_id: effectiveProjectId,
        drawing_id: selectedDrawingId,
        annotation_type: 'text_pin',
        geometry: { points: [centroid] },
        text: entity.layer,
        color: activeColor,
        measurement_value: measurement?.value,
        measurement_unit: measurement?.unit,
        metadata: { dwg_entity_id: entity.id, dwg_entity_type: entity.type },
      });
      queryClient.invalidateQueries({ queryKey: ['dwg-annotations', selectedDrawingId] });
      return created.id;
    } catch {
      return null;
    }
  }, [selectedDrawingId, projectId, drawings, annotations, activeColor, queryClient]);

  const handleLinkToPosition = useCallback(async (entityId: string, position: Position) => {
    const entity = entities.find((e) => e.id === entityId);
    if (!entity || !selectedDrawingId) return;
    setLinkingInProgress(true);
    try {
      const measurement = extractEntityMeasurement(entity, effectiveScale);
      const annotationId = await ensureAnnotationForEntity(entity, measurement);

      if (annotationId) {
        try { await linkAnnotationToBoq(annotationId, position.id); } catch { /* non-critical */ }
      }

      const existingMeta = (position.metadata ?? {}) as Record<string, unknown>;
      const patch: Record<string, unknown> = {
        metadata: {
          ...existingMeta,
          dwg_drawing_id: selectedDrawingId,
          dwg_entity_id: entity.id,
          dwg_entity_type: entity.type,
          linked_annotation_id: annotationId ?? undefined,
        },
      };

      // Unit-safety: linking a measured entity to an EXISTING position must
      // not silently change its unit of measure. An area measurement (m\u00b2)
      // pushed onto a position priced per metre or per piece would corrupt
      // the estimate. We only adopt the measurement's unit when the
      // existing position has none or the two already agree; otherwise we
      // keep the position's unit and push the quantity only, and tell the
      // user about the kept unit so the mismatch is never invisible.
      const existingUnit = (position.unit ?? '').trim();
      const measuredUnit = measurement ? measurement.unit.trim() : '';
      const unitsMatch =
        !existingUnit || existingUnit.toLowerCase() === measuredUnit.toLowerCase();
      let unitKept = false;
      if (measurement) {
        patch['quantity'] = measurement.value;
        if (unitsMatch) {
          patch['unit'] = measurement.unit;
        } else {
          // Keep position.unit; only the quantity is updated.
          unitKept = true;
        }
      }
      await boqApi.updatePosition(position.id, patch);

      queryClient.invalidateQueries({ queryKey: ['dwg-annotations', selectedDrawingId] });
      queryClient.invalidateQueries({ queryKey: ['boq', position.boq_id] });

      let message: string;
      if (!measurement) {
        message = position.ordinal;
      } else if (unitKept) {
        // Surface the old\u2192new unit difference so the user knows we kept
        // their unit and pushed only the quantity. Plain-template head
        // (value \u2192 ordinal) plus a translated "kept unit" explanation with
        // two interpolated units.
        const note = t('dwg_takeoff.linked_unit_kept_note', {
          defaultValue: 'kept unit {{kept}} (measured {{measured}})',
          kept: existingUnit,
          measured: measuredUnit,
        });
        message = `${measurement.value} \u2192 ${position.ordinal} \u00b7 ${note}`;
      } else {
        message = `${measurement.value} ${measurement.unit} \u2192 ${position.ordinal}`;
      }

      addToast({
        type: unitKept ? 'warning' : 'success',
        title: unitKept
          ? t('dwg_takeoff.linked_unit_mismatch', {
              defaultValue: 'Linked \u00b7 unit kept',
            })
          : t('dwg_takeoff.linked_to_boq', { defaultValue: 'Linked to BOQ' }),
        message,
      });
      setLinkingEntityId(null);
      setEntityPopup(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.link_failed', { defaultValue: 'Link failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setLinkingInProgress(false);
    }
  }, [entities, selectedDrawingId, effectiveScale, ensureAnnotationForEntity, queryClient, addToast, t]);

  const handleCreateAndLink = useCallback(async (entityId: string) => {
    const entity = entities.find((e) => e.id === entityId);
    if (!entity) return;
    if (!linkPickerBoqId) {
      addToast({
        type: 'warning',
        title: t('dwg_takeoff.link_need_boq', { defaultValue: 'Pick a BOQ first' }),
      });
      return;
    }
    setLinkingInProgress(true);
    try {
      // Derive next DW.NNN ordinal from existing positions.
      const dwgOrdinals = linkBoqPositions
        .map((p) => {
          const match = /^DW\.(\d+)$/.exec(p.ordinal || '');
          return match ? parseInt(match[1]!, 10) : 0;
        })
        .filter((n) => n > 0);
      const nextNum = (dwgOrdinals.length ? Math.max(...dwgOrdinals) : 0) + 1;
      const ordinal = `DW.${String(nextNum).padStart(3, '0')}`;

      const measurement = extractEntityMeasurement(entity, effectiveScale);
      const qty = measurement?.value ?? 0;
      const unit = measurement?.unit ?? 'pcs';
      const description = t('dwg_takeoff.position_default_desc', {
        defaultValue: 'From DWG: {{layer}}',
        layer: entity.layer,
      });

      const newPos = await boqApi.addPosition({
        boq_id: linkPickerBoqId,
        ordinal,
        description,
        unit,
        quantity: qty,
        unit_rate: 0,
      });

      const annotationId = await ensureAnnotationForEntity(entity, measurement);
      if (annotationId) {
        try { await linkAnnotationToBoq(annotationId, newPos.id); } catch { /* non-critical */ }
      }

      try {
        await boqApi.updatePosition(newPos.id, {
          metadata: {
            dwg_drawing_id: selectedDrawingId ?? undefined,
            dwg_entity_id: entity.id,
            dwg_entity_type: entity.type,
            linked_annotation_id: annotationId ?? undefined,
          },
        });
      } catch { /* metadata is non-critical */ }

      setLinkBoqPositions((prev) => [...prev, newPos]);
      queryClient.invalidateQueries({ queryKey: ['dwg-annotations', selectedDrawingId] });
      queryClient.invalidateQueries({ queryKey: ['boq', linkPickerBoqId] });

      addToast({
        type: 'success',
        title: t('dwg_takeoff.linked_created', { defaultValue: 'Position created & linked' }),
        message: `${ordinal} \u2014 ${qty} ${unit}`,
      });
      setLinkingEntityId(null);
      setEntityPopup(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.create_link_failed', { defaultValue: 'Create & link failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setLinkingInProgress(false);
    }
  }, [entities, linkPickerBoqId, linkBoqPositions, effectiveScale, ensureAnnotationForEntity, selectedDrawingId, queryClient, addToast, t]);

  /**
   * One-click "group -> BOQ": roll the whole multi-entity selection up into a
   * single aggregate quantity (area > length > count) and book it as one new
   * BOQ position. Resolves the target BOQ automatically - the project's
   * active BOQ, else its first BOQ, else a freshly-created "DWG Takeoff" BOQ -
   * so the estimator never has to leave the drawing. The destination + ordinal
   * are surfaced in the toast (never a silent write), and the per-entity picker
   * stays available for precise single-element linking.
   */
  const handleCreateBoqFromGroup = useCallback(async () => {
    const ids = Array.from(selectedEntityIds);
    if (ids.length === 0) return;
    const sel = entities.filter((e) => ids.includes(e.id));
    const agg = aggregateEntities(sel, effectiveScale);
    let quantity = ids.length;
    let unit = 'pcs';
    if (agg.area > 0) {
      quantity = agg.area;
      unit = 'm2';
    } else if (agg.length > 0) {
      quantity = agg.length;
      unit = 'm';
    }

    const drawing = drawings.find((d) => d.id === selectedDrawingId);
    const effectiveProjectId = drawing?.project_id || projectId;
    if (!effectiveProjectId) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.annotation_failed', { defaultValue: 'Annotation could not be saved' }),
        message: t('dwg_takeoff.no_project_context', {
          defaultValue: 'No active project - open this drawing from its project first.',
        }),
      });
      return;
    }

    setLinkingInProgress(true);
    try {
      // Resolve a destination BOQ without forcing the user through a picker.
      let boqId = activeBoqIdFromStore || '';
      if (!boqId) {
        const boqs = await apiGet<{ id: string; name: string }[]>(
          `/v1/boq/boqs/?project_id=${effectiveProjectId}`,
        );
        if (boqs.length > 0) {
          boqId = boqs[0]!.id;
        } else {
          const created = await boqApi.create({
            project_id: effectiveProjectId,
            name: t('dwg_takeoff.default_boq_name', { defaultValue: 'DWG Takeoff' }),
          });
          boqId = created.id;
        }
      }

      const boqData = await boqApi.get(boqId);
      const positions = boqData.positions || [];
      const dwgNums = positions
        .map((p) => {
          const m = /^DW\.(\d+)$/.exec(p.ordinal || '');
          return m ? parseInt(m[1]!, 10) : 0;
        })
        .filter((n) => n > 0);
      const nextNum = (dwgNums.length ? Math.max(...dwgNums) : 0) + 1;
      const ordinal = `DW.${String(nextNum).padStart(3, '0')}`;
      const layersInSel = Array.from(new Set(sel.map((e) => e.layer)));
      const description =
        layersInSel.length === 1
          ? t('dwg_takeoff.position_group_desc_layer', {
              defaultValue: 'From DWG group: {{layer}} ({{count}} items)',
              layer: layersInSel[0],
              count: ids.length,
            })
          : t('dwg_takeoff.position_group_desc', {
              defaultValue: 'From DWG group ({{count}} items)',
              count: ids.length,
            });
      const roundedQty = Math.round(quantity * 1000) / 1000;

      const newPos = await boqApi.addPosition({
        boq_id: boqId,
        ordinal,
        description,
        unit,
        quantity: roundedQty,
        unit_rate: 0,
      });
      try {
        await boqApi.updatePosition(newPos.id, {
          metadata: {
            dwg_drawing_id: selectedDrawingId ?? undefined,
            dwg_entity_ids: ids,
            dwg_source_layers: layersInSel,
          },
        });
      } catch {
        /* metadata is non-critical */
      }

      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      addToast({
        type: 'success',
        title: t('dwg_takeoff.group_boq_created', { defaultValue: 'BOQ position created' }),
        message: `${boqData.name || 'BOQ'} · ${ordinal} - ${roundedQty} ${unit}`,
      });
      setSelectedEntityIds(new Set());
      setEntityPopup(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.group_boq_failed', { defaultValue: 'Could not create BOQ position' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLinkingInProgress(false);
    }
  }, [
    selectedEntityIds,
    entities,
    effectiveScale,
    drawings,
    selectedDrawingId,
    projectId,
    activeBoqIdFromStore,
    queryClient,
    addToast,
    t,
  ]);

  /* ── RFC 11: per-entity hide / isolate / group handlers ───────────── */

  /** Hide the currently-selected entities (or a single right-clicked one). */
  const handleHideEntities = useCallback((ids: string[]) => {
    if (ids.length === 0) return;
    setHiddenEntityIds((prev) => {
      const next = new Set(prev);
      for (const id of ids) next.add(id);
      return next;
    });
    setSelectedEntityIds(new Set());
    setContextMenu(null);
    setEntityPopup(null);
  }, []);

  /** Isolate: hide everything EXCEPT the given ids. */
  const handleIsolateEntities = useCallback((ids: string[]) => {
    if (ids.length === 0) return;
    const keep = new Set(ids);
    const hide = new Set<string>();
    for (const e of entities) {
      if (!keep.has(e.id)) hide.add(e.id);
    }
    setHiddenEntityIds(hide);
    setContextMenu(null);
  }, [entities]);

  /** Unhide all hidden entities. */
  const handleShowAllEntities = useCallback(() => {
    setHiddenEntityIds(new Set());
  }, []);

  /**
   * Save the current selection as a named DwgEntityGroup on the backend.
   * Uses a simple prompt for the group name — good enough for v1.9.1;
   * a proper dialog can land in v1.9.2 if we need validation hints or
   * description fields.
   */
  const handleSaveSelectionAsGroup = useCallback(async () => {
    if (!selectedDrawingId || selectedEntityIds.size === 0) return;
    const defaultName = t('dwg_takeoff.group_default_name', {
      defaultValue: 'Group of {{count}}',
      count: selectedEntityIds.size,
    });
    // eslint-disable-next-line no-alert
    const name = window.prompt(
      t('dwg_takeoff.group_prompt', { defaultValue: 'Name this group:' }),
      defaultName,
    );
    if (!name || !name.trim()) return;
    try {
      await createEntityGroup({
        drawing_id: selectedDrawingId,
        entity_ids: Array.from(selectedEntityIds),
        name: name.trim(),
      });
      addToast({
        type: 'success',
        title: t('dwg_takeoff.group_saved', { defaultValue: 'Group saved' }),
        message: `${name.trim()} (${selectedEntityIds.size})`,
      });
      setContextMenu(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.group_save_failed', { defaultValue: 'Could not save group' }),
        message: err instanceof Error ? err.message : '',
      });
    }
  }, [selectedDrawingId, selectedEntityIds, addToast, t]);

  /**
   * Link the current multi-selection to a BOQ position. Creates a persisted
   * DwgEntityGroup first (so the link survives reloads and has an audit
   * trail), then reuses the existing position-patch path used by single
   * entities — writes ``dwg_group_id`` into position metadata alongside
   * the existing ``dwg_entity_id`` field so consumers can find either shape.
   *
   * Auto-fills quantity from the aggregated Σ area or Σ length depending
   * on the first selected entity's shape (closed polys → area; otherwise
   * length).
   */
  const handleLinkGroupToPosition = useCallback(async (position: Position) => {
    if (!selectedDrawingId || selectedEntityIds.size === 0) return;
    setLinkingInProgress(true);
    try {
      const ids = Array.from(selectedEntityIds);
      const groupName = t('dwg_takeoff.group_default_name', {
        defaultValue: 'Group of {{count}}',
        count: ids.length,
      });
      const group = await createEntityGroup({
        drawing_id: selectedDrawingId,
        entity_ids: ids,
        name: groupName,
      });

      const agg = aggregateEntities(selectedEntities, effectiveScale);
      const prefersArea = agg.area > 0 && agg.length === 0;
      const quantity = prefersArea ? agg.area : agg.length > 0 ? agg.length : agg.perimeter;
      const unit = prefersArea ? 'm2' : 'm';

      const existingMeta = (position.metadata ?? {}) as Record<string, unknown>;
      const patch: Record<string, unknown> = {
        metadata: {
          ...existingMeta,
          dwg_drawing_id: selectedDrawingId,
          dwg_group_id: group.id,
          dwg_entity_ids: ids,
        },
      };
      if (quantity > 0) {
        patch['quantity'] = Math.round(quantity * 100) / 100;
        patch['unit'] = unit;
      }
      await boqApi.updatePosition(position.id, patch);

      queryClient.invalidateQueries({ queryKey: ['boq', position.boq_id] });
      addToast({
        type: 'success',
        title: t('dwg_takeoff.linked_to_boq', { defaultValue: 'Linked to BOQ' }),
        message: `${ids.length} \u2192 ${position.ordinal}`,
      });
      setLinkingEntityId(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.link_failed', { defaultValue: 'Link failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setLinkingInProgress(false);
    }
  }, [
    selectedDrawingId,
    selectedEntityIds,
    selectedEntities,
    effectiveScale,
    queryClient,
    addToast,
    t,
  ]);

  // Global keyboard shortcuts for the page (Q1 UX #1 + #2).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Find-on-drawing: Ctrl/Cmd+F opens the find bar and selects its text,
      // from anywhere in the viewer (handled before the input guard so it works
      // even while another field is focused).
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'f') {
        e.preventDefault();
        setFindOpen(true);
        window.setTimeout(() => {
          findInputRef.current?.focus();
          findInputRef.current?.select();
        }, 0);
        return;
      }
      // Ignore shortcuts when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      // Skip if a modifier other than Shift / Ctrl is active — we only
      // own single-key tools and Ctrl+{Z,Y}/Ctrl+Shift+Z.
      if (e.altKey || e.metaKey) return;

      // Undo / redo first — these need to swallow the key even when
      // Ctrl is held, to avoid the browser shortcut kicking in.
      const key = e.key.toLowerCase();
      if (e.ctrlKey) {
        if (key === 'z' && !e.shiftKey) {
          e.preventDefault();
          handleUndo();
          return;
        }
        if (key === 'y' || (key === 'z' && e.shiftKey)) {
          e.preventDefault();
          handleRedo();
          return;
        }
        // Any other Ctrl+letter combo → bail (don't steal browser shortcuts).
        return;
      }

      switch (e.key) {
        case 'Escape':
          if (findOpenRef.current) {
            setFindOpen(false);
            setFindQuery('');
          } else if (contextMenu) {
            setContextMenu(null);
          } else if (selectedEntityIds.size > 0) {
            setSelectedEntityIds(new Set());
            setEntityPopup(null);
          } else if (selectedAnnotationId) {
            setSelectedAnnotationId(null);
          }
          break;
        case 'v': case 'V':
          setActiveTool('select');
          break;
        case 'h': case 'H':
          setActiveTool('pan');
          break;
        case 'd': case 'D':
          setActiveTool('distance');
          break;
        case 'l': case 'L':
          setActiveTool('line');
          break;
        case 'p': case 'P':
          setActiveTool('polyline');
          break;
        case 'a': case 'A':
          setActiveTool('area');
          break;
        case 'r': case 'R':
          setActiveTool('rectangle');
          break;
        case 'c': case 'C':
          setActiveTool('circle');
          break;
        case 'n': case 'N':
          setActiveTool('count');
          break;
        case 't': case 'T':
          setActiveTool('text_pin');
          break;
        case 'k': case 'K':
          setActiveTool('calibrate');
          break;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selectedEntityIds, selectedAnnotationId, contextMenu, handleUndo, handleRedo]);

  /* ── Render ──────────────────────────────────────────────────────── */
  // WAVE-FOLLOWUP: BetaBanner cannot mount here because the page renders a
  // full-screen drafting canvas (negative margins + 100vh-56px). A drafting
  // surface absorbs the whole viewport; adding a banner row would crop the
  // canvas. Surface beta status via the page header chip instead.

  return (
    <div className="flex flex-col -mx-4 sm:-mx-7 -mt-6 -mb-4 overflow-hidden" style={{ height: 'calc(100vh - 56px)' }}>
      {/* Top filter bar removed — ToolPalette now floats inside the viewer
          in the top-left corner so the drawing gets maximum vertical space
          and the tools live where the cursor already is while drawing. */}

      <div className="flex flex-1 overflow-hidden">
        {/* ── Center: DXF Viewer ──────────────────────────────────── */}
        <div className="flex flex-1 flex-col min-h-0 min-w-0">
          {importingDocId && !selectedDrawingId ? (
            // On-demand import from a Documents / File Manager deep-link is
            // running. Show an honest progress card instead of the upload
            // hero so the page is never blank while the drawing is created
            // server-side (the BIM page's graceful-open analogue).
            <div
              className="oe-dwg-canvas relative flex flex-1 items-center justify-center overflow-hidden"
              style={{ background: '#3f3f3f' }}
            >
              <GridBackground className="z-0" />
              <div className="relative z-10 flex flex-col items-center gap-4 rounded-2xl bg-[#22252b]/90 backdrop-blur-sm border border-[#333842] shadow-2xl shadow-black/30 px-10 py-9 text-center">
                <Loader2 size={36} className="text-blue-400 animate-spin" />
                <div>
                  <p className="text-base font-semibold text-gray-200">
                    {t('dwg_takeoff.opening_document', { defaultValue: 'Opening document…' })}
                  </p>
                  <p className="text-sm text-gray-500 mt-1.5 max-w-xs">
                    {t('dwg_takeoff.opening_document_hint', {
                      defaultValue: 'Preparing this drawing for takeoff. This can take a few minutes for large DWG files.',
                    })}
                  </p>
                  {deepLinkDocName && (
                    <p className="text-xs font-mono text-gray-600 mt-3 truncate max-w-xs">
                      {decodeURIComponent(deepLinkDocName)}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : !selectedDrawingId ? (
            <div
              className="oe-dwg-canvas relative flex flex-1 overflow-hidden overflow-y-auto"
              style={{ background: '#3f3f3f' }}
            >
              {/* AutoCAD-style drafting grid + vignette */}
              <GridBackground className="z-0" />
              {/* Subtle blue center glow retains the "laser-focused drawing" feel */}
              <div
                className="absolute inset-0 pointer-events-none z-0"
                style={{
                  background:
                    'radial-gradient(ellipse 60% 50% at 50% 40%, rgba(59,130,246,0.06) 0%, transparent 70%)',
                }}
              />
              {/* Crosshair at center (AutoCAD UCS marker) */}
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none opacity-20 z-0">
                <div className="w-px h-8 bg-blue-400 absolute left-1/2 -translate-x-1/2 -top-4" />
                <div className="h-px w-8 bg-blue-400 absolute top-1/2 -translate-y-1/2 -left-4" />
              </div>

              <div className="relative z-10 max-w-7xl mx-auto pt-20 pb-4 w-full">
                <DismissibleInfo
                  storageKey="dwg-takeoff"
                  className="mb-6 !bg-neutral-900/90 [&_.text-content-primary]:!text-gray-100 [&_.text-content-secondary]:!text-gray-300 [&_.text-content-tertiary]:!text-gray-400"
                  title={t('dwg_takeoff.intro_title', { defaultValue: 'Measure straight off the 2D drawing' })}
                  links={[
                    { label: t('dwg_takeoff.intro_link_boq', { defaultValue: 'Open BOQ' }), onClick: () => navigate('/boq') },
                    { label: t('dwg_takeoff.intro_link_bim', { defaultValue: 'BIM viewer' }), onClick: () => navigate('/bim') },
                  ]}
                >
                  {t('dwg_takeoff.intro_body', {
                    defaultValue:
                      'Upload DWG or DXF drawings to view their entities, toggle layers, and measure areas, lengths and counts directly on the plan. Link measurements to BOQ positions so the quantities flow into your cost estimate alongside BIM and the canonical model.',
                  })}
                </DismissibleInfo>
                <div className="grid grid-cols-1 md:grid-cols-[1.4fr_1fr] gap-8 items-stretch">
                  {/* LEFT · Upload card (gets the larger half) */}
                  <div className="flex flex-col">
                    <div className="rounded-2xl bg-[#22252b]/90 backdrop-blur-sm border border-[#333842] shadow-2xl shadow-black/30 p-3 flex flex-col h-full">
                      <button
                        type="button"
                        aria-label={t('dwg_takeoff.upload_aria', { defaultValue: 'Upload DWG or DXF file' })}
                        data-testid="dwg-hero-drop-zone"
                        onDrop={(e) => {
                          e.preventDefault();
                          setIsDragActive(false);
                          const f = e.dataTransfer.files?.[0];
                          if (f) { setUploadFile(f); setUploadName(f.name.replace(/\.[^.]+$/, '')); setShowUpload(true); }
                        }}
                        onDragOver={(e) => { e.preventDefault(); setIsDragActive(true); }}
                        onDragEnter={(e) => { e.preventDefault(); setIsDragActive(true); }}
                        onDragLeave={() => setIsDragActive(false)}
                        className={clsx(
                          'group/drop flex flex-col items-center justify-center gap-7 rounded-xl p-20 text-center cursor-pointer transition-all flex-1 border-2 border-dashed focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-[#22252b]',
                          isDragActive
                            ? 'border-blue-400 bg-blue-500/15 shadow-[0_0_40px_rgba(59,130,246,0.2)] scale-[1.01]'
                            : 'border-[#444c5a] bg-[#1a1d23]/60 hover:border-blue-500/50 hover:bg-blue-500/5 hover:shadow-[0_0_30px_rgba(59,130,246,0.1)]',
                        )}
                        onClick={() => setShowUpload(true)}
                      >
                        <div className="w-20 h-20 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center group-hover/drop:scale-110 group-hover/drop:shadow-[0_0_20px_rgba(59,130,246,0.2)] transition-all">
                          <Upload size={36} className="text-blue-400" />
                        </div>
                        <div>
                          <p className="text-base font-semibold text-gray-200">{t('dwg_takeoff.drop_here', { defaultValue: 'Drop your drawing here' })}</p>
                          <p className="text-sm text-gray-500 mt-1.5">{t('dwg_takeoff.drop_hint', { defaultValue: 'or click to browse files' })}</p>
                        </div>
                        <div className="flex items-center gap-2.5">
                          <span className="text-xs font-mono px-2.5 py-1 rounded-md bg-orange-500/10 text-orange-400 border border-orange-500/20 font-semibold">.dwg</span>
                          <span className="text-xs font-mono px-2.5 py-1 rounded-md bg-orange-500/10 text-orange-400 border border-orange-500/20 font-semibold">.dxf</span>
                        </div>
                        <p className="text-[11px] text-gray-600 leading-relaxed mt-1 text-center">
                          {t('dwg_takeoff.format_support', {
                            defaultValue: 'AutoCAD 2000–2025 · DXF R12–R2025',
                          })}
                        </p>
                      </button>
                    </div>
                  </div>

                  {/* RIGHT · Hero text + feature cards + local-processing badge */}
                  <div className="flex flex-col justify-center gap-4">
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <h1 className="text-2xl font-bold text-gray-100 tracking-tight leading-tight">
                          {t('dwg_takeoff.hero_title', { defaultValue: 'DWG Takeoff' })}
                        </h1>
                        <OfflineReadyBadge
                          readiness={offlineReadiness}
                          isLoading={loadingOfflineReadiness}
                          data-testid="dwg-offline-badge"
                        />
                        <ModuleGuideButton content={dwgTakeoffGuide} />
                      </div>
                      <p className="text-base text-gray-400 mt-3 leading-relaxed">
                        {t('dwg_takeoff.hero_subtitle', { defaultValue: 'Open DWG/DXF drawings, measure areas and lengths, annotate directly on the drawing, and link measurements to your BOQ positions.' })}
                      </p>
                      <p className="text-xs text-gray-600 mt-3 leading-relaxed">
                        {t('dwg_takeoff.format_support_dwg', {
                          defaultValue: 'AutoCAD DWG 2000–2025 · DXF R12–R2025',
                        })}
                      </p>
                    </div>
                    <div className="grid grid-cols-2 gap-3 mt-2">
                      {[
                        { icon: Layers, title: t('dwg_takeoff.feat_layers', { defaultValue: 'Layer Control' }), desc: t('dwg_takeoff.feat_layers_desc', { defaultValue: 'Toggle layers on/off, filter by entity type' }) },
                        { icon: FileUp, title: t('dwg_takeoff.feat_measure', { defaultValue: 'Measurements' }), desc: t('dwg_takeoff.feat_measure_desc', { defaultValue: 'Area, length, perimeter · link to BOQ' }) },
                      ].map((f, i) => (
                        <div key={i} className="flex items-start gap-3 rounded-xl p-4 bg-[#22252b]/80 backdrop-blur-sm border border-[#333842] hover:border-blue-500/30 hover:shadow-[0_0_15px_rgba(59,130,246,0.06)] transition-all">
                          <div className="w-8 h-8 rounded-lg bg-orange-500/10 border border-orange-500/20 flex items-center justify-center shrink-0"><f.icon size={15} className="text-orange-400" /></div>
                          <div className="min-w-0">
                            <h3 className="text-xs font-semibold text-gray-200 leading-tight">{f.title}</h3>
                            <p className="text-[11px] text-gray-500 leading-snug mt-1">{f.desc}</p>
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* Local processing badge — sits under the feature cards.
                        The strong "files never leave your computer" claim is
                        shown ONLY when the backend reports local_only (browser
                        + server on the same machine). On the hosted demo we
                        show honest "processed on your own server" copy. */}
                    <div className="mt-3 flex items-center justify-start">
                      <div className="inline-flex flex-wrap items-center gap-2 px-4 py-2 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                        <ShieldCheck size={14} className="text-emerald-400 shrink-0" />
                        <span className="text-xs text-emerald-300/90 font-medium">
                          {offlineReadiness?.local_only
                            ? t('common.local_processing', { defaultValue: '100% Local Processing · Your files never leave your computer' })
                            : t('dwg_takeoff.processed_on_your_server', { defaultValue: 'Processed on your OpenConstructionERP server · never sent to third parties' })}
                        </span>
                        <span className="text-[10px] text-emerald-500/30">|</span>
                        <a
                          href="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-emerald-400/70 hover:text-emerald-300 hover:underline whitespace-nowrap"
                        >
                          {t('common.powered_by_cad2data', { defaultValue: 'Powered by DDC cad2data' })}
                        </a>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : isNeedsConversion ? (
            <NeedsConversionCard
              drawingName={selectedDrawingFromList?.name || selectedDrawingFromList?.filename || ''}
              filename={selectedDrawingFromList?.filename || ''}
              converterAvailable={!!offlineReadiness?.converter_available}
              onConverted={() => {
                // The converter just installed. Re-upload semantics match the
                // error card: the backend has no in-place reconvert endpoint,
                // so the user re-picks the file (or a fresh one) and the new
                // upload runs through the now-present converter.
                if (selectedDrawingId) deleteMutation.mutate(selectedDrawingId);
                setShowUpload(true);
              }}
              onUploadAnother={() => setShowUpload(true)}
              onDelete={() => setConfirmDeleteId(selectedDrawingId)}
            />
          ) : isConverting ? (
            <ConversionProgressCard
              drawingName={selectedDrawingFromList?.name || selectedDrawingFromList?.filename || ''}
              filename={selectedDrawingFromList?.filename || ''}
              status={drawingStatus}
              startedAt={
                selectedDrawingFromList?.created_at
                  ? new Date(selectedDrawingFromList.created_at).getTime()
                  : Date.now()
              }
              onCancel={() => setConfirmDeleteId(selectedDrawingId)}
            />
          ) : isErrorStatus ? (
            <ConversionErrorCard
              drawingName={selectedDrawingFromList?.name || selectedDrawingFromList?.filename || ''}
              message={drawingErrorMessage}
              onRetry={() => {
                // Backend has no reconvert endpoint; "retry" means
                // delete the failed row and reopen the upload modal
                // so the user can pick the file again (or pick a
                // different one).
                if (selectedDrawingId) deleteMutation.mutate(selectedDrawingId);
                setShowUpload(true);
              }}
              onDelete={() => setConfirmDeleteId(selectedDrawingId)}
            />
          ) : isEmptyStatus ? (
            <ConversionEmptyCard
              drawingName={selectedDrawingFromList?.name || selectedDrawingFromList?.filename || ''}
              message={drawingErrorMessage}
              onDelete={() => setConfirmDeleteId(selectedDrawingId)}
              onUploadAnother={() => setShowUpload(true)}
            />
          ) : loadingEntities ? (
            <div className="flex flex-1 items-center justify-center">
              <div className="flex flex-col items-center gap-4 max-w-sm w-full px-6">
                <Loader2 size={32} className="animate-spin text-muted-foreground" />
                <p className="text-xs text-content-tertiary">
                  {t('dwg_takeoff.loading_drawing', { defaultValue: 'Loading drawing…' })}
                </p>
                <UploadProgressInline />
              </div>
            </div>
          ) : (
            <>
            <div className="relative flex-1 min-h-0" data-dwg-viewer-root>
              <DxfViewer
                key={`${selectedDrawingId}:${selectedLayout ?? 'default'}`}
                entities={viewerEntities}
                annotations={visibleAnnotations}
                visibleLayers={visibleLayers}
                activeTool={activeTool}
                activeColor={activeColor}
                selectedEntityIds={selectedEntityIds}
                hiddenEntityIds={hiddenEntityIds}
                selectedAnnotationId={selectedAnnotationId}
                drawingScale={effectiveScale}
                snapModes={snapModes}
                onSelectEntity={handleSelectEntity}
                onSelectAnnotation={setSelectedAnnotationId}
                onEntityContextMenu={handleEntityContextMenu}
                onAnnotationCreated={handleAnnotationCreated}
                onCalibrationPoint={handleCalibrationPoint}
                calibration={
                  calibration
                    ? { unitsPerPixel: calibration.unitsPerPixel, unit: calibration.unit }
                    : null
                }
                calibrationOverlay={{
                  pointA:
                    calibStep === 2 || calibStep === 3
                      ? calibPointA
                      : calibStep === 0 && calibration?.pointA
                        ? { x: calibration.pointA[0], y: calibration.pointA[1] }
                        : null,
                  pointB:
                    calibStep === 3
                      ? calibPointB
                      : calibStep === 0 && calibration?.pointB
                        ? { x: calibration.pointB[0], y: calibration.pointB[1] }
                        : null,
                }}
                searchBoxes={searchBoxes}
                activeSearchBox={activeMatch ? activeMatch.box : null}
                focusTarget={findFocusTarget}
              />

              {/* Onion-skin overlay (Item 17) — a dim wash over the current
                  revision while the compare drawer's overlay toggle is on,
                  so the user gets a visual "what changed" hint without us
                  reaching into the canvas render loop. Pointer-events none so
                  it never steals clicks from the viewer. */}
              {compareOverlay.enabled && (
                <div
                  aria-hidden="true"
                  data-testid="dwg-onion-skin"
                  className="pointer-events-none absolute inset-0 z-[5] bg-oe-blue/20 mix-blend-multiply transition-opacity"
                  style={{ opacity: compareOverlay.opacity }}
                />
              )}

              {/* Two-click calibration dialog. Step 0 = hidden. Steps 1/2
                  render a non-blocking banner; step 3 is a centered modal. */}
              <CalibrationDialog
                step={calibStep}
                pointA={calibPointA ? [calibPointA.x, calibPointA.y] : null}
                pointB={calibPointB ? [calibPointB.x, calibPointB.y] : null}
                onConfirm={handleCalibrationConfirm}
                onCancel={handleCalibrationCancel}
              />

              {/* Floating ToolPalette — top-left corner, above the canvas.
                  Lives here (not in a fixed header bar) so the drawing gets
                  the full viewport height and tools stay visually attached
                  to the thing they act on. */}
              <div className="absolute top-3 left-3 z-10 flex items-start gap-2">
                <div className="rounded-lg border border-white/60 bg-white/85 dark:bg-white/90 backdrop-blur-md shadow-xl shadow-black/30 ring-1 ring-black/5">
                  <ToolPalette
                    activeTool={activeTool}
                    onToolChange={setActiveTool}
                    activeColor={activeColor}
                    onColorChange={setActiveColor}
                  />
                </div>

                {/* Q1 UX #2 + #4: Undo / redo + snap-mode menu. Sit next
                    to the tool palette so tool + history + snap controls
                    are all reachable without leaving the top-left. */}
                <div
                  className="flex items-center gap-1 rounded-lg border border-white/60 bg-white/85 dark:bg-white/90 backdrop-blur-md px-1.5 py-1 shadow-xl shadow-black/30 ring-1 ring-black/5"
                  data-testid="dwg-history-bar"
                >
                  <button
                    type="button"
                    onClick={handleUndo}
                    disabled={!canUndoFn(undoState)}
                    data-testid="dwg-undo"
                    title={t('dwg_takeoff.undo', { defaultValue: 'Undo (Ctrl+Z)' })}
                    aria-label={t('dwg_takeoff.undo_aria', { defaultValue: 'Undo' })}
                    className={clsx(
                      'flex h-7 w-7 items-center justify-center rounded-md transition-colors',
                      canUndoFn(undoState)
                        ? 'text-slate-800 hover:bg-slate-100'
                        : 'text-slate-300 cursor-not-allowed',
                    )}
                  >
                    <Undo2 size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={handleRedo}
                    disabled={!canRedoFn(undoState)}
                    data-testid="dwg-redo"
                    title={t('dwg_takeoff.redo', {
                      defaultValue: 'Redo (Ctrl+Y / Ctrl+Shift+Z)',
                    })}
                    aria-label={t('dwg_takeoff.redo_aria', { defaultValue: 'Redo' })}
                    className={clsx(
                      'flex h-7 w-7 items-center justify-center rounded-md transition-colors',
                      canRedoFn(undoState)
                        ? 'text-slate-800 hover:bg-slate-100'
                        : 'text-slate-300 cursor-not-allowed',
                    )}
                  >
                    <Redo2 size={14} />
                  </button>

                  <div className="mx-1 h-5 w-px bg-slate-300" />

                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setSnapMenuOpen((o) => !o)}
                      data-testid="dwg-snap-menu-toggle"
                      title={t('dwg_takeoff.snap_menu', {
                        defaultValue: 'Snap modes',
                      })}
                      aria-label={t('dwg_takeoff.snap_menu', {
                        defaultValue: 'Snap modes',
                      })}
                      className={clsx(
                        'flex h-7 items-center gap-1 rounded-md px-2 text-xs transition-colors',
                        snapModes.endpoint || snapModes.midpoint || snapModes.intersection
                          ? 'bg-emerald-500/20 text-emerald-700'
                          : 'text-slate-700 hover:bg-slate-100',
                      )}
                    >
                      <Target size={13} />
                      <span className="font-semibold">
                        {t('dwg_takeoff.snap_label', { defaultValue: 'Snap' })}
                      </span>
                    </button>
                    {snapMenuOpen && (
                      <div
                        data-testid="dwg-snap-menu"
                        className="absolute left-0 top-full mt-1 w-48 rounded-lg border border-slate-200 bg-white p-2 shadow-xl"
                        onMouseLeave={() => setSnapMenuOpen(false)}
                      >
                        <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-100">
                          <input
                            type="checkbox"
                            data-testid="dwg-snap-endpoint"
                            checked={!!snapModes.endpoint}
                            onChange={(e) =>
                              setSnapModes((m) => ({ ...m, endpoint: e.target.checked }))
                            }
                          />
                          {t('dwg_takeoff.snap_endpoint', {
                            defaultValue: 'Endpoint snap',
                          })}
                        </label>
                        <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-100">
                          <input
                            type="checkbox"
                            data-testid="dwg-snap-midpoint"
                            checked={!!snapModes.midpoint}
                            onChange={(e) =>
                              setSnapModes((m) => ({ ...m, midpoint: e.target.checked }))
                            }
                          />
                          {t('dwg_takeoff.snap_midpoint', {
                            defaultValue: 'Midpoint snap',
                          })}
                        </label>
                        <label className="flex cursor-not-allowed items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-400">
                          <input
                            type="checkbox"
                            data-testid="dwg-snap-intersection"
                            checked={!!snapModes.intersection}
                            disabled
                          />
                          {t('dwg_takeoff.snap_intersection', {
                            defaultValue: 'Intersection snap (soon)',
                          })}
                        </label>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Floating Offline Ready badge + PDF export — top-right corner
                  of the viewer (opposite the ToolPalette). Download PDF is
                  paired with the badge so estimators discover it while
                  glancing at converter status without stealing real estate
                  from the drawing. */}
              <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
                <ModuleGuideButton content={dwgTakeoffGuide} />
                <button
                  type="button"
                  onClick={() => setFindOpen((o) => !o)}
                  disabled={!selectedDrawingId}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold',
                    'border border-white/60 backdrop-blur-md',
                    'shadow-xl shadow-black/30 ring-1 ring-black/5 transition-colors',
                    !selectedDrawingId
                      ? 'bg-white/85 dark:bg-white/90 text-slate-400 cursor-not-allowed'
                      : findOpen
                        ? 'bg-oe-blue text-white hover:bg-oe-blue-dark'
                        : 'bg-white/85 dark:bg-white/90 text-slate-800 hover:bg-white',
                  )}
                  title={t('dwg_takeoff.find_text_title', {
                    defaultValue: 'Find text on the drawing (Ctrl+F)',
                  })}
                  data-testid="dwg-find-toggle"
                >
                  <Search size={14} />
                  <span>{t('dwg_takeoff.find_text', { defaultValue: 'Find' })}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setShowCompare(true)}
                  disabled={!selectedDrawingId}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold',
                    'border border-white/60 bg-white/85 dark:bg-white/90 backdrop-blur-md',
                    'shadow-xl shadow-black/30 ring-1 ring-black/5 transition-colors',
                    selectedDrawingId
                      ? 'text-slate-800 hover:bg-white'
                      : 'text-slate-400 cursor-not-allowed',
                  )}
                  title={t('dwg_compare.compare_revisions', {
                    defaultValue: 'Compare revisions with cost delta',
                  })}
                  data-testid="dwg-compare-button"
                >
                  <GitCompare size={14} />
                  <span>{t('dwg_compare.compare_short', { defaultValue: 'Compare' })}</span>
                </button>
                <button
                  type="button"
                  onClick={handleDownloadCanvasPdf}
                  disabled={!selectedDrawingId}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold',
                    'border border-white/60 bg-white/85 dark:bg-white/90 backdrop-blur-md',
                    'shadow-xl shadow-black/30 ring-1 ring-black/5 transition-colors',
                    selectedDrawingId
                      ? 'text-slate-800 hover:bg-white'
                      : 'text-slate-400 cursor-not-allowed',
                  )}
                  title={t('dwg_takeoff.download_pdf', {
                    defaultValue: 'Download current viewport as PDF',
                  })}
                  data-testid="dwg-download-pdf"
                >
                  <FileDown size={14} />
                  <span>{t('dwg_takeoff.download_pdf_short', { defaultValue: 'PDF' })}</span>
                </button>
                <OfflineReadyBadge
                  readiness={offlineReadiness}
                  isLoading={loadingOfflineReadiness}
                  data-testid="dwg-offline-badge"
                />
              </div>

              {/* Find-text bar — top-center overlay, parity with the PDF
                  takeoff "find on sheet". Highlights every TEXT/MTEXT hit and
                  zooms to the active one; the result list jumps on click. */}
              {findOpen && (
                <div
                  className="absolute top-3 left-1/2 z-20 flex -translate-x-1/2 flex-col items-stretch gap-1"
                  data-testid="dwg-find-bar"
                >
                  <div className="flex items-center gap-1 rounded-lg border border-white/60 bg-white/90 px-2 py-1.5 shadow-xl shadow-black/30 ring-1 ring-black/5 backdrop-blur-md dark:bg-slate-800/95">
                    <Search size={14} className="shrink-0 text-slate-500 dark:text-slate-300" />
                    <input
                      ref={findInputRef}
                      value={findQuery}
                      onChange={(e) => setFindQuery(e.target.value)}
                      onKeyDown={handleFindKeyDown}
                      placeholder={t('dwg_takeoff.find_placeholder', { defaultValue: 'Find text…' })}
                      className="w-44 bg-transparent text-xs text-slate-800 outline-none placeholder:text-slate-400 dark:text-slate-100"
                      data-testid="dwg-find-input"
                      spellCheck={false}
                      autoComplete="off"
                    />
                    <span
                      className="min-w-[52px] text-center text-[11px] tabular-nums text-slate-500 dark:text-slate-300"
                      data-testid="dwg-find-count"
                    >
                      {textMatches.length > 0
                        ? `${safeMatchIdx + 1} / ${textMatches.length}`
                        : findQuery.trim()
                          ? t('dwg_takeoff.find_none', { defaultValue: 'No results' })
                          : ''}
                    </span>
                    <button
                      type="button"
                      onClick={prevMatch}
                      disabled={textMatches.length === 0}
                      className="rounded p-1 text-slate-600 hover:bg-black/5 disabled:opacity-40 dark:text-slate-300 dark:hover:bg-white/10"
                      title={t('dwg_takeoff.find_prev', { defaultValue: 'Previous (Shift+Enter)' })}
                      data-testid="dwg-find-prev"
                    >
                      <ChevronUp size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={nextMatch}
                      disabled={textMatches.length === 0}
                      className="rounded p-1 text-slate-600 hover:bg-black/5 disabled:opacity-40 dark:text-slate-300 dark:hover:bg-white/10"
                      title={t('dwg_takeoff.find_next', { defaultValue: 'Next (Enter)' })}
                      data-testid="dwg-find-next"
                    >
                      <ChevronDown size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setFindOpen(false);
                        setFindQuery('');
                      }}
                      className="rounded p-1 text-slate-600 hover:bg-black/5 dark:text-slate-300 dark:hover:bg-white/10"
                      title={t('common.close', { defaultValue: 'Close' })}
                      data-testid="dwg-find-close"
                    >
                      <X size={14} />
                    </button>
                  </div>
                  {textMatches.length > 0 && (
                    <div
                      className="max-h-44 w-full overflow-y-auto rounded-lg border border-white/60 bg-white/95 py-1 shadow-xl ring-1 ring-black/5 backdrop-blur-md dark:bg-slate-800/95"
                      data-testid="dwg-find-results"
                    >
                      {textMatches.map((m, i) => (
                        <button
                          key={m.entityId}
                          type="button"
                          onClick={() => gotoMatch(i)}
                          className={clsx(
                            'block w-full truncate px-2.5 py-1 text-left text-[11px]',
                            i === safeMatchIdx
                              ? 'bg-oe-blue/15 font-semibold text-oe-blue'
                              : 'text-slate-700 hover:bg-black/5 dark:text-slate-200 dark:hover:bg-white/10',
                          )}
                          data-testid="dwg-find-result-row"
                        >
                          {m.snippet}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {/* Floating entity info popup (shared ElementInfoPopover) —
                  only shown for a single-entity click, hidden during
                  multi-select to keep the screen readable. */}
              {selectedEntity && entityPopup && activeTool === 'select'
                && selectedEntityIds.size === 1 && (
                <ElementInfoPopover
                  element={toDWGElementPayload(selectedEntity, effectiveScale, {
                    calculatePerimeter,
                    calculateArea,
                    calculateDistance,
                  })}
                  style={{
                    position: 'absolute',
                    left: Math.min(entityPopup.x + 16, (document.documentElement.clientWidth || 800) - 360),
                    top: Math.min(entityPopup.y + 16, (document.documentElement.clientHeight || 600) - 320),
                  }}
                  onClose={() => setEntityPopup(null)}
                  onLinkToBOQ={(elementId) => {
                    setEntityPopup(null);
                    handleOpenLinkToBoq(elementId);
                  }}
                />
              )}

              {/* Right-click context menu (RFC 11 §4.4) */}
              {contextMenu && (
                <DwgContextMenu
                  screenX={contextMenu.screenX}
                  screenY={contextMenu.screenY}
                  selectionSize={selectedEntityIds.size}
                  onHide={() => handleHideEntities(Array.from(selectedEntityIds))}
                  onIsolate={() => handleIsolateEntities(Array.from(selectedEntityIds))}
                  onLink={() => {
                    setContextMenu(null);
                    handleOpenLinkToBoq(contextMenu.entityId);
                  }}
                  onSaveAsGroup={handleSaveSelectionAsGroup}
                  onCreateTask={() => {
                    setContextMenu(null);
                    if (!selectedDrawingId) return;
                    const ids = selectedEntityIds.size > 0
                      ? Array.from(selectedEntityIds)
                      : [contextMenu.entityId];
                    const primary = entities.find((e) => e.id === ids[0]);
                    setCreateTaskFor({
                      entityIds: ids,
                      drawingId: selectedDrawingId,
                      entityLabel: primary
                        ? `${primary.type} · ${primary.layer}`
                        : undefined,
                    });
                  }}
                  onLinkSchedule={() => {
                    setContextMenu(null);
                    if (!selectedDrawingId) return;
                    const ids = selectedEntityIds.size > 0
                      ? Array.from(selectedEntityIds)
                      : [contextMenu.entityId];
                    const primary = entities.find((e) => e.id === ids[0]);
                    setLinkActivityFor({
                      entityIds: ids,
                      drawingId: selectedDrawingId,
                      entityLabel: primary
                        ? `${primary.type} · ${primary.layer}`
                        : undefined,
                    });
                  }}
                  onLinkDocument={() => {
                    setContextMenu(null);
                    if (!selectedDrawingId) return;
                    const ids = selectedEntityIds.size > 0
                      ? Array.from(selectedEntityIds)
                      : [contextMenu.entityId];
                    const primary = entities.find((e) => e.id === ids[0]);
                    setLinkDocumentFor({
                      entityIds: ids,
                      drawingId: selectedDrawingId,
                      entityLabel: primary
                        ? `${primary.type} · ${primary.layer}`
                        : undefined,
                    });
                  }}
                  onLinkRequirement={() => {
                    setContextMenu(null);
                    if (!selectedDrawingId) return;
                    const ids = selectedEntityIds.size > 0
                      ? Array.from(selectedEntityIds)
                      : [contextMenu.entityId];
                    const primary = entities.find((e) => e.id === ids[0]);
                    setLinkRequirementFor({
                      entityIds: ids,
                      drawingId: selectedDrawingId,
                      entityLabel: primary
                        ? `${primary.type} · ${primary.layer}`
                        : undefined,
                    });
                  }}
                  onClose={() => setContextMenu(null)}
                />
              )}

              {/* Right-docked BOQ-link picker panel — mirrors the PDF takeoff
                  picker pattern but slides in from the right edge of the
                  canvas. */}
              {linkingEntityId && selectedEntity && (() => {
                const measurement = extractEntityMeasurement(selectedEntity, effectiveScale);
                const alreadyLinked = annotations.find(
                  (a) => a.type === 'text_pin'
                    && (a.metadata as Record<string, unknown> | undefined)?.['dwg_entity_id']
                      === selectedEntity.id
                    && a.linked_boq_position_id,
                );
                return (
                  <div className="absolute top-3 right-3 z-20 flex flex-col w-80 max-h-[calc(100%-1.5rem)] rounded-lg border border-[#3a3a3a] bg-[#2f2f2f] text-slate-100 shadow-2xl">
                    {/* Header */}
                    <div className="flex items-center justify-between px-3 py-2 border-b border-[#3a3a3a]">
                      <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-100">
                        <Link2 size={13} className="text-blue-400" />
                        {alreadyLinked
                          ? t('dwg_takeoff.relink_title', { defaultValue: 'Linked - pick new' })
                          : t('dwg_takeoff.link_to_boq_title', { defaultValue: 'Link to BOQ position' })}
                      </div>
                      <button
                        onClick={() => setLinkingEntityId(null)}
                        aria-label={t('common.close', { defaultValue: 'Close' })}
                        title={t('common.close', { defaultValue: 'Close' })}
                        className="text-slate-400 hover:text-slate-100 transition-colors"
                      >
                        <X size={14} />
                      </button>
                    </div>

                    <div className="flex-1 overflow-y-auto p-3 space-y-2">
                      {/* Already-linked badge */}
                      {alreadyLinked && (
                        <div className="flex items-center gap-1.5 rounded-sm bg-emerald-950/40 border border-emerald-800/40 px-2 py-1 text-[11px]">
                          <Link2 size={11} className="text-emerald-400 shrink-0" />
                          <span className="text-emerald-300 truncate">
                            {t('dwg_takeoff.already_linked', { defaultValue: 'Already linked to a BOQ position' })}
                          </span>
                        </div>
                      )}

                      {/* Entity summary */}
                      <div className="rounded-sm bg-[#262626] border border-[#3a3a3a] p-2 text-[11px] space-y-0.5">
                        <div className="flex justify-between">
                          <span className="text-slate-400">{t('dwg_takeoff.prop_type', 'Type')}</span>
                          <span className="font-mono text-slate-100">{selectedEntity.type}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">{t('dwg_takeoff.prop_layer', 'Layer')}</span>
                          <span className="font-mono text-slate-100 truncate ml-2">{selectedEntity.layer}</span>
                        </div>
                        {measurement && (
                          <div className="flex justify-between">
                            <span className="text-slate-400">
                              {measurement.kind === 'area'
                                ? t('dwg_takeoff.area', 'Area')
                                : measurement.kind === 'radius'
                                  ? t('dwg_takeoff.prop_radius', 'Radius')
                                  : t('dwg_takeoff.length', { defaultValue: 'Length' })}
                            </span>
                            <span className="font-mono font-semibold text-blue-300">
                              {measurement.value} {measurement.unit}
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Project + BOQ dropdowns */}
                      <div className="grid grid-cols-2 gap-1.5">
                        <select
                          value={linkPickerProjectId}
                          onChange={(e) => handlePickerProjectChange(e.target.value)}
                          className="text-[11px] rounded-sm border border-[#3a3a3a] bg-[#262626] px-1.5 py-1 text-slate-100"
                        >
                          <option value="">
                            {t('dwg_takeoff.pick_project', { defaultValue: '- project -' })}
                          </option>
                          {linkPickerProjects.map((p) => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                          ))}
                        </select>
                        <select
                          value={linkPickerBoqId}
                          onChange={(e) => handlePickerBoqChange(e.target.value)}
                          disabled={!linkPickerProjectId || linkBoqsLoading}
                          className="text-[11px] rounded-sm border border-[#3a3a3a] bg-[#262626] px-1.5 py-1 text-slate-100 disabled:opacity-60"
                        >
                          <option value="">
                            {linkBoqsLoading
                              ? t('common.loading', 'Loading...')
                              : t('dwg_takeoff.pick_boq', { defaultValue: '- BOQ -' })}
                          </option>
                          {linkPickerBoqs.map((b) => (
                            <option key={b.id} value={b.id}>{b.name}</option>
                          ))}
                        </select>
                      </div>

                      {/* Mode switch */}
                      <div className="flex gap-1 text-[11px]">
                        <button
                          type="button"
                          onClick={() => setLinkPickerMode('pick')}
                          className={clsx(
                            'flex-1 px-2 py-1 rounded-sm font-medium transition-colors',
                            linkPickerMode === 'pick'
                              ? 'bg-blue-600 text-white'
                              : 'bg-[#363636] text-slate-300 hover:bg-[#404040]',
                          )}
                        >
                          {t('dwg_takeoff.mode_pick', { defaultValue: 'Pick existing' })}
                        </button>
                        <button
                          type="button"
                          onClick={() => setLinkPickerMode('create')}
                          disabled={!linkPickerBoqId}
                          className={clsx(
                            'flex-1 px-2 py-1 rounded-sm font-medium transition-colors disabled:opacity-50',
                            linkPickerMode === 'create'
                              ? 'bg-blue-600 text-white'
                              : 'bg-[#363636] text-slate-300 hover:bg-[#404040]',
                          )}
                        >
                          {t('dwg_takeoff.mode_create', { defaultValue: '+ Create new' })}
                        </button>
                      </div>

                      {linkPickerMode === 'pick' ? (
                        !linkPickerBoqId ? (
                          <p className="text-[11px] text-slate-400 py-2 text-center">
                            {t('dwg_takeoff.link_need_project_boq', {
                              defaultValue: 'Pick a project and BOQ above.',
                            })}
                          </p>
                        ) : linkPositionsLoading ? (
                          <div className="flex items-center justify-center gap-1.5 py-3">
                            <Loader2 size={12} className="animate-spin text-blue-400" />
                            <span className="text-[11px] text-slate-400">
                              {t('common.loading', 'Loading...')}
                            </span>
                          </div>
                        ) : linkBoqPositions.filter((p) => p.unit).length === 0 ? (
                          <p className="text-[11px] text-slate-400 py-2 text-center">
                            {t('dwg_takeoff.link_boq_empty', {
                              defaultValue: 'BOQ is empty - switch to "Create new".',
                            })}
                          </p>
                        ) : (
                          <>
                            <input
                              type="text"
                              value={linkPickerSearch}
                              onChange={(e) => setLinkPickerSearch(e.target.value)}
                              placeholder={t('dwg_takeoff.link_search_placeholder', {
                                defaultValue: 'Search ordinal or description...',
                              })}
                              className="w-full text-[11px] rounded-sm border border-[#3a3a3a] bg-[#262626] px-2 py-1 text-slate-100 placeholder:text-slate-500"
                            />
                            <div className="max-h-56 overflow-y-auto space-y-0.5">
                              {linkBoqPositions
                                .filter((p) => p.unit)
                                .filter((p) => {
                                  if (!linkPickerSearch) return true;
                                  const q = linkPickerSearch.toLowerCase();
                                  return (
                                    (p.ordinal || '').toLowerCase().includes(q) ||
                                    (p.description || '').toLowerCase().includes(q)
                                  );
                                })
                                .slice(0, 100)
                                .map((pos) => (
                                  <button
                                    key={pos.id}
                                    type="button"
                                    onClick={() => {
                                      if (selectedEntityIds.size > 1) {
                                        handleLinkGroupToPosition(pos);
                                      } else {
                                        handleLinkToPosition(selectedEntity.id, pos);
                                      }
                                    }}
                                    disabled={linkingInProgress}
                                    className="w-full text-left px-2 py-1 rounded-sm text-[11px] hover:bg-blue-900/40 transition-colors flex items-center gap-1.5 disabled:opacity-50"
                                  >
                                    <span className="font-mono text-blue-300 shrink-0">
                                      {pos.ordinal}
                                    </span>
                                    <span className="text-slate-100 truncate flex-1">
                                      {pos.description}
                                    </span>
                                    <span className="text-slate-400 shrink-0 text-[10px]">
                                      {pos.unit}
                                    </span>
                                  </button>
                                ))}
                            </div>
                          </>
                        )
                      ) : (
                        /* Create new position */
                        <div className="rounded-sm bg-[#262626] border border-[#3a3a3a] p-2 space-y-1.5">
                          <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px]">
                            <span className="text-slate-400">
                              {t('dwg_takeoff.description', { defaultValue: 'Description' })}:
                            </span>
                            <span className="text-slate-100 truncate">
                              {t('dwg_takeoff.position_default_desc', {
                                defaultValue: 'From DWG: {{layer}}',
                                layer: selectedEntity.layer,
                              })}
                            </span>
                            <span className="text-slate-400">
                              {t('dwg_takeoff.quantity', { defaultValue: 'Quantity' })}:
                            </span>
                            <span className="text-slate-100 font-mono">
                              {measurement
                                ? `${measurement.value} ${measurement.unit}`
                                : `0 ${normalizeUnit('pcs')}`}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleCreateAndLink(selectedEntity.id)}
                            disabled={linkingInProgress || !linkPickerBoqId}
                            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-sm text-[11px] font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                          >
                            {linkingInProgress && <Loader2 size={11} className="animate-spin" />}
                            {t('dwg_takeoff.create_and_link', {
                              defaultValue: 'Create position & link',
                            })}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()}
            </div>
            {/* ── Sheet thumbnail strip (Goal 2) ──────────────────────
                 Bottom of the viewer, above the drawings filmstrip.
                 Hidden automatically when the DWG has only one layout.
                 Clicking a thumbnail switches the layout without losing
                 the current tool; calibration is keyed by layout so the
                 scale swaps in/out with the sheet. */}
            <SheetStrip
              layouts={layouts}
              entities={entities}
              activeLayout={selectedLayout}
              onLayoutChange={setSelectedLayout}
              entityCountByLayout={entityCountByLayout}
            />
            </>
          )}

          {/* ── Bottom Filmstrip: Drawing List (always visible) ──── */}
          <DrawingFilmstrip
            drawings={drawings}
            isLoading={loadingDrawings}
            activeDrawingId={selectedDrawingId}
            entities={entities}
            onSelectDrawing={handleSelectDrawing}
            onDeleteDrawing={(id) => setConfirmDeleteId(id)}
            onUpload={() => setShowUpload(true)}
          />
        </div>

        {/* ── Right Panel: Layers / Annotations / Properties ───── */}
        {selectedDrawingId && (
          <div className="flex w-72 flex-shrink-0 flex-col border-l border-border-light bg-surface-primary text-content-primary shadow-xl shadow-black/30">
            {/* Group aggregation panel (RFC 11 §4.5) — visible when 2+ entities selected */}
            {selectedEntityIds.size > 1 && (
              <div
                className="border-b border-border-light px-3 py-2.5 bg-amber-950/20"
                data-testid="dwg-group-panel"
              >
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <Sigma size={13} className="text-amber-400" />
                    <span className="text-[11px] font-semibold text-content-primary">
                      {t('dwg_takeoff.group_selection', { defaultValue: 'Group selection' })}
                    </span>
                    <span className="text-[10px] text-content-tertiary tabular-nums">
                      ({selectedEntityIds.size})
                    </span>
                  </div>
                  <button
                    onClick={() => { setSelectedEntityIds(new Set()); setEntityPopup(null); }}
                    className="text-content-tertiary hover:text-content-primary"
                    title={t('dwg_takeoff.clear_selection', { defaultValue: 'Clear selection' })}
                  >
                    <X size={12} />
                  </button>
                </div>
                <div
                  className="grid grid-cols-3 gap-1.5 text-[11px]"
                  data-testid="dwg-group-aggregate"
                >
                  <div>
                    <div
                      className="font-semibold text-content-primary tabular-nums"
                      data-testid="dwg-group-area"
                    >
                      {selectionAggregate.area > 0 ? selectionAggregate.area.toFixed(2) : '—'}
                    </div>
                    <div className="text-content-tertiary text-[9px] uppercase">
                      {t('dwg_takeoff.area', 'Area')} m²
                    </div>
                  </div>
                  <div>
                    <div
                      className="font-semibold text-content-primary tabular-nums"
                      data-testid="dwg-group-perimeter"
                    >
                      {selectionAggregate.perimeter > 0
                        ? selectionAggregate.perimeter.toFixed(2) : '—'}
                    </div>
                    <div className="text-content-tertiary text-[9px] uppercase">
                      {t('dwg_takeoff.perimeter', 'Perimeter')} m
                    </div>
                  </div>
                  <div>
                    <div
                      className="font-semibold text-content-primary tabular-nums"
                      data-testid="dwg-group-length"
                    >
                      {selectionAggregate.length > 0
                        ? selectionAggregate.length.toFixed(2) : '—'}
                    </div>
                    <div className="text-content-tertiary text-[9px] uppercase">
                      {t('dwg_takeoff.length', 'Length')} m
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 mt-2">
                  <button
                    onClick={handleCreateBoqFromGroup}
                    disabled={linkingInProgress}
                    className="flex-1 flex items-center justify-center gap-1 rounded-md bg-oe-blue text-white text-[11px] font-semibold px-2 py-1 hover:bg-oe-blue-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    data-testid="dwg-group-create-boq"
                    title={t('dwg_takeoff.group_to_boq_title', {
                      defaultValue: 'Book the group total as one BOQ position',
                    })}
                  >
                    <Link2 size={11} />
                    {t('dwg_takeoff.add_n_to_boq', {
                      defaultValue: 'Add {{count}} to BOQ',
                      count: selectedEntityIds.size,
                    })}
                  </button>
                  <button
                    onClick={handleSaveSelectionAsGroup}
                    className="flex items-center justify-center rounded-md border border-border-medium bg-surface-secondary text-content-primary text-[11px] px-2 py-1 hover:bg-surface-tertiary transition-colors"
                    title={t('dwg_takeoff.save_as_group', { defaultValue: 'Save as group' })}
                    data-testid="dwg-group-save"
                  >
                    <FolderPlus size={11} />
                  </button>
                </div>
              </div>
            )}

            {/* Hidden-entities toolbar */}
            {hiddenEntityIds.size > 0 && (
              <div className="flex items-center justify-between border-b border-border-light bg-surface-secondary/60 px-3 py-1.5">
                <span className="text-[10px] text-content-tertiary flex items-center gap-1">
                  <EyeOff size={11} />
                  {t('dwg_takeoff.hidden_count', {
                    defaultValue: '{{count}} hidden',
                    count: hiddenEntityIds.size,
                  })}
                </span>
                <button
                  onClick={handleShowAllEntities}
                  className="text-[10px] font-medium text-oe-blue hover:text-oe-blue/80 flex items-center gap-0.5"
                >
                  <Eye size={11} />
                  {t('dwg_takeoff.show_all', { defaultValue: 'Show all' })}
                </button>
              </div>
            )}

            {/* Summary bar — totals across current drawing */}
            {(entities.length > 0 || annotations.length > 0) && (() => {
              // Persisted measurement_value is in raw DXF units; convert to
              // real metres (area × scale², distance × scale) so the totals
              // match the canvas labels.
              const areaSum =
                annotations
                  .filter((a) => a.type === 'area' && a.measurement_value != null)
                  .reduce((s, a) => s + (a.measurement_value ?? 0), 0) *
                effectiveScale *
                effectiveScale;
              const distSum =
                annotations
                  .filter((a) => a.type === 'distance' && a.measurement_value != null)
                  .reduce((s, a) => s + (a.measurement_value ?? 0), 0) * effectiveScale;
              const handleExportCsv = () => {
                const rows = [
                  ['type', 'text', 'value', 'unit', 'linked_boq_position_id'].join(','),
                  ...annotations.map((a) => {
                    // Export real-metre values (raw DXF units × effectiveScale)
                    // so the CSV's m / m² columns are meaningful.
                    const isArea = (a.measurement_unit ?? '').includes('²');
                    const scaled =
                      a.measurement_value == null
                        ? ''
                        : (
                            a.measurement_value *
                            (isArea ? effectiveScale * effectiveScale : effectiveScale)
                          ).toFixed(3);
                    return [
                      a.type,
                      JSON.stringify(a.text ?? ''),
                      scaled,
                      a.measurement_unit ?? '',
                      a.linked_boq_position_id ?? '',
                    ].join(',');
                  }),
                ];
                const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `annotations-${selectedDrawingId?.slice(0, 8) ?? 'dwg'}.csv`;
                link.click();
                URL.revokeObjectURL(url);
                addToast({ type: 'success', title: t('dwg_takeoff.csv_exported', 'Measurements exported') });
              };
              return (
                <div className="border-b border-border-light px-3 py-2 bg-surface-secondary/40">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('dwg_takeoff.summary', 'Summary')}
                    </span>
                    <button
                      onClick={handleExportCsv}
                      disabled={annotations.length === 0}
                      className="text-[10px] font-medium text-oe-blue hover:text-oe-blue/80 disabled:text-content-quaternary disabled:cursor-not-allowed"
                      title={t('dwg_takeoff.export_csv', 'Export measurements as CSV')}
                    >
                      {t('dwg_takeoff.export_csv_short', 'Export CSV')}
                    </button>
                  </div>
                  <div className="grid grid-cols-3 gap-1.5 text-[11px]">
                    <div>
                      <div className="font-semibold text-content-primary tabular-nums">{entities.length}</div>
                      <div className="text-content-tertiary text-[9px] uppercase">{t('dwg_takeoff.entities', 'Entities')}</div>
                    </div>
                    <div>
                      <div className="font-semibold text-content-primary tabular-nums">{areaSum > 0 ? areaSum.toFixed(1) : '—'}</div>
                      <div className="text-content-tertiary text-[9px] uppercase">m²</div>
                    </div>
                    <div>
                      <div className="font-semibold text-content-primary tabular-nums">{distSum > 0 ? distSum.toFixed(1) : '—'}</div>
                      <div className="text-content-tertiary text-[9px] uppercase">m</div>
                    </div>
                  </div>
                </div>
              );
            })()}

            {/* Tab bar — stacked icon + label so five tabs fit cleanly in
                a narrow side panel without the text overlapping the icon.
                Short labels + tooltips keep it readable at ~320-360 px. */}
            <div className="flex border-b border-border">
              {(
                [
                  { id: 'layers' as const, icon: Layers, labelKey: 'dwg_takeoff.tab_layers_short', fallback: 'Layers', titleKey: 'dwg_takeoff.layers', titleFallback: 'Layers', count: visibleLayers.size > 0 ? visibleLayers.size : layers.length },
                  { id: 'annotations' as const, icon: MessageSquare, labelKey: 'dwg_takeoff.tab_annotations_short', fallback: 'Notes', titleKey: 'dwg_takeoff.annotations', titleFallback: 'Annotations', count: annotations.length },
                  { id: 'properties' as const, icon: Info, labelKey: 'dwg_takeoff.tab_properties_short', fallback: 'Props', titleKey: 'dwg_takeoff.properties', titleFallback: 'Properties', count: 0 },
                  { id: 'scale' as const, icon: Ruler, labelKey: 'dwg_takeoff.tab_scale_short', fallback: 'Scale', titleKey: 'dwg_takeoff.tab_scale', titleFallback: 'Drawing scale', count: 0 },
                  { id: 'summary' as const, icon: BarChart3, labelKey: 'dwg_takeoff.tab_summary_short', fallback: 'Sum', titleKey: 'dwg_takeoff.summary', titleFallback: 'Summary', count: 0 },
                ]
              ).map(({ id, icon: Icon, labelKey, fallback, titleKey, titleFallback, count }) => (
                <button
                  key={id}
                  onClick={() => setRightTab(id)}
                  title={t(titleKey, titleFallback)}
                  className={clsx(
                    'flex flex-1 min-w-0 flex-col items-center justify-center gap-0.5 py-1.5 px-1 text-[10px] font-medium leading-none transition-colors',
                    rightTab === id
                      ? 'border-b-2 border-oe-blue text-oe-blue'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                  data-testid={`dwg-right-tab-${id}`}
                >
                  <Icon size={14} />
                  <span className="flex items-center gap-0.5 truncate">
                    <span className="truncate">{t(labelKey, fallback)}</span>
                    {count > 0 && (
                      <span className="text-[9px] tabular-nums opacity-60">
                        ({count})
                      </span>
                    )}
                  </span>
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {rightTab === 'layers' && (
                <>
                  <LayerPanel
                    layers={layers}
                    visibleLayers={visibleLayers}
                    onToggleLayer={handleToggleLayer}
                    onShowAll={handleShowAllLayers}
                    onHideAll={handleHideAllLayers}
                  />
                  <EntityNameFilter
                    entities={filteredEntities}
                    visibleNames={visibleNames}
                    onToggleName={handleToggleName}
                    onShowAllNames={handleShowAllNames}
                    onHideAllNames={handleHideAllNames}
                  />
                </>
              )}

              {rightTab === 'annotations' && (
                <div className="flex flex-col gap-2">
                  <h3 className="text-sm font-semibold text-foreground">
                    {t('dwg_takeoff.annotations', 'Annotations')}
                    {annotations.length > 0 && (
                      <Badge variant="neutral" className="ml-2">
                        {annotations.length}
                      </Badge>
                    )}
                  </h3>
                  {annotations.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-4 text-center">
                      {t('dwg_takeoff.no_annotations', 'No annotations yet. Use the toolbar to add measurements.')}
                    </p>
                  ) : (
                    annotations.map((ann) => (
                      <button
                        key={ann.id}
                        onClick={() => setSelectedAnnotationId(ann.id)}
                        className={clsx(
                          'flex items-center gap-2 rounded px-2 py-1.5 text-xs text-left transition-colors',
                          selectedAnnotationId === ann.id
                            ? 'bg-oe-blue/10 text-oe-blue'
                            : 'text-foreground hover:bg-surface-secondary',
                        )}
                      >
                        <span
                          className="h-2.5 w-2.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: ann.color }}
                        />
                        <div className="flex-1 truncate">
                          <span className="font-medium capitalize">{ann.type.replace('_', ' ')}</span>
                          {ann.text && <span className="ml-1 text-muted-foreground">- {ann.text}</span>}
                          {ann.measurement_value != null && (
                            <span className="ml-1 text-muted-foreground">
                              ({ann.measurement_value.toFixed(2)} {ann.measurement_unit ?? 'm'})
                            </span>
                          )}
                        </div>
                        <button
                          onClick={async (e) => {
                            e.stopPropagation();
                            const ok = await confirmAnnotDelete({
                              title: t('dwg_takeoff.confirm_delete_annotation', 'Delete annotation?'),
                              message: t('dwg_takeoff.confirm_delete_annotation_desc', 'This annotation will be permanently removed.'),
                              confirmLabel: t('common.delete', 'Delete'),
                              variant: 'danger',
                            });
                            if (ok) {
                              deleteAnnotationMutation.mutate({
                                id: ann.id,
                                snapshotForUndo: snapshotFrom(ann),
                              });
                            }
                          }}
                          aria-label={t('dwg_takeoff.delete_annotation', { defaultValue: 'Delete annotation' })}
                          title={t('dwg_takeoff.delete_annotation', { defaultValue: 'Delete annotation' })}
                          className="text-muted-foreground hover:text-red-500"
                        >
                          <Trash2 size={12} />
                        </button>
                      </button>
                    ))
                  )}
                </div>
              )}

              {rightTab === 'properties' && (
                <div className="flex flex-col gap-2">
                  <h3 className="text-sm font-semibold text-foreground">
                    {t('dwg_takeoff.properties', 'Properties')}
                  </h3>
                  {selectedEntity ? (
                    <div className="space-y-2 text-xs">
                      <PropertyRow label={t('dwg_takeoff.prop_type', 'Type')} value={selectedEntity.type} />
                      <PropertyRow label={t('dwg_takeoff.prop_layer', 'Layer')} value={selectedEntity.layer} />
                      <PropertyRow label={t('dwg_takeoff.prop_color', 'Color')} value={String(selectedEntity.color)} />
                      <PropertyRow label={t('dwg_takeoff.prop_id', 'ID')} value={selectedEntity.id} />
                      {selectedEntity.start && (
                        <PropertyRow
                          label={t('dwg_takeoff.prop_position', 'Position')}
                          value={`(${selectedEntity.start.x.toFixed(2)}, ${selectedEntity.start.y.toFixed(2)})`}
                        />
                      )}
                      {selectedEntity.radius != null && (
                        <PropertyRow label={t('dwg_takeoff.prop_radius', 'Radius')} value={selectedEntity.radius.toFixed(3)} />
                      )}
                      {selectedEntity.text && (
                        <PropertyRow label={t('dwg_takeoff.prop_text', 'Text')} value={selectedEntity.text} />
                      )}
                      {selectedEntity.block_name && (
                        <PropertyRow label={t('dwg_takeoff.prop_block', 'Block')} value={selectedEntity.block_name} />
                      )}

                      {/* ── Attach-to: cross-module link actions ────
                       *  Matches the BIM page's "+ New task / + Link
                       *  document / ..." affordances.  Lives above the
                       *  polyline measurements block so the actions are
                       *  discoverable before the user scrolls through
                       *  per-segment lengths. */}
                      {selectedDrawingId && (
                        <div className="mt-3 space-y-1.5">
                          <div className="font-semibold text-xs text-foreground border-b border-border pb-1">
                            {t('dwg_takeoff.attach_to', { defaultValue: 'Attach to' })}
                          </div>
                          <button
                            type="button"
                            onClick={() => handleOpenLinkToBoq(selectedEntity.id)}
                            className="w-full flex items-center gap-2 rounded-md border border-border bg-surface-secondary px-2 py-1.5 text-left text-[11px] text-content-primary hover:bg-surface-tertiary transition-colors"
                            data-testid="dwg-attach-boq"
                          >
                            <Link2 size={12} className="text-oe-blue shrink-0" />
                            <span className="flex-1">
                              {t('dwg_takeoff.attach_boq', { defaultValue: 'Link to BOQ' })}
                            </span>
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setCreateTaskFor({
                                entityIds: [selectedEntity.id],
                                drawingId: selectedDrawingId,
                                entityLabel: `${selectedEntity.type} · ${selectedEntity.layer}`,
                              })
                            }
                            className="w-full flex items-center gap-2 rounded-md border border-border bg-surface-secondary px-2 py-1.5 text-left text-[11px] text-content-primary hover:bg-surface-tertiary transition-colors"
                            data-testid="dwg-attach-task"
                          >
                            <ListChecks size={12} className="text-amber-500 shrink-0" />
                            <span className="flex-1">
                              {t('dwg_takeoff.attach_task', { defaultValue: '+ New task' })}
                            </span>
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setLinkDocumentFor({
                                entityIds: [selectedEntity.id],
                                drawingId: selectedDrawingId,
                                entityLabel: `${selectedEntity.type} · ${selectedEntity.layer}`,
                              })
                            }
                            className="w-full flex items-center gap-2 rounded-md border border-border bg-surface-secondary px-2 py-1.5 text-left text-[11px] text-content-primary hover:bg-surface-tertiary transition-colors"
                            data-testid="dwg-attach-document"
                          >
                            <FileText size={12} className="text-violet-500 shrink-0" />
                            <span className="flex-1">
                              {t('dwg_takeoff.attach_document', { defaultValue: '+ Link document' })}
                            </span>
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setLinkActivityFor({
                                entityIds: [selectedEntity.id],
                                drawingId: selectedDrawingId,
                                entityLabel: `${selectedEntity.type} · ${selectedEntity.layer}`,
                              })
                            }
                            className="w-full flex items-center gap-2 rounded-md border border-border bg-surface-secondary px-2 py-1.5 text-left text-[11px] text-content-primary hover:bg-surface-tertiary transition-colors"
                            data-testid="dwg-attach-activity"
                          >
                            <CalendarDays size={12} className="text-emerald-500 shrink-0" />
                            <span className="flex-1">
                              {t('dwg_takeoff.attach_activity', { defaultValue: '+ Link activity' })}
                            </span>
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setLinkRequirementFor({
                                entityIds: [selectedEntity.id],
                                drawingId: selectedDrawingId,
                                entityLabel: `${selectedEntity.type} · ${selectedEntity.layer}`,
                              })
                            }
                            className="w-full flex items-center gap-2 rounded-md border border-border bg-surface-secondary px-2 py-1.5 text-left text-[11px] text-content-primary hover:bg-surface-tertiary transition-colors"
                            data-testid="dwg-attach-requirement"
                          >
                            <ClipboardCheck size={12} className="text-violet-500 shrink-0" />
                            <span className="flex-1">
                              {t('dwg_takeoff.attach_requirement', { defaultValue: '+ Link requirement' })}
                            </span>
                          </button>
                        </div>
                      )}

                      {/* ── Polyline measurements ──────────────── */}
                      {selectedEntity.type === 'LWPOLYLINE' && selectedEntity.vertices && selectedEntity.vertices.length >= 2 && (() => {
                        const verts = selectedEntity.vertices!;
                        const closed = !!selectedEntity.closed;
                        const segLengths = getSegmentLengths(verts, closed);
                        // Apply current drawing scale on display so the right-panel
                        // numbers stay in sync with the canvas labels when the user
                        // picks a different ratio via the Scale tab.
                        const perimeter = calculatePerimeter(verts, closed) * effectiveScale;
                        // calculateAreaSafe flags a self-intersecting
                        // ("bowtie") trace whose shoelace area cancels to
                        // a wrong/zero figure, so the estimator can fix
                        // the polyline instead of booking it (D-TKC-015).
                        const areaResult: { area: number; degenerate: AreaDegeneracy } =
                          closed
                            ? calculateAreaSafe(verts)
                            : { area: 0, degenerate: null };
                        const area = areaResult.area * effectiveScale * effectiveScale;
                        const areaDegenerate = areaResult.degenerate;
                        return (
                          <div className="mt-3 space-y-2">
                            <div className="font-semibold text-xs text-foreground border-b border-border pb-1">
                              {t('dwg_takeoff.measurements', 'Measurements')}
                            </div>
                            <div className="flex items-center justify-between rounded-md bg-emerald-950/30 px-2.5 py-1.5 border border-emerald-800/40">
                              <span className="text-emerald-400 font-medium">
                                {t('dwg_takeoff.perimeter', 'Perimeter')}
                              </span>
                              <span className="font-mono font-bold text-emerald-300">
                                {formatMeasurement(perimeter, 'm')}
                              </span>
                            </div>
                            {closed && area > 0 && !areaDegenerate && (
                              <div className="flex items-center justify-between rounded-md bg-blue-950/30 px-2.5 py-1.5 border border-blue-800/40">
                                <span className="text-blue-400 font-medium">
                                  {t('dwg_takeoff.area', 'Area')}
                                </span>
                                <span className="font-mono font-bold text-blue-300">
                                  {formatMeasurement(area, 'm\u00B2')}
                                </span>
                              </div>
                            )}
                            {closed && areaDegenerate && (
                              <div className="rounded-md bg-amber-950/30 px-2.5 py-1.5 border border-amber-800/40 text-amber-300 text-2xs">
                                {areaDegenerate === 'self_intersecting'
                                  ? t('dwg_takeoff.area_self_intersecting', {
                                      defaultValue:
                                        'This outline crosses itself \u2014 the area is unreliable. Re-trace it as a simple (non-crossing) polygon before using it as a quantity.',
                                    })
                                  : t('dwg_takeoff.area_degenerate', {
                                      defaultValue:
                                        'This outline encloses no measurable area. Check the vertices before using it as a quantity.',
                                    })}
                              </div>
                            )}
                            <PropertyRow
                              label={t('dwg_takeoff.vertices', 'Vertices')}
                              value={String(verts.length)}
                            />
                            <PropertyRow
                              label={t('dwg_takeoff.closed', 'Closed')}
                              value={closed
                                ? t('common.yes', 'Yes')
                                : t('common.no', 'No')}
                            />
                            <div className="mt-2">
                              <div className="font-medium text-[10px] text-muted-foreground uppercase tracking-wider mb-1">
                                {t('dwg_takeoff.segments', 'Segments')} ({segLengths.length})
                              </div>
                              <div className="space-y-0.5 max-h-48 overflow-y-auto">
                                {segLengths.map((len, i) => (
                                  <div
                                    key={i}
                                    className="flex items-center justify-between rounded px-2 py-1 bg-surface-secondary hover:bg-surface-tertiary transition-colors"
                                  >
                                    <span className="text-muted-foreground font-mono text-[10px]">
                                      #{i + 1}
                                    </span>
                                    <span className="font-mono font-medium text-[11px]">
                                      {formatMeasurement(len * effectiveScale, 'm')}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground py-4 text-center">
                      {t('dwg_takeoff.select_entity', 'Click an entity in the viewer to see its properties.')}
                    </p>
                  )}
                </div>
              )}

              {rightTab === 'scale' && (
                <ScaleTab
                  drawingScale={drawingScale}
                  onDrawingScaleChange={setDrawingScale}
                  mode={scaleMode}
                  onModeChange={setScaleMode}
                  isCalibrating={isCalibrating}
                  calibrationPixels={calibrationPixels}
                  onStartCalibration={handleStartCalibration}
                  onCancelCalibration={handleCancelCalibration}
                  dxfUnits={knownUnits}
                  effectiveScale={effectiveScale}
                />
              )}

              {rightTab === 'summary' && (
                <SummaryTab
                  entityCount={filteredEntities.length}
                  aggregate={summaryAggregate}
                  layerQuantities={layerQuantities}
                  byType={summaryByType}
                  byBlock={summaryByBlock}
                  countTotal={countTotal}
                  onExportCsv={handleExportSummaryCsv}
                  onExportExcel={handleExportSummaryExcel}
                  onExportPdf={handleExportSummaryPdf}
                />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Upload form modal overlay */}
      {showUpload && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
          onClick={closeUploadModal}
          onKeyDown={(e) => { if (e.key === 'Escape') closeUploadModal(); }}
          role="dialog"
          aria-modal="true"
          aria-label={t('dwg_takeoff.upload_drawing', 'Upload drawing')}
        >
          <div
            className="w-[420px] rounded-2xl border border-border-light bg-surface-primary shadow-2xl p-6 space-y-5"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-50 to-blue-100 dark:from-blue-950/30 dark:to-blue-900/20 border border-blue-200/50 dark:border-blue-800/30 flex items-center justify-center">
                  <FileUp size={20} className="text-oe-blue" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-content-primary">
                    {t('dwg_takeoff.upload_drawing', 'Upload drawing')}
                  </h3>
                  <p className="text-[11px] text-content-tertiary">
                    {t('dwg_takeoff.upload_hint', 'DWG or DXF files')}
                  </p>
                </div>
              </div>
              <button
                onClick={closeUploadModal}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-surface-secondary transition-colors"
              >
                <X size={16} className="text-content-tertiary hover:text-content-primary transition-colors" />
              </button>
            </div>

            {/* Drop zone / file picker */}
            <input
              ref={fileInputRef}
              id="dwg-takeoff-file-input"
              type="file"
              accept=".dwg,.dxf"
              aria-label={t('dwg_takeoff.upload_aria', { defaultValue: 'Upload DWG or DXF file' })}
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setUploadFile(f);
                  if (!uploadName) setUploadName(f.name.replace(/\.[^.]+$/, ''));
                }
              }}
            />
            <button
              type="button"
              aria-label={t('dwg_takeoff.upload_aria', { defaultValue: 'Upload DWG or DXF file' })}
              data-testid="dwg-modal-drop-zone"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragActive(true); }}
              onDragEnter={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragActive(true); }}
              onDragLeave={() => setIsDragActive(false)}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setIsDragActive(false);
                const f = e.dataTransfer.files?.[0];
                if (f) {
                  const ext = f.name.split('.').pop()?.toLowerCase();
                  if (ext !== 'dwg' && ext !== 'dxf') {
                    addToast({
                      type: 'error',
                      title: t('dwg_takeoff.invalid_format', 'Invalid file format'),
                      message: t('dwg_takeoff.accepted_formats', 'Only .dwg and .dxf files are accepted'),
                    });
                    return;
                  }
                  setUploadFile(f);
                  if (!uploadName) setUploadName(f.name.replace(/\.[^.]+$/, ''));
                }
              }}
              className={clsx(
                'w-full flex flex-col items-center gap-2 border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all',
                isDragActive && !uploadFile && 'border-oe-blue bg-oe-blue/10 scale-[1.01] shadow-md',
                uploadFile && !isDragActive && 'border-oe-blue bg-oe-blue/5',
                !uploadFile && !isDragActive && 'border-border-medium hover:border-oe-blue hover:bg-blue-50/50 dark:hover:bg-blue-950/20',
              )}
            >
              {uploadFile ? (
                <>
                  <div className="w-10 h-10 rounded-lg bg-oe-blue/10 flex items-center justify-center">
                    <FileText size={18} className="text-oe-blue" />
                  </div>
                  <p className="text-sm font-semibold text-content-primary">{uploadFile.name}</p>
                  <p className="text-[11px] text-content-quaternary">
                    {(uploadFile.size / 1024 / 1024).toFixed(1)} MB
                  </p>
                </>
              ) : (
                <>
                  <div className="w-10 h-10 rounded-lg bg-surface-secondary flex items-center justify-center">
                    <Upload size={18} className="text-content-tertiary" />
                  </div>
                  <p className="text-sm font-medium text-content-primary">
                    {t('dwg_takeoff.click_or_drop', 'Click or drag a file here')}
                  </p>
                  <p className="text-[11px] text-content-quaternary">.dwg, .dxf</p>
                </>
              )}
            </button>

            {/* Auto-install of the local DWG converter (background, no click).
                Shown when the user picks a .dwg and the converter is missing;
                DXF uploads bypass it entirely. The notice renders only while
                installing or after a failed attempt - on success it clears and
                the upload proceeds. Manual install stays a fallback (the
                OfflineReadyBadge CTA + the error-state link in the notice). */}
            {uploadNeedsDwgConverter && (
              <div className="space-y-1.5" data-testid="dwg-upload-install-hint">
                <p className="flex items-start gap-1.5 text-[10px] text-content-tertiary leading-relaxed">
                  <WifiOff size={12} className="shrink-0 mt-0.5" />
                  <span>
                    {t('dwg_takeoff.auto_install_dxf_note', {
                      defaultValue:
                        'DXF files already work without the converter - this only affects .dwg.',
                    })}
                  </span>
                </p>
                <AutoInstallConverterNotice state={dwgAutoInstall} variant="dark" />
              </div>
            )}

            {/* Project picker — fixes issue #110.
                On a fresh install with zero projects, the modal previously
                gated the submit button on a hidden `projectId` prerequisite
                with no UI surface, so the user saw a permanently disabled
                "Upload & Process" button and no explanation.

                When projects exist, this dropdown lets the user pick which
                one this drawing belongs to (defaults to the active or first
                project). When `projects.length === 0`, we render an explicit
                empty-state CTA that takes the user to /projects/new instead
                of leaving them stuck. */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-content-secondary">
                {t('dwg_takeoff.project_label', { defaultValue: 'Project' })}
              </label>
              {noProjects ? (
                <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-700 dark:text-amber-300">
                  <Info size={14} className="shrink-0 mt-0.5" />
                  <div className="flex-1 space-y-1.5">
                    <p className="font-semibold">
                      {t('dwg_takeoff.no_project_title', { defaultValue: 'Create a project first' })}
                    </p>
                    <p className="leading-relaxed text-amber-700/85 dark:text-amber-200/85">
                      {t('dwg_takeoff.no_project_body', {
                        defaultValue:
                          'Drawings have to live inside a project. Create one and you can come back to upload your DWG.',
                      })}
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        closeUploadModal();
                        navigate('/projects/new');
                      }}
                      className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/90 hover:bg-amber-600 text-white px-2.5 py-1 text-[11px] font-semibold transition-colors"
                    >
                      <Plus size={12} />
                      {t('dwg_takeoff.create_project_cta', { defaultValue: 'Create project' })}
                    </button>
                  </div>
                </div>
              ) : (
                <select
                  value={projectId}
                  onChange={(e) => {
                    const picked = projects.find((p) => p.id === e.target.value);
                    if (picked) setActiveProject(picked.id, picked.name);
                  }}
                  disabled={projectsLoading || projects.length === 0}
                  className="w-full rounded-xl border border-border-light bg-surface-secondary px-3.5 py-2.5 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all disabled:opacity-60"
                >
                  {projectsLoading && (
                    <option value="">{t('common.loading', { defaultValue: 'Loading…' })}</option>
                  )}
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Drawing name */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-content-secondary">
                {t('dwg_takeoff.drawing_name', 'Drawing name')}
              </label>
              <input
                type="text"
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
                placeholder={t('dwg_takeoff.drawing_name_placeholder', 'e.g. Floor Plan Level 1')}
                className="w-full rounded-xl border border-border-light bg-surface-secondary px-3.5 py-2.5 text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all"
              />
            </div>

            {/* Discipline */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-content-secondary">
                {t('dwg_takeoff.discipline_label', 'Discipline')}
              </label>
              <select
                value={uploadDiscipline}
                onChange={(e) => setUploadDiscipline(e.target.value)}
                className="w-full rounded-xl border border-border-light bg-surface-secondary px-3.5 py-2.5 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all"
              >
                <option value="architectural">{t('dwg_takeoff.discipline_arch', 'Architectural')}</option>
                <option value="structural">{t('dwg_takeoff.discipline_struct', 'Structural')}</option>
                <option value="mep">{t('dwg_takeoff.discipline_mep', 'MEP')}</option>
                <option value="civil">{t('dwg_takeoff.discipline_civil', 'Civil')}</option>
                <option value="other">{t('dwg_takeoff.discipline_other', 'Other')}</option>
              </select>
            </div>

            {/* Upload button — routes through the global DWG upload store so
                the job survives navigation and progress is shown in the
                corner dock.

                The disabled gate has three independent prerequisites
                (file, project, project list loaded). We surface the
                blocker explicitly so the user can act on it instead of
                staring at a perma-disabled button (issue #110). */}
            {(() => {
              const blocker = !uploadFile
                ? t('dwg_takeoff.blocker_file', { defaultValue: 'Choose a .dwg or .dxf file to enable upload.' })
                : noProjects
                  ? t('dwg_takeoff.blocker_no_project', { defaultValue: 'Create a project before uploading drawings.' })
                  : !projectId
                    ? t('dwg_takeoff.blocker_pick_project', { defaultValue: 'Pick a project from the list above.' })
                    : '';
              const isDisabled = !uploadFile || !projectId || projectsLoading;
              return (
                <div className="space-y-1.5">
                  <button
                    data-testid="dwg-upload-submit"
                    disabled={isDisabled}
                    title={blocker || undefined}
                    onClick={() => {
                      if (!uploadFile || !projectId) return;
                      useDwgUploadStore.getState().startUpload({
                        file: uploadFile,
                        projectId,
                        modelName: uploadName || uploadFile.name,
                        discipline: uploadDiscipline,
                      });
                      addToast({
                        type: 'info',
                        title: t('dwg_takeoff.upload_started', {
                          defaultValue: 'Upload started',
                        }),
                        message: t('dwg_takeoff.upload_started_hint', {
                          defaultValue:
                            'Progress continues in the dock - you can navigate away.',
                        }),
                      });
                      closeUploadModal();
                    }}
                    className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-oe-blue text-white hover:bg-oe-blue-dark active:scale-[0.98] shadow-md hover:shadow-lg"
                  >
                    <Upload size={16} />
                    {t('dwg_takeoff.upload_and_process', 'Upload & Process')}
                  </button>
                  {blocker && (
                    <p className="text-[11px] text-content-tertiary text-center">
                      {blocker}
                    </p>
                  )}
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {/* Delete drawing confirmation */}
      {confirmDeleteId && (
        <ConfirmDialog
          open
          title={t('dwg_takeoff.confirm_delete', 'Delete drawing?')}
          message={t(
            'dwg_takeoff.confirm_delete_desc',
            'This will permanently delete the drawing and all its annotations.',
          )}
          confirmLabel={t('common.delete', 'Delete')}
          variant="danger"
          loading={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(confirmDeleteId)}
          onCancel={() => setConfirmDeleteId(null)}
        />
      )}

      {/* Delete annotation confirmation */}
      <ConfirmDialog {...annotDeleteConfirmProps} />

      {/* Revision compare with cost delta (Item 17) */}
      {selectedDrawingId && (
        <DwgDrawingCompareDrawer
          open={showCompare}
          onClose={() => setShowCompare(false)}
          drawingId={selectedDrawingId}
          drawingName={
            selectedDrawingFromList?.name || selectedDrawingFromList?.filename || ''
          }
          onOverlayChange={setCompareOverlay}
        />
      )}

      {/* Inline cross-module link modals — mirror the BIM page pattern.
          Each one POSTs/PATCHes the relevant module and invalidates
          downstream queries so new badges appear instantly. */}
      {createTaskFor && projectId && (
        <CreateTaskFromDwgModal
          projectId={projectId}
          entityIds={createTaskFor.entityIds}
          drawingId={createTaskFor.drawingId}
          entityLabel={createTaskFor.entityLabel}
          onClose={() => setCreateTaskFor(null)}
        />
      )}
      {linkDocumentFor && projectId && (
        <LinkDocumentToDwgModal
          projectId={projectId}
          entityIds={linkDocumentFor.entityIds}
          drawingId={linkDocumentFor.drawingId}
          entityLabel={linkDocumentFor.entityLabel}
          onClose={() => setLinkDocumentFor(null)}
        />
      )}
      {linkActivityFor && projectId && (
        <LinkActivityToDwgModal
          projectId={projectId}
          entityIds={linkActivityFor.entityIds}
          drawingId={linkActivityFor.drawingId}
          entityLabel={linkActivityFor.entityLabel}
          onClose={() => setLinkActivityFor(null)}
        />
      )}
      {linkRequirementFor && projectId && (
        <LinkRequirementToDwgModal
          projectId={projectId}
          entityIds={linkRequirementFor.entityIds}
          drawingId={linkRequirementFor.drawingId}
          entityLabel={linkRequirementFor.entityLabel}
          onClose={() => setLinkRequirementFor(null)}
        />
      )}
    </div>
  );
}

/* ── EntityInfoPopup + BOQPositionPicker removed ─────────────────────── */
/* Replaced by shared <ElementInfoPopover> from @/shared/ui             */

/* ── Bottom Drawing Filmstrip ────────────────────────────────────────── */

interface DrawingFilmstripProps {
  drawings: {
    id: string;
    name: string;
    discipline: string;
    entity_count: number;
    created_at?: string;
  }[];
  isLoading: boolean;
  activeDrawingId: string | null;
  entities: DxfEntity[];
  onSelectDrawing: (id: string) => void;
  onDeleteDrawing: (id: string) => void;
  onUpload: () => void;
}

/**
 * Bottom-of-page strip of drawing cards.
 *
 * Changes vs. the previous revision:
 *  - Cards are ~30% smaller in both axes (w-36 × h-[72px] vs. w-52 × h-[108px])
 *    so a wider set of drawings fits in one row without horizontal scroll.
 *  - Shows "Uploaded <relative>" using date-fns `formatDistanceToNow` so
 *    estimators can spot stale vs. fresh drawings at a glance.
 *  - Always visible — no auto-hide / collapse toggle. All drawings in the
 *    active project are always on screen. A compact header still shows
 *    the count.
 */
function DrawingFilmstrip({
  drawings,
  isLoading,
  activeDrawingId,
  entities,
  onSelectDrawing,
  onDeleteDrawing,
  onUpload,
}: DrawingFilmstripProps) {
  const { t } = useTranslation();

  return (
    <div
      className="shrink-0 border-t border-[#2a2a2a] bg-[#2f2f2f] text-slate-200"
      data-testid="dwg-filmstrip"
    >
      {/* Header -- always visible, no longer acts as a collapse toggle. */}
      <div className="flex items-center w-full px-3 py-1">
        <Layers size={12} className="text-slate-300 mr-1.5 shrink-0" />
        <span className="text-[11px] font-semibold text-slate-100">
          {t('dwg_takeoff.drawings', 'Drawings')}
        </span>
        <span className="text-[10px] text-slate-400 ml-1">({drawings.length})</span>
      </div>

      {/* Drawing cards — always visible, horizontally scrolling if needed. */}
      <div className="flex items-center gap-1.5 px-3 pb-2 pt-0.5 overflow-x-auto">
        {isLoading ? (
          <Loader2 size={12} className="animate-spin text-slate-400" />
        ) : drawings.length > 0 ? (
          drawings.map((d) => {
            // Prefer date-fns' formatDistanceToNow for the upload label;
            // fall back to empty if it's missing or malformed (older rows
            // in dev DBs without a timestamp).
            let uploadedLabel = '';
            if (d.created_at) {
              try {
                const dt = new Date(d.created_at);
                if (!Number.isNaN(dt.getTime())) {
                  uploadedLabel = t('dwg_takeoff.uploaded_relative', {
                    defaultValue: 'Uploaded {{when}}',
                    when: formatDistanceToNow(dt, { addSuffix: true }),
                  });
                }
              } catch {
                uploadedLabel = '';
              }
            }

            return (
              // Card itself acts as a button (click selects); rendered as a
              // <div role="button"> so the inner delete button can stay a
              // real <button> — nesting buttons trips React's DOM warning.
              <div
                key={d.id}
                role="button"
                tabIndex={0}
                onClick={() => onSelectDrawing(d.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelectDrawing(d.id);
                  }
                }}
                className={clsx(
                  'group relative shrink-0 w-36 h-[72px] text-start rounded-md border overflow-hidden flex flex-col cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500/50',
                  'transition-all duration-150',
                  activeDrawingId === d.id
                    ? 'border-blue-500/80 bg-blue-500/10 shadow shadow-blue-500/20'
                    : 'border-[#3a3a3a] bg-[#363636] hover:bg-[#3d3d3d] hover:border-[#4a4a4a]',
                )}
                data-testid="dwg-filmstrip-card"
              >
                <div className="px-2 py-1.5 flex flex-col gap-0.5">
                  <div className="flex items-center gap-1">
                    <FileText
                      size={10}
                      className={clsx(
                        'shrink-0',
                        activeDrawingId === d.id ? 'text-blue-400' : 'text-slate-400',
                      )}
                    />
                    <span
                      className={clsx(
                        'text-[10px] font-semibold truncate',
                        activeDrawingId === d.id ? 'text-blue-300' : 'text-slate-100',
                      )}
                    >
                      {d.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 text-[9px] text-slate-400">
                    <span className="capitalize truncate">{d.discipline}</span>
                    <span>&middot;</span>
                    <span className="tabular-nums">
                      {activeDrawingId === d.id && entities.length > 0
                        ? entities.length
                        : d.entity_count || '--'}
                    </span>
                  </div>
                  {uploadedLabel && (
                    <div
                      className="text-[9px] text-slate-500 truncate"
                      title={uploadedLabel}
                    >
                      {uploadedLabel}
                    </div>
                  )}
                </div>
                {/* Delete button */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteDrawing(d.id);
                  }}
                  aria-label={t('dwg_takeoff.delete_drawing', { defaultValue: 'Delete drawing' })}
                  title={t('dwg_takeoff.delete_drawing', { defaultValue: 'Delete drawing' })}
                  className="absolute top-0.5 right-0.5 h-4 w-4 rounded flex items-center justify-center
                             text-transparent group-hover:text-slate-400 hover:!text-red-400 hover:bg-red-500/20
                             transition-all"
                >
                  <Trash2 size={9} />
                </button>
              </div>
            );
          })
        ) : (
          <span className="text-[10px] text-slate-400">
            {t('dwg_takeoff.no_drawings', 'No drawings uploaded yet')}
          </span>
        )}
        {/* Upload button — compact to match the new card dimensions. */}
        <button
          onClick={onUpload}
          className="flex items-center justify-center shrink-0 w-9 h-9 rounded-md border-2 border-dashed
                     border-[#4a4a4a] hover:border-blue-400/60 hover:bg-blue-500/10 transition-all group"
          title={t('dwg_takeoff.upload_drawing', 'Upload drawing')}
        >
          <Plus size={14} className="text-slate-400 group-hover:text-blue-300 transition-colors" />
        </button>
      </div>
    </div>
  );
}

/* ── Tiny sub-components ─────────────────────────────────────────────── */

function PropertyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-foreground">{value}</span>
    </div>
  );
}

/* ── Summary tab (R3 #12) ─────────────────────────────────────────────── */

interface SummaryKpiCardProps {
  label: string;
  value: string;
  unit?: string;
  accent: 'blue' | 'emerald' | 'amber' | 'violet';
}

/** One KPI tile in the Summary tab — count, area, perimeter, length. */
function SummaryKpiCard({ label, value, unit, accent }: SummaryKpiCardProps) {
  const accentMap: Record<SummaryKpiCardProps['accent'], string> = {
    blue: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
    emerald: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    amber: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    violet: 'text-violet-400 bg-violet-500/10 border-violet-500/20',
  };
  return (
    <div
      className={clsx(
        'rounded-lg border px-2.5 py-2 flex flex-col gap-0.5 min-w-0',
        accentMap[accent],
      )}
      data-testid="dwg-summary-kpi"
    >
      <div className="text-[9px] uppercase tracking-wider opacity-80 truncate">
        {label}
      </div>
      <div className="text-lg font-bold tabular-nums leading-tight truncate">
        {value}
        {unit && (
          <span className="text-[10px] font-medium ml-1 opacity-70">{unit}</span>
        )}
      </div>
    </div>
  );
}

/* ── Scale tab ─────────────────────────────────────────────────────────
 * Drawing scale selector lives here (moved out of a floating canvas
 * overlay).  Raw DXF units are treated as metres, so picking "1:50"
 * means every length reported on screen is divided by 50 (the drawing's
 * native unit is fifty times larger than the real-world one).  Presets
 * cover the common architectural ratios; a "Custom" slot lets the user
 * type any positive integer. */
const SCALE_PRESETS: { value: number; label: string }[] = [
  { value: 1, label: '1:1' },
  { value: 50, label: '1:50' },
  { value: 100, label: '1:100' },
  { value: 200, label: '1:200' },
  { value: 500, label: '1:500' },
];

interface ScaleTabProps {
  drawingScale: number;
  onDrawingScaleChange: (n: number) => void;
  mode: DwgScaleMode;
  onModeChange: (mode: DwgScaleMode) => void;
  /** Called when the user starts or cancels the two-point calibration pick.
   *  While the parent's "calibration arm" flag is set, the canvas captures
   *  the next two clicks and reports them back via `onCalibrationPicked`. */
  isCalibrating: boolean;
  calibrationPixels: number | null;
  onStartCalibration: () => void;
  onCancelCalibration: () => void;
  /** DXF $INSUNITS label ("mm", "cm", "m", ...) read from the drawing. */
  dxfUnits?: string | null;
  /** drawingScale × unit-factor — the multiplier actually applied to raw
   *  DXF coordinates before they become display metres. */
  effectiveScale: number;
}

function ScaleTab({
  drawingScale,
  onDrawingScaleChange,
  mode,
  onModeChange,
  isCalibrating,
  calibrationPixels,
  onStartCalibration,
  onCancelCalibration,
  dxfUnits,
  effectiveScale,
}: ScaleTabProps) {
  const { t } = useTranslation();
  const isPreset = SCALE_PRESETS.some((p) => p.value === drawingScale);
  const [customMode, setCustomMode] = useState(!isPreset);
  const [customInput, setCustomInput] = useState<string>(
    isPreset ? '' : String(drawingScale),
  );
  // Real-world distance the user types in during two-point calibration.
  const [realDistance, setRealDistance] = useState<string>('');
  const [realUnit, setRealUnit] = useState<'m' | 'cm' | 'mm'>('m');

  useEffect(() => {
    if (SCALE_PRESETS.some((p) => p.value === drawingScale)) {
      setCustomMode(false);
      setCustomInput('');
    } else {
      setCustomMode(true);
      setCustomInput(String(drawingScale));
    }
  }, [drawingScale]);

  const handlePickPreset = (value: number) => {
    setCustomMode(false);
    onDrawingScaleChange(value);
  };

  const handlePickCustom = () => {
    setCustomMode(true);
    if (!customInput) setCustomInput(String(drawingScale));
  };

  const handleCustomChange = (raw: string) => {
    setCustomInput(raw);
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) onDrawingScaleChange(n);
  };

  const applyCalibration = () => {
    if (!calibrationPixels) return;
    const distRaw = Number(realDistance);
    if (!Number.isFinite(distRaw) || distRaw <= 0) return;
    const distInMetres =
      realUnit === 'mm' ? distRaw / 1000 : realUnit === 'cm' ? distRaw / 100 : distRaw;
    // `drawingScale` is the denominator — raw/real. Ignoring the click
    // order, two points in raw DXF units measure `calibrationPixels`; the
    // user says those correspond to `distInMetres` of real-world length.
    // Denominator = raw / real, so measured-on-screen divided by this
    // gives the true metric length.
    const denom = calibrationPixels / distInMetres;
    if (Number.isFinite(denom) && denom > 0) onDrawingScaleChange(denom);
  };

  const ModeButton = ({
    id,
    label,
    hint,
  }: {
    id: DwgScaleMode;
    label: string;
    hint: string;
  }) => {
    const active = mode === id;
    return (
      <button
        type="button"
        onClick={() => onModeChange(id)}
        className={clsx(
          'flex-1 flex flex-col items-start gap-0.5 rounded-md border px-2.5 py-1.5 text-left text-[11px] transition-colors',
          active
            ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
            : 'border-border bg-surface-secondary text-content-primary hover:bg-surface-tertiary',
        )}
        data-testid={`dwg-scale-mode-${id}`}
        aria-pressed={active}
      >
        <span className="font-semibold">{label}</span>
        <span className={clsx('text-[10px] leading-tight', active ? 'text-oe-blue/80' : 'text-content-tertiary')}>
          {hint}
        </span>
      </button>
    );
  };

  const unitLabel = (dxfUnits ?? '').toLowerCase();
  const unitKnown = ['mm', 'cm', 'm', 'km', 'inches', 'in', 'feet', 'ft'].includes(unitLabel);

  return (
    <div className="flex flex-col gap-4" data-testid="dwg-scale-tab">
      <div className="flex items-center gap-1.5">
        <Ruler size={14} className="text-oe-blue" />
        <h3 className="text-sm font-semibold text-foreground">
          {t('dwg_takeoff.scale_title', { defaultValue: 'Drawing scale' })}
        </h3>
      </div>

      {/* DXF native unit + effective multiplier — lets the user see why
          measurements read the way they do. "unitless" DXFs are assumed
          to be in metres (historical default). */}
      <div
        className={clsx(
          'flex items-center justify-between rounded-md border px-2.5 py-1.5 text-[11px]',
          unitKnown
            ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300'
            : 'border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300',
        )}
        data-testid="dwg-scale-unit-info"
      >
        <span className="font-medium">
          {t('dwg_takeoff.dxf_units', { defaultValue: 'DXF units' })}:{' '}
          <span className="font-mono">{unitLabel || 'unitless'}</span>
        </span>
        <span className="font-mono">
          × {effectiveScale.toPrecision(4)}
        </span>
      </div>

      {/* Mode picker — 3 strategies */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-content-tertiary">
          {t('dwg_takeoff.scale_mode_label', { defaultValue: 'Scale mode' })}
        </span>
        <div className="flex gap-1.5">
          <ModeButton
            id="preset"
            label={t('dwg_takeoff.scale_mode_preset', { defaultValue: 'Preset ratio' })}
            hint={t('dwg_takeoff.scale_mode_preset_hint', { defaultValue: '1:50, 1:100 or custom' })}
          />
          <ModeButton
            id="calibrated"
            label={t('dwg_takeoff.scale_mode_calibrated', { defaultValue: 'Calibrate' })}
            hint={t('dwg_takeoff.scale_mode_calibrated_hint', { defaultValue: 'Two points + known distance' })}
          />
          <ModeButton
            id="per_annotation"
            label={t('dwg_takeoff.scale_mode_per_annotation', { defaultValue: 'Per-annotation' })}
            hint={t('dwg_takeoff.scale_mode_per_annotation_hint', { defaultValue: 'Detail views on same sheet' })}
          />
        </div>
      </div>

      {/* ── Mode: Preset ──────────────────────────────────────────────── */}
      {mode === 'preset' && (
        <>
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            {t('dwg_takeoff.scale_explainer', {
              defaultValue:
                'Raw DXF units are treated as metres. A scale of 1:50 divides displayed measurements so a 50-metre raw span reads as 1 metre.',
            })}
          </p>

          <div className="flex flex-col gap-1.5">
            {SCALE_PRESETS.map((p) => {
              const checked = !customMode && drawingScale === p.value;
              return (
                <label
                  key={p.value}
                  className={clsx(
                    'flex items-center gap-2 rounded-md border px-2.5 py-1.5 cursor-pointer text-xs transition-colors',
                    checked
                      ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                      : 'border-border bg-surface-secondary text-content-primary hover:bg-surface-tertiary',
                  )}
                >
                  <input
                    type="radio"
                    name="dwg-scale-preset"
                    value={p.value}
                    checked={checked}
                    onChange={() => handlePickPreset(p.value)}
                    className="accent-oe-blue"
                    data-testid={`dwg-scale-preset-${p.value}`}
                  />
                  <span className="font-mono font-semibold">{p.label}</span>
                </label>
              );
            })}

            <label
              className={clsx(
                'flex items-center gap-2 rounded-md border px-2.5 py-1.5 cursor-pointer text-xs transition-colors',
                customMode
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border bg-surface-secondary text-content-primary hover:bg-surface-tertiary',
              )}
            >
              <input
                type="radio"
                name="dwg-scale-preset"
                checked={customMode}
                onChange={handlePickCustom}
                className="accent-oe-blue"
                data-testid="dwg-scale-preset-custom"
              />
              <span className="font-mono font-semibold shrink-0">
                {t('dwg_takeoff.scale_custom', { defaultValue: 'Custom 1:' })}
              </span>
              {customMode && (
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={customInput}
                  onChange={(e) => handleCustomChange(e.target.value)}
                  className="w-20 ml-auto px-1.5 py-0.5 text-xs font-mono rounded border border-border bg-surface-primary text-foreground focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  data-testid="dwg-scale-custom-input"
                  aria-label={t('dwg_takeoff.scale_input_aria', {
                    defaultValue: 'Drawing scale denominator',
                  })}
                />
              )}
            </label>
          </div>

          <div className="rounded-md border border-border bg-surface-secondary px-2.5 py-2 text-[11px] text-muted-foreground leading-relaxed">
            {t('dwg_takeoff.scale_example', {
              defaultValue:
                'Example: if the drawing shows a 10 m wall at 1:100, set scale to 1:100 and the wall will report as 10 m on the canvas.',
            })}
          </div>
        </>
      )}

      {/* ── Mode: Calibrate ───────────────────────────────────────────── */}
      {mode === 'calibrated' && (
        <div className="flex flex-col gap-3">
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            {t('dwg_takeoff.scale_calibrate_explainer', {
              defaultValue:
                'Click a Distance measurement on the drawing between two points whose real length you know. Type the real length below, then press Apply - the scale is computed automatically.',
            })}
          </p>

          <div className="rounded-md border border-border bg-surface-secondary px-3 py-2.5 text-[11px] flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-content-tertiary uppercase tracking-wider text-[9px] font-semibold">
                {t('dwg_takeoff.scale_calibrate_measured', { defaultValue: 'Measured (raw)' })}
              </span>
              <span className="font-mono font-semibold text-content-primary tabular-nums">
                {calibrationPixels !== null
                  ? calibrationPixels.toFixed(3)
                  : t('dwg_takeoff.scale_calibrate_none', { defaultValue: '—' })}
              </span>
            </div>
            {!isCalibrating ? (
              <button
                type="button"
                onClick={onStartCalibration}
                className="inline-flex items-center justify-center gap-1.5 h-7 rounded-md text-[11px] font-semibold text-white bg-oe-blue hover:bg-oe-blue-dark transition-colors"
              >
                <Ruler size={11} />
                {calibrationPixels !== null
                  ? t('dwg_takeoff.scale_calibrate_repick', { defaultValue: 'Pick two points again' })
                  : t('dwg_takeoff.scale_calibrate_pick', { defaultValue: 'Pick two points on drawing' })}
              </button>
            ) : (
              <button
                type="button"
                onClick={onCancelCalibration}
                className="inline-flex items-center justify-center gap-1.5 h-7 rounded-md text-[11px] font-semibold text-content-primary bg-surface-tertiary hover:bg-surface-primary transition-colors"
              >
                {t('dwg_takeoff.scale_calibrate_cancel', { defaultValue: 'Cancel - click two points on the drawing' })}
              </button>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-[9px] font-semibold uppercase tracking-wider text-content-tertiary">
              {t('dwg_takeoff.scale_calibrate_real_label', { defaultValue: 'Real-world distance' })}
            </span>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                step="any"
                value={realDistance}
                onChange={(e) => setRealDistance(e.target.value)}
                placeholder="5.00"
                className="flex-1 px-2 py-1 text-xs font-mono rounded border border-border bg-surface-primary text-foreground focus:outline-none focus:ring-1 focus:ring-oe-blue"
                data-testid="dwg-scale-calibrate-distance"
              />
              <select
                value={realUnit}
                onChange={(e) => setRealUnit(e.target.value as typeof realUnit)}
                className="px-2 py-1 text-xs rounded border border-border bg-surface-primary text-foreground focus:outline-none focus:ring-1 focus:ring-oe-blue"
                data-testid="dwg-scale-calibrate-unit"
              >
                <option value="m">m</option>
                <option value="cm">cm</option>
                <option value="mm">mm</option>
              </select>
            </div>
            <button
              type="button"
              onClick={applyCalibration}
              disabled={!calibrationPixels || !Number(realDistance)}
              className="mt-1 inline-flex items-center justify-center gap-1.5 h-8 rounded-md text-[11px] font-semibold text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              data-testid="dwg-scale-calibrate-apply"
            >
              {t('dwg_takeoff.scale_calibrate_apply', { defaultValue: 'Apply calibration' })}
            </button>
          </div>
        </div>
      )}

      {/* ── Mode: Per-annotation ──────────────────────────────────────── */}
      {mode === 'per_annotation' && (
        <div className="flex flex-col gap-3">
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            {t('dwg_takeoff.scale_per_annotation_explainer', {
              defaultValue:
                'Use when one sheet mixes scales (e.g. a 1:100 plan with a 1:20 detail window). Every new annotation you draw carries the scale below until you change it - older annotations keep their own stored scale.',
            })}
          </p>

          <label className="flex items-center gap-2 rounded-md border border-oe-blue/40 bg-oe-blue/5 px-3 py-2 text-[11px]">
            <span className="font-mono font-semibold shrink-0 text-oe-blue">
              {t('dwg_takeoff.scale_active_override', { defaultValue: 'New annotation scale 1:' })}
            </span>
            <input
              type="number"
              min={1}
              step={1}
              value={customInput || String(drawingScale)}
              onChange={(e) => handleCustomChange(e.target.value)}
              className="w-24 ml-auto px-1.5 py-0.5 text-xs font-mono rounded border border-border bg-surface-primary text-foreground focus:outline-none focus:ring-1 focus:ring-oe-blue"
              data-testid="dwg-scale-per-annotation-input"
            />
          </label>

          <div className="rounded-md border border-border bg-surface-secondary px-2.5 py-2 text-[11px] text-muted-foreground leading-relaxed">
            {t('dwg_takeoff.scale_per_annotation_note', {
              defaultValue:
                'Tip: switch back to Preset mode once the detail takeoff is done so the default scale applies to the rest of the sheet again.',
            })}
          </div>
        </div>
      )}

      <div className="text-[10px] text-content-tertiary tabular-nums">
        {t('dwg_takeoff.scale_current', {
          defaultValue: 'Current: 1:{{n}}',
          n: drawingScale,
        })}
      </div>
    </div>
  );
}

interface SummaryTabProps {
  entityCount: number;
  aggregate: { area: number; perimeter: number; length: number; count: number };
  layerQuantities: LayerQuantity[];
  byType: { type: string; count: number }[];
  byBlock: { name: string; count: number }[];
  countTotal: number;
  onExportCsv: () => void;
  onExportExcel: () => void;
  onExportPdf: () => void;
}

/**
 * Summary tab (R3 #12) — KPI cards + per-layer breakdown + per-type breakdown.
 *
 * Data comes straight from ``aggregateEntities`` + the layer/type memos in
 * the parent. The per-layer "share" bar uses the maximum of area or
 * length across layers so both kinds of geometry render meaningfully
 * (an all-lines drawing still gets a bar, not a flatline).
 */
function SummaryTab({
  entityCount,
  aggregate,
  layerQuantities,
  byType,
  byBlock,
  countTotal,
  onExportCsv,
  onExportExcel,
  onExportPdf,
}: SummaryTabProps) {
  const { t } = useTranslation();

  // Per-layer override of the auto-selected headline measure. The user can,
  // e.g., switch a layer from "area" to "length" when they want the running
  // length of a slab edge instead of its face area.
  const [layerMeasure, setLayerMeasure] = useState<Record<string, QuantifyMeasure>>({});

  // Largest headline quantity per measure band, used to scale the share bars
  // so area layers compare against area layers and length against length
  // (mixing m² and m on one bar would be meaningless).
  const maxByMeasure = useMemo(() => {
    const m: Record<QuantifyMeasure, number> = { area: 0, length: 0, count: 0 };
    for (const row of layerQuantities) {
      const measure = layerMeasure[row.layer] ?? row.primary;
      const v = quantityFor(row, measure);
      if (v > m[measure]) m[measure] = v;
    }
    return m;
  }, [layerQuantities, layerMeasure]);

  // Grand totals across all visible layers, shown as the headline strip.
  const quantifyTotals = useMemo(() => {
    let area = 0;
    let length = 0;
    let count = 0;
    for (const row of layerQuantities) {
      area += row.area;
      length += row.length;
      count += row.count;
    }
    return {
      area: Math.round(area * 100) / 100,
      length: Math.round(length * 100) / 100,
      count,
    };
  }, [layerQuantities]);

  if (entityCount === 0) {
    return (
      <p className="text-xs text-muted-foreground py-4 text-center">
        {t('dwg_takeoff.summary_empty', {
          defaultValue: 'No entities to summarize. Upload a drawing to see totals.',
        })}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="dwg-summary-tab">
      {/* Header + export */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 pt-0.5">
          <BarChart3 size={14} className="text-oe-blue shrink-0" />
          <h3 className="text-sm font-semibold text-foreground">
            {t('dwg_takeoff.summary_title', { defaultValue: 'Measurements Summary' })}
          </h3>
        </div>
        <div className="flex flex-wrap justify-end gap-1 shrink-0">
          {/* Excel leads — it is the natural home for the quantity takeoff. */}
          <button
            type="button"
            onClick={onExportExcel}
            className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-600 dark:text-emerald-300 hover:bg-emerald-500/20 transition-colors"
            data-testid="dwg-summary-export-excel"
            title={t('dwg_takeoff.export_excel', {
              defaultValue: 'Export quantities as Excel (.xlsx)',
            })}
          >
            <Download size={11} />
            {t('dwg_takeoff.export_excel_short', { defaultValue: 'Excel' })}
          </button>
          <button
            type="button"
            onClick={onExportCsv}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-secondary px-2 py-1 text-[10px] font-medium text-content-secondary hover:text-content-primary hover:bg-surface-tertiary transition-colors"
            data-testid="dwg-summary-export"
            title={t('dwg_takeoff.export_csv', {
              defaultValue: 'Export measurements as CSV',
            })}
          >
            <Download size={11} />
            {t('dwg_takeoff.export_csv_short', { defaultValue: 'CSV' })}
          </button>
          <button
            type="button"
            onClick={onExportPdf}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-secondary px-2 py-1 text-[10px] font-medium text-content-secondary hover:text-content-primary hover:bg-surface-tertiary transition-colors"
            data-testid="dwg-summary-export-pdf"
            title={t('dwg_takeoff.export_pdf', {
              defaultValue: 'Export current viewport as PDF',
            })}
          >
            <Download size={11} />
            {t('dwg_takeoff.export_pdf_short', { defaultValue: 'PDF' })}
          </button>
        </div>
      </div>

      {/* KPI cards */}
      <div
        className="grid grid-cols-2 gap-2"
        data-testid="dwg-summary-kpis"
      >
        <SummaryKpiCard
          label={t('dwg_takeoff.kpi_total_entities', { defaultValue: 'Total entities' })}
          value={entityCount.toLocaleString()}
          accent="blue"
        />
        <SummaryKpiCard
          label={t('dwg_takeoff.kpi_total_area', { defaultValue: 'Σ Area' })}
          value={aggregate.area > 0 ? aggregate.area.toFixed(2) : '—'}
          unit={aggregate.area > 0 ? 'm²' : undefined}
          accent="emerald"
        />
        <SummaryKpiCard
          label={t('dwg_takeoff.kpi_total_perimeter', { defaultValue: 'Σ Perimeter' })}
          value={aggregate.perimeter > 0 ? aggregate.perimeter.toFixed(2) : '—'}
          unit={aggregate.perimeter > 0 ? 'm' : undefined}
          accent="amber"
        />
        <SummaryKpiCard
          label={t('dwg_takeoff.kpi_total_length', { defaultValue: 'Σ Length' })}
          value={aggregate.length > 0 ? aggregate.length.toFixed(2) : '—'}
          unit={aggregate.length > 0 ? 'm' : undefined}
          accent="violet"
        />
      </div>

      {/* Manual count total (count tool markers) */}
      <div
        className="flex items-center justify-between rounded-lg border border-border-light bg-surface-secondary/50 px-2.5 py-2"
        data-testid="dwg-summary-count-total"
      >
        <div className="flex items-center gap-1.5">
          <Hash size={12} className="text-content-tertiary" />
          <span className="text-[11px] font-medium text-content-secondary">
            {t('dwg_takeoff.summary_count_items', { defaultValue: 'Count items' })}
          </span>
        </div>
        <span className="text-sm font-bold tabular-nums text-content-primary">
          {countTotal.toLocaleString()}
        </span>
      </div>

      {/* Auto-quantify by layer — DWG's signature edge over PDF takeoff: real
          quantities measured straight from the vectors, no manual tracing.
          Each layer gets a headline measure (area > length > count) the user
          can override per layer. */}
      <div data-testid="dwg-summary-by-layer">
        <div className="flex items-center gap-1.5 mb-0.5">
          <Zap size={12} className="text-amber-400" />
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-content-secondary">
            {t('dwg_takeoff.quantify_title', { defaultValue: 'Auto-quantify by layer' })}
          </h4>
          <span className="text-[10px] text-content-quaternary tabular-nums">
            ({layerQuantities.length})
          </span>
        </div>
        <p className="text-[10px] text-content-tertiary mb-1.5 leading-snug">
          {t('dwg_takeoff.quantify_subtitle', {
            defaultValue: 'Measured straight from the drawing vectors - no manual tracing.',
          })}
        </p>

        {/* Grand totals strip */}
        <div className="grid grid-cols-3 gap-1 mb-2" data-testid="dwg-quantify-totals">
          <div className="rounded-md bg-emerald-500/10 border border-emerald-500/20 px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wide text-emerald-500/80">
              {t('dwg_takeoff.area', 'Area')}
            </div>
            <div className="text-[11px] font-bold tabular-nums text-emerald-300">
              {quantifyTotals.area > 0
                ? quantifyTotals.area.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : '-'}
              <span className="text-[9px] font-medium opacity-70"> m²</span>
            </div>
          </div>
          <div className="rounded-md bg-violet-500/10 border border-violet-500/20 px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wide text-violet-400/80">
              {t('dwg_takeoff.length', 'Length')}
            </div>
            <div className="text-[11px] font-bold tabular-nums text-violet-300">
              {quantifyTotals.length > 0
                ? quantifyTotals.length.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : '-'}
              <span className="text-[9px] font-medium opacity-70"> m</span>
            </div>
          </div>
          <div className="rounded-md bg-sky-500/10 border border-sky-500/20 px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wide text-sky-400/80">
              {t('dwg_takeoff.count', 'Count')}
            </div>
            <div className="text-[11px] font-bold tabular-nums text-sky-300">
              {quantifyTotals.count.toLocaleString()}
              <span className="text-[9px] font-medium opacity-70"> nr</span>
            </div>
          </div>
        </div>

        {/* Per-layer rows */}
        <div className="space-y-1 max-h-72 overflow-y-auto pr-1">
          {layerQuantities.slice(0, 30).map((row) => {
            const measure = layerMeasure[row.layer] ?? row.primary;
            const quantity = quantityFor(row, measure);
            const unit = unitForMeasure(measure);
            const max = maxByMeasure[measure] || 0;
            const share = max > 0 ? (quantity / max) * 100 : 0;
            const barColor =
              measure === 'area'
                ? 'from-emerald-500 to-emerald-400'
                : measure === 'length'
                  ? 'from-violet-500 to-violet-400'
                  : 'from-sky-500 to-sky-400';
            return (
              <div
                key={row.layer}
                className="rounded-md border border-border-light bg-surface-secondary/50 px-2 py-1.5 hover:bg-surface-secondary transition-colors"
                data-testid="dwg-quantify-row"
                data-layer={row.layer}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span
                    className="font-mono text-[11px] text-content-primary truncate"
                    title={row.layer}
                  >
                    {row.layer}
                  </span>
                  <span className="text-[9px] tabular-nums text-content-tertiary shrink-0">
                    {row.count} {t('dwg_takeoff.quantify_entities_short', { defaultValue: 'ent.' })}
                  </span>
                </div>
                <div className="relative h-1 rounded-full bg-surface-tertiary overflow-hidden mb-1">
                  <div
                    className={clsx('absolute inset-y-0 left-0 bg-gradient-to-r', barColor)}
                    style={{ width: `${Math.max(share, 3)}%` }}
                  />
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="text-[13px] font-bold tabular-nums text-content-primary"
                    data-testid="dwg-quantify-value"
                  >
                    {quantity.toLocaleString(undefined, {
                      maximumFractionDigits: measure === 'count' ? 0 : 2,
                    })}
                    <span className="text-[10px] font-medium text-content-tertiary"> {unit}</span>
                  </span>
                  {/* Measure toggle — only the measures this layer actually has. */}
                  {row.available.length > 1 && (
                    <div className="inline-flex rounded-md bg-surface-tertiary p-0.5">
                      {row.available.map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={() =>
                            setLayerMeasure((prev) => ({ ...prev, [row.layer]: m }))
                          }
                          className={clsx(
                            'px-1.5 py-0.5 rounded text-[9px] font-semibold transition-colors',
                            measure === m
                              ? 'bg-surface-primary text-content-primary shadow-xs'
                              : 'text-content-tertiary hover:text-content-primary',
                          )}
                          title={t('dwg_takeoff.quantify_switch_measure', {
                            defaultValue: 'Show {{measure}}',
                            measure: m,
                          })}
                        >
                          {unitForMeasure(m)}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          {layerQuantities.length > 30 && (
            <p className="text-[10px] text-content-tertiary text-center py-1">
              {t('dwg_takeoff.summary_layers_more', {
                defaultValue: '+{{count}} more',
                count: layerQuantities.length - 30,
              })}
            </p>
          )}
        </div>
      </div>

      {/* By Type */}
      <div data-testid="dwg-summary-by-type">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Sigma size={11} className="text-content-tertiary" />
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('dwg_takeoff.summary_by_type', { defaultValue: 'By entity type' })}
          </h4>
          <span className="text-[10px] text-content-quaternary tabular-nums">
            ({byType.length})
          </span>
        </div>
        <div className="grid grid-cols-2 gap-1">
          {byType.map((row) => (
            <div
              key={row.type}
              className="flex items-center justify-between rounded-md border border-border-light bg-surface-secondary/50 px-2 py-1 text-[10px]"
            >
              <span className="font-mono text-content-primary truncate">
                {row.type}
              </span>
              <span className="tabular-nums font-semibold text-content-secondary">
                {row.count}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* By Block: INSERT entity rollup grouped by block name. Hidden when
          the drawing has no block references. */}
      {byBlock.length > 0 && (
        <div data-testid="dwg-summary-by-block">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Hash size={11} className="text-content-tertiary" />
            <h4 className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
              {t('dwg_takeoff.summary_by_block', { defaultValue: 'Count by block' })}
            </h4>
            <span className="text-[10px] text-content-quaternary tabular-nums">
              ({byBlock.length})
            </span>
          </div>
          <div className="grid grid-cols-2 gap-1">
            {byBlock.map((row) => (
              <div
                key={row.name}
                className="flex items-center justify-between rounded-md border border-border-light bg-surface-secondary/50 px-2 py-1 text-[10px]"
              >
                <span className="font-mono text-content-primary truncate">
                  {row.name}
                </span>
                <span className="tabular-nums font-semibold text-content-secondary">
                  {row.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Right-click context menu for DWG entities (RFC 11 §4.4 + R4 #14 cross-module links). */
function DwgContextMenu({
  screenX,
  screenY,
  selectionSize,
  onHide,
  onIsolate,
  onLink,
  onSaveAsGroup,
  onCreateTask,
  onLinkSchedule,
  onLinkDocument,
  onLinkRequirement,
  onClose,
}: {
  screenX: number;
  screenY: number;
  selectionSize: number;
  onHide: () => void;
  onIsolate: () => void;
  onLink: () => void;
  onSaveAsGroup: () => void;
  onCreateTask: () => void;
  onLinkSchedule: () => void;
  onLinkDocument: () => void;
  onLinkRequirement: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const menu = document.getElementById('dwg-context-menu');
      if (menu && !menu.contains(e.target as Node)) onClose();
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div
      id="dwg-context-menu"
      data-testid="dwg-context-menu"
      className="absolute z-40 min-w-[180px] rounded-lg border border-white/15 bg-[#1e1e38]/95 shadow-2xl backdrop-blur-md py-1"
      style={{ left: screenX, top: screenY }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <MenuItem onClick={onHide} icon={<EyeOff size={12} />} label={
        selectionSize > 1
          ? t('dwg_takeoff.hide_n', { defaultValue: 'Hide {{count}}', count: selectionSize })
          : t('dwg_takeoff.hide', { defaultValue: 'Hide' })
      } />
      <MenuItem onClick={onIsolate} icon={<Eye size={12} />} label={
        t('dwg_takeoff.isolate', { defaultValue: 'Isolate' })
      } />
      <div className="my-1 border-t border-white/10" />
      <MenuItem onClick={onLink} icon={<Link2 size={12} />} label={
        selectionSize > 1
          ? t('dwg_takeoff.link_n_to_boq', {
              defaultValue: 'Link {{count}} to BOQ',
              count: selectionSize,
            })
          : t('dwg_takeoff.link_to_boq', { defaultValue: 'Link to BOQ' })
      } />
      {selectionSize > 1 && (
        <MenuItem onClick={onSaveAsGroup} icon={<FolderPlus size={12} />} label={
          t('dwg_takeoff.save_as_group', { defaultValue: 'Save as group' })
        } />
      )}
      <div className="my-1 border-t border-white/10" />
      <MenuItem onClick={onCreateTask} icon={<CheckSquare size={12} />} label={
        t('dwg_takeoff.create_task', { defaultValue: 'Create task' })
      } />
      <MenuItem onClick={onLinkSchedule} icon={<CalendarDays size={12} />} label={
        t('dwg_takeoff.link_schedule', { defaultValue: 'Link to schedule' })
      } />
      <MenuItem onClick={onLinkDocument} icon={<FileText size={12} />} label={
        t('dwg_takeoff.link_document', { defaultValue: 'Link to document' })
      } />
      <MenuItem onClick={onLinkRequirement} icon={<ClipboardCheck size={12} />} label={
        t('dwg_takeoff.link_requirement', { defaultValue: 'Link to requirement' })
      } />
    </div>
  );
}

function MenuItem({
  onClick,
  icon,
  label,
}: {
  onClick: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 w-full px-3 py-1.5 text-left text-[11px] text-white/85 hover:bg-white/10 transition-colors"
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

/**
 * Inline upload progress pill — surfaces the first active DWG upload from
 * the global store under the entities loader, so users get a parallel
 * signal that processing is running (not only the corner dock).
 */
function UploadProgressInline() {
  const { t } = useTranslation();
  const jobs = useDwgUploadStore((s) => s.jobs);
  const active = useMemo(() => {
    for (const job of jobs.values()) {
      if (job.status === 'uploading' || job.status === 'converting') return job;
    }
    return null;
  }, [jobs]);

  if (!active) return null;

  return (
    <div
      data-testid="dwg-loader-upload-progress"
      className="w-full rounded-xl border border-oe-blue/25 bg-oe-blue/5 px-4 py-3 space-y-2"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Upload size={12} className="text-oe-blue shrink-0" />
          <span className="text-[11px] font-semibold text-content-primary truncate">
            {active.fileName}
          </span>
        </div>
        <span className="text-[11px] font-semibold text-oe-blue tabular-nums shrink-0">
          {active.progress}%
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-tertiary overflow-hidden">
        <div
          className="h-full rounded-full bg-oe-blue transition-all duration-300"
          style={{ width: `${active.progress}%` }}
        />
      </div>
      <p className="text-[10px] text-content-tertiary">
        {t(active.stage, { defaultValue: 'Processing upload…' })}
      </p>
    </div>
  );
}

/* ── Conversion progress / error / empty cards ──────────────────────────
 *
 * These render in place of the DxfViewer when the selected drawing has
 * not yet reached `status="ready"`. Before P1 the page silently rendered
 * an empty viewer for the entire 3-8 minute DDC conversion window — the
 * user reported it as "показывает что проект загружен — но ничего не
 * показывается и только потом через 5 минут происходит загрузка".
 *
 * ConversionProgressCard intentionally does NOT show a determinate
 * percentage. The DDC pipeline does not expose granular progress, and a
 * fake percentage that climbs to 95% and sits there for minutes is worse
 * than honest indeterminate motion + a step list + a live elapsed-time
 * counter.
 *
 * Cancel: the backend has no "abort conversion" endpoint (the asyncio
 * task runs DwgExporter to completion), so "Cancel" here actually means
 * "delete this drawing row" — the conversion continues server-side but
 * the user gets back to the upload flow immediately. This matches user
 * intent ("I changed my mind, get me out of here") without pretending
 * to kill a subprocess we don't control. */
function ConversionProgressCard({
  drawingName,
  filename,
  status,
  startedAt,
  onCancel,
}: {
  drawingName: string;
  filename: string;
  status: string | null;
  startedAt: number;
  onCancel?: () => void;
}) {
  const { t } = useTranslation();
  const [, force] = useState(0);

  // Refresh once a second so the elapsed-time pill stays honest.
  useEffect(() => {
    const iv = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(iv);
  }, []);

  const elapsedSec = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
  const elapsedLabel =
    elapsedSec < 60
      ? `${elapsedSec}s`
      : `${Math.floor(elapsedSec / 60)}m ${elapsedSec % 60}s`;

  // Step machine — drives the highlighted "current step". When the
  // backend says `uploaded` the file is on disk but conversion has not
  // started yet (step 1). `processing` covers steps 2 and 3 — we can't
  // distinguish them from the API, so step 2 is "current" until the
  // status flips out of processing.
  const currentStep = status === 'uploaded' ? 1 : status === 'processing' ? 2 : 4;

  const steps: { id: number; label: string; hint: string }[] = [
    {
      id: 1,
      label: t('dwg_takeoff.conv_step_upload', { defaultValue: 'Upload received' }),
      hint: t('dwg_takeoff.conv_step_upload_hint', {
        defaultValue: 'File saved on the server.',
      }),
    },
    {
      id: 2,
      label: t('dwg_takeoff.conv_step_convert', {
        defaultValue: 'Converting DWG to canonical JSON',
      }),
      hint: t('dwg_takeoff.conv_step_convert_hint', {
        defaultValue:
          'DDC cad2data is parsing your drawing. This is the slow step - usually 3-8 minutes for a medium DWG, longer for large architectural sets.',
      }),
    },
    {
      id: 3,
      label: t('dwg_takeoff.conv_step_extract', {
        defaultValue: 'Extracting entities and layers',
      }),
      hint: t('dwg_takeoff.conv_step_extract_hint', {
        defaultValue: 'Building the entity list the viewer will render.',
      }),
    },
    {
      id: 4,
      label: t('dwg_takeoff.conv_step_render', { defaultValue: 'Opening the viewer' }),
      hint: t('dwg_takeoff.conv_step_render_hint', {
        defaultValue: 'You will see the drawing here as soon as the entities arrive.',
      }),
    },
  ];

  // Live-region announcement: changes whenever the backend status flips
  // (uploaded → processing → ready/error). Screen readers hear "Converting
  // your drawing…" / "Step 2 of 4 — extracting entities" etc., instead of
  // silently rendering a spinner. Kept terse so it doesn't drone on.
  const liveAnnouncement = t('dwg_takeoff.conv_aria_live', {
    defaultValue: 'Converting {{name}}, step {{step}} of 4, {{elapsed}} elapsed',
    name: drawingName || filename,
    step: currentStep,
    elapsed: elapsedLabel,
  });

  return (
    <div className="flex flex-1 items-center justify-center overflow-y-auto p-6">
      <div
        data-testid="dwg-conversion-progress-card"
        className="w-full max-w-xl rounded-2xl border border-border-light bg-surface-elevated p-6 shadow-xl"
        role="status"
        aria-live="polite"
      >
        <span className="sr-only">{liveAnnouncement}</span>
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-oe-blue/10 border border-oe-blue/20 flex items-center justify-center shrink-0">
            <Loader2 size={20} className="text-oe-blue animate-spin" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-content-primary leading-tight">
              {t('dwg_takeoff.conv_title', { defaultValue: 'Converting your drawing…' })}
            </h2>
            <p className="text-xs text-content-tertiary mt-1 truncate" title={filename}>
              {drawingName || filename}
            </p>
          </div>
          <span
            className="text-[11px] font-semibold tabular-nums text-content-secondary bg-surface-secondary px-2 py-1 rounded-md shrink-0"
            aria-label={t('dwg_takeoff.conv_elapsed', { defaultValue: 'Elapsed time' })}
          >
            {elapsedLabel}
          </span>
        </div>

        {/* Indeterminate progress bar — honest motion without a fake %.
            role="progressbar" with no aria-valuenow signals
            "indeterminate" to assistive tech (per ARIA 1.2). */}
        <div
          className="mt-5 h-1.5 rounded-full bg-surface-tertiary overflow-hidden relative"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={t('dwg_takeoff.conv_progress_label', {
            defaultValue: 'Conversion progress (indeterminate)',
          })}
        >
          <div
            className="absolute inset-y-0 w-1/3 rounded-full bg-oe-blue"
            style={{
              animation: 'oe-dwg-indeterminate 1.6s ease-in-out infinite',
            }}
          />
        </div>
        <style>{`
          @keyframes oe-dwg-indeterminate {
            0%   { left: -33%; }
            50%  { left: 50%; }
            100% { left: 110%; }
          }
        `}</style>

        {/* Step list — one row per pipeline phase, current step highlighted. */}
        <ol className="mt-5 space-y-2">
          {steps.map((step) => {
            const isDone = step.id < currentStep;
            const isCurrent = step.id === currentStep;
            return (
              <li
                key={step.id}
                className={clsx(
                  'flex items-start gap-3 rounded-lg px-3 py-2 transition-colors',
                  isCurrent && 'bg-oe-blue/5 border border-oe-blue/20',
                  !isCurrent && 'border border-transparent',
                )}
              >
                <div
                  className={clsx(
                    'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
                    isDone && 'bg-emerald-500/15 text-emerald-500',
                    isCurrent && 'bg-oe-blue/15 text-oe-blue',
                    !isDone && !isCurrent && 'bg-surface-secondary text-content-quaternary',
                  )}
                >
                  {isDone ? '✓' : step.id}
                </div>
                <div className="min-w-0 flex-1">
                  <p
                    className={clsx(
                      'text-xs font-medium leading-tight',
                      isCurrent ? 'text-content-primary' : 'text-content-secondary',
                    )}
                  >
                    {step.label}
                    {isCurrent && (
                      <Loader2
                        size={11}
                        className="inline-block ml-1.5 text-oe-blue animate-spin align-[-1px]"
                      />
                    )}
                  </p>
                  {isCurrent && (
                    <p className="text-[11px] text-content-tertiary leading-snug mt-0.5">
                      {step.hint}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>

        <div className="mt-5 rounded-lg bg-amber-500/5 border border-amber-500/20 px-3 py-2.5 text-[11px] text-amber-700 dark:text-amber-300 leading-relaxed">
          {t('dwg_takeoff.conv_note', {
            defaultValue:
              'You can safely navigate to other pages - conversion runs on the server. The drawing will be ready here when you come back.',
          })}
        </div>

        {/* Cancel — only when the parent wired a handler. Note that this
            removes the drawing row but does NOT abort the backend
            asyncio task (no API for that); the microcopy is explicit. */}
        {onCancel && (
          <div className="mt-4 flex items-center justify-end">
            <button
              type="button"
              onClick={onCancel}
              data-testid="dwg-conversion-cancel"
              className="text-[11px] font-medium text-content-tertiary hover:text-red-500 transition-colors underline-offset-2 hover:underline"
            >
              {t('dwg_takeoff.conv_cancel', {
                defaultValue: 'Cancel - remove this drawing',
              })}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Sub-component: one-click DWG converter installer.
 *
 * Mounted by ConversionErrorCard when the backend signals "converter
 * missing" via the stable substring `DDC DwgExporter`. Calls the same
 * `POST /v1/takeoff/converters/dwg/install/` that /settings → Converters
 * uses, with a live progress bar (downloads ~150 MB of Qt6 DLLs on
 * Windows; Linux is unsupported and the response carries the apt-get
 * commands the user has to run themselves).
 *
 * On successful install, the file the user already uploaded is
 * pre-processed via `onInstalled` (delete-and-reupload, matching the
 * existing Retry semantics — backend has no re-convert endpoint).
 */
function InstallDwgConverterCTA({
  onInstalled,
}: {
  onInstalled?: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [unsupportedMessage, setUnsupportedMessage] = useState<string | null>(null);

  const installMutation = useMutation({
    mutationFn: () => installBIMConverter('dwg'),
    onSuccess: (result) => {
      if (result.installed) {
        addToast({
          type: 'success',
          title: t('dwg_takeoff.conv_install_ok_title', {
            defaultValue: 'DWG converter installed',
          }),
          message: t('dwg_takeoff.conv_install_ok_message', {
            defaultValue: 'Re-uploading your drawing now.',
          }),
        });
        onInstalled?.();
      } else if (result.platform_unsupported) {
        setUnsupportedMessage(
          result.message ||
            t('dwg_takeoff.conv_install_unsupported', {
              defaultValue:
                'Automated install is only available on Windows. On Linux, install the DDC DwgExporter manually.',
            }),
        );
      } else {
        addToast({
          type: 'error',
          title: t('dwg_takeoff.conv_install_failed', {
            defaultValue: 'Install failed',
          }),
          message: result.message,
        });
      }
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('dwg_takeoff.conv_install_failed', {
          defaultValue: 'Install failed',
        }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  if (unsupportedMessage) {
    return (
      <div className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] text-amber-700 dark:text-amber-200">
        <p>{unsupportedMessage}</p>
        <a
          href="/settings?tab=converters"
          className="mt-2 inline-flex items-center gap-1 text-amber-700 dark:text-amber-200 underline hover:no-underline"
        >
          {t('dwg_takeoff.conv_open_settings', {
            defaultValue: 'Open Converters settings →',
          })}
        </a>
      </div>
    );
  }

  if (installMutation.isPending) {
    return (
      <div className="mt-4">
        <ConverterInstallProgressBar
          converterId="dwg"
          installing={true}
          sizeMb={150}
        />
      </div>
    );
  }

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => installMutation.mutate()}
        data-testid="dwg-install-converter-cta"
        className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 text-white text-[11px] font-semibold px-3 py-1.5 hover:bg-emerald-700 transition-colors"
      >
        <Download size={12} />
        {t('dwg_takeoff.conv_install_cta', {
          defaultValue: 'Install DWG converter (1 click)',
        })}
      </button>
      <p className="mt-1.5 text-[10px] text-content-tertiary">
        {t('dwg_takeoff.conv_install_hint', {
          defaultValue:
            'Downloads ~150 MB to ~/.openestimator/converters/ - Windows only. Takes 30-90 seconds.',
        })}
      </p>
    </div>
  );
}

function ConversionErrorCard({
  drawingName,
  message,
  onRetry,
  onDelete,
}: {
  drawingName: string;
  message: string | null;
  onRetry?: () => void;
  onDelete?: () => void;
}) {
  const { t } = useTranslation();
  // Stable marker emitted by `_handle_dwg` when `find_converter('dwg')`
  // returns None. Keeps the install CTA scoped — generic conversion
  // failures (wrong version, corrupt file) should still show the
  // "Retry / Delete" UX without an Install button that wouldn't help.
  const isMissingConverter = !!message && message.includes('DDC DwgExporter');
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div
        data-testid="dwg-conversion-error-card"
        className="w-full max-w-xl rounded-2xl border border-red-500/30 bg-red-500/5 p-6 shadow-xl"
        role="alert"
        aria-live="assertive"
      >
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-red-500/15 border border-red-500/30 flex items-center justify-center shrink-0">
            <X size={20} className="text-red-500" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-content-primary leading-tight">
              {isMissingConverter
                ? t('dwg_takeoff.conv_missing_title', {
                    defaultValue: 'DWG converter not installed',
                  })
                : t('dwg_takeoff.conv_error_title', { defaultValue: 'Conversion failed' })}
            </h2>
            <p className="text-xs text-content-tertiary mt-1 truncate" title={drawingName}>
              {drawingName}
            </p>
            <p className="text-xs text-content-secondary mt-3 leading-relaxed">
              {isMissingConverter
                ? t('dwg_takeoff.conv_missing_message', {
                    defaultValue:
                      'OpenConstructionERP needs the DDC DwgExporter to read DWG files. Install it once - works for every DWG you upload after.',
                  })
                : message ||
                  t('dwg_takeoff.conv_error_default', {
                    defaultValue:
                      'The server could not parse this file. Try re-saving as a newer DWG/DXF version or upload a different file.',
                  })}
            </p>
            {isMissingConverter && <InstallDwgConverterCTA onInstalled={onRetry} />}
            {(onRetry || onDelete) && (
              <div className="mt-4 flex items-center gap-2">
                {onRetry && (
                  <button
                    type="button"
                    onClick={onRetry}
                    data-testid="dwg-conversion-retry"
                    className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue text-white text-[11px] font-semibold px-3 py-1.5 hover:bg-oe-blue-dark transition-colors"
                  >
                    <RotateCcw size={12} />
                    {isMissingConverter
                      ? t('dwg_takeoff.conv_retry_after_install', {
                          defaultValue: 'Re-upload after install',
                        })
                      : t('dwg_takeoff.conv_retry', {
                          defaultValue: 'Retry - upload again',
                        })}
                  </button>
                )}
                {onDelete && (
                  <button
                    type="button"
                    onClick={onDelete}
                    data-testid="dwg-conversion-error-delete"
                    className="inline-flex items-center gap-1.5 rounded-md border border-red-500/30 text-red-500 text-[11px] font-medium px-3 py-1.5 hover:bg-red-500/10 transition-colors"
                  >
                    <Trash2 size={12} />
                    {t('dwg_takeoff.conv_delete', {
                      defaultValue: 'Delete drawing',
                    })}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ConversionEmptyCard({
  drawingName,
  message,
  onDelete,
  onUploadAnother,
}: {
  drawingName: string;
  message: string | null;
  onDelete?: () => void;
  onUploadAnother?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div
        data-testid="dwg-conversion-empty-card"
        className="w-full max-w-xl rounded-2xl border border-amber-500/30 bg-amber-500/5 p-6 shadow-xl"
        role="status"
        aria-live="polite"
      >
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center shrink-0">
            <Info size={20} className="text-amber-500" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-content-primary leading-tight">
              {t('dwg_takeoff.conv_empty_title', { defaultValue: 'No entities found' })}
            </h2>
            <p className="text-xs text-content-tertiary mt-1 truncate" title={drawingName}>
              {drawingName}
            </p>
            <p className="text-xs text-content-secondary mt-3 leading-relaxed">
              {message ||
                t('dwg_takeoff.conv_empty_default', {
                  defaultValue:
                    'This DWG/DXF parsed successfully but contains no drawable entities. The file may contain only metadata or be a template.',
                })}
            </p>
            {(onUploadAnother || onDelete) && (
              <div className="mt-4 flex items-center gap-2">
                {onUploadAnother && (
                  <button
                    type="button"
                    onClick={onUploadAnother}
                    data-testid="dwg-conversion-empty-upload"
                    className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue text-white text-[11px] font-semibold px-3 py-1.5 hover:bg-oe-blue-dark transition-colors"
                  >
                    <Upload size={12} />
                    {t('dwg_takeoff.conv_upload_another', {
                      defaultValue: 'Upload another drawing',
                    })}
                  </button>
                )}
                {onDelete && (
                  <button
                    type="button"
                    onClick={onDelete}
                    data-testid="dwg-conversion-empty-delete"
                    className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/30 text-amber-700 dark:text-amber-300 text-[11px] font-medium px-3 py-1.5 hover:bg-amber-500/10 transition-colors"
                  >
                    <Trash2 size={12} />
                    {t('dwg_takeoff.conv_delete', {
                      defaultValue: 'Delete drawing',
                    })}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Needs-conversion card ──────────────────────────────────────────────
 *
 * Shown for a .dwg drawing that has no parsed entities and no DDC cad2data
 * converter on this server, so nothing will ever transition it on its own
 * (the fresh-install case: demo DWG rows seeded without a converter present).
 * This replaces the old behaviour where such a drawing span on the
 * "Converting your drawing…" spinner indefinitely.
 *
 * DWG is an open format we open directly once cad2data is present. The card
 * offers a one-click "Convert with cad2data" install (reusing the same
 * installer the error card and the offline-readiness pill use). If the
 * converter is somehow already present the file is simply mid-flight, so the
 * card nudges the user to re-upload to kick the conversion. Never a spinner. */
function NeedsConversionCard({
  drawingName,
  filename,
  converterAvailable,
  onConverted,
  onUploadAnother,
  onDelete,
}: {
  drawingName: string;
  filename: string;
  converterAvailable: boolean;
  onConverted?: () => void;
  onUploadAnother?: () => void;
  onDelete?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div
        data-testid="dwg-needs-conversion-card"
        className="w-full max-w-xl rounded-2xl border border-oe-blue/30 bg-oe-blue/5 p-6 shadow-xl"
        role="status"
        aria-live="polite"
      >
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-oe-blue/15 border border-oe-blue/30 flex items-center justify-center shrink-0">
            <FileUp size={20} className="text-oe-blue" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-content-primary leading-tight">
              {t('dwg_takeoff.needs_conv_title', {
                defaultValue: 'This drawing needs conversion',
              })}
            </h2>
            <p className="text-xs text-content-tertiary mt-1 truncate" title={drawingName || filename}>
              {drawingName || filename}
            </p>
            <p className="text-xs text-content-secondary mt-3 leading-relaxed">
              {t('dwg_takeoff.needs_conv_message', {
                defaultValue:
                  'DWG is an open format and we open it directly once the cad2data converter is set up. This drawing has not been converted yet, and the converter is not installed on this server. Install it once and every DWG you open after will render here automatically. DXF files render without any converter.',
              })}
            </p>

            {!converterAvailable && <InstallDwgConverterCTA onInstalled={onConverted} />}

            <div className="mt-4 flex flex-wrap items-center gap-2">
              {converterAvailable && onUploadAnother && (
                <button
                  type="button"
                  onClick={onUploadAnother}
                  data-testid="dwg-needs-conversion-upload"
                  className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue text-white text-[11px] font-semibold px-3 py-1.5 hover:bg-oe-blue-dark transition-colors"
                >
                  <Upload size={12} />
                  {t('dwg_takeoff.needs_conv_reupload', {
                    defaultValue: 'Re-upload to convert',
                  })}
                </button>
              )}
              {onUploadAnother && (
                <button
                  type="button"
                  onClick={onUploadAnother}
                  data-testid="dwg-needs-conversion-upload-dxf"
                  className="inline-flex items-center gap-1.5 rounded-md border border-oe-blue/30 text-oe-blue text-[11px] font-medium px-3 py-1.5 hover:bg-oe-blue/10 transition-colors"
                >
                  <FileText size={12} />
                  {t('dwg_takeoff.needs_conv_upload_dxf', {
                    defaultValue: 'Upload a DXF instead',
                  })}
                </button>
              )}
              {onDelete && (
                <button
                  type="button"
                  onClick={onDelete}
                  data-testid="dwg-needs-conversion-delete"
                  className="inline-flex items-center gap-1.5 rounded-md border border-border-light text-content-tertiary text-[11px] font-medium px-3 py-1.5 hover:bg-surface-secondary transition-colors"
                >
                  <Trash2 size={12} />
                  {t('dwg_takeoff.conv_delete', {
                    defaultValue: 'Delete drawing',
                  })}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
