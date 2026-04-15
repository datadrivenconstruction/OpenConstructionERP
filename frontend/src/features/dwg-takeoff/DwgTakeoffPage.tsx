/**
 * DWG Takeoff page — upload DWG/DXF drawings, view entities in a Canvas2D
 * renderer, toggle layers, and create measurement annotations.
 *
 * Layout:
 *  - Left panel: drawing list + upload
 *  - Center: DXF canvas viewer (or empty state)
 *  - Right panel: layers, annotations, selected entity properties
 *  - Top toolbar: annotation tool palette
 */

import { useState, useMemo, useCallback, useRef } from 'react';
import {
  calculateArea,
  calculatePerimeter,
  getSegmentLengths,
  formatMeasurement,
} from './lib/measurement';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
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
} from 'lucide-react';
import { Button, Badge, EmptyState, Breadcrumb, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
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
import { DxfViewer } from './components/DxfViewer';
import { ToolPalette, type DwgTool } from './components/ToolPalette';
import { LayerPanel } from './components/LayerPanel';
import { EntityNameFilter, entityDisplayName } from './components/EntityNameFilter';

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

  const handleSelectEntity = useCallback((id: string | null) => {
    setSelectedEntityId(id);
    if (id) {
      // Auto-switch to properties tab when an entity is selected
      setRightTab('properties');
    }
  }, []);

  const handleSelectDrawing = useCallback((id: string) => {
    setSelectedDrawingId(id);
    setVisibleLayers(new Set());
    setVisibleNames(new Set());
    setSelectedEntityId(null);
    setSelectedAnnotationId(null);
    setSelectedLayout(null);
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
        {/* ── Left Panel: Drawing List ──────────────────────────────── */}
        <div className="flex w-60 flex-shrink-0 flex-col border-r border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <h3 className="text-sm font-semibold text-foreground">
              {t('dwg_takeoff.drawings', 'Drawings')}
            </h3>
            <Button size="sm" variant="ghost" onClick={() => setShowUpload(true)}>
              <Plus size={14} />
            </Button>
          </div>

          {/* Upload form */}
          {showUpload && (
            <div className="border-b border-border p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-foreground">
                  {t('dwg_takeoff.upload_drawing', 'Upload drawing')}
                </span>
                <button onClick={() => setShowUpload(false)}>
                  <X size={14} className="text-muted-foreground" />
                </button>
              </div>
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
              <Button
                size="sm"
                variant="secondary"
                className="w-full justify-center"
                onClick={() => fileInputRef.current?.click()}
              >
                <FileUp size={14} className="mr-1" />
                {uploadFile ? uploadFile.name : t('dwg_takeoff.choose_file', 'Choose file')}
              </Button>
              <input
                type="text"
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
                placeholder={t('dwg_takeoff.drawing_name', 'Drawing name')}
                className="w-full rounded-md border border-border bg-surface-secondary px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-oe-blue"
              />
              <select
                value={uploadDiscipline}
                onChange={(e) => setUploadDiscipline(e.target.value)}
                className="w-full rounded-md border border-border bg-surface-secondary px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-oe-blue"
              >
                <option value="architectural">{t('dwg_takeoff.discipline_arch', 'Architectural')}</option>
                <option value="structural">{t('dwg_takeoff.discipline_struct', 'Structural')}</option>
                <option value="mep">{t('dwg_takeoff.discipline_mep', 'MEP')}</option>
                <option value="civil">{t('dwg_takeoff.discipline_civil', 'Civil')}</option>
                <option value="other">{t('dwg_takeoff.discipline_other', 'Other')}</option>
              </select>
              <Button
                size="sm"
                variant="primary"
                className="w-full justify-center"
                disabled={!uploadFile || uploadMutation.isPending}
                onClick={() => uploadMutation.mutate()}
              >
                {uploadMutation.isPending ? (
                  <Loader2 size={14} className="mr-1 animate-spin" />
                ) : (
                  <Upload size={14} className="mr-1" />
                )}
                {t('dwg_takeoff.upload', 'Upload')}
              </Button>
            </div>
          )}

          {/* Drawing list */}
          <div className="flex-1 overflow-y-auto">
            {loadingDrawings && (
              <div className="flex items-center justify-center py-8">
                <Loader2 size={20} className="animate-spin text-muted-foreground" />
              </div>
            )}
            {!loadingDrawings && drawings.length === 0 && (
              <div className="px-3 py-8 text-center text-xs text-muted-foreground">
                {t('dwg_takeoff.no_drawings', 'No drawings uploaded yet')}
              </div>
            )}
            {drawings.map((d) => (
              <button
                key={d.id}
                onClick={() => handleSelectDrawing(d.id)}
                className={clsx(
                  'flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left text-xs transition-colors',
                  selectedDrawingId === d.id
                    ? 'bg-oe-blue/10 text-oe-blue'
                    : 'text-foreground hover:bg-surface-secondary',
                )}
              >
                <FileText size={14} className="flex-shrink-0" />
                <div className="flex-1 truncate">
                  <div className="truncate font-medium">{d.name}</div>
                  <div className="text-muted-foreground">
                    {d.discipline} &middot;{' '}
                    {selectedDrawingId === d.id && entities.length > 0
                      ? entities.length
                      : d.entity_count || '—'}{' '}
                    {t('dwg_takeoff.entities', 'entities')}
                  </div>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDeleteId(d.id);
                  }}
                  className="text-muted-foreground hover:text-red-500 transition-colors"
                >
                  <Trash2 size={13} />
                </button>
              </button>
            ))}
          </div>
        </div>

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
            </>
          )}
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

/* ── Tiny sub-components ─────────────────────────────────────────────── */

function PropertyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-foreground">{value}</span>
    </div>
  );
}
