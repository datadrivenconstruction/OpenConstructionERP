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
import { Button, Badge, EmptyState, Breadcrumb, ConfirmDialog } from '@/shared/ui';
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
import { boqApi, type Position } from '@/features/boq/api';

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

/* ── Component ─────────────────────────────────────────────────────── */

export function DwgTakeoffPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  // Deep-link support: ?drawingId=xxx opens a specific drawing
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkDrawingId = searchParams.get('drawingId');

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

  // Deep-link: auto-select drawing when ?drawingId= is in URL
  useEffect(() => {
    if (!deepLinkDrawingId || drawings.length === 0) return;
    const target = drawings.find((d) => d.id === deepLinkDrawingId);
    if (target && selectedDrawingId !== deepLinkDrawingId) {
      handleSelectDrawing(deepLinkDrawingId);
      // Clean up the URL param
      const next = new URLSearchParams(searchParams);
      next.delete('drawingId');
      setSearchParams(next, { replace: true });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkDrawingId, drawings]);

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
  useMemo(() => {
    if (layouts.length > 0 && selectedLayout === null) {
      setSelectedLayout(layouts[0] ?? null);
    }
  }, [layouts]);

  // Filter entities by selected layout
  const filteredEntities = useMemo(() => {
    if (!selectedLayout || layouts.length === 0) return entities;
    return entities.filter((e) => e.layout === selectedLayout);
  }, [entities, selectedLayout, layouts]);

  // Computed layers (from filtered entities)
  const layers = useMemo(() => extractLayers(filteredEntities), [filteredEntities]);

  // Initialize visible layers when entities/layout change
  useMemo(() => {
    if (layers.length > 0) {
      setVisibleLayers(new Set(layers.map((l) => l.name)));
    }
  }, [layers]);

  // Initialize visible entity names when entities/layout change
  useMemo(() => {
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
      setShowUpload(false);
      setUploadFile(null);
      setUploadName('');
      setSelectedDrawingId(drawing.id);

      // Auto-save to Documents module as well (fire-and-forget)
      if (uploadFile && projectId) {
        const file = uploadFile;
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

  const breadcrumbs = [
    { label: t('nav.group_takeoff', 'Takeoff'), to: '/takeoff' },
    { label: t('dwg_takeoff.title', 'DWG Takeoff') },
  ];

  /* ── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="flex h-full flex-col -mx-4 sm:-mx-7 -my-4" style={{ height: 'calc(100vh - 3.5rem)' }}>
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
              {/* Floating entity info popup */}
              {selectedEntity && entityPopup && activeTool === 'select' && (
                <EntityInfoPopup
                  entity={selectedEntity}
                  screenX={entityPopup.x}
                  screenY={entityPopup.y}
                  projectId={projectId}
                  onClose={() => setEntityPopup(null)}
                  onLinkBOQ={() => {
                    setEntityPopup(null);
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
          <div className="flex w-64 flex-shrink-0 flex-col border-l border-white/10 bg-[#1a1a2e]/90 backdrop-blur-sm text-white/90">
            {/* Tab bar */}
            <div className="flex border-b border-border">
              {(
                [
                  { id: 'layers', icon: Layers, labelKey: 'dwg_takeoff.layers' },
                  { id: 'annotations', icon: MessageSquare, labelKey: 'dwg_takeoff.annotations' },
                  { id: 'properties', icon: Info, labelKey: 'dwg_takeoff.properties' },
                ] as const
              ).map(({ id, icon: Icon, labelKey }) => (
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
                                    className="flex items-center justify-between rounded px-2 py-1 bg-white/5 hover:bg-white/10 transition-colors"
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
          onClick={() => setShowUpload(false)}
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
                onClick={() => setShowUpload(false)}
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
                  setUploadFile(f);
                  if (!uploadName) setUploadName(f.name.replace(/\.[^.]+$/, ''));
                }
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
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
                    {t('dwg_takeoff.click_to_select', 'Click to select a file')}
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

/* ── Floating Entity Info Popup ──────────────────────────────────────── */

interface EntityInfoPopupProps {
  entity: DxfEntity;
  screenX: number;
  screenY: number;
  projectId: string;
  onClose: () => void;
  onLinkBOQ: () => void;
}

function EntityInfoPopup({ entity, screenX, screenY, projectId, onClose }: EntityInfoPopupProps) {
  const { t } = useTranslation();
  const popupRef = useRef<HTMLDivElement>(null);
  const [showBoqPicker, setShowBoqPicker] = useState(false);

  // Dismiss on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // Dismiss when clicking outside the popup
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    // Delay to avoid catching the click that opened the popup
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handler);
    }, 100);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handler);
    };
  }, [onClose]);

  // Compute measurements
  const isPolyline = entity.type === 'LWPOLYLINE' && entity.vertices && entity.vertices.length >= 2;
  const closed = !!entity.closed;
  const verts = entity.vertices ?? [];
  const perimeter = isPolyline ? calculatePerimeter(verts, closed) : 0;
  const area = isPolyline && closed ? calculateArea(verts) : 0;
  const segCount = isPolyline ? getSegmentLengths(verts, closed).length : 0;
  const isCircle = entity.type === 'CIRCLE' && entity.radius != null;
  const circleArea = isCircle ? Math.PI * (entity.radius! ** 2) : 0;
  const circleCircumference = isCircle ? 2 * Math.PI * entity.radius! : 0;

  // Copy measurements to clipboard
  const handleCopyMeasurements = useCallback(() => {
    const lines: string[] = [];
    lines.push(`Type: ${entity.type}`);
    lines.push(`Layer: ${entity.layer}`);
    if (isPolyline) {
      lines.push(`Perimeter: ${formatMeasurement(perimeter, 'm')}`);
      if (closed && area > 0) lines.push(`Area: ${formatMeasurement(area, 'm\u00B2')}`);
      lines.push(`Segments: ${segCount}`);
      lines.push(`Vertices: ${verts.length}`);
    }
    if (isCircle) {
      lines.push(`Radius: ${formatMeasurement(entity.radius!, 'm')}`);
      lines.push(`Circumference: ${formatMeasurement(circleCircumference, 'm')}`);
      lines.push(`Area: ${formatMeasurement(circleArea, 'm\u00B2')}`);
    }
    navigator.clipboard.writeText(lines.join('\n')).catch(() => {});
  }, [entity, isPolyline, isCircle, perimeter, area, segCount, verts.length, circleCircumference, circleArea, closed]);

  // Position popup near click point (offset right and down), clamp to viewport
  const popupW = 260;
  const popupH = 300;
  const parentEl = popupRef.current?.parentElement;
  const maxW = parentEl?.clientWidth ?? 800;
  const maxH = parentEl?.clientHeight ?? 600;
  let left = screenX + 16;
  let top = screenY + 16;
  if (left + popupW > maxW) left = screenX - popupW - 8;
  if (top + popupH > maxH) top = Math.max(8, maxH - popupH - 8);
  if (left < 8) left = 8;
  if (top < 8) top = 8;

  return (
    <div
      ref={popupRef}
      className="absolute z-40 animate-in fade-in slide-in-from-top-1 duration-150"
      style={{ left, top, width: popupW }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="rounded-xl border border-white/15 bg-[#1e1e38]/95 shadow-2xl backdrop-blur-md overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-white/10">
          <div className="flex items-center gap-2 min-w-0">
            <span className="h-2 w-2 rounded-full bg-oe-blue flex-shrink-0" />
            <span className="text-xs font-semibold text-white/90 truncate">
              {entity.type}
            </span>
            <span className="text-[10px] text-white/40 truncate">{entity.layer}</span>
          </div>
          <button
            onClick={onClose}
            className="flex h-5 w-5 items-center justify-center rounded-md
                       text-white/40 hover:text-white/80 hover:bg-white/10 transition-colors"
          >
            <X size={12} />
          </button>
        </div>

        {/* Properties grid */}
        <div className="px-3 py-2 space-y-1.5 text-[11px]">
          <div className="flex justify-between">
            <span className="text-white/40">{t('dwg_takeoff.prop_type', 'Type')}</span>
            <span className="font-mono text-white/80">{entity.type}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-white/40">{t('dwg_takeoff.prop_layer', 'Layer')}</span>
            <span className="font-mono text-white/80">{entity.layer}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-white/40">{t('dwg_takeoff.prop_color', 'Color')}</span>
            <div className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-full border border-white/20"
                style={{ backgroundColor: typeof entity.color === 'string' ? entity.color : `hsl(${(entity.color * 30) % 360}, 70%, 55%)` }}
              />
              <span className="font-mono text-white/80">{String(entity.color)}</span>
            </div>
          </div>
          {entity.block_name && (
            <div className="flex justify-between">
              <span className="text-white/40">{t('dwg_takeoff.prop_block', 'Block')}</span>
              <span className="font-mono text-white/80">{entity.block_name}</span>
            </div>
          )}
        </div>

        {/* Measurements section */}
        {(isPolyline || isCircle) && (
          <div className="px-3 py-2 border-t border-white/10 space-y-1.5">
            <div className="text-[10px] font-semibold text-white/50 uppercase tracking-wider">
              {t('dwg_takeoff.measurements', 'Measurements')}
            </div>
            {isPolyline && (
              <>
                <div className="flex items-center justify-between rounded-md bg-emerald-950/30 px-2 py-1 border border-emerald-800/40">
                  <span className="text-[11px] text-emerald-400 font-medium">
                    {t('dwg_takeoff.perimeter', 'Perimeter')}
                  </span>
                  <span className="font-mono font-bold text-[11px] text-emerald-300">
                    {formatMeasurement(perimeter, 'm')}
                  </span>
                </div>
                {closed && area > 0 && (
                  <div className="flex items-center justify-between rounded-md bg-blue-950/30 px-2 py-1 border border-blue-800/40">
                    <span className="text-[11px] text-blue-400 font-medium">
                      {t('dwg_takeoff.area', 'Area')}
                    </span>
                    <span className="font-mono font-bold text-[11px] text-blue-300">
                      {formatMeasurement(area, 'm\u00B2')}
                    </span>
                  </div>
                )}
                <div className="flex justify-between text-[11px]">
                  <span className="text-white/40">{t('dwg_takeoff.segments', 'Segments')}</span>
                  <span className="font-mono text-white/80">{segCount}</span>
                </div>
                <div className="flex justify-between text-[11px]">
                  <span className="text-white/40">{t('dwg_takeoff.closed', 'Closed')}</span>
                  <span className="font-mono text-white/80">
                    {closed ? t('common.yes', 'Yes') : t('common.no', 'No')}
                  </span>
                </div>
              </>
            )}
            {isCircle && (
              <>
                <div className="flex justify-between text-[11px]">
                  <span className="text-white/40">{t('dwg_takeoff.prop_radius', 'Radius')}</span>
                  <span className="font-mono text-white/80">
                    {formatMeasurement(entity.radius!, 'm')}
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-emerald-950/30 px-2 py-1 border border-emerald-800/40">
                  <span className="text-[11px] text-emerald-400 font-medium">
                    {t('dwg_takeoff.circumference', 'Circumference')}
                  </span>
                  <span className="font-mono font-bold text-[11px] text-emerald-300">
                    {formatMeasurement(circleCircumference, 'm')}
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-blue-950/30 px-2 py-1 border border-blue-800/40">
                  <span className="text-[11px] text-blue-400 font-medium">
                    {t('dwg_takeoff.area', 'Area')}
                  </span>
                  <span className="font-mono font-bold text-[11px] text-blue-300">
                    {formatMeasurement(circleArea, 'm\u00B2')}
                  </span>
                </div>
              </>
            )}
          </div>
        )}

        {/* Action buttons */}
        <div className="px-3 py-2 border-t border-white/10 flex flex-wrap gap-1.5">
          <button
            onClick={handleCopyMeasurements}
            className="flex-1 flex items-center justify-center gap-1.5 rounded-lg border border-white/15 bg-white/5
                       px-2 py-1.5 text-[11px] font-medium text-white/70 hover:text-white hover:bg-white/10 transition-colors"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            {t('dwg_takeoff.copy_measurements', 'Copy')}
          </button>
          <button
            onClick={() => setShowBoqPicker((v) => !v)}
            className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-oe-blue/20 border border-oe-blue/30
                       px-2 py-1.5 text-[11px] font-medium text-oe-blue hover:bg-oe-blue/30 transition-colors"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            </svg>
            {t('dwg_takeoff.link_to_boq', 'Link to BOQ')}
          </button>
        </div>

        {/* Inline BOQ position picker */}
        {showBoqPicker && (
          <BOQPositionPicker
            projectId={projectId}
            onClose={() => setShowBoqPicker(false)}
          />
        )}
      </div>
    </div>
  );
}

/* ── BOQ Position Picker (inline in entity popup) ───────────────────── */

function BOQPositionPicker({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const addToast = useToastStore((s) => s.addToast);

  const { data: boqs = [], isLoading } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => boqApi.list(projectId),
    enabled: !!projectId,
  });

  // Load positions for all BOQs
  const { data: allPositions = [] } = useQuery({
    queryKey: ['boq-positions-for-picker', projectId, boqs.map((b) => b.id).join(',')],
    queryFn: async () => {
      const results: (Position & { boq_name: string })[] = [];
      for (const boq of boqs) {
        try {
          const full = await boqApi.get(boq.id);
          for (const pos of full.positions) {
            results.push({ ...pos, boq_name: boq.name });
          }
        } catch {
          // skip
        }
      }
      return results;
    },
    enabled: boqs.length > 0,
  });

  const filtered = useMemo(() => {
    if (!search.trim()) return allPositions.slice(0, 20);
    const q = search.toLowerCase();
    return allPositions
      .filter(
        (p) =>
          p.description.toLowerCase().includes(q) ||
          p.ordinal.toLowerCase().includes(q) ||
          p.boq_name.toLowerCase().includes(q),
      )
      .slice(0, 20);
  }, [allPositions, search]);

  const handleSelect = useCallback(
    (pos: Position & { boq_name: string }) => {
      addToast({
        type: 'info',
        title: t('dwg_takeoff.boq_link_info', 'BOQ link'),
        message: t('dwg_takeoff.boq_link_info_desc', 'Position "{{desc}}" selected. Use annotations to formally link measurements.', {
          desc: pos.description.slice(0, 40),
        }),
      });
      onClose();
    },
    [addToast, t, onClose],
  );

  return (
    <div className="border-t border-white/10 px-3 py-2 space-y-2 max-h-52 overflow-y-auto">
      <div className="text-[10px] font-semibold text-white/50 uppercase tracking-wider">
        {t('dwg_takeoff.select_boq_position', 'Select BOQ position')}
      </div>
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={t('dwg_takeoff.search_positions', 'Search positions...')}
        className="w-full rounded-md border border-white/15 bg-white/5 px-2 py-1 text-[11px] text-white
                   placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-oe-blue/50"
        autoFocus
      />
      {isLoading ? (
        <div className="flex items-center justify-center py-3">
          <Loader2 size={14} className="animate-spin text-white/30" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-[11px] text-white/30 text-center py-2">
          {t('dwg_takeoff.no_positions_found', 'No positions found')}
        </div>
      ) : (
        <div className="space-y-0.5">
          {filtered.map((pos) => (
            <button
              key={pos.id}
              onClick={() => handleSelect(pos)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left
                         hover:bg-white/10 transition-colors group"
            >
              <span className="font-mono text-[10px] text-white/40 shrink-0 w-14 truncate">
                {pos.ordinal}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] text-white/80 truncate">{pos.description}</div>
                <div className="text-[10px] text-white/30 truncate">{pos.boq_name}</div>
              </div>
              <span className="text-[10px] text-white/30 shrink-0">
                {pos.quantity} {pos.unit}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

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
    <div className="shrink-0 border-t border-white/10 bg-[#1a1a2e]/90 backdrop-blur-sm">
      {/* Header -- always visible */}
      <button
        type="button"
        onClick={onToggleExpanded}
        className="flex items-center w-full px-4 py-1.5 cursor-pointer group hover:bg-white/5 transition-colors"
      >
        <div className="flex flex-col items-center gap-[2px] mr-3 opacity-50 group-hover:opacity-80 transition-opacity">
          <div className="w-4 h-[2px] rounded-full bg-white/40" />
          <div className="w-4 h-[2px] rounded-full bg-white/40" />
        </div>
        <Layers size={14} className="text-white/50 mr-2 shrink-0" />
        <span className="text-xs font-semibold text-white/80">
          {t('dwg_takeoff.drawings', 'Drawings')}
        </span>
        <span className="text-[11px] text-white/40 ml-1.5">({drawings.length})</span>
        <ChevronUp
          size={14}
          className={clsx(
            'ml-auto text-white/40 transition-transform duration-200',
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
            <Loader2 size={14} className="animate-spin text-white/30" />
          ) : drawings.length > 0 ? (
            drawings.map((d) => (
              <button
                key={d.id}
                onClick={() => onSelectDrawing(d.id)}
                className={clsx(
                  'group relative shrink-0 w-44 text-start rounded-lg border-2 transition-all duration-200 overflow-hidden',
                  activeDrawingId === d.id
                    ? 'border-oe-blue bg-oe-blue/10 shadow-lg shadow-oe-blue/10'
                    : 'border-transparent bg-white/5 hover:bg-white/10 hover:border-white/15',
                )}
              >
                <div className="px-2.5 py-2">
                  <div className="flex items-center gap-1.5 mb-1">
                    <FileText size={12} className={clsx(
                      'shrink-0',
                      activeDrawingId === d.id ? 'text-oe-blue' : 'text-white/40',
                    )} />
                    <span className={clsx(
                      'text-[11px] font-semibold truncate',
                      activeDrawingId === d.id ? 'text-oe-blue' : 'text-white/80',
                    )}>
                      {d.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-white/40">
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
                             text-white/0 group-hover:text-white/40 hover:!text-red-400 hover:bg-red-500/10
                             transition-all"
                >
                  <Trash2 size={11} />
                </button>
              </button>
            ))
          ) : (
            <span className="text-[11px] text-white/30">
              {t('dwg_takeoff.no_drawings', 'No drawings uploaded yet')}
            </span>
          )}
          {/* Upload button */}
          <button
            onClick={onUpload}
            className="flex items-center justify-center shrink-0 w-14 h-14 rounded-lg border-2 border-dashed
                       border-white/15 hover:border-oe-blue/50 hover:bg-oe-blue/5 transition-all group"
            title={t('dwg_takeoff.upload_drawing', 'Upload drawing')}
          >
            <Plus size={18} className="text-white/30 group-hover:text-oe-blue transition-colors" />
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
