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

import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
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
  ChevronUp,
  ShieldCheck,
  Link2,
} from 'lucide-react';
import { Badge, ConfirmDialog, ElementInfoPopover, type DWGElementPayload } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet } from '@/shared/lib/api';
import { boqApi, normalizePositions, type Position } from '@/features/boq/api';
import { projectsApi } from '@/features/projects/api';
import {
  fetchDrawings,
  uploadDrawing,
  deleteDrawing,
  fetchEntities,
  fetchAnnotations,
  createAnnotation,
  deleteAnnotation,
  linkAnnotationToBoq,
} from './api';
import type { DxfEntity, DxfLayer, DwgAnnotation, CreateAnnotationPayload } from './api';
import { DxfViewer, type EntitySelectEvent } from './components/DxfViewer';
import { ToolPalette, type DwgTool } from './components/ToolPalette';
import { LayerPanel } from './components/LayerPanel';
import { EntityNameFilter, entityDisplayName } from './components/EntityNameFilter';
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

function extractLayers(entities: DxfEntity[]): DxfLayer[] {
  const map = new Map<string, { color: string | number; count: number }>();
  for (const e of entities) {
    const existing = map.get(e.layer);
    if (existing) {
      existing.count++;
    } else {
      map.set(e.layer, { color: e.color, count: 1 });
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

/* ── Component ─────────────────────────────────────────────────────── */

export function DwgTakeoffPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  // Deep-link support: ?drawingId=xxx opens a specific drawing
  // Also supports ?docName=xxx from the Documents page (matches by filename)
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkDrawingId = searchParams.get('drawingId');
  const deepLinkDocName = searchParams.get('docName');

  // State
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<DwgTool>('select');
  const [activeColor, setActiveColor] = useState('#ef4444');
  const [visibleLayers, setVisibleLayers] = useState<Set<string>>(new Set());
  const [visibleNames, setVisibleNames] = useState<Set<string>>(new Set());
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<'layers' | 'annotations' | 'properties'>('layers');
  const [showUpload, setShowUpload] = useState(false);
  const [uploadName, setUploadName] = useState('');
  const [uploadDiscipline, setUploadDiscipline] = useState('architectural');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const { confirm: confirmAnnotDelete, ...annotDeleteConfirmProps } = useConfirm();
  const [filmstripExpanded, setFilmstripExpanded] = useState(true);
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

  // Filter entities by selected layout
  const filteredEntities = useMemo(() => {
    if (!selectedLayout || layouts.length === 0) return entities;
    return entities.filter((e) => e.layout === selectedLayout);
  }, [entities, selectedLayout, layouts]);

  // Computed layers (from filtered entities)
  const layers = useMemo(() => extractLayers(filteredEntities), [filteredEntities]);

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

  // Mutations
  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!uploadFile) throw new Error('No file selected');
      return uploadDrawing(projectId, uploadFile, uploadName || uploadFile.name, uploadDiscipline);
    },
    onSuccess: (drawing) => {
      queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
      addToast({ type: 'success', title: t('dwg_takeoff.upload_success', 'Drawing uploaded') });
      // Capture file ref before clearing state
      const savedFile = uploadFile;
      closeUploadModal();
      setSelectedDrawingId(drawing.id);

      // Auto-save to Documents module as well (fire-and-forget)
      if (savedFile && projectId) {
        const file = savedFile;
        const token = useAuthStore.getState().accessToken;
        const formData = new FormData();
        formData.append('file', file);
        const headers: Record<string, string> = { 'X-DDC-Client': 'OE/1.0' };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        fetch(
          `/api/v1/documents/upload?project_id=${projectId}&category=drawing`,
          { method: 'POST', headers, body: formData },
        )
          .then(() => {
            queryClient.invalidateQueries({ queryKey: ['documents'] });
          })
          .catch(() => {
            // Silently ignore — the drawing was already saved in the DWG module
          });
      }
    },
    onError: () => {
      addToast({ type: 'error', title: t('dwg_takeoff.upload_error', 'Upload failed') });
    },
  });

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
  });

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
      if (!selectedDrawingId || !projectId) return;
      createAnnotationMutation.mutate({
        project_id: projectId,
        drawing_id: selectedDrawingId,
        annotation_type: ann.type,
        geometry: { points: ann.points },
        text: ann.text,
        color: ann.color ?? activeColor,
        measurement_value: ann.measurement_value,
        measurement_unit: ann.measurement_unit,
        metadata: ann.fontSize ? { font_size: ann.fontSize } : undefined,
      });
    },
    [selectedDrawingId, projectId, activeColor, createAnnotationMutation],
  );

  const handleSelectEntity = useCallback((id: string | null, event?: EntitySelectEvent) => {
    setSelectedEntityId(id);
    if (id) {
      // Auto-switch to properties tab when an entity is selected
      setRightTab('properties');
      // Show floating popup at click position
      if (event) {
        setEntityPopup({ x: event.screenX, y: event.screenY });
      }
    } else {
      setEntityPopup(null);
    }
  }, []);

  const handleSelectDrawing = useCallback((id: string) => {
    setSelectedDrawingId(id);
    setVisibleLayers(new Set());
    setVisibleNames(new Set());
    setSelectedEntityId(null);
    setSelectedAnnotationId(null);
    setSelectedLayout(null);
    setEntityPopup(null);
  }, []);

  // Selected entity details
  const selectedEntity = useMemo(
    () => entities.find((e) => e.id === selectedEntityId) ?? null,
    [entities, selectedEntityId],
  );

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
    if (!selectedDrawingId || !projectId) return null;

    // Reuse an existing text_pin annotation anchored to this entity, if any.
    const existing = annotations.find(
      (a) => a.type === 'text_pin'
        && (a.metadata as Record<string, unknown> | undefined)?.['dwg_entity_id'] === entity.id,
    );
    if (existing) return existing.id;

    const centroid = computeEntityCentroid(entity);
    try {
      const created = await createAnnotation({
        project_id: projectId,
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
  }, [selectedDrawingId, projectId, annotations, activeColor, queryClient]);

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

  // Global keyboard shortcuts for the page
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ignore shortcuts when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      switch (e.key) {
        case 'Escape':
          if (selectedEntityId) { setSelectedEntityId(null); setEntityPopup(null); }
          else if (selectedAnnotationId) setSelectedAnnotationId(null);
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
  }, [selectedEntityId, selectedAnnotationId]);

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
                      <h1 className="text-2xl font-bold text-gray-100 tracking-tight leading-tight">
                        {t('dwg_takeoff.hero_title', { defaultValue: 'DWG Takeoff' })}
                      </h1>
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
              <Loader2 size={32} className="animate-spin text-muted-foreground" />
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
            <div className="relative flex-1 min-h-0">
              <DxfViewer
                entities={viewerEntities}
                annotations={annotations}
                visibleLayers={visibleLayers}
                activeTool={activeTool}
                activeColor={activeColor}
                selectedEntityId={selectedEntityId}
                selectedAnnotationId={selectedAnnotationId}
                onSelectEntity={handleSelectEntity}
                onSelectAnnotation={setSelectedAnnotationId}
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
              {/* Floating entity info popup (shared ElementInfoPopover) */}
              {selectedEntity && entityPopup && activeTool === 'select' && (
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
                                    onClick={() => handleLinkToPosition(selectedEntity.id, pos)}
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

          {/* ── Bottom Filmstrip: Drawing List ────────────────────── */}
          <DrawingFilmstrip
            drawings={drawings}
            isLoading={loadingDrawings}
            activeDrawingId={selectedDrawingId}
            entities={entities}
            expanded={filmstripExpanded}
            onToggleExpanded={() => setFilmstripExpanded((v) => !v)}
            onSelectDrawing={handleSelectDrawing}
            onDeleteDrawing={(id) => setConfirmDeleteId(id)}
            onUpload={() => setShowUpload(true)}
          />
        </div>

        {/* ── Right Panel: Layers / Annotations / Properties ───── */}
        {selectedDrawingId && (
          <div className="flex w-72 flex-shrink-0 flex-col border-l border-border-light bg-surface-primary text-content-primary shadow-xl shadow-black/30">
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

            {/* Tab bar */}
            <div className="flex border-b border-border">
              {(
                [
                  { id: 'layers' as const, icon: Layers, labelKey: 'dwg_takeoff.layers', count: layers.length },
                  { id: 'annotations' as const, icon: MessageSquare, labelKey: 'dwg_takeoff.annotations', count: annotations.length },
                  { id: 'properties' as const, icon: Info, labelKey: 'dwg_takeoff.properties', count: 0 },
                ]
              ).map(({ id, icon: Icon, labelKey, count }) => (
                <button
                  key={id}
                  onClick={() => setRightTab(id)}
                  className={clsx(
                    'flex flex-1 items-center justify-center gap-1 py-2 text-xs font-medium transition-colors',
                    rightTab === id
                      ? 'border-b-2 border-oe-blue text-oe-blue'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Icon size={13} />
                  {t(labelKey, id)}
                  {count > 0 && (
                    <span className="text-[9px] tabular-nums opacity-60">({count})</span>
                  )}
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

                      {/* ── Polyline measurements ──────────────── */}
                      {selectedEntity.type === 'LWPOLYLINE' && selectedEntity.vertices && selectedEntity.vertices.length >= 2 && (() => {
                        const verts = selectedEntity.vertices!;
                        const closed = !!selectedEntity.closed;
                        const segLengths = getSegmentLengths(verts, closed);
                        const perimeter = calculatePerimeter(verts, closed);
                        const area = closed ? calculateArea(verts) : 0;
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
                                      {formatMeasurement(len, 'm')}
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

            {/* Upload button */}
            <button
              disabled={!uploadFile || uploadMutation.isPending}
              onClick={() => uploadMutation.mutate()}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-bold transition-all disabled:opacity-50 bg-oe-blue text-white hover:bg-oe-blue-dark active:scale-[0.98] shadow-md hover:shadow-lg"
            >
              {uploadMutation.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Upload size={16} />
              )}
              {uploadMutation.isPending
                ? t('dwg_takeoff.uploading', 'Uploading...')
                : t('dwg_takeoff.upload_and_process', 'Upload & Process')}
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
    </div>
  );
}

/* ── EntityInfoPopup + BOQPositionPicker removed ─────────────────────── */
/* Replaced by shared <ElementInfoPopover> from @/shared/ui             */

/* ── Bottom Drawing Filmstrip ────────────────────────────────────────── */

interface DrawingFilmstripProps {
  drawings: { id: string; name: string; discipline: string; entity_count: number }[];
  isLoading: boolean;
  activeDrawingId: string | null;
  entities: DxfEntity[];
  expanded: boolean;
  onToggleExpanded: () => void;
  onSelectDrawing: (id: string) => void;
  onDeleteDrawing: (id: string) => void;
  onUpload: () => void;
}

function DrawingFilmstrip({
  drawings,
  isLoading,
  activeDrawingId,
  entities,
  expanded,
  onToggleExpanded,
  onSelectDrawing,
  onDeleteDrawing,
  onUpload,
}: DrawingFilmstripProps) {
  const { t } = useTranslation();

  return (
    <div className="shrink-0 border-t border-[#2a2a2a] bg-[#2f2f2f] text-slate-200">
      {/* Header -- always visible */}
      <button
        type="button"
        onClick={onToggleExpanded}
        className="flex items-center w-full px-4 py-1.5 cursor-pointer group hover:bg-white/5 transition-colors"
      >
        <div className="flex flex-col items-center gap-[2px] mr-3 opacity-60 group-hover:opacity-90 transition-opacity">
          <div className="w-4 h-[2px] rounded-full bg-slate-400" />
          <div className="w-4 h-[2px] rounded-full bg-slate-400" />
        </div>
        <Layers size={14} className="text-slate-300 mr-2 shrink-0" />
        <span className="text-xs font-semibold text-slate-100">
          {t('dwg_takeoff.drawings', 'Drawings')}
        </span>
        <span className="text-[11px] text-slate-400 ml-1.5">({drawings.length})</span>
        <ChevronUp
          size={14}
          className={clsx(
            'ml-auto text-slate-300 transition-transform duration-200',
            expanded ? '' : 'rotate-180',
          )}
        />
      </button>

      {/* Collapsible drawing cards */}
      <div
        className="overflow-hidden transition-all duration-300 ease-in-out"
        style={{ maxHeight: expanded ? '100px' : '0px', opacity: expanded ? 1 : 0 }}
      >
        <div className="flex items-center gap-2 px-4 pb-2 overflow-x-auto">
          {isLoading ? (
            <Loader2 size={14} className="animate-spin text-slate-400" />
          ) : drawings.length > 0 ? (
            drawings.map((d) => (
              <button
                key={d.id}
                onClick={() => onSelectDrawing(d.id)}
                className={clsx(
                  'group relative shrink-0 w-44 text-start rounded-lg border transition-all duration-200 overflow-hidden',
                  activeDrawingId === d.id
                    ? 'border-blue-500/80 bg-blue-500/10 shadow-md shadow-blue-500/20'
                    : 'border-[#3a3a3a] bg-[#363636] hover:bg-[#3d3d3d] hover:border-[#4a4a4a]',
                )}
              >
                <div className="px-2.5 py-2">
                  <div className="flex items-center gap-1.5 mb-1">
                    <FileText size={12} className={clsx(
                      'shrink-0',
                      activeDrawingId === d.id ? 'text-blue-400' : 'text-slate-400',
                    )} />
                    <span className={clsx(
                      'text-[11px] font-semibold truncate',
                      activeDrawingId === d.id ? 'text-blue-300' : 'text-slate-100',
                    )}>
                      {d.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-slate-400">
                    <span className="capitalize">{d.discipline}</span>
                    <span>&middot;</span>
                    <span>
                      {activeDrawingId === d.id && entities.length > 0
                        ? entities.length
                        : d.entity_count || '--'}{' '}
                      {t('dwg_takeoff.entities', 'entities')}
                    </span>
                  </div>
                </div>
                {/* Delete button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteDrawing(d.id);
                  }}
                  className="absolute top-1 right-1 h-5 w-5 rounded flex items-center justify-center
                             text-transparent group-hover:text-slate-400 hover:!text-red-400 hover:bg-red-500/20
                             transition-all"
                >
                  <Trash2 size={11} />
                </button>
              </button>
            ))
          ) : (
            <span className="text-[11px] text-slate-400">
              {t('dwg_takeoff.no_drawings', 'No drawings uploaded yet')}
            </span>
          )}
          {/* Upload button */}
          <button
            onClick={onUpload}
            className="flex items-center justify-center shrink-0 w-14 h-14 rounded-lg border-2 border-dashed
                       border-[#4a4a4a] hover:border-blue-400/60 hover:bg-blue-500/10 transition-all group"
            title={t('dwg_takeoff.upload_drawing', 'Upload drawing')}
          >
            <Plus size={18} className="text-slate-400 group-hover:text-blue-300 transition-colors" />
          </button>
        </div>
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
