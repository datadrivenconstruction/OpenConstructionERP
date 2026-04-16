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
} from 'lucide-react';
import { Button, Badge, EmptyState, Breadcrumb, ConfirmDialog, ElementInfoPopover, type DWGElementPayload } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchDrawings,
  uploadDrawing,
  deleteDrawing,
  fetchEntities,
  fetchAnnotations,
  createAnnotation,
  deleteAnnotation,
} from './api';
import type { DxfEntity, DxfLayer, DwgAnnotation, CreateAnnotationPayload } from './api';
import { DxfViewer, type EntitySelectEvent } from './components/DxfViewer';
import { ToolPalette, type DwgTool } from './components/ToolPalette';
import { LayerPanel } from './components/LayerPanel';
import { EntityNameFilter, entityDisplayName } from './components/EntityNameFilter';
// boqApi / Position import removed — BOQ picker now handled via ElementInfoPopover callback

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
      if (!selectedDrawingId) return;
      createAnnotationMutation.mutate({
        drawing_id: selectedDrawingId,
        type: ann.type,
        points: ann.points,
        text: ann.text,
        color: ann.color ?? activeColor,
        measurement_value: ann.measurement_value,
        measurement_unit: ann.measurement_unit,
        metadata: ann.fontSize ? { font_size: ann.fontSize } : undefined,
      });
    },
    [selectedDrawingId, activeColor, createAnnotationMutation],
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

  const breadcrumbs = [
    { label: t('nav.group_takeoff', 'Takeoff'), to: '/takeoff' },
    { label: t('dwg_takeoff.title', 'DWG Takeoff') },
  ];

  /* ── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col -mx-4 sm:-mx-7 -mt-6 -mb-4 overflow-hidden" style={{ height: 'calc(100vh - 56px)' }}>
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <Breadcrumb items={breadcrumbs} />
        <div className="flex items-center gap-2">
          {selectedDrawingId && (
            <ToolPalette
              activeTool={activeTool}
              onToolChange={setActiveTool}
              activeColor={activeColor}
              onColorChange={setActiveColor}
            />
          )}
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Center: DXF Viewer ──────────────────────────────────── */}
        <div className="flex flex-1 flex-col min-h-0 min-w-0">
          {!selectedDrawingId ? (
            <div className="flex flex-1 items-center justify-center">
              <EmptyState
                icon={<Layers size={40} className="text-muted-foreground" />}
                title={t('dwg_takeoff.empty_title', 'No drawing selected')}
                description={t(
                  'dwg_takeoff.empty_desc',
                  'Upload a DWG/DXF file or select a drawing from the list to start takeoff.',
                )}
                action={
                  <Button variant="primary" onClick={() => setShowUpload(true)}>
                    <Upload size={14} className="mr-1" />
                    {t('dwg_takeoff.upload_drawing', 'Upload drawing')}
                  </Button>
                }
              />
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
                  onLinkToBOQ={() => {
                    /* Close the popover and switch to the properties tab so the user
                       can see full entity details and use the right-panel BOQ actions. */
                    setEntityPopup(null);
                    setRightTab('properties');
                  }}
                />
              )}
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
          <div className="flex w-64 flex-shrink-0 flex-col border-l border-border-light bg-surface-primary text-content-primary">
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
    <div className="shrink-0 border-t border-border-light bg-surface-primary">
      {/* Header -- always visible */}
      <button
        type="button"
        onClick={onToggleExpanded}
        className="flex items-center w-full px-4 py-1.5 cursor-pointer group hover:bg-surface-secondary transition-colors"
      >
        <div className="flex flex-col items-center gap-[2px] mr-3 opacity-50 group-hover:opacity-80 transition-opacity">
          <div className="w-4 h-[2px] rounded-full bg-content-tertiary" />
          <div className="w-4 h-[2px] rounded-full bg-content-tertiary" />
        </div>
        <Layers size={14} className="text-content-tertiary mr-2 shrink-0" />
        <span className="text-xs font-semibold text-content-primary">
          {t('dwg_takeoff.drawings', 'Drawings')}
        </span>
        <span className="text-[11px] text-content-quaternary ml-1.5">({drawings.length})</span>
        <ChevronUp
          size={14}
          className={clsx(
            'ml-auto text-content-tertiary transition-transform duration-200',
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
            <Loader2 size={14} className="animate-spin text-content-quaternary" />
          ) : drawings.length > 0 ? (
            drawings.map((d) => (
              <button
                key={d.id}
                onClick={() => onSelectDrawing(d.id)}
                className={clsx(
                  'group relative shrink-0 w-44 text-start rounded-lg border transition-all duration-200 overflow-hidden',
                  activeDrawingId === d.id
                    ? 'border-oe-blue bg-oe-blue/5 shadow-md shadow-oe-blue/10'
                    : 'border-border-light bg-surface-secondary hover:bg-surface-tertiary hover:border-border',
                )}
              >
                <div className="px-2.5 py-2">
                  <div className="flex items-center gap-1.5 mb-1">
                    <FileText size={12} className={clsx(
                      'shrink-0',
                      activeDrawingId === d.id ? 'text-oe-blue' : 'text-content-tertiary',
                    )} />
                    <span className={clsx(
                      'text-[11px] font-semibold truncate',
                      activeDrawingId === d.id ? 'text-oe-blue' : 'text-content-primary',
                    )}>
                      {d.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-content-quaternary">
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
                             text-transparent group-hover:text-content-quaternary hover:!text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30
                             transition-all"
                >
                  <Trash2 size={11} />
                </button>
              </button>
            ))
          ) : (
            <span className="text-[11px] text-content-quaternary">
              {t('dwg_takeoff.no_drawings', 'No drawings uploaded yet')}
            </span>
          )}
          {/* Upload button */}
          <button
            onClick={onUpload}
            className="flex items-center justify-center shrink-0 w-14 h-14 rounded-lg border-2 border-dashed
                       border-border-light hover:border-oe-blue/50 hover:bg-oe-blue/5 transition-all group"
            title={t('dwg_takeoff.upload_drawing', 'Upload drawing')}
          >
            <Plus size={18} className="text-content-quaternary group-hover:text-oe-blue transition-colors" />
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
