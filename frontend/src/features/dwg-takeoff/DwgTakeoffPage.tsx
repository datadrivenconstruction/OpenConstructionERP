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

import { useState, useMemo, useCallback, useRef, useEffect, type ReactNode } from 'react';
import {
  calculateArea,
  calculateDistance,
  calculatePerimeter,
  getSegmentLengths,
  formatMeasurement,
} from './lib/measurement';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import clsx from 'clsx';
import {
  Upload,
  FileUp,
  Trash2,
  Loader2,
  FileText,
  Layers,
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
} from 'lucide-react';
import { Badge, ConfirmDialog, ElementInfoPopover, type DWGElementPayload } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useDwgUploadStore } from '@/stores/useDwgUploadStore';
import { apiGet } from '@/shared/lib/api';
import { boqApi, normalizePositions, type Position } from '@/features/boq/api';
import { projectsApi } from '@/features/projects/api';
import {
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
  USER_MARKUP_LAYER,
} from './api';
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
import { exportCanvasToPdf } from './lib/pdf-export';
import { ToolPalette, type DwgTool } from './components/ToolPalette';
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

/** Convert a DxfEntity into the shared ElementInfoPopover payload shape. */
function toDWGElementPayload(
  entity: DxfEntity,
  opts?: {
    calculatePerimeter?: (verts: { x: number; y: number }[], closed: boolean) => number;
    calculateArea?: (verts: { x: number; y: number }[]) => number;
    calculateDistance?: (a: { x: number; y: number }, b: { x: number; y: number }) => number;
  },
): DWGElementPayload {
  const measurements: Record<string, { value: number; unit: string }> = {};

  // Polyline measurements
  if (entity.type === 'LWPOLYLINE' && entity.vertices && entity.vertices.length >= 2) {
    const closed = !!entity.closed;
    if (opts?.calculatePerimeter) {
      measurements['Perimeter'] = {
        value: opts.calculatePerimeter(entity.vertices, closed),
        unit: 'm',
      };
    }
    if (closed && opts?.calculateArea) {
      const area = opts.calculateArea(entity.vertices);
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
      value: opts.calculateDistance(entity.start, entity.end),
      unit: 'm',
    };
  }

  // Circle measurements
  if (entity.type === 'CIRCLE' && entity.radius != null) {
    measurements['Radius'] = { value: entity.radius, unit: 'm' };
    measurements['Circumference'] = {
      value: 2 * Math.PI * entity.radius,
      unit: 'm',
    };
    measurements['Area'] = {
      value: Math.PI * entity.radius ** 2,
      unit: 'm\u00B2',
    };
  }

  // ARC radius
  if (entity.type === 'ARC' && entity.radius != null) {
    measurements['Radius'] = { value: entity.radius, unit: 'm' };
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
 */
function extractEntityMeasurement(
  entity: DxfEntity,
): { value: number; unit: string; kind: 'length' | 'area' | 'radius' } | null {
  if (entity.type === 'LWPOLYLINE' && entity.vertices && entity.vertices.length >= 2) {
    const closed = !!entity.closed;
    if (closed) {
      const area = calculateArea(entity.vertices);
      if (area > 0) {
        return { value: Math.round(area * 100) / 100, unit: 'm2', kind: 'area' };
      }
    }
    const perimeter = calculatePerimeter(entity.vertices, closed);
    return { value: Math.round(perimeter * 100) / 100, unit: 'm', kind: 'length' };
  }
  if (entity.type === 'LINE' && entity.start && entity.end) {
    const len = calculateDistance(entity.start, entity.end);
    return { value: Math.round(len * 100) / 100, unit: 'm', kind: 'length' };
  }
  if (entity.type === 'CIRCLE' && entity.radius != null) {
    const area = Math.PI * entity.radius ** 2;
    return { value: Math.round(area * 100) / 100, unit: 'm2', kind: 'area' };
  }
  if (entity.type === 'ARC' && entity.radius != null) {
    return { value: Math.round(entity.radius * 100) / 100, unit: 'm', kind: 'radius' };
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
  const [showHint, setShowHint] = useState(false);

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
            ? t('dwg_takeoff.offline_ready_tooltip', {
                defaultValue:
                  'This tool works fully offline — conversions run on your machine.',
              })
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
              className="text-content-tertiary hover:text-content-primary"
            >
              <X size={12} />
            </button>
          </div>
          <p className="text-content-secondary leading-relaxed">
            {readiness?.message ??
              t('dwg_takeoff.offline_ready_tooltip', {
                defaultValue:
                  'This tool works fully offline — conversions run on your machine.',
              })}
          </p>
          {converterMissing && (
            <div className="mt-2 rounded-md bg-amber-500/10 border border-amber-500/20 px-2 py-1.5 text-[10px] text-amber-300">
              {t('dwg_takeoff.offline_install_hint', {
                defaultValue:
                  'Upload DXF files to continue without the converter, or install it to enable .dwg support.',
              })}
            </div>
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
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  // Fallback: if no project is currently active (e.g. first load after
  // ``clearProject`` wiped a stale id from localStorage), use the first
  // project from the server list. Without this, ``fetchDrawings('')``
  // short-circuits to ``[]`` and the DWG panel looks empty on every
  // reload — reported as "при перезагрузке потеряются все документы".
  // The drawings themselves are always persisted server-side; only the
  // client-side project context was lost.
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 5 * 60_000,
  });
  const projectId = activeProjectId || projects[0]?.id || '';

  // Persist the fallback choice so subsequent reloads and sibling
  // modules (BIM, BOQ, CDE) see the same active project instead of each
  // picking the "first" independently.
  useEffect(() => {
    if (!activeProjectId && projectId) {
      const picked = projects.find((p) => p.id === projectId);
      if (picked) setActiveProject(picked.id, picked.name);
    }
  }, [activeProjectId, projectId, projects, setActiveProject]);

  // Deep-link support: ?drawingId=xxx opens a specific drawing
  // Also supports ?docName=xxx from the Documents page (matches by filename)
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkDrawingId = searchParams.get('drawingId');
  const deepLinkDocName = searchParams.get('docName');

  // State
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<DwgTool>('select');
  const [activeColor, setActiveColor] = useState('#ef4444');
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
        if (prev?.status !== 'ready' && job.status === 'ready' && job.projectId === projectId) {
          queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
          queryClient.invalidateQueries({ queryKey: ['documents'] });
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

  const { data: entities = [], isLoading: loadingEntities } = useQuery({
    queryKey: ['dwg-entities', selectedDrawingId],
    queryFn: () => fetchEntities(selectedDrawingId!),
    enabled: !!selectedDrawingId,
  });

  const { data: annotations = [] } = useQuery({
    queryKey: ['dwg-annotations', selectedDrawingId],
    queryFn: () => fetchAnnotations(selectedDrawingId!),
    enabled: !!selectedDrawingId,
  });

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

  // Deep-link: auto-select drawing when ?drawingId= or ?docName= is in URL
  useEffect(() => {
    if (drawings.length === 0) return;

    let target: typeof drawings[number] | undefined;

    // 1. Try matching by exact drawing ID
    if (deepLinkDrawingId) {
      target = drawings.find((d) => d.id === deepLinkDrawingId);
    }

    // 2. Fallback: match by document name from Documents page (?docName=)
    if (!target && deepLinkDocName) {
      const docNameLower = decodeURIComponent(deepLinkDocName).toLowerCase();
      target = drawings.find(
        (d) =>
          d.name.toLowerCase() === docNameLower ||
          d.name.toLowerCase() === docNameLower.replace(/\.[^.]+$/, ''),
      );
    }

    if (target && selectedDrawingId !== target.id) {
      handleSelectDrawing(target.id);
      // Clean up the URL params
      const next = new URLSearchParams(searchParams);
      next.delete('drawingId');
      next.delete('docId');
      next.delete('docName');
      setSearchParams(next, { replace: true });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkDrawingId, deepLinkDocName, drawings]);

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

  // Computed layers (from filtered entities + annotations so virtual
  // USER_MARKUP layer gets a LayerPanel row once users start drawing).
  const layers = useMemo(
    () => extractLayers(filteredEntities, annotations),
    [filteredEntities, annotations],
  );

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

  // Initialize visible layers when entities/layout change
  useEffect(() => {
    if (layers.length > 0) {
      setVisibleLayers(new Set(layers.map((l) => l.name)));
    }
  }, [layers]);

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

  const createAnnotationMutation = useMutation({
    mutationFn: (data: CreateAnnotationPayload) => createAnnotation(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dwg-annotations', selectedDrawingId] });
    },
    onError: (err: Error) => {
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

  const deleteAnnotationMutation = useMutation({
    mutationFn: (id: string) => deleteAnnotation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dwg-annotations', selectedDrawingId] });
      setSelectedAnnotationId(null);
    },
  });

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
            defaultValue: 'No active project — open this drawing from its project first.',
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
        ann.type === 'text_pin';
      createAnnotationMutation.mutate({
        project_id: effectiveProjectId,
        drawing_id: selectedDrawingId,
        annotation_type: ann.type,
        geometry: { points: ann.points },
        text: ann.text,
        color: ann.color ?? activeColor,
        thickness: 2,
        line_width: 2,
        layer_name: isPrimitive ? USER_MARKUP_LAYER : 'ANNOTATIONS',
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
    setSelectedEntityIds(new Set());
    setHiddenEntityIds(new Set());
    setSelectedAnnotationId(null);
    setSelectedLayout(null);
    setEntityPopup(null);
    setContextMenu(null);
  }, []);

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
    () => aggregateEntities(selectedEntities),
    [selectedEntities],
  );

  /**
   * Drawing-wide aggregate for the Summary tab (R3 #12). Uses the same
   * helper as the selection panel so totals are consistent — if a polygon
   * contributes 12 m² to the selection aggregate, it contributes the same
   * 12 m² to the drawing totals.
   */
  const summaryAggregate = useMemo(
    () => aggregateEntities(filteredEntities),
    [filteredEntities],
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
    return Array.from(buckets.entries())
      .map(([layer, v]) => ({ layer, ...v }))
      .sort((a, b) => (b.area || b.length || b.count) - (a.area || a.length || a.count));
  }, [filteredEntities]);

  /** Breakdown by DXF entity type, already computed by ``aggregateEntities``. */
  const summaryByType = useMemo(() => {
    const rows = Object.entries(summaryAggregate.byType)
      .map(([type, count]) => ({ type, count }))
      .sort((a, b) => b.count - a.count);
    return rows;
  }, [summaryAggregate]);

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
      const measurement = extractEntityMeasurement(entity);
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
      if (measurement) {
        patch['quantity'] = measurement.value;
        patch['unit'] = measurement.unit;
      }
      await boqApi.updatePosition(position.id, patch);

      queryClient.invalidateQueries({ queryKey: ['dwg-annotations', selectedDrawingId] });
      queryClient.invalidateQueries({ queryKey: ['boq', position.boq_id] });

      addToast({
        type: 'success',
        title: t('dwg_takeoff.linked_to_boq', { defaultValue: 'Linked to BOQ' }),
        message: measurement
          ? `${measurement.value} ${measurement.unit} \u2192 ${position.ordinal}`
          : position.ordinal,
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
  }, [entities, selectedDrawingId, ensureAnnotationForEntity, queryClient, addToast, t]);

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

      const measurement = extractEntityMeasurement(entity);
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
  }, [entities, linkPickerBoqId, linkBoqPositions, ensureAnnotationForEntity, selectedDrawingId, queryClient, addToast, t]);

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

      const agg = aggregateEntities(selectedEntities);
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
    queryClient,
    addToast,
    t,
  ]);

  // Global keyboard shortcuts for the page
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ignore shortcuts when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      switch (e.key) {
        case 'Escape':
          if (contextMenu) {
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
        case 'a': case 'A':
          setActiveTool('area');
          break;
        case 't': case 'T':
          setActiveTool('text_pin');
          break;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selectedEntityIds, selectedAnnotationId, contextMenu]);

  /* ── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col -mx-4 sm:-mx-7 -mt-6 -mb-4 overflow-hidden" style={{ height: 'calc(100vh - 56px)' }}>
      {/* Top filter bar removed — ToolPalette now floats inside the viewer
          in the top-left corner so the drawing gets maximum vertical space
          and the tools live where the cursor already is while drawing. */}

      <div className="flex flex-1 overflow-hidden">
        {/* ── Center: DXF Viewer ──────────────────────────────────── */}
        <div className="flex flex-1 flex-col min-h-0 min-w-0">
          {!selectedDrawingId ? (
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
                <div className="grid grid-cols-1 md:grid-cols-[1.4fr_1fr] gap-8 items-stretch">
                  {/* LEFT · Upload card (gets the larger half) */}
                  <div className="flex flex-col">
                    <div className="rounded-2xl bg-[#22252b]/90 backdrop-blur-sm border border-[#333842] shadow-2xl shadow-black/30 p-3 flex flex-col h-full">
                      <label
                        onDrop={(e) => {
                          e.preventDefault();
                          const f = e.dataTransfer.files?.[0];
                          if (f) { setUploadFile(f); setUploadName(f.name.replace(/\.[^.]+$/, '')); setShowUpload(true); }
                        }}
                        onDragOver={(e) => e.preventDefault()}
                        className="group/drop flex flex-col items-center justify-center gap-7 rounded-xl p-20 text-center cursor-pointer transition-all flex-1 border-2 border-dashed border-[#444c5a] bg-[#1a1d23]/60 hover:border-blue-500/50 hover:bg-blue-500/5 hover:shadow-[0_0_30px_rgba(59,130,246,0.1)]"
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
                          AutoCAD 2000–2025 &middot; DXF R12–R2025
                        </p>
                      </label>
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
                      </div>
                      <p className="text-base text-gray-400 mt-3 leading-relaxed">
                        {t('dwg_takeoff.hero_subtitle', { defaultValue: 'Open DWG/DXF drawings, measure areas and lengths, annotate directly on the drawing, and link measurements to your BOQ positions.' })}
                      </p>
                      <p className="text-xs text-gray-600 mt-3 leading-relaxed">
                        AutoCAD DWG 2000–2025 &middot; DXF R12–R2025
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

                    {/* Local processing badge — sits under the feature cards */}
                    <div className="mt-3 flex items-center justify-start">
                      <div className="inline-flex flex-wrap items-center gap-2 px-4 py-2 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                        <ShieldCheck size={14} className="text-emerald-400 shrink-0" />
                        <span className="text-xs text-emerald-300/90 font-medium">
                          {t('common.local_processing', { defaultValue: '100% Local Processing · Your files never leave your computer' })}
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
            {layouts.length > 1 && (
              <div className="flex items-center gap-0.5 border-b border-border bg-surface px-2 py-1 overflow-x-auto flex-shrink-0">
                {layouts.map((layout) => (
                  <button
                    key={layout}
                    onClick={() => setSelectedLayout(layout)}
                    className={clsx(
                      'px-3 py-1 text-xs font-medium rounded transition-colors whitespace-nowrap',
                      selectedLayout === layout
                        ? 'bg-oe-blue/15 text-oe-blue'
                        : 'text-muted-foreground hover:text-foreground hover:bg-surface-secondary',
                    )}
                  >
                    {layout}
                  </button>
                ))}
              </div>
            )}
            <div className="relative flex-1 min-h-0" data-dwg-viewer-root>
              <DxfViewer
                entities={viewerEntities}
                annotations={visibleAnnotations}
                visibleLayers={visibleLayers}
                activeTool={activeTool}
                activeColor={activeColor}
                selectedEntityIds={selectedEntityIds}
                hiddenEntityIds={hiddenEntityIds}
                selectedAnnotationId={selectedAnnotationId}
                drawingScale={drawingScale}
                onSelectEntity={handleSelectEntity}
                onSelectAnnotation={setSelectedAnnotationId}
                onEntityContextMenu={handleEntityContextMenu}
                onAnnotationCreated={handleAnnotationCreated}
              />

              {/* Floating ToolPalette — top-left corner, above the canvas.
                  Lives here (not in a fixed header bar) so the drawing gets
                  the full viewport height and tools stay visually attached
                  to the thing they act on. */}
              <div className="absolute top-3 left-3 z-10 rounded-lg border border-white/60 bg-white/85 dark:bg-white/90 backdrop-blur-md shadow-xl shadow-black/30 ring-1 ring-black/5">
                <ToolPalette
                  activeTool={activeTool}
                  onToolChange={setActiveTool}
                  activeColor={activeColor}
                  onColorChange={setActiveColor}
                />
              </div>

              {/* Floating Offline Ready badge + PDF export — top-right corner
                  of the viewer (opposite the ToolPalette). Download PDF is
                  paired with the badge so estimators discover it while
                  glancing at converter status without stealing real estate
                  from the drawing. */}
              <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
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
              {/* Floating entity info popup (shared ElementInfoPopover) —
                  only shown for a single-entity click, hidden during
                  multi-select to keep the screen readable. */}
              {selectedEntity && entityPopup && activeTool === 'select'
                && selectedEntityIds.size === 1 && (
                <ElementInfoPopover
                  element={toDWGElementPayload(selectedEntity, {
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
                const measurement = extractEntityMeasurement(selectedEntity);
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
                          ? t('dwg_takeoff.relink_title', { defaultValue: 'Linked — pick new' })
                          : t('dwg_takeoff.link_to_boq_title', { defaultValue: 'Link to BOQ position' })}
                      </div>
                      <button
                        onClick={() => setLinkingEntityId(null)}
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
                            {t('dwg_takeoff.pick_project', { defaultValue: '— project —' })}
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
                              : t('dwg_takeoff.pick_boq', { defaultValue: '— BOQ —' })}
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
                              defaultValue: 'BOQ is empty — switch to "Create new".',
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
                    onClick={() => {
                      const firstId = selectedEntityIds.values().next().value;
                      if (firstId) handleOpenLinkToBoq(firstId);
                    }}
                    className="flex-1 flex items-center justify-center gap-1 rounded-md bg-oe-blue text-white text-[11px] font-semibold px-2 py-1 hover:bg-oe-blue-dark transition-colors"
                    data-testid="dwg-group-link-boq"
                  >
                    <Link2 size={11} />
                    {t('dwg_takeoff.link_n_to_boq', {
                      defaultValue: 'Link {{count}} to BOQ',
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
              const areaSum = annotations
                .filter((a) => a.type === 'area' && a.measurement_value != null)
                .reduce((s, a) => s + (a.measurement_value ?? 0), 0);
              const distSum = annotations
                .filter((a) => a.type === 'distance' && a.measurement_value != null)
                .reduce((s, a) => s + (a.measurement_value ?? 0), 0);
              const handleExportCsv = () => {
                const rows = [
                  ['type', 'text', 'value', 'unit', 'linked_boq_position_id'].join(','),
                  ...annotations.map((a) =>
                    [
                      a.type,
                      JSON.stringify(a.text ?? ''),
                      a.measurement_value ?? '',
                      a.measurement_unit ?? '',
                      a.linked_boq_position_id ?? '',
                    ].join(','),
                  ),
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
                  { id: 'layers' as const, icon: Layers, labelKey: 'dwg_takeoff.tab_layers_short', fallback: 'Layers', titleKey: 'dwg_takeoff.layers', titleFallback: 'Layers', count: layers.length },
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
                            if (ok) deleteAnnotationMutation.mutate(ann.id);
                          }}
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
                        const perimeter = calculatePerimeter(verts, closed) * drawingScale;
                        const area = closed
                          ? calculateArea(verts) * drawingScale * drawingScale
                          : 0;
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
                            {closed && area > 0 && (
                              <div className="flex items-center justify-between rounded-md bg-blue-950/30 px-2.5 py-1.5 border border-blue-800/40">
                                <span className="text-blue-400 font-medium">
                                  {t('dwg_takeoff.area', 'Area')}
                                </span>
                                <span className="font-mono font-bold text-blue-300">
                                  {formatMeasurement(area, 'm\u00B2')}
                                </span>
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
                                      {formatMeasurement(len * drawingScale, 'm')}
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
                />
              )}

              {rightTab === 'summary' && (
                <SummaryTab
                  entityCount={filteredEntities.length}
                  aggregate={summaryAggregate}
                  byLayer={summaryByLayer}
                  byType={summaryByType}
                  onExportCsv={handleExportSummaryCsv}
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
                    {t('dwg_takeoff.upload_hint', 'DWG or DXF files up to 100 MB')}
                  </p>
                </div>
              </div>
              <button
                onClick={closeUploadModal}
                className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-surface-secondary transition-colors"
              >
                <X size={16} className="text-content-tertiary hover:text-content-primary transition-colors" />
              </button>
            </div>

            {/* Drop zone / file picker */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".dwg,.dxf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  const MAX_SIZE_MB = 100;
                  if (f.size > MAX_SIZE_MB * 1024 * 1024) {
                    addToast({
                      type: 'error',
                      title: t('dwg_takeoff.file_too_large', 'File too large'),
                      message: t('dwg_takeoff.file_size_limit', 'Maximum file size is {{max}} MB', {
                        max: MAX_SIZE_MB,
                      }),
                    });
                    return;
                  }
                  setUploadFile(f);
                  if (!uploadName) setUploadName(f.name.replace(/\.[^.]+$/, ''));
                }
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
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
                  const MAX_SIZE_MB = 100;
                  if (f.size > MAX_SIZE_MB * 1024 * 1024) {
                    addToast({
                      type: 'error',
                      title: t('dwg_takeoff.file_too_large', 'File too large'),
                      message: t('dwg_takeoff.file_size_limit', 'Maximum file size is {{max}} MB', {
                        max: MAX_SIZE_MB,
                      }),
                    });
                    return;
                  }
                  setUploadFile(f);
                  if (!uploadName) setUploadName(f.name.replace(/\.[^.]+$/, ''));
                }
              }}
              className={`w-full flex flex-col items-center gap-2 border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
                uploadFile
                  ? 'border-oe-blue bg-oe-blue/5'
                  : 'border-border-medium hover:border-oe-blue hover:bg-blue-50/50 dark:hover:bg-blue-950/20'
              }`}
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

            {/* Install-hint banner — shown when user picks a .dwg but the
                local converter isn't installed. DXF uploads bypass it. */}
            {uploadFile
              && uploadFile.name.toLowerCase().endsWith('.dwg')
              && offlineReadiness
              && !offlineReadiness.converter_available && (
              <div
                className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[11px] text-amber-700 dark:text-amber-300"
                data-testid="dwg-upload-install-hint"
              >
                <WifiOff size={14} className="shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="font-semibold">
                    {t('dwg_takeoff.offline_install', { defaultValue: 'Install converter' })}
                  </p>
                  <p className="leading-relaxed">
                    {offlineReadiness.message
                      || t('dwg_takeoff.offline_install_hint', {
                        defaultValue:
                          'Upload DXF files to continue without the converter, or install it to enable .dwg support.',
                      })}
                  </p>
                </div>
              </div>
            )}

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
                corner dock. */}
            <button
              data-testid="dwg-upload-submit"
              disabled={!uploadFile || !projectId}
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
                      'Progress continues in the dock — you can navigate away.',
                  }),
                });
                closeUploadModal();
              }}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-bold transition-all disabled:opacity-50 bg-oe-blue text-white hover:bg-oe-blue-dark active:scale-[0.98] shadow-md hover:shadow-lg"
            >
              <Upload size={16} />
              {t('dwg_takeoff.upload_and_process', 'Upload & Process')}
            </button>
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
              <button
                key={d.id}
                onClick={() => onSelectDrawing(d.id)}
                className={clsx(
                  'group relative shrink-0 w-36 h-[72px] text-start rounded-md border overflow-hidden flex flex-col',
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
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteDrawing(d.id);
                  }}
                  className="absolute top-0.5 right-0.5 h-4 w-4 rounded flex items-center justify-center
                             text-transparent group-hover:text-slate-400 hover:!text-red-400 hover:bg-red-500/20
                             transition-all"
                >
                  <Trash2 size={9} />
                </button>
              </button>
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

  return (
    <div className="flex flex-col gap-4" data-testid="dwg-scale-tab">
      <div className="flex items-center gap-1.5">
        <Ruler size={14} className="text-oe-blue" />
        <h3 className="text-sm font-semibold text-foreground">
          {t('dwg_takeoff.scale_title', { defaultValue: 'Drawing scale' })}
        </h3>
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
                'Click a Distance measurement on the drawing between two points whose real length you know. Type the real length below, then press Apply — the scale is computed automatically.',
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
                {t('dwg_takeoff.scale_calibrate_cancel', { defaultValue: 'Cancel — click two points on the drawing' })}
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
                'Use when one sheet mixes scales (e.g. a 1:100 plan with a 1:20 detail window). Every new annotation you draw carries the scale below until you change it — older annotations keep their own stored scale.',
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
  byLayer: { layer: string; area: number; length: number; count: number }[];
  byType: { type: string; count: number }[];
  onExportCsv: () => void;
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
  byLayer,
  byType,
  onExportCsv,
  onExportPdf,
}: SummaryTabProps) {
  const { t } = useTranslation();

  const maxLayerMetric = useMemo(() => {
    let m = 0;
    for (const row of byLayer) {
      const v = row.area > 0 ? row.area : row.length;
      if (v > m) m = v;
    }
    return m;
  }, [byLayer]);

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
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <BarChart3 size={14} className="text-oe-blue" />
          <h3 className="text-sm font-semibold text-foreground">
            {t('dwg_takeoff.summary_title', { defaultValue: 'Measurements Summary' })}
          </h3>
        </div>
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
          {t('dwg_takeoff.export_csv_short', { defaultValue: 'Export CSV' })}
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
          {t('dwg_takeoff.export_pdf_short', { defaultValue: 'Export PDF' })}
        </button>
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

      {/* By Layer */}
      <div data-testid="dwg-summary-by-layer">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Layers size={11} className="text-content-tertiary" />
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('dwg_takeoff.summary_by_layer', { defaultValue: 'By layer' })}
          </h4>
          <span className="text-[10px] text-content-quaternary tabular-nums">
            ({byLayer.length})
          </span>
        </div>
        <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
          {byLayer.slice(0, 20).map((row) => {
            const metric = row.area > 0 ? row.area : row.length;
            const share = maxLayerMetric > 0 ? (metric / maxLayerMetric) * 100 : 0;
            return (
              <div
                key={row.layer}
                className="rounded-md border border-border-light bg-surface-secondary/50 px-2 py-1.5 hover:bg-surface-secondary transition-colors"
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="font-mono text-[11px] text-content-primary truncate">
                    {row.layer}
                  </span>
                  <span className="text-[10px] tabular-nums text-content-tertiary shrink-0">
                    {row.count}
                  </span>
                </div>
                <div className="relative h-1 rounded-full bg-surface-tertiary overflow-hidden">
                  <div
                    className="absolute inset-y-0 left-0 bg-gradient-to-r from-oe-blue to-blue-400"
                    style={{ width: `${Math.max(share, 3)}%` }}
                  />
                </div>
                <div className="flex items-center justify-between mt-1 text-[10px] tabular-nums">
                  {row.area > 0 && (
                    <span className="text-emerald-400">
                      {row.area.toFixed(2)} m²
                    </span>
                  )}
                  {row.length > 0 && (
                    <span className="text-violet-400">
                      {row.length.toFixed(2)} m
                    </span>
                  )}
                  {row.area === 0 && row.length === 0 && (
                    <span className="text-content-quaternary">
                      {t('dwg_takeoff.summary_no_measure', {
                        defaultValue: 'no measurable geometry',
                      })}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
          {byLayer.length > 20 && (
            <p className="text-[10px] text-content-tertiary text-center py-1">
              {t('dwg_takeoff.summary_layers_more', {
                defaultValue: '+{{count}} more',
                count: byLayer.length - 20,
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
